# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_mailbox_int_test (SMU_ALL_004).

DV-CARD:          SMU_ALL_004   ANCHOR: smu_smc_mailbox_int_test

Owns:
  SMC-MBX-IRQ-EXT.S2 — Width equals NUM_MAILBOXES (32) at the SMU boundary
    (wrapper; required_cells width=32).

Width and value are both read on the DUT's own output port
`smc_ext_mailbox_interrupts_o`, reached hierarchically through `smu_scope()`.
The testbench net that port drives is declared from the same RTL package as the
port, so its width is 32 whatever width the port has, and only the port answers
the boundary claim. The 32 the measured width is compared against is the SMC
specification's mailbox count (`hw/sys/smc/doc/port_table.adoc`,
`smc_ext_mailbox_interrupts_o`). Bit-index mapping is proven by
raising the outbound write-threshold IRQ of mailbox 0 and of mailbox
NUM_MAILBOXES-1 over the SMC fabric JTAG2AXI frontdoor and requiring exactly
that bit of the boundary vector to move.

CHANNELS.S2/S3 and EXT.S1 are owned by SMU_ALL_008 — out of scope.
No Force/deposit on smc_ext_mailbox_interrupts_o; all stimulus is MMIO.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import mailbox_u32, smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope, tb_pin

IRQEN_WTIRQ = mailbox_u32("AXIL_MAILBOX__IRQEN__WTIRQ_bm")
# The DUT boundary port the width claim is about, inside the design.
MBX_PORT = "smc_ext_mailbox_interrupts_o"
MBX_PORT_PATH = f"smu.{MBX_PORT}"
# One push takes the outbound write FIFO above the WIRQT reset threshold.
MBX_PUSH_PATTERN = 0x5A5A_5A5A
J2A_POLL = 128
MASK32 = 0xFFFF_FFFF


