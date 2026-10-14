# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Gated peripheral windows answer SLVERR with 0xBADCAB1E and recover when the enable clears.

Spec sources: memmap.adoc Address Space Organization gated-clock rule;
smc_base_config.rdl CLOCK_GATE_CONTROL field descriptions (cg_en, cg_hysteresis).

Every window is polled with a literal bound of 400 clk_smc_i cycles, one re-read
every 4 cycles; the interval between the enable write and the effective SLVERR is
measured and printed, never compared (the specification does not state the value). Only
the five peripherals named by the spec are driven.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    AVS_CG_EN,
    CLOCK_GATE_CONTROL,
    I2C_CG_EN,
    I3C_CG_EN,
    TELEMETRY_CG_EN,
    UART_CG_EN,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i3c_to_fabric_test_seq import HCI_VERSION_OFFSET, I3C_HCI_VERSION_RESET

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT,
    I2C_CTRL_I2C_CTRL_REG_DEFAULT,
    TELEMETRY_RECEIVER_CTRL_REG_DEFAULT,
    UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT,
)

AXI_RESP_OKAY = 0
AXI_RESP_SLVERR = 2
GATED_RDATA = SmcCsrSeq.ERR_SLAVE_SIGNATURE
POLL_BOUND_CYCLES = 400
POLL_SPACING_CYCLES = 4
AXI_TIMEOUT_NS = 50_000
FUSE_SUB_WAIT_CYCLES = 200_000
# Literal stimulus floor: S2-S5 each run five peripherals with at least a set, a poll,
# the stage accesses and a clear; S1 and the restore add a handful.
MIN_SEP_IN_ACCESSES = 130

# (peripheral, enable mask, window base register, RDL reset word)
PERIPHERALS: tuple[tuple[str, int, int, int], ...] = (
    (
        "I3C",
        I3C_CG_EN,
        smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", 0) + HCI_VERSION_OFFSET,
        I3C_HCI_VERSION_RESET,
    ),
    (
        "AVS",
        AVS_CG_EN,
        smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR"),
        AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT,
    ),
    (
        "I2C",
        I2C_CG_EN,
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0),
        I2C_CTRL_I2C_CTRL_REG_DEFAULT,
    ),
    (
        "UART",
        UART_CG_EN,
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
        ),
        UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT,
    ),
    (
        "TELEMETRY",
        TELEMETRY_CG_EN,
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
        ),
        TELEMETRY_RECEIVER_CTRL_REG_DEFAULT,
    ),
)
ALL_CG_EN = 0
for _p in PERIPHERALS:
    ALL_CG_EN |= _p[1]
_STEPS = (
    "SAVED",
    "READ_SLVERR",
    "WRITE_SLVERR",
    "RESTORED",
    "ISOLATION",
    "TRANSITION",
    "CLOCK_GATE_CONTROL_RESTORED",
)
_CHECKERS = (
    ("CHK-CG-READ-SLVERR", "READ_SLVERR"),
    ("CHK-CG-WRITE-SLVERR", "WRITE_SLVERR"),
    ("CHK-CG-RESTORED", "RESTORED"),
    ("CHK-CG-ISOLATION", "ISOLATION"),
    ("CHK-CG-TRANSITION-BOUNDED", "TRANSITION"),
)


