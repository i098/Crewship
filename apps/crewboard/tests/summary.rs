//! Topic summaries against a real daemon: `summary` stores a line, `topics --summary` prints it,
//! and `summarize` refreshes it through a model command after new messages.

use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{Value, json};

const BIN: &str = env!("CARGO_BIN_EXE_crewboard");

/// Kills the child process when the test ends, pass or fail.
struct Proc(Child);

impl Drop for Proc {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn cmd(sock: &Path, args: &[&str]) -> Command {
    let mut c = Command::new(BIN);
    c.args(args).env("CREWBOARD_SOCKET", sock).env_remove("FM_TASK_ID");
    c
}

fn run(sock: &Path, args: &[&str]) -> std::process::Output {
    cmd(sock, args).output().unwrap()
}

fn topics(sock: &Path) -> Value {
    let out = run(sock, &["topics", "--summary", "--json"]);
    assert!(out.status.success());
    serde_json::from_slice(&out.stdout).unwrap()
}

fn wait_for(what: &str, mut ready: impl FnMut() -> bool) {
    let start = Instant::now();
    while !ready() {
        assert!(start.elapsed() < Duration::from_secs(10), "timed out: {what}");
        std::thread::sleep(Duration::from_millis(20));
    }
}

struct Rig {
    dir: PathBuf,
    sock: PathBuf,
    _daemon: Proc,
}

impl Rig {
    fn start(name: &str) -> Rig {
        let dir = std::env::temp_dir().join(format!("crewboard-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
        let sock = dir.join("crewboard.sock");
        let daemon = Proc(cmd(&sock, &["serve"]).stderr(Stdio::null()).spawn().unwrap());
        wait_for("daemon", || run(&sock, &["stat"]).status.success());
        Rig { dir, sock, _daemon: daemon }
    }
}

impl Drop for Rig {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

#[test]
fn stores_a_summary_and_lists_it_only_on_request() {
    let rig = Rig::start("summary-store");
    let s = &rig.sock;
    assert!(run(s, &["pub", "t", "one"]).status.success());
    assert!(run(s, &["pub", "t", "two"]).status.success());

    let plain: Value = serde_json::from_slice(&run(s, &["topics"]).stdout).unwrap();
    assert_eq!(plain, json!([{"topic": "t", "count": 2, "oldest": 1, "newest": 2}]));
    assert_eq!(topics(s)[0]["summary"], json!(""));
    assert_eq!(topics(s)[0]["summary_seq"], json!(0));

    assert!(run(s, &["summary", "t", "a", "b"]).status.success());
    let t = &topics(s)[0];
    assert_eq!((t["summary"].as_str(), t["summary_seq"].as_u64()), (Some("a b"), Some(2)));
    let text = String::from_utf8(run(s, &["topics", "--summary"]).stdout).unwrap();
    assert_eq!(text, "t (2): a b\n");

    assert!(run(s, &["summary", "t", "x", "--seq", "1"]).status.code() == Some(1), "an older seq is stale");
    assert_eq!(topics(s)[0]["summary"], json!("a b"));
    assert_eq!(run(s, &["summary", "nope", "x"]).status.code(), Some(1));
}

#[test]
fn summarize_refreshes_a_topic_after_new_messages() {
    let rig = Rig::start("summary-refresh");
    let s = &rig.sock;
    let model = rig.dir.join("model");
    // The fake model reads the prompt and answers with the number of message lines it was given.
    std::fs::write(&model, "#!/bin/sh\nn=$(grep -c '^me: ')\necho \"$n messages\"\n").unwrap();
    std::fs::set_permissions(&model, std::fs::Permissions::from_mode(0o755)).unwrap();

    // One topic exists before the summarizer starts: it must be picked up without a new message.
    assert!(cmd(s, &["pub", "old", "hi"]).env("FM_TASK_ID", "me").status().unwrap().success());
    let _summarizer =
        Proc(cmd(s, &["summarize", "--quiet", "1", "--max-wait", "5"]).env("CREWBOARD_SUMMARY_CMD", &model).stderr(Stdio::null()).spawn().unwrap());
    let summary_of = |topic: &str| topics(s).as_array().unwrap().iter().find(|t| t["topic"] == topic).map(|t| (t["summary"].clone(), t["summary_seq"].clone()));
    wait_for("summary of the old topic", || summary_of("old") == Some((json!("1 messages"), json!(1))));

    for _ in 0..3 {
        assert!(cmd(s, &["pub", "new", "hello"]).env("FM_TASK_ID", "me").status().unwrap().success());
    }
    wait_for("summary of the new topic", || summary_of("new") == Some((json!("3 messages"), json!(4))));
}
