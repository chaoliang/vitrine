# -*- coding: utf-8 -*-
"""Every machine-specific path in one place, resolved once.

Before this module existed, thirteen module-level constants across eight files
each named an absolute path on one Windows workstation, and the editor quietly
read its beat grid and its music out of an unrelated job directory. A clone on
any other machine imported fine and then died at the first file access -- or
worse, at the last one, after forty minutes of GPU.

Resolution order for every value, first hit wins:

  1. an environment variable, ``VITRINE_<FIELD>`` in upper case
  2. a TOML file -- ``$VITRINE_CONFIG``, else ``./vitrine.toml``, else
     ``~/.config/vitrine/vitrine.toml``
  3. a platform default

Nothing here guesses a render backend. A missing backend is an error with the
two ways to fix it, never a silent fall back to placeholder footage: a run that
prints "done" and hands over colour bars is worse than one that stops.
"""
from __future__ import annotations

import os
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent

# A CJK face is required: every price chip and spec card renders Chinese. These
# are searched in order and the first that exists wins.
FONT_CANDIDATES = {
    "bold": [
        r"C:\Windows\Fonts\msyhbd.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ],
    "regular": [
        r"C:\Windows\Fonts\msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ],
}


def _config_file() -> Path | None:
    for cand in (os.environ.get("VITRINE_CONFIG"),
                 "vitrine.toml",
                 Path.home() / ".config" / "vitrine" / "vitrine.toml"):
        if not cand:
            continue
        p = Path(cand).expanduser()
        if p.is_file():
            return p
    return None


def _load_toml() -> dict:
    p = _config_file()
    if not p:
        return {}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{p} is not valid TOML: {e}") from e


def _first_existing(paths: list[str]) -> str | None:
    return next((p for p in paths if Path(p).is_file()), None)


@dataclass
class Settings:
    """Resolved locations. Build one with :func:`load`, never by hand."""

    # where work and output live
    jobs_dir: Path
    # tools
    ffmpeg: str
    ffprobe: str
    # typography for chips and spec cards
    font_bold: str
    font_regular: str
    # the cut's rhythm and music -- shipped with the package, overridable
    beatgrid: Path
    bgm: Path
    # which renderer produces takes and stills
    backend: str
    # backend-specific, only meaningful for comfy_h3
    comfy_root: Path | None = None
    workflow_template: Path | None = None
    still_model: Path | None = None
    render_python: str | None = None
    extra: dict = field(default_factory=dict)

    # ---- derived ----
    @property
    def comfy_input(self) -> Path:
        if not self.comfy_root:
            raise SystemExit("comfy_root is not configured; see vitrine.example.toml")
        return self.comfy_root / "ComfyUI" / "input"

    @property
    def comfy_output(self) -> Path:
        if not self.comfy_root:
            raise SystemExit("comfy_root is not configured; see vitrine.example.toml")
        return self.comfy_root / "ComfyUI" / "output"

    def job(self, episode: str) -> Path:
        return self.jobs_dir / episode

    def takes_dir(self, episode: str) -> Path:
        """Where finished takes land. Backend-dependent by design: ComfyUI writes
        into its own output tree, everything else writes into the job."""
        if self.backend == "comfy_h3":
            return self.comfy_output / episode
        return self.job(episode) / "takes"

    def describe(self) -> dict:
        return {
            "backend": self.backend,
            "jobs_dir": str(self.jobs_dir),
            "ffmpeg": self.ffmpeg,
            "font_bold": self.font_bold,
            "beatgrid": str(self.beatgrid),
            "bgm": str(self.bgm),
            "comfy_root": str(self.comfy_root) if self.comfy_root else None,
        }


def _get(key: str, toml: dict, default=None):
    env = os.environ.get(f"VITRINE_{key.upper()}")
    if env:
        return env
    if key in toml:
        return toml[key]
    return default


def load(backend_override: str | None = None) -> Settings:
    """Resolve settings from env, TOML and platform defaults, in that order."""
    t = _load_toml()

    jobs_dir = Path(str(_get("jobs_dir", t, Path.home() / "vitrine-jobs"))).expanduser()

    ffmpeg = str(_get("ffmpeg", t, "")) or shutil.which("ffmpeg") or ""
    ffprobe = str(_get("ffprobe", t, "")) or shutil.which("ffprobe") or ""
    if not ffmpeg or not ffprobe:
        raise SystemExit(
            "ffmpeg and ffprobe are required and were not found on PATH.\n"
            "  install them, or set VITRINE_FFMPEG / VITRINE_FFPROBE, or put\n"
            "  ffmpeg = \"...\" and ffprobe = \"...\" in vitrine.toml")

    bold = str(_get("font_bold", t, "")) or _first_existing(FONT_CANDIDATES["bold"])
    regular = str(_get("font_regular", t, "")) or _first_existing(FONT_CANDIDATES["regular"])
    if not bold or not regular:
        raise SystemExit(
            "no CJK font found -- price chips and spec cards render Chinese.\n"
            f"  looked for: {', '.join(FONT_CANDIDATES['bold'][:3])}\n"
            "  set VITRINE_FONT_BOLD / VITRINE_FONT_REGULAR to a .ttc or .otf")

    audio = PROJECT_ROOT / "assets" / "audio"
    # Your own grid if you have derived one, otherwise the neutral 120 BPM
    # placeholder that ships with the package. The repo deliberately does not
    # carry a grid belonging to a real track: it would name an mp3 nobody else
    # has, at a tempo nobody else's takes can hold.
    default_grid = (audio / "beatgrid.json" if (audio / "beatgrid.json").is_file()
                    else audio / "beatgrid.default.json")
    beatgrid = Path(str(_get("beatgrid", t, default_grid))).expanduser()
    bgm = Path(str(_get("bgm", t, audio / "bgm.mp3"))).expanduser()

    backend = backend_override or str(_get("backend", t, "")) or _auto_backend(t)

    comfy_root = _get("comfy_root", t)
    comfy_root = Path(str(comfy_root)).expanduser() if comfy_root else None
    # The H3 graph ships with the package; a user template overrides it.
    tmpl = _get("workflow_template", t) or (
        PROJECT_ROOT / "assets" / "workflows" / "h3_ref2va.api.json")
    still_model = _get("still_model", t)
    return Settings(
        jobs_dir=jobs_dir, ffmpeg=ffmpeg, ffprobe=ffprobe,
        font_bold=bold, font_regular=regular,
        beatgrid=beatgrid, bgm=bgm, backend=backend,
        comfy_root=comfy_root,
        workflow_template=Path(str(tmpl)).expanduser() if tmpl else None,
        still_model=Path(str(still_model)).expanduser() if still_model else None,
        render_python=str(_get("render_python", t, "")) or sys.executable,
        extra={k: v for k, v in t.items() if k not in Settings.__dataclass_fields__},
    )


def _auto_backend(t: dict) -> str:
    """Pick a backend only when the choice is unambiguous, otherwise say so."""
    root = _get("comfy_root", t)
    if root and (Path(str(root)).expanduser() / "ComfyUI" / "main.py").is_file():
        return "comfy_h3"
    raise SystemExit(
        "no render backend configured.\n"
        "  · on a GPU box: set comfy_root in vitrine.toml to your ComfyUI-H3 install\n"
        "  · to check a config and the cut without rendering: --backend null\n"
        "    (null writes placeholder takes; it is for wiring tests, not delivery)")
