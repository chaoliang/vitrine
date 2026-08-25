# -*- coding: utf-8 -*-
"""参考图编号：提示词说的第 N 张，必须真的是 staged 的第 N 张。

这组断言全部来自一个真实的失败模式 —— 提示词引用了不存在的图，或者放着 staged
的图不引用。两种都能渲染成功，都渲错，而且要四十分钟之后看片子才发现。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vitrine import prompts
from vitrine.backends.base import (PICTURE, BackendError, ShotSpec,
                                   check_picture_refs)
from vitrine.build import plan
from vitrine.schema import Config
from vitrine.settings import load

DEMO = Path(__file__).resolve().parents[1] / "configs" / "demo.json"


@pytest.mark.unit
@pytest.mark.parametrize("has_product,carry,expect", [
    (False, False, {"identity": 1}),
    (True,  False, {"identity": 1, "product": 2}),
    (False, True,  {"identity": 1, "carry": 2}),
    (True,  True,  {"identity": 1, "product": 2, "carry": 3}),
])
def test_numbering_follows_what_is_actually_staged(has_product, carry, expect):
    """接力帧在有商品图时是第 3 张、没有时是第 2 张 —— 编号是浮动的。"""
    assert prompts.pictures(has_product, carry) == expect


@pytest.mark.unit
def test_every_planned_shot_cites_exactly_its_staged_images():
    """整条产线跑一遍：每条镜头引用的图号集合 == 1..len(refs)。"""
    st = load("null")
    shots = plan(st, Config.load(DEMO), require_assets=False)
    assert shots
    for s in shots:
        cited = {int(n) for n in PICTURE.findall(s.prompt)}
        assert cited == set(range(1, len(s.refs) + 1)), s.id
    check_picture_refs(shots)          # 同一条不变式，走真正那道门


def _config_with(tmp_path: Path, refs: list[str]) -> tuple[Config, str]:
    """把 demo 配置搬到 tmp 下，素材是真文件，好让 product_still 真的 stage。"""
    d = json.loads(DEMO.read_text(encoding="utf-8"))
    d["asset_dir"] = str(tmp_path)
    d["items"][0]["refs"] = list(refs)
    for name in [d["model_ref"], *refs]:
        (tmp_path / name).write_bytes(b"\x89PNG\r\n\x1a\n")
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return Config.load(p), d["items"][0]["id"]


@pytest.mark.unit
def test_two_factory_photos_still_promise_only_one(tmp_path: Path):
    """商家给两张图，产线只 stage 第一张 —— 提示词不许声称有两张。

    这正是原来的写法翻的车：它按 len(item.refs) 写 "the 2 reference frames"，
    而 product_still 只取 refs[0]。schema 上限是 2，所以这是真能走到的路径。
    """
    cfg, item_id = _config_with(tmp_path, ["a.png", "b.png"])
    shots = [s for s in plan(load("null"), cfg) if s.id.startswith(item_id)]
    assert shots
    for s in shots:
        assert "2 reference frames" not in s.prompt
        assert len(s.refs) == 2                      # 身份 + 一张商品图
        assert "<Picture 3>" not in s.prompt
    check_picture_refs(shots)


@pytest.mark.unit
def test_a_listed_photo_that_is_not_on_disk_gets_no_subject(tmp_path: Path):
    """`check` 不要求素材到位，所以会走到"配置里有图、盘上没有"这一步。

    此时不能仍旧写出 <Subject 2> / <Picture 2> —— backend 根本不会 stage 它。
    """
    _config_with(tmp_path, [])                      # 素材目录就位，但不放商品图
    d = json.loads((tmp_path / "cfg.json").read_text(encoding="utf-8"))
    d["items"][0]["refs"] = ["missing.png"]
    item_id = d["items"][0]["id"]
    (tmp_path / "cfg.json").write_text(json.dumps(d, ensure_ascii=False),
                                       encoding="utf-8")

    shots = [s for s in plan(load("null"), Config.load(tmp_path / "cfg.json"),
                             require_assets=False) if s.id.startswith(item_id)]
    assert shots
    for s in shots:
        assert "<Picture 2>" not in s.prompt
        assert "<Subject 2>" not in s.prompt
    check_picture_refs(shots)


@pytest.mark.unit
def test_citing_a_picture_that_was_never_staged_is_refused():
    shot = ShotSpec(id="x", prompt="<Subject 2> is in <Picture 2>.",
                    refs=[Path("only-one.png")], seed=1, width=768, height=1344,
                    frames=124, fps=24.0, steps=12)
    with pytest.raises(BackendError, match="picture"):
        check_picture_refs([shot])


@pytest.mark.unit
def test_leaving_a_staged_picture_unnamed_is_refused():
    """图 staged 了却没人引用，模型会自己给它派用途 —— 一样是错的。"""
    shot = ShotSpec(id="x", prompt="<Subject 1> is in <Picture 1>.",
                    refs=[Path("a.png"), Path("carry.png")], seed=1,
                    width=768, height=1344, frames=124, fps=24.0, steps=12)
    with pytest.raises(BackendError, match="picture"):
        check_picture_refs([shot])


@pytest.mark.unit
def test_a_prompt_that_cites_nothing_is_left_alone():
    """不引用任何图的提示词没有做出承诺，这道门不该管它。"""
    shot = ShotSpec(id="x", prompt="no citations here", refs=[Path("a.png")],
                    seed=1, width=768, height=1344, frames=124, fps=24.0, steps=12)
    check_picture_refs([shot])
