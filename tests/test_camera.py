# -*- coding: utf-8 -*-
"""运镜 LoRA 的接线，不开显卡就能验。

值得写死的三件事：触发词必须领头（LoRA 的 README 明说，实测放中间不生效）、
没配 camera 时行为一字不变、以及 null 后端遇到运镜必须报错而不是默默渲成固定机位。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vitrine.backends.base import BackendError, ShotSpec, check_lora
from vitrine.backends.comfy_h3 import ComfyH3Backend
from vitrine.backends.null import NullBackend
from vitrine.schema import Camera, Config

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "workflows" / "h3_ref2va.api.json"
DEMO = Path(__file__).resolve().parents[1] / "configs" / "demo.json"

CAMERA_BLOCK = {
    "lora": "camera_motion_h3_lora_v1_3000_pruned.safetensors",
    "strength": 1.0,
    "moves": {"wide": "slow push-in with subtle lateral tracking",
              "detail": "slow push-in to extreme close-up",
              "ending": "slow smooth orbit then gentle pull-back"},
}


def cfg_with_camera(tmp_path: Path, block=CAMERA_BLOCK) -> Config:
    d = json.loads(DEMO.read_text(encoding="utf-8"))
    d["camera"] = block
    p = tmp_path / "cam.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return Config.load(p)


@pytest.mark.unit
def test_absent_camera_leaves_prompts_untouched(tmp_path: Path):
    """没配 camera 的配置，产出必须和加这个功能之前一字不差。"""
    from vitrine.build import plan
    from vitrine.settings import load

    st = load("null")
    plain = Config.load(DEMO)
    shots = plan(st, plain, require_assets=False)
    assert all(s.lora is None for s in shots)
    assert not any(s.prompt.startswith("camera motion") for s in shots)


@pytest.mark.unit
def test_trigger_leads_the_prompt(tmp_path: Path):
    """触发词必须在最前面 —— 放中间 LoRA 不生效。"""
    from vitrine.build import plan
    from vitrine.settings import load

    st = load("null")
    cfg = cfg_with_camera(tmp_path)
    shots = plan(st, cfg, require_assets=False)
    for s in shots:
        assert s.prompt.startswith("camera motion, "), s.id
        assert s.lora == CAMERA_BLOCK["lora"]
        assert s.lora_strength == 1.0


@pytest.mark.unit
def test_each_kind_gets_its_own_move(tmp_path: Path):
    from vitrine.build import plan
    from vitrine.settings import load

    st = load("null")
    shots = {s.id: s for s in plan(st, cfg_with_camera(tmp_path), require_assets=False)}
    assert "slow push-in with subtle lateral tracking" in shots["dress_wide"].prompt
    assert "slow push-in to extreme close-up" in shots["dress_detail"].prompt
    assert "orbit" in shots["ending"].prompt


@pytest.mark.unit
def test_a_kind_without_a_move_stays_fixed_camera(tmp_path: Path):
    """只给 wide 配运镜时，detail 必须还是固定机位、且不挂 LoRA。"""
    from vitrine.build import plan
    from vitrine.settings import load

    st = load("null")
    block = {**CAMERA_BLOCK, "moves": {"wide": "slow push-in"}}
    shots = {s.id: s for s in plan(st, cfg_with_camera(tmp_path, block), require_assets=False)}
    assert shots["dress_wide"].lora is not None
    assert shots["dress_detail"].lora is None
    assert not shots["dress_detail"].prompt.startswith("camera motion")


@pytest.mark.unit
def test_graph_splices_the_lora_before_every_model_consumer(tmp_path: Path):
    """LoRA 要接在 UNET 和所有用到它的节点之间，漏一个就会有的路径带 LoRA 有的不带。"""
    backend = ComfyH3Backend(comfy_root=tmp_path, workflow_template=TEMPLATE,
                             logs_dir=tmp_path / "logs")
    shot = ShotSpec(id="x", prompt="camera motion, slow push-in. …", refs=[Path("a")],
                    seed=1, width=768, height=1344, frames=124, fps=24.0, steps=12,
                    lora="cam.safetensors", lora_strength=0.9)
    wf = backend.build_graph("ep", shot, ["ep/a.png"])

    unet = backend._find(wf, "UNETLoader")
    loader = backend._find(wf, "LoraLoaderModelOnly")
    assert wf[loader]["inputs"]["lora_name"] == "cam.safetensors"
    assert wf[loader]["inputs"]["strength_model"] == 0.9
    assert wf[loader]["inputs"]["model"] == [unet, 0]
    # 除了 LoRA 自己，没有任何节点还直接吃 UNET
    for k, node in wf.items():
        if k == loader:
            continue
        for val in node.get("inputs", {}).values():
            assert not (isinstance(val, list) and val and val[0] == unet), k


@pytest.mark.unit
def test_null_backend_refuses_rather_than_dropping_the_move(tmp_path: Path):
    """渲成固定机位而不报错，是"长度对、镜头错"，比失败更难发现。"""
    shot = ShotSpec(id="x", prompt="camera motion, …", refs=[Path("a")], seed=1,
                    width=768, height=1344, frames=124, fps=24.0, steps=12,
                    lora="cam.safetensors")
    with pytest.raises(BackendError, match="cannot load a LoRA"):
        check_lora(NullBackend(ffmpeg="ffmpeg", font="f"), [shot])


@pytest.mark.unit
@pytest.mark.parametrize("bad,msg", [
    ({"lora": "", "moves": {}}, "empty"),
    ({"lora": "x", "strength": 1.8, "moves": {}}, "0-1.5"),
    ({"lora": "x", "moves": {"closeup": "orbit"}}, "unknown shot kinds"),
])
def test_bad_camera_blocks_are_rejected(bad, msg):
    with pytest.raises(ValueError, match=msg):
        Camera(**bad).validate()


@pytest.mark.unit
def test_camera_survives_to_json(tmp_path: Path):
    """split 会经 to_json 重建配置，运镜不能在路上掉。"""
    cfg = cfg_with_camera(tmp_path)
    back = cfg.to_json()
    assert back["camera"]["lora"] == CAMERA_BLOCK["lora"]
    assert back["camera"]["moves"]["ending"].startswith("slow smooth orbit")
