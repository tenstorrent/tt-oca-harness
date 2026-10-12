# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stalled R, W and B handshakes on UART SCR[0] and SCRATCH[0] at the default clock triple.

Contract SMC_CLOCK_RATIO_012, anchor smc_clk_ratio_handshake_stall_test.
Allocated scenarios: RATIO-HANDSHAKE-STALL.S1, RATIO-HANDSHAKE-STALL.S2, RATIO-HANDSHAKE-STALL.S3.
Spec sources: hw/sys/smc/doc/fabric.adoc, hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_SYMBOL = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR"
UART_SCR_SYMBOL = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR"
STALL_CYCLES = 64
READY_HOLD_CYCLES = 256
AXI_TIMEOUT_NS = 50_000
FUSE_SENSE_MAX_CYCLES = 200_000
CATCH_UP_CYCLES = 256
QUIET_CYCLES = 16
OKAY = 0
UART_PRELOAD = 0x5A
UART_WRITE = 0xA5
SCRATCH_PRELOAD = 0xC3C3C3C3
SCRATCH_WRITE = 0x3C3C3C3C
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
FENCE_TERMS = {
    "S1": "PRELOAD_DONE",
    "S2": "PERIPH_READ_STALLED",
    "S3": "PERIPH_WRITE_STALLED",
    "S4": "SMC_STALLS_DONE",
    "S5": "TIMEOUT_BOUNDS_LISTED",
}
CHK_ORDER = (
    "CHK-STALL-PERIPH-READ",
    "CHK-STALL-PERIPH-WRITE",
    "CHK-STALL-SMC",
    "CHK-TIMEOUT-PATHS",
)
CHK_STEP = {
    "CHK-STALL-PERIPH-READ": "S2",
    "CHK-STALL-PERIPH-WRITE": "S3",
    "CHK-STALL-SMC": "S4",
    "CHK-TIMEOUT-PATHS": "S5",
}
PORT_SIGNALS = (
    "clk_smc",
    "s_axi_arvalid",
    "s_axi_arready",
    "s_axi_awvalid",
    "s_axi_awready",
    "s_axi_wvalid",
    "s_axi_wready",
    "s_axi_rvalid",
    "s_axi_rready",
    "s_axi_rresp",
    "s_axi_bvalid",
    "s_axi_bready",
    "s_axi_bresp",
)


def _bit(dut, name: str) -> int:
    value = getattr(dut, name).value
    assert value.is_resolvable, f"{name} is not resolvable: {value}"
    return int(value)


class _Window:
    """Handshake observations of one access: counts and the cycle of each event."""

    def __init__(self) -> None:
        self.cycle = 0
        self.r_beats = 0
        self.b_beats = 0
        self.r_resp: list[int] = []
        self.b_resp: list[int] = []
        self.r_stall = 0
        self.b_stall = 0
        self.first_arvalid: int | None = None
        self.first_awvalid: int | None = None
        self.w_hs: int | None = None
        self.rready_rise: int | None = None
        self.bready_rise: int | None = None
        self.r_hs: int | None = None
        self.b_hs: int | None = None


