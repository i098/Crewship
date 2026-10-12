//! `crewboard serve`: the Unix socket daemon around `Board`.
//!
//! Wire protocol: one JSON request per line; each answers with one JSON line
//! (`hist` with lines ended by `{"end":true}`), except `sub`.
//! - `{"op":"pub","topic":T,"body":B,"from":F}` -> `{"ok":true,"seq":N}`; a body over
//!   `--max-msg` bytes or a `from` over 64 bytes is `{"ok":false,"error":"too_large"}`
//! - `{"op":"hist","topic":T,"n":N}`, `{"op":"topics"}`, `{"op":"stat"}`
//! - `{"op":"sub","topics":[T..],"since":N,"boot":ID}` streams until either side closes.
//!   The first line is `{"boot":ID,"seq":N}`: the board's boot id and seq. With `since`,
//!   retained messages above it follow, led by `{"gap":true,"oldest":N}` when some were
//!   evicted. When `boot` differs from the board's, or `since` is above its seq, the board
//!   restarted: the gap carries `"restarted":true` and all retained messages follow.
//!   `boot` without `since` is ignored. A subscriber that falls behind gets
//!   `{"error":"slow"}` when the socket has room, and is disconnected.

use std::io;
use std::os::unix::fs::FileTypeExt;
use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::unix::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::{UnixListener, UnixStream};

use crate::board::{Board, Feed, Limits, Subscription};

type Shared = Arc<Mutex<Board>>;

fn lock(board: &Shared) -> MutexGuard<'_, Board> {
    board.lock().expect("board lock poisoned")
}

fn err(e: &str) -> Value {
    json!({"ok": false, "error": e})
}

pub fn run(path: &Path, limits: Limits) -> io::Result<()> {
    if std::os::unix::net::UnixStream::connect(path).is_ok() {
        return Err(io::Error::new(io::ErrorKind::AddrInUse, format!("{} already serves a board", path.display())));
    }
    // A socket nobody answers on is left by a stopped daemon; replace it, but never another file type.
    match std::fs::symlink_metadata(path) {
        Ok(m) if m.file_type().is_socket() => std::fs::remove_file(path)?,
        Ok(_) => return Err(io::Error::new(io::ErrorKind::AlreadyExists, format!("{} is not a socket", path.display()))),
        Err(_) => {}
    }
    tokio::runtime::Builder::new_current_thread().enable_all().build()?.block_on(async {
        // SAFETY: umask and getuid only read or set this process's own attributes.
        // umask 0177 makes bind create the socket as 0600, with no window at a wider mode.
        let old = unsafe { libc::umask(0o177) };
        let listener = UnixListener::bind(path);
        unsafe { libc::umask(old) };
        let listener = listener?;
        let uid = unsafe { libc::getuid() };
        eprintln!("crewboard: serving {}", path.display());
        let board = Arc::new(Mutex::new(Board::new(limits)));
        loop {
            match listener.accept().await {
                Ok((stream, _)) => {
                    tokio::spawn(conn(stream, board.clone(), uid));
                }
                Err(e) => {
                    // Usually out of file descriptors: back off instead of spinning.
                    eprintln!("crewboard: accept: {e}");
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }
            }
        }
    })
}

/// Serves one connection: one JSON request per line until EOF or a `sub`.
async fn conn(stream: UnixStream, board: Shared, uid: u32) -> io::Result<()> {
    let cred = stream.peer_cred()?;
    if cred.uid() != uid {
        return Ok(());
    }
    let pid = cred.pid().unwrap_or(0);
    // JSON escapes can grow a body six-fold (`\u0000`); the rest of a request is small.
    let max_line = lock(&board).limits.max_msg * 6 + 4096;
    let (r, mut w) = stream.into_split();
    let mut r = BufReader::new(r);
    let mut line = Vec::new();
    loop {
        line.clear();
        let n = (&mut r).take(max_line as u64).read_until(b'\n', &mut line).await?;
        if n == 0 {
            return Ok(());
        }
        if n == max_line && line.last() != Some(&b'\n') {
            return put(&mut w, &format!("{}\n", err("too_large"))).await;
        }
        let req: Value = serde_json::from_slice(&line).unwrap_or(Value::Null);
        let reply = if req["op"] == "sub" {
            match subscribe(&board, &req) {
                Ok(sub) => return stream_sub(r, w, board, sub).await,
                Err(e) => format!("{}\n", err(e)),
            }
        } else {
            answer(&board, pid, &req)
        };
        put(&mut w, &reply).await?;
    }
}

