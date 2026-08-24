# -*- coding: utf-8 -*-
"""Derive the cut's rhythm from whatever track you are licensed to use.

The editor lands every cut on a beat, which needs two numbers: how long a beat
lasts and where the first one falls. Those used to live in a JSON file copied
out of one job directory next to an mp3 of unrecorded provenance -- fine on the
machine that made it, a licensing problem the moment the pipeline is shared. So
the grid is derived here from your own audio instead of shipped with someone
else's.

The method is deliberately plain: short-time energy, its positive difference as
an onset strength, autocorrelation over a musical range of lags. It reports a
confidence, and a low confidence is worth believing -- a track with a soft or
rubato pulse will produce a grid that technically exists and cuts that feel
wrong. Override `period_s` and `first_beat_s` by hand when that happens.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

SR = 22050
HOP = 512
HOP_S = HOP / SR
BPM_MIN, BPM_MAX = 60.0, 200.0


def _pcm(ffmpeg: str, src: Path) -> "list[float]":
    """Mono float samples at SR, via ffmpeg so any container works."""
    r = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(src), "-f", "f32le", "-ac", "1",
         "-ar", str(SR), "-"],
        capture_output=True, check=True)
    import array
    a = array.array("f")
    a.frombytes(r.stdout)
    return a


def analyse(ffmpeg: str, src: Path) -> dict:
    try:
        import numpy as np
    except ImportError as e:
        raise SystemExit(
            "beat detection needs numpy (`pip install numpy`), or write the two "
            "numbers by hand:\n"
            '  {"period_s": 60/BPM, "first_beat_s": <seconds to the first beat>}'
        ) from e

    x = np.asarray(_pcm(ffmpeg, src), dtype=np.float32)
    if x.size < SR:
        raise SystemExit(f"{src} is shorter than a second of audio")

    n = x.size // HOP
    frames = x[: n * HOP].reshape(n, HOP)
    energy = np.log1p(np.sqrt((frames ** 2).mean(axis=1)) * 1000.0)
    onset = np.diff(energy, prepend=energy[:1])
    onset[onset < 0] = 0.0
    onset -= onset.mean()

    lag_min = max(2, int(round((60.0 / BPM_MAX) / HOP_S)))
    lag_max = min(n - 2, int(round((60.0 / BPM_MIN) / HOP_S)))
    if lag_max <= lag_min:
        raise SystemExit(f"{src} is too short to find a tempo")

    ac = np.correlate(onset, onset, mode="full")[onset.size - 1:]
    window = ac[lag_min:lag_max + 1]
    lag = int(np.argmax(window)) + lag_min
    confidence = float(window.max() / (np.abs(window).mean() + 1e-9)) / 10.0

    period_s = lag * HOP_S
    # phase: slide a pulse train over the envelope and keep the best offset
    offsets = np.arange(0, lag)
    scores = [onset[o::lag].sum() for o in offsets]
    first_beat_s = float(int(offsets[int(np.argmax(scores))]) * HOP_S)

    return {
        "file": str(src),
        "bpm": round(60.0 / period_s, 1),
        "period_s": round(period_s, 4),
        "first_beat_s": round(first_beat_s, 4),
        "autocorr_confidence": round(min(confidence, 1.0), 3),
        "grid_head": [round(first_beat_s + i * period_s, 3) for i in range(8)],
    }


def write(ffmpeg: str, src: Path, dst: Path) -> dict:
    grid = analyse(ffmpeg, src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")
    return grid


def _duration(ffprobe: str, p: Path) -> float:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def bed(ffmpeg: str, ffprobe: str, src: Path, dst: Path, target_s: float,
        beats_per_bar: int = 4, fade_out_s: float = 1.2) -> dict:
    """Extend a short track to `target_s` by looping it on a bar boundary.

    Generative music models tend to end a piece when they feel like it -- the
    local MiniMax Music 3 build tops out around 22 seconds however long you ask
    for -- so a bed that has to run under a 26-second cut has to be looped. The
    loop point is placed on a whole number of bars starting from the detected
    first beat, which is the one place a repeat is least audible: the seam lands
    exactly where the next downbeat was going to be anyway.

    Trimming to the bar also throws away the model's intro and outro, which is
    what you want in an underscore.
    """
    grid = analyse(ffmpeg, src)
    period, first = grid["period_s"], grid["first_beat_s"]
    bar = period * beats_per_bar
    usable = _duration(ffprobe, src) - first
    bars = int(usable // bar)
    if bars < 1:
        raise SystemExit(
            f"{src} holds less than one {beats_per_bar}-beat bar after its first "
            f"beat ({usable:.1f}s < {bar:.1f}s); nothing to loop")
    body = bar * bars
    loops = max(1, int(-(-target_s // body)))     # ceil

    dst.parent.mkdir(parents=True, exist_ok=True)
    trimmed = dst.with_suffix(".loop.wav")
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-ss", f"{first:.4f}", "-t", f"{body:.4f}",
         "-i", str(src), "-c:a", "pcm_s16le", str(trimmed)], check=True)
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-stream_loop", str(loops - 1),
         "-i", str(trimmed), "-t", f"{target_s:.3f}",
         "-af", f"afade=t=out:st={max(0.0, target_s - fade_out_s):.3f}:"
                f"d={fade_out_s}",
         "-c:a", "libmp3lame", "-b:a", "320k", str(dst)], check=True)
    trimmed.unlink(missing_ok=True)

    out_grid = {"source": str(src), "bpm": grid["bpm"], "period_s": period,
                "first_beat_s": 0.0,
                "autocorr_confidence": grid["autocorr_confidence"],
                "grid_head": [round(i * period, 3) for i in range(8)]}
    return {"bed": str(dst), "seconds": round(_duration(ffprobe, dst), 2),
            "loop_body_s": round(body, 3), "bars_per_loop": bars,
            "loops": loops, "grid": out_grid}
