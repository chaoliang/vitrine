"""AIGC compliance labelling for delivered short-drama video (GB 45438-2025).

Two independent obligations are implemented here, and they are kept apart on
purpose because only one of them is machine verifiable:

* The *explicit* label (5.4) is burned into the picture. It must carry both an
  "artificial intelligence" element and a "generated/synthesised" element, sit on
  an edge or corner of the *starting* frames, stand at least 5% of the shortest
  frame side tall, and hold for at least 2 seconds at normal playback speed.
  Nothing in a container can prove a human can read it, so this module builds and
  runs the burn-in but never reports it as verified.
* The *implicit* label (Annex E) is a JSON document stored in a file metadata
  field whose name contains ``AIGC``. It is written with a pure stream copy and
  is read back with ffprobe, so it *is* machine verifiable. 6.1 c) requires that
  exactly one copy survives, so both zero and more than one are failures.

Every requirement violation raises instead of being quietly repaired: a delivery
that silently drops below the mandatory 2 seconds, or falls back to a font that
renders Chinese as empty boxes, would still ship and would still be illegal.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import ImageFont

from .runner import CommandRunner


GB_STANDARD = "GB 45438-2025"

# 5.4 geometry and timing floors. They are minimums, never targets.
MINIMUM_TEXT_HEIGHT_RATIO = 0.05
MINIMUM_DISPLAY_SECONDS = 2.0

# Annex E stores the implicit label in a field whose name contains "AIGC".
METADATA_FIELD_NAME = "AIGC"

DEFAULT_LABEL_TEXT = "本视频由 AI 生成"
FONT_FILE_ENVIRONMENT_VARIABLE = "AI_DRAMA_AIGC_FONT_FILE"

EXPLICIT_LABEL_REVIEW_NOTE = (
    "显式标识需人工/视觉检查：文件元数据只能证明隐式标识，无法证明起始画面上的文字标识真实可辨、位置正确、时长达标。"
)

LABEL_POSITIONS: tuple[str, ...] = (
    "top_left",
    "top_right",
    "top_center",
    "bottom_left",
    "bottom_right",
    "bottom_center",
)

#: Annex E label values.
LABEL_GENERATED = 1  # 内容属于人工智能生成合成
LABEL_POSSIBLY_GENERATED = 2  # 内容可能为人工智能生成合成
LABEL_SUSPECTED_GENERATED = 3  # 内容疑似为人工智能生成合成
LABEL_VALUES: tuple[int, ...] = (LABEL_GENERATED, LABEL_POSSIBLY_GENERATED, LABEL_SUSPECTED_GENERATED)

ANNEX_E_FIELDS: tuple[str, ...] = (
    "Label",
    "ContentProducer",
    "ProduceID",
    "ReservedCode1",
    "ContentPropagator",
    "PropagateID",
    "ReservedCode2",
)
_MANDATORY_FIELDS: tuple[str, ...] = ("Label", "ContentProducer", "ProduceID")

#: Fonts that ship with a CJK repertoire on the platforms this engine runs on.
DEFAULT_CJK_FONT_CANDIDATES: tuple[Path, ...] = (
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
)

_MUXERS_NEEDING_METADATA_TAGS = frozenset({".mp4", ".m4v", ".m4a", ".mov"})

# "AI" must be a standalone token. A bare substring test would certify captions
# such as "detailed chair" that never actually say the content is AI generated.
_AI_ELEMENT = re.compile(r"(?<![0-9A-Za-z])AI(?![0-9A-Za-z])")
_AI_ELEMENT_CHINESE = "人工智能"
_SYNTHESIS_ELEMENTS: tuple[str, ...] = ("生成", "合成")

# Unassigned codepoints used to fingerprint the font's ".notdef" box. They are
# deliberately *not* default-ignorable characters: those are dropped outright by
# some Pillow/HarfBuzz builds and would fingerprint an empty bitmap instead.
_GLYPH_PROBE_CODEPOINTS: tuple[str, ...] = ("͸", "׫", "⿠")
_GLYPH_PROBE_SIZE = 48


class AigcLabelError(ValueError):
    """A GB 45438 labelling requirement is not satisfiable as configured."""


class AigcFontError(AigcLabelError):
    """The label font is missing or cannot render the mandated wording."""


def validate_label_text(text: str) -> None:
    """Require both mandatory 5.4 wording elements, or fail with the reason."""

    has_ai = _AI_ELEMENT_CHINESE in text or bool(_AI_ELEMENT.search(text))
    has_synthesis = any(element in text for element in _SYNTHESIS_ELEMENTS)
    if has_ai and has_synthesis:
        return
    missing: list[str] = []
    if not has_ai:
        missing.append("人工智能 或 AI")
    if not has_synthesis:
        missing.append("生成 或 合成")
    raise AigcLabelError(
        f"{GB_STANDARD} 5.4 requires the explicit label to contain both an AI element and a "
        f"generation element; {text!r} is missing: {'; '.join(missing)}. "
        f"Use wording such as {DEFAULT_LABEL_TEXT!r}."
    )


def _escape_filtergraph_value(value: str) -> str:
    """Escape one drawtext option value for a single-quoted filtergraph token."""

    # Order matters: the backslash pass must run before the passes that add
    # backslashes, and the quote pass closes/reopens the surrounding quotes.
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace(":", "\\:")
    return escaped.replace("'", "'\\''")


@dataclass(frozen=True, slots=True)
class ExplicitLabelSpec:
    """A 5.4-compliant burned-in label, resolved against a concrete frame size."""

    font_file: Path
    text: str = DEFAULT_LABEL_TEXT
    position: str = "top_left"
    duration_seconds: float = MINIMUM_DISPLAY_SECONDS
    text_height_ratio: float = MINIMUM_TEXT_HEIGHT_RATIO
    margin_ratio: float = 0.03
    font_color: str = "white"
    box_color: str = "black@0.5"

    def __post_init__(self) -> None:
        object.__setattr__(self, "font_file", Path(self.font_file))
        validate_label_text(self.text)
        if self.position not in LABEL_POSITIONS:
            raise AigcLabelError(
                f"unsupported label position {self.position!r}; {GB_STANDARD} 5.4 requires an edge or a "
                f"corner of the starting frame, so choose one of: {', '.join(LABEL_POSITIONS)}"
            )
        if self.duration_seconds < MINIMUM_DISPLAY_SECONDS:
            raise AigcLabelError(
                f"explicit label duration {self.duration_seconds} s is below the {MINIMUM_DISPLAY_SECONDS} s "
                f"floor in {GB_STANDARD} 5.4; raise the duration rather than shipping a shorter label"
            )
        if self.text_height_ratio < MINIMUM_TEXT_HEIGHT_RATIO:
            raise AigcLabelError(
                f"text height ratio {self.text_height_ratio} is below the {MINIMUM_TEXT_HEIGHT_RATIO} floor in "
                f"{GB_STANDARD} 5.4 (at least 5% of the shortest frame side)"
            )
        if not 0.0 <= self.margin_ratio < 0.2:
            raise AigcLabelError(
                f"margin ratio {self.margin_ratio} must stay within [0, 0.2) so the label remains on the frame edge"
            )

    def font_size_for(self, width: int, height: int) -> int:
        """Size the em box from the shortest side; never hardcode a pixel value."""

        shortest = _shortest_side(width, height)
        # Round up: the standard sets a floor, so a fractional pixel must grow.
        return math.ceil(round(shortest * self.text_height_ratio, 6))

    def margin_for(self, width: int, height: int) -> int:
        """Inset from the frame edge. Not a compliance floor, so this rounds down."""

        shortest = _shortest_side(width, height)
        return max(1, int(shortest * self.margin_ratio))

    def drawtext_filter(self, width: int, height: int) -> str:
        """Build the FFmpeg ``drawtext`` filter for this frame size."""

        font_size = self.font_size_for(width, height)
        margin = self.margin_for(width, height)
        x_expression, y_expression = _position_expressions(self.position, margin)
        options = (
            f"fontfile='{_escape_filtergraph_value(str(self.font_file))}'",
            f"text='{_escape_filtergraph_value(self.text)}'",
            f"fontsize={font_size}",
            f"fontcolor={self.font_color}",
            "box=1",
            f"boxcolor={self.box_color}",
            f"boxborderw={max(2, font_size // 8)}",
            f"x={x_expression}",
            f"y={y_expression}",
            # 5.4 wants the label on the *starting* frames, hence t=0.
            f"enable='between(t,0,{self.duration_seconds:g})'",
        )
        return "drawtext=" + ":".join(options)


def _shortest_side(width: int, height: int) -> int:
    if width <= 0 or height <= 0:
        raise AigcLabelError(f"frame size must be positive; received {width}x{height}")
    return min(width, height)


def _position_expressions(position: str, margin: int) -> tuple[str, str]:
    left = str(margin)
    right = f"w-tw-{margin}"
    centre = "(w-tw)/2"
    top = str(margin)
    bottom = f"h-th-{margin}"
    return {
        "top_left": (left, top),
        "top_right": (right, top),
        "top_center": (centre, top),
        "bottom_left": (left, bottom),
        "bottom_right": (right, bottom),
        "bottom_center": (centre, bottom),
    }[position]


def _font_hint() -> str:
    return (
        f"Pass font_file explicitly or set {FONT_FILE_ENVIRONMENT_VARIABLE} to a font file that contains "
        "Chinese glyphs (for example Noto Sans CJK, Microsoft YaHei, or Hiragino Sans GB). "
        "The label is never rendered with a substitute font, because a missing glyph ships as an empty box."
    )


def resolve_cjk_font(
    font_file: Path | str | None = None,
    *,
    candidates: Sequence[Path] = DEFAULT_CJK_FONT_CANDIDATES,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Locate a Chinese-capable font file, failing loudly rather than degrading."""

    if font_file is not None:
        path = Path(font_file)
        if not path.is_file():
            raise AigcFontError(f"configured AIGC label font is missing: {path}. {_font_hint()}")
        return path

    environment = os.environ if environ is None else environ
    override = environment.get(FONT_FILE_ENVIRONMENT_VARIABLE)
    if override:
        path = Path(override)
        if not path.is_file():
            raise AigcFontError(
                f"{FONT_FILE_ENVIRONMENT_VARIABLE} points at a missing font file: {path}. {_font_hint()}"
            )
        return path

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(candidate) for candidate in candidates) or "(no candidates configured)"
    raise AigcFontError(f"no Chinese-capable label font was found. Searched: {searched}. {_font_hint()}")


