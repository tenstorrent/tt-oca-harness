# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A payload larger than the SMC-published window is refused; the backup boots.

The length fits SEP SRAM and the flash slot, so only the window check can refuse it.
Needs ``+sep_crypto_edn_force``: the backup runs RSA-3072 on OTBN.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_no_payload_images_base as npi
from rom_fw import sep_payload_size_base as psb
from rom_fw import sep_toc_defect as td
from rom_fw import sep_use_ext_sram_base as ues
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

ERR_PAYLOAD_NO_ROOM = 0x0003_001A
ERR_PAYLOAD_TOO_LARGE = 0x0003_0007
ERR_PAYLOAD_BAD_LOC = 0x0003_0012

# Must match the +sep_smc_scratch13/14 values on this test's testlist entry.
WINDOW_OFFSET = ues.SMC_WINDOW_OFFSET
WINDOW_SIZE = ues.SMC_WINDOW_SIZE

_EXCESS_KIB_MIN = 1
_EXCESS_KIB_MAX = 100

_NO_ROOM_TOKEN = f"PAYLOAD_NO_ROOM=0x{WINDOW_SIZE:08x}"

_OTHER_TOKENS = tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != "PAYLOAD_NO_ROOM=")
assert len(_OTHER_TOKENS) == len(td.OTHER_PAYLOAD_TOKENS) - 1, (
    "'PAYLOAD_NO_ROOM=' is missing from sep_toc_defect.OTHER_PAYLOAD_TOKENS; add it "
    "back so the other payload rows forbid this row's refusal token"
)
_OTHER_SMC_REFUSALS = tuple(t for t in ues.SMC_REFUSALS if t != "PAYLOAD_NO_ROOM=")
_LOCATION_TOKENS = (
    "PAYLOAD_LOC_OT_OOB",
    "PAYLOAD_LOC_SMC_OOB",
    "PAYLOAD_LOC_OVERFLOW",
    "STAGED_WIPE=",
    "FLASH_REINIT_FAIL=",
)


