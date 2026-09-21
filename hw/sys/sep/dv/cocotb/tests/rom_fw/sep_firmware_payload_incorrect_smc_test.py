# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A payload larger than the SMC-published window is refused; the backup boots.

The SMC half of the payload-size decision, and the ONLY route to
``MANIFEST_ERR_PAYLOAD_NO_ROOM`` (0x0003001A) in this repository. The primary
clears ``flag_args`` bit 29, so the ROM waits for SRAM_INIT, reads the staging
window SMC published in scratch[13]/[14], and measures the declared payload against
the WINDOW LENGTH instead of against SEP SRAM (``manifest_load.c``). A payload that
does not fit prints ``PAYLOAD_NO_ROOM=`` with the capacity it was measured against
and returns a SLOT error, so the backup is tried and boots.

THE STIMULUS HAS TO CLEAR TWO BOUNDS TO REACH THE ONE UNDER TEST, and getting that
wrong is how this arm stays uncovered. Three different rules bound a payload:

  * ``validate_manifest_header``: ``payload_offset + payload_length <= SEP SRAM``,
    252 KiB at the shipped offset, ``MANIFEST_ERR_PAYLOAD_TOO_LARGE``;
  * ``boot_flash_bounds_ok``: the flash read must stay inside one boot slot, the
    same 252 KiB measured from the slot base;
  * the staging block: ``payload_length <= payload_max``, which on the SMC arm is
    the window length -- the arm this row is about.

The first two run FIRST, so the declared length must be INSIDE them and OUTSIDE the
window. A window wider than 252 KiB puts this arm permanently out of reach, which
is why the accepted SMC size members publish 256 KiB and state in
``sep_payload_size_base`` that they cover nothing here. This row publishes the
128 KiB window ``sep_use_ext_sram_base`` already defines and draws a declared
length above it, so the first two bounds are satisfied and the third is not. Both
of the earlier bounds are asserted against the ROM's own numbers before the run,
and ``MANIFEST_ERR=0x00030007`` and ``PAYLOAD_LOC_OT_OOB`` are forbidden during it,
so a draw that violated either would fail rather than report this row's verdict.

THE CAPACITY IS ECHOED, AND THAT IS THE EVIDENCE. ``PAYLOAD_NO_ROOM=`` carries
``payload_max``, so requiring it to equal the published ``scratch[14]`` -- together
with ``SMC_WIN_OFF=``/``SMC_WIN_LEN=`` -- proves the ROM measured the payload
against the window SMC gave it rather than against a capacity it could have
assumed. A ROM that had used SEP SRAM's capacity on this branch would echo a
different number and accept every draw.

NOTHING IS PRODUCED BEHIND THE DECLARATION, and that is a property of where the
check sits. The refusal precedes the transfer, so the material is never read; the
row asserts that no SPI read BEGINS at the primary's payload source, which is what
separates "refused the declared size" from "fetched it, then complained". Writing
128 KiB of real material into the primary slot would also overwrite the backup
manifest this row needs to boot.

THE REFERENCE REGRESSION ROW DOES NOT REACH THIS ARM, AND THIS ROW DELIBERATELY
AVOIDS THE ONE IT DOES REACH. That is the load-bearing difference here, so it is
stated rather than left to be inferred. The reference declares
``SMC-available + 1..100 KiB`` from a figure unrelated to the 66000-byte window
its own testlist publishes -- but its slot never gets as far as the window. Its
primary is ENCRYPTED and its generator rewrites ``payload_length`` without
``payload_hashed_length``, so its manifest sanity check refuses the slot on
``encrypted_payload && payload_hashed_length != payload_length``
(``WARNING: INVALID_ENCRYPTED_PAYLOAD_LENGTH``), upstream of the SRAM_INIT wait and
of the window read. This row therefore loads the PLAINTEXT image, asserts that flag
on both slots, and forbids ``ENC_HASHED_LEN_PARTIAL`` and the ``BAD_LENGTH`` code,
so the reference's incidental arm cannot fire and pre-empt the one the row is named
for.

The rule this row DOES assert is the reference's all the same -- it is covered
there by a host test rather than by the regression row.
``payload_length_gt_smc_sram`` declares more than the SMC window with BOTH length
fields matched, exactly to get past that sanity arm, and its expectation is the
window refusal followed by a backup boot. That is this row, one design over. The
draw keeps the reference's ``+1..100 KiB`` shape, measured against the window this
row publishes rather than against an unrelated constant. The seed is the runner's
and the drawn value is logged.

