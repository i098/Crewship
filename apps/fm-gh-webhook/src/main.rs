//! GitHub webhook receiver (docs/github-webhook.md).
//!
//! Listens on 127.0.0.1:GH_WEBHOOK_PORT (default 8788); the host's public Tailscale
//! funnel forwards POST /gh-webhook here. A post counts only when its
//! X-Hub-Signature-256 is the HMAC-SHA256 of the raw body under GH_WEBHOOK_SECRET.
//! The secret comes from the environment (the unit reads ~/super.env) and is never
//! logged. Without it the program exits 78 and the unit stays down.
//!
//! Events land under GH_WEBHOOK_DIR (default ~/.local/state/crewship/gh-webhook),
//! one small file each, written atomically, for the Firstmate merged-PR poll:
//!   merged/<owner>__<repo>__<number>  empty; pull_request closed with merged true
//!   ci/<owner>__<repo>__<sha>/<event>-<id>-<hex name>
//!                                     conclusion of each completed check_suite (app slug),
//!                                     check_run or workflow_run (name); names over 80 bytes are skipped

use hmac::{Hmac, Mac};
use serde_json::Value;
use sha2::Sha256;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;
use std::{env, fs, process, thread};

const MAX_BODY: usize = 1 << 20;
const MAX_HEAD: usize = 16 << 10;
const MAX_CONNECTIONS: usize = 32;

static OPEN: AtomicUsize = AtomicUsize::new(0);

fn verify(secret: &[u8], body: &[u8], header: &str) -> bool {
    let Some(sig) = header.strip_prefix("sha256=").and_then(unhex) else {
        return false;
    };
    let mut mac = Hmac::<Sha256>::new_from_slice(secret).expect("hmac takes any key length");
    mac.update(body);
    mac.verify_slice(&sig).is_ok()
}

fn unhex(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 || !s.is_ascii() {
        return None;
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).ok())
        .collect()
}

fn owner_ok(s: &str) -> bool {
    let b = s.as_bytes();
    (1..=39).contains(&b.len())
        && b.iter().all(|c| c.is_ascii_alphanumeric() || *c == b'-')
        && b[0] != b'-'
        && b[b.len() - 1] != b'-'
        && !s.contains("--")
}

fn repo_ok(s: &str) -> bool {
    (1..=100).contains(&s.len())
        && s != "."
        && s != ".."
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
}

static TMP_SEQ: AtomicUsize = AtomicUsize::new(0);

fn write(path: &Path, text: &str) -> std::io::Result<()> {
    fs::create_dir_all(path.parent().expect("event paths have a parent"))?;
    let mut name = path
        .file_name()
        .expect("event paths have a name")
        .to_os_string();
    name.push(format!(
        ".{}.{}.tmp",
        process::id(),
        TMP_SEQ.fetch_add(1, Ordering::Relaxed)
    ));
    let tmp = path.with_file_name(name);
    fs::write(&tmp, text)?;
    fs::rename(tmp, path)
}

fn merged_marker(payload: &Value) -> Option<String> {
    let pr = &payload["pull_request"];
    let merged = payload["action"] == "closed" && pr["merged"] == Value::Bool(true);
    let n = pr["number"].as_u64().filter(|n| *n > 0)?;
    merged.then(|| format!("merged/{{}}__{{}}__{n}"))
}

fn check_name(payload: &Value, event: &str) -> Option<String> {
    let obj = &payload[event];
    let raw = match event {
        "check_suite" => obj["app"]["slug"].as_str()?,
        _ => obj["name"].as_str()?,
    };
    (1..=80)
        .contains(&raw.len())
        .then(|| raw.bytes().map(|b| format!("{b:02x}")).collect())
}

fn ci_marker(payload: &Value, event: &str) -> Option<(String, String)> {
    let obj = &payload[event];
    let sha = obj["head_sha"].as_str()?;
    let conclusion = obj["conclusion"].as_str()?;
    let name = check_name(payload, event)?;
    let id = obj["id"].as_u64()?;
    let sha_ok = sha.len() == 40
        && sha
            .bytes()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase());
    let word_ok = (1..=32).contains(&conclusion.len())
        && conclusion
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c == b'_');
    (payload["action"] == "completed" && sha_ok && word_ok).then(|| {
        (
            format!("ci/{{}}__{{}}__{sha}/{event}-{id}-{name}"),
            format!("{conclusion}\n"),
        )
    })
}

