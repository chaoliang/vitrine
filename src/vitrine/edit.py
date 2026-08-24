# -*- coding: utf-8 -*-
"""Config -> cut. Every item gets: dressing wide, product detail, optional specs.

The ordering rule is the one an earlier cut got wrong: after a piece goes on,
the next shot frames *that piece*. Cutting to her face after the boots land
hides the thing being sold, so the detail segment comes from the item's own
DETAIL take, framed at its body region.

Cuts land on the measured beat grid. Scene changes only ever happen between
items, which is also where the takes change, so a set change is never a jump cut
inside one action.

What changed when this was made portable: the beat grid and the music used to be
read out of an unrelated job directory on one workstation. They are settings
now, and a missing music track produces a silent cut and says so in the report
rather than dying at the last ffmpeg call after all the segments are encoded.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .backends.null import MARKER
from .schema import Config
from .settings import Settings

W, H, FPS = 1080, 1920, 24
AMBER = (232, 163, 23, 255)

WIDE_IN, WIDE_BEATS = 0.55, 8       # dressing action
DETAIL_IN, DETAIL_BEATS = 0.90, 7   # the product itself


def _font(p: str, s: int):
    return ImageFont.truetype(p, s)


def probe(st: Settings, p: Path) -> dict:
    r = subprocess.run([st.ffprobe, "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(p)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def beat_grid(st: Settings) -> tuple[float, float]:
    if not st.beatgrid.is_file():
        raise SystemExit(
            f"no beat grid at {st.beatgrid}.\n"
            f"  derive one from your own track:  vitrine beatgrid <audio file>\n"
            f"  or point `beatgrid` in vitrine.toml at an existing one")
    g = json.loads(st.beatgrid.read_text(encoding="utf-8"))
    return g["period_s"], g["first_beat_s"]


def find(st: Settings, cfg: Config, stem: str) -> Path:
    """The pinned take if the operator accepted one, otherwise the newest."""
    folder = st.takes_dir(cfg.episode)
    pinned = cfg.pin.get(stem)
    if pinned:
        p = folder / pinned
        if not p.is_file():
            raise SystemExit(f"pinned take is missing: {p}")
        return p
    hits = sorted(folder.glob(f"{stem}_*.mp4"))
    if not hits:
        raise SystemExit(f"missing take: {cfg.episode}/{stem} (looked in {folder})")
    return hits[-1]


def chips_png(st: Settings, cfg: Config, n: int, cta: bool, path: Path) -> Path:
    """Price chips for the first n items, stacked upward from a fixed baseline."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_ser = _font(st.font_regular, 34)
    f_name, f_price = _font(st.font_bold, 42), _font(st.font_bold, 40)
    f_cta = _font(st.font_regular, 36)
    tw = d.textlength(cfg.series, font=f_ser)
    d.rounded_rectangle([56, 92, 56 + tw + 52, 154], radius=31, fill=(0, 0, 0, 130))
    d.text((82, 106), cfg.series, font=f_ser, fill=(255, 255, 255, 235))
    y = H - 300 - 86 * (n - 1)
    for it in cfg.items[:n]:
        nw = d.textlength(it.name, font=f_name)
        pw = d.textlength(it.price, font=f_price)
        d.rounded_rectangle([64, y, 64 + nw + 48, y + 70], radius=10, fill=(0, 0, 0, 172))
        d.text((88, y + 11), it.name, font=f_name, fill=(255, 255, 255, 255))
        px = 64 + nw + 48 + 12
        d.rounded_rectangle([px, y, px + pw + 32, y + 70], radius=10, fill=AMBER)
        d.text((px + 16, y + 13), it.price, font=f_price, fill=(24, 20, 16, 255))
        y += 86
    if cta:
        d.text((64, H - 196), cfg.cta, font=f_cta, fill=AMBER)
    img.save(path)
    return path