def missing_glyphs(font_file: Path | str, text: str) -> tuple[str, ...]:
    """Return the characters this font cannot draw, so boxes are never shipped.

    Two independent signals are combined, because neither alone survives every
    font and Pillow build: a character is missing when it renders as the font's
    ".notdef" box (or as nothing at all), or when two different non-Latin
    characters render to byte-identical bitmaps, which only happens when both are
    really the same fallback box.
    """

    path = Path(font_file)
    try:
        font = ImageFont.truetype(str(path), _GLYPH_PROBE_SIZE)
        notdef = {bytes(font.getmask(probe)) for probe in _GLYPH_PROBE_CODEPOINTS}
        notdef.discard(b"")  # some fonts draw a blank .notdef; that proves nothing.
        characters = [character for character in dict.fromkeys(text) if not character.isspace()]
        masks = {character: bytes(font.getmask(character)) for character in characters}
    except OSError as exc:
        raise AigcFontError(f"AIGC label font cannot be read as a font file: {path} ({exc}). {_font_hint()}") from exc

    # Latin letters are excluded from the duplicate signal on purpose: many fonts
    # legitimately draw "I" and "l" with one shared glyph.
    first_seen: dict[bytes, str] = {}
    duplicated: set[str] = set()
    for character in characters:
        if ord(character) <= 0x7F:
            continue
        mask = masks[character]
        if mask in first_seen:
            duplicated.update({character, first_seen[mask]})
        else:
            first_seen[mask] = character

    return tuple(
        character
        for character in characters
        if not masks[character] or masks[character] in notdef or character in duplicated
    )