@pyuvm.test()
class sep_firmware_payload_incorrect_smc_test(sep_primary_fail_backup_boot_base):
    """Primary declares more than the SMC window holds -> refused -> backup boots."""

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_PAYLOAD_NO_ROOM
    # The base would also require CRYPTO_FAIL=, so the token is in extra_required.
    primary_defect_marker = ""
    # Refused inside the staging block, which runs before the crypto chain.
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0

    extra_required = (
        ues.WAIT_MARKER,
        ues.USING_SMC,
        f"SMC_WIN_OFF=0x{WINDOW_OFFSET:08x}",
        f"SMC_WIN_LEN=0x{WINDOW_SIZE:08x}",
        _NO_ROOM_TOKEN,
        "MANIFEST_HASH_OK",
        "PLD_HASH_OK",
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    extra_forbidden = tuple(
        npi.forbidden_errors()
        + [
            f"MANIFEST_ERR=0x{ERR_PAYLOAD_TOO_LARGE:08x}",
            f"MANIFEST_ERR=0x{ERR_PAYLOAD_BAD_LOC:08x}",
            td.DECRYPT_START,
            "CRYPTO_FAIL=",
            "MANIFEST_ALL_FAILED",
        ]
        + list(_OTHER_TOKENS)
        + list(_OTHER_SMC_REFUSALS)
        + list(_LOCATION_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; this row is the "
                f"PLAINTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one it is about"
            )
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        capacity = psb.ext_payload_capacity(payload_offset)
        seed = self.random_seed()
        excess_kib = SepSeededRng(seed).randrange(_EXCESS_KIB_MIN, _EXCESS_KIB_MAX + 1)
        declared = WINDOW_SIZE + excess_kib * 1024

        assert declared > WINDOW_SIZE, (
            f"declared {declared} does not exceed the {WINDOW_SIZE}-byte window, so "
            f"the ROM would stage it; raise _EXCESS_KIB_MIN above 0"
        )
        assert declared <= capacity, (
            f"declared {declared} exceeds the {capacity}-byte SEP SRAM capacity at "
            f"payload_offset 0x{payload_offset:x}, so validate_manifest_header "
            f"would refuse the slot with MANIFEST_ERR_PAYLOAD_TOO_LARGE before the "
            f"window is ever read, and the arm under test would not run"
        )
        # The flash-slot bound also runs before staging; the draw must stay in the slot.
        slot_start, slot_end = mm.slot_span(buf, "primary")
        payload_src = pm.payload_base(buf, "primary")
        assert payload_src + declared <= slot_end, (
            f"a {declared}-byte read from flash 0x{payload_src:x} would run past "
            f"the primary slot's end 0x{slot_end:x}, so boot_flash_bounds_ok would "
            f"refuse it as PAYLOAD_LOC_OT_OOB instead"
        )

        was = pm.declare_payload_length(buf, "primary", declared)
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_USE_EXT_SRAM, False)
        ues.assert_stimulus(self.logger, buf, "primary", want_set=False)
        mm.verify_public_key(buf, "primary")

        self._declared = declared
        self._payload_src = payload_src
        self._served_length = declared.to_bytes(8, "little")
        self._served_flags = mm.get_flag_args(buf, "primary").to_bytes(4, "little")
        self.logger.info(
            "CHK-STIMULUS-SMC-NO-ROOM: seed %d drew %d KiB past the %d-byte SMC "
            "window, so primary payload_length %d -> %d (0x%x) and flag_args bit %d "
            "is CLEARED. That is inside the %d-byte SEP SRAM capacity and inside the "
            "primary slot 0x%x..0x%x, so both earlier bounds pass and the window's "
            "own capacity is the only one left to refuse it. The slot is re-signed, "
            "and the material behind the declaration is NOT produced because the "
            "refusal precedes the fetch",
            seed,
            excess_kib,
            WINDOW_SIZE,
            was,
            declared,
            declared,
            mm.FLAG_ARGS_BIT_USE_EXT_SRAM,
            capacity,
            slot_start,
            slot_end,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_NO_ROOM:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        for marker in (ues.WAIT_MARKER, ues.USING_SMC):
            n = fd.count(console, marker)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's): "
                f"only the primary clears bit 29 in this row. Console: {console}"
            )
        i_wait = fd.assert_slot_attributed(console, ues.WAIT_MARKER, after=i_psrc, before=i_bsrc)
        i_smc = fd.assert_slot_attributed(console, ues.USING_SMC, after=i_wait, before=i_bsrc)

        echoed = fd.hex_value(console, "PAYLOAD_NO_ROOM=")
        win_len = fd.hex_value(console, "SMC_WIN_LEN=")
        win_off = fd.hex_value(console, "SMC_WIN_OFF=")
        assert (win_off, win_len) == (WINDOW_OFFSET, WINDOW_SIZE), (
            f"ROM read SMC_WIN_OFF=0x{win_off or 0:08x} SMC_WIN_LEN="
            f"0x{win_len or 0:08x}, but the testlist publishes "
            f"0x{WINDOW_OFFSET:08x}/0x{WINDOW_SIZE:08x}: the window under test did "
            f"not reach the DUT. Console: {console}"
        )
        assert echoed == win_len, (
            f"PAYLOAD_NO_ROOM=0x{echoed or 0:08x} but the window the ROM read is "
            f"0x{win_len:08x}: the payload was measured against some other "
            f"capacity, so this refusal is not the window's. Console: {console}"
        )
        assert self._declared > echoed, (
            f"this row declared {self._declared} bytes, which is not more than the "
            f"{echoed}-byte capacity the ROM enforced; the refusal cannot be the "
            f"one this row is named for"
        )
        i_no_room = fd.assert_slot_attributed(console, _NO_ROOM_TOKEN, after=i_smc, before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_no_room, before=i_bsrc)

        n_hash = fd.count(console, "MANIFEST_HASH_OK")
        assert n_hash == 2, (
            f"MANIFEST_HASH_OK appeared {n_hash} times, expected exactly 2 (one per "
            f"slot): manifest_check_integrity runs before the staging block, so the "
            f"primary must pass it. Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_psrc < i_hash < i_wait, (
            f"the primary's MANIFEST_HASH_OK@{i_hash} does not sit between its "
            f"read@{i_psrc} and its {ues.WAIT_MARKER}@{i_wait}. Console: {console}"
        )

        want_dst = f"PAYLOAD_DST=0x{ues.SEP_PAYLOAD_DST:08x}"
        for marker in (ues.USING_SEP, want_dst):
            n = fd.count(console, marker)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the backup's): "
                f"the primary never staged, and the backup stages in SEP SRAM. "
                f"Console: {console}"
            )
            i = fd.first_index(console, marker)
            assert i_bsrc < i, (
                f"{marker}@{i} precedes the backup read@{i_bsrc}, so the primary "
                f"staged a payload the ROM had already refused. Console: {console}"
            )
        self.logger.info(
            "CHK-SMC-NO-ROOM: primary@%d -> MANIFEST_HASH_OK@%d -> %s@%d -> %s@%d "
            "-> %s@%d -> %s@%d -> backup@%d, and the backup staged in SEP SRAM. The "
            "ROM measured %d declared bytes against the 0x%08x it read from the "
            "window and refused the slot",
            i_psrc,
            i_hash,
            ues.WAIT_MARKER,
            i_wait,
            ues.USING_SMC,
            i_smc,
            _NO_ROOM_TOKEN,
            i_no_room,
            slot_err,
            i_err,
            i_bsrc,
            self._declared,
            echoed,
        )

        fd.assert_no_read_starting_at(
            self.logger,
            flash,
            self._payload_src,
            f"the primary declared {self._declared} bytes for a "
            f"{WINDOW_SIZE}-byte window, so the staging block must refuse the slot "
            f"before the payload fetch is ever issued",
        )

        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            pm.OFF_PAYLOAD_LENGTH,
            self._served_length,
            "primary manifest payload_length",
        )
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            mm.OFF_FLAG_ARGS,
            self._served_flags,
            "primary boot_arguments.flag_args",
        )
