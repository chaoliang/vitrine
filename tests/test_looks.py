# -*- coding: utf-8 -*-
"""Grouping a catalogue into outfits.

Every assertion here is something that went wrong once, on real orders: a shop
that sells only skirts got one video per skirt; a midi skirt and a knee-high
boot were rendered together and their silhouettes collided; a dress shared a
video with a skirt.
"""
from __future__ import annotations

import pytest

from vitrine import compat, looks
from vitrine.schema import Item


def item(sku: str, region: str, *, hem: str = "none", shaft: str = "flat") -> Item:
    enter = {"feet": "below", "shoulder": "left", "wrist": "right"}.get(region, "above")
    side = {"shoulder": "left", "wrist": "right"}.get(region)
    return Item(id=sku, name=sku, price="", garment=f"a {sku}", region=region,
                enter=enter, scene="room", side=side, hem=hem, shaft=shaft)


def flat(groups):
    return [i.id for g in groups for i in g]


def clash_free(group) -> bool:
    return not any(compat.check(a.hem, b.shaft)
                   for a in group if a.hem != "none"
                   for b in group if b.region == "feet")


def invariants(items, groups, cap=4):
    assert sorted(flat(groups)) == sorted(i.id for i in items), "an SKU went missing"
    assert len(flat(groups)) == len(set(flat(groups))), "an SKU appears twice"
    assert all(len(g) <= cap for g in groups), "a video is over the cap"
    assert all(clash_free(g) for g in groups), "a clashing pair shares a video"


def test_a_shop_that_sells_only_skirts_gets_full_videos():
    """One item per region would give ten videos of one skirt each."""
    skirts = [item(f"s{i}", "waist", hem="midi") for i in range(10)]
    groups = looks.assemble(skirts)
    invariants(skirts, groups)
    assert len(groups) == 3, [len(g) for g in groups]


def test_a_complete_outfit_stays_one_video():
    outfit = [item("top", "torso"), item("skirt", "waist", hem="midi"),
              item("boot", "feet", shaft="ankle"), item("chain", "neck")]
    groups = looks.assemble(outfit)
    invariants(outfit, groups)
    assert len(groups) == 1
    assert [i.region for i in groups[0]] == ["torso", "waist", "feet", "neck"], \
        "beats must follow the order a person dresses in"


def test_a_clashing_pair_is_forced_apart():
    items = [item("skirt", "waist", hem="midi"),
             item("tall", "feet", shaft="over_knee"),
             item("top", "torso"), item("chain", "neck")]
    groups = looks.assemble(items)
    invariants(items, groups)
    assert len(groups) == 2


def test_a_dress_never_shares_a_video_with_a_skirt():
    """A dress is filed under torso but occupies the waist as well."""
    dress = item("dress", "torso", hem="midi")
    skirt = item("skirt", "waist", hem="midi")
    assert "waist" in looks.occupies(dress)
    assert "waist" not in looks.occupies(item("cardigan", "torso"))
    groups = looks.assemble([dress, skirt, item("boot", "feet", shaft="ankle")])
    invariants([dress, skirt], [[i for i in g if i.id in ("dress", "skirt")]
                                for g in groups])
    for g in groups:
        ids = {i.id for i in g}
        assert not {"dress", "skirt"} <= ids


def test_a_layerable_top_still_shares_with_a_skirt():
    """The dress rule must not swallow an ordinary cardigan."""
    items = [item("cardigan", "torso"), item("skirt", "waist", hem="midi")]
    assert len(looks.assemble(items)) == 1


def test_eighteen_products_become_five_videos_not_eighteen():
    items = ([item(f"k{i}", "torso") for i in range(4)] +
             [item(f"q{i}", "waist", hem="midi") for i in range(4)] +
             [item(f"x{i}", "feet", shaft="ankle") for i in range(4)] +
             [item(f"n{i}", "neck") for i in range(3)] +
             [item(f"b{i}", "shoulder") for i in range(3)])
    groups = looks.assemble(items)
    invariants(items, groups)
    assert len(groups) == 5, [len(g) for g in groups]


def test_the_cap_is_honoured_and_validated():
    items = [item(f"s{i}", "waist", hem="midi") for i in range(6)]
    assert [len(g) for g in looks.assemble(items, 2)] == [2, 2, 2]
    with pytest.raises(ValueError):
        looks.assemble(items, 0)


def test_the_estimate_matches_the_measured_length():
    """Four items measured 33.0 s end to end."""
    assert looks.estimate_seconds(4) == pytest.approx(33.0, abs=0.5)