class smu_smc_mailbox_int_test_seq:
    """SMU_ALL_004: smc_ext_mailbox_interrupts_o width and bit-index DECODE."""

    NUM_MAILBOXES = 32
    BOUND_CYCLES = 2000
    SETTLE_CYCLES = 32
    # Bounded waits: primary release (S1), width-sample settle (S2), one IRQ
    # assert per probed mailbox and one vector release (S3).
    EXPECTED_TIMEOUT_PATHS = 5

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        self._lifecycle_ts: dict[str, float] = {}
        # Fence granularity: one SMU clock period of simulated time. Every
        # step below spans at least one clk_smu_i edge, so a run whose
        # simulation time did not advance fails the fence.
        self.min_sim_advance_ns = float(self.cfg.smu_clk_period_ns)

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sim_ns(self) -> float:
        return float(get_sim_time(units="ns"))

    def _mark_step(self, step_id: str, detail: str) -> None:
        now = self._sim_ns()
        self._step_ts[step_id] = now
        self._log(f"STEP {step_id} @{now:.3f}ns: {detail}")

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    def _nbits(self, signal, name: str) -> int:
        if signal is None:
            raise AssertionError(f"width observe fail: {name} is None")
        n = getattr(signal, "n_bits", None)
        if n is None:
            try:
                n = len(signal)
            except TypeError as exc:
                raise AssertionError(f"width observe fail: cannot measure {name}") from exc
        if n <= 0:
            raise AssertionError(f"width observe fail: {name} n_bits={n}")
        return int(n)

    async def _wait_eq(
        self,
        signal,
        expect: int,
        *,
        clk,
        bound: int,
        label: str,
    ) -> int:
        last = None
        for _ in range(bound):
            await RisingEdge(clk)
            last = self._sample(signal, label)
            if last == expect:
                self._timeout_paths.append(f"{label}: bound={bound} ok last={last}")
                return last
        self._timeout_paths.append(f"{label}: bound={bound} EXPIRED last={last}")
        raise AssertionError(f"TIMEOUT {label}: bound={bound} last_state={last} expect={expect}")

    async def _wait_width(
        self,
        signal,
        expect_w: int,
        *,
        clk,
        bound: int,
        label: str,
    ) -> tuple[int, int]:
        """Bounded wait until port width is measurable and equals expect_w."""
        last_w = None
        last_val = None
        for _ in range(bound):
            await RisingEdge(clk)
            try:
                last_w = self._nbits(signal, label)
                last_val = self._sample(signal, label)
            except AssertionError:
                continue
            if last_w == expect_w:
                self._timeout_paths.append(
                    f"{label}: bound={bound} ok last=width={last_w}/val=0x{last_val:x}"
                )
                return last_w, last_val
        self._timeout_paths.append(
            f"{label}: bound={bound} EXPIRED last=width={last_w}/val={last_val}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound} "
            f"last_state=width={last_w}/val={last_val} expect_width={expect_w}"
        )

    @staticmethod
    def _mbx_addr(idx: int, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_{idx}_{reg}_BASE_ADDR")

    async def _j2a_rd32(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=J2A_POLL,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"MBX RD {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A RD {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(rdata) & MASK32

    async def _j2a_wr32(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=J2A_POLL,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"MBX WR {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A WR {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"J2A WR {name} @0x{addr:08x} data=0x{data:08x} status=SUCCESS")

    def _mark_lifecycle(self, phase: str, detail: str) -> None:
        self._lifecycle_ts[phase] = time.monotonic()
        self._log(f"LIFECYCLE CHK-SMC-MBX-IRQ-EXT-S2 {phase}: {detail}")

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self.cfg.reset_done.wait()
        for _ in range(self.SETTLE_CYCLES):
            await RisingEdge(dut.clk_smu_i)

        # ------------------------------------------------------------------
        # S1 SETUP
        # ------------------------------------------------------------------
        self._mark_step(
            "S1",
            "SETUP: wrapper bring-up; clocks/resets stable; "
            f"pre-MMIO baseline {MBX_PORT_PATH} DUT-port observation",
        )
        await self._wait_eq(
            smc_primary_reset(dut),
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s1_primary_release",
        )
        mbx = tb_pin(smu_scope(dut), MBX_PORT)
        baseline = self._sample(mbx, MBX_PORT_PATH)
        baseline_w = self._nbits(mbx, MBX_PORT_PATH)
        self._log(
            f"baseline DUT port {MBX_PORT_PATH} width={baseline_w} "
            f"val=0x{baseline:x} (passive; no MMIO)"
        )

        # ------------------------------------------------------------------
        # S2 SMC-MBX-IRQ-EXT.S2 — width DECODE at NUM_MAILBOXES
        # ------------------------------------------------------------------
        self._mark_step(
            "S2",
            f"ACTION SMC-MBX-IRQ-EXT.S2: observe DUT port {MBX_PORT_PATH}"
            f"[{self.NUM_MAILBOXES - 1}:0] width/DECODE at SMU boundary",
        )
        self._log(f"COVERAGE SMC-MBX-IRQ-EXT.S2 cells: width={self.NUM_MAILBOXES}")

        # Lifecycle (card non-null): set → observed → cleared → checked_cleared
        self._mark_lifecycle(
            "set",
            "assert observation for SMC-MBX-IRQ-EXT.S2 "
            f"(port={MBX_PORT_PATH} baseline_w={baseline_w} "
            f"baseline_val=0x{baseline:x})",
        )

        width, observed_val = await self._wait_width(
            mbx,
            self.NUM_MAILBOXES,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s2_width_sample",
        )
        self._mark_lifecycle(
            "observed",
            "consumer samples asserted condition for SMC-MBX-IRQ-EXT.S2 "
            f"(width={width} val=0x{observed_val:x} "
            f"NUM_MAILBOXES={self.NUM_MAILBOXES})",
        )
        if width != self.NUM_MAILBOXES:
            raise AssertionError(f"SMC-MBX-IRQ-EXT.S2 width={width} expect={self.NUM_MAILBOXES}")

        # ------------------------------------------------------------------
        # S3 SMC-MBX-IRQ-EXT.S2 — bit-index DECODE over the SMC fabric J2A
        # ------------------------------------------------------------------
        probe_idx = (0, self.NUM_MAILBOXES - 1)
        self._mark_step(
            "S3",
            "ACTION SMC-MBX-IRQ-EXT.S2: raise the outbound write-threshold IRQ of "
            f"mailboxes {probe_idx} over J2A; each must move exactly its own bit of "
            f"the DUT port {MBX_PORT_PATH}",
        )
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if not hasattr(dut, "tb_smc_jtag2axi_security_disable"):
            raise AssertionError("unobservable: tb_top.tb_smc_jtag2axi_security_disable missing")
        gate = self._sample(dut.tb_smc_jtag2axi_security_disable, "security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")

        expected = baseline
        for idx in probe_idx:
            bit = 1 << idx
            if baseline & bit:
                raise AssertionError(
                    f"mailbox {idx} bit already set in baseline 0x{baseline:x}; "
                    "its assert would prove nothing"
                )
            irqen_addr = self._mbx_addr(idx, "IRQEN")
            await self._j2a_wr32(jtag, irqen_addr, IRQEN_WTIRQ, f"MBX{idx}-IRQEN")
            got_en = await self._j2a_rd32(jtag, irqen_addr, f"MBX{idx}-IRQEN")
            if got_en != IRQEN_WTIRQ:
                raise AssertionError(
                    f"MBX{idx} IRQEN readback want 0x{IRQEN_WTIRQ:x} got 0x{got_en:x}"
                )
            await self._j2a_wr32(
                jtag,
                self._mbx_addr(idx, "WRITE_DATA"),
                MBX_PUSH_PATTERN,
                f"MBX{idx}-WRITE_DATA",
            )
            expected |= bit
            await self._wait_eq(
                mbx,
                expected,
                clk=dut.clk_smu_i,
                bound=self.BOUND_CYCLES,
                label=f"s3_mbx{idx}_irq_assert",
            )
            for _ in range(self.SETTLE_CYCLES):
                await RisingEdge(dut.clk_smu_i)
            held = self._sample(mbx, MBX_PORT_PATH)
            if held != expected:
                raise AssertionError(
                    f"mailbox {idx} IRQ not level-held: {MBX_PORT_PATH}=0x{held:x} "
                    f"expect=0x{expected:x} after {self.SETTLE_CYCLES} cycles"
                )
            self._log(
                f"CHK-SMC-MBX-IRQ-EXT-S2 index mailbox {idx}: "
                f"{MBX_PORT_PATH}=0x{held:x} (bit {idx} set, all other bits unchanged)"
            )
            sb.expect_eq(f"CHK-SMC-MBX-IRQ-EXT-S2 bit {idx}", held, expected)

        for idx in probe_idx:
            await self._j2a_wr32(jtag, self._mbx_addr(idx, "IRQEN"), 0, f"MBX{idx}-IRQEN-CLR")
        await self._wait_eq(
            mbx,
            baseline,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s3_mbx_irq_release",
        )
        released = self._sample(mbx, MBX_PORT_PATH)
        self._log(
            f"CHK-SMC-MBX-IRQ-EXT-S2 release: {MBX_PORT_PATH}=0x{released:x} "
            f"baseline=0x{baseline:x}"
        )
        sb.expect_eq("CHK-SMC-MBX-IRQ-EXT-S2 release", released, baseline)

        # cleared: quiet window after the IRQ release; confirm DUT-driven idle
        for _ in range(self.SETTLE_CYCLES):
            await RisingEdge(dut.clk_smu_i)
        cleared_val = self._sample(mbx, MBX_PORT_PATH)
        if cleared_val != baseline:
            raise AssertionError(
                "SMC-MBX-IRQ-EXT.S2 clear/ack fail: vector moved with no MMIO "
                f"in flight (baseline=0x{baseline:x} "
                f"cleared=0x{cleared_val:x})"
            )
        self._mark_lifecycle(
            "cleared",
            "clear/ack for SMC-MBX-IRQ-EXT.S2 "
            f"(idle_val=0x{cleared_val:x} matches baseline; no force)",
        )

        checked_w = self._nbits(mbx, MBX_PORT_PATH)
        checked_val = self._sample(mbx, MBX_PORT_PATH)
        if checked_w != self.NUM_MAILBOXES:
            raise AssertionError(
                f"SMC-MBX-IRQ-EXT.S2 checked_cleared width={checked_w} expect={self.NUM_MAILBOXES}"
            )
        if checked_val != baseline:
            raise AssertionError(
                "SMC-MBX-IRQ-EXT.S2 checked_cleared value drift: "
                f"baseline=0x{baseline:x} checked=0x{checked_val:x}"
            )
        self._mark_lifecycle(
            "checked_cleared",
            f"readback cleared for SMC-MBX-IRQ-EXT.S2 (width={checked_w} val=0x{checked_val:x})",
        )

        lc_order = ["set", "observed", "cleared", "checked_cleared"]
        for phase in lc_order:
            if phase not in self._lifecycle_ts:
                raise AssertionError(f"CHK-SMC-MBX-IRQ-EXT-S2 lifecycle missing: {phase}")
        for a, b in zip(lc_order, lc_order[1:]):
            if self._lifecycle_ts[a] >= self._lifecycle_ts[b]:
                raise AssertionError(
                    f"CHK-SMC-MBX-IRQ-EXT-S2 lifecycle order fail: {a} not before {b}"
                )

        detail = (
            f"width={width} NUM_MAILBOXES={self.NUM_MAILBOXES} "
            f"port={MBX_PORT_PATH} "
            f"baseline=0x{baseline:x} observed=0x{observed_val:x} "
            f"checked=0x{checked_val:x}"
        )
        self._log(f"CHK-SMC-MBX-IRQ-EXT-S2: PASS ({detail})")
        sb.expect_eq(
            "CHK-SMC-MBX-IRQ-EXT-S2 width equals NUM_MAILBOXES",
            width,
            self.NUM_MAILBOXES,
            evidence="CHK-SMC-MBX-IRQ-EXT-S2",
        )

        # ------------------------------------------------------------------
        # S4 TIMEOUT inventory
        # ------------------------------------------------------------------
        self._mark_step(
            "S4",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last-state",
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing finite bound: {line}")
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing last-state: {line}")
        self._log(
            "CHK-TIMEOUT-PATHS: Finite bound on S4; expiry fails with "
            f"last-state diagnostics (paths={n_paths} "
            f"expect={self.EXPECTED_TIMEOUT_PATHS} bound={self.BOUND_CYCLES})"
        )
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        await ClockCycles(dut.clk_smu_i, self.SETTLE_CYCLES)
        self._step_ts["PASS"] = self._sim_ns()
        self._log("SMU_ALL_004 sequence complete (PASS term recorded for NONVAC fence)")

        order = ["S1", "S2", "S3", "S4", "PASS"]
        expect_deltas = len(order) - 1
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        deltas_ns = [self._step_ts[b] - self._step_ts[a] for a, b in zip(order, order[1:])]
        min_ns = self.min_sim_advance_ns
        advancing = sum(1 for d in deltas_ns if d >= min_ns)
        if advancing != expect_deltas:
            raise AssertionError(
                f"CHK-NONVAC sim-time fence fail: {advancing} of {expect_deltas} steps "
                f"advanced >= {min_ns:.3f}ns of simulation time; "
                f"deltas_ns={[round(d, 3) for d in deltas_ns]}"
            )
        self._log(
            "CHK-NONVAC: Ordered simulation-time fence S1<S2<S3<S4<PASS all hold "
            f"(min_step={min_ns:.3f}ns "
            f"total={self._step_ts['PASS'] - self._step_ts['S1']:.3f}ns "
            f"deltas_ns={[round(d, 3) for d in deltas_ns]})"
        )
        sb.expect_eq(
            "CHK-NONVAC sim-time advancing step count",
            advancing,
            expect_deltas,
            evidence="CHK-NONVAC",
        )
