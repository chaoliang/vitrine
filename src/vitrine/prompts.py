# -*- coding: utf-8 -*-
"""Assemble H3 Ref2VA prompts from a config.

Each item produces two takes:
  WIDE   - the dressing action, full body, so the giant-hand scale contrast reads
  DETAIL - the product itself, framed natively at its own body region

The performance language is deliberately large. An earlier version wrote every
beat with a diminutive (slightly, once, small, closed-mouth) and produced a
mannequin; the words banned in NEG are the ones that caused it.
"""
from __future__ import annotations

from . import styles
from .framing import (DETAIL_FRAMING, ENDING_FRAMING, ENTRY_BY_REGION,
                     ENTRY_PHRASING, OCCLUSION, WIDE_DEFAULT,
                     WIDE_FRAMING, WORN_CONTACT)

HANDS = (
    "The giant hands are life-sized female hands, much larger than <Subject 1>, "
    "with realistic skin, stable proportions and anatomically correct left and "
    "right hands of five fingers each, wearing long almond mirror-silver nails. "
    "They never touch her head or her face."
)

NEG_BASE = (
    "The swap happens only inside the moment of fullest occlusion and never uses "
    "a flash, smoke, sparkle or dissolve effect. No identity change, no face "
    "swap, no big-headed doll, no chibi, no plastic toy skin, no shortened legs, "
    "no body deformation, no extra fingers, no extra limbs, no third hand, no "
    "giant hand touching her head or face, no clothing passing through the body, "
    "no floating or detached product, no product held up in front of her body "
    "instead of worn on it, no floating accessories, no giant hand caging, ringing or crowding her "
    "face, no giant hand entering the frame at the height of her face, no text, "
    "no captions, no logos, no emblems, no "
    "brand marks, no interlocking letters, nothing resembling an existing "
    "luxury brand, no watermark, no camera movement, no cut, no speech. She must "
    "never stand still with her arms at her sides and never hold a blank neutral "
    "face."
)

CAMERA = ("Fixed eye level camera with a 50mm look: no push, no pull, no pan, no "
          "tilt, no roll and no focal length change at any point.")


def _neg(style) -> str:
    return f"{NEG_BASE} For this style: {style.forbid}." if style.forbid else NEG_BASE


def pictures(has_product: bool, carry: bool) -> dict[str, int]:
    """Which staged reference image is which ``<Picture N>``.

    build.py stages ``[identity] + [product?] + [carry?]`` and the backend prunes
    the slots it does not use, so the numbering shifts from shot to shot: the
    continuity frame is Picture 3 behind a packshot and Picture 2 without one.
    Naming a subject without naming its picture leaves the model to guess which
    photograph is the product and which is last shot's final frame -- and it
    guesses differently in the wide take than in the detail take, which is how
    two takes of one necklace end up disagreeing about it.
    """
    pics = {"identity": 1}
    if has_product:
        pics["product"] = len(pics) + 1
    if carry:
        pics["carry"] = len(pics) + 1
    return pics


def _shell(identity: str, summary: str, scene: str, shot: str,
           product: str = "", has_product: bool = False, carry: bool = False,
           style=None) -> str:
    """`product` names the SKU when the config supplies real photographs of it.

    A factory's whole requirement is that the video shows *their* garment, so
    when product photos are present the product becomes <Subject 2> at
    fully_preserved and the prompt forbids redesigning it. Without photos the
    model is free to design from the text, which is fine for a mock-up and
    useless for a catalogue.

    Exactly one photograph of the product is ever staged, whatever the config
    lists -- ``product_still`` picks the first. An earlier version told the model
    there were ``len(item.refs)`` reference frames of it, so a config carrying
    three factory photos promised three and delivered one. A prompt that cites
    pictures which are not there is the same defect as one that cites none.
    """
    pics = pictures(has_product, carry)
    subj2 = ""
    ret2 = ""
    subj3 = ""
    ret3 = ""
    if carry:
        # A frame lifted from the previously accepted take. It is the only thing
        # that carries the accumulated outfit through a set change, because H3
        # keeps no state between calls.
        subj3 = (f"\n<Subject {len(pics)}> is the continuity frame shown in "
                 f"<Picture {pics['carry']}>: it shows <Subject 1> wearing everything she has "
                 f"already put on. Every garment and accessory visible on her in "
                 f"that frame must appear on her here at the same size, colour, "
                 f"cut and position on her body. Its background, its set and its "
                 f"lighting are not retained -- only what she is wearing.")
        ret3 = (f"\n<Subject {len(pics)}>: partially_preserved -- the clothing and "
                f"accessories she already wears are carried over exactly; the "
                f"background and lighting of that frame are not.")
    if product and has_product:
        subj2 = (f"\n<Subject 2> is {product}, exactly as photographed in "
                 f"<Picture {pics['product']}>. Its cut, colour, "
                 f"texture, closures, hardware, stitching and proportions must "
                 f"match that photograph exactly and must never be "
                 f"redesigned, restyled or substituted.")
        ret2 = ("\n<Subject 2>: fully_preserved -- the product is reproduced "
                "exactly as photographed and is not redesigned.")
    return f"""subject_definitions:
{len(pics)} reference image{'' if len(pics) == 1 else 's'} accompany this generation, numbered <Picture 1>{f" to <Picture {len(pics)}>" if len(pics) > 1 else ""}. No other picture exists.
<Subject 1> is the woman shown in <Picture {pics['identity']}>: {identity} {style.performance()} The garment shown in <Picture {pics['identity']}> is wardrobe only and is not preserved.{subj2}{subj3}

summary:
[reference generation] {summary}

retention_analysis:
<Subject 1>: partially_preserved -- face, hair, skin tone and body proportions are fully retained; her expression, gaze, posture and movement amplitude are explicitly not constrained; the garment shown in <Picture {pics['identity']}> is not retained.{ret2}{ret3}

detailed_description:
{scene} {style.light} {style.palette} {CAMERA}
[Shot 1] {shot} {_neg(style)}

overall_soundscape: Quiet room tone for this set, the rustle and snap of fabric and leather being moved, one faint click of long nails, and her footfalls when she moves; no speech and no music.

non_diegetic_music: N/A"""


