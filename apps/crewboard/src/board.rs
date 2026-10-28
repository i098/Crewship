//! Board state: topics, history rings, memory cap and subscriber fan-out.
//! Pure logic with no I/O; `serve.rs` owns the socket.

use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde_json::{Value, json};
use tokio::sync::Notify;
use tokio::sync::mpsc::{self, error::TrySendError};

pub const MAX_TOPICS: usize = 1024;
/// Longest advisory `from`, like a topic name.
const MAX_FROM: usize = 64;
/// Messages queued for one subscriber before the board drops it as slow.
pub const SUB_QUEUE: usize = 1024;

/// Longest topic summary, in characters.
pub const MAX_SUMMARY: usize = 160;

pub struct Limits {
    pub cap_bytes: usize,
    pub history: usize,
    pub max_msg: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Limits { cap_bytes: 64 << 20, history: 256, max_msg: 64 << 10 }
    }
}

/// A stored message: its seq and its wire line, newline included.
struct Msg {
    seq: u64,
    line: Arc<str>,
}

#[derive(Default)]
struct Topic {
    ring: VecDeque<Msg>,
    /// Highest seq evicted from this topic, for the gap marker.
    evicted: u64,
    /// Seq of the latest publish, for dropping the least recently published topic.
    last: u64,
    /// One line for readers choosing a thread; empty until a summarizer sets it.
    summary: String,
    /// Highest seq delivered to a non-viewer client that names the topic exactly (an agent); viewers and wildcard subscribers never move it.
    read_seq: u64,
    /// Seq of the last message the summary covers.
    summary_seq: u64,
}

struct Sub {
    id: u64,
    patterns: Vec<String>,
    tx: mpsc::Sender<Arc<str>>,
    viewer: bool,
    slow: Arc<Notify>,
}

/// A subscriber's live message queue, and the signal that the board dropped it as slow.
pub struct Feed {
    pub rx: mpsc::Receiver<Arc<str>>,
    pub slow: Arc<Notify>,
    /// The first line of the stream: the boot id and the seq at subscription time.
    pub hello: Arc<str>,
}

/// Subscriber id, replay lines, and the live message queue.
pub type Subscription = (u64, Vec<Arc<str>>, Feed);

pub struct Board {
    pub limits: Limits,
    boot: String,
    started: Instant,
    seq: u64,
    bytes: usize,
    topics: HashMap<String, Topic>,
    /// Highest seq of topics dropped at the topic cap.
    forgotten: u64,
    subs: Vec<Sub>,
    next_sub: u64,
    dropped: u64,
}

impl Board {
    pub fn new(limits: Limits) -> Self {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
        Board {
            limits,
            boot: format!("{:x}-{:x}", now.as_nanos(), std::process::id()),
            started: Instant::now(),
            seq: 0,
            bytes: 0,
            topics: HashMap::new(),
            forgotten: 0,
            subs: Vec::new(),
            next_sub: 0,
            dropped: 0,
        }
    }

