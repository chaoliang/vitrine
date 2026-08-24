# -*- coding: utf-8 -*-
"""Native framings for the detail takes, one per body region.

These are prompt-level framings, not crops. A 768x1344 render does not survive
being punched in on a pair of boots -- that is a five-times upscale -- so the
detail shot is generated at that framing instead of cut out of the wide one.
"""

DETAIL_FRAMING = {
    "torso": ("Three-quarter vertical framing from the top of her head down to "
              "just below her knee, her whole face in frame and clearly alive, "
              "the garment filling the centre of the picture so its cut, "
              "length, shoulder line and how it falls on a real body all read at "
              "once. She is unmistakably a person wearing it, never a garment on "
              "a mannequin or a hanger."),
    "neck": ("Close vertical framing on her collarbones and the base of her "
             "neck, cropped just above her mouth and just below her chest, the "
             "neckpiece dead centre and large in frame."),
    "feet": ("Low vertical framing from floor level up to her knees only, her "
             "footwear filling the lower two thirds of the frame, the floor "
             "surface visible beneath."),
    "wrist": ("Tight vertical framing on her forearm and hand held up in front "
              "of her, cropped at the elbow and above the fingertips, the piece "
              "on her wrist dead centre and large in frame."),
    "shoulder": ("Close vertical framing from the top of her head to her waist, "
                 "angled on the shoulder that carries the piece."),
    "waist": ("Close vertical framing from her ribs to her upper thigh, the "
              "waistline dead centre."),
    "ear": ("Tight vertical framing on the side of her face from temple to jaw, "
            "the ear and the piece on it dead centre."),
}

# which side of the frame the giant hands come from, and how they travel
ENTRY_PHRASING = {
    "above": ("two giant manicured hands lower {obj} into frame from directly "
              "above her, descending steadily"),
    "below": ("two giant manicured hands rise into frame from below the bottom "
              "edge carrying {obj}, coming up from floor level"),
    "left": ("one giant manicured hand comes in from the left edge of frame "
             "carrying {obj}, travelling right"),
    "right": ("one giant manicured hand comes in from the right edge of frame "
              "carrying {obj}, travelling left"),
}

# The dressing take's framing, per region. Full body is the default because the
# giant-hand scale contrast needs it -- but a necklace is fastened at neck
# height, so in a full-body frame the hands *must* arrive level with her head and
# will crowd it no matter how many negatives are added. The reference video cuts
# to a medium for exactly this beat. Composition solves it; prohibitions do not.
WIDE_FRAMING = {
    "neck": ("Fixed medium vertical framing from just above her head down to her "
             "hips, her upper body filling the frame, so hands working at her "
             "neck are naturally composed and never crowd her face."),
    "ear": ("Fixed medium close vertical framing from just above her head down to "
            "her chest."),
}
ENDING_FRAMING = ("Full-body vertical framing, <Subject 1> centred with her "
                  "entire head including the top of her hair inside the frame "
                  "and clear background above it, both feet inside the frame "
                  "with a clear gap below them, and her face never cropped by "
                  "any edge.")

WIDE_DEFAULT = ("Full-body vertical framing, <Subject 1> centred. Her entire "
                "head including the very top of her hair is inside the frame "
                "with a clear gap of empty background above it, and both feet "
                "are inside the frame with a clear gap below them. Her face is "
                "never cropped by any edge at any moment of the take.")

# (region, entry) -> choreography that direction alone gets wrong
ENTRY_BY_REGION = {
    ("neck", "above"): (
        "only the fingertips of two giant hands reach down into the top of frame "
        "holding {obj} stretched between them; the hands stay high and well "
        "behind her shoulders, they never come down beside her face, never "
        "surround her head and never fill the frame around her"),
    ("ear", "above"): (
        "the fingertips of one giant hand reach down into the top corner of frame "
        "holding {obj}, approaching from behind and above her ear, never crossing "
        "in front of her face"),
}

# A product shot has to show the thing *worn*. Saying only "centred and large in
# frame" got a necklace rendered floating in front of her chest, detached from
# her body -- technically the subject of the shot, commercially useless.
WORN_CONTACT = {
    "neck": ("The chain lies flat against her skin the whole time, following the "
             "curve at the base of her throat, and the pendant rests in the "
             "hollow there under its own weight. It is worn and in contact with "
             "her body at every point of the take."),
    "wrist": ("The piece sits around her wrist in contact with her skin, resting "
              "against the wrist bone under its own weight, worn and not held."),
    "feet": ("Her feet are inside the footwear, the closures done up, the soles "
             "flat on the floor and taking her weight."),
    "torso": ("The garment is on her body, in contact along her shoulders and "
              "sides, following her shape and moving when she moves."),
    "waist": ("The garment sits on her waist in contact with her body, its "
              "waistband against her, hanging under its own weight."),
    "shoulder": ("The strap rests on her shoulder in contact with the cloth, "
                 "taking the weight of the bag."),
    "ear": "The piece hangs from her earlobe under its own weight.",
}

OCCLUSION = {
    "torso": "the garment completely covers her torso",
    "neck": "the fingers completely cover both sides of her neck",
    "feet": "the footwear and the fingers completely cover both of her lower legs",
    "wrist": "the fingers completely cover her wrist",
    "shoulder": "the hand and the strap completely cover her shoulder",
    "waist": "the hands completely cover her waistline",
    "ear": "the fingers completely cover her ear",
}
