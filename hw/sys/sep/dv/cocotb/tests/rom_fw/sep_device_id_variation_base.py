# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-word ``selector_bits`` variation for the chiplet_id and package_id arms.

A word is checked when, and only when, its selector bit is set, and a SELECTED
word which MATCHES does not refuse the slot.

THE RULE, from ``manifest_load.c``. Each arm walks words 0..7, skips a word whose
selector bit is clear, reads ``SMC_FUSE_MAP_<KIND>_OFFSET + i*4`` for a word whose
bit is set, and returns ``MANIFEST_ERR_LC_USAGE_CONSTRAINT`` on the FIRST
disagreement -- echoing ``*_IDX=``, ``*_FUSE=`` and ``*_MFST=`` for that word.
``selector_bits[0..7]`` drive chiplet_id and ``[8..15]`` package_id, read as
``sel & 0xFF`` and ``(sel >> 8) & 0xFF`` respectively.

WHY IT TAKES TWO SLOTS. One slot can carry at most one rejection, so the two SPI
slots are the two poles of the variation:

  PRIMARY -- a PARTIAL mask over one MATCHING and one MISMATCHING word, refused::

      selected + matching     word M   ->  must NOT refuse
      selected + mismatching  word R   ->  must refuse, and *_IDX= must be R
      clear    + mismatching  the rest ->  must NOT refuse

    ``*_IDX=R`` carries all three legs: M < R, and the words below R other than M
    mismatch with their bits CLEAR, so a ROM that ignored the VALUE would report M
    and one that ignored the SELECTOR would report the lowest of those.

  BACKUP -- ALL EIGHT bits set with ALL EIGHT words matching, accepted and booted.

    The arm's satisfied case at full selector width: no comparison failed while the
    manifest declared all eight words checked.

    WHAT THE ACCEPTED SLOT DOES NOT ESTABLISH. The fuse map serves one value for
    every address in its window, so on this slot an offset error, or any
    selector-to-word permutation, is invisible -- all eight comparisons compare
    equal either way. The selector-to-word mapping is pinned by the PRIMARY's
    ``*_IDX=`` under its decoy-bearing partial mask, not here, and the ``+ i*4u``
    per-word address arithmetic (``manifest_load.c``) is exercised by neither slot.
    A successful per-word comparison prints nothing, so the matching leg is an
    absence of rejection and not a positive observation: ``*_IDX=R`` cannot separate
    "word M was read and matched" from "word M was never read".

THE SELECTOR DOMAINS ARE SEPARATED IN BOTH DIRECTIONS. A member sets bits in its
OWN byte only and leaves the other arm's eight words at the mismatching shipped
value with their selectors clear. So on the BACKUP, where this member's byte is
0xFF, a ROM that fed one byte to both loops would refuse the slot on the other
arm; and on the PRIMARY the other arm's token is forbidden outright
(``sep_manifest_field_defect.SIBLING_MARKERS`` via the usage-constraint base).

WHAT THE FUSE SIDE MAY AND MAY NOT CLAIM. The SMC fuse map is a flat
``axi_sim_mem`` (``dv/tb/tb_top.sv``) instantiated with ``UninitializedData
("zeros")`` and nothing writes the chiplet_id/package_id window, so it serves
``0x00000000``. That is a property of the model, not of the part, and
:data:`MODEL_FUSE_WORD` is named as such. The matching words are set to it, so
unlike the mismatch-only rows this family depends on the model's VALUE and not only
on the two values DIFFERING. The dependency is discharged inside the run: the
primary's own ``*_FUSE=`` echo is the DUT's measurement of what the model served,
and :meth:`check_constraint_evidence` requires it to equal the value the matching
words carry. A model that served anything else would otherwise turn the matching
leg silently into a second mismatching leg.

``selector_bits`` and both eight-word arrays are contiguous at manifest offsets
16..88 (``manifest.h``) and arrive in one transaction, so one served-field check
per slot covers the whole stimulus. No console line reports either of them.

