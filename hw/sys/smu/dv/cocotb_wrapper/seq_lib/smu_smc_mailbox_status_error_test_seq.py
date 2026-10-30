# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_mailbox_status_error_test.

Spec: axil_mailbox.rdl (STATUS, ERROR_FLAGS, IRQS, IRQEN, IRQP, CTRL); axil_mailbox_smc_wrap.rdl;
  smc.rdl smc_mailbox; interface.adoc Access Results; architecture.adoc IRQ model; periphs.adoc
  MailboxDepth = 2.

Outbound mailbox 0 over the SMC fabric JTAG2AXI bridge: STATUS live flags against FIFO occupancy,
the empty-read and full-write SLVERR responses with their error flags, ERROR_FLAGS clear on read,
the error interrupt enable and acknowledge on lane 0 of smc_ext_mailbox_interrupts_o, and SLVERR
on writes to STATUS, READ_DATA, ERROR_FLAGS and IRQP. The lane-n = mailbox-n mapping is proven by
smu_smc_mailbox_int_test. The three push words are drawn from the seed; STATUS is read after
each of the first two pushes, so both levels are read in every run. After the full-write
error the two pushed words are read back through the pair-0 inbound aperture's READ_DATA
(architecture.adoc, Paired FIFOs: within a pair the inbound aperture reads the FIFO the
outbound aperture writes) and compared, a third read answers the empty-read SLVERR with
0xFEEDDEAD, so the refused third word was not enqueued, then the two words are pushed again
and STATUS read full, so the flush later discards a full FIFO; the third word's value is
printed.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import mailbox_u32, smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset, tb_pin

WRITE_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR")
READ_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR")
STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_BASE_ADDR")
IRQS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR")
IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")
IRQP = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQP_BASE_ADDR")
CTRL = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR")
# The inbound aperture of pair 0 reads the FIFO the outbound aperture writes.
INBOUND_READ_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_READ_DATA_BASE_ADDR")

ST_EMPTY = mailbox_u32("AXIL_MAILBOX__STATUS__EMPTY_bm")
ST_FULL = mailbox_u32("AXIL_MAILBOX__STATUS__FULL_bm")
ST_WTHRESH = mailbox_u32("AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm")
IRQ_EIRQ = mailbox_u32("AXIL_MAILBOX__IRQS__EIRQ_bm")

EMPTY_READ_DATA = 0xFEED_DEAD
FIFO_DEPTH = 2
J2A_POLL = 128
LANE_BOUND = 2000
MASK32 = 0xFFFF_FFFF
SC = {J2A_STATUS_SUCCESS: "SUCCESS", J2A_STATUS_SLVERR: "SLVERR"}


