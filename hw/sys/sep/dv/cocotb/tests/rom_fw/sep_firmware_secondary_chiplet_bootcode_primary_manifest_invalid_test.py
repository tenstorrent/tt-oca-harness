# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary chiplet, published manifest invalid: one attempt, then terminal.

THE STIMULUS, AND WHY IT IS THE REFERENCE'S OWN. The reference scenario publishes
the primary manifest at 0x5000 instead of 0x6000 "to ensure the primary manifest
is invalid" -- it does not corrupt a manifest, it points the SMC's published
offset at an address that holds no manifest. This row does the same with this
design's numbers: ``+sep_smc_scratch8=00005000`` republishes SMC scratch[8], so
the ROM loads from ``0x4006_5000``, and the packed SMC image carries eight zero
bytes there. ``validate_manifest_header`` compares the first word against
``MANIFEST_ID_TBL1`` and returns ``MANIFEST_ERR_BAD_MAGIC`` (0x00030002), which
is the reference's ``INVALID_MANIFEST_ID``.

0x5000 is not an arbitrary hole. The base asserts it is INSIDE the span
``+sep_smc_mem_hex`` covers, so the zero bytes the ROM compared are bytes THIS
image really supplies rather than an absent-key default -- a provenance
requirement, not X-avoidance, since ``u_smc_mem`` reads absent bytes as zero on
every simulator. It also asserts that 0x1000 still holds a valid ``TBL1`` -- so
this run failed because of WHERE the SMC pointed, not because the image had no
manifest to offer.

WHY THIS IS TERMINAL AND NOT A FAILOVER, which is the whole point of the row.
``rom_manifest_boot`` fills ``offsets[0]`` from scratch[8], sets
``offsets[1] = offsets[0]`` and ``num_retries = 0``, and guards the
rotate_update swap with ``from_spi`` (``manifest_load.c``). The SMC path
therefore has ONE slot. That is the reference's "there is no backup manifest in
the SMC SRAM", and it is why the same ``BAD_MAGIC`` that merely triggers a
failover on every SPI-path row ends the run here. The base requires exactly one
``MANIFEST_PRIMARY`` and one published ``MANIFEST_SRC=`` and forbids
``MANIFEST_BACKUP``; this member adds that ``MANIFEST_ERR=`` occurs exactly once
and that the code is BAD_MAGIC, so a second rejection of any kind would fail the
row.

THE ATTRIBUTION. ``BAD_MAGIC`` is returned before any hash, usage constraint or
crypto work, so this member forbids every downstream token: the hash markers, the
whole crypto chain, ``SBOOT_OFF``, the usage-constraint tokens, and every other
structural error code the header validator could have returned instead
(``BAD_VERSION``, ``BAD_LENGTH``). A run refused one check later would wear a
different code and is rejected here rather than accepted as a generic manifest
failure.

THE INDEPENDENT HALF. The console says which check complained; the encoded
``cold_scratch[1]`` word says what ``rom_err_fail()`` was handed
(``rom_main.c``), and the quiescence window says the ROM then stopped rather than
reporting and carrying on.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_secondary_chiplet_base import (
    ALL_FAILED,
    ERR_BAD_MAGIC,
    MANIFEST_OK,
    sep_secondary_chiplet_base,
)

# The offset the testlist republishes. Inside the span the packed SMC image
# covers, and eight zero bytes there.
_INVALID_OFFSET = 0x5000

# manifest_load.c: printed once per rejected slot, and rom_main.c's own echo.
_SLOT_ERR = f"MANIFEST_ERR=0x{ERR_BAD_MAGIC:08x}"
_BOOT_FAIL = f"MANIFEST_BOOT_FAIL=0x{ERR_BAD_MAGIC:08x}"

