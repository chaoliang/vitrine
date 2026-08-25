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


# What a photograph says about length, mapped back into this file's vocabulary.
# A vision model describes the shop's own photo in English; the product title is
# what the sheet states. When the two disagree the photo wins, and saying so
# before rendering costs a second instead of the twenty-five minutes it took to
# discover a knee-high boot rendered from an ankle-boot photo after the fact.
PHOTO_SHAFT = {
    "ankle": "ankle", "ankleheight": "ankle", "anklehigh": "ankle",
    "bootie": "ankle", "booties": "ankle", "short": "ankle", "low": "ankle",
    "midcalf": "mid_calf", "calf": "mid_calf", "calfheight": "mid_calf",
    "knee": "knee", "kneehigh": "knee", "kneelength": "knee", "tall": "knee",
    "overknee": "over_knee", "abovetheknee": "over_knee", "overtheknee": "over_knee",
    "thigh": "over_knee", "thighhigh": "over_knee",
}
PHOTO_HEM = {
    "mini": "mini", "micro": "mini", "short": "mini", "aboveknee": "mini",
    "knee": "knee", "kneelength": "knee",
    "midi": "midi", "midcalf": "midi", "calf": "midi", "calflength": "midi",
    "maxi": "maxi", "floor": "maxi", "floorlength": "maxi", "ankle": "maxi",
    "anklelength": "maxi", "full": "maxi", "fulllength": "maxi",
}


def _lookup(text: str, table: dict) -> str | None:
    """The one length this phrase names, or None when it names none or several.

    Two words in one phrase can map to different heights -- "short shaft with a
    tall heel" hits both "short" and "tall" -- and which one won depended on
    dict order. An ambiguous phrase is not evidence of a disagreement, so it
    yields nothing rather than a coin flip.
    """
    words = str(text or "").lower().replace("-", " ").replace("/", " ").split()
    hits = {table[w] for w in words + ["".join(words)] if w in table}
    return hits.pop() if len(hits) == 1 else None


def photo_shaft(text: str) -> str | None:
    return _lookup(text, PHOTO_SHAFT)


def photo_hem(text: str) -> str | None:
    return _lookup(text, PHOTO_HEM)


def title_vs_photo(kind: str, stated: str, photo_length: str) -> str | None:
    """Flag a product title that disagrees with its own photograph.

    Footwear is checked at one step, because shaft height is exactly where a
    title lies most often -- "soft sole", "ankle boot", "over the knee" are
    marketing words as much as measurements. Hems need two steps: a skirt
    photographed flat is genuinely hard to place, and a gate that fires on
    wording costs more than it saves.
    """
    if kind not in ("shaft", "hem"):
        raise ValueError(f"kind must be 'shaft' or 'hem', got {kind!r}")
    if kind == "shaft":
        seen, scale, gap, what = photo_shaft(photo_length), SHAFT, 1, "shaft height"
    else:
        seen, scale, gap, what = photo_hem(photo_length), HEM, 2, "hem length"
    if not seen or stated not in scale or seen == stated:
        return None
    if abs(scale[seen] - scale[stated]) < gap:
        return None
    return (f"the title says {stated}, but the photograph looks {seen}. The "
            f"{what} is rendered from the photograph, so a title that disagrees "
            f"with it produces a video that does not match the product. Check "
            f"whether the photo is on the wrong row or the title is wrong.")
