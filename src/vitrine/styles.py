# -*- coding: utf-8 -*-
"""Style profiles: expression, movement, light and palette, all pluggable.

The first version of this pipeline hardcoded one performance -- "laughs with her
mouth open, bounces on her toes, plays to the lens" -- into the prompt builder.
That is a teen-idol register, and putting it on a mature woman's tailoring made
the video read wrong no matter how good the garment was. Expression is not a
detail of the shot; it is part of the merchandising, so it belongs in the
config beside the clothes.

A profile also carries light and palette, because a set lit for bubbly and a set
lit for restrained are not the same set.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    id: str
    expression: str
    movement: str
    light: str
    palette: str
    forbid: str = ""
    # The opening and closing beats carry more weight with the model than the
    # subject block does, so they have to come from the profile too. Leaving a
    # hardcoded "she is already mid-laugh" in the beat text overrode every
    # restrained word elsewhere in the prompt.
    opening: str = ""
    closing: str = ""

    def performance(self) -> str:
        return f"{self.expression} {self.movement}"


MATURE_QUIET = Style(
    id="mature-quiet-luxury",
    expression=(
        "She is composed and self-possessed. She does not grin, laugh out loud or "
        "mug for the camera. Her mouth stays closed or barely parted; the warmth "
        "shows in her eyes and in a slow private half-smile that arrives late and "
        "fades slowly. She meets the lens without performing for it."),
    movement=(
        "She moves unhurried and weight-led: initiated from the hips, weight set "
        "down deliberately, hands falling rather than gesturing. Every beat is a "
        "whole-body movement, but the tempo is slow and the amplitude is "
        "controlled -- never bouncy, never skittish, never girlish."),
    light=(
        "Soft directional daylight from one tall window at camera left, a deep "
        "quiet shadow falling away to camera right, no fill bounce, matte skin, "
        "no sparkle and no rim light."),
    palette=(
        "Warm greige, charcoal, deep brown and off-white throughout the set; no "
        "saturated colour anywhere in frame."),
    forbid=(
        "no open-mouthed laughing, no grinning with teeth showing, no bouncing, "
        "no skipping, no clapping, no waving at the lens, no cutesy or girlish "
        "gestures, no wide-eyed surprise"),
    opening=(
        "she is already standing settled with her weight on one hip, mouth "
        "closed, holding the lens with a level, unhurried gaze"),
    closing=(
        "she lets her hands fall, shifts her weight once and holds the lens with "
        "her mouth closed, a slow half-smile arriving late in the beat"),
)

YOUTHFUL_BRIGHT = Style(
    id="youthful-bright",
    expression=(
        "She is bright and playful: she laughs with her mouth open, her eyes go "
        "wide, and she plays to the lens like a girl filming herself for fun."),
    movement=(
        "She moves with big energy: she throws her arms and her hair around, "
        "bounces on her toes and swings her hips hard. Amplitude is large."),
    light=(
        "Bright even daylight from a wide window, soft fill on both sides, clean "
        "highlights, cheerful and airy."),
    palette="Cream, pale blue and champagne, light and high-key throughout.",
    forbid="no severe or sullen expression, no stiff runway posing",
    opening=("she is already mid-laugh with her mouth open, moving her whole "
             "body and playing to the lens"),
    closing="she throws her arms out and laughs at the lens",
)

STYLES = {s.id: s for s in (MATURE_QUIET, YOUTHFUL_BRIGHT)}


def get(style_id: str) -> Style:
    if style_id not in STYLES:
        raise ValueError(
            f"unknown style {style_id!r}; defined styles: {sorted(STYLES)}")
    return STYLES[style_id]
