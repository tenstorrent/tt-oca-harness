# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with ``skip_SHA256`` requested -> not demoted, both registers locked.

Outcome **O1** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD_END stimulus it shares with its
siblings is in ``rom_fw/sep_demotion_prod_end_base.py``.

**COVERED-BY-O1, AND WEAKER THAN ITS THREE SIBLINGS. Stated first because burying
it would be the whole problem.** ``rom_main.c`` short-circuits on
``lc_state == LC_STATE_PROD_END`` and reads none of the three manifest demotion
inputs, so this row lands on the same observable as every other PROD_END row. It
drives the same three inputs as ``no_flag_prod_end`` -- all clear -- and its ONLY
difference from that member is ``boot_arguments.flag_args`` bit 31.

**AND THAT BIT IS READ BY NOTHING IN THIS ROM.**
``FLAG_ARGS_BIT_SKIP_SHA256`` is defined at ``bootrom/prod/include/manifest.h``
and has no read site anywhere under ``bootrom/prod/src``; the only two ``flag_args``
bits with a reader are bit 30 (``manifest_load.c``, ``secure_boot_enabled``) and
bit 0 (``rom_main.c``, the BL2 demotion request). So the distinguishing half of this
row's stimulus cannot change any ROM behaviour, and this run's console is
byte-identical to ``no_flag_prod_end``'s by construction.

**AND FOR THIS LIFECYCLE THAT COSTS NOTHING, WHICH IS A STRONGER STATEMENT THAN
"DISCLOSED LIMIT".** The skip is gated on the lifecycle before the bit is ever
read: ``check_sha256_enabled()`` returns
true immediately when secure boot is on, then returns true again for every lifecycle
except ``LC_STATE_TEST_DEV``, and only in TEST_DEV does it test
``FLAG_ARGS_BIT_SKIP_SHA256``. This member runs at PROD_END with secure boot
enforced, so the bit is ignored by design here. **The inertness is correct for this
scenario, not a gap**. The ROM-wide gap is real and bites the TEST_DEV
hash-skip members, which are different testcases.

The remaining limit is therefore about DISCRIMINATION rather than about lost coverage:

  * the demotion DECISION under test is real, fully implemented and asserted here on
    both channels -- the console tokens and the DEMOTE_1/DEMOTE_2 register probes;
  * what the row cannot separate is "the demotion block correctly ignores
    ``skip_SHA256``" from "this ROM ignores ``skip_SHA256`` everywhere". The
    reference's own expectation for ``+UNAUTH_FLAG_30`` is identical to its no-flag
    expectation, so the demotion verdict asserted here IS what the
    reference asserts. The part that is lost is the hash-skip behaviour, which is a
    different feature and is covered by different testcases;
  * the row is still separable from ``no_flag_prod_end`` at RUN time, on one channel
    only: :meth:`~sep_demotion_decision_base._check_stimulus_served` requires the
    flash DEVICE to have returned the planted ``flag_args`` word, and
    :meth:`check_manifest_stimulus` below pins it to exactly 0xC0000000. Neither is
    a ROM observable.

WHAT IT STILL ASSERTS PER RUN: that a part at PROD_END is locked down --
``DEMOTE: PROD_END lock`` and ``DEMOTE_LOCKED`` exactly once each and after
``MANIFEST_OK``, with every other [C15] string forbidden -- and DEMOTE_1 =
(demote 0, lock 1) together with DEMOTE_2 = (demote 0, lock 1) read back from the
lifecycle controller. DEMOTE_2 locked is producible by no other row of the table:
``lc_write_demotion_2`` is called on the PROD_END arm only.

MARKER SUBSTITUTION. This ROM defines no demotion status code, so the
so the console tokens plus the register probes carry the whole verdict, and the
lock requirements are an addition derived from this ROM's own behaviour. SCOPE:
only the DECISION is checked; its UID/KBKDF consumers have no BL0-side equivalent
here. Both disclosed in the entry's ``flow_deviation``.

Needs ``+sep_crypto_edn_force``: PROD_END enforces secure boot (``lifecycle.c``).
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base

# The shipped image carries flag_args = 0x40000000 (bit 30, secure_boot) and this
# member adds bit 31. Pinned as a whole word rather than as a bit test so that a
# stray write to any other bit is caught too -- the ROM echoes none of this field.
_EXPECTED_FLAG_ARGS = (1 << mm.FLAG_ARGS_BIT_SECURE_BOOT) | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256)

# measurement.h echoes the low three bits of rom_main.c's demotion_bits. On the
# PROD_END arm the word is lock-only.
_MEAS_LOCK_ONLY = "MEAS_DEMOTE=0x00000002"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_30_prod_end_test(
        sep_demotion_prod_end_base):
    """PROD_END with skip_SHA256 set: not demoted, both registers locked."""

    # PLD_HASH_OK is required and PLD_HASH_FAIL= forbidden for parity with the PROD
    # members, whose base requires the first. It matters more here than on the other
    # PROD_END rows: skip_SHA256 is precisely the bit that, on a ROM that implemented
    # it, would suppress a payload hash -- so requiring the hash to have SUCCEEDED is
    # the closest this platform can come to observing the bit's absence of effect.
    required_markers = sep_demotion_prod_end_base.required_markers + (
        _MEAS_LOCK_ONLY, "PLD_HASH_OK", "MANIFEST_HASH_OK",
    )
    forbidden_markers = sep_demotion_prod_end_base.forbidden_markers + (
        "PLD_HASH_FAIL=", "MANIFEST_HASH_MISMATCH",
    )

    # The stimulus is
    # +UNAUTH_FLAG_30 sets boot_arguments.skip_SHA256 = 1 and leaves BL2_demotion,
    # the BL1 flag and the selector clear, so all three demotion inputs are 0.
    _SEL = 0
    _AUTH = 0
    _BL2 = 0

    def mutate_manifest(self, buf: bytearray) -> None:
        """Plant the base's PROD_END stimulus, then the row's ``skip_SHA256`` bit.

        ``flag_args`` sits outside the TBS (``manifest.h``), so this write needs no
        re-hash and no re-sign and can follow the base's re-sealing lifecycle
        narrowing without invalidating it.
        """
        super().mutate_manifest(buf)
        before = mm.get_flag_args(buf, "primary")
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_SKIP_SHA256, True)
        after = mm.get_flag_args(buf, "primary")
        assert after == before | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256), (
            f"primary flag_args is 0x{after:08x} after the write, expected "
            f"0x{before | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256):08x}; the mutation did "
            f"not land"
        )
        self.logger.info(
            "CHK-STIMULUS-SKIP-SHA256: primary flag_args 0x%08x -> 0x%08x (bit %d "
            "set). No ROM code reads this bit, so the only "
            "channels that can see it are the packed image and the bytes the flash "
            "device serves", before, after, mm.FLAG_ARGS_BIT_SKIP_SHA256,
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        """The base's triple, plus the whole ``flag_args`` word this row is named for."""
        super().check_manifest_stimulus(buf)
        fa = mm.get_flag_args(buf, "primary")
        assert fa == _EXPECTED_FLAG_ARGS, (
            f"primary flag_args is 0x{fa:08x}, expected 0x{_EXPECTED_FLAG_ARGS:08x} "
            f"(secure_boot bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} plus skip_SHA256 bit "
            f"{mm.FLAG_ARGS_BIT_SKIP_SHA256}). This word is the ONLY thing that "
            f"distinguishes this run from sep_firmware_demotion_decision_no_flag_"
            f"prod_end_test, because no ROM code reads bit "
            f"{mm.FLAG_ARGS_BIT_SKIP_SHA256}"
        )