/// Store what the watcher reads. 204 stored, 202 valid but not of interest, 500 write failed.
fn record(root: &Path, event: &str, payload: &Value) -> u16 {
    let full = payload["repository"]["full_name"].as_str().unwrap_or("");
    let Some((owner, repo)) = full.split_once('/') else {
        return 202;
    };
    if !owner_ok(owner) || !repo_ok(repo) {
        return 202;
    }
    let stored = match event {
        "pull_request" => merged_marker(payload).map(|p| (p, String::new())),
        "check_suite" | "check_run" | "workflow_run" => ci_marker(payload, event),
        _ => None,
    };
    let Some((template, text)) = stored else {
        return 202;
    };
    let path = root.join(template.replacen("{}", owner, 1).replacen("{}", repo, 1));
    if write(&path, &text).is_ok() {
        204
    } else {
        500
    }
}

fn handle(secret: &[u8], root: &Path, event: &str, sig: &str, body: &[u8]) -> u16 {
    if !verify(secret, body, sig) {
        return 401;
    }
    match serde_json::from_slice::<Value>(body) {
        Ok(v) if v.is_object() => record(root, event, &v),
        _ => 400,
    }
}

/// Read from the stream until `done` accepts the buffer; Err is the status to send.
fn fill(
    stream: &mut TcpStream,
    buf: &mut Vec<u8>,
    done: impl Fn(&[u8]) -> bool,
    cap: usize,
) -> Result<(), u16> {
    let mut chunk = [0u8; 4096];
    while !done(buf) {
        if buf.len() > cap {
            return Err(431);
        }
        match stream.read(&mut chunk) {
            Ok(0) | Err(_) => return Err(400),
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
        }
    }
    Ok(())
}

/// The three headers that matter: (content-length, signature, event).
fn parse_head(head: &str) -> Result<(usize, String, String), u16> {
    let mut lines = head.split("\r\n");
    if lines.next() != Some("POST /gh-webhook HTTP/1.1") {
        return Err(404);
    }
    let (mut len, mut sig, mut event) = (None, String::new(), String::new());
    for (k, v) in lines.filter_map(|l| l.split_once(':')) {
        let v = v.trim();
        match k.to_ascii_lowercase().as_str() {
            "content-length" => len = v.parse::<usize>().ok(),
            "x-hub-signature-256" => sig = v.into(),
            "x-github-event" => event = v.into(),
            _ => {}
        }
    }
    match len {
        None => Err(411),
        Some(n) if n > MAX_BODY => Err(413),
        Some(n) => Ok((n, sig, event)),
    }
}

fn read_request(stream: &mut TcpStream) -> Result<(String, String, Vec<u8>), u16> {
    let mut buf = Vec::new();
    fill(
        stream,
        &mut buf,
        |b| b.windows(4).any(|w| w == b"\r\n\r\n"),
        MAX_HEAD,
    )?;
    let head_end = buf
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .map_or(0, |i| i + 4);
    let (len, sig, event) = parse_head(&String::from_utf8_lossy(&buf[..head_end]))?;
    let mut body = buf.split_off(head_end);
    fill(stream, &mut body, |b| b.len() >= len, MAX_BODY)?;
    body.truncate(len);
    Ok((event, sig, body))
}

/// Read one request and return the status to send.
fn serve(stream: &mut TcpStream, secret: &[u8], root: &Path) -> u16 {
    match read_request(stream) {
        Ok((event, sig, body)) => handle(secret, root, &event, &sig, &body),
        Err(code) => code,
    }
}

