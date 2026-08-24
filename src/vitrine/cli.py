# -*- coding: utf-8 -*-
"""One entry point. `vitrine <command> <config>`.

The stages used to be four scripts that re-launched each other through a
hardcoded interpreter path, which meant the pipeline could only run where that
interpreter lived. They are function calls now and the whole run happens in one
process, so `python -m vitrine` works wherever the package is installed.

Stages skip themselves when their output already exists, so a run that dies in
the middle of a forty-minute render resumes instead of starting over. `--from`
forces a stage and everything after it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import beatgrid as beatgrid_mod
from . import stills
from .deliver import deliver
from .edit import cut
from .render import render_episode
from .schema import Config
from .settings import Settings, load

STAGES = ("bible", "render", "edit", "deliver")


def _out(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1))


def _done(st: Settings, cfg: Config, stage: str) -> bool:
    job = st.job(cfg.episode)
    if stage == "bible":
        return not stills.needs_bible(st, cfg)
    if stage == "render":
        want = {f"{i.id}_{k}" for i in cfg.items for k in ("wide", "detail")}
        if cfg.ending:
            want.add("ending")
        folder = st.takes_dir(cfg.episode)
        have = ({p.name.rsplit("_", 2)[0] for p in folder.glob("*.mp4")}
                if folder.is_dir() else set())
        return want <= have
    if stage == "edit":
        return (job / "deliverables" / f"{cfg.episode}.mp4").is_file()
    return (job / "deliverables" / f"{cfg.episode}.delivery.mp4").is_file()


def cmd_make(args) -> dict:
    st = load(args.backend)
    cfg = Config.load(args.config)
    forced = STAGES[STAGES.index(args.start):] if args.start else ()
    report, t0 = [], time.perf_counter()

    for stage in STAGES:
        if stage not in forced and _done(st, cfg, stage):
            report.append({"stage": stage, "status": "skipped (already done)"})
            print(f"[make] {stage}: already done", flush=True)
            continue
        t = time.perf_counter()
        print(f"[make] {stage}: running", flush=True)
        if stage == "bible":
            stills.bible(st, cfg)
        elif stage == "render":
            render_episode(st, cfg)
        elif stage == "edit":
            cut(st, cfg)
        else:
            deliver(st, cfg, args.producer)
        report.append({"stage": stage, "status": "ran",
                       "minutes": round((time.perf_counter() - t) / 60, 1)})

    return {"episode": cfg.episode, "backend": st.backend,
            "delivery": str(st.job(cfg.episode) / "deliverables" /
                            f"{cfg.episode}.delivery.mp4"),
            "total_minutes": round((time.perf_counter() - t0) / 60, 1),
            "stages": report}


def cmd_batch(args) -> dict:
    configs = sorted(p for p in Path(args.config_dir).glob(args.glob)
                     if not p.name.startswith("TEMPLATE"))
    if not configs:
        raise SystemExit(f"no configs matched {args.glob} in {args.config_dir}")
    results, t0 = [], time.perf_counter()
    # Sequential on purpose: one render already saturates the card, so
    # overlapping two episodes makes both slower and risks evicting each other.
    for i, c in enumerate(configs, 1):
        print(f"\n[batch] {i}/{len(configs)}  {c.name}", flush=True)
        t = time.perf_counter()
        try:
            cmd_make(argparse.Namespace(config=str(c), producer=args.producer,
                                        start=None, backend=args.backend))
            ok, err = True, None
        except SystemExit as e:            # one bad SKU must not stop a catalogue
            ok, err = False, str(e)[:400]
            print(f"[batch] {c.name} FAILED, continuing", flush=True)
        results.append({"config": c.name, "ok": ok, "error": err,
                        "minutes": round((time.perf_counter() - t) / 60, 1)})
    ok = sum(1 for r in results if r["ok"])
    out = {"total": len(results), "ok": ok,
           "failed": [r["config"] for r in results if not r["ok"]],
           "total_minutes": round((time.perf_counter() - t0) / 60, 1),
           "results": results}
    if ok != len(results):
        _out(out)
        raise SystemExit(1)
    return out


def _bed(args) -> dict:
    """Loop a short track to length and write the matching grid beside it."""
    st = load(args.backend or "null")
    out = beatgrid_mod.bed(st.ffmpeg, st.ffprobe, Path(args.audio),
                           Path(args.out), args.seconds)
    grid_path = Path(args.grid_out)
    grid_path.parent.mkdir(parents=True, exist_ok=True)
    grid_path.write_text(json.dumps(out["grid"], ensure_ascii=False),
                         encoding="utf-8")
    out["grid_written_to"] = str(grid_path)
    return out


def cmd_check(args) -> dict:
    """Validate a config without touching a GPU: schema, outfit clash, shots."""
    from .build import plan
    st = load(args.backend or "null")
    cfg = Config.load(args.config)
    shots = plan(st, cfg)
    return {"episode": cfg.episode, "items": len(cfg.items),
            "shots": len(shots), "style": cfg.style,
            "settings": st.describe(),
            "plan": [s.to_json() for s in shots]}


def cmd_doctor(args) -> dict:
    st = load(args.backend)
    checks = {
        "ffmpeg": Path(st.ffmpeg).exists() or bool(st.ffmpeg),
        "ffprobe": Path(st.ffprobe).exists() or bool(st.ffprobe),
        "font_bold": Path(st.font_bold).is_file(),
        "font_regular": Path(st.font_regular).is_file(),
        "beatgrid": st.beatgrid.is_file(),
        "bgm": st.bgm.is_file(),
        "jobs_dir_writable": _writable(st.jobs_dir),
    }
    return {"settings": st.describe(), "checks": checks,
            "ready_to_render": all(v for k, v in checks.items() if k != "bgm"),
            "note": None if checks["bgm"] else
                    "no music track configured: cuts will be silent"}


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".vitrine-write-test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vitrine",
                                 description="配置驱动的服饰商品视频产线")
    ap.add_argument("--backend", help="override the configured render backend "
                                      "(comfy_h3 / null)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("make", help="bible -> render -> edit -> deliver")
    p.add_argument("config")
    p.add_argument("--producer", default="未命名内容生产者",
                   help="goes into the AIGC implicit label, required by GB 45438-2025")
    p.add_argument("--from", dest="start", choices=STAGES,
                   help="force this stage and everything after it")
    p.set_defaults(fn=cmd_make)

    p = sub.add_parser("batch", help="every config in a directory, in turn")
    p.add_argument("config_dir")
    p.add_argument("--producer", default="未命名内容生产者")
    p.add_argument("--glob", default="*.json")
    p.set_defaults(fn=cmd_batch)

    p = sub.add_parser("render", help="render takes only")
    p.add_argument("config")
    p.add_argument("takes", nargs="*",
                   help="names to re-render, e.g. dress_detail ending; "
                        "omit for the whole episode")
    p.set_defaults(fn=lambda a: render_episode(
        load(a.backend), Config.load(a.config), set(a.takes) or None))

    p = sub.add_parser("edit", help="cut the accepted takes")
    p.add_argument("config")
    p.set_defaults(fn=lambda a: cut(load(a.backend), Config.load(a.config)))

    p = sub.add_parser("deliver", help="burn and stamp the AIGC label")
    p.add_argument("config")
    p.add_argument("--producer", default="未命名内容生产者")
    p.set_defaults(fn=lambda a: deliver(load(a.backend), Config.load(a.config),
                                        a.producer))

    p = sub.add_parser("bible", help="generate the missing product packshots")
    p.add_argument("config")
    p.set_defaults(fn=lambda a: stills.bible(load(a.backend), Config.load(a.config)))

    p = sub.add_parser("model-ref", help="four candidate model reference stills")
    p.add_argument("config")
    p.set_defaults(fn=lambda a: stills.model_reference(load(a.backend),
                                                       Config.load(a.config)))

    p = sub.add_parser("beatgrid", help="derive the beat grid from your own track")
    p.add_argument("audio")
    p.add_argument("-o", "--out", default="assets/audio/beatgrid.json")
    p.set_defaults(fn=lambda a: beatgrid_mod.write(
        load(a.backend or "null").ffmpeg, Path(a.audio), Path(a.out)))

    p = sub.add_parser("bed", help="loop a short track up to length on a bar boundary")
    p.add_argument("audio")
    p.add_argument("--seconds", type=float, required=True,
                   help="target length; make it a little longer than the cut")
    p.add_argument("-o", "--out", default="assets/audio/bgm.mp3")
    p.add_argument("--grid-out", default="assets/audio/beatgrid.json")
    p.set_defaults(fn=lambda a: _bed(a))

    p = sub.add_parser("check", help="validate a config without a GPU")
    p.add_argument("config")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("doctor", help="what is configured and what is missing")
    p.set_defaults(fn=cmd_doctor)

    args = ap.parse_args(argv)
    _out(args.fn(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
