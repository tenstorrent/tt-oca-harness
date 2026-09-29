# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC firmware on every hart reaches SEP SRAM, ext_out and the SMC-local words.

The SMC ROM image ``smu_smc_fabric`` (``hw/sys/smu/dv/fw/tests/smu_smc_fabric``)
runs on all four SMC harts. Hart 0 publishes READY, and every hart waits for
GO in scratch word 1 (``smu_smc_fabric_protocol.h``). The SMC CPU reaches
everything outside its caches through its MMIO port and the SMC input fabric,
so these are the SMC-CPU-issued transfers on the SMC's outbound path and on
the input fabric's response channels.

S0..S3 are ``smu_dtp_sep_dm_dmi_test``; the SEP debug module's system bus
carries the set-up.
S4: the system bus opens the SEP aperture at 0x0400_0000 (SEP SRAM at global
    0x1400_0000), sets SMC outbound filter entry 0 to pass all through the SEP
    view of the SMC window, and writes GO.
S5: each hart stores four doublewords tagged with its hart id into SEP SRAM
    over the crossbar's smc_out-to-sep_in route and into an address outside
    both apertures, which leaves on ext_out, before loading any back; it
    compares every read-back and re-reads GO. Each hart posts its result and
    hart 0 posts TEST_PASS once all four pass.
S6: the bench cross-checks the firmware: all four hart words pass, the
    responder holds each hart's ext_out words, a system-bus read of SEP SRAM
    returns each hart's SEP words, and ext_out carried the writes and reads of
    every hart. The SMC zeroer, started over the system bus, then writes zeros
    past the harts' words on the same path, and the responder holds them.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.smu_addr_map import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    c_header_u32,
)
from seq_lib.smu_axi_in_sep_aperture_test_seq import (
    WIN_BASE,
    WIN_SIZE,
    smu_axi_in_sep_aperture_test_seq,
)
from seq_lib.smu_axi_out_addr_len_size_test_seq import (
    ZEROER_BUSY,
    ZEROER_CTRL,
    ZEROER_DEST,
    ZEROER_SIZE,
    _OutboundTap,
)
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from seq_lib.smu_filter_helpers import PASS_ALL_END, PASS_RW_CONFIG

_PROTOCOL_H = (
    Path(__file__).resolve().parents[2]
    / "fw"
    / "tests"
    / "smu_smc_fabric"
    / "smu_smc_fabric_protocol.h"
)


def _p(name: str) -> int:
    return c_header_u32(_PROTOCOL_H, f"SMCFAB_{name}")


def _scratch(idx: int) -> int:
    return _p("SCRATCH_BASE") + idx * _p("SCRATCH_STRIDE")


NUM_HARTS = _p("NUM_HARTS")
WORDS = _p("WORDS")
STRIDE = _p("HART_STRIDE")
SEP_TARGET = _p("SEP_TARGET")
EXT_TARGET = _p("EXT_TARGET")
PATTERN = _p("PATTERN")
READY_POLL_CYCLES = 200_000
DONE_POLL_CYCLES = 400_000
# A zeroer run after the firmware, past every hart's words.
ZERO_TARGET = EXT_TARGET + 0x1000
ZERO_LENGTH = 0x40
ZERO_POLLS = 64


def hart_word(hart: int, word: int, ext: bool) -> int:
    return PATTERN | (hart << 16) | (0x100 if ext else 0) | word


