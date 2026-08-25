# -*- coding: utf-8 -*-
"""Config -> shot specs for one item at a time. No engine, no file staging.

This used to write ComfyUI graphs directly, naming node ids in the middle of
what is really a merchandising decision. Now it emits
:class:`~vitrine.backends.base.ShotSpec` objects and the backend turns those
into whatever its engine wants, so the reference logic below is stated once and
survives a change of renderer.

Reference slots, and why each exists:
  0  the model's identity still            -- who she is
  1  the item's canonical product still    -- so wide and detail agree on the object
  2  the continuity frame from the last    -- so the outfit survives a set change
     accepted take
"""
from __future__ import annotations

from pathlib import Path

from . import prompts
from .backends.base import ShotSpec
from .schema import Config, Item
from .settings import Settings

W, H, LEN, STEPS, FPS = 768, 1344, 124, 12, 24.0


def _identity(cfg: Config, require: bool = True) -> Path:
    """The model's identity still.

    ``require`` is False for `vitrine check`, whose job is to validate a config
    and the shot plan it produces. Refusing to do that until the images exist
    confuses two failures -- a config that is wrong, and assets that are merely
    absent -- and made the first command in the README fail on a fresh clone.
    """
    p = Path(cfg.asset_dir) / cfg.model_ref
    if not p.is_file() and require:
        raise SystemExit(
            f"model reference still not found: {p}\n"
            f"  generate one with `vitrine model-ref <config>` or point "
            f"asset_dir/model_ref at an existing full-body photograph")
    return p


def product_still(st: Settings, cfg: Config, item: Item,
                  require: bool = True) -> Path | None:
    """The item's canonical still: the factory's photo, else the generated one."""
    if item.refs:
        src = Path(cfg.asset_dir) / item.refs[0]
        if not src.is_file():
            if require:
                raise SystemExit(f"{item.id}: product photo not found: {src}")
            return None
        return src
    still = st.job(cfg.episode) / "bible" / f"{item.id}.png"
    return still if still.is_file() else None


def _camera(cfg: Config, kind: str, text: str) -> tuple[str, str | None, float]:
    """Prefix the camera trigger and move onto a prompt, if this config asks for one.

    The trigger has to lead the prompt -- the LoRA's own README says so and a
    trial with it mid-document did not engage the movement. The move phrase
    rides right behind it, which is the shape the LoRA was trained on.
    """
    if not cfg.camera:
        return text, None, 1.0
    move = cfg.camera.move_for(kind)
    if not move:
        return text, None, 1.0
    return (f"{cfg.camera.trigger}, {move}. {text}",
            cfg.camera.lora, cfg.camera.strength)


def shots_for_item(st: Settings, cfg: Config, item: Item, wearing: str,
                   carry: Path | None, seed: int,
                   require_assets: bool = True) -> list[ShotSpec]:
    """The two takes for one item: the dressing action, then the product."""
    product = product_still(st, cfg, item, require_assets)
    refs = [_identity(cfg, require_assets)] + [p for p in (product, carry) if p]

    # The prompt must describe what was actually staged, not what the config
    # hoped for. Those differ in both directions: a generated packshot is a real
    # photograph the config never listed, and `check` runs with require_assets
    # False, so it reaches here with refs listed and no file behind them. Left
    # alone, the prompt would name a <Subject 2> and cite a <Picture 2> that the
    # backend never staged.
    item_for_prompt = item
    if product is None:
        if item.refs:
            item_for_prompt = Item(**{**item.__dict__, "refs": []})
    elif not item.refs:
        item_for_prompt = Item(**{**item.__dict__, "refs": ["__bible__"]})

    out = []
    for n, (kind, text) in enumerate((
            ("wide", prompts.wide(cfg, item_for_prompt, wearing, carry=bool(carry))),
            ("detail", prompts.detail(cfg, item_for_prompt, wearing, carry=bool(carry))))):
        text, lora, strength = _camera(cfg, kind, text)
        out.append(ShotSpec(
            id=f"{item.id}_{kind}", prompt=text, refs=list(refs), seed=seed + n,
            width=W, height=H, frames=LEN, fps=FPS, steps=STEPS,
            lora=lora, lora_strength=strength,
            note=f"{item.name} · {item.scene} · from {item.enter}"))
    return out


def shot_for_ending(cfg: Config, wearing: str, carry: Path | None,
                    seed: int, require_assets: bool = True) -> ShotSpec:
    """The closing take: identity plus continuity, no product reference."""
    refs = [_identity(cfg, require_assets)] + ([carry] if carry else [])
    text = prompts.ending(cfg, wearing, cfg.ending.scene, cfg.ending.action,
                          carry=bool(carry))
    text, lora, strength = _camera(cfg, "ending", text)
    return ShotSpec(id="ending", prompt=text, refs=refs, seed=seed,
                    width=W, height=H, frames=LEN, fps=FPS, steps=STEPS,
                    lora=lora, lora_strength=strength,
                    note=f"closing take · {cfg.ending.scene}")


# Cut lengths the editor derives from the beat grid, as (in-point, beats).
# Kept here rather than in edit.py so `check` can flag a grid that cannot work
# before anything is rendered -- the alternative is finding out at the edit
# stage, after forty minutes of GPU.
SEGMENTS = {"wide": (0.55, 8), "detail": (0.90, 7)}


def tempo_floor(cfg: Config) -> float:
    """The slowest tempo whose segments still fit inside a take, in BPM."""
    worst = (LEN / FPS - SEGMENTS["wide"][0]) / SEGMENTS["wide"][1]
    for tin, beats in SEGMENTS.values():
        worst = min(worst, (LEN / FPS - tin) / beats)
    if cfg.ending:
        worst = min(worst, (LEN / FPS - 0.30) / cfg.ending.beats)
    return round(60.0 / worst, 1)


def missing_assets(st: Settings, cfg: Config) -> list[str]:
    """Which referenced image files do not exist yet. Empty means ready to render."""
    out = []
    ident = Path(cfg.asset_dir) / cfg.model_ref
    if not ident.is_file():
        out.append(f"model_ref: {ident}  (vitrine model-ref <config>)")
    for item in cfg.items:
        if item.refs:
            src = Path(cfg.asset_dir) / item.refs[0]
            if not src.is_file():
                out.append(f"{item.id} product photo: {src}")
        elif not (st.job(cfg.episode) / "bible" / f"{item.id}.png").is_file():
            out.append(f"{item.id} packshot: not generated yet  (vitrine bible <config>)")
    return out


def plan(st: Settings, cfg: Config, require_assets: bool = True) -> list[ShotSpec]:
    """Every shot in the episode, in render order.

    Order is not cosmetic: item N+1's continuity reference is a frame of item
    N's accepted take, so the loop in run.py cannot be parallelised and this
    list cannot be reordered. The continuity paths are filled in as the run
    proceeds, which is why this returns the plan without them and run.py
    rebuilds each item's shots when its turn comes.
    """
    shots, wearing, seed = [], "", 26100001
    for item in cfg.items:
        shots += shots_for_item(st, cfg, item, wearing, None, seed, require_assets)
        seed += 2
        wearing = f"{wearing} and {item.garment}" if wearing else item.garment
    if cfg.ending:
        shots.append(shot_for_ending(cfg, wearing, None, seed, require_assets))
    return shots