class _StallSampler:
    """Samples the s_axi channels on every clk_smc rising edge into the current window."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.win = _Window()
        self._prev_rready = 0
        self._prev_bready = 0

    def new_window(self) -> _Window:
        self.win = _Window()
        return self.win

    async def run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smc)
            w = self.win
            w.cycle += 1
            arvalid, awvalid = _bit(dut, "s_axi_arvalid"), _bit(dut, "s_axi_awvalid")
            rvalid, rready = _bit(dut, "s_axi_rvalid"), _bit(dut, "s_axi_rready")
            bvalid, bready = _bit(dut, "s_axi_bvalid"), _bit(dut, "s_axi_bready")
            wvalid, wready = _bit(dut, "s_axi_wvalid"), _bit(dut, "s_axi_wready")
            if arvalid and w.first_arvalid is None:
                w.first_arvalid = w.cycle
            if awvalid and w.first_awvalid is None:
                w.first_awvalid = w.cycle
            if wvalid and wready and w.w_hs is None:
                w.w_hs = w.cycle
            if rready and not self._prev_rready and w.first_arvalid is not None:
                w.rready_rise = w.rready_rise or w.cycle
            if bready and not self._prev_bready and w.first_awvalid is not None:
                w.bready_rise = w.bready_rise or w.cycle
            if rvalid and not rready:
                w.r_stall += 1
            if bvalid and not bready:
                w.b_stall += 1
            if rvalid and rready:
                w.r_beats += 1
                w.r_hs = w.cycle
                w.r_resp.append(_bit(dut, "s_axi_rresp"))
            if bvalid and bready:
                w.b_beats += 1
                w.b_hs = w.cycle
                w.b_resp.append(_bit(dut, "s_axi_bresp"))
            self._prev_rready, self._prev_bready = rready, bready


class smc_clk_ratio_handshake_stall_test_seq(SmcCsrSeq):
    """Stalled reads and trailing-data writes on UART SCR[0] and SCRATCH[0]."""

    def __init__(self, name: str = "smc_clk_ratio_handshake_stall_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []
        self._steps: list[tuple[str, int]] = []
        self._chk_lines: list[tuple[str, int]] = []
        self._last_access = "none"
        self._bounded_waits: list[tuple[str, str, str]] = []
        self._sampler: _StallSampler | None = None

    def _mark_step(self, step_id: str) -> None:
        self._steps.append((step_id, int(get_sim_time("ps"))))

    def _emit_chk(self, chk_id: str, text: str) -> None:
        self._chk_lines.append((chk_id, int(get_sim_time("ps"))))
        self.chk_seen.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    async def _preload(self, tag: str, addr: int, label: str, data: int) -> None:
        self._last_access = f"write {tag} {label}=0x{data:08x} addr=0x{addr:08x}"
        await self.csr_write(tag, addr, data)
        self._last_access = f"read {tag} {label} addr=0x{addr:08x}"
        got = await self.csr_read(tag, addr, expected=data)
        assert got == data, f"{self._last_access}: got 0x{got:08x}, want 0x{data:08x}"

    async def _access(self, op: SmcSysAxiOp, tag: str, addr: int, label: str, data: int, timing):
        """Run one stalled access and return its item and observation window."""
        item = SmcSysAxiItem(f"stall_{tag}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data if op is SmcSysAxiOp.WRITE else 0
        item.expected = data if op is SmcSysAxiOp.READ else None
        item.timing = timing
        self._last_access = f"{op.value} {tag} {label} data=0x{data:08x} addr=0x{addr:08x}"
        win = self._sampler.new_window()
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == OKAY, f"{self._last_access}: response code {item.resp_code}"
        want_r = 1 if op is SmcSysAxiOp.READ else 0
        want_b = 1 if op is SmcSysAxiOp.WRITE else 0
        for _ in range(CATCH_UP_CYCLES):
            if win.r_beats >= want_r and win.b_beats >= want_b:
                break
            await RisingEdge(cocotb.top.clk_smc)
        else:
            raise AssertionError(
                f"{self._last_access}: sampler saw R={win.r_beats}/{want_r} "
                f"B={win.b_beats}/{want_b} after {CATCH_UP_CYCLES} clk_smc cycles"
            )
        await ClockCycles(cocotb.top.clk_smc, QUIET_CYCLES)
        assert (win.r_beats, win.b_beats) == (want_r, want_b), (
            f"{self._last_access}: R beats {win.r_beats} B beats {win.b_beats}, "
            f"want R={want_r} B={want_b}"
        )
        assert win.r_resp + win.b_resp == [OKAY] * (want_r + want_b), (
            f"{self._last_access}: R resp {win.r_resp} B resp {win.b_resp}"
        )
        return item, win

    async def _stalled_read(self, tag: str, addr: int, label: str, want: int):
        timing = AxiTimingProfile(r_ready_delay=READY_HOLD_CYCLES)
        item, win = await self._access(SmcSysAxiOp.READ, tag, addr, label, want, timing)
        assert item.rdata == want, (
            f"{self._last_access}: read 0x{item.rdata:08x}, want 0x{want:08x}"
        )
        assert win.r_stall > 0, f"{self._last_access}: no R stall seen (r_stall={win.r_stall})"
        return item, win

    async def _stalled_write(self, tag: str, addr: int, label: str, data: int):
        timing = AxiTimingProfile(w_delay=STALL_CYCLES, b_ready_delay=READY_HOLD_CYCLES)
        item, win = await self._access(SmcSysAxiOp.WRITE, tag, addr, label, data, timing)
        assert win.first_awvalid is not None and win.w_hs is not None and win.b_hs is not None, (
            f"{self._last_access}: AW/W/B events missing {vars(win)}"
        )
        assert win.w_hs - win.first_awvalid > 0, (
            f"{self._last_access}: no W trail seen (W trail {win.w_hs - win.first_awvalid})"
        )
        assert win.b_stall > 0, f"{self._last_access}: no B stall seen (b_stall={win.b_stall})"
        return item, win

    @staticmethod
    def _read_summary(win: _Window) -> str:
        rise = win.rready_rise
        to_done = "n/a" if rise is None or win.r_hs is None else str(win.r_hs - rise)
        total = (
            "n/a"
            if win.first_arvalid is None or win.r_hs is None
            else str(win.r_hs - win.first_arvalid)
        )
        return (
            f"R stall cycles {win.r_stall}, R beats {win.r_beats}, resp {win.r_resp}, "
            f"RREADY rising to completion {to_done} smc cycles, ARVALID to completion {total}"
        )

    @staticmethod
    def _write_summary(win: _Window) -> str:
        trail = win.w_hs - win.first_awvalid
        total = win.b_hs - win.first_awvalid
        rise = win.bready_rise
        to_done = "n/a" if rise is None else str(win.b_hs - rise)
        return (
            f"W trailed AWVALID by {trail} smc cycles, B stall cycles {win.b_stall}, "
            f"B beats {win.b_beats}, resp {win.b_resp}, BREADY rising to completion {to_done}, "
            f"AWVALID to completion {total} smc cycles"
        )

    async def body(self) -> None:
        dut = cocotb.top
        for sig in PORT_SIGNALS:
            assert hasattr(dut, sig), f"tb_top has no {sig}"
        uart0 = smc_indexed_addr(UART_SCR_SYMBOL, 0)
        scratch0 = smc_indexed_addr(SCRATCH_SYMBOL, 0)

        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._bounded_waits.append(
            ("fuse_sense_done", f"{FUSE_SENSE_MAX_CYCLES}smc_cycles", "done")
        )
        self._sampler = _StallSampler(dut)
        sampler_task = cocotb.start_soon(self._sampler.run())
        await self._preload("UART_PRELOAD", uart0, "UART0_SCR", UART_PRELOAD)
        await self._preload("SCRATCH_PRELOAD", scratch0, "SCRATCH[0]", SCRATCH_PRELOAD)
        self._mark_step("S1")

        _, win = await self._stalled_read("PERIPH_RD", uart0, "UART0_SCR", UART_PRELOAD)
        read_text = self._read_summary(win)
        self._mark_step("S2")

        _, win = await self._stalled_write("PERIPH_WR", uart0, "UART0_SCR", UART_WRITE)
        write_text = self._write_summary(win)
        self._last_access = "read PERIPH_WR_RB UART0_SCR"
        back = await self.csr_read("PERIPH_WR_RB", uart0, expected=UART_WRITE)
        assert back == UART_WRITE, f"UART0_SCR reads 0x{back:08x} after write, want 0xa5"
        self._mark_step("S3")

        _, rwin = await self._stalled_read("SMC_RD", scratch0, "SCRATCH[0]", SCRATCH_PRELOAD)
        _, wwin = await self._stalled_write("SMC_WR", scratch0, "SCRATCH[0]", SCRATCH_WRITE)
        self._last_access = "read SMC_WR_RB SCRATCH[0]"
        back_smc = await self.csr_read("SMC_WR_RB", scratch0, expected=SCRATCH_WRITE)
        assert back_smc == SCRATCH_WRITE, f"SCRATCH[0] reads 0x{back_smc:08x}, want 0x3c3c3c3c"
        self._mark_step("S4")
        sampler_task.cancel()
        stamp = int(get_sim_time("ps"))
        while int(get_sim_time("ps")) == stamp:
            await RisingEdge(dut.clk_smc)

        self._emit_chk(
            "CHK-STALL-PERIPH-READ",
            f"UART0 SCR[0] read with r_ready_delay {READY_HOLD_CYCLES} "
            f"returned 0x{UART_PRELOAD:02x} OKAY; {read_text}; "
            "completion count printed, SF-006 bound not asserted",
        )
        self._emit_chk(
            "CHK-STALL-PERIPH-WRITE",
            f"UART0 SCR[0] write 0x{UART_WRITE:02x} with w_delay {STALL_CYCLES} and "
            f"b_ready_delay {READY_HOLD_CYCLES} drew one OKAY B beat and reads back 0x{back:02x}; "
            f"{write_text}; completion count printed, SF-006 bound not asserted",
        )
        self._emit_chk(
            "CHK-STALL-SMC",
            f"SCRATCH[0] stalled read returned 0x{SCRATCH_PRELOAD:08x} OKAY "
            f"({self._read_summary(rwin)}); stalled write 0x{SCRATCH_WRITE:08x} drew one OKAY "
            f"B beat ({self._write_summary(wwin)}) and reads back 0x{back_smc:08x}",
        )

        self._bounded_waits.append(("sep_in_axi_access", f"{AXI_TIMEOUT_NS}ns", self._last_access))
        self._bounded_waits.append(
            ("sampler_catch_up", f"{CATCH_UP_CYCLES}smc_cycles", "R/B beat seen")
        )
        self._bounded_waits.append(("quiet_window", f"{QUIET_CYCLES}smc_cycles", "no second beat"))
        self._mark_step("S5")
        waits = " ".join(f"{n}={b} last={s}" for n, b, s in self._bounded_waits)
        self._emit_chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._bounded_waits)} bounded waits: {waits}; expiry raises AssertionError",
        )
        self._assert_fence()

    def _assert_fence(self) -> None:
        ids = tuple(s for s, _ in self._steps)
        assert ids == STEP_ORDER, f"step ids {ids} != contract order {STEP_ORDER}"
        stamps = [t for _, t in self._steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing: {stamps}"
        chk_ids = tuple(c for c, _ in self._chk_lines)
        assert chk_ids == CHK_ORDER, f"checker lines {chk_ids} != order {CHK_ORDER}"
        step_stamp = dict(self._steps)
        for chk_id, t in self._chk_lines:
            assert t >= step_stamp[CHK_STEP[chk_id]], f"{chk_id} printed before its step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            "<".join(FENCE_TERMS[s] for s in STEP_ORDER),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._steps),
        )