def spec_png(st: Settings, cfg: Config, item, path: Path) -> Path:
    """The parameter card that runs during an item's hold."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_name, f_price = _font(st.font_bold, 54), _font(st.font_bold, 46)
    f_spec = _font(st.font_regular, 38)
    box_h = 150 + len(item.specs) * 62
    top = H - 200 - box_h
    d.rounded_rectangle([56, top, W - 56, top + box_h], radius=18, fill=(0, 0, 0, 196))
    d.text((92, top + 34), item.name, font=f_name, fill=(255, 255, 255, 255))
    pw = d.textlength(item.price, font=f_price)
    d.rounded_rectangle([W - 92 - pw - 36, top + 32, W - 92, top + 32 + 66],
                        radius=10, fill=AMBER)
    d.text((W - 92 - pw - 18, top + 42), item.price, font=f_price, fill=(24, 20, 16, 255))
    y = top + 122
    for spec in item.specs:
        d.ellipse([96, y + 16, 108, y + 28], fill=AMBER)
        d.text((126, y), spec, font=f_spec, fill=(232, 230, 224, 255))
        y += 62
    img.save(path)
    return path


def seg(st: Settings, src: Path, tin: float, dur: float, overlay: Path | None,
        dst: Path, freeze: bool = False, fade_in: float | None = None) -> Path:
    """One cut. `freeze` holds a single frame so a parameter card can be read.

    The still is extracted to a file first rather than held with -frames:v,
    which is an output option and silently produces an invalid graph when it is
    written in the input position.
    """
    args = [st.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if freeze:
        still = dst.with_suffix(".still.png")
        subprocess.run([st.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-ss", f"{tin:.3f}", "-i", str(src), "-frames:v", "1",
                        str(still)], check=True)
        args += ["-loop", "1", "-i", str(still)]
    else:
        args += ["-ss", f"{tin:.3f}", "-i", str(src)]
    vf = f"scale={W}:{H}:flags=lanczos,setsar=1"
    if overlay:
        args += ["-loop", "1", "-i", str(overlay)]
        f_in = (f",fade=t=in:st={fade_in:.2f}:d=0.20:alpha=1"
                if fade_in is not None else "")
        fc = f"[0:v]{vf}[v];[1:v]format=rgba{f_in}[o];[v][o]overlay=0:0:shortest=1[x]"
    else:
        fc = f"[0:v]{vf}[x]"
    args += ["-filter_complex", fc, "-map", "[x]", "-an",
             "-t", f"{dur:.3f}", "-r", str(FPS), "-c:v", "libx264",
             "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", str(dst)]
    subprocess.run(args, check=True)
    return dst


def _placeholder_sources(st: Settings, sources: list[Path]) -> bool:
    """True when any take came from the null backend, so nothing downstream
    can mistake a wiring test for footage."""
    for p in sources:
        try:
            meta = probe(st, p)
        except subprocess.CalledProcessError:
            continue
        if MARKER in json.dumps(meta.get("format", {}).get("tags", {})):
            return True
    return False


def cut(st: Settings, cfg: Config) -> dict:
    job = st.job(cfg.episode)
    work, out = job / "cuts", job / "deliverables"
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    beat, phase = beat_grid(st)

    pieces: list[Path] = []
    ledger: list[dict] = []
    sources: list[Path] = []
    want_chips = cfg.overlays in ("chips", "chips+specs")

    for i, item in enumerate(cfg.items):
        last = i == len(cfg.items) - 1
        chips = (chips_png(st, cfg, i + 1, cta=last, path=work / f"chips_{i}.png")
                 if want_chips else None)
        wide_src = find(st, cfg, f"{item.id}_wide")
        det_src = find(st, cfg, f"{item.id}_detail")
        sources += [wide_src, det_src]

        d1 = WIDE_BEATS * beat
        w_in = item.wide_in if item.wide_in is not None else WIDE_IN
        pre = (chips_png(st, cfg, i, cta=False, path=work / f"chips_pre{i}.png")
               if want_chips and i else None)
        pieces.append(seg(st, wide_src, w_in, d1, pre, work / f"{i:02d}a.mp4"))
        ledger.append({"item": item.id, "kind": "wide", "scene": item.scene,
                       "enter": item.enter, "in": round(w_in, 2),
                       "dur": round(d1, 3)})

        # the punch follows the product, never the model
        d2 = DETAIL_BEATS * beat
        d_in = item.detail_in if item.detail_in is not None else DETAIL_IN
        pieces.append(seg(st, det_src, d_in, d2, chips, work / f"{i:02d}b.mp4",
                          fade_in=0.15))
        ledger.append({"item": item.id, "kind": "detail", "region": item.region,
                       "dur": round(d2, 3)})

        if cfg.overlays == "chips+specs" and item.hold_s > 0 and item.specs:
            k = max(2, round(item.hold_s / beat))
            d3 = k * beat
            pieces.append(seg(st, det_src, d_in + d2, d3,
                              spec_png(st, cfg, item, work / f"spec_{i}.png"),
                              work / f"{i:02d}c.mp4", freeze=True, fade_in=0.12))
            ledger.append({"item": item.id, "kind": "specs",
                           "lines": len(item.specs), "dur": round(d3, 3)})

    if cfg.ending:
        src = find(st, cfg, "ending")
        sources.append(src)
        d = cfg.ending.beats * beat
        pieces.append(seg(st, src, 0.30, d, None, work / "zz_end.mp4"))
        ledger.append({"item": "ending", "kind": "ending",
                       "scene": cfg.ending.scene, "dur": round(d, 3)})

    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces),
                   encoding="utf-8")
    picture = work / "picture.mp4"
    subprocess.run([st.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(picture)], check=True)

    total = sum(r["dur"] for r in ledger)
    final = out / f"{cfg.episode}.mp4"
    silent = not st.bgm.is_file()
    if silent:
        subprocess.run([st.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(picture), "-c:v", "copy",
                        "-movflags", "+faststart", str(final)], check=True)
    else:
        subprocess.run(
            [st.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(picture), "-ss", f"{phase:.4f}", "-i", str(st.bgm),
             "-map", "0:v", "-map", "1:a", "-shortest",
             "-af", f"volume=0.85,afade=t=out:st={max(0.0, total - 1.2):.3f}:d=1.2,"
                    f"alimiter=limit=0.95",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(final)], check=True)

    info = probe(st, final)
    dur = float(info["format"]["duration"])
    problems = []
    if cfg.min_duration_s and dur < cfg.min_duration_s:
        problems.append(f"BLOCK: {dur:.1f}s is under the {cfg.min_duration_s}s floor")
    for item in cfg.items:
        if not any(r["item"] == item.id and r["kind"] == "detail" for r in ledger):
            problems.append(f"BLOCK: {item.id} has no product shot")
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    report = {"final": str(final), "duration_s": round(dur, 2),
              "style": cfg.style, "overlays": cfg.overlays, "pinned": cfg.pin,
              "segments": len(ledger), "items": len(cfg.items),
              "video": f"{v['codec_name']} {v['width']}x{v['height']}",
              "size_mb": round(int(info["format"]["size"]) / 1024 ** 2, 2),
              "silent": silent,
              "placeholder_footage": _placeholder_sources(st, sources),
              "problems": problems, "ledger": ledger}
    if silent:
        report.setdefault("notes", []).append(
            f"no music: {st.bgm} does not exist, so the cut is silent")
    (job / "edit-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if problems:
        raise SystemExit(json.dumps(report, ensure_ascii=False, indent=1))
    return report
