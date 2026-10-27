//! `crewboard summarize`: keeps each topic's one-line summary fresh.
//!
//! A client of the daemon, never part of it: the daemon only stores the line. The loop in
//! `main.rs` feeds every message into `Debounce`, and a topic that is due goes to a model
//! command (stdin prompt, stdout summary). Credentials stay in the environment of that command.

use std::collections::HashMap;
use std::io::Write;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::Value;

/// Default model command: Haiku 5.5 through omp, no tools, no session.
pub const DEFAULT_CMD: &str = "omp -p --model anthropic/claude-haiku-5-5 --no-rules --no-skills --no-extensions --no-tools --no-session";
/// Messages of a topic given to the model.
pub const CONTEXT: u64 = 30;

/// Per topic: when it was first and last touched since its summary was last asked for.
struct Pending {
    first: Instant,
    last: Instant,
    seq: u64,
}

/// A topic is due after `quiet` without a message, or `max_wait` after its first new message
/// so that a chatty topic still refreshes.
pub struct Debounce {
    quiet: Duration,
    max_wait: Duration,
    pending: HashMap<String, Pending>,
}

impl Debounce {
    pub fn new(quiet: Duration, max_wait: Duration) -> Self {
        Debounce { quiet, max_wait, pending: HashMap::new() }
    }

    pub fn note(&mut self, topic: &str, seq: u64, now: Instant) {
        let p = self.pending.entry(topic.to_owned()).or_insert(Pending { first: now, last: now, seq });
        p.last = now;
        p.seq = seq;
    }

    fn due_at(&self, p: &Pending) -> Instant {
        (p.last + self.quiet).min(p.first + self.max_wait)
    }

    /// Removes and returns one due topic with the seq of its latest message.
    pub fn take_due(&mut self, now: Instant) -> Option<(String, u64)> {
        let topic = self.pending.iter().filter(|(_, p)| self.due_at(p) <= now).min_by_key(|(_, p)| self.due_at(p)).map(|(t, _)| t.clone())?;
        let p = self.pending.remove(&topic)?;
        Some((topic, p.seq))
    }

    /// How long until the next topic is due; `None` when nothing waits.
    pub fn wait(&self, now: Instant) -> Option<Duration> {
        self.pending.values().map(|p| self.due_at(p).saturating_duration_since(now)).min()
    }
}

/// The model prompt for `topic`: its old summary and its latest messages (`hist` reply lines).
pub fn prompt(topic: &str, old: &str, messages: &[Value]) -> String {
    let mut p = format!(
        "Summarize the message board thread `{topic}` in ONE line of at most 160 characters, so a reader can decide whether to read it: \
         who is talking, what about, and the latest decision or open question. Reply with the line only.\n"
    );
    if !old.is_empty() {
        p += &format!("Previous summary: {old}\n");
    }
    p += "Messages, oldest first:\n";
    for m in messages {
        let s = |k: &str| m[k].as_str().unwrap_or("-");
        let body: String = s("body").chars().take(500).collect();
        p += &format!("{}: {}\n", s("from"), body.replace('\n', " "));
    }
    p
}

/// A model call that takes longer is killed, so one stuck call cannot stop every refresh.
pub const MODEL_TIMEOUT: Duration = Duration::from_secs(120);

/// Runs the model command `cmd` (split on spaces, no shell) with `prompt` on stdin.
pub fn ask(cmd: &str, prompt: &str, timeout: Duration) -> Result<String, String> {
    let mut words = cmd.split_whitespace();
    let prog = words.next().ok_or("empty summary command")?;
    let mut child =
        Command::new(prog).args(words).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().map_err(|e| format!("{prog}: {e}"))?;
    // Feed stdin from its own thread: a child that answers before it has read everything must not block us.
    let (mut stdin, input) = (child.stdin.take().expect("piped"), prompt.to_owned());
    std::thread::spawn(move || {
        let _ = stdin.write_all(input.as_bytes());
    });
    let (done, watch) = std::sync::mpsc::channel::<()>();
    let pid = child.id() as i32;
    let killed = std::thread::spawn(move || {
        let timed_out = watch.recv_timeout(timeout) == Err(std::sync::mpsc::RecvTimeoutError::Timeout);
        if timed_out {
            unsafe { libc::kill(pid, libc::SIGKILL) };
        }
        timed_out
    });
    let out = child.wait_with_output().map_err(|e| format!("{prog}: {e}"));
    let _ = done.send(());
    if killed.join().unwrap_or(false) {
        return Err(format!("{prog} timed out after {}s", timeout.as_secs()));
    }
    let out = out?;
    if !out.status.success() {
        return Err(format!("{prog} failed: {}", String::from_utf8_lossy(&out.stderr).trim().chars().take(200).collect::<String>()));
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    const S: Duration = Duration::from_secs(1);

    #[test]
    fn quiet_period_restarts_on_each_message() {
        let t0 = Instant::now();
        let mut d = Debounce::new(10 * S, 100 * S);
        d.note("a", 1, t0);
        d.note("a", 2, t0 + 8 * S);
        assert_eq!(d.take_due(t0 + 12 * S), None);
        assert_eq!(d.wait(t0 + 12 * S), Some(6 * S));
        assert_eq!(d.take_due(t0 + 18 * S), Some(("a".into(), 2)));
        assert_eq!(d.wait(t0 + 18 * S), None);
    }

    #[test]
    fn chatty_topic_is_due_at_max_wait() {
        let t0 = Instant::now();
        let mut d = Debounce::new(10 * S, 30 * S);
        for i in 0..40 {
            d.note("a", i, t0 + Duration::from_secs(i * 2));
        }
        assert_eq!(d.take_due(t0 + 29 * S), None);
        assert_eq!(d.take_due(t0 + 30 * S), Some(("a".into(), 39)));
    }

    #[test]
    fn topics_are_independent_and_earliest_goes_first() {
        let t0 = Instant::now();
        let mut d = Debounce::new(10 * S, 100 * S);
        d.note("b", 2, t0 + S);
        d.note("a", 1, t0);
        assert_eq!(d.take_due(t0 + 20 * S), Some(("a".into(), 1)));
        assert_eq!(d.take_due(t0 + 20 * S), Some(("b".into(), 2)));
    }

    #[test]
    fn model_command_gets_the_prompt_on_stdin() {
        assert_eq!(ask("cat", "hello", 10 * S).unwrap(), "hello");
        // `cat` echoes while it reads: a prompt beyond the pipe size must not deadlock.
        assert_eq!(ask("cat", &"x".repeat(300_000), 10 * S).unwrap().len(), 300_000);
        assert!(ask("false", "x", 10 * S).is_err());
        assert!(ask("no-such-binary-xyz", "x", 10 * S).is_err());
    }

    #[test]
    fn a_stuck_model_command_is_killed() {
        let start = Instant::now();
        let err = ask("sleep 30", "", Duration::from_millis(200)).unwrap_err();
        assert!(err.contains("timed out"), "{err}");
        assert!(start.elapsed() < 5 * S);
    }
}
