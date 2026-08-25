# -*- coding: utf-8 -*-
"""`vitrine split`: a catalogue in, one runnable config per outfit out."""
from __future__ import annotations

import json
from argparse import Namespace

import pytest

from vitrine.cli import cmd_split
from vitrine.schema import Config

CATALOGUE = {
    "episode": "autumn", "series": "", "cta": "", "model_ref": "model.png",
    "identity": "A woman with the face of the reference image.",
    "scenes": {"room": "A quiet room with one tall window."},
    "style": "mature-quiet-luxury", "overlays": "none", "asset_dir": "",
    "min_duration_s": 25.0,
    "pin": {"skirt_wide": "skirt_wide_00002_.mp4"},
    "ending": {"scene": "room", "action": "she turns to the lens", "beats": 11},
    "items": [
        {"id": "skirt", "name": "skirt", "price": "", "garment": "a midi skirt",
         "region": "waist", "enter": "above", "scene": "room", "hem": "midi",
         "scale": "The hem sits at mid-calf."},
        {"id": "tall", "name": "tall boots", "price": "", "garment": "tall boots",
         "region": "feet", "enter": "below", "scene": "room", "shaft": "over_knee",
         "scale": "The shaft reaches above the knee."},
        {"id": "top", "name": "cardigan", "price": "", "garment": "a cardigan",
         "region": "torso", "enter": "above", "scene": "room",
         "scale": "Hip-length on her."},
        {"id": "chain", "name": "necklace", "price": "", "garment": "a necklace",
         "region": "neck", "enter": "above", "scene": "room",
         "scale": "A fine chain sitting at the base of her throat."},
    ],
}


@pytest.fixture
def catalogue(tmp_path):
    p = tmp_path / "autumn.json"
    p.write_text(json.dumps(CATALOGUE, ensure_ascii=False), encoding="utf-8")
    return p


def run(path, tmp_path, **kw):
    args = Namespace(config=str(path), out=str(tmp_path / "out"),
                     max_items=4, dry_run=False, backend="null")
    for k, v in kw.items():
        setattr(args, k, v)
    return cmd_split(args)


def test_a_catalogue_that_clashes_is_accepted_as_input(catalogue):
    """Loading it as a video would raise -- separating it is the whole job."""
    with pytest.raises(ValueError, match="skirt \\+ tall"):
        Config.load(catalogue)
    assert Config.load(catalogue, as_catalogue=True).episode == "autumn"


def test_every_piece_stands_on_its_own(catalogue, tmp_path):
    out = run(catalogue, tmp_path)
    assert out["videos"] == 2
    assert len(out["written"]) == 2
    for path in out["written"]:
        cfg = Config.load(path)          # would raise on a clash or a bad ref
        assert cfg.items
        assert cfg.ending and cfg.ending.scene in cfg.scenes


def test_pins_do_not_survive_the_split(catalogue, tmp_path):
    """A take accepted for the catalogue was never a take of this cut."""
    out = run(catalogue, tmp_path)
    for path in out["written"]:
        assert json.loads(open(path, encoding="utf-8").read())["pin"] == {}


def test_dry_run_writes_nothing(catalogue, tmp_path):
    out = run(catalogue, tmp_path, dry_run=True)
    assert out["written"] == [] and out["dry_run"] is True
    assert not (tmp_path / "out").exists()


def test_a_thin_cut_is_reported_before_it_is_rendered(catalogue, tmp_path):
    """min_duration_s is 25 s here and a two-item cut cannot reach it."""
    out = run(catalogue, tmp_path)
    rows = {r["episode"]: r for r in out["plan"]}
    assert any(r["clears_min_duration"] is False for r in rows.values()), rows
    assert all("estimated_seconds" in r for r in rows.values())


def test_every_product_appears_exactly_once(catalogue, tmp_path):
    out = run(catalogue, tmp_path)
    ids = [i.id for p in out["written"] for i in Config.load(p).items]
    assert sorted(ids) == ["chain", "skirt", "tall", "top"]
