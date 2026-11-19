//! Token acceleration watcher (docs/architecture.md#token-acceleration-notice).
//!
//! Every FM_ACCEL_INTERVAL seconds it counts the tokens the fleet's omp sessions logged since the
//! last sample, turns that into a rate (tokens/s) and its change (tokens/s^2), and when the change
//! passes FM_ACCEL_THRESHOLD it sends one usage status card with `fm-text-card --send`.
//! FM_ACCEL_COOLDOWN seconds must pass between cards. From 00:00 to 08:00 Pacific time no card is
//! sent unless the change passes EXTREME times the threshold.

use serde_json::Value;
use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::{env, thread};

const DEFAULT_THRESHOLD: f64 = 200.0; // tokens/s^2
const DEFAULT_INTERVAL: u64 = 300; // seconds
const DEFAULT_COOLDOWN: u64 = 3600; // seconds
const EXTREME: f64 = 3.0; // times the threshold: breaks quiet hours
const QUIET_END_HOUR: u32 = 8; // quiet hours are 00:00 to 08:00 Pacific

/// What the watcher needs from the outside world; tests supply fakes.
trait Clock {
    fn epoch(&self) -> u64;
    fn pacific_hour(&self) -> u32;
}

trait Sender {
    fn send(&mut self, card: &str) -> bool;
}

struct Watch {
    threshold: f64,
    cooldown: u64,
    prev_rate: Option<f64>,
    last_sent: Option<u64>,
}

struct Reading {
    rate: f64,
    prev_rate: f64,
    accel: f64,
}

impl Watch {
    /// Feed the tokens counted over `secs` seconds; returns the reading once a previous rate exists.
    fn sample(&mut self, tokens: u64, secs: f64) -> Option<Reading> {
        let rate = tokens as f64 / secs;
        let prev = self.prev_rate.replace(rate)?;
        Some(Reading {
            rate,
            prev_rate: prev,
            accel: (rate - prev) / secs,
        })
    }

    /// True when a card is due: past the threshold, out of cooldown, and out of quiet hours unless extreme.
    fn due(&self, accel: f64, now: u64, pacific_hour: u32) -> bool {
        if accel <= self.threshold {
            return false;
        }
        if self
            .last_sent
            .is_some_and(|t| now.saturating_sub(t) < self.cooldown)
        {
            return false;
        }
        pacific_hour >= QUIET_END_HOUR || accel > self.threshold * EXTREME
    }

    /// One tick: sample, decide, send. A failed send restores the earlier rate and leaves the cooldown unset, so the next tick sees the same jump and retries.
    fn tick(
        &mut self,
        tokens: u64,
        secs: f64,
        tops: &[(String, u64)],
        quota: impl FnOnce() -> Vec<String>,
        clock: &dyn Clock,
        sender: &mut dyn Sender,
    ) -> bool {
        let Some(r) = self.sample(tokens, secs) else {
            return false;
        };
        if !self.due(r.accel, clock.epoch(), clock.pacific_hour()) {
            return false;
        }
        if sender.send(&card(&r, tops, &quota())) {
            self.last_sent = Some(clock.epoch());
            return true;
        }
        self.prev_rate = Some(r.prev_rate);
        false
    }
}

fn card(r: &Reading, tops: &[(String, u64)], quota: &[String]) -> String {
    let mut s = String::from("Token use is speeding up\n");
    s += &format!(
        "rate now: {:.0} tokens/s\nrate before: {:.0} tokens/s\nchange: {:+.0} tokens/s per s\n",
        r.rate, r.prev_rate, r.accel
    );
    s += "# Top consumers\n";
    for (name, n) in tops.iter().take(3) {
        s += &format!("- {name}: {n} tokens\n");
    }
    s += "# Quota left\n";
    for q in quota {
        s += &format!("- {q}\n");
    }
    s
}

/// "claude: 5h 31%, resets in 2h 3m · 7d 40%" (fm-usage-brief text) -> "claude 5h: 69% left".
fn quota_left(brief: &str) -> Vec<String> {
    let mut out = vec![];
    for line in brief.lines() {
        let Some((who, rest)) = line.split_once(": ") else {
            continue;
        };
        if who != "claude" && who != "codex" {
            continue;
        }
        for part in rest.split(" · ") {
            let mut w = part.split_whitespace();
            let (Some(win), Some(pct)) = (w.next(), w.next()) else {
                continue;
            };
            if let Ok(used) = pct.trim_end_matches([',', '%']).parse::<u32>() {
                out.push(format!(
                    "{who} {win}: {}% left",
                    100u32.saturating_sub(used)
                ));
            }
        }
    }
    out
}

