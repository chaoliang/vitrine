# -*- coding: utf-8 -*-
"""Config schema for the product-video generator.

Everything that changes between two videos lives in a JSON config: the model
reference, the sets, and the item list. Nothing about a particular product is
written into the code, so a new video is a new config rather than a new script.

Two rules are enforced here rather than left to whoever writes the config,
because both were learned by getting them wrong:
- an item's detail shot must frame the item, not the model. Putting the camera on
  her upper body right after the boots go on hides the thing being sold.
- the hands must not all come from the front. Entry direction is per item and is
  what decides which side the detail shot sits on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import compat
from . import styles

# where a product lives on the body -> the detail take must be framed there
REGION_FOR = {
    "torso": "torso", "neck": "neck", "feet": "feet",
    "wrist": "wrist", "shoulder": "shoulder", "ear": "ear", "waist": "waist",
}
# a garment is lowered onto her, footwear comes up from the floor, and anything
# worn on one side arrives from that side so the detail shot can sit there
ENTRY = {"above", "below", "left", "right"}
SIDES = {"left", "right", None}


@dataclass
class Item:
    id: str
    name: str                 # what the price chip says
    price: str
    garment: str              # prompt fragment describing the object
    region: str               # torso / neck / feet / wrist / shoulder ...
    enter: str                # above / below / left / right
    scene: str                # key into config.scenes
    side: str | None = None   # left / right for one-sided items
    specs: list[str] = field(default_factory=list)
    hold_s: float = 0.0       # dwell on the spec card, 0 disables it
    action: str = ""          # what she does with it once it is on
    # The factory's own photographs of this SKU, relative to the config's
    # asset_dir. When present the model is told to reproduce the garment in
    # these frames exactly instead of designing one from the text.
    refs: list[str] = field(default_factory=list)
    # The product's real size and how it sits on the body, stated identically in
    # the wide and the detail take. Without it each take invents its own scale
    # and the piece changes size between the two -- the defect that made a
    # necklace read as one width on her body and another in close-up.
    scale: str = ""
    # Per-take in-points, for trimming past a defect an operator has accepted
    # rather than re-rolling the whole take. None means use the editor default.
    wide_in: float | None = None
    detail_in: float | None = None
    # Silhouette, for the outfit-clash check. A hem and a boot shaft that end at
    # the same height collide on screen; nothing in the prompt can hide it.
    hem: str = "none"       # mini / knee / midi / maxi / none
    shaft: str = "flat"     # flat / ankle / mid_calf / knee / over_knee

    def validate(self, scenes: dict) -> None:
        if self.region not in REGION_FOR:
            raise ValueError(f"{self.id}: unknown region {self.region!r}")
        if self.enter not in ENTRY:
            raise ValueError(f"{self.id}: enter must be one of {sorted(ENTRY)}")
        if self.side not in SIDES:
            raise ValueError(f"{self.id}: side must be left, right or null")
        if self.scene not in scenes:
            raise ValueError(f"{self.id}: scene {self.scene!r} not defined")
        if self.region == "feet" and self.enter != "below":
            raise ValueError(f"{self.id}: footwear has to come from below")
        if self.region in ("torso", "neck") and self.enter != "above":
            raise ValueError(f"{self.id}: a garment or neckpiece is lowered from above")
        if self.side and self.enter != self.side:
            raise ValueError(
                f"{self.id}: a {self.side}-side item must enter from the {self.side}")
        if self.region == "feet" and self.shaft == "flat":
            raise ValueError(
                f"{self.id}: footwear needs a real shaft height for the clash "
                f"check -- ankle / mid_calf / knee / over_knee")
        if self.specs and self.hold_s <= 0:
            raise ValueError(f"{self.id}: specs given but hold_s is 0")
        if not self.scale.strip():
            raise ValueError(
                f"{self.id}: scale is required -- state the real dimensions and "
                f"how the piece sits, or the two takes will disagree")
        if len(self.refs) > 2:
            raise ValueError(
                f"{self.id}: at most 2 product photos per item; slot 0 is the "
                f"model identity and the last slot carries continuity")


@dataclass
class Ending:
    """The closing take. Set to null in the config to end on the last product."""
    scene: str
    action: str
    beats: int = 10          # how long it runs in the cut


@dataclass
class Config:
    episode: str
    series: str
    cta: str
    model_ref: str
    identity: str             # the locked-identity sentence
    scenes: dict              # name -> set description used in the prompt
    items: list[Item]
    # Expression, movement, light and palette all come from here. Putting a
    # bubbly performance on mature tailoring reads wrong however good the
    # garment is, so the register is merchandising, not decoration.
    ending: Ending | None = None
    style: str = "mature-quiet-luxury"
    overlays: str = "none"    # none / chips / chips+specs
    asset_dir: str = ""       # where model_ref and every item ref live
    # Accepted takes, e.g. {"dress_detail": "dress_detail_00002_.mp4"}. Without
    # this the editor takes whatever rendered last, so one retry of a
    # neighbouring shot silently replaces a take that was already signed off.
    pin: dict = field(default_factory=dict)
    min_duration_s: float = 0.0

    @staticmethod
    def load(path: str | Path) -> "Config":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg = Config(
            episode=d["episode"], series=d["series"], cta=d["cta"],
            model_ref=d["model_ref"], identity=d["identity"],
            scenes=d["scenes"], items=[Item(**i) for i in d["items"]],
            ending=Ending(**d["ending"]) if d.get("ending") else None,
            style=d.get("style", "mature-quiet-luxury"),
            overlays=d.get("overlays", "none"),
            asset_dir=str(Path(d.get("asset_dir", "")).expanduser()),
            pin=d.get("pin", {}),
            min_duration_s=d.get("min_duration_s", 25.0))
        ids = [i.id for i in cfg.items]
        if len(set(ids)) != len(ids):
            raise ValueError("item ids must be unique")
        styles.get(cfg.style)
        if cfg.overlays not in ("none", "chips", "chips+specs"):
            raise ValueError(f"unknown overlays mode {cfg.overlays!r}")
        for it in cfg.items:
            it.validate(cfg.scenes)
        cfg.check_outfit()
        if cfg.ending and cfg.ending.scene not in cfg.scenes:
            raise ValueError(f"ending scene {cfg.ending.scene!r} not defined")
        return cfg

    def check_outfit(self) -> None:
        """Every hem in the outfit against every footwear shaft worn with it."""
        hems = [i for i in self.items if i.hem != "none"]
        feet = [i for i in self.items if i.region == "feet"]
        for h in hems:
            for f in feet:
                why = compat.check(h.hem, f.shaft)
                if why:
                    raise ValueError(f"{h.id} + {f.id}: {why}")