def _obj(item) -> str:
    """How the object is referred to inside the beats."""
    return f"<Subject 2>, {item.garment}," if item.refs else item.garment


def _scale(item) -> str:
    """The same sentence in both takes, so the piece cannot change size."""
    return f" {item.scale.rstrip('.')}. This size relative to her body is fixed and identical in every shot."


def wide(cfg, item, wearing: str, carry: bool = False) -> str:
    style = styles.get(cfg.style)
    """The dressing beat: hands bring the item in from its own direction."""
    template = ENTRY_BY_REGION.get((item.region, item.enter),
                                   ENTRY_PHRASING[item.enter])
    entry = template.format(obj=_obj(item))
    already = f" She is already wearing {wearing}." if wearing else ""
    return _shell(
        cfg.identity,
        f"A locked-off vertical take in which giant hands put {item.name} onto "
        f"<Subject 1>, the swap hidden inside the occlusion the object itself creates.",
        cfg.scenes[item.scene],
        f"{WIDE_FRAMING.get(item.region, WIDE_DEFAULT)} This framing is fixed "
        f"for the whole take and never drifts wider or tighter.{already} "
        f"{HANDS} "
        f"From 0.000 to 0.900 {style.opening}. "
        f"From 0.900 to 2.100 {entry}; her gaze goes to it and she answers it "
        f"with her whole body, in this style's register. "
        f"{_scale(item)} "
        f"From 2.100 to 3.500 the hands bring it into place; between 2.700 and "
        f"3.100 {OCCLUSION[item.region]} and, in that fully covered instant and "
        f"only then, she is already wearing it. "
        f"From 3.500 to 4.400 the hands withdraw back out the way they came in, "
        f"off the same edge of frame they entered from. "
        f"From 4.400 to 5.167 {item.action or style.closing}, "
        f"the set unchanged from the first frame.",
        product=item.garment, has_product=bool(item.refs), carry=carry,
        style=style)


def ending(cfg, wearing: str, scene: str, action: str, carry: bool = False) -> str:
    """The closing take: the finished look and one complete action.

    Every item take stops the moment its product is on, which leaves the video
    ending on a fragment. A viewer needs to see the whole outfit worn and moving
    once before the video is over.
    """
    style = styles.get(cfg.style)
    return _shell(
        cfg.identity,
        "A locked-off vertical closing take of <Subject 1> wearing the finished "
        "look, performing one complete action.",
        cfg.scenes[scene],
        f"{ENDING_FRAMING} No giant hands appear at any point in this take. She "
        f"is wearing the complete finished look: {wearing}. Every garment and "
        f"accessory stays exactly as it was put on and nothing changes. "
        f"From 0.000 to 1.000 {style.opening}. "
        f"From 1.000 to 3.600 {action}. "
        f"From 3.600 to 4.500 the movement resolves and she comes back to "
        f"stillness facing the lens, the clothes settling under their own weight. "
        f"From 4.500 to 5.167 {style.closing}, the set unchanged from the first "
        f"frame.",
        carry=carry, style=style)


def detail(cfg, item, wearing: str, carry: bool = False) -> str:
    style = styles.get(cfg.style)
    """The product shot: framed at the item's own region, natively."""
    side = ""
    if item.side:
        side = (f" She holds the {item.side} side toward the lens so the piece "
                f"reads clearly.")
    return _shell(
        cfg.identity,
        f"A locked-off vertical product shot of {item.name} worn by <Subject 1>, "
        f"framed on the part of her body that carries it.",
        cfg.scenes[item.scene],
        f"{DETAIL_FRAMING[item.region]}{side} She is wearing "
        f"{wearing or item.garment}, and {_obj(item)} is the subject of this "
        f"shot and must stay sharp and centred for the whole take. "
        f"{WORN_CONTACT.get(item.region, '')}"
        f"{_scale(item)} "
        f"From 0.000 to 1.200 the piece is held still and the light travels "
        f"across its surface and texture. "
        f"From 1.200 to 3.200 she moves it through one slow, generous turn in "
        f"this style's register so "
        f"the lens sees a second face of it -- the material, the edge and the "
        f"hardware all read. "
        f"From 3.200 to 4.300 she settles it back and the surface catches the "
        f"key light again. "
        f"From 4.300 to 5.167 the piece holds still and perfectly framed, the "
        f"background quiet and out of focus behind it.",
        product=item.garment, has_product=bool(item.refs), carry=carry,
        style=style)
