#!/usr/bin/env python3
"""Ambient sound for a walk-through, synthesized from noise and sines (no samples), timed from the capture log.

usage: synth.py LOG.json OUT.wav
Bed: a low rumble swelling slowly, a wind band, a faint drone. Events from the log: a soft footstep per step,
a blip per click, a thud per door crossing; muffled while inside a room. Silent until the first click, as a
browser starts sound only on a user gesture.
"""

import json
import sys
import wave

import numpy as np

SR = 44100


def band(x, lo, hi):
    f, fr = np.fft.rfft(x), np.fft.rfftfreq(len(x), 1 / SR)
    m = np.clip((fr - lo) / max(lo * 0.2, 1), 0, 1) * np.clip((hi - fr) / max(hi * 0.2, 1), 0, 1)
    return np.fft.irfft(f * m, len(x))


def gate(pts, n, tau=0.35):
    """A 0..1 level from [(time, value)] steps that ramps over tau seconds after each step, never before it."""
    g = np.zeros(n)
    for at, v in sorted(pts):
        g[int(at * SR) :] = v
    k = int(tau * SR)
    c = np.concatenate([np.zeros(k), np.cumsum(g)])
    return (c[k:] - c[:-k]) / k


def mix(log):
    n = int(log["frames"] / log["fps"] * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)  # fixed seed: the same sound on every render

    def noise(lo, hi):
        x = band(rng.standard_normal(n), lo, hi)
        return x / (np.abs(x).max() + 1e-9)

    def swell(period, phase, k=1.8):
        return (0.5 + 0.5 * np.sin(2 * np.pi * t / period + phase)) ** k

    mono = (
        noise(40, 700) * (0.25 + 0.75 * swell(9.7, 0.4)) * 0.55
        + noise(220, 900) * (0.35 + 0.65 * swell(23, 1)) * 0.2
        + (np.sin(2 * np.pi * 55 * t) + 0.6 * np.sin(2 * np.pi * 82.41 * t)) * 0.035
    )
    bed = np.stack([mono, np.roll(mono, 60)], 1)
    fx = np.zeros(n)

    def add(at, sig, gain):
        i = int(at * SR)
        j = min(n, i + len(sig))
        if 0 <= i < n:
            fx[i:j] += sig[: j - i] * gain

    def env(sec, decay):
        tt = np.arange(int(sec * SR)) / SR
        return tt, np.exp(-tt * decay)

    for k, at in enumerate(log["steps"]):
        tt, e = env(0.14, 34)
        add(
            at,
            np.sin(2 * np.pi * (78 + 10 * (k % 2)) * tt) * e
            + band(rng.standard_normal(len(tt)), 600, 2400) * e**2 * 0.5,
            0.36,
        )
    for at in log["clicks"]:
        tt, e = env(0.12, 55)
        add(at, np.sin(2 * np.pi * 880 * tt) * e * (1 - np.exp(-tt * 900)), 0.13)
    for at in log["doors"]:
        tt, e = env(0.35, 14)
        add(
            at,
            np.sin(2 * np.pi * 62 * tt) * e
            + 0.4 * band(rng.standard_normal(len(tt)), 200, 900) * e**2,
            0.35,
        )
    inside = gate(
        [(r["a"], 1) for r in log["rooms"]] + [(r["b"], 0) for r in log["rooms"] if "b" in r], n
    )[:, None]
    bed = (
        bed * (1 - inside)
        + np.stack([band(bed[:, c], 20, 380) for c in range(2)], 1) * 0.55 * inside
    )
    on = [(log["clicks"][0], 1)] if log["clicks"] else []
    out = (bed + fx[:, None]) * gate(on, n, 0.5)[:, None]
    out *= (np.clip(t / 0.3, 0, 1) * np.clip((t[-1] - t) / 1.4, 0, 1))[:, None]
    return out * 0.7 / (np.abs(out).max() + 1e-9)


if __name__ == "__main__":
    log = json.load(open(sys.argv[1]))
    pcm = (np.clip(mix(log), -1, 1) * 32767).astype("<i2")
    with wave.open(sys.argv[2], "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(sys.argv[2])