/// Tokens in one JSONL line: an assistant message or a model_usage record with usage.totalTokens.
fn line_tokens(line: &str) -> u64 {
    if !line.contains("\"totalTokens\"") {
        return 0;
    }
    let Ok(v) = serde_json::from_str::<Value>(line) else {
        return 0;
    };
    let usage = match v["type"].as_str() {
        Some("message") if v["message"]["role"] == "assistant" => &v["message"]["usage"],
        Some("model_usage") => &v["usage"],
        _ => return 0,
    };
    usage["totalTokens"].as_u64().unwrap_or(0)
}

/// Follows the omp session logs: reads only the bytes appended since the last scan.
struct Sessions {
    root: PathBuf,
    offsets: HashMap<PathBuf, u64>,
    primed: bool,
}

impl Sessions {
    fn new(root: PathBuf) -> Self {
        Sessions {
            root,
            offsets: HashMap::new(),
            primed: false,
        }
    }

    fn files(dir: &Path, depth: u8, out: &mut Vec<PathBuf>) {
        let Ok(rd) = fs::read_dir(dir) else { return };
        for e in rd.flatten() {
            let p = e.path();
            if p.extension().is_some_and(|x| x == "jsonl") {
                out.push(p);
            } else if depth > 0 && e.file_type().is_ok_and(|t| t.is_dir()) {
                Self::files(&p, depth - 1, out);
            }
        }
    }

    /// Tokens added since the last scan, in total and per project folder. The first scan only sets offsets.
    fn scan(&mut self) -> (u64, HashMap<String, u64>) {
        let mut files = vec![];
        Self::files(&self.root, 2, &mut files);
        let (mut total, mut per) = (0, HashMap::new());
        for p in files {
            let Ok(mut f) = File::open(&p) else { continue };
            let len = f.metadata().map(|m| m.len()).unwrap_or(0);
            let off = match self.offsets.get(&p) {
                Some(o) if *o <= len => *o,
                Some(_) => 0, // truncated: read it again
                None if !self.primed => len,
                None => 0,
            };
            if off == len {
                self.offsets.insert(p, len);
                continue;
            }
            let mut buf = vec![];
            if f.seek(SeekFrom::Start(off)).is_err()
                || f.take(len - off).read_to_end(&mut buf).is_err()
            {
                continue;
            }
            // Only whole lines count; a half-written last line waits for the next scan.
            let end = buf.iter().rposition(|b| *b == b'\n').map_or(0, |i| i + 1);
            let n: u64 = String::from_utf8_lossy(&buf[..end])
                .lines()
                .map(line_tokens)
                .sum();
            self.offsets.insert(p.clone(), off + end as u64);
            total += n;
            if n > 0 {
                *per.entry(project(&self.root, &p)).or_insert(0) += n;
            }
        }
        self.primed = true;
        (total, per)
    }
}

/// The first folder under the sessions root, trimmed to its last 32 characters.
fn project(root: &Path, p: &Path) -> String {
    let name = p
        .strip_prefix(root)
        .ok()
        .and_then(|r| r.components().next())
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .unwrap_or_default();
    let name = name.trim_matches('-');
    let skip = name.chars().count().saturating_sub(32);
    name.chars().skip(skip).collect()
}

struct RealClock;

impl Clock for RealClock {
    fn epoch(&self) -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_secs())
    }
    fn pacific_hour(&self) -> u32 {
        let out = Command::new("date")
            .env("TZ", "America/Los_Angeles")
            .arg("+%H")
            .output();
        out.ok()
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(QUIET_END_HOUR)
    }
}

/// Sends the card text through `fm-text-card --send`, which renders the PNG and texts it.
struct TextCardSender;

impl Sender for TextCardSender {
    fn send(&mut self, card: &str) -> bool {
        let Ok(mut child) = Command::new("fm-text-card")
            .arg("--send")
            .stdin(Stdio::piped())
            .spawn()
        else {
            return false;
        };
        if let Some(mut stdin) = child.stdin.take()
            && stdin.write_all(card.as_bytes()).is_err()
        {
            return false;
        }
        child.wait().is_ok_and(|s| s.success())
    }
}

fn quota_now() -> Vec<String> {
    let out = Command::new("fm-usage-brief")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok());
    let left = out.map(|s| quota_left(&s)).unwrap_or_default();
    if left.is_empty() {
        vec!["unknown".into()]
    } else {
        left
    }
}

