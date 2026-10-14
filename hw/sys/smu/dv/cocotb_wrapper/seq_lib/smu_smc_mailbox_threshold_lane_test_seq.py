# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_mailbox_threshold_lane_test.

Spec: axil_mailbox.rdl (STATUS, WIRQT, IRQS woclr, IRQEN, IRQP, CTRL.wflush);
  axil_mailbox_smc_wrap.rdl;
  smc.rdl smc_mailbox; architecture.adoc Interrupts (IRQP = IRQS & IRQEN, strict greater-than
  WIRQT, WIRQT clamp); interface.adoc CTRL flush; periphs.adoc MailboxDepth = 2.

Outbound mailbox 0 over the SMC fabric JTAG2AXI bridge: IRQS and STATUS latch with IRQEN = 0, IRQP
and lane 0 of smc_ext_mailbox_interrupts_o follow IRQEN, the lane drops with the enable, flush and
acknowledge return to baseline, WIRQT = 5 clamps to MailboxDepth - 1, and an acknowledge while the
occupancy still exceeds WIRQT is observed and logged only. The lane-n = mailbox-n mapping is proven
by smu_smc_mailbox_int_test. No force/deposit; all stimulus is JTAG2AXI MMIO.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
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
from seq_lib.smu_tb_pins import smc_primary_reset, tb_pin

WRITE_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR")
STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
WIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_BASE_ADDR")
IRQS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR")
IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")
IRQP = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQP_BASE_ADDR")
CTRL = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR")

ST_EMPTY = mailbox_u32("AXIL_MAILBOX__STATUS__EMPTY_bm")
ST_FULL = mailbox_u32("AXIL_MAILBOX__STATUS__FULL_bm")
ST_WTHRESH = mailbox_u32("AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm")
IRQ_WTIRQ = mailbox_u32("AXIL_MAILBOX__IRQS__WTIRQ_bm")
CTRL_WFLUSH = mailbox_u32("AXIL_MAILBOX__CTRL__WFLUSH_bm")

PUSH_WORD = 0xA5A5_A5A5
WIRQT_ABOVE_DEPTH = 0x5
J2A_POLL = 128
LANE_BOUND = 2000
WINDOW_SHORT = 64
WINDOW_TRACE = 256
MASK32 = 0xFFFF_FFFF
SC = {J2A_STATUS_SUCCESS: "SUCCESS"}


