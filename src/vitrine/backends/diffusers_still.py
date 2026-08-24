# -*- coding: utf-8 -*-
"""Local text-to-image stills through diffusers, for packshots and the model ref.

Kept apart from the video backend because it is a different model with a
different memory profile, and because a config whose items all carry the
factory's own photographs never needs it at all. torch is imported inside the
call for the same reason: paying seconds of import time on every run to load a
pipeline most runs skip is a bad trade.

The offload choice is made from free VRAM at call time rather than from a
setting. Model offload is faster; sequential offload is what keeps this working
on a card that is already holding a video model.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .base import BackendError

MODEL_OFFLOAD_FREE_GIB = 11.0


@dataclass
class DiffusersStills:
    model: Path
    steps: int = 6
    guidance: float = 1.0

    name: str = "diffusers"

    def __post_init__(self) -> None:
        self._pipe = None

    def _pipeline(self):
        if self._pipe is not None:
            return self._pipe
        try:
            import torch
            from diffusers import Flux2KleinPipeline
        except ImportError as e:
            raise BackendError(
                "still", f"generating packshots needs torch and diffusers "
                         f"installed in this environment ({e}). Either install "
                         f"them, or supply product photographs in the config so "
                         f"no packshot has to be generated.") from e
        if not self.model.exists():
            raise BackendError("still", f"still model not found: {self.model}")
        pipe = Flux2KleinPipeline.from_pretrained(
            self.model, torch_dtype=torch.bfloat16, local_files_only=True)
        free_gib = torch.cuda.mem_get_info()[0] / 1024 ** 3
        if free_gib >= MODEL_OFFLOAD_FREE_GIB:
            pipe.enable_model_cpu_offload()
        else:
            pipe.enable_sequential_cpu_offload()
        self._pipe = pipe
        return pipe

    def still(self, prompt: str, out: Path, *, width: int, height: int,
              seed: int) -> Path:
        import torch

        out.parent.mkdir(parents=True, exist_ok=True)
        img = self._pipeline()(
            prompt=prompt, height=height, width=width,
            num_inference_steps=self.steps, guidance_scale=self.guidance,
            generator=torch.Generator("cpu").manual_seed(seed)).images[0]
        img.save(out)
        return out

    def release(self) -> None:
        """Hand the card back before a video render wants all of it."""
        if self._pipe is None:
            return
        import torch
        del self._pipe
        self._pipe = None
        torch.cuda.empty_cache()
