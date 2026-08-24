# -*- coding: utf-8 -*-
"""Backend registry: a name in the config becomes an object here.

Adding a hosted video model means adding one module with a ``render`` method and
one line below. Nothing outside this package needs to change -- ``build.py``
already speaks :class:`~vitrine.backends.base.ShotSpec`, which is prompt,
references, size, length, seed and nothing engine-specific.
"""
from __future__ import annotations

from ..settings import Settings
from .base import BackendError, RenderResult, ShotBackend, ShotSpec, StillBackend

KNOWN = ("comfy_h3", "null")


def shot_backend(st: Settings, episode: str) -> ShotBackend:
    if st.backend == "comfy_h3":
        from .comfy_h3 import ComfyH3Backend
        if not st.comfy_root or not st.workflow_template:
            raise SystemExit(
                "backend comfy_h3 needs both comfy_root and workflow_template "
                "in vitrine.toml")
        return ComfyH3Backend(comfy_root=st.comfy_root,
                              workflow_template=st.workflow_template,
                              logs_dir=st.job(episode) / "logs")
    if st.backend == "null":
        from .null import NullBackend
        return NullBackend(ffmpeg=st.ffmpeg, font=st.font_regular)
    raise SystemExit(f"unknown backend {st.backend!r}; known: {', '.join(KNOWN)}")


def still_backend(st: Settings) -> StillBackend:
    if st.backend == "comfy_h3":
        # Stills come from a diffusers pipeline, not from ComfyUI, so this is a
        # separate import kept out of the module top level: torch takes seconds
        # to load and most runs never need it.
        from .diffusers_still import DiffusersStills
        if not st.still_model:
            raise SystemExit(
                "generating packshots needs still_model in vitrine.toml, or "
                "supply the factory's own photographs in the config's refs")
        return DiffusersStills(model=st.still_model)
    if st.backend == "null":
        from .null import NullStills
        return NullStills(ffmpeg=st.ffmpeg, font=st.font_regular)
    raise SystemExit(f"unknown backend {st.backend!r}; known: {', '.join(KNOWN)}")


__all__ = ["shot_backend", "still_backend", "ShotSpec", "RenderResult",
           "BackendError", "ShotBackend", "StillBackend", "KNOWN"]
