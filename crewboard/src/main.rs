//! crewboard: a host-local, in-memory message board for agents.
//! One binary: the daemon (`serve`) and its clients (`pub`, `sub`, `tail`, `topics`, `stat`).

mod board;
mod serve;

use std::ffi::OsString;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::exit;
use std::str::FromStr;

use serde_json::{Value, json};

const USAGE: &str = "usage:
  crewboard pub <topic> [text|-]          publish; reads stdin when text is - or absent
  crewboard sub <topic>... [--since N [--boot ID]] [--json]
                                          stream messages; a trailing * matches a prefix.
                                          The first line is {\"boot\":ID,\"seq\":N} (stderr unless --json);
                                          pass the last boot ID and seq back on reconnect: a different
                                          boot replays all history after a gap marker with restarted:true
  crewboard tail <topic> [-n 50] [--json] print history, then exit
  crewboard topics                        list topics with counts
  crewboard stat                          print caps, usage and the boot id
  crewboard serve [--socket PATH] [--cap-bytes 67108864] [--history 256] [--max-msg 65536]

The socket is $CREWBOARD_SOCKET, else $XDG_RUNTIME_DIR/crewboard.sock, else /run/user/<uid>/crewboard.sock.
Clients exit 3 with \"board off\" when no daemon answers on it.";

fn usage() -> ! {
    eprintln!("{USAGE}");
    exit(2)
}

fn fail(msg: &str) -> ! {
    eprintln!("crewboard: {msg}");
    exit(1)
}

fn off() -> ! {
    eprintln!("crewboard: board off");
    exit(3)
}

/// Positional arguments, `--flag value` options from `allowed`, and `--json`.
#[derive(Default)]
struct Args<'a> {
    pos: Vec<&'a str>,
    opts: Vec<(&'a str, &'a str)>,
    json: bool,
}

impl<'a> Args<'a> {
    fn parse(args: &'a [String], allowed: &[&str]) -> Self {
        let mut a = Args::default();
        let mut it = args.iter().map(String::as_str);
        while let Some(arg) = it.next() {
            match arg {
                "--" => a.pos.extend(it.by_ref()),
                "--json" => a.json = true,
                f if allowed.contains(&f) => a.opts.push((f, it.next().unwrap_or_else(|| usage()))),
                f if f.starts_with('-') && f != "-" => usage(),
                p => a.pos.push(p),
            }
        }
        a
    }

    fn opt<T: FromStr>(&self, name: &str) -> Option<T> {
        let (_, v) = self.opts.iter().rev().find(|(f, _)| *f == name)?;
        Some(v.parse().unwrap_or_else(|_| usage()))
    }
}

/// The socket path: `$CREWBOARD_SOCKET`, else `$XDG_RUNTIME_DIR/crewboard.sock`, else
/// `/run/user/<uid>/crewboard.sock`. Empty variables count as unset. Daemon and clients share it.
fn socket_path() -> PathBuf {
    let var = |k| std::env::var_os(k).filter(|v| !v.is_empty());
    resolve_socket(var("CREWBOARD_SOCKET"), var("XDG_RUNTIME_DIR"), unsafe { libc::getuid() })
}

fn resolve_socket(explicit: Option<OsString>, runtime_dir: Option<OsString>, uid: u32) -> PathBuf {
    explicit.map(PathBuf::from).unwrap_or_else(|| {
        runtime_dir.map_or_else(|| PathBuf::from(format!("/run/user/{uid}")), PathBuf::from).join("crewboard.sock")
    })
}

/// Sends one request and returns the reply stream.
fn request(req: Value) -> BufReader<UnixStream> {
    let path = socket_path();
    let mut s = match UnixStream::connect(&path) {
        Ok(s) => s,
        Err(e) if matches!(e.kind(), io::ErrorKind::NotFound | io::ErrorKind::ConnectionRefused) => off(),
        Err(e) => fail(&format!("{}: {e}", path.display())),
    };
    writeln!(s, "{req}").unwrap_or_else(|e| fail(&e.to_string()));
    BufReader::new(s)
}

/// The next reply line, raw and parsed. A closed stream means the daemon is gone.
fn next(r: &mut impl BufRead) -> (String, Value) {
    let mut line = String::new();
    match r.read_line(&mut line) {
        Ok(0) => off(),
        Ok(_) => {}
        Err(e) => fail(&e.to_string()),
    }
    let v: Value = serde_json::from_str(&line).unwrap_or_else(|e| fail(&format!("bad reply: {e}")));
    if let Some(e) = v["error"].as_str() {
        fail(e);
    }
    line.truncate(line.trim_end().len());
    (line, v)
}