THE ACCEPTING SIDE OF THE BOUND IS NOT COVERED HERE. ``p_len == win_len`` must be
accepted, and no row in this repository declares it: this one only over-shoots, and
the accepted SMC size members publish a 256 KiB window so their largest payload is
never equal to it either. An off-by-one at the staging check would pass every row
here. The reference covers that side separately, with ``payload_length_eq_smc_sram``
expecting a normal boot; the equivalent row has yet to be written.

UPSTREAM OF THE CRYPTO CHAIN. The staging block runs before
``manifest_crypto_validate``, so the primary must NOT reach the verifier at all:
``primary_expected_rsa_starts`` and ``primary_expected_sig_valids`` are both 0, and
its ``MANIFEST_HASH_OK`` is still required because
``manifest_check_integrity`` runs earlier -- which is what says the slot was
otherwise intact and refused for its size alone.

SCOPE LIMIT, inherited from every SMC-staging row here. ``u_smc_mem`` is a flat
``axi_sim_mem`` and the window comes from ``+sep_smc_scratch13/14``, so a pass says
the ROM honoured the window it was given. It says nothing about SMC firmware
publishing that window; see ``sep_use_ext_sram_base``.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp on OTBN.
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

# manifest.h
ERR_PAYLOAD_NO_ROOM = 0x0003_001A
ERR_PAYLOAD_TOO_LARGE = 0x0003_0007
ERR_PAYLOAD_BAD_LOC = 0x0003_0012

# The window this row publishes, and it MUST match the +sep_smc_scratch13/14 values
# on its testlist entry. These are sep_use_ext_sram_base's values -- 128 KiB at
# offset 0x20000, which clears the status ring buffer at the SMC SRAM base and is
# 8-byte aligned, so neither window check is what this row exercises. Deliberately
# NOT sep_payload_size_base's 256 KiB: that one is wider than the 252 KiB
# validate_manifest_header allows any payload, which is exactly what puts this arm
# out of reach for the accepted size members.
WINDOW_OFFSET = ues.SMC_WINDOW_OFFSET
WINDOW_SIZE = ues.SMC_WINDOW_SIZE

# The reference's range, measured from the capacity the ROM actually enforces here.
_EXCESS_KIB_MIN = 1
_EXCESS_KIB_MAX = 100

_NO_ROOM_TOKEN = f"PAYLOAD_NO_ROOM=0x{WINDOW_SIZE:08x}"

# Every payload token except this row's own.
_OTHER_TOKENS = tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != "PAYLOAD_NO_ROOM=")
assert len(_OTHER_TOKENS) == len(td.OTHER_PAYLOAD_TOKENS) - 1, (
    "'PAYLOAD_NO_ROOM=' is no longer in sep_toc_defect.OTHER_PAYLOAD_TOKENS, so "
    "this arm's token would be neither required by this row nor forbidden by its "
    "neighbours; the swap-test defence has silently lapsed"
)
# The window's OTHER refusals, both terminal rather than slot errors. None may fire:
# the window this row publishes is in bounds and aligned.
_OTHER_SMC_REFUSALS = tuple(t for t in ues.SMC_REFUSALS if t != "PAYLOAD_NO_ROOM=")
# The bounds gate that runs just ahead of staging, and the reinit path a second
# failover would take.
_LOCATION_TOKENS = ("PAYLOAD_LOC_OT_OOB", "PAYLOAD_LOC_SMC_OOB",
                    "PAYLOAD_LOC_OVERFLOW", "STAGED_WIPE=", "FLASH_REINIT_FAIL=")


