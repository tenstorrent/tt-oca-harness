# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both slots declare payload fields at the 32-bit limits; the ROM halts.

The primary's payload_length makes the 32-bit bounds sum wrap and is refused silently
by the wrap guard; the backup's payload_offset is refused by the offset-range guard.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

# The wrap arm's code, shared with the length-range and capacity arms.
ERR_PAYLOAD_TOO_LARGE = 0x0003_0007
# The offset-range arm's code, shared with every other length verdict in the function.
ERR_BAD_LENGTH = 0x0003_0004

_OFF_RANGE_TOKEN = "PAYLOAD_OFF_RANGE"
_LEN_RANGE_TOKEN = "PAYLOAD_LEN_RANGE"


@pyuvm.test()
class sep_manifest_payload_limits_test(sep_backup_manifest_structural_fail_base):
    """Primary wraps its payload bound, backup over-ranges its offset, ROM halts."""

    efuse_preload = EFUSE_PRELOAD
    primary_expected_error = ERR_PAYLOAD_TOO_LARGE
    expected_error = ERR_BAD_LENGTH
    backup_defect_marker = _OFF_RANGE_TOKEN

    # PAYLOAD_LEN_RANGE must stay absent: the primary sits on that arm's accept-side boundary.
    extra_forbidden = (
        _LEN_RANGE_TOKEN, "PAYLOAD_OFF_ALIGN", "PAYLOAD_HASHED_LEN_BAD=",
        "ENC_HASHED_LEN_PARTIAL", "PAYLOAD_OVERLAPS_MANIFEST",
        "TOC_REGION_OOB=", "TOC_PLEN_MISMATCH=", "PAYLOAD_NO_ROOM=",
        "PAYLOAD_LOC_OVERFLOW", "PAYLOAD_LOC_OT_OOB", "PAYLOAD_DST=",
        "USING_SEP_SRAM", "USING_SMC_SRAM", "EXT_SRAM_INIT_WAIT",
        "MANIFEST_HASH_MISMATCH", "MANIFEST_HASH_OK", "CRYPTO_FAIL=",
        fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        geom = pm.declare_wrapping_payload_length(buf, "primary")
        self._wrap = geom
        self._primary_served = geom["payload_length"].to_bytes(8, "little")
        stored = bytes(buf[mm.slot_base("primary") + pm.OFF_PAYLOAD_LENGTH:
                           mm.slot_base("primary") + pm.OFF_PAYLOAD_LENGTH + 8])
        assert stored == self._primary_served, (
            f"primary payload_length reads {stored.hex()} after the write, expected "
            f"{self._primary_served.hex()}; the mutation did not land"
        )
        self._primary_src = mm.slot_base("primary") + geom["payload_offset"]
        self.logger.info(
            "CHK-STIMULUS-WRAP: primary payload_length 0x%x -> 0x%x at "
            "payload_offset 0x%x. (0x%x + 0x%x) & 0xFFFFFFFF = 0x%x, which is BELOW "
            "the offset (so `total < p_off` fires) and below the 0x%x SRAM (so the "
            "capacity arm cannot fire). 0x%x is the largest value the length-range "
            "arm accepts, so %s must be ABSENT. Re-signed: the declared length is "
            "the slot's only defect",
            geom["payload_length_before"], geom["payload_length"],
            geom["payload_offset"], geom["payload_offset"], geom["payload_length"],
            geom["wrapped_sum"], geom["sram_size"], geom["len_range_limit"],
            _LEN_RANGE_TOKEN,
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        seed = self.random_seed()
        value = SepSeededRng(seed).choice(pm.OFF_RANGE_VALUES)
        was = pm.set_out_of_range_payload_offset(buf, "backup", value)
        self._off_value = value
        self._backup_served = value.to_bytes(8, "little")
        stored = int.from_bytes(
            bytes(buf[mm.slot_base("backup") + pm.OFF_BOOT_PAYLOAD_OFFSET:
                      mm.slot_base("backup") + pm.OFF_BOOT_PAYLOAD_OFFSET + 8]),
            "little", signed=True,
        )
        # A sign-extended write would hit the silent `p_off <= 0` arm with the same code.
        assert stored > pm.PAYLOAD_OFF_RANGE_LIMIT, (
            f"backup payload_offset reads {stored} as int64 for draw 0x{value:x}; "
            f"the offset-range arm needs a value above "
            f"+0x{pm.PAYLOAD_OFF_RANGE_LIMIT:x}, and a smaller or negative one is "
            f"claimed by a different arm that returns the same code silently"
        )
        self.logger.info(
            "CHK-STIMULUS-OFF-RANGE: seed %d drew payload_offset 0x%x from the "
            "procedure's %s; the backup's field goes %d -> %d as int64, above "
            "+0x%x, so validate_manifest_header must refuse it as %s before the "
            "cast to int32. NOT re-signed -- boot_arguments sits outside the TBS -- "
            "and the payload is not moved, because the refusal precedes the fetch",
            seed, value, [hex(v) for v in pm.OFF_RANGE_VALUES], was, stored,
            pm.PAYLOAD_OFF_RANGE_LIMIT, _OFF_RANGE_TOKEN,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # The wrap arm prints no token, so no announcing arm may appear in the primary's attempt.
        for token in (_OFF_RANGE_TOKEN, _LEN_RANGE_TOKEN):
            n_before_backup = sum(
                1 for i, line in enumerate(console)
                if i_psrc < i < i_bsrc and token in line
            )
            assert n_before_backup == 0, (
                f"{token} appeared inside the primary's attempt (lines "
                f"{i_psrc}..{i_bsrc}): the primary declared an in-range, aligned "
                f"payload_offset and a length the range arm accepts, so an "
                f"announcing arm must not be what refused it. Console: {console}"
            )

        # Exactly one occurrence rules out both slots producing the token.
        n_off = fd.count(console, _OFF_RANGE_TOKEN)
        assert n_off == 1, (
            f"{_OFF_RANGE_TOKEN} appeared {n_off} times, expected exactly 1 (the "
            f"backup's): only the backup declares an out-of-range offset, and a "
            f"second occurrence would mean the two slots carry one defect and "
            f"nothing attributes the terminal verdict. Console: {console}"
        )
        self.logger.info(
            "CHK-ARM-SPLIT: primary@%d refused silently with "
            "MANIFEST_ERR=0x%08x (the wrap arm), backup@%d refused with %s and "
            "MANIFEST_ERR=0x%08x (the offset-range arm) -- two different arms, two "
            "different codes, one terminal verdict",
            i_psrc, ERR_PAYLOAD_TOO_LARGE, i_bsrc, _OFF_RANGE_TOKEN,
            ERR_BAD_LENGTH,
        )

        fd.assert_no_read_starting_at(
            self.logger, self._flash, self._primary_src,
            f"the primary declared payload_length 0x{self._wrap['payload_length']:x}, "
            f"whose 32-bit sum with payload_offset wraps, so "
            f"validate_manifest_header must refuse the slot before the payload "
            f"fetch is issued",
        )

        fd.assert_served_field(self.logger, self._flash, "primary",
                               pm.OFF_PAYLOAD_LENGTH, self._primary_served,
                               "primary payload_length")
        fd.assert_served_field(self.logger, self._flash, "backup",
                               pm.OFF_BOOT_PAYLOAD_OFFSET, self._backup_served,
                               "backup boot_arguments.payload_offset")
