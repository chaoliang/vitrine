# -*- coding: utf-8 -*-
"""The per-item loop: render, then hand the finished outfit to the next item.

Items render in order because item N+1's continuity reference is a frame of
item N's accepted take. That frame is the only thing carrying the accumulated
outfit across a set change -- the model keeps no state between calls, so without
it she changes clothes when the room changes. This is also why the loop cannot
be parallelised however idle the card looks.

Retakes reuse the same code path on purpose. A take that is re-rolled outside
the continuity chain it belongs to lands in a different outfit than its
neighbours, which is worse than the defect it was meant to fix.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .backends import shot_backend
from .backends.base import (ShotSpec, check_lora, check_picture_refs,
                            check_ref_slots)
from .build import shot_for_ending, shots_for_item
from .schema import Config
from .settings import Settings

SEED_BASE = 26100001
RETAKE_SEED_OFFSET = 500     # a retake must differ or it reproduces the take


def last_frame(st: Settings, src: Path, dst: Path) -> Path:
    """The final frame of an accepted take: she is wearing everything so far."""
    meta = json.loads(subprocess.run(
        [st.ffprobe, "-v", "error", "-print_format", "json", "-show_format",
         str(src)], capture_output=True, text=True, check=True).stdout)
    dur = float(meta["format"]["duration"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([st.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{max(0.0, dur - 0.30):.3f}", "-i", str(src),
                    "-frames:v", "1", str(dst)], check=True)
    return dst


def _accepted(st: Settings, cfg: Config, stem: str) -> Path | None:
    """The pinned take if one was accepted, else the newest that exists."""
    folder = st.takes_dir(cfg.episode)
    if not folder.is_dir():
        return None
    pinned = cfg.pin.get(stem)
    if pinned:
        p = folder / pinned
        return p if p.is_file() else None
    hits = sorted(folder.glob(f"{stem}_*.mp4"))
    return hits[-1] if hits else None


def render_episode(st: Settings, cfg: Config, only: set[str] | None = None) -> dict:
    """Render the whole episode, or just the named takes when ``only`` is given."""
    backend = shot_backend(st, cfg.episode)
    job = st.job(cfg.episode)
    takes = st.takes_dir(cfg.episode)
    takes.mkdir(parents=True, exist_ok=True)

    wearing, carry, seed = "", None, SEED_BASE
    log: list[dict] = []

    for item in cfg.items:
        shots = shots_for_item(st, cfg, item, wearing, carry, seed)
        if only is not None:
            shots = [s for s in shots if s.id in only]
            shots = [ShotSpec(**{**s.__dict__, "seed": s.seed + RETAKE_SEED_OFFSET})
                     for s in shots]
        if shots:
            check_ref_slots(backend, shots)
            check_lora(backend, shots)
            check_picture_refs(shots)
            print(f"[render] {item.id}: {len(shots)} take(s), "
                  f"{len(shots[0].refs)} refs"
                  f"{' (+continuity)' if carry else ''}", flush=True)
            for r in backend.render(cfg.episode, shots, takes):
                log.append({"take": r.shot_id, "seconds": r.seconds_elapsed,
                            "peak_vram_mib": r.peak_vram_mib,
                            "backend": r.backend, "path": str(r.path)})

        seed += 2
        wide = _accepted(st, cfg, f"{item.id}_wide")
        carry = (last_frame(st, wide, job / "bible" / f"carry_after_{item.id}.png")
                 if wide else None)
        wearing = f"{wearing} and {item.garment}" if wearing else item.garment

    if cfg.ending and (only is None or "ending" in only):
        shot = shot_for_ending(cfg, wearing, carry, seed)
        if only is not None:
            shot = ShotSpec(**{**shot.__dict__, "seed": shot.seed + RETAKE_SEED_OFFSET})
        check_ref_slots(backend, [shot])
        check_lora(backend, [shot])
        check_picture_refs([shot])
        print(f"[render] ending · {cfg.ending.scene}", flush=True)
        for r in backend.render(cfg.episode, [shot], takes):
            log.append({"take": r.shot_id, "seconds": r.seconds_elapsed,
                        "peak_vram_mib": r.peak_vram_mib,
                        "backend": r.backend, "path": str(r.path)})

    if only is not None:
        missing = only - {e["take"] for e in log}
        if missing:
            raise SystemExit(f"no such take(s) in this config: {sorted(missing)}")

    total = round(sum(e["seconds"] for e in log), 1)
    peaks = [e["peak_vram_mib"] for e in log if e["peak_vram_mib"]]
    report = {"episode": cfg.episode, "backend": backend.name,
              "takes": len(log), "render_seconds": total,
              "render_minutes": round(total / 60, 1),
              "peak_vram_mib": max(peaks) if peaks else None,
              "log": log}
    job.mkdir(parents=True, exist_ok=True)
    (job / "render-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
