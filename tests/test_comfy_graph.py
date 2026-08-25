# -*- coding: utf-8 -*-
"""The graph the backend submits, checked without a GPU or a ComfyUI.

`build_graph` is pure: template in, filled graph out. Everything worth getting
wrong about it -- a pruned slot left dangling, a node id that only exists in one
person's export, the measured `ref_image_size` quietly reverting to the ComfyUI
default -- is visible in the returned dict.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vitrine.backends.base import BackendError, ShotSpec
from vitrine.backends.comfy_h3 import HUB, ComfyH3Backend

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "workflows" / "h3_ref2va.api.json"


@pytest.fixture
def backend(tmp_path: Path) -> ComfyH3Backend:
    return ComfyH3Backend(comfy_root=tmp_path, workflow_template=TEMPLATE,
                          logs_dir=tmp_path / "logs")


def shot(n_refs: int) -> ShotSpec:
    return ShotSpec(id="skirt_wide", prompt="一条裙子", seed=4242,
                    refs=[Path(f"r{i}.png") for i in range(n_refs)],
                    width=768, height=1344, frames=124, fps=24.0, steps=12)


def hub_of(wf: dict) -> dict:
    return next(v for v in wf.values() if v["class_type"] == HUB)["inputs"]


def ref_keys(wf: dict) -> list[str]:
    return sorted(k for k in hub_of(wf) if k.startswith("ref_images."))


@pytest.mark.unit
def test_template_ships_three_wired_slots():
    """The shape of a run should be readable from the JSON, not from Python."""
    wf = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert ref_keys(wf) == [f"ref_images.ref_image_{i}" for i in range(3)]
    assert hub_of(wf)["ref_image_size"] == "max"
    assert hub_of(wf)["prompt"] == ""


@pytest.mark.unit
def test_three_refs_fill_every_slot(backend: ComfyH3Backend):
    wf = backend.build_graph("ep", shot(3), ["ep/a.png", "ep/b.png", "ep/c.png"])
    assert ref_keys(wf) == [f"ref_images.ref_image_{i}" for i in range(3)]
    images = [wf[nid]["inputs"]["image"]
              for _, nid in backend._ref_slots(wf, backend._find(wf, HUB))]
    assert images == ["ep/a.png", "ep/b.png", "ep/c.png"]


@pytest.mark.unit
def test_unused_slot_is_pruned_not_left_dangling(backend: ComfyH3Backend):
    """A two-reference shot must not leave a LoadImage on a file nobody staged.

    ComfyUI rejects the whole prompt for a missing input and names the image,
    not the cause -- which is how this stayed invisible before.
    """
    wf = backend.build_graph("ep", shot(2), ["ep/a.png", "ep/b.png"])
    assert ref_keys(wf) == ["ref_images.ref_image_0", "ref_images.ref_image_1"]
    loaders = [k for k, v in wf.items() if v["class_type"] == "LoadImage"]
    assert len(loaders) == 2
    assert all(wf[k]["inputs"]["image"].startswith("ep/") for k in loaders)


@pytest.mark.unit
def test_per_shot_fields_are_filled(backend: ComfyH3Backend):
    wf = backend.build_graph("autumn", shot(3), ["a", "b", "c"])
    hub = hub_of(wf)
    assert hub["prompt"] == "一条裙子"
    assert (hub["width"], hub["height"], hub["length"]) == (768, 1344, 124)
    # measured, not the ComfyUI default -- "match" drifts off the identity
    assert hub["ref_image_size"] == "max"
    assert wf[backend._find(wf, "RandomNoise")]["inputs"]["noise_seed"] == 4242
    assert wf[backend._find(wf, "BasicScheduler")]["inputs"]["steps"] == 12
    assert wf[backend._find(wf, "CreateVideo")]["inputs"]["fps"] == 24.0
    assert (wf[backend._find(wf, "SaveVideo")]["inputs"]["filename_prefix"]
            == "autumn/skirt_wide")


@pytest.mark.unit
def test_node_ids_are_discovered_not_assumed(backend: ComfyH3Backend, tmp_path: Path):
    """Renumber every node; the backend should not notice."""
    wf = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    remap = {k: f"n{i}" for i, k in enumerate(wf)}
    moved = {}
    for old, node in wf.items():
        ins = {k: ([remap[v[0]], v[1]] if isinstance(v, list) and v and v[0] in remap else v)
               for k, v in node["inputs"].items()}
        moved[remap[old]] = {**node, "inputs": ins}
    alt = tmp_path / "renumbered.api.json"
    alt.write_text(json.dumps(moved), encoding="utf-8")

    backend.workflow_template = alt
    out = backend.build_graph("ep", shot(3), ["a", "b", "c"])
    assert hub_of(out)["prompt"] == "一条裙子"
    assert out[backend._find(out, "SaveVideo")]["inputs"]["filename_prefix"] == "ep/skirt_wide"


@pytest.mark.unit
def test_template_without_the_hub_fails_loudly(backend: ComfyH3Backend, tmp_path: Path):
    alt = tmp_path / "wrong.api.json"
    alt.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {}}}),
                   encoding="utf-8")
    backend.workflow_template = alt
    with pytest.raises(BackendError, match=HUB):
        backend.build_graph("ep", shot(1), ["a"])
