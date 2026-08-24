# -*- coding: utf-8 -*-
"""One canonical still per product, plus the episode's model reference.

The defect the packshot fixes: the wide take and the detail take are
independent generations, so each invented its own version of the necklace and
the two disagreed on how wide it read against her body. Pinning both takes to
the same still removes the disagreement at the source instead of describing the
same object twice in two prompts and hoping.

A factory that supplies its own SKU photographs skips this entirely -- their
photograph is the canonical still, and it is better than a generated one
because it is the thing actually being shipped.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .backends import still_backend
from .schema import Config
from .settings import Settings

PACKSHOT = (
    "Studio e-commerce packshot of {obj}, photographed alone on a plain seamless "
    "light grey background, centred and filling most of the frame, soft even "
    "frontal lighting, no shadows on the backdrop, colour accurate, sharp focus "
    "edge to edge, catalogue photography. {scale} "
    "No person, no model, no hands, no props, no text, no letters, no logo, no "
    "emblem, no brand mark, no interlocking letters, nothing resembling an "
    "existing luxury brand, no watermark."
)

MODEL_REF = (
    "Full-body studio photograph of a poised East Asian woman in her early "
    "thirties standing centred and facing the camera, her whole body and both "
    "shoes inside the frame with clear space above her head, relaxed neutral "
    "stance, arms loose at her sides, long straight black hair worn loose, "
    "restrained natural makeup, calm composed expression with her mouth closed. "
    "She wears a plain off-white fine-gauge knit top with three-quarter sleeves "
    "tucked into plain straight taupe trousers, and plain low-heel shoes. Plain "
    "seamless warm greige backdrop with no floor line. {light} {palette} Sharp "
    "focus edge to edge, 85mm portrait lens, editorial lookbook photography, "
    "colour accurate, no text, no letters, no logo, no watermark, no props, no "
    "other people."
)

PACKSHOT_SIZE = (1024, 1024)
MODEL_REF_SIZE = (768, 1344)
MODEL_REF_SEEDS = (510031, 510037, 510043, 510049)


def bible(st: Settings, cfg: Config) -> dict:
    """Generate the packshots this config still needs, and only those."""
    out = st.job(cfg.episode) / "bible"
    out.mkdir(parents=True, exist_ok=True)

    supplied = [i.id for i in cfg.items if i.refs]
    todo = [i for i in cfg.items
            if not i.refs and not (out / f"{i.id}.png").is_file()]
    report = {"episode": cfg.episode, "supplied": supplied, "generated": []}
    if not todo:
        return report

    backend = still_backend(st)
    w, h = PACKSHOT_SIZE
    for n, item in enumerate(todo):
        t0 = time.perf_counter()
        backend.still(PACKSHOT.format(obj=item.garment, scale=item.scale),
                      out / f"{item.id}.png", width=w, height=h, seed=70001 + n)
        report["generated"].append(
            {"id": item.id, "seconds": round(time.perf_counter() - t0, 1)})
    if hasattr(backend, "release"):
        backend.release()
    return report


def model_reference(st: Settings, cfg: Config) -> dict:
    """Four candidate reference stills; a human picks one and renames it.

    The reference has to be full body -- the video model only locks what the
    still actually shows -- and it has to already read as the right person for
    the clothes. A twenty-something grinning in high-key light is the wrong
    anchor for restrained tailoring before a single garment arrives, so the
    style's own light and palette go into the prompt.
    """
    from . import styles

    style = styles.get(cfg.style)
    out = Path(cfg.asset_dir)
    out.mkdir(parents=True, exist_ok=True)
    backend = still_backend(st)
    w, h = MODEL_REF_SIZE

    picks = []
    for n, seed in enumerate(MODEL_REF_SEEDS):
        t0 = time.perf_counter()
        p = out / f"cand_{n + 1}.png"
        backend.still(MODEL_REF.format(light=style.light, palette=style.palette),
                      p, width=w, height=h, seed=seed)
        picks.append({"file": p.name, "seed": seed,
                      "seconds": round(time.perf_counter() - t0, 1)})
    if hasattr(backend, "release"):
        backend.release()
    return {"style": style.id, "candidates": picks, "directory": str(out),
            "next": f"pick one and rename it to {cfg.model_ref}"}


def needs_bible(st: Settings, cfg: Config) -> bool:
    out = st.job(cfg.episode) / "bible"
    return any(not i.refs and not (out / f"{i.id}.png").is_file()
               for i in cfg.items)
