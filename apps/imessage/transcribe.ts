// Voice memos and audio attachments (.caf, .m4a, .amr, .mp3 ...): ffmpeg makes a 16 kHz mono wav, whisperx (local, CPU,
// int8) turns it into text. Free of spectrum-ts, so tests run without it. Local only: no API is called.
import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";

const AUDIO_NAME = /\.(caf|m4a|amr|mp3|aac|wav|ogg|oga|opus|flac|aiff?)$/i;

// True for an attachment that is sound: an audio/* type, or an audio file name (iMessage often sends .caf as
// application/octet-stream).
export const isAudio = (c: { mimeType?: string; name?: string }) => /^audio\//i.test(c.mimeType ?? "") || AUDIO_NAME.test(c.name ?? "");

export type Heard = { text: string; seconds: number };

// What `transcribe` needs from the host. `track` registers each child so a bridge stop can kill it.
export type Listen = { whisperx: string; model: string; timeoutMs: number; track: <T extends Bun.Subprocess>(proc: T) => T };

export const listenFrom = (env: Record<string, string | undefined>, track: Listen["track"]): Listen => ({
  whisperx: env.FM_IMESSAGE_WHISPERX || `${env.HOME}/.cache/watch/whisperx-venv/bin/whisperx`,
  model: env.FM_IMESSAGE_WHISPER_MODEL || "small",
  timeoutMs: Number(env.FM_IMESSAGE_TRANSCRIBE_MS || 120_000), // a cold whisperx start took 42 s on this host
  track,
});

async function run(listen: Listen, cmd: string[]) {
  const proc = listen.track(Bun.spawn(cmd, { stdin: "ignore", stdout: "ignore", stderr: "pipe", timeout: listen.timeoutMs, killSignal: "SIGKILL" }));
  const [err, exit] = await Promise.all([new Response(proc.stderr).text(), proc.exited]);
  if (exit !== 0) throw new Error(`${cmd[0]!.split("/").pop()} failed (exit ${exit}): ${err.trim().split("\n").at(-1) ?? ""}`);
}

// The words of the audio file at `path` and its length. Throws when ffmpeg or whisperx fails or runs out of time.
export async function transcribe(path: string, listen: Listen): Promise<Heard> {
  const dir = mkdtempSync(`${tmpdir()}/fm-imessage-listen-`);
  try {
    const wav = `${dir}/in.wav`;
    await run(listen, ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav]);
    await run(listen, [listen.whisperx, wav, "--model", listen.model, "--device", "cpu", "--compute_type", "int8", "--no_align",
      "--vad_method", "silero", "--output_format", "txt", "--output_dir", dir, "--verbose", "False"]);
    return { text: readFileSync(`${dir}/in.txt`, "utf8").replace(/\s+/g, " ").trim(), seconds: Math.round((statSync(wav).size - 44) / 32000) };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