class smu_smc_mailbox_threshold_lane_test_seq:
    """Outbound mailbox 0 write-threshold interrupt lane."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.jtag = None
        self.j2a_count = 0
        self.j2a_last = "none"
        self.j2a_expired = False
        self.sites: list[tuple[str, str, str, str]] = []
        self.step_ts: dict[str, float] = {}

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    @staticmethod
    def _sample(signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    async def _j2a(self, write: bool, addr: int, data: int = 0) -> int:
        word = data & MASK32
        try:
            if write:
                status, raw = await jtag2axi_single_write(
                    self.jtag,
                    addr,
                    word,
                    wstrb=0x0F,
                    size=SMC_DBG_AXSIZE_4B,
                    poll_limit=J2A_POLL,
                    require_complete=True,
                )
            else:
                status, raw = await jtag2axi_single_read(
                    self.jtag,
                    addr,
                    size=SMC_DBG_AXSIZE_4B,
                    poll_limit=J2A_POLL,
                    require_complete=True,
                )
        except (TimeoutError, AssertionError) as exc:
            self.j2a_expired = True
            self.j2a_last = f"EXPIRED {exc}"
            raise
        require_jtag_tdo_resolved(f"MBX {'WR' if write else 'RD'} @0x{addr:08x}")
        self.j2a_count += 1
        self.j2a_last = f"status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A {'WR' if write else 'RD'} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(raw) & MASK32

    async def _wr(self, cell: str, addr: int, value: int) -> None:
        await self._j2a(True, addr, value)
        self._log(f"CELL {cell} addr=0x{addr:08x} status=SUCCESS value=0x{value:08x}")

    async def _rd(self, cell: str, addr: int) -> int:
        value = await self._j2a(False, addr)
        self._log(f"CELL {cell} addr=0x{addr:08x} status=SUCCESS value=0x{value:08x}")
        return value

    def _vector(self) -> int:
        return self._sample(self.dut.ext_mailbox_interrupts_o, "ext_mailbox_interrupts_o")

    async def _window(self, cell: str, edges: int) -> list[int]:
        out = []
        for _ in range(edges):
            await RisingEdge(self.dut.clk_smu_i)
            out.append(self._vector())
        self._log(
            f"CELL {cell} ext_mailbox_interrupts_o=0x{out[-1]:x} samples={len(out)} "
            f"lane0_high={sum(v & 1 for v in out)} nonzero={sum(1 for v in out if v)}"
        )
        return out

    async def _wait_lane(self, expect: int, site: str) -> bool:
        last = None
        for _ in range(LANE_BOUND):
            await RisingEdge(self.dut.clk_smu_i)
            last = self._vector() & 1
            if last == expect:
                self.sites.append((site, f"{LANE_BOUND} clk_smu_i edges", f"lane0={last}", "ok"))
                self._log(f"CELL {site} ext_mailbox_interrupts_o=0x{self._vector():x} samples=1")
                return True
        self.sites.append((site, f"{LANE_BOUND} clk_smu_i edges", f"lane0={last}", "EXPIRED"))
        self._log(f"TIMEOUT-PATH {site}: bound={LANE_BOUND} EXPIRED last={last}")
        raise AssertionError(
            f"TIMEOUT {site}: bound={LANE_BOUND} last_state={last} expect={expect}"
        )

    @staticmethod
    def _runs(samples: list[int]) -> list[tuple[int, int]]:
        runs: list[tuple[int, int]] = []
        for v in samples:
            if runs and runs[-1][0] == v:
                runs[-1] = (v, runs[-1][1] + 1)
            else:
                runs.append((v, 1))
        return runs

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        # S1 SETUP
        await self.cfg.reset_done.wait()
        self._mark("S1", "SETUP: reset_done, primary reset released, TAP reset, IDCODE, J2A gate")
        primary = smc_primary_reset(dut)
        last = None
        for _ in range(LANE_BOUND):
            last = self._sample(primary, "rst_primary_smc_clk_n_o")
            if last == 1:
                break
            await RisingEdge(dut.clk_smu_i)
        else:
            raise AssertionError(f"TIMEOUT s1_primary_release: bound={LANE_BOUND} last={last}")
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample(tb_pin(dut, "tb_smc_jtag2axi_security_disable"), "security_disable")
        if gate & 1:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")

        # S2 latch with the enable clear
        self._mark("S2", "push one word with IRQEN = 0; STATUS, IRQS, IRQP; 64 lane samples")
        await self._wr("irqen_wtirq_0.WRITE_DATA", WRITE_DATA, PUSH_WORD)
        status2 = await self._rd("irqen_wtirq_0.STATUS", STATUS)
        irqs2 = await self._rd("irqs_latched.IRQS", IRQS)
        irqp2 = await self._rd("irqp_gated.IRQP", IRQP)
        win2 = await self._window("lane_low", WINDOW_SHORT)
        sb.expect_eq(
            "CHK-MBX-WT-LATCH-GATED (status_bit2, irqs_bit0, nonzero_lane_samples)",
            ((status2 & ST_WTHRESH) >> 2, irqs2 & IRQ_WTIRQ, sum(1 for v in win2 if v)),
            (1, 1, 0),
            evidence="MBX_WT_LATCH_GATED",
        )
        sb.expect_eq("CHK-MBX-IRQP-GATING (IRQP, IRQEN = 0)", irqp2, 0, evidence="MBX_IRQP_GATING")

        # S3 enable
        self._mark("S3", "write IRQEN = 0x1, read IRQP, wait for lane 0 to rise")
        await self._wr("irqp_follows_enable.IRQEN", IRQEN, IRQ_WTIRQ)
        irqp3 = await self._rd("irqp_follows_enable.IRQP", IRQP)
        rose3 = await self._wait_lane(1, "S3_lane0_rise")
        sb.expect_eq(
            "CHK-MBX-IRQP-GATING (IRQP, lane_rose, IRQEN = 1)",
            (irqp3, rose3),
            (IRQ_WTIRQ, True),
            evidence="MBX_IRQP_GATING",
        )

        # S4 enable dropped with the word queued
        self._mark("S4", "write IRQEN = 0, wait for lane 0 to fall, read STATUS")
        await self._wr("enable_cleared_lane_drops.IRQEN", IRQEN, 0)
        fell4 = await self._wait_lane(0, "S4_lane0_fall")
        status4 = await self._rd("status_unchanged.STATUS", STATUS)
        sb.expect_eq(
            "CHK-MBX-WT-ENABLE-DROP (lane_fell, status_bit2)",
            (fell4, (status4 & ST_WTHRESH) >> 2),
            (True, 1),
            evidence="MBX_WT_ENABLE_DROP",
        )

        # S5 flush and acknowledge
        self._mark("S5", "IRQEN = 1, lane 0 rise, wflush, STATUS, IRQS, acknowledge, lane 0 fall")
        await self._wr("occupancy_removed.IRQEN", IRQEN, IRQ_WTIRQ)
        await self._wait_lane(1, "S5_lane0_rise")
        await self._wr("occupancy_removed.CTRL", CTRL, CTRL_WFLUSH)
        status5 = await self._rd("occupancy_removed.STATUS", STATUS)
        irqs5 = await self._rd("occupancy_removed.IRQS", IRQS)
        win5 = await self._window("lane_baseline.latched_lane_high", WINDOW_SHORT)
        await self._wr("irqs_ack_w1c.IRQS", IRQS, IRQ_WTIRQ)
        irqs5a = await self._rd("irqs_ack_w1c.IRQS_after_ack", IRQS)
        fell5 = await self._wait_lane(0, "S5_lane0_fall")
        status5a = await self._rd("status_baseline.STATUS", STATUS)
        sb.expect_eq(
            "CHK-MBX-WT-ACK-BASELINE (status_after_flush, irqs_bit0_after_flush, "
            "lane_high_samples, irqs_after_ack, lane_fell, status_after_ack)",
            (status5, irqs5 & IRQ_WTIRQ, sum(v & 1 for v in win5), irqs5a, fell5, status5a),
            (ST_EMPTY, 1, WINDOW_SHORT, 0, True, ST_EMPTY),
            evidence="MBX_WT_ACK_BASELINE",
        )

        # S6 WIRQT clamp
        self._mark("S6", "WIRQT = 5 (clamped to depth - 1), one word, then a second word")
        await self._wr("wirqt_clamped_1.WIRQT", WIRQT, WIRQT_ABOVE_DEPTH)
        await self._wr("one_word_no_irq.WRITE_DATA", WRITE_DATA, PUSH_WORD)
        win6 = await self._window("one_word_no_irq", WINDOW_SHORT)
        status6a = await self._rd("one_word_no_irq.STATUS", STATUS)
        irqs6a = await self._rd("one_word_no_irq.IRQS", IRQS)
        await self._wr("two_words_irq.WRITE_DATA", WRITE_DATA, PUSH_WORD)
        rose6 = await self._wait_lane(1, "S6_lane0_rise")
        status6b = await self._rd("two_words_irq.STATUS", STATUS)
        sb.expect_eq(
            "CHK-MBX-WT-CLAMP (lane_high_after_one, status_bit2_one, irqs_bit0_one, "
            "lane_rose_after_two, status_full_two, status_bit2_two)",
            (
                sum(v & 1 for v in win6),
                (status6a & ST_WTHRESH) >> 2,
                irqs6a & IRQ_WTIRQ,
                rose6,
                (status6b & ST_FULL) >> 1,
                (status6b & ST_WTHRESH) >> 2,
            ),
            (0, 0, 0, True, 1, 1),
            evidence="MBX_WT_CLAMP",
        )

        # S7 acknowledge while the condition holds (observe only)
        self._mark("S7", "acknowledge IRQS with two words queued; 256-sample lane trace")
        await self._wr("ack_while_condition_true.IRQS_ack", IRQS, IRQ_WTIRQ)
        trace = await self._window("ack_while_condition_true.trace", WINDOW_TRACE)
        irqs7a = await self._rd("ack_while_condition_true.IRQS_1", IRQS)
        irqs7b = await self._rd("ack_while_condition_true.IRQS_2", IRQS)
        status7 = await self._rd("ack_while_condition_true.STATUS", STATUS)
        runs = [(v & 1, n) for v, n in self._runs([t & 1 for t in trace])]
        self._log(
            f"CHK-MBX-WT-REASSERT-LOG: irqs_1=0x{irqs7a:x} irqs_2=0x{irqs7b:x} "
            f"lane_runs={runs} (LINKED-ISSUE, owner value pending, never compared)"
        )
        sb.expect_eq(
            "CHK-MBX-WT-REASSERT-LOG (status_bit2)",
            (status7 & ST_WTHRESH) >> 2,
            1,
            evidence="MBX_WT_REASSERT_LOG",
        )

        # S8 clean-up
        self._mark("S8", "wflush, acknowledge, IRQEN = 0, WIRQT = 0, read STATUS")
        await self._wr("checked_cleared.CTRL", CTRL, CTRL_WFLUSH)
        await self._wr("checked_cleared.IRQS", IRQS, IRQ_WTIRQ)
        await self._wr("checked_cleared.IRQEN", IRQEN, 0)
        await self._wr("checked_cleared.WIRQT", WIRQT, 0)
        status8 = await self._rd("checked_cleared.STATUS", STATUS)
        await RisingEdge(dut.clk_smu_i)
        lane8 = self._vector() & 1
        self._log(f"CELL checked_cleared ext_mailbox_interrupts_o=0x{self._vector():x} samples=1")
        sb.expect_eq(
            "CHK-MBX-WT-CLAMP checked_cleared (STATUS, lane0)",
            (status8, lane8),
            (ST_EMPTY, 0),
            evidence="MBX_WT_CLAMP",
        )

        # S9 timeout inventory
        self._mark("S9", "TIMEOUT: bounded waits with last state")
        self.sites.insert(
            0,
            (
                "j2a",
                f"{J2A_POLL} polls x {self.j2a_count} accesses",
                self.j2a_last,
                "EXPIRED" if self.j2a_expired else "ok",
            ),
        )
        for site, bound, last_state, outcome in self.sites:
            self._log(f"TIMEOUT-PATH {site}: bound={bound} {outcome} last={last_state}")
        expired = sum(1 for s in self.sites if s[3] != "ok")
        names = [s[0] for s in self.sites]
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={names} expired={expired} j2a_accesses={self.j2a_count}"
        )
        sb.expect_eq("CHK-TIMEOUT-PATHS expired", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS sites",
            names,
            [
                "j2a",
                "S3_lane0_rise",
                "S4_lane0_fall",
                "S5_lane0_rise",
                "S5_lane0_fall",
                "S6_lane0_rise",
            ],
        )

        await ClockCycles(dut.clk_smu_i, 32)
        self.step_ts["PASS"] = time.monotonic()

        order = [f"S{i}" for i in range(1, 10)] + ["PASS"]
        for step in order:
            if step not in self.step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step}")
        advancing = sum(1 for a, b in zip(order, order[1:]) if self.step_ts[b] >= self.step_ts[a])
        self._log(f"CHK-NONVAC: Ordered fence {'<'.join(order)} advancing={advancing}")
        sb.expect_eq(
            "CHK-NONVAC ordered step count", advancing, len(order) - 1, evidence="CHK-NONVAC"
        )