fn subscribe(board: &Shared, req: &Value) -> Result<Subscription, &'static str> {
    let topics = req["topics"].as_array().and_then(|a| a.iter().map(|t| t.as_str().map(String::from)).collect());
    let boot = match &req["boot"] {
        Value::Null => None,
        Value::String(b) => Some(b.as_str()),
        _ => return Err("bad_request"),
    };
    lock(board).subscribe(topics.ok_or("bad_request")?, req["since"].as_u64(), boot)
}

/// The reply lines to any request but `sub`, newline included.
fn answer(board: &Shared, pid: i32, req: &Value) -> String {
    let mut b = lock(board);
    let reply = match req["op"].as_str() {
        Some("pub") => match (req["topic"].as_str(), req["body"].as_str()) {
            (Some(topic), Some(body)) => match b.publish(topic, req["from"].as_str(), pid, body) {
                Ok(seq) => json!({"ok": true, "seq": seq}),
                Err(e) => err(e),
            },
            _ => err("bad_request"),
        },
        Some("hist") => {
            let lines = b.history(req["topic"].as_str().unwrap_or(""), req["n"].as_u64().unwrap_or(50) as usize);
            return lines.concat() + "{\"end\":true}\n";
        }
        Some("topics") => b.topics(),
        Some("stat") => b.stat(),
        _ => err("bad_request"),
    };
    format!("{reply}\n")
}

/// A stalled write ends the connection after this long.
const WRITE_TIMEOUT: Duration = Duration::from_secs(5);

async fn put(w: &mut OwnedWriteHalf, line: &str) -> io::Result<()> {
    tokio::time::timeout(WRITE_TIMEOUT, w.write_all(line.as_bytes())).await.unwrap_or_else(|_| Err(io::ErrorKind::TimedOut.into()))
}

/// Streams replay then live messages until the client closes its end or falls behind.
async fn stream_sub(mut r: BufReader<OwnedReadHalf>, mut w: OwnedWriteHalf, board: Shared, sub: Subscription) -> io::Result<()> {
    let (id, replay, Feed { mut rx, slow, hello }) = sub;
    let reader = tokio::spawn(async move {
        let mut sink = [0u8; 256];
        while matches!(r.read(&mut sink).await, Ok(n) if n > 0) {}
    });
    let stop_reader = reader.abort_handle();
    let shared = board.clone();
    let writer = tokio::spawn(async move {
        let mut lines = std::iter::once(hello).chain(replay);
        // (write timed out, notice may follow the last whole line)
        let (timed_out, notice) = loop {
            let next = tokio::select! {
                biased;
                _ = slow.notified() => break (false, true),
                next = async { match lines.next() { Some(line) => Some(line), None => rx.recv().await } } => next,
            };
            let Some(line) = next else { break (false, true) };
            let mut write = std::pin::pin!(put(&mut w, &line));
            // A line in flight is finished, never cut, so the notice cannot land inside it.
            let (wrote, dropped_slow) = tokio::select! {
                wrote = &mut write => (wrote, false),
                _ = slow.notified() => {
                    rx.close();
                    while rx.try_recv().is_ok() {}
                    (write.await, true)
                }
            };
            if let Err(e) = wrote {
                break (e.kind() == io::ErrorKind::TimedOut, false);
            }
            if dropped_slow {
                break (false, true);
            }
        };
        // The queue is full: free it now instead of delivering it.
        drop(rx);
        if notice {
            let _ = w.as_ref().try_write(b"{\"error\":\"slow\"}\n");
        }
        let _ = w.shutdown().await;
        lock(&shared).unsubscribe(id, timed_out);
        drop(w);
        stop_reader.abort();
    });
    let _ = reader.await;
    writer.abort();
    lock(&board).unsubscribe(id, false);
    Ok(())
}