fn main() {
    let secret = env::var("GH_WEBHOOK_SECRET").unwrap_or_default();
    if secret.is_empty() {
        eprintln!("fm-gh-webhook: GH_WEBHOOK_SECRET is not set; add it to ~/super.env");
        process::exit(78);
    }
    let root = env::var_os("GH_WEBHOOK_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env::var_os("HOME").unwrap_or_default())
                .join(".local/state/crewship/gh-webhook")
        });
    let port = env::var("GH_WEBHOOK_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8788u16);
    let listener = TcpListener::bind(("127.0.0.1", port)).unwrap_or_else(|e| {
        eprintln!("fm-gh-webhook: cannot listen on 127.0.0.1:{port}: {e}");
        process::exit(1);
    });
    for stream in listener.incoming().flatten() {
        if OPEN.fetch_add(1, Ordering::SeqCst) >= MAX_CONNECTIONS {
            OPEN.fetch_sub(1, Ordering::SeqCst);
            continue;
        }
        let (secret, root) = (secret.clone().into_bytes(), root.clone());
        thread::spawn(move || {
            let mut stream = stream;
            let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
            let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
            let code = serve(&mut stream, &secret, &root);
            let _ = write!(
                stream,
                "HTTP/1.1 {code} \r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            );
            OPEN.fetch_sub(1, Ordering::SeqCst);
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SECRET: &[u8] = b"s3cret-for-tests";
    const SHA: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    fn sign(secret: &[u8], body: &[u8]) -> String {
        let mut mac = Hmac::<Sha256>::new_from_slice(secret).unwrap();
        mac.update(body);
        let hex: String = mac
            .finalize()
            .into_bytes()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        format!("sha256={hex}")
    }

    fn post(root: &Path, event: &str, body: &str, secret: &[u8]) -> u16 {
        handle(
            SECRET,
            root,
            event,
            &sign(secret, body.as_bytes()),
            body.as_bytes(),
        )
    }

    fn merged(n: u32, merged: bool) -> String {
        format!(
            r#"{{"action":"closed","repository":{{"full_name":"o/r"}},"pull_request":{{"number":{n},"merged":{merged}}}}}"#
        )
    }

    #[test]
    fn signed_merge_writes_marker_and_unmerged_close_does_not() {
        let d = tempdir("merge");
        assert_eq!(post(&d, "pull_request", &merged(7, true), SECRET), 204);
        assert!(d.join("merged/o__r__7").exists());
        assert_eq!(post(&d, "pull_request", &merged(8, false), SECRET), 202);
        assert!(!d.join("merged/o__r__8").exists());
    }

    #[test]
    fn bad_or_malformed_signature_stores_nothing() {
        let d = tempdir("badsig");
        let body = merged(9, true);
        assert_eq!(post(&d, "pull_request", &body, b"wrong"), 401);
        for sig in [
            "",
            "sha256=",
            "sha256=zz",
            "md5=00",
            &sign(SECRET, b"other"),
        ] {
            assert_eq!(
                handle(SECRET, &d, "pull_request", sig, body.as_bytes()),
                401,
                "{sig}"
            );
        }
        assert!(!d.join("merged").exists());
    }

    #[test]
    fn signed_non_json_is_400() {
        assert_eq!(post(&tempdir("json"), "ping", "not json", SECRET), 400);
    }

    #[test]
    fn ci_records_are_per_check_so_later_success_keeps_earlier_failure() {
        let d = tempdir("ci");
        let run = |event: &str, id: u32, name: &str, conclusion: &str| {
            let key = if event == "check_suite" {
                r#""app":{"slug":"NAME"}"#
            } else {
                r#""name":"NAME""#
            };
            let key = key.replace("NAME", name);
            format!(
                r#"{{"action":"completed","repository":{{"full_name":"o/r"}},"{event}":{{"id":{id},"head_sha":"{SHA}","conclusion":"{conclusion}",{key}}}}}"#
            )
        };
        for (event, id, name, conclusion) in [
            ("workflow_run", 1, "test", "failure"),
            ("check_run", 2, "test", "success"),
            ("check_run", 3, "test", "success"),
            ("check_run", 4, "build (x)", "failure"),
            ("check_run", 5, "build [x]", "success"),
        ] {
            assert_eq!(
                post(&d, event, &run(event, id, name, conclusion), SECRET),
                204
            );
        }
        let dir = d.join(format!("ci/o__r__{SHA}"));
        let read = |f: &str| fs::read_to_string(dir.join(f)).unwrap();
        assert_eq!(read("workflow_run-1-74657374"), "failure\n");
        assert_eq!(read("check_run-2-74657374"), "success\n");
        assert_eq!(read("check_run-3-74657374"), "success\n");
        assert_eq!(read("check_run-4-6275696c6420287829"), "failure\n");
        assert_eq!(read("check_run-5-6275696c64205b785d"), "success\n");
        assert_eq!(fs::read_dir(&dir).unwrap().count(), 5);
        let pending = run("check_run", 2, "test", "failure").replace("completed", "requested");
        assert_eq!(post(&d, "check_run", &pending, SECRET), 202);
    }

    #[test]
    fn traversal_in_repo_name_is_refused() {
        let d = tempdir("trav");
        let body = merged(1, true).replace("o/r", "o/../../x");
        assert_eq!(post(&d, "pull_request", &body, SECRET), 202);
        assert!(!d.join("merged").exists());
    }

    #[test]
    fn full_request_over_a_socket() {
        let d = tempdir("sock");
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let root = d.clone();
        let server = thread::spawn(move || {
            let (mut s, _) = listener.accept().unwrap();
            serve(&mut s, SECRET, &root)
        });
        let body = merged(5, true);
        let req = format!(
            "POST /gh-webhook HTTP/1.1\r\nHost: x\r\nX-GitHub-Event: pull_request\r\nX-Hub-Signature-256: {}\r\nContent-Length: {}\r\n\r\n{body}",
            sign(SECRET, body.as_bytes()),
            body.len()
        );
        TcpStream::connect(addr)
            .unwrap()
            .write_all(req.as_bytes())
            .unwrap();
        assert_eq!(server.join().unwrap(), 204);
        assert!(d.join("merged/o__r__5").exists());
    }

    fn tempdir(name: &str) -> PathBuf {
        let d = env::temp_dir().join(format!("fm-gh-webhook-{}-{name}", process::id()));
        let _ = fs::remove_dir_all(&d);
        d
    }
}