fn config<T: std::str::FromStr>(name: &str, default: T) -> T {
    env::var(name)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn main() {
    let interval: u64 = config("FM_ACCEL_INTERVAL", DEFAULT_INTERVAL);
    let home = env::var("HOME").unwrap_or_default();
    let root = env::var("FM_ACCEL_SESSIONS")
        .map(PathBuf::from)
        .unwrap_or_else(|_| Path::new(&home).join(".omp/agent/sessions"));
    let mut watch = Watch {
        threshold: config("FM_ACCEL_THRESHOLD", DEFAULT_THRESHOLD),
        cooldown: config("FM_ACCEL_COOLDOWN", DEFAULT_COOLDOWN),
        prev_rate: None,
        last_sent: None,
    };
    let (clock, mut sender, mut sessions) = (RealClock, TextCardSender, Sessions::new(root));
    sessions.scan();
    let mut last = clock.epoch();
    loop {
        thread::sleep(Duration::from_secs(interval));
        let (now, (tokens, per)) = (clock.epoch(), sessions.scan());
        let secs = now.saturating_sub(last).max(1) as f64;
        last = now;
        let mut tops: Vec<_> = per.into_iter().collect();
        tops.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        watch.tick(tokens, secs, &tops, quota_now, &clock, &mut sender);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    struct FakeClock(Cell<u64>, u32);
    impl Clock for FakeClock {
        fn epoch(&self) -> u64 {
            self.0.get()
        }
        fn pacific_hour(&self) -> u32 {
            self.1
        }
    }
    #[derive(Default)]
    struct FakeSender {
        cards: Vec<String>,
        ok: bool,
    }
    impl Sender for FakeSender {
        fn send(&mut self, card: &str) -> bool {
            self.cards.push(card.to_string());
            self.ok
        }
    }

    fn watch() -> Watch {
        Watch {
            threshold: 200.0,
            cooldown: 3600,
            prev_rate: None,
            last_sent: None,
        }
    }

    #[test]
    fn rate_and_acceleration() {
        let mut w = watch();
        assert!(w.sample(3000, 300.0).is_none()); // 10 tokens/s, no previous rate yet
        let r = w.sample(33000, 300.0).unwrap(); // 110 tokens/s
        assert_eq!((r.prev_rate, r.rate), (10.0, 110.0));
        assert!((r.accel - 100.0 / 300.0).abs() < 1e-9);
    }

    #[test]
    fn card_only_past_threshold_and_cooldown() {
        let (mut w, mut s) = (
            watch(),
            FakeSender {
                ok: true,
                ..Default::default()
            },
        );
        let clock = FakeClock(Cell::new(100_000), 12);
        assert!(!w.tick(0, 300.0, &[], Vec::new, &clock, &mut s)); // first sample
        assert!(!w.tick(300 * 100, 300.0, &[], Vec::new, &clock, &mut s)); // accel 0.33 < 200
        assert!(w.tick(300 * 100_000, 300.0, &[], Vec::new, &clock, &mut s)); // accel ~333
        assert!(!w.tick(0, 300.0, &[], Vec::new, &clock, &mut s)); // rate falls
        assert!(!w.tick(300 * 100_000, 300.0, &[], Vec::new, &clock, &mut s)); // still in cooldown
        clock.0.set(100_000 + 3600);
        assert!(!w.tick(0, 300.0, &[], Vec::new, &clock, &mut s));
        assert!(w.tick(300 * 100_000, 300.0, &[], Vec::new, &clock, &mut s)); // cooldown over
        assert_eq!(s.cards.len(), 2);
    }

    #[test]
    fn quiet_hours_need_an_extreme_jump() {
        let w = watch();
        assert!(!w.due(300.0, 0, 7)); // 07:xx Pacific, past threshold only
        assert!(!w.due(600.0, 0, 3)); // exactly 3x is not past 3x
        assert!(w.due(601.0, 0, 3));
        assert!(w.due(300.0, 0, 8));
        assert!(!w.due(200.0, 0, 12)); // at threshold is not past it
    }

    #[test]
    fn failed_send_retries_next_tick() {
        let (mut w, mut s) = (watch(), FakeSender::default());
        let clock = FakeClock(Cell::new(1), 12);
        w.tick(0, 300.0, &[], Vec::new, &clock, &mut s);
        assert!(!w.tick(300 * 100_000, 300.0, &[], Vec::new, &clock, &mut s));
        assert!(w.last_sent.is_none());
        s.ok = true;
        assert!(w.tick(300 * 100_000, 300.0, &[], Vec::new, &clock, &mut s));
        assert_eq!(s.cards.len(), 2);
    }

    #[test]
    fn quota_and_tokens_parse() {
        assert_eq!(
            quota_left("usage\nclaude: 5h 31%, resets in 2h 3m · 7d 40%\nserver: cpu 3%"),
            ["claude 5h: 69% left", "claude 7d: 60% left"]
        );
        let m = r#"{"type":"message","message":{"role":"assistant","usage":{"totalTokens":7}}}"#;
        assert_eq!(line_tokens(m), 7);
        assert_eq!(line_tokens(&m.replace("assistant", "user")), 0);
    }
}
