# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM refuses a signed OCA manifest with one tampered byte in both slots.

The test flips byte 64 of both manifest copies. The byte is inside CHIPLET_ID (bytes
40..71) and inside the signed region, which the manifest hash and the RSA signature both
cover. Both slots are tampered, so the backup cannot rescue the boot and the ROM prints
``MANIFEST_ALL_FAILED``. Integrity is checked before interpretation, so each slot must
fail with exactly ``OCA_FAIL_MANIFEST_HASH`` (13); a bad-magic or length refusal does not
satisfy the test. ``MANIFEST_OK`` and ``PAYLOAD_OK`` are forbidden, and the
cold_scratch[0] verdict must be FAIL.

The tamper is applied in memory through :meth:`mutate_flash_image`.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_PRIMARY_MANIFEST_OFFSET = mm.PRIMARY_MANIFEST_OFFSET
_BACKUP_MANIFEST_OFFSET = mm.BACKUP_MANIFEST_OFFSET
# Byte to corrupt, relative to a manifest's start: inside CHIPLET_ID
# (OFF_CHIPLET_ID = 40, 32 bytes wide) and the signed region [0, 3172). A flip
# in the unsigned tail changes nothing the hash covers.
_TAMPER_OFFSET = 64

# The staged body does not hash to manifest_hash; reported per slot.
_MANIFEST_ERR = f"MANIFEST_ERR=0x{mm.boot_err('OCA_FAIL_MANIFEST_HASH'):08x}"
# Printed once both slots have been tried and rejected.
_ALL_FAILED = "MANIFEST_ALL_FAILED"

# Must never appear: each would mean the ROM got further than a tampered manifest
# should allow. PAYLOAD_OK would mean it validated a payload described by a
# manifest it could not trust.
_MANIFEST_OK = "MANIFEST_OK"
_PAYLOAD_OK = "PAYLOAD_OK"


@pyuvm.test()
class sep_rom_oca_tamper_test(sep_rom_ot_secure_boot_test):
    """Flip a byte in both manifest copies and require the ROM to refuse the boot."""

    # Inherits flash_image (the signed image) from the secure test;
    # mutate_flash_image() tampers it before load.
    #
    # The positive parent's marker tuples require MANIFEST_OK, PUBK_AUTHORIZED,
    # RSA_VERIFY_OK and PAYLOAD_OK, none of which may happen here. This test keeps
    # only the transport evidence needed to prove a real SPI boot attempt.
    # The limit must exceed the time both slots take to be refused. It reports a
    # refusal-path hang before the inherited cycle limit.
    max_run_cycles = 3_500_000
    verdict_source = "scratch0"
    verify_otbn_edn = False

    required_markers = (
        "BOOT_SPI",
        "MANIFEST_SRC=0x00001000",
        _MANIFEST_ERR,
        _ALL_FAILED,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _MANIFEST_OK,
        _PAYLOAD_OK,
    )

    @staticmethod
    def _tamper(image: bytes) -> bytes:
        """Flip one byte in the signed region of both manifest slots."""
        buf = bytearray(image)
        for base in (_PRIMARY_MANIFEST_OFFSET, _BACKUP_MANIFEST_OFFSET):
            idx = base + _TAMPER_OFFSET
            if idx >= len(buf):
                raise AssertionError(
                    f"tamper offset 0x{idx:x} past end of image ({len(buf)} bytes); "
                    f"the packed layout is not what this test assumes"
                )
            buf[idx] ^= 0xFF
        return bytes(buf)

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        """Tamper through the base's mutate hook; ``flash_image`` stays a path."""
        original = bytes(buf)
        tampered = self._tamper(original)
        assert tampered != original, "tamper produced an identical image"
        return bytearray(tampered)

    async def run_scenario(self) -> None:
        # The refused boot must not reach BL1, so the scoreboard expects fw_pass low.
        self.sb.expect_fw_pass = False
        await super().run_scenario()
        # rom_err_fail records the terminal verdict in cold_scratch[0], so
        # poll_boot reports fw_done with fw_pass low.
        assert self.sb.fw_done, (
            "ROM never reported a verdict: the tampered image was refused (the "
            "console markers confirm it) but cold_scratch[0] never signaled completion"
        )
        assert not self.sb.fw_pass, "scoreboard recorded PASS on a refused boot"
