# -*- coding: utf-8 -*-
"""A renderer that renders nothing, for proving the wiring without a GPU.

Every stage after the render -- the beat-grid cut, the price chips, the spec
cards, the outfit clash check, the AIGC label and its read-back -- is ordinary
Python and ffmpeg and has no business needing a 24GB card to exercise. This
backend produces takes of exactly the right dimensions, duration and frame rate
with the shot id burned into them, so the editor has something real to cut and
an operator can see at a glance which take landed where.

It is a wiring test, never a delivery path. Each clip says so on screen, the
backend name appears in every report, and ``deliver.py`` refuses to label a cut
that was assembled from placeholders.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Sequence

from .base import BackendError, RenderResult, ShotSpec

# Deterministic per-shot colour so two runs of the same plan look identical and
# a diff of the output is meaningful.
_PALETTE = ["#2E3B3F", "#3F3630", "#2B3340", "#3A2F38", "#31402F", "#403A2B"]

MARKER = "vitrine-null-placeholder"


class NullBackend:
    name = "null"
    ref_slots = 3
    supports_lora = False

    def __init__(self, ffmpeg: str, font: str):
        self.ffmpeg = ffmpeg
        self.font = font

    # ffmpeg's drawtext takes a filter-graph string, so the path separators and
    # the colon after a Windows drive letter both have to be escaped.
    @staticmethod
    def _escape(p: str) -> str:
        return p.replace("\\", "/").replace(":", r"\:")

    def render(self, episode: str, shots: Sequence[ShotSpec],
               out_dir: Path) -> list[RenderResult]:
        out_dir.mkdir(parents=True, exist_ok=True)
        results: list[RenderResult] = []
        for n, shot in enumerate(shots):
            dst = out_dir / f"{shot.id}_{n + 1:05d}_.mp4"
            colour = _PALETTE[shot.seed % len(_PALETTE)]
            # three short lines rather than one long one: at 768px wide a single
            # line of this runs off both edges and the frame reads as empty
            font = self._escape(self.font)
            lines = [(shot.id, 0.42, 34, 0.90),
                     (f"seed {shot.seed}", 0.47, 24, 0.55),
                     (MARKER, 0.51, 22, 0.45),
                     ("frame %{n}", 0.56, 20, 0.35)]
            vf = ",".join(
                f"drawtext=fontfile='{font}':text='{text}':"
                f"fontcolor=white@{alpha}:fontsize={size}:"
                f"x=(w-text_w)/2:y=h*{y}"
                for text, y, size, alpha in lines)
            cmd = [
                self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi",
                "-i", f"color=c={colour}:s={shot.width}x{shot.height}:"
                      f"r={shot.fps}:d={shot.seconds}",
                "-vf", vf, "-frames:v", str(shot.frames),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                "-pix_fmt", "yuv420p",
                # burned text is for a human watching; this tag is what the
                # delivery gate reads, so a placeholder can never be labelled
                # and shipped as generated footage
                "-metadata", f"comment={MARKER}",
                str(dst),
            ]
            t0 = time.perf_counter()
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise BackendError(shot.id, f"ffmpeg failed: {r.stderr.strip()[:400]}")
            results.append(RenderResult(shot_id=shot.id, path=dst,
                                        seconds_elapsed=round(time.perf_counter() - t0, 2),
                                        backend=self.name))
        return results


class NullStills:
    """Flat panels standing in for packshots, same contract as the real one."""

    name = "null"

    def __init__(self, ffmpeg: str, font: str):
        self.ffmpeg = ffmpeg
        self.font = font

    def still(self, prompt: str, out: Path, *, width: int, height: int,
              seed: int) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        colour = _PALETTE[seed % len(_PALETTE)]
        head = prompt.strip().split(",")[0][:48].replace("'", "")
        vf = (f"drawtext=fontfile='{NullBackend._escape(self.font)}':"
              f"text='{head}':fontcolor=white@0.85:fontsize=30:"
              f"x=(w-text_w)/2:y=(h-text_h)/2")
        r = subprocess.run(
            [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"color=c={colour}:s={width}x{height}",
             "-vf", vf, "-frames:v", "1", str(out)],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise BackendError("still", f"ffmpeg failed: {r.stderr.strip()[:400]}")
        return out
