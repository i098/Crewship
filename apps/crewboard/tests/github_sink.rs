//! `crewboard github-sink` against a real daemon and a fake `gh`: the sink posts the messages
//! of its topic as one comment when the daemon goes away, and exits 3 like the other clients.

use std::io::{BufRead, BufReader};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
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

fn cmd(sock: &Path, args: &[&str]) -> Command {
    let mut c = Command::new(BIN);
    c.args(args).env("CREWBOARD_SOCKET", sock).env_remove("FM_TASK_ID");
    c
}

fn wait_for(what: &str, mut ready: impl FnMut() -> bool) {
    let start = Instant::now();
    while !ready() {
        assert!(start.elapsed() < Duration::from_secs(10), "timed out: {what}");
        std::thread::sleep(Duration::from_millis(20));
    }
}

fn stat(sock: &Path) -> Option<Value> {
    let out = cmd(sock, &["stat"]).output().ok().filter(|o| o.status.success())?;
    serde_json::from_slice(&out.stdout).ok()
}

#[test]
fn posts_the_topic_messages_as_one_comment_when_the_board_goes_away() {
    let dir: PathBuf = std::env::temp_dir().join(format!("crewboard-sink-test-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::DirBuilder::new().mode(0o700).create(&dir).unwrap();
    let sock = dir.join("crewboard.sock");
    let (args_file, body_file, gh) = (dir.join("args"), dir.join("body"), dir.join("gh"));
    std::fs::write(&gh, format!("#!/bin/sh\necho \"$@\" >> {}\ncat > {}\n", args_file.display(), body_file.display())).unwrap();
    std::fs::set_permissions(&gh, std::fs::Permissions::from_mode(0o755)).unwrap();

    let daemon = Proc(cmd(&sock, &["serve"]).stderr(Stdio::null()).spawn().unwrap());
    wait_for("daemon", || stat(&sock).is_some());
    let mut sink = Proc(
        cmd(&sock, &["github-sink", "--repo", "o/r", "--issue", "7"])
            .env("CREWBOARD_GH", &gh)
            .stderr(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    wait_for("sink subscription", || stat(&sock).is_some_and(|s| s["subs"] == 1));

    // A second subscriber tells us when the daemon has fanned the message out.
    let mut watcher = Proc(cmd(&sock, &["sub", "fleet", "--json"]).stdout(Stdio::piped()).spawn().unwrap());
    let mut out = BufReader::new(watcher.0.stdout.take().unwrap());
    let mut line = String::new();
    out.read_line(&mut line).unwrap(); // the boot line
    for (topic, text) in [("other", "not for the sink"), ("fleet", "main is green @octocat")] {
        assert!(cmd(&sock, &["pub", topic, text]).status().unwrap().success());
    }
    out.read_line(&mut line).unwrap();
    std::thread::sleep(Duration::from_millis(200));
    drop(daemon);

    let status = sink.0.wait().unwrap();
    assert_eq!(status.code(), Some(3), "{status:?}");
    assert_eq!(std::fs::read_to_string(&args_file).unwrap(), "api --method POST repos/o/r/issues/7/comments --input -\n");
    let body: Value = serde_json::from_slice(&std::fs::read(&body_file).unwrap()).unwrap();
    let text = body["body"].as_str().unwrap();
    assert!(text.starts_with("crewboard: 1 message\n\n```text\n"), "{text}");
    assert!(text.contains("fleet: main is green @octocat\n```"), "{text}");
    assert!(!text.contains("not for the sink"), "{text}");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn rejects_a_bad_repo_or_interval_with_usage() {
    let sock = Path::new("/nonexistent/crewboard.sock");
    for args in [
        &["github-sink", "--issue", "7"][..],
        &["github-sink", "--repo", "a/..", "--issue", "7"],
        &["github-sink", "--repo", "o/r", "--issue", "7", "--interval", "59"],
    ] {
        let out = cmd(sock, args).output().unwrap();
        assert_eq!(out.status.code(), Some(2), "{args:?}");
    }
}
