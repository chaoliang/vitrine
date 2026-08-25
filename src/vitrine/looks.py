# -*- coding: utf-8 -*-
"""Split a catalogue into outfits, one video each.

A shop sends twenty SKUs, not four. Something has to decide which ones share a
video, and it is a styling decision before it is a scheduling one: four items
that make one outfit read as a lookbook, four items taken in row order read as a
slideshow.

Three rules, in priority order:

1. **Nothing that clashes shares a video.** A midi hem and a knee-high shaft are
   on screen together at some point even when they go on in different beats, so
   the check is pairwise over the whole group, not over adjacent beats.
2. **Prefer one item per body region** -- torso, waist, feet, then accessories --
   because that is a complete outfit. Fall back to a second item in a region
   only when nothing else fits: for a shop that sells nothing but skirts, four
   skirts in one video is not a compromise, it is the correct change sequence.
3. **Every SKU appears exactly once.** The shop paid for all of them.

Beats inside a look are ordered the way a person actually dresses: clothes
before shoes before bag before jewellery. That ordering is also what keeps the
hands' entry directions from crossing over each other.
"""
from __future__ import annotations

from . import compat

# the order a person dresses in, which is also the order the shots go in
DRESS_ORDER = ["torso", "waist", "feet", "shoulder", "neck", "wrist", "ear"]
ORDER_INDEX = {r: i for i, r in enumerate(DRESS_ORDER)}

MAX_ITEMS = 4          # measured: four items is 33 s, the length that sells
SECONDS_PER_ITEM = 6.6  # measured on the same runs, for the planning estimate
SECONDS_FIXED = 6.5     # ending plus the opening beat


def occupies(item) -> set[str]:
    """Every region this item covers, not only the one it is filed under.

    A dress is filed under `torso` and has a hem, which means it also occupies
    the waist -- so it cannot share a video with a skirt even though their
    regions differ. Derived from the fields that already exist rather than from
    a new "is a dress" flag, which would be one more thing to get wrong.
    """
    covered = {item.region}
    if item.region == "torso" and item.hem != "none":
        covered.add("waist")
    return covered


def _conflicts(item, look: list) -> bool:
    for other in look:
        # a shared region is a change of that garment, which is fine; a partial
        # overlap between different regions is a dress fighting a skirt
        shared = occupies(item) & occupies(other)
        if shared and item.region != other.region:
            return True
        pairs = ((item.hem, other.shaft) if other.region == "feet" else None,
                 (other.hem, item.shaft) if item.region == "feet" else None)
        for pair in pairs:
            if pair and pair[0] != "none" and compat.check(*pair):
                return True
    return False


def _score(item, look: list) -> tuple:
    """Lower sorts first: a new region beats a repeat, dress order breaks ties."""
    used = {i.region for i in look}
    return (item.region in used, ORDER_INDEX.get(item.region, 99))


def assemble(items: list, max_items: int = MAX_ITEMS) -> list[list]:
    """Greedy: anchor each look with the earliest unused garment, then fill it.

    Greedy rather than exhaustive on purpose. The constraint graph is tiny, and
    whoever runs this has to be able to read the grouping and agree with it -- a
    search that produced a marginally better packing but an inexplicable one
    would cost more review time than it saves render time.
    """
    if max_items < 1:
        raise ValueError(f"max_items must be at least 1, got {max_items}")
    pool = sorted(items, key=lambda i: ORDER_INDEX.get(i.region, 99))
    looks: list[list] = []

    while pool:
        look = [pool.pop(0)]
        while len(look) < max_items:
            candidates = [i for i in pool if not _conflicts(i, look)]
            if not candidates:
                break
            pick = min(candidates, key=lambda i: _score(i, look))
            pool.remove(pick)
            look.append(pick)
        look.sort(key=lambda i: ORDER_INDEX.get(i.region, 99))
        looks.append(look)

    return looks


def estimate_seconds(n_items: int) -> float:
    return round(SECONDS_FIXED + SECONDS_PER_ITEM * n_items, 1)


def describe(looks: list[list]) -> list[dict]:
    """The plan to read before any GPU is spent."""
    return [{"n": n, "items": len(look),
             "estimated_seconds": estimate_seconds(len(look)),
             "products": [f"{i.id} {i.name}" for i in look],
             "regions": [i.region for i in look],
             "thin": len(look) < 2}
            for n, look in enumerate(looks, 1)]
