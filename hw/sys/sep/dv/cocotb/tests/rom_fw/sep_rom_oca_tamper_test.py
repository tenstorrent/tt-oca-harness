# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM refuses a tampered OCA manifest, in both slots (PyUVM).

The first manifest-negative test in this environment. Every other ROM test proves
the ROM accepts something it should; this one proves it rejects something it must,
which is the half that actually carries the security claim. A ROM that validated
nothing at all would pass all of the others.

The image is the signed one, with a single byte flipped inside the signed region
of **both** manifest copies. Both matters: the ROM keeps a primary at 0x1000 and a
backup at 0x41000 and rotates to the backup when the primary fails, so corrupting
only the primary would still boot -- correctly -- and prove nothing about refusal.
Corrupting both is what forces the ROM to run out of options and say so.

The flip lands at offset 64, inside CHIPLET_ID (bytes 40..71) -- a real identity
field rather than padding, so the mutation is the shape of an actual attack:
retargeting a signed manifest at a part it was not issued for. It sits well inside
the signed region [0, 3172), which is covered by BOTH the manifest hash and the RSA
signature.

The expected verdict is OCA_FAIL_MANIFEST_HASH (13). Integrity is checked before
interpretation, so the corrupted body is caught by the hash before either the
signature or the identity constraint gets a chance to object. Asserting that
specific code is deliberate: a test that only looked for "some failure" would pass
just as happily if the ROM rejected the image for a bad magic or a truncated
length, which would mean the tamper detection under test never ran at all.

No new image target: OcahSpiFlash.preload() accepts a bytes-like object, so the
mutation happens in memory here rather than in the Makefile. That keeps the
tampering visible next to the assertion it justifies.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_PRIMARY_MANIFEST_OFFSET = mm.PRIMARY_MANIFEST_OFFSET
_BACKUP_MANIFEST_OFFSET = mm.BACKUP_MANIFEST_OFFSET
# Byte to corrupt, relative to a manifest's start: inside CHIPLET_ID (OFF_CHIPLET_ID
# = 40, 32 bytes wide). Deliberately not in the unsigned tail past 3172, where a
# flip would change nothing the hash covers and the boot would succeed.
_TAMPER_OFFSET = 64

# The staged body no longer hashes to manifest_hash; reported per slot.
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

    # Inherits flash_image (the signed image) from the secure test, then mutates
    # it in run_scenario.
    #
    # The parent's marker tuples are discarded rather than extended: they assert a
    # SUCCESSFUL signed boot (MANIFEST_OK, PUBK_AUTHORIZED, RSA_VERIFY_OK,
    # PAYLOAD_OK), none of which may happen here. What survives is the transport
    # evidence -- this must still be a real SPI boot, or the refusal proves
    # nothing about the SPI path.
    # Measured: both slots are read and rejected and rom_err_fail() reports the
    # failure by ~1.65M cycles, so poll_boot does break out on fw_done and this
    # budget is a backstop rather than the normal exit. It is trimmed from the
    # inherited 24M anyway: if a future refusal path ever hangs instead of
    # reporting, the budget IS the runtime, and 24M is ~6 hours at the ~1.1k
    # cycles/s this testbench sustains -- past the testlist timeout, so the
    # failure would surface as an unhelpful timeout rather than a verdict.
    max_run_cycles = 3_000_000

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
        """Flip one bit in the signed region of both manifest slots."""
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
        """Inject the tamper through the base's own hook.

        The base reads ``flash_image`` as a PATH and routes the bytes through
        this method, which is the seam a negative testcase is meant to use.
        Rebinding ``self.flash_image`` to bytes instead -- as this test did --
        left the base's own ``open()`` holding a bytes object and failed the run
        at 0.00 ns with ``ValueError: embedded null byte``. The comment defending
        it described an older base that passed the attribute straight to
        ``preload()``.
        """
        original = bytes(buf)
        tampered = self._tamper(original)
        assert tampered != original, "tamper produced an identical image"
        return bytearray(tampered)

    async def run_scenario(self) -> None:
        # This boot must NOT reach BL1. Without this the scoreboard would fail the
        # test for the very outcome it exists to require.
        self.sb.expect_fw_pass = False
        await super().run_scenario()
        # The ROM reports the refusal through the mailbox (rom_err_fail) rather
        # than hanging, so fw_done asserts with fw_pass low. Assert that
        # explicitly: "no PASS" alone would also be satisfied by a ROM that
        # wedged before reaching a verdict, and a refusal nobody is told about is
        # a worse outcome than one that is.
        assert self.sb.fw_done, (
            "ROM never reported a verdict: the tampered image was refused (the "
            "console markers confirm it) but nothing signaled completion, so the "
            "failure would be invisible to anything watching the mailbox"
        )
        assert not self.sb.fw_pass, "scoreboard recorded PASS on a refused boot"