    /// Stores and fans out one message; never blocks on a subscriber.
    pub fn publish(&mut self, topic: &str, from: Option<&str>, pid: i32, body: &str) -> Result<u64, &'static str> {
        if !valid_topic(topic) {
            return Err("bad_topic");
        }
        if body.len() > self.limits.max_msg || from.is_some_and(|f| f.len() > MAX_FROM) {
            return Err("too_large");
        }
        let seq = self.seq + 1;
        let line: Arc<str> = format!(
            "{{\"seq\":{seq},\"ts\":\"{}\",\"topic\":\"{topic}\",\"from\":{},\"pid\":{pid},\"body\":{}}}\n",
            rfc3339(SystemTime::now()),
            Value::from(from),
            Value::from(body),
        )
        .into();
        if line.len() > self.limits.cap_bytes {
            return Err("cap");
        }
        if !self.topics.contains_key(topic) && self.topics.len() >= MAX_TOPICS {
            let stale = self.topics.iter().min_by_key(|(_, t)| t.last).map(|(k, _)| k.clone()).expect("the topic cap is not zero");
            let gone = self.topics.remove(&stale).expect("key found above");
            self.bytes -= gone.ring.iter().map(|m| m.line.len()).sum::<usize>();
            self.forgotten = self.forgotten.max(gone.last);
        }
        self.seq = seq;
        self.bytes += line.len();
        let t = self.topics.entry(topic.to_owned()).or_default();
        t.last = seq;
        t.ring.push_back(Msg { seq, line: line.clone() });
        if t.ring.len() > self.limits.history {
            let old = t.ring.pop_front().expect("ring is not empty");
            t.evicted = old.seq;
            self.bytes -= old.line.len();
        }
        // Over the global cap: evict the oldest message on the board, whatever its topic.
        while self.bytes > self.limits.cap_bytes {
            let Some(t) = self.topics.values_mut().filter(|t| !t.ring.is_empty()).min_by_key(|t| t.ring[0].seq) else {
                break;
            };
            let old = t.ring.pop_front().expect("ring is not empty");
            t.evicted = old.seq;
            self.bytes -= old.line.len();
        }
        if self.fan_out(topic, &line) {
            self.topics.get_mut(topic).expect("topic was just published").read_seq = seq;
        }
        Ok(seq)
    }

    /// Delivers `line` to the matching subscribers and drops slow or closed ones.
    /// True when a non-viewer subscriber that names the topic exactly received it; wildcards only queue.
    fn fan_out(&mut self, topic: &str, line: &Arc<str>) -> bool {
        let dropped = &mut self.dropped;
        let mut agent_read = false;
        self.subs.retain(|s| {
            if !s.patterns.iter().any(|p| matches(p, topic)) {
                return true;
            }
            match s.tx.try_send(line.clone()) {
                Ok(()) => {
                    agent_read |= !s.viewer && s.patterns.iter().any(|p| p == topic);
                    true
                }
                Err(TrySendError::Full(_)) => {
                    *dropped += 1;
                    s.slow.notify_one();
                    false
                }
                Err(TrySendError::Closed(_)) => false,
            }
        });
        agent_read
    }

    /// Counts the newest message of each topic named exactly in `patterns` as read by an agent when it is above `after`.
    fn mark_read_after(&mut self, patterns: &[String], after: u64) {
        for (_, t) in self.topics.iter_mut().filter(|(n, _)| patterns.iter().any(|p| p == *n)) {
            if let Some(newest) = t.ring.back().map(|m| m.seq).filter(|&s| s > after) {
                t.read_seq = t.read_seq.max(newest);
            }
        }
    }

    /// Registers a subscriber. With `since`, replays retained messages with a
    /// higher seq, led by a gap marker when any of them were evicted. The board
    /// restarted when `since` is beyond its seq or `boot` is not its boot id: that
    /// is a gap marked `restarted` and replays all retained messages.
    pub fn subscribe(&mut self, patterns: Vec<String>, since: Option<u64>, boot: Option<&str>, viewer: bool) -> Result<Subscription, &'static str> {
        if patterns.is_empty() || !patterns.iter().all(|p| valid_pattern(p)) {
            return Err("bad_topic");
        }
        let mut replay = Vec::new();
        if let Some(since) = since {
            let restarted = since > self.seq || boot.is_some_and(|b| b != self.boot);
            let mut lost = self.forgotten;
            let mut msgs: Vec<&Msg> = Vec::new();
            for (name, t) in &self.topics {
                if patterns.iter().any(|p| matches(p, name)) {
                    lost = lost.max(t.evicted);
                    msgs.extend(t.ring.iter().filter(|m| restarted || m.seq > since));
                }
            }
            msgs.sort_unstable_by_key(|m| m.seq);
            if restarted || lost > since {
                let oldest = msgs.first().map_or(self.seq + 1, |m| m.seq);
                let restarted = if restarted { ",\"restarted\":true" } else { "" };
                replay.push(format!("{{\"gap\":true,\"oldest\":{oldest}{restarted}}}\n").into());
            }
            replay.extend(msgs.into_iter().map(|m| m.line.clone()));
            if !viewer {
                self.mark_read_after(&patterns, if restarted { 0 } else { since });
            }
        }
        let (tx, rx) = mpsc::channel(SUB_QUEUE);
        self.next_sub += 1;
        let slow = Arc::new(Notify::new());
        self.subs.push(Sub { id: self.next_sub, patterns, tx, slow: slow.clone(), viewer });
        let hello = format!("{{\"boot\":{},\"seq\":{}}}\n", Value::from(self.boot.as_str()), self.seq).into();
        Ok((self.next_sub, replay, Feed { rx, slow, hello }))
    }

    /// Removes a subscriber; `slow` counts it as dropped for being too slow.
    pub fn unsubscribe(&mut self, id: u64, slow: bool) {
        if let Some(i) = self.subs.iter().position(|s| s.id == id) {
            self.subs.remove(i);
            self.dropped += u64::from(slow);
        }
    }

    /// A `hist` read: the last `n` messages. Unless `viewer`, it counts as an agent read of the topic.
    pub fn read(&mut self, topic: &str, n: usize, viewer: bool) -> Vec<Arc<str>> {
        if let Some(t) = self.topics.get_mut(topic).filter(|_| !viewer) {
            t.read_seq = t.ring.back().map_or(t.read_seq, |m| m.seq);
        }
        self.history(topic, n)
    }

    /// The last `n` messages of `topic`, oldest first.
    pub fn history(&self, topic: &str, n: usize) -> Vec<Arc<str>> {
        let Some(t) = self.topics.get(topic) else {
            return Vec::new();
        };
        t.ring.iter().skip(t.ring.len().saturating_sub(n)).map(|m| m.line.clone()).collect()
    }

    /// Stores the one-line `summary` of `topic`, covering messages up to `seq` (default: the
    /// newest). Whitespace collapses and the line is cut at `MAX_SUMMARY` characters. An older
    /// `seq` than the stored one is `stale`: a slow summarizer must not overwrite a newer line.
    pub fn set_summary(&mut self, topic: &str, summary: &str, seq: Option<u64>) -> Result<(), &'static str> {
        let t = self.topics.get_mut(topic).ok_or("bad_topic")?;
        let seq = seq.unwrap_or(t.last).min(self.seq);
        if seq < t.summary_seq {
            return Err("stale");
        }
        t.summary = summary.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(MAX_SUMMARY).collect();
        t.summary_seq = seq;
        Ok(())
    }

    /// The topics with counts; `with_summary` adds `summary` and `summary_seq`.
    pub fn topics(&self, with_summary: bool) -> Value {
        let mut names: Vec<&String> = self.topics.keys().collect();
        names.sort();
        names
            .into_iter()
            .map(|name| {
                let t = &self.topics[name];
                let mut v = json!({
                    "topic": name,
                    "count": t.ring.len(),
                    "oldest": t.ring.front().map(|m| m.seq),
                    "newest": t.ring.back().map(|m| m.seq),
                    "read_seq": t.read_seq,
                });
                if with_summary {
                    v["summary"] = t.summary.as_str().into();
                    v["summary_seq"] = t.summary_seq.into();
                }
                v
            })
            .collect()
    }

    pub fn stat(&self) -> Value {
        json!({
            "boot": self.boot,
            "uptime_s": self.started.elapsed().as_secs(),
            "seq": self.seq,
            "bytes": self.bytes,
            "cap_bytes": self.limits.cap_bytes,
            "topics": self.topics.len(),
            "subs": self.subs.len(),
            "dropped": self.dropped,
        })
    }
}

