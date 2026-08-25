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
from dataclasses import asdict, dataclass, field
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
class Camera:
    """Optional camera-movement LoRA and the move each kind of shot gets.

    Off by default. The pipeline's shots are fixed-camera, and the push-in it
    sells is done in the cut by cutting to a natively rendered detail take --
    that stays true, this is not a replacement for it. What a camera LoRA adds
    is movement *inside* a take, which a fixed frame cannot have.

    Measured on 2026-08-25: the move costs nothing (292.0s with the LoRA vs
    292.1s without), and the trigger word has to lead the prompt or the LoRA
    does not engage.
    """

    lora: str                       # file name under ComfyUI models/loras
    strength: float = 1.0           # the LoRA's own README: 0.8 gentle, 1.0 clear, >1.2 unstable
    trigger: str = "camera motion"  # must lead the prompt
    moves: dict = field(default_factory=dict)   # wide / detail / ending -> move phrase

    KINDS = ("wide", "detail", "ending")

    def validate(self) -> None:
        if not self.lora.strip():
            raise ValueError("camera.lora is empty; drop the camera block to disable it")
        if not 0.0 < self.strength <= 1.5:
            raise ValueError(
                f"camera.strength {self.strength} is outside 0-1.5; the LoRA's own "
                f"guidance is 0.8-1.0 and above 1.2 the frame stops being stable")
        unknown = set(self.moves) - set(self.KINDS)
        if unknown:
            raise ValueError(
                f"camera.moves has unknown shot kinds {sorted(unknown)}; "
                f"use any of {list(self.KINDS)}")

    def move_for(self, kind: str) -> str | None:
        return (self.moves.get(kind) or "").strip() or None


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
    # Absent means fixed camera, which is what every episode shipped so far used.
    camera: Camera | None = None

    @staticmethod
    def load(path: str | Path, as_catalogue: bool = False) -> "Config":
        """Read a config. `as_catalogue` skips the outfit check only.

        The clash rule is an invariant of one *video*, not of a list of products:
        a catalogue is expected to contain a midi skirt and a knee-high boot, and
        resolving that by putting them in different videos is exactly what
        `vitrine split` is for. Refusing to load its own input would make the
        command impossible to use on the catalogues that need it most.
        """
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg = Config(
            episode=d["episode"], series=d["series"], cta=d["cta"],
            model_ref=d["model_ref"], identity=d["identity"],
            scenes=d["scenes"], items=[Item(**i) for i in d["items"]],
            ending=Ending(**d["ending"]) if d.get("ending") else None,
            camera=Camera(**d["camera"]) if d.get("camera") else None,
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
        if cfg.camera:
            cfg.camera.validate()
        if not as_catalogue:
            cfg.check_outfit()
        if cfg.ending and cfg.ending.scene not in cfg.scenes:
            raise ValueError(f"ending scene {cfg.ending.scene!r} not defined")
        return cfg

    def to_json(self) -> dict:
        """Round-trips through `load`: every field the loader reads, and no more."""
        d = {"episode": self.episode, "series": self.series, "cta": self.cta,
             "model_ref": self.model_ref, "identity": self.identity,
             "scenes": self.scenes, "style": self.style,
             "overlays": self.overlays, "asset_dir": self.asset_dir,
             "pin": self.pin, "min_duration_s": self.min_duration_s,
             "items": [asdict(i) for i in self.items]}
        if self.ending:
            d["ending"] = asdict(self.ending)
        if self.camera:
            # Must round-trip: `split` rebuilds configs through here, and a
            # camera block dropped on the way out is movement the split videos
            # silently lose.
            d["camera"] = asdict(self.camera)
        return d

    def check_outfit(self) -> None:
        """Every hem in the outfit against every footwear shaft worn with it."""
        hems = [i for i in self.items if i.hem != "none"]
        feet = [i for i in self.items if i.region == "feet"]
        for h in hems:
            for f in feet:
                why = compat.check(h.hem, f.shaft)
                if why:
                    raise ValueError(f"{h.id} + {f.id}: {why}")