class smu_smc_mailbox_status_error_test_seq:
    """Outbound mailbox 0 STATUS and access-error behaviour."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.jtag = None
        self.j2a_count = 0
        self.j2a_last = "none"
        self.j2a_expired = False
        self.sites: list[tuple[str, str, str, str]] = []
        self.seed = test.random_seed()
        self.rng = random.Random(self.seed)
        self.words = [self.rng.getrandbits(32) for _ in range(FIFO_DEPTH + 1)]
        self.drawn = f"drawn words={[f'0x{w:08x}' for w in self.words]}"

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    @staticmethod
    def _sample(signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    async def _j2a(self, write: bool, addr: int, data: int = 0) -> tuple[int, int]:
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
        return status, int(raw) & MASK32

    async def _wr(self, cell: str, addr: int, value: int) -> int:
        status, _ = await self._j2a(True, addr, value)
        self._log(
            f"CELL {cell} addr=0x{addr:08x} status={SC.get(status, status)} value=0x{value:08x}"
        )
        return status

    async def _rd(self, cell: str, addr: int) -> tuple[int, int]:
        status, value = await self._j2a(False, addr)
        self._log(
            f"CELL {cell} addr=0x{addr:08x} status={SC.get(status, status)} value=0x{value:08x}"
        )
        return status, value

    async def _wait_lane(self, expect: int, site: str) -> bool:
        clk = self.dut.clk_smu_i
        lane = self.dut.ext_mailbox_interrupts_o
        last = None
        for _ in range(LANE_BOUND):
            await RisingEdge(clk)
            last = self._sample(lane, "ext_mailbox_interrupts_o") & 1
            if last == expect:
                self.sites.append((site, f"{LANE_BOUND} clk_smu_i edges", f"lane0={last}", "ok"))
                return True
        self.sites.append((site, f"{LANE_BOUND} clk_smu_i edges", f"lane0={last}", "EXPIRED"))
        self._log(f"TIMEOUT-PATH {site}: bound={LANE_BOUND} EXPIRED last={last}")
        raise AssertionError(
            f"TIMEOUT {site}: bound={LANE_BOUND} last_state={last} expect={expect}"
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        # S1 SETUP
        self._log(f"SEED: RANDOM_SEED={self.seed} {self.drawn}")
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

        # S2 empty read
        self._mark("S2", "read READ_DATA while empty, ERROR_FLAGS, IRQS")
        st_rd, rd_data = await self._rd("read_while_empty.READ_DATA", READ_DATA)
        _, err = await self._rd("read_while_empty.ERROR_FLAGS", ERROR_FLAGS)
        _, irqs = await self._rd("read_while_empty.IRQS", IRQS)
        sb.expect_eq(
            "CHK-MBX-ERR-READ-EMPTY (status, data, error_flags, irqs_eirq)",
            (st_rd, rd_data, err, (irqs & IRQ_EIRQ) != 0),
            (J2A_STATUS_SLVERR, EMPTY_READ_DATA, 0x1, True),
            evidence="MBX_ERR_READ_EMPTY",
        )

        # S3, S4: the first two drawn words, STATUS read after each push
        levels = []
        for n, word in enumerate(self.words[:FIFO_DEPTH], 1):
            cell = "one_word_status" if n == 1 else "two_words_full"
            self._mark(f"S{n + 2}", f"push {n}: write WRITE_DATA = 0x{word:08x}, read STATUS")
            levels.append(await self._wr(f"{cell}.WRITE_DATA", WRITE_DATA, word))
            levels.append((await self._rd(f"{cell}.STATUS", STATUS))[1])
        sb.expect_eq(
            f"CHK-MBX-STATUS-LEVELS (push1 status, STATUS, push2 status, STATUS) {self.drawn}",
            tuple(levels),
            (
                J2A_STATUS_SUCCESS,
                ST_EMPTY | ST_WTHRESH,
                J2A_STATUS_SUCCESS,
                ST_EMPTY | ST_FULL | ST_WTHRESH,
            ),
            evidence="MBX_STATUS_LEVELS",
        )

        # S5 write to full
        self._mark("S5", f"write WRITE_DATA = 0x{self.words[FIFO_DEPTH]:08x} to the full FIFO")
        st_w3 = await self._wr("write_while_full.WRITE_DATA", WRITE_DATA, self.words[FIFO_DEPTH])
        _, err5 = await self._rd("write_while_full.ERROR_FLAGS", ERROR_FLAGS)
        _, irqs5 = await self._rd("write_while_full.IRQS", IRQS)
        _, status5 = await self._rd("write_while_full.STATUS", STATUS)
        sb.expect_eq(
            f"CHK-MBX-ERR-WRITE-FULL (status, error_flags, irqs_eirq, STATUS) {self.drawn}",
            (st_w3, err5, (irqs5 & IRQ_EIRQ) != 0, status5),
            (J2A_STATUS_SLVERR, 0x2, True, ST_EMPTY | ST_FULL | ST_WTHRESH),
            evidence="MBX_ERR_WRITE_FULL",
        )

        # S6 the pushed words through the inbound aperture, the empty read, then the refill
        self._mark("S6", "read inbound READ_DATA three times: the pushed words, then empty; refill")
        back = []
        for n in (1, 2, 3):
            back.extend(await self._rd(f"inbound_readback.READ_DATA_{n}", INBOUND_READ_DATA))
        # The third read meets a drained FIFO; its answer is the empty-read result of
        # interface.adoc, Access Results.
        refill = []
        for n, word in enumerate(self.words[:FIFO_DEPTH], 1):
            refill.append(await self._wr(f"refill.WRITE_DATA_{n}", WRITE_DATA, word))
        _, status6 = await self._rd("refill.STATUS", STATUS)
        sb.expect_eq(
            f"CHK-MBX-STATUS-LEVELS (inbound READ_DATA status, word, status, word, status, "
            f"data; refill status 1, 2; STATUS) {self.drawn}",
            (*back, *refill, status6),
            (
                J2A_STATUS_SUCCESS,
                self.words[0],
                J2A_STATUS_SUCCESS,
                self.words[1],
                J2A_STATUS_SLVERR,
                EMPTY_READ_DATA,
                J2A_STATUS_SUCCESS,
                J2A_STATUS_SUCCESS,
                ST_EMPTY | ST_FULL | ST_WTHRESH,
            ),
            evidence="MBX_STATUS_LEVELS",
        )

        # S7 clear on read
        self._mark("S7", "read ERROR_FLAGS a second time, read IRQS")
        _, err6 = await self._rd("error_flags_read_clears.ERROR_FLAGS", ERROR_FLAGS)
        _, irqs6 = await self._rd("error_flags_read_clears.IRQS", IRQS)
        sb.expect_eq(
            "CHK-MBX-ERR-CLEAR-ON-READ (error_flags, irqs_eirq)",
            (err6, (irqs6 & IRQ_EIRQ) != 0),
            (0, True),
            evidence="MBX_ERR_CLEAR_ON_READ",
        )

        # S8 error IRQ enable and acknowledge
        self._mark("S8", "write IRQEN = 0x4, lane 0 rise, acknowledge IRQS, lane 0 fall")
        await self._wr("error_irq_ack_lane_drops.IRQEN", IRQEN, IRQ_EIRQ)
        _, irqp = await self._rd("error_irq_ack_lane_drops.IRQP", IRQP)
        rose = await self._wait_lane(1, "S8_lane0_rise")
        await self._wr("error_irq_ack_lane_drops.IRQS_ack", IRQS, IRQ_EIRQ)
        _, irqs7 = await self._rd("error_irq_ack_lane_drops.IRQS", IRQS)
        fell = await self._wait_lane(0, "S8_lane0_fall")
        sb.expect_eq(
            "CHK-MBX-ERR-IRQ-ACK (irqp_bit2, lane_rose, irqs_eirq_after, lane_fell)",
            ((irqp >> 2) & 1, rose, (irqs7 & IRQ_EIRQ) != 0, fell),
            (1, True, False, True),
            evidence="MBX_ERR_IRQ_ACK",
        )

        # S9 flush
        self._mark("S9", "write CTRL = 0x1 (wflush), read STATUS, read IRQS")
        await self._wr("flush_status_0x1_irqs_latched.CTRL", CTRL, 0x1)
        _, status8 = await self._rd("flush_status_0x1_irqs_latched.STATUS", STATUS)
        _, irqs8 = await self._rd("flush_status_0x1_irqs_latched.IRQS", IRQS)
        sb.expect_eq(
            "CHK-MBX-STATUS-FLUSH (STATUS, irqs_bit0)",
            (status8, irqs8 & 1),
            (ST_EMPTY, 1),
            evidence="MBX_STATUS_FLUSH",
        )

        # S10 write STATUS
        self._mark("S10", "write STATUS = 0xF, read STATUS")
        st9 = await self._wr("status_write_slverr.STATUS", STATUS, 0xF)
        _, status9 = await self._rd("status_write_slverr.STATUS_rb", STATUS)

        # S11 other read-only writes
        self._mark("S11", "write READ_DATA, ERROR_FLAGS, IRQP; read ERROR_FLAGS, IRQP")
        st10a = await self._wr("ro_writes_slverr.READ_DATA", READ_DATA, 0x1)
        st10b = await self._wr("ro_writes_slverr.ERROR_FLAGS", ERROR_FLAGS, 0x3)
        st10c = await self._wr("ro_writes_slverr.IRQP", IRQP, 0x7)
        _, err10 = await self._rd("no_flag_changed.ERROR_FLAGS", ERROR_FLAGS)
        _, irqp10 = await self._rd("no_flag_changed.IRQP", IRQP)
        sb.expect_eq(
            "CHK-MBX-RO-WRITES (STATUS wr, STATUS, READ_DATA wr, ERROR_FLAGS wr, IRQP wr, "
            "ERROR_FLAGS, IRQP)",
            (st9, status9, st10a, st10b, st10c, err10, irqp10),
            (
                J2A_STATUS_SLVERR,
                ST_EMPTY,
                J2A_STATUS_SLVERR,
                J2A_STATUS_SLVERR,
                J2A_STATUS_SLVERR,
                0,
                0,
            ),
            evidence="MBX_RO_WRITES",
        )

        # S12 timeout inventory
        self._mark("S12", "TIMEOUT: bounded waits with last state")
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
            ["j2a", "S8_lane0_rise", "S8_lane0_fall"],
        )
        sb.expect_eq("CHK-TIMEOUT-PATHS j2a accesses", self.j2a_count, 33)

        # final state
        lane0 = self._sample(dut.ext_mailbox_interrupts_o, "ext_mailbox_interrupts_o") & 1
        self._log(f"CELL final irqen=0x{IRQ_EIRQ:x} irqs=0x{irqs8:x} lane0={lane0}")
        await ClockCycles(dut.clk_smu_i, 32)