def ensure_font_supports_text(font_file: Path | str, text: str) -> None:
    """Fail unless every label character has a real glyph in this font."""

    path = Path(font_file)
    if not path.is_file():
        raise AigcFontError(f"AIGC label font is missing: {path}. {_font_hint()}")
    missing = missing_glyphs(path, text)
    if missing:
        raise AigcFontError(
            f"AIGC label font {path} has no glyph for {''.join(missing)!r}; the burned-in label would render as "
            f"empty boxes and would not satisfy {GB_STANDARD} 5.4. {_font_hint()}"
        )


@dataclass(frozen=True, slots=True)
class AigcMetadata:
    """The Annex E implicit-label payload."""

    label: int
    content_producer: str
    produce_id: str
    reserved_code1: str | None = None
    content_propagator: str | None = None
    propagate_id: str | None = None
    reserved_code2: str | None = None

    def __post_init__(self) -> None:
        if self.label not in LABEL_VALUES:
            raise AigcLabelError(
                f"Annex E Label must be one of {LABEL_VALUES} (1 属于 / 2 可能 / 3 疑似); received {self.label!r}"
            )
        _require_text("ContentProducer", self.content_producer)
        _require_text("ProduceID", self.produce_id)
        for name, value in (
            ("ReservedCode1", self.reserved_code1),
            ("ContentPropagator", self.content_propagator),
            ("PropagateID", self.propagate_id),
            ("ReservedCode2", self.reserved_code2),
        ):
            if value is not None:
                _require_text(name, value)

    def as_payload(self) -> dict[str, str]:
        """Serialise to the exact Annex E field names, omitting absent optionals."""

        payload: dict[str, str] = {
            "Label": str(self.label),
            "ContentProducer": self.content_producer,
            "ProduceID": self.produce_id,
        }
        for name, value in (
            ("ReservedCode1", self.reserved_code1),
            ("ContentPropagator", self.content_propagator),
            ("PropagateID", self.propagate_id),
            ("ReservedCode2", self.reserved_code2),
        ):
            if value is not None:
                payload[name] = value
        return payload

    def to_json(self) -> str:
        return json.dumps(self.as_payload(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_payload(cls, payload: Any) -> "AigcMetadata":
        if not isinstance(payload, Mapping):
            raise AigcLabelError(f"Annex E implicit label must be a JSON object; received {type(payload).__name__}")
        unknown = sorted(set(payload) - set(ANNEX_E_FIELDS))
        if unknown:
            raise AigcLabelError(
                f"Annex E implicit label carries fields outside the standard: {', '.join(unknown)}. "
                f"Permitted fields are: {', '.join(ANNEX_E_FIELDS)}"
            )
        missing = [name for name in _MANDATORY_FIELDS if name not in payload]
        if missing:
            raise AigcLabelError(f"Annex E implicit label is missing mandatory field(s): {', '.join(missing)}")
        return cls(
            label=_parse_label(payload["Label"]),
            content_producer=_as_text("ContentProducer", payload["ContentProducer"]),
            produce_id=_as_text("ProduceID", payload["ProduceID"]),
            reserved_code1=_optional_text("ReservedCode1", payload.get("ReservedCode1")),
            content_propagator=_optional_text("ContentPropagator", payload.get("ContentPropagator")),
            propagate_id=_optional_text("PropagateID", payload.get("PropagateID")),
            reserved_code2=_optional_text("ReservedCode2", payload.get("ReservedCode2")),
        )

    @classmethod
    def from_json(cls, document: str) -> "AigcMetadata":
        try:
            payload = json.loads(document)
        except json.JSONDecodeError as exc:
            raise AigcLabelError(f"Annex E implicit label is not valid JSON: {exc}") from exc
        return cls.from_payload(payload)


def _require_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AigcLabelError(f"Annex E field {name} must be a non-empty string; received {value!r}")


def _as_text(name: str, value: Any) -> str:
    _require_text(name, value)
    return str(value)


def _optional_text(name: str, value: Any) -> str | None:
    if value is None:
        return None
    return _as_text(name, value)


def _parse_label(value: Any) -> int:
    # Third-party writers emit Label as either "1" or 1; both are accepted, and
    # anything else is rejected rather than coerced.
    if isinstance(value, bool):
        raise AigcLabelError(f"Annex E Label must be 1, 2 or 3; received {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise AigcLabelError(f"Annex E Label must be 1, 2 or 3; received {value!r}")


@dataclass(frozen=True, slots=True)
class AigcLabelVerification:
    """What ffprobe could and could not prove about one delivered file."""

    path: Path
    implicit_field_names: tuple[str, ...]
    metadata: AigcMetadata | None
    failures: tuple[str, ...]

    @property
    def implicit_label_passed(self) -> bool:
        """True only for the Annex E metadata, never for overall compliance."""

        return not self.failures

    @property
    def explicit_label_verified(self) -> bool:
        """Always False: no container field can prove a readable burned-in caption."""

        return False

    @property
    def explicit_label_review_required(self) -> bool:
        return True

    @property
    def notes(self) -> tuple[str, ...]:
        return (EXPLICIT_LABEL_REVIEW_NOTE,)

    def as_dict(self) -> dict[str, Any]:
        return {
            "standard": GB_STANDARD,
            "path": str(self.path),
            "implicit_label_passed": self.implicit_label_passed,
            "implicit_field_names": list(self.implicit_field_names),
            "metadata": self.metadata.as_payload() if self.metadata is not None else None,
            "failures": list(self.failures),
            "explicit_label_verified": self.explicit_label_verified,
            "explicit_label_review_required": self.explicit_label_review_required,
            "notes": list(self.notes),
        }


def _is_aigc_key(key: str) -> bool:
    """Annex E only requires the field *name* to contain AIGC, in any casing."""

    return "aigc" in key.lower()


def _probe(path: Path, *, ffprobe: str, runner: CommandRunner) -> dict[str, Any]:
    result = runner.run(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-print_format", "json", str(path)],
        Path(path).resolve().parent,
        timeout=120,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AigcLabelError(f"ffprobe returned invalid JSON for {path}") from exc
    if not isinstance(payload, dict):
        raise AigcLabelError(f"ffprobe returned an unexpected document for {path}")
    return payload


def probe_dimensions(
    path: Path | str, *, ffprobe: str = "ffprobe", runner: CommandRunner | None = None
) -> tuple[int, int]:
    """Read the frame size the 5% text-height rule has to be measured against."""

    payload = _probe(Path(path), ffprobe=ffprobe, runner=runner or CommandRunner())
    for stream in payload.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        width, height = stream.get("width"), stream.get("height")
        if width and height:
            return int(width), int(height)
    raise AigcLabelError(f"no video stream with a frame size was found in {path}; cannot size the explicit label")


def build_metadata_command(
    source: Path | str,
    destination: Path | str,
    metadata: AigcMetadata,
    *,
    ffmpeg: str = "ffmpeg",
    stale_keys: Iterable[str] = (),
) -> list[str]:
    """Build the stream-copy command that stamps exactly one Annex E field."""

    source_path, destination_path = _distinct_paths(source, destination)
    command = [ffmpeg, "-y", "-i", str(source_path), "-map", "0", "-c", "copy", "-map_metadata", "0"]
    if destination_path.suffix.lower() in _MUXERS_NEEDING_METADATA_TAGS:
        # Without this the MP4 muxer drops non-standard tags such as AIGC.
        command.extend(["-movflags", "use_metadata_tags"])
    # 6.1 c) allows only one file-metadata implicit label, so any differently
    # named leftover is cleared in the same pass by assigning it an empty value.
    for key in stale_keys:
        command.extend(["-metadata", f"{key}="])
    command.extend(["-metadata", f"{METADATA_FIELD_NAME}={metadata.to_json()}"])
    command.append(str(destination_path))
    return command


def build_explicit_label_command(
    source: Path | str,
    destination: Path | str,
    *,
    width: int,
    height: int,
    spec: ExplicitLabelSpec,
    ffmpeg: str = "ffmpeg",
    video_codec: str = "libx264",
    preset: str = "medium",
    crf: int = 18,
    pixel_format: str = "yuv420p",
) -> list[str]:
    """Build the burn-in command. Video must be re-encoded; audio is copied."""

    source_path, destination_path = _distinct_paths(source, destination)
    ensure_font_supports_text(spec.font_file, spec.text)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-vf",
        spec.drawtext_filter(width, height),
        "-c:v",
        video_codec,
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        pixel_format,
        "-c:a",
        "copy",
    ]
    if destination_path.suffix.lower() in _MUXERS_NEEDING_METADATA_TAGS:
        command.extend(["-movflags", "+faststart"])
    command.append(str(destination_path))
    return command


def _distinct_paths(source: Path | str, destination: Path | str) -> tuple[Path, Path]:
    source_path, destination_path = Path(source), Path(destination)
    if source_path.resolve() == destination_path.resolve():
        raise AigcLabelError(
            f"AIGC labelling cannot write onto its own input ({source_path}); choose a separate destination"
        )
    return source_path, destination_path


def burn_explicit_label(
    source: Path | str,
    destination: Path | str,
    spec: ExplicitLabelSpec,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    runner: CommandRunner | None = None,
) -> Path:
    """Burn the 5.4 explicit label onto the starting frames of ``source``.

    The result still needs a human or visual check; see EXPLICIT_LABEL_REVIEW_NOTE.
    """

    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"explicit AIGC label source video is missing: {source_path}")
    command_runner = runner or CommandRunner()
    width, height = probe_dimensions(source_path, ffprobe=ffprobe, runner=command_runner)
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_explicit_label_command(
        source_path,
        destination_path,
        width=width,
        height=height,
        spec=spec,
        ffmpeg=ffmpeg,
    )
    command_runner.run(command, destination_path.parent, timeout=3_600)
    return destination_path


def verify_aigc_label(
    path: Path | str,
    *,
    expected: AigcMetadata | None = None,
    ffprobe: str = "ffprobe",
    runner: CommandRunner | None = None,
) -> AigcLabelVerification:
    """Read the implicit label back out of a delivered file and judge it.

    Failure codes: ``IMPLICIT_LABEL_MISSING``, ``IMPLICIT_LABEL_DUPLICATED``,
    ``IMPLICIT_LABEL_MALFORMED`` and ``IMPLICIT_LABEL_MISMATCH``.
    """

    target = Path(path)
    payload = _probe(target, ffprobe=ffprobe, runner=runner or CommandRunner())

    found: list[tuple[str, str, str]] = []  # (location, key, raw value)
    for key, value in ((payload.get("format") or {}).get("tags") or {}).items():
        if _is_aigc_key(key):
            found.append(("format", key, str(value)))
    for stream in payload.get("streams") or []:
        for key, value in (stream.get("tags") or {}).items():
            if _is_aigc_key(key):
                found.append((f"stream:{stream.get('index')}", key, str(value)))

    failures: list[str] = []
    metadata: AigcMetadata | None = None
    if not found:
        failures.append("IMPLICIT_LABEL_MISSING")
    else:
        if len(found) > 1:
            # 6.1 c): exactly one file-metadata implicit label may survive.
            failures.append("IMPLICIT_LABEL_DUPLICATED")
        try:
            metadata = AigcMetadata.from_json(found[0][2])
        except AigcLabelError:
            failures.append("IMPLICIT_LABEL_MALFORMED")
        else:
            if expected is not None and metadata != expected:
                failures.append("IMPLICIT_LABEL_MISMATCH")

    return AigcLabelVerification(
        path=target,
        implicit_field_names=tuple(key for _, key, _ in found),
        metadata=metadata,
        failures=tuple(failures),
    )


def write_aigc_metadata(
    source: Path | str,
    destination: Path | str,
    metadata: AigcMetadata,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    runner: CommandRunner | None = None,
) -> AigcLabelVerification:
    """Stamp the Annex E implicit label by stream copy, then prove it read back.

    Raises when the read-back does not show exactly one matching label, so a
    non-compliant delivery can never leave this function looking successful.
    """

    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"implicit AIGC label source video is missing: {source_path}")
    command_runner = runner or CommandRunner()

    existing = _probe(source_path, ffprobe=ffprobe, runner=command_runner)
    stale_keys = tuple(
        key
        for key in ((existing.get("format") or {}).get("tags") or {})
        if _is_aigc_key(key) and key != METADATA_FIELD_NAME
    )

    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_metadata_command(
        source_path,
        destination_path,
        metadata,
        ffmpeg=ffmpeg,
        stale_keys=stale_keys,
    )
    command_runner.run(command, destination_path.parent, timeout=1_800)

    verification = verify_aigc_label(
        destination_path,
        expected=metadata,
        ffprobe=ffprobe,
        runner=command_runner,
    )
    if not verification.implicit_label_passed:
        raise AigcLabelError(
            f"implicit AIGC label read-back failed for {destination_path}: {', '.join(verification.failures)}; "
            f"observed field names: {verification.implicit_field_names or '(none)'}"
        )
    return verification