@pyuvm.test()
class sep_firmware_payload_incorrect_smc_test(sep_primary_fail_backup_boot_base):
    """Primary declares more than the SMC window holds -> refused -> backup boots."""

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_PAYLOAD_NO_ROOM
    # The arm DOES print, but sep_primary_fail_backup_boot_base couples
    # primary_defect_marker to a required CRYPTO_FAIL= line and this rejection is
    # upstream of manifest_crypto_validate. The token is required through
    # extra_required and attributed by check_transport below instead.
    primary_defect_marker = ""
    # Refused inside the staging block, which runs before the crypto chain.
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0

    extra_required = (
        ues.WAIT_MARKER, ues.USING_SMC,
        f"SMC_WIN_OFF=0x{WINDOW_OFFSET:08x}",
        f"SMC_WIN_LEN=0x{WINDOW_SIZE:08x}",
        _NO_ROOM_TOKEN, "MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=",
    )
    extra_forbidden = tuple(
        npi.forbidden_errors()
        + [f"MANIFEST_ERR=0x{ERR_PAYLOAD_TOO_LARGE:08x}",
           f"MANIFEST_ERR=0x{ERR_PAYLOAD_BAD_LOC:08x}",
           td.DECRYPT_START, "CRYPTO_FAIL=", "MANIFEST_ALL_FAILED"]
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
        # Cross-checked against the C header the ROM compiles with, so a resized
        # SRAM moves this bound rather than silently legalising the draw.
        capacity = psb.ext_payload_capacity(payload_offset)
        seed = self.random_seed()
        excess_kib = SepSeededRng(seed).randrange(_EXCESS_KIB_MIN,
                                                  _EXCESS_KIB_MAX + 1)
        declared = WINDOW_SIZE + excess_kib * 1024

        assert declared > WINDOW_SIZE, (
            f"declared {declared} does not exceed the {WINDOW_SIZE}-byte window, so "
            f"the ROM would STAGE it and this row would prove the opposite of its "
            f"name"
        )
        assert declared <= capacity, (
            f"declared {declared} exceeds the {capacity}-byte SEP SRAM capacity at "
            f"payload_offset 0x{payload_offset:x}, so validate_manifest_header "
            f"would refuse the slot with MANIFEST_ERR_PAYLOAD_TOO_LARGE before the "
            f"window is ever read, and the arm under test would not run"
        )
        # The same number bounds the flash read to one boot slot
        # (boot_flash.h), and that gate runs just ahead of staging. Asserted from
        # the slot geometry rather than assumed to coincide with the SRAM bound.
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
            seed, excess_kib, WINDOW_SIZE, was, declared, declared,
            mm.FLAG_ARGS_BIT_USE_EXT_SRAM, capacity, slot_start, slot_end,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_NO_ROOM:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-SMC-ARM: the primary, and only the primary, took the SMC branch. It
        # waited for SRAM_INIT first, which only that branch does, and it did so
        # inside its own attempt.
        for marker in (ues.WAIT_MARKER, ues.USING_SMC):
            n = fd.count(console, marker)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's): "
                f"only the primary clears bit 29 in this row. Console: {console}"
            )
        i_wait = fd.assert_slot_attributed(console, ues.WAIT_MARKER, after=i_psrc,
                                           before=i_bsrc)
        i_smc = fd.assert_slot_attributed(console, ues.USING_SMC, after=i_wait,
                                          before=i_bsrc)

        # CHK-WINDOW-IS-THE-CAPACITY: the capacity the ROM echoed is the window it
        # read, which is the window the testlist published. This is the check that
        # says the refusal came from the SMC-supplied number rather than from a
        # capacity the ROM could have assumed -- and the forbidden
        # MANIFEST_ERR=0x00030007 says the SEP SRAM bound is not what fired.
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
        i_no_room = fd.assert_slot_attributed(console, _NO_ROOM_TOKEN, after=i_smc,
                                              before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_no_room,
                                          before=i_bsrc)

        # CHK-INTACT-BUT-FOR-SIZE: the primary passed its own manifest integrity
        # check, which runs before the staging block. Two occurrences, one per slot,
        # says the slot was otherwise sound and was refused for its declared size.
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

        # CHK-BACKUP-STAGED-IN-SEP: the backup kept bit 29 set, so exactly one
        # SEP-SRAM staging happened and it is the backup's. Requiring both branch
        # markers -- one per slot, in the right order -- is what says bit 29 selected
        # the destination in each case.
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
            i_psrc, i_hash, ues.WAIT_MARKER, i_wait, ues.USING_SMC, i_smc,
            _NO_ROOM_TOKEN, i_no_room, slot_err, i_err, i_bsrc, self._declared,
            echoed,
        )

        # CHK-NO-READ: the declared payload was never fetched. The refusal sits
        # between the window read and the transfer, so the absence of a read
        # beginning at the primary's payload source is a claim about the ROM's
        # decision rather than about the transport.
        fd.assert_no_read_starting_at(
            self.logger, flash, self._payload_src,
            f"the primary declared {self._declared} bytes for a "
            f"{WINDOW_SIZE}-byte window, so the staging block must refuse the slot "
            f"before the payload fetch is ever issued",
        )

        # CHK-STIMULUS-SERVED: the device really returned both halves of the
        # stimulus -- the over-declared length and the cleared destination bit -- at
        # their own field addresses, so the DUT was given what this row's name
        # describes rather than the shipped image.
        fd.assert_served_field(self.logger, flash, "primary", pm.OFF_PAYLOAD_LENGTH,
                               self._served_length,
                               "primary manifest payload_length")
        fd.assert_served_field(self.logger, flash, "primary", mm.OFF_FLAG_ARGS,
                               self._served_flags,
                               "primary boot_arguments.flag_args")
