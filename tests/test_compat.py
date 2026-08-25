# -*- coding: utf-8 -*-
"""Outfit clashes, and titles that disagree with their own photograph."""
from __future__ import annotations

import pytest

from vitrine import compat


class TestClash:
    def test_a_midi_hem_over_a_knee_high_shaft_collides(self):
        assert compat.check("midi", "over_knee") is not None
        assert compat.check("midi", "knee") is not None

    def test_a_midi_hem_over_an_ankle_boot_is_fine(self):
        assert compat.check("midi", "ankle") is None

    def test_a_mini_hem_clears_any_shaft(self):
        assert all(compat.check("mini", s) is None for s in compat.SHAFT)

    def test_an_unknown_value_is_an_error_not_a_silent_pass(self):
        with pytest.raises(ValueError):
            compat.check("ankle-length", "ankle")
        with pytest.raises(ValueError):
            compat.check("midi", "tall")


class TestTitleVsPhoto:
    def test_an_over_knee_title_on_an_ankle_boot_photo_is_flagged(self):
        assert compat.title_vs_photo("shaft", "over_knee", "ankle-height")

    def test_a_title_that_agrees_is_silent(self):
        assert compat.title_vs_photo("shaft", "ankle", "ankle-height") is None

    def test_footwear_is_checked_at_one_step(self):
        """Shaft height is where titles lie most often, so the gate is tight."""
        assert compat.title_vs_photo("shaft", "knee", "mid-calf")

    def test_hems_need_two_steps(self):
        """A skirt photographed flat is genuinely hard to place."""
        assert compat.title_vs_photo("hem", "midi", "knee-length") is None
        assert compat.title_vs_photo("hem", "mini", "floor-length")

    def test_a_photo_naming_no_length_is_not_a_disagreement(self):
        assert compat.title_vs_photo("shaft", "over_knee", "") is None
        assert compat.title_vs_photo("shaft", "over_knee", "regular") is None

    def test_a_photo_naming_two_heights_is_not_a_disagreement(self):
        """'short shaft with a tall heel' used to resolve by dict order."""
        assert compat.title_vs_photo(
            "shaft", "over_knee", "short shaft with a tall heel") is None

    def test_the_message_says_what_to_check(self):
        why = compat.title_vs_photo("shaft", "over_knee", "ankle")
        assert "wrong row" in why and "title is wrong" in why

    def test_an_unknown_kind_is_an_error(self):
        with pytest.raises(ValueError):
            compat.title_vs_photo("length", "midi", "knee")
