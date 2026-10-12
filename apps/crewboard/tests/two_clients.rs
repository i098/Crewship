//! Two clients talk through a real `crewboard serve` on a socket in a temp dir:
//! pub/sub, history with `--since` and the gap marker, the caps, and a restart.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdout, Command, Output, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use serde_json::Value;

const BIN: &str = env!("CARGO_BIN_EXE_crewboard");

/// Kills the child process when the test ends, pass or fail.
struct Proc(Child);

impl Drop for Proc {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn cmd(sock: &Path, dir: &Path, args: &[&str]) -> Command {
    let mut c = Command::new(BIN);
    // Never the real runtime dir: both variables point into the temp dir.
    c.args(args).env("CREWBOARD_SOCKET", sock).env("XDG_RUNTIME_DIR", dir).env_remove("FM_TASK_ID");
    c
}

fn run(sock: &Path, dir: &Path, args: &[&str]) -> Output {
    cmd(sock, dir, args).output().unwrap()
}

fn stdout(o: &Output) -> String {
    assert!(o.status.success(), "{o:?}");
    String::from_utf8(o.stdout.clone()).unwrap()
}

fn stat(sock: &Path, dir: &Path) -> Value {
    serde_json::from_str(&stdout(&run(sock, dir, &["stat"]))).unwrap()
}

fn serve(sock: &Path, dir: &Path) -> Proc {
    let args = ["serve", "--socket", sock.to_str().unwrap(), "--history", "3", "--cap-bytes", "1500", "--max-msg", "300"];
    let daemon = Proc(cmd(sock, dir, &args).stderr(Stdio::null()).spawn().unwrap());
    let start = Instant::now();
    while !run(sock, dir, &["stat"]).status.success() {
        assert!(start.elapsed() < Duration::from_secs(10), "daemon did not start");
        std::thread::sleep(Duration::from_millis(20));
    }
    daemon
}

/// A subscriber whose stdout lines arrive on a channel, so reads can time out.
fn sub(sock: &Path, dir: &Path, args: &[&str]) -> (Proc, mpsc::Receiver<String>) {
    let mut child = cmd(sock, dir, args).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().unwrap();
    let out: ChildStdout = child.stdout.take().unwrap();
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        for line in BufReader::new(out).lines().map_while(Result::ok) {
            if tx.send(line).is_err() {
                break;
            }
        }
    });
    (Proc(child), rx)
}

fn recv(rx: &mpsc::Receiver<String>) -> Value {
    serde_json::from_str(&rx.recv_timeout(Duration::from_secs(10)).expect("no message")).unwrap()
}

