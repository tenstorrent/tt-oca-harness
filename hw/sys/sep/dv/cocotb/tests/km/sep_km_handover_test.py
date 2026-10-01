# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM mailbox handover: inhibit contract, then a SRAM load and warm-reset exec.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex.

The 14-word blob is the KM IP ``mutable_fw_blob_small`` image. After a
successful ``CMD_SRAM_LOAD_EXEC`` stream and a warm reset, ``CMD_SRAM_EXEC``
returns success. KMCSR ``TEST_SIGNATURE`` is not SEP-visible.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import (
    KM_CMD_EXEC_ROM,
    KM_CMD_SRAM_EXEC,
    KM_CMD_SRAM_LOAD_EXEC,
    KM_RC_FAILURE,
    KM_RC_INVALID_ARG,
    KM_RC_SUCCESS,
    KM_STATUS_INBOUND_EMPTY,
    SepKmMailbox,
    crc32c,
)

# mutable_fw_blob_small -- a minimal mutable firmware image loaded at 0x8000;
# 14 words so image+CRC fits the 16-word FIFO.
_MUTABLE_FW_BLOB_SMALL = (
    0x0140006F,
    0x00000013,
    0x00000013,
    0x00000013,
    0x0000006F,
    0x000142B7,
    0x1102E293,
    0x00100313,
    0x0062A023,
    0x00428293,
    0x600D6337,
    0x00D30313,
    0x0062A023,
    0x0000006F,
)
_FW_WORDS = len(_MUTABLE_FW_BLOB_SMALL)


def _blob_crc() -> int:
    return crc32c(b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in _MUTABLE_FW_BLOB_SMALL))


@pyuvm.test()
class sep_km_handover_test(sep_base_test):
    """Inhibit handover, then load an image and accept CMD_SRAM_EXEC after warm reset."""

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(lc_raw=0x1)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        self.km = SepKmMailbox(self)
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 PASS: rom_main booted, RESP_KM_READY over the mailbox")

        # --- CHK-EMPTY / CHK-ARG: refuse before any inhibit ------------------
        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_SRAM_EXEC, [])
        assert rc == KM_RC_INVALID_ARG, (
            f"CHK-EMPTY FAIL: empty CMD_SRAM_EXEC rc={rc}, expected {KM_RC_INVALID_ARG}"
        )
        self.logger.info("CHK-EMPTY PASS: CMD_SRAM_EXEC with no image returned RC_INVALID_ARG")

        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_SRAM_LOAD_EXEC, [0])
        assert rc == KM_RC_INVALID_ARG, (
            f"CHK-ARG FAIL: FW_WORDS=0 rc={rc}, expected {KM_RC_INVALID_ARG}"
        )
        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_SRAM_LOAD_EXEC, [0x0001_000E])
        assert rc == KM_RC_INVALID_ARG, (
            f"CHK-ARG FAIL: reserved[31:16] set rc={rc}, expected {KM_RC_INVALID_ARG}"
        )
        self.logger.info(
            "CHK-ARG PASS: FW_WORDS=0 and reserved[31:16] each returned RC_INVALID_ARG"
        )

        # --- CHK-INHIBIT: first EXEC_ROM commits this warm-reset epoch -------
        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_EXEC_ROM, [])
        assert rc == KM_RC_SUCCESS, f"CHK-INHIBIT FAIL: first CMD_EXEC_ROM rc={rc}"
        for cmd, payload, name in (
            (KM_CMD_SRAM_LOAD_EXEC, [_FW_WORDS], "CMD_SRAM_LOAD_EXEC"),
            (KM_CMD_SRAM_EXEC, [], "CMD_SRAM_EXEC"),
            (KM_CMD_EXEC_ROM, [], "CMD_EXEC_ROM"),
        ):
            rc, _ = await self.km.send_raw_expect_rc(cmd, payload)
            assert rc == KM_RC_FAILURE, (
                f"CHK-INHIBIT FAIL: {name} after EXEC_ROM rc={rc}, expected {KM_RC_FAILURE}"
            )
        self.logger.info(
            "CHK-INHIBIT PASS: first CMD_EXEC_ROM rc=0; later 0x11/0x12/0x10 returned RC_FAILURE"
        )

        await self._warm_reset_km()
        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_EXEC_ROM, [])
        assert rc == KM_RC_SUCCESS, f"CHK-INHIBIT-RST FAIL: CMD_EXEC_ROM after warm reset rc={rc}"
        self.logger.info("CHK-INHIBIT-RST PASS: warm reset cleared the inhibit; CMD_EXEC_ROM rc=0")

        # New epoch so the load is not inhibited by the EXEC_ROM above.
        await self._warm_reset_km()

        # --- CHK-LOAD: stream the 14-word blob and accept the RESP before it --
        seq = await self.km.send_command(KM_CMD_SRAM_LOAD_EXEC, [_FW_WORDS])
        rc, _ = await self.km.recv_resp_cmd(KM_CMD_SRAM_LOAD_EXEC, seq)
        assert rc == KM_RC_SUCCESS, f"CHK-LOAD FAIL: CMD_SRAM_LOAD_EXEC rc={rc} before stream"
        await self.km.post_raw_words(list(_MUTABLE_FW_BLOB_SMALL) + [_blob_crc()])
        for _ in range(20_000):
            if await self.km.read_status() & (1 << KM_STATUS_INBOUND_EMPTY):
                break
            await ClockCycles(cocotb.top.clk_i, 20)
        else:
            raise AssertionError("CHK-LOAD FAIL: inbound FIFO never emptied after the image stream")
        self.logger.info(
            "CHK-LOAD PASS: CMD_SRAM_LOAD_EXEC rc=0 then streamed %d words + CRC-32C",
            _FW_WORDS,
        )

        # --- CHK-EXEC: warm reset, then CMD_SRAM_EXEC -------------------------
        await self._warm_reset_km()
        seq = await self.km.send_command(KM_CMD_SRAM_EXEC, [])
        rc, _ = await self.km.recv_resp_cmd(KM_CMD_SRAM_EXEC, seq)
        assert rc == KM_RC_SUCCESS, f"CHK-EXEC FAIL: CMD_SRAM_EXEC rc={rc} after warm reset"
        self.logger.info("CHK-EXEC PASS: CMD_SRAM_EXEC rc=0 after warm reset")

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("entropy alerts clear and DRBG scoreboard reports PASS")

    async def _warm_reset_km(self) -> None:
        await self.swrst.park("km")
        await self.swrst.release("km")
        self.km.reset_host_seq()
        await self.km.wait_km_ready()
