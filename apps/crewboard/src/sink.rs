//! `crewboard github-sink`: subscribe to topics and post the messages to one GitHub issue.
//!
//! One REST call per interval, only when messages arrived. The call is `gh api`, so the host's
//! gh login is used and no token is stored. A failed call or a gone daemon ends the sink after
//! the last post attempt; the systemd unit (or the operator) starts it again.

use std::collections::VecDeque;
use std::io::{BufRead, Write};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::{Duration, Instant};

use serde_json::{Value, json};

/// GitHub rejects a comment above 65536 characters; stay well under it.
const MAX_COMMENT: usize = 60_000;
/// One message line is cut here, so any single line fits a comment.
const MAX_LINE: usize = 2_000;
/// Messages held between two posts. Older ones count as omitted.
const MAX_PENDING: usize = 500;

pub enum Stop {
    /// The daemon closed the stream.
    Off,
    Fail(String),
}

/// `owner/repo`: exactly one slash, only characters GitHub allows in a name.
pub fn valid_repo(repo: &str) -> bool {
    let ok = |s: &str| s.bytes().all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-')) && s.bytes().any(|b| b != b'.');
    repo.split_once('/').is_some_and(|(owner, name)| ok(owner) && ok(name))
}

fn line(m: &Value) -> String {
    let s = |k: &str| m[k].as_str().unwrap_or("-");
    format!("{} {} {}: {}", s("ts"), s("from"), s("topic"), s("body")).chars().take(MAX_LINE).collect()
}

/// A comment for `lines`, oldest first. The lines sit in a code fence, so `@name` and `#12`
/// in a message notify and link nobody. `omitted` counts the messages dropped before `lines`.
fn comment(lines: &VecDeque<String>, omitted: usize) -> String {
    let fence_len = lines.iter().map(|l| longest_run(l, '`')).max().unwrap_or(0).max(2) + 1;
    let fence = "`".repeat(fence_len);
    let (mut kept, mut size) = (0, 0);
    for l in lines.iter().rev() {
        if size + l.len() + 1 > MAX_COMMENT {
            break;
        }
        size += l.len() + 1;
        kept += 1;
    }
    let omitted = omitted + lines.len() - kept;
    let mut out = format!("crewboard: {kept} message{}", if kept == 1 { "" } else { "s" });
    if omitted > 0 {
        out += &format!(", {omitted} older omitted");
    }
    out += &format!("\n\n{fence}text\n");
    for l in lines.iter().skip(lines.len() - kept) {
        out += l;
        out.push('\n');
    }
    out + &fence
}

fn longest_run(s: &str, c: char) -> usize {
    s.split(|x| x != c).map(str::len).max().unwrap_or(0)
}