fn print_msg(raw: &str, m: &Value, json: bool) {
    if json {
        println!("{raw}");
    } else {
        let s = |k: &str| m[k].as_str().unwrap_or("-").to_owned();
        println!("{} {} {} {}: {}", m["seq"], s("ts"), s("from"), s("topic"), s("body"));
    }
}

fn serve(rest: &[String]) {
    let a = Args::parse(rest, &["--socket", "--cap-bytes", "--history", "--max-msg"]);
    if !a.pos.is_empty() {
        usage();
    }
    let d = board::Limits::default();
    let limits = board::Limits {
        cap_bytes: a.opt("--cap-bytes").unwrap_or(d.cap_bytes),
        history: a.opt("--history").unwrap_or(d.history),
        max_msg: a.opt("--max-msg").unwrap_or(d.max_msg),
    };
    let path = a.opt("--socket").unwrap_or_else(socket_path);
    serve::run(&path, limits).unwrap_or_else(|e| fail(&e.to_string()));
}

fn publish(rest: &[String]) {
    let [topic, words @ ..] = rest else { usage() };
    let words = words.strip_prefix(&["--".to_owned()]).unwrap_or(words);
    let text = if words.is_empty() { "-".to_owned() } else { words.join(" ") };
    let (topic, text) = (topic.as_str(), text.as_str());
    let body = if text == "-" {
        let mut s = String::new();
        io::stdin().read_to_string(&mut s).unwrap_or_else(|e| fail(&e.to_string()));
        s.strip_suffix('\n').map(String::from).unwrap_or(s)
    } else {
        text.to_owned()
    };
    let from = std::env::var("FM_TASK_ID").ok();
    let (_, v) = next(&mut request(json!({"op": "pub", "topic": topic, "body": body, "from": from})));
    println!("{}", v["seq"]);
}

fn subscribe(rest: &[String]) {
    let a = Args::parse(rest, &["--since", "--boot"]);
    let (since, boot) = (a.opt::<u64>("--since"), a.opt::<String>("--boot"));
    if a.pos.is_empty() || (boot.is_some() && since.is_none()) {
        usage();
    }
    let mut r = request(json!({"op": "sub", "topics": a.pos, "since": since, "boot": boot}));
    loop {
        let (raw, v) = next(&mut r);
        if v["boot"].is_string() {
            if a.json {
                println!("{raw}");
            } else {
                eprintln!("crewboard: boot {} seq {}", v["boot"].as_str().unwrap_or("-"), v["seq"]);
            }
        } else if v["gap"] == true && !a.json {
            let why = if v["restarted"] == true { "the board restarted; its history starts at" } else { "messages before" };
            eprintln!("crewboard: gap: {why} seq {} are gone", v["oldest"]);
        } else {
            print_msg(&raw, &v, a.json);
        }
    }
}

fn tail(rest: &[String]) {
    let a = Args::parse(rest, &["-n"]);
    let [topic] = a.pos[..] else { usage() };
    let mut r = request(json!({"op": "hist", "topic": topic, "n": a.opt::<u64>("-n").unwrap_or(50)}));
    loop {
        let (raw, v) = next(&mut r);
        if v["end"] == true {
            break;
        }
        print_msg(&raw, &v, a.json);
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some((cmd, rest)) = args.split_first() else { usage() };
    match cmd.as_str() {
        "serve" => serve(rest),
        "pub" => publish(rest),
        "sub" => subscribe(rest),
        "tail" => tail(rest),
        "topics" | "stat" if rest.is_empty() => println!("{}", next(&mut request(json!({"op": cmd}))).0),
        "-h" | "--help" | "help" => println!("{USAGE}"),
        _ => usage(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn path(explicit: Option<&str>, xdg: Option<&str>) -> PathBuf {
        resolve_socket(explicit.map(Into::into), xdg.map(Into::into), 1234)
    }

    #[test]
    fn default_override_and_missing_runtime_dir() {
        assert_eq!(path(None, Some("/run/x")), PathBuf::from("/run/x/crewboard.sock"));
        assert_eq!(path(Some("/tmp/a.sock"), Some("/run/x")), PathBuf::from("/tmp/a.sock"));
        assert_eq!(path(None, None), PathBuf::from("/run/user/1234/crewboard.sock"));
    }
}