class smc_clock_gated_window_slverr_test_seq(SmcCsrSeq):
    """Set each peripheral enable alone and hold its window to SLVERR, then recover."""

    def __init__(self, name: str = "smc_clock_gated_window_slverr_test_seq") -> None:
        super().__init__(name)
        self.finished = False
        self._edges = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._last_poll = "none"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _count_edges(self) -> None:
        while True:
            await RisingEdge(cocotb.top.clk_smc_i)
            self._edges += 1

    async def _read_any(self, name: str, addr: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name}: read returned no response code"
        return item

    async def _poll(self, name: str, addr: int, want_resp: int) -> tuple[SmcSysAxiItem, int, int]:
        """Re-read `addr` every 4 cycles until it answers `want_resp`; fail after 400 cycles."""
        start = self._edges
        polls = 0
        while True:
            item = await self._read_any(f"{name}_POLL", addr)
            polls += 1
            elapsed = self._edges - start
            self._last_poll = (
                f"{name}: resp={item.resp_code} rdata=0x{item.rdata:08X} polls={polls} "
                f"cycles={elapsed}"
            )
            done = item.resp_code == want_resp and (
                want_resp != AXI_RESP_SLVERR or item.rdata == GATED_RDATA
            )
            if done:
                self._waits.append(f"{name}=400cyc last[{self._last_poll}]")
                return item, polls, elapsed
            assert elapsed < POLL_BOUND_CYCLES, (
                f"{name}: window 0x{addr:08x} did not reach resp={want_resp} within "
                f"{POLL_BOUND_CYCLES} clk_smc_i cycles; last {self._last_poll}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, POLL_SPACING_CYCLES)

    async def _write_cgc(self, name: str, value: int) -> None:
        await self.csr_write(name, CLOCK_GATE_CONTROL, value)
        await self.csr_read(f"{name}_RB", CLOCK_GATE_CONTROL, expected=value)

    async def _gate(self, periph: str, enable: int, addr: int) -> tuple[int, int]:
        await self._write_cgc(f"CGC_{periph}_SET", self.base | enable)
        _item, polls, cycles = await self._poll(f"{periph}_GATED", addr, AXI_RESP_SLVERR)
        return polls, cycles

    async def _ungate(self, periph: str, addr: int) -> tuple[SmcSysAxiItem, int, int]:
        await self._write_cgc(f"CGC_{periph}_CLR", self.base)
        return await self._poll(f"{periph}_RESTORED", addr, AXI_RESP_OKAY)

    async def body(self) -> None:
        cocotb.start_soon(self._count_edges())
        await self.wait_fuse_sense_done()
        self._fuse_last = {}
        for sub in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, sub).value
            assert sig.is_resolvable, f"{sub} is X/Z ({sig})"
            self._fuse_last[sub] = int(sig)
        original = await self.csr_read("CGC_SAVE", CLOCK_GATE_CONTROL)
        self.base = original & ~ALL_CG_EN
        self._mark_step("SAVED")

        # S2: read of each gated window.
        read_lines = []
        for periph, enable, addr, _reset in PERIPHERALS:
            polls, cycles = await self._gate(periph, enable, addr)
            rdata = await self.csr_read_err_signature(
                f"{periph}_GATED_AGAIN", addr, resp=AXI_RESP_SLVERR
            )
            read_lines.append(f"{periph}: SLVERR/0x{rdata:08X} after {polls} polls, {cycles} cyc")
            await self._ungate(periph, addr)
        self._mark_step("READ_SLVERR")
        self._log_chk(
            "CHK-CG-READ-SLVERR",
            f"{'; '.join(read_lines)} (rresp 2, rdata 0x{GATED_RDATA:08X}, bound "
            f"{POLL_BOUND_CYCLES} cycles)",
        )

        # S3: write of each gated window.
        write_lines = []
        for periph, enable, addr, reset in PERIPHERALS:
            await self._gate(periph, enable, addr)
            wresp = await self.csr_write_expect_error(
                f"{periph}_GATED_WR", addr, (~reset) & 0xFFFF_FFFF, resp=AXI_RESP_SLVERR
            )
            write_lines.append(f"{periph}: bresp {wresp}")
            await self._ungate(periph, addr)
        self._mark_step("WRITE_SLVERR")
        self._log_chk(
            "CHK-CG-WRITE-SLVERR",
            f"{'; '.join(write_lines)} (write of the complemented reset word refused)",
        )

        # S4: window reads its reset after the enable clears.
        restored_lines = []
        for periph, enable, addr, reset in PERIPHERALS:
            await self._gate(periph, enable, addr)
            item, polls, cycles = await self._ungate(periph, addr)
            assert item.rdata == reset, (
                f"{periph}: window 0x{addr:08x} read 0x{item.rdata:08X} after the enable "
                f"cleared, RDL reset 0x{reset:08X}"
            )
            restored_lines.append(
                f"{periph}: OKAY 0x{item.rdata:08X} == reset after {polls} polls, {cycles} cyc"
            )
        self._mark_step("RESTORED")
        self._log_chk("CHK-CG-RESTORED", "; ".join(restored_lines))

        # S5: the other four windows and CLOCK_GATE_CONTROL stay reachable.
        iso_lines = []
        for periph, enable, addr, _reset in PERIPHERALS:
            await self._gate(periph, enable, addr)
            others = [p for p in PERIPHERALS if p[0] != periph]
            for other, _en, oaddr, oreset in others:
                await self.csr_read(f"{other}_WHILE_{periph}_GATED", oaddr, expected=oreset)
            await self.csr_read(
                f"CGC_WHILE_{periph}_GATED", CLOCK_GATE_CONTROL, expected=self.base | enable
            )
            iso_lines.append(f"{periph} gated: {','.join(o[0] for o in others)} and CGC OKAY")
            await self._ungate(periph, addr)
        self._mark_step("ISOLATION")
        self._log_chk("CHK-CG-ISOLATION", "; ".join(iso_lines))

        # S6: SYS_IN window read issued with the SEP_IN enable write (observe-only).
        periph, enable, addr, _reset = PERIPHERALS[2]
        item = SmcSysAxiItem("sys_in_window_rd_during_enable")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        sys_task = cocotb.start_soon(
            _OneShot(item, "sys_in_transition_os").start(self.env.sys_in_axi_agent.sequencer)
        )
        await self._write_cgc("CGC_TRANSITION_SET", self.base | enable)
        await sys_task
        assert item.resp_code is not None, "SYS_IN read during the enable write got no response"
        sys_resp, sys_rdata = item.resp_code, item.rdata
        await self._poll(f"{periph}_TRANSITION_GATED", addr, AXI_RESP_SLVERR)
        await self._ungate(periph, addr)
        self._mark_step("TRANSITION")
        self._log_chk(
            "CHK-CG-TRANSITION-BOUNDED",
            f"sys_in_resp={sys_resp} sys_in_rdata=0x{sys_rdata:08X} window={periph} "
            f"completed within {AXI_TIMEOUT_NS} ns (observe-only, not specified, measured)",
        )

        await self.csr_write("CGC_RESTORE", CLOCK_GATE_CONTROL, original)
        await self.csr_read("CGC_RESTORE_RB", CLOCK_GATE_CONTROL, expected=original)
        self._mark_step("CLOCK_GATE_CONTROL_RESTORED")

        self._waits.append(f"sep_in_axi_access={AXI_TIMEOUT_NS}ns last[{self._last_poll}]")
        self._waits.append(f"sys_in_axi_access={AXI_TIMEOUT_NS}ns last[resp={sys_resp}]")
        for sub in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            self._waits.append(f"{sub}={FUSE_SUB_WAIT_CYCLES}cyc last[{self._fuse_last[sub]}]")
        self._log_chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self._waits)} bounded waits: {' | '.join(self._waits)}; "
            "expiry raises AssertionError with the last state",
        )
        self._nonvac_fence()
        self.finished = True

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        marks = [c for c in self._chk_marks if c[0] != "CHK-TIMEOUT-PATHS"]
        assert tuple(c for c, _ in marks) == tuple(c for c, _ in _CHECKERS), (
            f"checker lines {[c for c, _ in marks]}"
        )
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_c, step) in zip(marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; accesses %d >= %d",
            " < ".join(ids),
            ",".join(c for c, _ in self._chk_marks),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self.accesses,
            MIN_SEP_IN_ACCESSES,
        )