class smu_smc_fabric_test_seq(smu_axi_in_sep_aperture_test_seq):
    """SMC ROM firmware on four harts against SEP SRAM, ext_out and SMC scratch."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps = {"S4": False, "S5": False, "S6": False}

    async def _scratch_settles(self, want: set[int], bound: int) -> int:
        value = 0
        for _ in range(bound // 64):
            value = int(self.dut.smc_scratch_0_o.value) & 0xFFFF_FFFF
            if value in want:
                break
            await ClockCycles(self.dut.clk_smu_i, 64)
        return value

    async def _sba_read64(self, jtag, addr: int) -> int:
        lo = await self._sba_read(jtag, addr)
        hi = await self._sba_read(jtag, addr + 4)
        return (hi << 32) | lo

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        ready = await self._scratch_settles({_p("READY")}, READY_POLL_CYCLES)
        await self._window(jtag, WIN_BASE, WIN_SIZE)
        for addr, value in (
            (OUTBOUND0_START, 0),
            (OUTBOUND0_END, PASS_ALL_END),
            (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            await self._sba_write64(jtag, self._smc_view(addr), value)
        self.steps["S4"] = True

        tap = _OutboundTap(self.dut)
        try:
            await self._sba_write(jtag, self._smc_view(_scratch(_p("GO_IDX"))), _p("GO"))
            status = await self._scratch_settles(
                {_p("TEST_PASS"), _p("TEST_FAIL")}, DONE_POLL_CYCLES
            )
            await ClockCycles(self.dut.clk_smu_i, 64)
            aw, ar = list(tap.aw), list(tap.ar)
            mem = self.test.cfg.axi_out_mem
            mem.write(ZERO_TARGET, bytes([0xA5]) * ZERO_LENGTH)
            mark = tap.mark()
            for addr, value in (
                (ZEROER_DEST, ZERO_TARGET),
                (ZEROER_SIZE, ZERO_LENGTH),
                (ZEROER_CTRL, 0),
            ):
                await self._sba_write64(jtag, self._smc_view(addr), value)
            zero_busy = ZEROER_BUSY
            for _ in range(ZERO_POLLS):
                zero_busy = await self._sba_read64(jtag, self._smc_view(ZEROER_CTRL)) & ZEROER_BUSY
                if not zero_busy:
                    break
            zero_aw, _ = tap.since(mark)
        finally:
            tap.stop()
        harts = [
            await self._sba_read(jtag, self._smc_view(_scratch(_p("HART_IDX") + h)))
            for h in range(NUM_HARTS)
        ]
        self._log(
            f"CHK-SMC-FW-FABRIC-PASS ready=0x{ready:08x} status=0x{status:08x} "
            f"harts={[hex(h) for h in harts]} "
            f"aw={[(hex(p[0]), p[4]) for p in aw]} ar={[(hex(p[0]), p[4]) for p in ar]}"
        )
        sb.expect_eq(
            "CHK-SMC-FW-FABRIC-PASS",
            (ready, status),
            (_p("READY"), _p("TEST_PASS")),
            evidence="CHK-SMC-FW-FABRIC-PASS",
        )
        self.steps["S5"] = True

        ext_bad = [
            (h, w)
            for h in range(NUM_HARTS)
            for w in range(WORDS)
            if mem.read_int(EXT_TARGET + h * STRIDE + 8 * w, 8) != hart_word(h, w, True)
        ]
        sep_local = SEP_TARGET - WIN_BASE
        sep_bad = []
        for h in range(NUM_HARTS):
            for w in range(WORDS):
                got = await self._sba_read64(jtag, sep_local + h * STRIDE + 8 * w)
                if got != hart_word(h, w, False):
                    sep_bad.append((h, w, hex(got)))
        ext_harts = {(p[0] - EXT_TARGET) // STRIDE for p in aw if EXT_TARGET <= p[0]}
        ext_read_harts = {(p[0] - EXT_TARGET) // STRIDE for p in ar if EXT_TARGET <= p[0]}
        ids = sorted({p[4] for p in aw + ar})
        observed = (
            (zero_busy, len(zero_aw) > 0, mem.read(ZERO_TARGET, ZERO_LENGTH).hex()),
            harts,
            ext_bad,
            sep_bad,
            sorted(ext_harts),
            sorted(ext_read_harts),
        )
        self._log(f"CHK-SMC-FW-FABRIC-CROSSCHECK {observed} ext_out ids={ids}")
        sb.expect_eq(
            "CHK-SMC-FW-FABRIC-CROSSCHECK",
            observed,
            (
                (0, True, bytes(ZERO_LENGTH).hex()),
                [_p("HART_PASS") | h for h in range(NUM_HARTS)],
                [],
                [],
                list(range(NUM_HARTS)),
                list(range(NUM_HARTS)),
            ),
            evidence="CHK-SMC-FW-FABRIC-CROSSCHECK",
        )
        self.steps["S6"] = True
        cocotb.log.info("SMC firmware fabric sweep complete")
