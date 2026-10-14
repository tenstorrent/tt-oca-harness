# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus pad enables follow AVS_CONFIG.AVS_GPIO_ENABLE and the enabled pads carry a frame.

Sources: hw/ip/avsbus_controller/doc/interface.adoc, hw/sys/smc/doc/clk_rst.adoc.

AVS_GPIO_ENABLE resets to 1 and drives the output enable of avs_clock and avs_mdata
and the input enable of avs_sdata. The avs_clock pad (GPIO 49) enable is asserted
exactly; the avs_mdata (50) and avs_sdata (51) enables are measured and printed
because their pad numbers and polarity are an open finding (owner value pending).
"""

from __future__ import annotations

from collections import deque

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_avsbus_protocol_utils import (
    AVS_CFG_0,
    AVS_CMD,
    AVS_NORMAL_STATUS,
    AVS_READBACK,
    CMD_TYPE_READ,
    MAX_RETRIES_BM,
    READ_CMD_DATA,
    READBACK_HAS_DATA_BM,
    avs_field,
    build_avs_cmd,
    expected_master_subframe,
)
from .smc_csr_seq_utils import SmcCsrSeq

AVS_CONFIG = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CONFIG_BASE_ADDR")
GPIO_ENABLE_BM = avs_field("AVSBUS_CONTROLLER__AVS_CONFIG__AVS_GPIO_ENABLE_bm")
GPIO_ENABLE_RESET = avs_field("AVSBUS_CONTROLLER__AVS_CONFIG__AVS_GPIO_ENABLE_reset")
READBACK_FIELDS = (
    avs_field("AVSBUS_CONTROLLER__AVS_READBACK__SLAVE_ACK_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__STATUS_RESPONSE_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__CMD_DATA_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__CRC_bm")
)

# clk_rst.adoc: avs_clock is GPIO 49; the GPIO numbers 50 and 51 for avs_mdata and avs_sdata
# are not stated in the documents and are taken from the pad wiring.
PADS = (("avs_clock", 49), ("avs_mdata", 50), ("avs_sdata", 51))
CLOCK_PAD = 49

ENABLE_WAIT_CYCLES = 200
FRAME_WAIT_CYCLES = 20000
REPLY_POLL_CYCLES = 50
REPLY_POLL_LIMIT = 400

SUBFRAME_BITS = 32
ACK_BP = 30
FRAME_INVALID_BIT = 29
STATUS_BP = 24
DATA_BP = 8
GOOD_REPLY = (0 << ACK_BP) | (0 << FRAME_INVALID_BIT) | (0x10 << STATUS_BP) | (0x1234 << DATA_BP)
IDLE_REPLY = 0
CMD_WORD = build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x3, READ_CMD_DATA)


class AvsReplyDriver:
    """Answers each master subframe on mdata with the next queued reply on sdata.

    A master subframe opens with a low bit on an idle-high line. The reply to the
    subframe starting on clock n is shifted out on clocks n + 32 to n + 63, one bit
    after each rising edge.
    """

    def __init__(self, default: int) -> None:
        self.replies: deque[int] = deque()
        self.default = default
        self.masters: list[int] = []
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._task.cancel()
        cocotb.top.tb_avs_sdata_ext.value = 1

    async def _run(self) -> None:
        top = cocotb.top
        clk = top.tb_avs_clk_from_dut
        mdata = top.tb_avs_mdata_from_dut
        sdata = top.tb_avs_sdata_ext
        sdata.value = 1
        edge = 0
        prev = 1
        frame_end = 0
        frame_start = -1
        frame_word = 0
        schedule: list[tuple[int, int]] = []
        while True:
            await RisingEdge(clk)
            await Timer(1, unit="ns")
            raw = mdata.value
            level = int(raw) if raw.is_resolvable else 1
            if edge >= frame_end:
                if frame_start >= 0:
                    self.masters.append(frame_word)
                    frame_start = -1
                if level == 0 and (prev == 1 or edge == frame_end):
                    frame_start = edge
                    frame_end = edge + SUBFRAME_BITS
                    frame_word = 0
                    word = self.replies.popleft() if self.replies else self.default
                    schedule.append((edge + SUBFRAME_BITS, word))
            if frame_start >= 0:
                frame_word = (frame_word << 1) | level
            out = 1
            for start, word in schedule:
                if start <= edge < start + SUBFRAME_BITS:
                    out = (word >> (SUBFRAME_BITS - 1 - (edge - start))) & 1
            sdata.value = out
            schedule = [(s, w) for s, w in schedule if edge < s + SUBFRAME_BITS]
            prev = level
            edge += 1


class smc_avsbus_pad_enable_test_seq(SmcCsrSeq):
    """Sample the pad enables across AVS_GPIO_ENABLE 1, 0, 1 and run one frame."""

    def __init__(self, name: str = "smc_avsbus_pad_enable_test_seq") -> None:
        super().__init__(name)
        self.waits: list[tuple[str, int, str]] = []
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []
        self.last_pads = "not sampled"

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, step, int(get_sim_time("ps"))))

    @staticmethod
    def _bit(sig_name: str, pad: int) -> int:
        raw = getattr(cocotb.top, sig_name).value
        assert raw.is_resolvable, f"{sig_name} is X/Z: {raw}"
        return (int(raw) >> pad) & 1

    def _sample(self) -> dict[str, tuple[int, int]]:
        dut = cocotb.top
        for sig in ("tb_core2pad_en_o", "tb_pad2core_en_o"):
            assert hasattr(dut, sig), f"{sig} is not visible on the bench top"
        got = {
            name: (self._bit("tb_core2pad_en_o", pad), self._bit("tb_pad2core_en_o", pad))
            for name, pad in PADS
        }
        self.last_pads = " ".join(f"{n}(c2p,p2c)={v}" for n, v in got.items())
        return got

    async def _await_clock_enable(self, label: str, want: int) -> dict[str, tuple[int, int]]:
        got = self._sample()
        for _ in range(ENABLE_WAIT_CYCLES):
            got = self._sample()
            if got["avs_clock"][0] == want:
                self.waits.append(
                    (f"{label}_ENABLE_WAIT", ENABLE_WAIT_CYCLES, f"last={self.last_pads}")
                )
                return got
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: avs_clock pad output enable never reached {want} within "
            f"{ENABLE_WAIT_CYCLES} clk_smc cycles; last pad enables {self.last_pads}"
        )

    async def _write_enable(self, label: str, level: int) -> None:
        cfg = await self.csr_read(f"{label}_CFG_RMW", AVS_CONFIG)
        want = (cfg | GPIO_ENABLE_BM) if level else (cfg & ~GPIO_ENABLE_BM)
        await self.csr_write(f"{label}_CFG", AVS_CONFIG, want)
        await self.csr_read(f"{label}_CFG_RB", AVS_CONFIG, expected=want)

    async def _await_reply(self) -> None:
        for _ in range(REPLY_POLL_LIMIT):
            status = await self.csr_read("REPLY_NORMAL", AVS_NORMAL_STATUS)
            if status & READBACK_HAS_DATA_BM:
                self.waits.append(
                    ("REPLY_WAIT", REPLY_POLL_LIMIT * REPLY_POLL_CYCLES, "READBACK_HAS_DATA=1")
                )
                return
            await ClockCycles(cocotb.top.clk_smc_i, REPLY_POLL_CYCLES)
        raise AssertionError(
            f"reply: AVS_NORMAL_STATUS.READBACK_HAS_DATA never set; last pad enables "
            f"{self.last_pads}"
        )

    async def _await_frame(self, driver: AvsReplyDriver) -> None:
        for _ in range(FRAME_WAIT_CYCLES):
            if driver.masters:
                self.waits.append(
                    ("FRAME_WAIT", FRAME_WAIT_CYCLES, f"masters={len(driver.masters)}")
                )
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"frame: no master subframe captured on tb_avs_mdata_from_dut within "
            f"{FRAME_WAIT_CYCLES} clk_smc cycles; last pad enables {self.last_pads}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        for sig in ("tb_avs_clk_from_dut", "tb_avs_mdata_from_dut", "tb_avs_sdata_ext"):
            assert hasattr(dut, sig), f"{sig} is not visible on the bench top"

        # S1: SETUP
        self._sample()
        cfg0 = await self.csr_read("AVS_CONFIG_RESET", AVS_CONFIG)
        assert cfg0 & GPIO_ENABLE_BM == GPIO_ENABLE_RESET, (
            f"AVS_CONFIG=0x{cfg0:08x}: AVS_GPIO_ENABLE does not read its reset value "
            f"{GPIO_ENABLE_RESET}; last pad enables {self.last_pads}"
        )
        driver = AvsReplyDriver(default=IDLE_REPLY)
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S1")

        # S2: enable follows the field
        reset_pads = await self._await_clock_enable("RESET", 1)
        await self._write_enable("DISABLE", 0)
        off_pads = await self._await_clock_enable("DISABLE", 0)
        await self._write_enable("ENABLE", 1)
        on_pads = await self._await_clock_enable("ENABLE", 1)
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-AVS-PAD-ENABLE-FOLLOWS",
            f"AVS_GPIO_ENABLE reset {GPIO_ENABLE_RESET}, avs_clock pad (GPIO {CLOCK_PAD}) output "
            f"enable reset={reset_pads['avs_clock'][0]} after 0 write={off_pads['avs_clock'][0]} "
            f"after 1 write={on_pads['avs_clock'][0]}; measured (c2p,p2c) per pad (owner value "
            f"pending) "
            f"reset={reset_pads} write0={off_pads} write1={on_pads}",
        )

        # S3: protocol on the pads
        cfg_retry = await self.csr_read("AVS_CFG_0_SAVE", AVS_CFG_0)
        await self.csr_write("RETRIES_0", AVS_CFG_0, cfg_retry & ~MAX_RETRIES_BM)
        await self.csr_read("RETRIES_0_RB", AVS_CFG_0, expected=cfg_retry & ~MAX_RETRIES_BM)
        driver.replies.append(GOOD_REPLY)
        await self.csr_write("AVS_CMD", AVS_CMD, CMD_WORD)
        await self._await_frame(driver)
        await self._await_reply()
        got = await self.csr_read("AVS_READBACK", AVS_READBACK)
        assert got & READBACK_FIELDS == GOOD_REPLY & READBACK_FIELDS, (
            f"reply 0x{GOOD_REPLY:08x} reached AVS_READBACK as 0x{got:08x}; "
            f"last pad enables {self.last_pads}"
        )
        want_frame = expected_master_subframe(CMD_WORD)
        frames = [m & ~0x7 for m in driver.masters]
        assert want_frame in frames, (
            f"master subframes {[hex(f) for f in frames]} lack 0x{want_frame:08x}; "
            f"last pad enables {self.last_pads}"
        )
        await self.csr_write("RETRIES_RESTORE", AVS_CFG_0, cfg_retry)
        driver.stop()
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-AVS-PAD-PROTOCOL",
            f"with AVS_GPIO_ENABLE=1 the master subframe 0x{want_frame:08x} (CRC-3 excluded) "
            f"appeared on tb_avs_mdata_from_dut clocked by tb_avs_clk_from_dut and the reply "
            f"0x{GOOD_REPLY:08x} reached AVS_READBACK as 0x{got:08x} (compared on bits 31:30, "
            f"29, 28:24, 23:8, 2:0) with an OKAY response",
        )

        # S4: timeouts
        names = " ".join(f"{n}={b} last={s}" for n, b, s in self.waits)
        await ClockCycles(dut.clk_smc_i, 1)
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-TIMEOUT-PATHS",
            f"{len(self.waits)} bounded waits (each raises AssertionError with the last pad "
            f"enables on expiry, units clk_smc cycles): {names}",
        )

        steps = [s for s, _ in self.stamps]
        assert steps == ["S1", "S2", "S3", "S4"], f"fence steps {steps} out of order"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        stamp_of = dict(self.stamps)
        ids = [c for c, _, _ in self.chk_lines]
        assert ids == [
            "CHK-AVS-PAD-ENABLE-FOLLOWS",
            "CHK-AVS-PAD-PROTOCOL",
            "CHK-TIMEOUT-PATHS",
        ], f"checker lines {ids} out of order"
        assert all(t >= stamp_of[s] for _, s, t in self.chk_lines), "checker line before its step"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence PADS_SAMPLED < ENABLE_SEQUENCE < PROTOCOL_ON_PADS; "
            "checker lines %s; stamps %s",
            ",".join(ids),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )
