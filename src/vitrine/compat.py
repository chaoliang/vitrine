# -*- coding: utf-8 -*-
"""Reject outfits that fight each other, before forty minutes of GPU are spent.

The rule that made this necessary: a mid-calf skirt was paired with
over-the-knee boots. The boot shaft ends inside the hem, so the two garments
collide on screen and no amount of prompt work hides it. A stylist catches that
in a second; a config file does not, unless something checks.
"""
from __future__ import annotations

# how far down the leg each thing reaches
HEM = {"mini": 1, "knee": 2, "midi": 3, "maxi": 4, "none": 0}
SHAFT = {"flat": 0, "ankle": 1, "mid_calf": 2, "knee": 3, "over_knee": 4}

# a hem and a shaft clash when they end at nearly the same height: the boot top
# disappears into the hem and the leg reads as one broken line
CLASH = {
    ("midi", "knee"), ("midi", "over_knee"), ("midi", "mid_calf"),
    ("knee", "knee"), ("knee", "over_knee"),
    ("maxi", "knee"), ("maxi", "over_knee"), ("maxi", "mid_calf"),
}


def check(hem: str, shaft: str) -> str | None:
    """Returns a human explanation when the pair clashes, otherwise None."""
    if hem not in HEM:
        raise ValueError(f"unknown hem {hem!r}; use one of {sorted(HEM)}")
    if shaft not in SHAFT:
        raise ValueError(f"unknown shaft {shaft!r}; use one of {sorted(SHAFT)}")
    if (hem, shaft) in CLASH:
        return (f"a {hem} hem over a {shaft} shaft: the boot top lands inside the "
                f"hem, so the two collide and the leg line breaks. Pair a {hem} "
                f"hem with an ankle boot or a flat, or shorten the hem.")
    return None