The primary is re-hashed but NOT re-signed: the usage-constraint block runs after
``manifest_check_integrity`` and before ``manifest_crypto_validate``
(``manifest_load.c``), so the refused slot's signature is never examined --
``primary_expected_rsa_starts`` stays 0 and the base asserts it. The backup must
survive the whole crypto chain, so it is re-sealed with a genuine dev0 signature
and the base re-verifies it offline before the simulation.
"""

from __future__ import annotations

import struct

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_primary_usage_constraint_base

# What the testbench's flat axi_sim_mem serves for the SMC fuse-map device-ID
# window: nothing writes it and the model is instantiated with
# UninitializedData("zeros") (dv/tb/tb_top.sv). A model value, not a part value.
MODEL_FUSE_WORD = 0x0000_0000

# usage_constraints.selector_bits + chiplet_id[8] + package_id[8], contiguous at
# manifest offsets 16..88 (manifest.h).
_BLOCK_OFF = mm.OFF_SELECTOR_BITS
_BLOCK_FMT = "<Q8I8I"
_BLOCK_LEN = struct.calcsize(_BLOCK_FMT)

_SELECTOR_BASE = {
    "chiplet_id": mm.SELECTOR_BIT_CHIPLET_ID_BASE,
    "package_id": mm.SELECTOR_BIT_PACKAGE_ID_BASE,
}
_OTHER_KIND = {"chiplet_id": "package_id", "package_id": "chiplet_id"}


class sep_device_id_variation_base(sep_primary_usage_constraint_base):
    """Partial mask refused on a chosen word; full mask with matching words boots."""

    # --- subclass contract -------------------------------------------------
    # Which arm this member drives: "chiplet_id" or "package_id".
    kind: str = ""
    # 8-bit selector mask for the PRIMARY, within the member's own byte. Must
    # select at least the matching word and the rejecting word.
    primary_mask: int = 0
    # Selected PRIMARY words set to MODEL_FUSE_WORD, i.e. the ones that match.
    primary_match_words: tuple[int, ...] = ()
    # Word the PRIMARY must be refused on. Asserted against *_IDX=.
    reject_index: int = -1

    @classmethod
    def _derive_reject_index(cls) -> int:
        """Lowest selected word this member leaves mismatching.

        The arm returns on the first disagreement, so this is the only index the
        ROM can report for the declared mask. Deriving it rather than trusting
        ``reject_index`` is what stops a member from asserting an index its own
        stimulus cannot produce.
        """
        for i in range(mm.DEVICE_ID_NUM_WORDS):
            if cls.primary_mask & (1 << i) and i not in cls.primary_match_words:
                return i
        raise AssertionError(
            f"selector mask 0x{cls.primary_mask:02x} selects no word outside "
            f"primary_match_words {cls.primary_match_words}, so every checked word "
            f"matches and the primary would be ACCEPTED; a member of this refusal "
            f"family must be refused"
        )

    def _assert_contract(self) -> None:
        assert self.kind in _SELECTOR_BASE, (
            f"kind must be chiplet_id or package_id, got {self.kind!r}"
        )
        assert 1 <= self.primary_mask <= 0xFF, (
            f"primary_mask 0x{self.primary_mask:x} is not a non-zero 8-bit mask"
        )
        assert self.primary_match_words, (
            "primary_match_words is empty, so no SELECTED word matches and this "
            "member would prove nothing the existing mismatch-only testcases do not"
        )
        for w in self.primary_match_words:
            assert self.primary_mask & (1 << w), (
                f"word {w} is listed as matching but selector bit {w} is clear in "
                f"mask 0x{self.primary_mask:02x}: the ROM would never read it, so "
                f"the matching leg would be inert"
            )
        derived = self._derive_reject_index()
        assert derived == self.reject_index, (
            f"mask 0x{self.primary_mask:02x} with matching words "
            f"{self.primary_match_words} makes word {derived} the first "
            f"disagreement, but this member asserts {self.reject_index}"
        )
        # The unchecked-word leg needs a mismatching word BELOW the rejecting one
        # with its selector clear; without one, a ROM that ignored the selector
        # would report the same index and the leg would measure nothing.
        below_clear = [i for i in range(self.reject_index)
                       if not self.primary_mask & (1 << i)]
        assert below_clear, (
            f"every word below {self.reject_index} is selected in mask "
            f"0x{self.primary_mask:02x}, so a ROM that ignored selector_bits "
            f"entirely would report the same index and the unchecked-word leg "
            f"would be unfalsifiable"
        )
        self._below_clear = tuple(below_clear)

    # --- stimulus ----------------------------------------------------------
    def _plant_words(self, buf: bytearray, slot: str, mask: int,
                     match_words: tuple[int, ...]) -> None:
        """Set this arm's selector bits for ``mask`` and match the listed words."""
        base_bit = _SELECTOR_BASE[self.kind]
        for i in range(mm.DEVICE_ID_NUM_WORDS):
            if mask & (1 << i):
                mm.set_selector_bit(buf, slot, base_bit + i, True)
        for i in match_words:
            mm.set_device_id_word(buf, slot, self.kind, i, MODEL_FUSE_WORD)

    def _log_slot(self, buf: bytes, slot: str, mask: int,
                  match_words: tuple[int, ...]) -> None:
        sel = mm.selector_bits(buf, slot)
        mine = mm.device_id_words(buf, slot, self.kind)
        other = mm.device_id_words(buf, slot, _OTHER_KIND[self.kind])
        self.logger.info(
            "CHK-STIMULUS-%s: %s selector_bits=0x%016x -> %s byte 0x%02x, %s byte "
            "0x%02x. %s=%s (matching words %s hold the fuse-map value 0x%08x); "
            "%s=%s with its selector byte clear, so the other arm cannot fire",
            self.kind.upper().replace("_", "-"), slot, sel, self.kind, mask,
            _OTHER_KIND[self.kind], (sel >> _SELECTOR_BASE[_OTHER_KIND[self.kind]])
            & 0xFF, self.kind, [f"0x{w:08x}" for w in mine], list(match_words),
            MODEL_FUSE_WORD, _OTHER_KIND[self.kind],
            [f"0x{w:08x}" for w in other],
        )

    def plant(self, buf: bytearray, slot: str) -> None:
        """The PRIMARY's partial mask. Called by the usage-constraint base."""
        self._assert_contract()
        # Anchor the selector and both arrays against the shipped bytes BEFORE
        # writing: the whole stimulus is which words the ROM reads and what it
        # finds there, which it only is if these offsets address those fields.
        mm.verify_usage_constraints_layout(buf, "primary")
        mm.verify_device_id_layout(buf, "primary")
        self._plant_words(buf, "primary", self.primary_mask,
                          self.primary_match_words)
        self._log_slot(buf, "primary", self.primary_mask, self.primary_match_words)
        self.logger.info(
            "CHK-STIMULUS-DISCRIMINATION: word %d is selected and matches, words %s "
            "are NOT selected and mismatch, word %d is selected and mismatches. The "
            "arm returns on the first disagreement, so %s must be %d: %d would "
            "mean the value was ignored and %d would mean the selector was",
            self.primary_match_words[0], list(self._below_clear),
            self.reject_index, fd.device_id_tokens(self.kind)[0],
            self.reject_index, self.primary_match_words[0], self._below_clear[0],
        )

    def prepare_backup(self, buf: bytearray) -> None:
        """All eight words selected and matching, re-sealed so the slot can boot."""
        mm.verify_usage_constraints_layout(buf, "backup")
        mm.verify_device_id_layout(buf, "backup")
        full = (1 << mm.DEVICE_ID_NUM_WORDS) - 1
        self._plant_words(buf, "backup", full,
                          tuple(range(mm.DEVICE_ID_NUM_WORDS)))
        pm.reseal(buf, "backup")
        self._log_slot(buf, "backup", full, tuple(range(mm.DEVICE_ID_NUM_WORDS)))
        self.logger.info(
            "CHK-STIMULUS-BACKUP-FULL: backup selects all %d %s words and every one "
            "of them equals the fuse-map value, so the arm must be SATISFIED at full "
            "selector width and the slot must boot. Its %s selector byte stays clear "
            "over eight mismatching words, so a ROM applying one byte to both loops "
            "would refuse this slot instead",
            mm.DEVICE_ID_NUM_WORDS, self.kind, _OTHER_KIND[self.kind],
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # The backup is re-signed below, so establish on the UNTOUCHED slot that
        # the local signer reproduces the packer's shipped signature byte for byte.
        # Without it a re-seal fault would surface as the ROM refusing the slot,
        # which is indistinguishable from a plausible negative result.
        pm.verify_signing_key(buf, "backup")
        pm.verify_sealed(buf, "backup")
        return super().mutate_flash_image(buf)

    # --- checks ------------------------------------------------------------
    def _served_block(self, buf_sel: int, mine: list[int],
                      other: list[int]) -> bytes:
        if self.kind == "chiplet_id":
            return struct.pack(_BLOCK_FMT, buf_sel, *mine, *other)
        return struct.pack(_BLOCK_FMT, buf_sel, *other, *mine)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        # CHK-STIMULUS-SERVED: the device returned the exact selector and both
        # eight-word arrays for BOTH slots. No console line reports a selector bit
        # or a matching word, so this is the only channel on which the accepted
        # backup is more than Python intent.
        base_bit = _SELECTOR_BASE[self.kind]
        other_bit = _SELECTOR_BASE[_OTHER_KIND[self.kind]]
        shipped = mm.SHIPPED_DEVICE_ID_WORD
        full = (1 << mm.DEVICE_ID_NUM_WORDS) - 1

        p_sel = mm.SHIPPED_SELECTOR_BITS | (self.primary_mask << base_bit)
        p_mine = [MODEL_FUSE_WORD if i in self.primary_match_words else shipped
                  for i in range(mm.DEVICE_ID_NUM_WORDS)]
        fd.assert_served_field(
            self.logger, flash, "primary", _BLOCK_OFF,
            self._served_block(p_sel, p_mine, [shipped] * mm.DEVICE_ID_NUM_WORDS),
            f"primary selector_bits + chiplet_id[8] + package_id[8] "
            f"({self.kind} mask 0x{self.primary_mask:02x}, matching words "
            f"{list(self.primary_match_words)})",
        )

        b_sel = mm.SHIPPED_SELECTOR_BITS | (full << base_bit)
        fd.assert_served_field(
            self.logger, flash, "backup", _BLOCK_OFF,
            self._served_block(b_sel, [MODEL_FUSE_WORD] * mm.DEVICE_ID_NUM_WORDS,
                               [shipped] * mm.DEVICE_ID_NUM_WORDS),
            f"backup selector_bits + chiplet_id[8] + package_id[8] "
            f"({self.kind} mask 0xff, every word matching)",
        )
        assert not (b_sel >> other_bit) & 0xFF, (
            f"backup {_OTHER_KIND[self.kind]} selector byte is "
            f"0x{(b_sel >> other_bit) & 0xFF:02x}, expected 0: the cross-domain "
            f"control depends on the other arm being disabled while its eight words "
            f"mismatch"
        )
        self.logger.info(
            "CHK-SELECTOR-DOMAINS: primary served %s byte 0x%02x / %s byte 0x00, "
            "backup served %s byte 0x%02x / %s byte 0x00, with the other arm's eight "
            "words mismatching in both slots",
            self.kind, self.primary_mask, _OTHER_KIND[self.kind], self.kind, full,
            _OTHER_KIND[self.kind],
        )

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, self.kind,
                                     self.reject_index)
        # CHK-FUSE-VALUE: the two legs of this row are consistent. The ROM's own
        # *_FUSE= echo is the DUT's measurement of what the fuse-map model served,
        # and the matching words were set to that same number offline. A model
        # serving something else would make the matching leg a second mismatching
        # leg, and the backup would not have booted -- assert it here so the cause
        # is named rather than inferred from a terminal run.
        fuse_token = fd.device_id_tokens(self.kind)[1]
        fuse = fd.hex_value(console, fuse_token)
        assert fuse == MODEL_FUSE_WORD, (
            f"{fuse_token}{fuse if fuse is None else f'0x{fuse:08x}'} but this member "
            f"sets its MATCHING words to 0x{MODEL_FUSE_WORD:08x}. The fuse-map model "
            f"no longer serves that value, so the words this row calls matching are "
            f"mismatching and the selected-and-matching leg measures nothing"
        )
        self.logger.info(
            "CHK-PER-WORD-VARIATION: %s word %d refused the primary while word %d "
            "was selected and equal to the fuse value 0x%08x, words %s were "
            "unselected and unequal to it, and the backup selected all %d words at "
            "that value and booted",
            self.kind, self.reject_index, self.primary_match_words[0],
            MODEL_FUSE_WORD, list(self._below_clear), mm.DEVICE_ID_NUM_WORDS,
        )