/// Posts `body` as a comment on `repo` issue `issue` with `gh api`. `$CREWBOARD_GH` names another binary.
pub fn gh_post(repo: &str, issue: u64, body: &str) -> Result<(), String> {
    let gh = std::env::var("CREWBOARD_GH").unwrap_or_else(|_| "gh".into());
    let mut child = Command::new(&gh)
        .args(["api", "--method", "POST", &format!("repos/{repo}/issues/{issue}/comments"), "--input", "-"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("{gh}: {e}"))?;
    let payload = json!({ "body": body }).to_string();
    child.stdin.take().expect("piped").write_all(payload.as_bytes()).map_err(|e| format!("{gh}: {e}"))?;
    let out = child.wait_with_output().map_err(|e| format!("{gh}: {e}"))?;
    if out.status.success() {
        Ok(())
    } else {
        Err(format!("{gh} api failed: {}", String::from_utf8_lossy(&out.stderr).trim()))
    }
}

/// Parses the stream into `tx`: one formatted line per message, or the daemon's error, which ends it.
fn read(stream: impl BufRead, tx: mpsc::Sender<Result<String, String>>) {
    for raw in stream.lines().map_while(Result::ok) {
        let Ok(v) = serde_json::from_str::<Value>(&raw) else { continue };
        // Boot and gap lines have no body; only messages do.
        let msg = match (v["error"].as_str(), v["body"].is_string()) {
            (Some(e), _) => Err(e.to_owned()),
            (None, true) => Ok(line(&v)),
            _ => continue,
        };
        let last = msg.is_err();
        if tx.send(msg).is_err() || last {
            return;
        }
    }
}

/// Messages waiting for the next post.
#[derive(Default)]
struct Batch {
    pending: VecDeque<String>,
    omitted: usize,
}

impl Batch {
    fn push(&mut self, l: String) {
        if self.pending.len() == MAX_PENDING {
            self.pending.pop_front();
            self.omitted += 1;
        }
        self.pending.push_back(l);
    }

    /// Posts the waiting messages, if any. They stay waiting when the post fails.
    fn flush(&mut self, post: &mut impl FnMut(&str) -> Result<(), String>) -> Result<(), String> {
        if !self.pending.is_empty() {
            post(&comment(&self.pending, self.omitted))?;
            *self = Batch::default();
        }
        Ok(())
    }

    /// A last post, then `stop`; a failed last post wins.
    fn finish(&mut self, post: &mut impl FnMut(&str) -> Result<(), String>, stop: Stop) -> Stop {
        self.flush(post).map_or_else(Stop::Fail, |()| stop)
    }
}

/// Reads the subscription stream from `stream`, and calls `post` with one comment body each
/// `interval` that had messages. Returns when the stream ends, reports an error, or a post fails.
pub fn run(stream: impl BufRead + Send + 'static, interval: Duration, mut post: impl FnMut(&str) -> Result<(), String>) -> Stop {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || read(stream, tx));
    let (mut batch, mut due) = (Batch::default(), Instant::now() + interval);
    loop {
        match rx.recv_timeout(due.saturating_duration_since(Instant::now())) {
            Ok(Ok(l)) => batch.push(l),
            Ok(Err(e)) => return batch.finish(&mut post, Stop::Fail(e)),
            Err(RecvTimeoutError::Timeout) => {
                if let Err(e) = batch.flush(&mut post) {
                    return Stop::Fail(e);
                }
                due = Instant::now() + interval;
            }
            Err(RecvTimeoutError::Disconnected) => return batch.finish(&mut post, Stop::Off),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lines(items: &[&str]) -> VecDeque<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn repo_names() {
        assert!(valid_repo("i098/board.v2_x-y"));
        for bad in ["", "board", "a/b/c", "/b", "a/", "a/..", "../b", "a/../b", "a b/c", "a/b?x=1"] {
            assert!(!valid_repo(bad), "{bad}");
        }
    }

    #[test]
    fn comment_fences_a_message_that_holds_backticks() {
        let c = comment(&lines(&["t a x: ```` @octocat #1"]), 0);
        assert!(c.starts_with("crewboard: 1 message\n\n`````text\n"), "{c}");
        assert!(c.ends_with("\n`````"), "{c}");
    }

    #[test]
    fn comment_keeps_the_newest_lines_when_too_large() {
        let big = "x".repeat(MAX_LINE);
        let all: VecDeque<String> = (0..40).map(|i| format!("{i:02}{big}")).collect();
        let c = comment(&all, 5);
        assert!(c.len() < 65_000, "{}", c.len());
        assert!(c.contains("older omitted"), "{c}");
        assert!(c.contains("\n39xxx") && !c.contains("\n00xxx"), "{}", &c[..80]);
    }

    #[test]
    fn line_cuts_a_long_message_on_a_character() {
        let m = json!({"ts": "t", "from": null, "topic": "fleet", "body": "é".repeat(MAX_LINE + 5)});
        assert_eq!(line(&m).chars().count(), MAX_LINE);
    }

    fn feed(input: &str, interval: Duration) -> (Vec<String>, bool) {
        let mut posts = vec![];
        let stop = run(std::io::Cursor::new(input.to_owned()), interval, |b| {
            posts.push(b.to_owned());
            Ok(())
        });
        (posts, matches!(stop, Stop::Off))
    }

    #[test]
    fn a_closed_stream_flushes_what_is_pending_once() {
        let input = "{\"boot\":\"b\",\"seq\":0}\n{\"gap\":true,\"oldest\":3}\n\
            {\"seq\":1,\"ts\":\"t1\",\"topic\":\"fleet\",\"from\":\"a\",\"body\":\"one\"}\n\
            {\"seq\":2,\"ts\":\"t2\",\"topic\":\"fleet\",\"from\":null,\"body\":\"two\"}\n";
        let (posts, off) = feed(input, Duration::from_secs(3600));
        assert!(off);
        assert_eq!(posts.len(), 1);
        assert!(posts[0].starts_with("crewboard: 2 messages"), "{}", posts[0]);
        assert!(posts[0].contains("t1 a fleet: one\nt2 - fleet: two\n"), "{}", posts[0]);
    }

    #[test]
    fn no_message_means_no_post() {
        assert_eq!(feed("{\"boot\":\"b\",\"seq\":0}\n", Duration::from_secs(3600)), (vec![], true));
    }

    #[test]
    fn a_failed_post_stops_the_sink() {
        let input = "{\"seq\":1,\"ts\":\"t\",\"topic\":\"fleet\",\"from\":null,\"body\":\"x\"}\n";
        let stop = run(std::io::Cursor::new(input.to_owned()), Duration::from_secs(3600), |_| Err("boom".into()));
        assert!(matches!(stop, Stop::Fail(e) if e == "boom"));
    }
}