# manifest.h: the two other verdicts validate_manifest_header could have
# returned. Forbidding them is the swap test -- a row whose published offset
# happened to hold a stale or short manifest would be refused here instead of
# passing as a generic header failure.
_OTHER_HEADER_ERRORS = (0x0003_0003, 0x0003_0004)
# Everything downstream of the identifier check: integrity, the usage-constraint
# block, the crypto chain, and the payload. None of it may run.
_DOWNSTREAM_TOKENS = (
    "MANIFEST_HASH_OK", "MANIFEST_HASH_MISMATCH", "LC_USAGE_CONSTRAINT_FAIL",
    "CHIPLET_ID_MISMATCH", "PACKAGE_ID_MISMATCH", "RSA_VERIFY_START",
    "SIG_VALID", "CRYPTO_VALIDATE_OK", "CRYPTO_FAIL=", "SBOOT_OFF",
    "PLD_HASH_OK", "DECRYPT_START", MANIFEST_OK,
)
# rom_main.c: the boot progress that must not have happened, and the fuse lock,
# which sits after rom_manifest_boot and is therefore unreachable on this path.
_BOOT_PROGRESS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=", "FUSE_SECRETS_LOCKED")


@pyuvm.test()
class sep_firmware_secondary_chiplet_bootcode_primary_manifest_invalid_test(
        sep_secondary_chiplet_base):
    """Secondary arm + published offset 0x5000 -> BAD_MAGIC, one attempt, halt."""

    manifest_offset = _INVALID_OFFSET
    expect_boot = False
    expected_error = ERR_BAD_MAGIC
    extra_required = (_SLOT_ERR, ALL_FAILED, _BOOT_FAIL)
    extra_forbidden = (
        tuple(f"MANIFEST_ERR=0x{c:08x}" for c in _OTHER_HEADER_ERRORS)
        + _DOWNSTREAM_TOKENS + _BOOT_PROGRESS
    )

    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        status_hex = [hex(v) for v in status_seq]
        src = self.src_echo
        i_src = self._index_of(console, src)
        i_err = self._index_of(console, _SLOT_ERR)
        i_all = self._index_of(console, ALL_FAILED)
        i_fail = self._index_of(console, _BOOT_FAIL)

        # CHK-ONE-REJECTION: exactly one slot error in the whole run. The base
        # already forbids MANIFEST_BACKUP and pins the attempt count; this is the
        # complementary statement about rejections, and together they are what
        # distinguish the SMC path's single attempt from a failover that happened
        # to end the same way.
        n_err = self._count(console, "MANIFEST_ERR=")
        assert n_err == 1, (
            f"MANIFEST_ERR= appeared {n_err} times, expected exactly 1: the SMC "
            f"path has one slot, so one rejection ends the run. Console: {console}"
        )

        # CHK-INVALID-ID-ORDER: the rejection sits inside the one attempt, and the
        # loop then gives up and reports the same code out of rom_manifest_boot.
        assert i_src < i_err < i_all < i_fail, (
            f"rejection sequence is out of order: {src}@{i_src} -> "
            f"{_SLOT_ERR}@{i_err} -> {ALL_FAILED}@{i_all} -> {_BOOT_FAIL}@{i_fail}. "
            f"Console: {console}"
        )

        # CHK-TERMINAL: the encoded status word is the half the console does not
        # provide -- rom_err_fail() writes STATUS_ENCODE(ERROR, code) to
        # cold_scratch[1] (rom_main.c) and the FAIL verdict to cold_scratch[0].
        assert _SLOT_ERR == f"MANIFEST_ERR=0x{self.expected_error:08x}", (
            f"the required slot-error marker {_SLOT_ERR} and the declared "
            f"expected_error 0x{self.expected_error:08x} disagree"
        )
        expected_status = 0x0F01_0000 | (self.expected_error & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{self.expected_error & 0xFFFF:04x})); observed "
            f"{status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion; a published offset holding no "
            f"manifest must converge on a FAIL verdict. cold_scratch[1]: "
            f"{status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted from an offset that holds no manifest"
        )
        self.logger.info(
            "CHK-INVALID-PUBLISHED-MANIFEST: one attempt at %s, refused "
            "%s@%d, %s@%d, %s@%d, cold_scratch[1]=0x%08x, verdict FAIL",
            src, _SLOT_ERR, i_err, ALL_FAILED, i_all, _BOOT_FAIL, i_fail,
            expected_status,
        )