#[test]
fn two_clients_history_caps_and_restart() {
    let dir: PathBuf = std::env::temp_dir().join(format!("crewboard-test-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let sock = dir.join("crewboard.sock");
    let (sock, dir) = (sock.as_path(), dir.as_path());

    // No daemon: every client exits 3 with "board off".
    let o = run(sock, dir, &["stat"]);
    assert_eq!(o.status.code(), Some(3));
    assert_eq!(String::from_utf8_lossy(&o.stderr).trim(), "crewboard: board off");

    let mut daemon = serve(sock, dir);
    assert_eq!(std::fs::metadata(sock).unwrap().permissions().mode() & 0o777, 0o600);

    // Client A subscribes; client B publishes as an argument and from stdin.
    let (mut a, a_rx) = sub(sock, dir, &["sub", "task/a", "fleet", "--since", "0", "--json"]);
    let hello = recv(&a_rx);
    assert_eq!((hello["boot"].is_string(), &hello["seq"]), (true, &0.into()));
    let o = cmd(sock, dir, &["pub", "task/a", "hello"]).env("FM_TASK_ID", "b").output().unwrap();
    assert_eq!(stdout(&o).trim(), "1");
    let mut b = cmd(sock, dir, &["pub", "fleet"]).stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
    b.stdin.take().unwrap().write_all(b"from stdin\n").unwrap();
    assert_eq!(stdout(&b.wait_with_output().unwrap()).trim(), "2");
    let m = recv(&a_rx);
    assert_eq!((&m["seq"], &m["topic"], &m["from"], &m["body"]), (&1.into(), &"task/a".into(), &"b".into(), &"hello".into()));
    assert!(m["pid"].as_u64().unwrap() > 0);
    assert_eq!(recv(&a_rx)["body"], "from stdin");

    // History keeps 3 per topic: seq 1 and 3 leave task/a.
    for body in ["3", "4", "5"] {
        stdout(&run(sock, dir, &["pub", "task/a", body]));
    }
    for want in [3, 4, 5] {
        assert_eq!(recv(&a_rx)["seq"], want);
    }
    assert_eq!(stdout(&run(sock, dir, &["tail", "task/a", "-n", "2"])).lines().map(|l| &l[..1]).collect::<Vec<_>>(), ["4", "5"]);
    let (_late, late_rx) = sub(sock, dir, &["sub", "task/a", "--since", "0", "--json"]);
    assert!(recv(&late_rx)["boot"].is_string());
    assert_eq!(recv(&late_rx), serde_json::json!({"gap": true, "oldest": 3}));
    for want in [3, 4, 5] {
        assert_eq!(recv(&late_rx)["seq"], want);
    }
    let (_caught_up, rx) = sub(sock, dir, &["sub", "task/*", "--since", "3", "--json"]);
    assert!(recv(&rx)["boot"].is_string());
    assert_eq!(recv(&rx)["seq"], 4);

    // Message size limit, then the global cap evicts the oldest messages first.
    let o = run(sock, dir, &["pub", "fleet", &"x".repeat(301)]);
    assert_eq!((o.status.code(), String::from_utf8_lossy(&o.stderr).trim()), (Some(1), "crewboard: too_large"));
    for i in 0..10 {
        stdout(&run(sock, dir, &["pub", &format!("bulk/{i}"), &"x".repeat(250)]));
    }
    let s = stat(sock, dir);
    assert!(s["bytes"].as_u64().unwrap() <= 1500, "{s}");
    assert_eq!(stdout(&run(sock, dir, &["tail", "task/a"])), "");
    assert_eq!(stdout(&run(sock, dir, &["tail", "bulk/9"])).lines().count(), 1);

    // Restart: subscribers see the board go off; the new daemon starts empty with a new boot id.
    let boot = s["boot"].clone();
    daemon.0.kill().unwrap();
    daemon.0.wait().unwrap();
    assert_eq!(a.0.wait().unwrap().code(), Some(3));
    assert_eq!(run(sock, dir, &["stat"]).status.code(), Some(3));
    let restarted = serve(sock, dir);
    let s = stat(sock, dir);
    assert_ne!(s["boot"], boot);
    assert_eq!((&s["seq"], &s["topics"], &s["bytes"]), (&0.into(), &0.into(), &0.into()));
    assert_eq!(stdout(&run(sock, dir, &["pub", "task/a", "after restart"])).trim(), "1");

    // A subscriber that saw seq 3 on the old board reconnects after the new board passed seq 3:
    // the old boot id tells the two boards apart, so it gets a restart gap, not a false continuation.
    for body in ["2", "3", "4", "5"] {
        stdout(&run(sock, dir, &["pub", "task/a", body]));
    }
    let old_boot = boot.as_str().unwrap();
    let (_again, again_rx) = sub(sock, dir, &["sub", "task/a", "--since", "3", "--boot", old_boot, "--json"]);
    let hello = recv(&again_rx);
    assert_eq!((hello["boot"].is_string(), hello["boot"] == boot, &hello["seq"]), (true, false, &5.into()));
    assert_eq!(recv(&again_rx), serde_json::json!({"gap": true, "oldest": 3, "restarted": true}));
    for want in [3, 4, 5] {
        assert_eq!(recv(&again_rx)["seq"], want);
    }

    drop(restarted);
    std::fs::remove_dir_all(dir).unwrap();
}

/// A daemon with room for a full subscriber queue of big lines, plus a subscriber on every topic.
fn big_line_board(tag: &str) -> (PathBuf, Proc, std::os::unix::net::UnixStream) {
    use std::os::unix::net::UnixStream;

    let dir: PathBuf = std::env::temp_dir().join(format!("crewboard-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let sock = dir.join("crewboard.sock");
    let args = ["serve", "--socket", sock.to_str().unwrap(), "--cap-bytes", "8000000"];
    let daemon = Proc(cmd(&sock, &dir, &args).stderr(Stdio::null()).spawn().unwrap());
    let start = Instant::now();
    while !run(&sock, &dir, &["stat"]).status.success() {
        assert!(start.elapsed() < Duration::from_secs(10), "daemon did not start");
        std::thread::sleep(Duration::from_millis(20));
    }
    let mut sub = UnixStream::connect(&sock).unwrap();
    sub.write_all(b"{\"op\":\"sub\",\"topics\":[\"*\"]}\n").unwrap();
    while stat(&sock, &dir)["subs"] != 1 {
        std::thread::sleep(Duration::from_millis(20));
    }
    (dir, daemon, sub)
}

/// Publishes 60 KB lines until the board has dropped every subscriber.
fn publish_until_dropped(sock: &Path, dir: &Path) -> usize {
    use std::os::unix::net::UnixStream;

    let mut publisher = UnixStream::connect(sock).unwrap();
    let mut replies = BufReader::new(publisher.try_clone().unwrap());
    let body = "x".repeat(60_000);
    let deadline = Instant::now() + Duration::from_secs(120);
    for i in 1.. {
        assert!(Instant::now() < deadline, "subscriber was never dropped");
        writeln!(publisher, "{{\"op\":\"pub\",\"topic\":\"t\",\"body\":\"{body}\"}}").unwrap();
        let mut reply = String::new();
        replies.read_line(&mut reply).unwrap();
        assert!(reply.contains("\"ok\":true"), "{reply}");
        if i % 25 == 0 && stat(sock, dir)["subs"] == 0 {
            assert!(stat(sock, dir)["dropped"].as_u64().unwrap() >= 1);
            return i * body.len();
        }
    }
    unreachable!()
}

/// Reads to EOF and returns the bytes received; a connection left open fails the test.
fn read_to_close(s: &mut std::os::unix::net::UnixStream, pause: Duration) -> Vec<u8> {
    use std::io::Read;

    s.set_read_timeout(Some(Duration::from_secs(20))).unwrap();
    let mut all = Vec::new();
    let mut buf = vec![0u8; 1 << 13];
    loop {
        match s.read(&mut buf) {
            Ok(0) => return all,
            Ok(n) => all.extend_from_slice(&buf[..n]),
            Err(e) if e.kind() == std::io::ErrorKind::ConnectionReset => return all,
            Err(e) => panic!("connection still open: {e}"),
        }
        std::thread::sleep(pause);
    }
}

/// A subscriber that never reads is dropped and its connection closed, not kept with its queue.
#[test]
fn stalled_subscriber_is_closed() {
    let (dir, _daemon, mut stalled) = big_line_board("stall");
    let sock = dir.join("crewboard.sock");
    publish_until_dropped(&sock, &dir);

    // Do not read until the write timeout has closed the connection, so nothing drains the backlog.
    std::thread::sleep(Duration::from_secs(7));
    let total = read_to_close(&mut stalled, Duration::ZERO).len();
    // Only what the kernel buffered before the stall arrives, not the ~60 MB queue.
    assert!(total < 8 << 20, "{total} bytes delivered");
    std::fs::remove_dir_all(&dir).unwrap();
}

/// A subscriber that reads, but slower than the board publishes, is cut off when its queue fills.
#[test]
fn slow_reader_is_cut_off_without_its_backlog() {
    let (dir, _daemon, mut slow) = big_line_board("slow");
    let sock = dir.join("crewboard.sock");
    // 8 KB every 5 ms never stalls a write for the 5 s timeout, yet needs ~40 s for the 60 MB queue.
    let reader = std::thread::spawn(move || read_to_close(&mut slow, Duration::from_millis(5)));
    let published = publish_until_dropped(&sock, &dir);
    let got = reader.join().unwrap();
    // The reader gets what it read while the queue filled, never the ~60 MB left queued at the drop.
    assert!(got.len() + 30_000_000 < published, "{} of {published} bytes delivered", got.len());
    // The stream stops on a whole line; the slow notice is best effort, as the socket may have no room.
    let text = String::from_utf8(got).unwrap();
    assert!(text.ends_with('\n'));
    let lines: Vec<Value> = text.lines().map(|l| serde_json::from_str(l).unwrap()).collect();
    assert!(lines[0]["boot"].is_string());
    assert!(lines[1..].iter().all(|l| l["body"].is_string() || l["error"] == "slow"));
    std::fs::remove_dir_all(&dir).unwrap();
}

/// `pub` text may start with a dash, and `from` is capped like a topic name.
#[test]
fn pub_text_with_dash_and_long_from() {
    let dir: PathBuf = std::env::temp_dir().join(format!("crewboard-dash-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let sock = dir.join("crewboard.sock");
    let (sock, dir) = (sock.as_path(), dir.as_path());
    let _daemon = serve(sock, dir);

    for text in ["- done", "--force retry", "-1 failing"] {
        stdout(&run(sock, dir, &["pub", "task/a", text]));
    }
    let tail = stdout(&run(sock, dir, &["tail", "task/a", "--json"]));
    let bodies: Vec<String> = tail.lines().map(|l| serde_json::from_str::<Value>(l).unwrap()["body"].as_str().unwrap().to_owned()).collect();
    assert_eq!(bodies, ["- done", "--force retry", "-1 failing"]);
    stdout(&run(sock, dir, &["pub", "task/a", "--", "- two", "words"]));
    stdout(&run(sock, dir, &["pub", "task/a", "hello", "world"]));
    let tail = stdout(&run(sock, dir, &["tail", "-n", "2", "task/a", "--json"]));
    let bodies: Vec<String> = tail.lines().map(|l| serde_json::from_str::<Value>(l).unwrap()["body"].as_str().unwrap().to_owned()).collect();
    assert_eq!(bodies, ["- two words", "hello world"]);
    assert_eq!(stdout(&run(sock, dir, &["tail", "-n", "1", "--", "task/a"])).lines().count(), 1);

    let o = cmd(sock, dir, &["pub", "task/a", "x"]).env("FM_TASK_ID", "f".repeat(65)).output().unwrap();
    assert_eq!((o.status.code(), String::from_utf8_lossy(&o.stderr).trim()), (Some(1), "crewboard: too_large"));
    let o = cmd(sock, dir, &["pub", "task/a", "x"]).env("FM_TASK_ID", "f".repeat(64)).output().unwrap();
    assert!(o.status.success(), "{o:?}");
    std::fs::remove_dir_all(dir).unwrap();
}