pub fn valid_topic(t: &str) -> bool {
    (1..=64).contains(&t.len()) && t.bytes().all(|b| matches!(b, b'a'..=b'z' | b'0'..=b'9' | b'.' | b'_' | b'/' | b'-'))
}

/// A topic name, or a prefix with a trailing `*` (`task/*`, `*`).
fn valid_pattern(p: &str) -> bool {
    p == "*" || valid_topic(p.strip_suffix('*').unwrap_or(p))
}

fn matches(pattern: &str, topic: &str) -> bool {
    match pattern.strip_suffix('*') {
        Some(prefix) => topic.starts_with(prefix),
        None => pattern == topic,
    }
}

/// UTC RFC 3339 with milliseconds, e.g. `2026-10-09T20:14:03.117Z`.
pub fn rfc3339(t: SystemTime) -> String {
    let d = t.duration_since(UNIX_EPOCH).unwrap_or_default();
    let (days, secs) = (d.as_secs() / 86_400, d.as_secs() % 86_400);
    // Civil date from days since 1970-01-01 (H. Hinnant's algorithm).
    let z = days + 719_468;
    let (era, doe) = (z / 146_097, z % 146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + u64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}.{:03}Z", secs / 3600, secs / 60 % 60, secs % 60, d.subsec_millis())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn board(cap_bytes: usize, history: usize) -> Board {
        Board::new(Limits { cap_bytes, history, max_msg: 1000 })
    }

    fn seqs(lines: &[Arc<str>]) -> Vec<Value> {
        lines.iter().map(|l| serde_json::from_str::<Value>(l).unwrap()["seq"].clone()).collect()
    }

    #[test]
    fn timestamps() {
        let at = |ms| rfc3339(UNIX_EPOCH + Duration::from_millis(ms));
        assert_eq!(at(0), "1970-01-01T00:00:00.000Z");
        assert_eq!(at(951_782_400_000), "2000-02-29T00:00:00.000Z");
        assert_eq!(at(1_791_576_843_117), "2026-10-09T20:14:03.117Z");
    }

    #[test]
    fn topic_names_and_patterns() {
        assert!(valid_topic("task/cf-x_1.2"));
        assert!(!valid_topic("") && !valid_topic("Task") && !valid_topic("a b") && !valid_topic(&"a".repeat(65)));
        assert!(valid_pattern("*") && valid_pattern("task/*") && !valid_pattern("ta*sk") && !valid_pattern("**"));
        assert!(matches("*", "fleet") && matches("task/*", "task/a") && !matches("task/*", "fleet"));
        assert!(matches("fleet", "fleet") && !matches("fleet", "fleet2"));
    }

    #[test]
    fn history_ring_and_gap_marker() {
        let mut b = board(1 << 20, 2);
        for body in ["1", "2", "3"] {
            b.publish("t", None, 1, body).unwrap();
        }
        b.publish("u", Some("me"), 1, "4").unwrap();
        assert_eq!(seqs(&b.history("t", 10)), [json!(2), json!(3)]);
        let (_, replay, _rx) = b.subscribe(vec!["t".into()], Some(0), None, false).unwrap();
        assert_eq!(&*replay[0], "{\"gap\":true,\"oldest\":2}\n");
        assert_eq!(seqs(&replay[1..]), [json!(2), json!(3)]);
        // Nothing after seq 1 was evicted from `t`, and `u` evicted nothing.
        let (_, replay, _rx) = b.subscribe(vec!["t".into(), "u".into()], Some(1), None, false).unwrap();
        assert_eq!(seqs(&replay), [json!(2), json!(3), json!(4)]);
        let (_, replay, _rx) = b.subscribe(vec!["u".into()], None, None, false).unwrap();
        assert!(replay.is_empty());
    }

    #[test]
    fn limits_and_global_cap() {
        let mut b = board(400, 100);
        assert_eq!(b.publish("t", None, 1, &"x".repeat(1001)), Err("too_large"));
        assert_eq!(b.publish("t", Some(&"f".repeat(65)), 1, "x"), Err("too_large"));
        assert_eq!(b.publish("t", None, 1, &"x".repeat(500)), Err("cap"));
        assert_eq!(b.publish("Bad", None, 1, "x"), Err("bad_topic"));
        for topic in ["a", "b", "c", "d"] {
            b.publish(topic, None, 1, &"x".repeat(100)).unwrap();
        }
        // About 180 bytes per line: only the newest two fit in 400.
        assert!(b.stat()["bytes"].as_u64().unwrap() <= 400);
        assert!(b.history("a", 10).is_empty() && b.history("b", 10).is_empty());
        assert_eq!(seqs(&b.history("d", 10)), [json!(4)]);
    }

    #[test]
    fn summary_is_stored_cut_and_never_overwritten_by_an_older_one() {
        let mut b = board(1 << 20, 10);
        assert_eq!(b.set_summary("t", "x", None), Err("bad_topic"));
        b.publish("t", None, 1, "x").unwrap();
        b.publish("u", None, 1, "x").unwrap();
        b.publish("t", None, 1, "x").unwrap();
        assert_eq!(b.topics(false)[0].get("summary"), None);
        assert_eq!(b.topics(true)[0]["summary"], json!(""));
        assert_eq!(b.topics(true)[0]["summary_seq"], json!(0));
        let long = format!("a  b\n{}", "z".repeat(300));
        b.set_summary("t", &long, None).unwrap();
        let t = &b.topics(true)[0];
        assert_eq!(t["summary"].as_str().unwrap().chars().count(), MAX_SUMMARY);
        assert!(t["summary"].as_str().unwrap().starts_with("a b z"));
        assert_eq!(t["summary_seq"], json!(3));
        assert_eq!(b.set_summary("t", "old", Some(1)), Err("stale"));
        b.set_summary("t", "same seq", Some(3)).unwrap();
        // A seq beyond the board is clamped to it.
        b.set_summary("u", "ok", Some(99)).unwrap();
        assert_eq!(b.topics(true)[1]["summary_seq"], json!(3));
        assert_eq!(b.topics(true)[0]["summary"], json!("same seq"));
    }

    #[test]
    fn topic_cap_drops_the_least_recently_published_topic() {
        let mut b = board(1 << 20, 10);
        for i in 0..MAX_TOPICS {
            b.publish(&format!("t{i}"), None, 1, "x").unwrap();
        }
        // t0 is fresh again, so t1 is the stalest.
        b.publish("t0", None, 1, "x").unwrap();
        b.publish("one-more", None, 1, "x").unwrap();
        assert_eq!(b.stat()["topics"], json!(MAX_TOPICS));
        assert!(b.history("t1", 10).is_empty());
        assert_eq!(b.history("t0", 10).len(), 2);
        assert_eq!(b.history("one-more", 10).len(), 1);
        assert_eq!(b.publish("Bad", None, 1, "x"), Err("bad_topic"));
        let kept: usize =
            b.topics(false).as_array().unwrap().iter().map(|t| b.history(t["topic"].as_str().unwrap(), 10).iter().map(|l| l.len()).sum::<usize>()).sum();
        assert_eq!(b.stat()["bytes"], json!(kept));
        // t1 held seq 2: a subscriber that saw seq 1 must be told about the loss.
        let (_, replay, _rx) = b.subscribe(vec!["t0".into()], Some(1), None, false).unwrap();
        assert_eq!(&*replay[0], "{\"gap\":true,\"oldest\":1025}\n");
        let (_, replay, _rx) = b.subscribe(vec!["t0".into()], Some(2), None, false).unwrap();
        assert_eq!(seqs(&replay), [json!(1025)]);
    }

    #[test]
    fn since_beyond_seq_means_restart() {
        let mut b = board(1 << 20, 10);
        for body in ["1", "2", "3"] {
            b.publish("t", None, 1, body).unwrap();
        }
        let (_, replay, _rx) = b.subscribe(vec!["t".into()], Some(100), None, false).unwrap();
        assert_eq!(&*replay[0], "{\"gap\":true,\"oldest\":1,\"restarted\":true}\n");
        assert_eq!(seqs(&replay[1..]), [json!(1), json!(2), json!(3)]);
        let (_, replay, _rx) = b.subscribe(vec!["t".into()], Some(3), None, false).unwrap();
        assert!(replay.is_empty());
    }

    #[test]
    fn boot_id_detects_a_restart_past_the_old_seq() {
        let mut old = board(1 << 20, 10);
        for body in ["1", "2", "3"] {
            old.publish("t", None, 1, body).unwrap();
        }
        let (_, _, feed) = old.subscribe(vec!["t".into()], None, None, false).unwrap();
        let hello: Value = serde_json::from_str(&feed.hello).unwrap();
        assert_eq!(hello["seq"], json!(3));
        let old_boot = hello["boot"].as_str().unwrap().to_owned();

        let mut new = board(1 << 20, 10);
        for body in ["1", "2", "3", "4", "5"] {
            new.publish("t", None, 1, body).unwrap();
        }
        let (_, _, feed) = new.subscribe(vec!["t".into()], None, None, false).unwrap();
        let new_boot = serde_json::from_str::<Value>(&feed.hello).unwrap()["boot"].clone();
        assert_ne!(new_boot, json!(old_boot));

        let (_, replay, _rx) = new.subscribe(vec!["t".into()], Some(3), Some(&old_boot), false).unwrap();
        assert_eq!(&*replay[0], "{\"gap\":true,\"oldest\":1,\"restarted\":true}\n");
        assert_eq!(seqs(&replay[1..]), [json!(1), json!(2), json!(3), json!(4), json!(5)]);
        // Without a boot id the seq alone cannot tell: it continues the stream.
        let (_, replay, _rx) = new.subscribe(vec!["t".into()], Some(3), None, false).unwrap();
        assert_eq!(seqs(&replay), [json!(4), json!(5)]);
        let (_, replay, _rx) = new.subscribe(vec!["t".into()], Some(3), new_boot.as_str(), false).unwrap();
        assert_eq!(seqs(&replay), [json!(4), json!(5)]);
    }

    fn read_seq(b: &Board) -> Value {
        b.topics(false)[0]["read_seq"].clone()
    }

    #[test]
    fn read_seq_follows_agent_reads_only() {
        let mut b = board(1 << 20, 10);
        b.publish("t", None, 1, "1").unwrap();
        assert_eq!(read_seq(&b), json!(0));
        // A viewer's replay and live delivery leave it alone.
        let (_, _, mut viewer) = b.subscribe(vec!["t".into()], Some(0), None, true).unwrap();
        b.publish("t", None, 1, "2").unwrap();
        viewer.rx.try_recv().unwrap();
        assert_eq!(read_seq(&b), json!(0));
        // A wildcard subscriber only queues messages.
        let (_, _, mut star) = b.subscribe(vec!["*".into(), "t*".into()], Some(0), None, false).unwrap();
        b.publish("t", None, 1, "3").unwrap();
        star.rx.try_recv().unwrap();
        assert_eq!(read_seq(&b), json!(0));
        // A non-viewer naming the topic exactly moves it.
        let (_, _, mut agent) = b.subscribe(vec!["t".into()], None, None, false).unwrap();
        b.publish("t", None, 1, "4").unwrap();
        agent.rx.try_recv().unwrap();
        assert_eq!(read_seq(&b), json!(4));
        // An agent's replay moves it too, and a hist read is marked explicitly.
        b.publish("t", None, 1, "5").unwrap();
        assert_eq!(read_seq(&b), json!(5));
        b.publish("u", None, 1, "6").unwrap();
        assert_eq!(b.read("u", 10, true).len(), 1);
        assert_eq!(b.topics(false)[1]["read_seq"], json!(0));
        b.read("u", 10, false);
        assert_eq!(b.topics(false)[1]["read_seq"], json!(6));
    }

    #[test]
    fn read_seq_resets_on_restart() {
        let mut b = board(1 << 20, 10);
        let (_, _, _rx) = b.subscribe(vec!["t".into()], None, None, false).unwrap();
        b.publish("t", None, 1, "1").unwrap();
        assert_eq!(read_seq(&b), json!(1));
        let mut fresh = board(1 << 20, 10);
        fresh.publish("t", None, 1, "1").unwrap();
        assert_eq!(read_seq(&fresh), json!(0));
    }

    #[test]
    fn slow_subscriber_is_dropped() {
        let mut b = board(1 << 20, 10);
        let (_, _, _rx) = b.subscribe(vec!["*".into()], None, None, false).unwrap();
        let (_, _, mut fast) = b.subscribe(vec!["t".into()], None, None, false).unwrap();
        for _ in 0..SUB_QUEUE {
            b.publish("t", None, 1, "x").unwrap();
            fast.rx.try_recv().unwrap();
        }
        assert_eq!(b.stat()["subs"], json!(2));
        b.publish("t", None, 1, "x").unwrap();
        assert_eq!(b.stat()["subs"], json!(1));
        assert_eq!(b.stat()["dropped"], json!(1));
    }
}
