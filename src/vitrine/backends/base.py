# -*- coding: utf-8 -*-
"""What a renderer has to provide, and nothing more.

The old pipeline had no seam here at all: ``build.py`` wrote a ComfyUI workflow
graph directly, naming node ids like ``"19"`` and ``"21"``, and ``run.py``
shelled out to a script that started a local ComfyUI. Swapping the renderer
meant rewriting both. So the shot description stops at what any video model
needs -- a prompt, reference images, a size, a length, a seed -- and each
backend is responsible for whatever its own engine wants on top of that.

Two roles, kept separate because in practice they are two different models:

  StillBackend   text -> one image        (product packshots, the model reference)
  ShotBackend    ShotSpec -> one mp4      (the takes)

A backend that can only do one of them is legitimate; the pipeline asks for the
still backend only when a config has items without supplied photographs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class ShotSpec:
    """One take, described in terms every video model understands.

    ``refs`` is ordered and the order is load-bearing: slot 0 is the model's
    identity still, slot 1 the item's canonical product still, slot 2 the
    continuity frame from the previously accepted take. A backend that supports
    fewer reference slots must say so rather than silently dropping the tail --
    dropping slot 2 is what makes her change clothes when the room changes.
    """

    id: str                 # "dress_wide", "boots_detail", "ending"
    prompt: str
    refs: list[Path]
    seed: int
    width: int
    height: int
    frames: int
    fps: float
    steps: int
    note: str = ""
    # Optional camera-movement LoRA. A backend that cannot load LoRAs must say
    # so rather than dropping it: a shot rendered without the movement it was
    # written for is not the shot, and the prompt already carries the trigger.
    lora: str | None = None
    lora_strength: float = 1.0

    @property
    def seconds(self) -> float:
        return round(self.frames / self.fps, 3)

    def to_json(self) -> dict:
        return {"id": self.id, "seed": self.seed, "width": self.width,
                "height": self.height, "frames": self.frames, "fps": self.fps,
                "seconds": self.seconds, "steps": self.steps, "note": self.note,
                "refs": [str(r) for r in self.refs],
                "lora": self.lora, "lora_strength": self.lora_strength,
                "prompt_chars": len(self.prompt)}


@dataclass
class RenderResult:
    """What came back, including the measurements worth keeping."""

    shot_id: str
    path: Path
    seconds_elapsed: float = 0.0
    peak_vram_mib: int | None = None
    backend: str = ""


@runtime_checkable
class ShotBackend(Protocol):
    name: str
    #: how many reference images this engine actually honours
    ref_slots: int
    #: whether this engine can load a camera-movement LoRA
    supports_lora: bool

    def render(self, episode: str, shots: Sequence[ShotSpec],
               out_dir: Path) -> list[RenderResult]:
        """Render every shot and return them in the order given.

        Must raise rather than return a short list: a caller that receives four
        results for five shots has no way to tell which one is missing.
        """
        ...


@runtime_checkable
class StillBackend(Protocol):
    name: str

    def still(self, prompt: str, out: Path, *, width: int, height: int,
              seed: int) -> Path:
        ...


class BackendError(RuntimeError):
    """A render failed. Carries the shot so the caller can name it."""

    def __init__(self, shot_id: str, message: str):
        super().__init__(f"{shot_id}: {message}")
        self.shot_id = shot_id


def check_lora(backend: ShotBackend, shots: Sequence[ShotSpec]) -> None:
    """Refuse a job whose camera movement this engine would silently drop.

    Dropping it does not fail -- it renders a fixed-camera take from a prompt
    that opens with "camera motion, slow push-in". The frame is stable, the
    file is the right length, and nothing says the movement is missing.
    """
    if getattr(backend, "supports_lora", False):
        return
    wanted = sorted({s.lora for s in shots if s.lora})
    if wanted:
        raise BackendError(
            "plan",
            f"{backend.name} cannot load a LoRA, but this config asks for "
            f"{', '.join(wanted)}. Rendering anyway would produce fixed-camera "
            f"takes from prompts that open with the movement trigger -- right "
            f"length, wrong shot. Drop the config's `camera` block, or render "
            f"on a backend that loads LoRAs.")


def check_ref_slots(backend: ShotBackend, shots: Sequence[ShotSpec]) -> None:
    """Refuse a job whose continuity references this engine would discard."""
    worst = max((len(s.refs) for s in shots), default=0)
    if worst > backend.ref_slots:
        raise BackendError(
            "plan",
            f"{backend.name} honours {backend.ref_slots} reference image(s) but "
            f"this job needs {worst}. Slot 2 is the continuity frame -- without "
            f"it the outfit resets at every set change. Pick a backend with "
            f"enough slots rather than letting it drop silently.")
