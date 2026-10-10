# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OT SPI host CSRs, interrupts, error bits, watermark and enable follow the spi_host spec.

OCAH provenance: ``spi_ot_reg``, ``tx_fifo``, ``cmd_queue``, ``interrupt``,
``error_handling``, ``watermark`` and ``enable_disable`` check the SPI-host
control plane.

A combined-per-group `[RAND-REP]` for the OT SPI host control plane: register R/W,
TX FIFO, command queue, interrupts, error handling, watermark and enable/disable.
Not covered, because nothing here checks them: the clock configuration (CFG.CLKDIV
is R/W-walked but no transfer runs at a programmed divider) and the RX FIFO (the
only RX touch is the empty-FIFO read that triggers UNDERFLOW). Drives the upstream
OpenTitan spi_host CSRs (@0x10B0_0000, NUM_CS=1) directly over the CPU-LSU AXI splice
(no_cpu, no firmware, no flash BFM).
This is the host control plane, distinct from `sep_spi_ot_flash_cmd_rand_test`
(flash command datapath) and `sep_spi_ot_dma_rx_test` (flash READ + DMA).

Randomization (single source of randomness): SepSpiHostCfg seeds
legal field values for the register R/W walk + two watermark thresholds from the
runner seed, one from 2-4 and one from 5-8, in seeded order, each with its own
fill depth. CHK-WATERMARK grades both on every seed. The golden is the documented
reset values + RW/W1C/RO field semantics
(seq_lib/sep_spi_host_csr_seq.py, taken from the generated spi_controller reg
block, which reggen derives from upstream spi_host.hjson).

Checks (each emits a positive CHK-X PASS line; assert fails the test on a bad DUT):
  CHK-RESET     : every control/status reg reads its documented reset value.
  CHK-REG-RW    : each RW reg write->readback exact; bits outside the writable
                  mask (RO/reserved) read 0.
  CHK-INTR      : INTR_STATE.ERROR is an Event latch -- INTR_TEST sets it with
                  INTR_ENABLE clear (the enable gates only the outgoing line),
                  a write of 0 to INTR_TEST does not clear it, and W1C does.
                  INTR_STATE.SPI_EVENT is Status-type and tracks the INTR_TEST
                  force level instead. INTR_ENABLE raises and drops
                  sep_internal_interrupts[13] (PIC source 14) for both sources.
  CHK-ERR-W1C   : each drivable ERROR_STATUS bit is set by its exact trigger and
                  W1C-clears -- UNDERFLOW (read empty RXDATA), CMDINVAL (COMMAND
                  SPEED=reserved), CSIDINVAL (CSID at the top of the field, out of
                  range for any NumCS, + COMMAND), OVERFLOW (fill until the DUT
                  reports STATUS.TXFULL with the core disabled, then one beat more),
                  CMDBUSY (queue until STATUS.READY drops, then one command more).
                  ACCESSINVAL is not claimed: the RDL defines it as a TXDATA write
                  with no bytes enabled, which neither this AXI master nor the
                  wrapper's bridge can present to the core.
  CHK-WATERMARK : STATUS.TXWM moves as the TX FIFO occupancy crosses TX_WATERMARK
                  (occupancy proven by STATUS.TXQD), for one threshold from
                  each half of the draw range.
  CHK-ENABLE    : SPIEN=0 with OUTPUT_EN=1 holds a queued TX command off (FIFO
                  not drained); setting SPIEN alone lets it execute (FIFO drains).
  CHK-NONVAC    : every walked reg reads back different from its observed pre-write
                  value, so no entry in the walk is a no-op against a tied-off decode.
  CHK-ZERO-STRB : a 64-bit beat that enables only the CONTROL half returns OKAY,
                  lands that write, and leaves ERROR_STATUS clear. The empty
                  STATUS half is the neighbour the 64-to-32 downsizer would
                  present as WSTRB==0; the wrapper acks that beat locally.

RXWM is covered by the RX-path tests (`sep_spi_ot_flash_cmd_rand_test` /
`sep_spi_ot_dma_rx_test`).

The checks above run first, with the graded FCOV window closed. Four legs follow
that grade only the cells the checks above do not grade, against
``vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/gen/adoc/spi_controller.adoc``,
``hw/sys/sep/doc/spi.adoc`` (Features) and ``hw/sys/sep/doc/interrupts.adoc``
(PIC source 14 is ``sep_internal_interrupts_probe_o`` index 13). The legs start
from the SPI clean state with CONTROL SPIEN=1 OUTPUT_EN=1, CONFIGOPTS CLKDIV 1
and CSID 0, and read the pads through ``env/sep_spi_pad_sampler.py``.

  L1 CHK-SPI-EVENT  : INTR_STATE.SPI_EVENT equals the OR of the levels of the
                      sources that EVENT_ENABLE selects (TXEMPTY, TXWM, RXFULL,
                      RXWM in two passes over five FIFO states; the
                      TXEMPTY-only, RXFULL-only, IDLE and READY sequences), and
                      0 after the mask step. STATUS must show the levels the
                      stimulus names, else CTRL-MISSING.
  L1 CHK-SPI-LINE   : PIC source 14 equals (SPI_EVENT and INTR_ENABLE.SPI_EVENT)
                      or (ERROR and INTR_ENABLE.ERROR) at each state read, with
                      a twin sample at INTR_ENABLE=3, and on the 16-cell line
                      walk. The five walk cells that the checks above grade log
                      CTL-SPI-LINE and fail the leaf on a mismatch.
  L2 CHK-SPI-ERR-KIND : each of the five error kinds sets INTR_STATE.ERROR, which
                      survives the ERROR_STATUS clear and clears on its own W1C.
  L2 CHK-SPI-CSID-RANGE : a COMMAND at a drawn CSID from 2 to 0xFFFFFFFE sets
                      ERROR_STATUS to CSIDINVAL alone; CSID=1 is logged only
                      (OBS-SPI-CSID1).
  L2 CHK-SPI-ERR-MASK : accumulated kinds OR into ERROR_STATUS, a drawn W1C mask
                      clears only its bits and a write of 0 clears nothing. A
                      kind injected with its ERROR_ENABLE bit clear is logged
                      only (OBS-SPI-MASK).
  L2 CHK-SPI-CMDBUSY0 : a COMMAND written while READY=0 and ACTIVE=0 (SPIEN=0)
                      sets CMDBUSY.
  L3 CHK-SPI-STRB   : an 8-byte write with strobe 0x0F, 0xF0 or 0xFF at the
                      pairs 0x00, 0x18, 0x28 and 0x30 returns OKAY, lands the
                      strobed half by its register type and keeps the other
                      half. ACCESSINVAL is logged only (OBS-SPI-STRB-ACCESSINVAL).
  L3 CHK-SPI-STRB-TX: the TXDATA half queues one word only when strobed.
  L3 CHK-SPI-STRB-CTRL : strobe 0xFF changes both halves of each pair.
  L4 CHK-SPI-SWRST  : SW_RST written at a drawn sck cycle of a Tx segment reads
                      back 1, empties both FIFOs and the core, keeps the
                      registers, and a clean command then runs.
  L4 CHK-SPI-SPIEN  : SPIEN=0 holds 1 to 3 queued commands off the pads for
                      4*T clocks; SPIEN=1 runs them in order.

Run mode: no_cpu with +skip_fuse_sense. The graded window carries this test's
code during the four legs only; it is closed during the checks above, the
control cells and the logged-only injections. RANDCFG and RAND-REP draws of the
legs come from ``SepSeededRng`` and the run seed and are logged on the PLAN and
DRAW lines.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_reg_meta import SPI_CONTROLLER
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import agg_from_pic
from env.sep_spi_pad_sampler import SepSpiPadSampler
from sep_base_test import sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    CMD_DIR_TX,
    CMD_SPEED_RESERVED,
    COMMAND,
    CONFIGOPTS,
    CONTROL,
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_RESET,
    CTRL_RX_WM,
    CTRL_SPIEN,
    CTRL_SW_RST,
    CTRL_TX_WM_LSB,
    ERR_ACCESSINVAL,
    ERR_CMDBUSY,
    ERR_CMDINVAL,
    ERR_CSIDINVAL,
    ERR_OVERFLOW,
    ERR_STATUS_MASK,
    ERR_UNDERFLOW,
    ERROR_ENABLE,
    ERROR_STATUS,
    EVENT_ENABLE,
    INTR_ENABLE,
    INTR_ERROR,
    INTR_SPI_EVENT,
    INTR_STATE,
    INTR_STATE_MASK,
    INTR_TEST,
    RESET_VALUES,
    RXDATA,
    ST_ACTIVE,
    ST_CMDQD,
    ST_READY,
    ST_RXEMPTY,
    ST_RXFULL,
    ST_RXQD,
    ST_TXEMPTY,
    ST_TXFULL,
    ST_TXQD,
    ST_TXWM,
    STATUS,
    TXDATA,
    SepSpiHost,
    SepSpiHostCfg,
)
from seq_lib.sep_spi_host_ops import (
    DIR_DUMMY,
    DIR_RX,
    DIR_TX,
    EVT_IDLE,
    EVT_READY,
    EVT_RXFULL,
    EVT_RXWM,
    EVT_TXEMPTY,
    EVT_TXWM,
    SepSpiHostOps,
    SpiStatus,
    command_word,
    configopts_word,
)

# Bounded-wait budgets. Every one of these fails its own checker on expiry.
# CHK-ENABLE's negative window is not a constant: it is _NEG_WINDOW_MARGIN times
# the drain latency the enabled leg measures on this build, floored at
# _NEG_WINDOW_FLOOR so a 1-poll calibration cannot shrink it to a window a merely
# slow device would survive.
_DRAIN_POLLS = 200
_ENABLED_POLLS = 2000
_NEG_WINDOW_MARGIN = 4
_NEG_WINDOW_FLOOR = 32
# Runaway guards for the two error triggers that fill until the DUT reports its
# own boundary (STATUS.TXFULL / STATUS.READY). They are loop bounds, not expected
# depths: reaching either fails the checker rather than passing it.
_FILL_LIMIT = 512
_CMD_LIMIT = 64
_SPI_AGG = agg_from_pic("SPI IRQ")

# ---- Legs L1 to L4 -----------------------------------------------------------
TEST = "sep_spi_ot_host_csr_irq_rand_test"
_R = SPI_CONTROLLER
_LEG_CHECKS = (
    "CHK-SPI-EVENT",
    "CHK-SPI-LINE",
    "CHK-SPI-ERR-KIND",
    "CHK-SPI-CSID-RANGE",
    "CHK-SPI-ERR-MASK",
    "CHK-SPI-CMDBUSY0",
    "CHK-SPI-STRB",
    "CHK-SPI-STRB-TX",
    "CHK-SPI-STRB-CTRL",
    "CHK-SPI-SWRST",
    "CHK-SPI-SPIEN",
)
_OPEN_CHECKS = 8
# Separates the leg stream from the SepSpiHostCfg stream of the same seed.
_LEG_SALT = 0x5350_4931
_CTRL_BASE = CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN
_CTRL_TX_WM_LSB = _R.field_lsb("CONTROL", "tx_watermark")
_CTRL_RX_WM_LSB = _R.field_lsb("CONTROL", "rx_watermark")
_CTRL_RX_WM_RESET = (CTRL_RESET & _R.field_mask("CONTROL", "rx_watermark")) >> _CTRL_RX_WM_LSB
_ERR_EN_ALL = _R.reset32("ERROR_ENABLE")
_CFG_BASE = configopts_word(clkdiv=1)
_SPEED_RESERVED = 3
_CMD_DUMMY = command_word(0, direction=DIR_DUMMY)

# Event sources: EVENT_ENABLE bit and the STATUS level (spi_controller.adoc).
_EVT = {
    "TXEMPTY": EVT_TXEMPTY,
    "TXWM": EVT_TXWM,
    "RXFULL": EVT_RXFULL,
    "RXWM": EVT_RXWM,
    "IDLE": EVT_IDLE,
    "READY": EVT_READY,
}
_LEVEL = {
    "TXEMPTY": lambda s: s.txempty,
    "TXWM": lambda s: s.txwm,
    "RXFULL": lambda s: s.rxfull,
    "RXWM": lambda s: s.rxwm,
    "IDLE": lambda s: 1 - s.active,
    "READY": lambda s: s.ready,
}
_FIFO_SRCS = ("TXEMPTY", "TXWM", "RXFULL", "RXWM")
_EV_FIFO_ALL = EVT_TXEMPTY | EVT_TXWM | EVT_RXFULL | EVT_RXWM
# L1 FIFO states: TX_WATERMARK, RX_WATERMARK, TX words, Rx segment bytes and the
# levels of TXEMPTY, TXWM, RXFULL and RXWM that STATUS must show.
_L1_STATES = {
    "F": (1, 2, 2, 0, (0, 0, 0, 0)),
    "T1": (0, 2, 0, 0, (1, 0, 0, 0)),
    "T2": (2, 2, 1, 0, (0, 1, 0, 0)),
    "T3": (0, 2, 1, 12, (0, 0, 0, 1)),
    "T4": (2, 2, 0, 0, (1, 1, 0, 0)),
}
_RXFULL_SEG_BYTES = 1032
# The line walk: (state, stimulus, SPI_EVENT, ERROR). "none" ends the walk again.
_WALK = (("none", 0, 0), ("error", 0, 1), ("both", 1, 1), ("event", 1, 0), ("none", 0, 0))

# Error kinds: own ERROR_STATUS bit (spi_controller.adoc, ERROR_STATUS).
_KIND_BIT = {
    "CSIDINVAL": ERR_CSIDINVAL,
    "CMDINVAL": ERR_CMDINVAL,
    "UNDERFLOW": ERR_UNDERFLOW,
    "OVERFLOW": ERR_OVERFLOW,
    "CMDBUSY": ERR_CMDBUSY,
}
_CMD_KINDS = ("CSIDINVAL", "CMDINVAL", "CMDBUSY")

# L3 pairs: offset -> (low register, high register). Each entry: (name, address,
# compare mask, write-one-to-clear).
_STRB_PAIRS = {
    0x00: (
        ("INTR_STATE", INTR_STATE, INTR_ERROR, True),
        ("INTR_ENABLE", INTR_ENABLE, _R.mask32("INTR_ENABLE"), False),
    ),
    0x18: (
        ("CONFIGOPTS", CONFIGOPTS, _R.mask32("CONFIGOPTS"), False),
        ("CSID", CSID, _R.mask32("CSID"), False),
    ),
    0x28: (
        ("TXDATA", TXDATA, 0, False),
        ("ERROR_ENABLE", ERROR_ENABLE, _R.mask32("ERROR_ENABLE"), False),
    ),
    0x30: (
        ("ERROR_STATUS", ERROR_STATUS, ERR_STATUS_MASK, True),
        ("EVENT_ENABLE", EVENT_ENABLE, _R.mask32("EVENT_ENABLE"), False),
    ),
}
_STROBES = (0x0F, 0xF0, 0xFF)
_SPI_BASE = INTR_STATE

# L4 Tx segment of the SW_RST point, in 32-bit words (8 sck cycles per byte).
_SWRST_SEG_WORDS = 4

# Bounds: STATUS or register reads, accepted COMMAND writes and clk_i cycles.
_POLL_READS = 64
_READY_ACCEPT_LIMIT = 16
_SEG_BOUND_CLKS = 400_000
_RX_DRAIN_READS = 4_000


@pyuvm.test()
class sep_spi_ot_host_csr_irq_rand_test(sep_base_test):
    """Each control-plane CHK (CSR, IRQ, error, watermark, enable) holds on the OT SPI host."""

    required_evidence = (
        "CHK-RESET",
        "CHK-REG-RW",
        "CHK-NONVAC",
        "CHK-ZERO-STRB",
        "CHK-INTR",
        "CHK-ERR-W1C",
        "CHK-WATERMARK",
        "CHK-ENABLE",
        *_LEG_CHECKS,
    )

    async def run_scenario(self) -> None:
        self.scfg = SepSpiHostCfg(self.random_seed())
        self.spi = SepSpiHost(self)
        self.logger.info("SPI host CSR config: %s", self.scfg.summary())

        await self.bring_up_no_cpu()
        close_graded_window(self.logger)

        await self._chk_reset()
        await self._chk_reg_rw()
        await self._chk_zero_strb()
        await self._chk_intr()
        await self._chk_err_w1c()
        for half, wm, fill in self.scfg.tx_wm_reps:
            await self._chk_watermark(half, wm, fill)
        await self._chk_enable()
        self.logger.info("SPI host CSR/IRQ breadth ALL CHECKS PASS")
        await self._extension_legs()

    # ---- helpers ----------------------------------------------------------
    async def _sw_rst_pulse(self) -> None:
        """Hold the core soft-reset until both FIFOs drain, then release it.

        CONTROL.SW_RST is a level, and the RDL documents that SW_RST drains the
        CDC FIFOs rather than resetting them and that software must confirm both
        are empty before releasing the IP. Releasing early would make the
        occupancy assertions in the watermark and CMDBUSY facets read a depth
        this test did not create, and never releasing would leave the core held
        in reset for every facet below, so both edges are explicit here.
        """
        await self.spi.wr(CONTROL, CTRL_RESET | CTRL_SW_RST)
        drained = False
        for _ in range(_DRAIN_POLLS):
            st = await self.spi.rd(STATUS)
            if (st & ST_TXEMPTY) and (st & ST_RXEMPTY) and (st & (ST_TXQD | ST_RXQD)) == 0:
                drained = True
                break
        await self.spi.wr(CONTROL, CTRL_RESET)
        if not drained:
            raise AssertionError(
                f"SW_RST held but the FIFOs did not drain in {_DRAIN_POLLS} polls "
                f"(STATUS=0x{st:08x})"
            )

    async def _clear_error_status(self) -> None:
        await self.spi.wr(ERROR_STATUS, ERR_STATUS_MASK)  # W1C every defined bit

    # ---- CHK-RESET --------------------------------------------------------
    async def _chk_reset(self) -> None:
        for name, (addr, exp) in RESET_VALUES.items():
            got = await self.spi.rd(addr)
            assert got == exp, f"CHK-RESET {name}@0x{addr:08x} 0x{got:08x} != 0x{exp:08x}"
        # STATUS is RO/hw-driven: check the stable idle bits rather than a constant.
        st = await self.spi.rd(STATUS)
        assert st & ST_READY, f"CHK-RESET STATUS.READY not set: 0x{st:08x}"
        assert not (st & ST_ACTIVE), f"CHK-RESET STATUS.ACTIVE set: 0x{st:08x}"
        assert st & ST_TXEMPTY, f"CHK-RESET STATUS.TXEMPTY not set: 0x{st:08x}"
        assert st & ST_RXEMPTY, f"CHK-RESET STATUS.RXEMPTY not set: 0x{st:08x}"
        assert not (st & ST_TXFULL), f"CHK-RESET STATUS.TXFULL set: 0x{st:08x}"
        assert not (st & ST_RXFULL), f"CHK-RESET STATUS.RXFULL set: 0x{st:08x}"
        assert not (st & (ST_TXQD | ST_RXQD | ST_CMDQD)), (
            f"CHK-RESET STATUS queue depths nonzero: 0x{st:08x}"
        )
        self.logger.info(
            "CHK-RESET PASS: %d control regs at documented reset + STATUS idle (0x%08x)",
            len(RESET_VALUES),
            st,
        )

    # ---- CHK-REG-RW (+ CHK-NONVAC) ---------------------------------------
    async def _chk_reg_rw(self) -> None:
        for name, addr, wmask, impl_mask, val in self.scfg.rw_regs:
            # The baseline for CHK-NONVAC is the observed pre-write value, not the
            # reset table: the readback below is already asserted equal to the
            # written value, so a reset-table compare would grade the stimulus.
            pre = await self.spi.rd(addr)
            # Guarantee the write is observable. If the seeded value happens to
            # equal what the register already holds, flip its lowest writable bit,
            # so CHK-NONVAC grades the DUT for EVERY register on EVERY seed.
            target = val if val != pre else val ^ (wmask & -wmask)
            await self.spi.wr(addr, target)
            rb = await self.spi.rd(addr)
            assert rb == target, (
                f"CHK-REG-RW {name}@0x{addr:08x} readback 0x{rb:08x} "
                f"!= written 0x{target:08x} (wmask 0x{wmask:08x})"
            )
            assert rb != pre, (
                f"CHK-NONVAC {name}@0x{addr:08x} readback 0x{rb:08x} equals the "
                f"observed pre-write value -- the write changed nothing observable"
            )
            # Drive the bits the generated block does not implement and require
            # them to read back zero. The probe pattern is built from impl_mask,
            # not from wmask: CONTROL's SW_RST is implemented but outside the walk,
            # since driving it here would soft-reset the core mid-walk.
            probe = ~impl_mask & 0xFFFF_FFFF
            if probe:
                await self.spi.wr(addr, target | probe)
                rb2 = await self.spi.rd(addr)
                assert (rb2 & probe) == 0, (
                    f"CHK-REG-RW {name} unimplemented bits hold storage: 0x{rb2 & probe:08x}"
                )
                assert (rb2 & wmask) == target, (
                    f"CHK-REG-RW {name} writable bits disturbed by an "
                    f"unimplemented-bit write: 0x{rb2 & wmask:08x} != 0x{target:08x}"
                )
        self.logger.info(
            "CHK-REG-RW PASS: %d RW regs write->readback exact; unimplemented bits "
            "hold no storage and do not disturb the writable ones",
            len(self.scfg.rw_regs),
        )
        self.logger.info(
            "CHK-NONVAC PASS: all %d walked regs differ from their observed pre-write value",
            len(self.scfg.rw_regs),
        )
        # Restore every walked reg to its reset value for the later facets.
        for name, addr, _, _, _ in self.scfg.rw_regs:
            await self.spi.wr(addr, RESET_VALUES[name][1])

    # ---- CHK-ZERO-STRB ----------------------------------------------------
    async def _chk_zero_strb(self) -> None:
        # CONTROL sits at an 8-byte-aligned address; STATUS is the next word.
        # A 64-bit beat (AxSIZE=3) that carries only four payload bytes enables
        # the CONTROL half. The 64-to-32 downsizer then presents the STATUS
        # half with WSTRB==0. Without the wrapper ack that beat returns SLVERR
        # from the upstream register file.
        await self._clear_error_status()
        pre_ctrl = await self.spi.rd(CONTROL)
        written = CTRL_RESET | CTRL_OUTPUT_EN
        if written == pre_ctrl:
            written = CTRL_RESET
        await self.spi.wr(CONTROL, written, length=4, size=3)
        got = await self.spi.rd(CONTROL)
        assert got == written, (
            f"CHK-ZERO-STRB: CONTROL readback 0x{got:08x} != written 0x{written:08x} "
            f"-- the enabled half of the 64-bit beat did not land"
        )
        es = await self.spi.rd(ERROR_STATUS)
        assert es == 0, (
            f"CHK-ZERO-STRB: ERROR_STATUS 0x{es:08x} after the 64-bit beat "
            f"(ACCESSINVAL 0x{ERR_ACCESSINVAL:x} must stay clear)"
        )
        await self.spi.wr(CONTROL, CTRL_RESET)
        self.logger.info(
            "CHK-ZERO-STRB PASS: 64-bit CONTROL write with a 4-byte payload "
            "returned OKAY, landed 0x%08x, ERROR_STATUS stayed 0",
            written,
        )

    # ---- CHK-INTR ---------------------------------------------------------
    async def _chk_intr(self) -> None:
        # Graded against the upstream OpenTitan interrupt contract the SEP
        # inherits with the block. The two sources are deliberately different
        # types, so each gets the check its type states:
        #
        #   ERROR is Event-type. INTR_TEST.ERROR sets the INTR_STATE.ERROR
        #   latch; a write of 0 to INTR_TEST does not clear it and only a write
        #   of 1 back to INTR_STATE does. INTR_ENABLE gates the outgoing
        #   interrupt line, never the state bit, so the whole leg runs with the
        #   enable clear and the latch is still required to set.
        #
        #   SPI_EVENT is Status-type. INTR_STATE.SPI_EVENT is read-only and
        #   tracks its source level, with INTR_TEST holding a force that a write
        #   of 0 releases.
        #
        # The wrapper ORs the two core lines onto one SEP interrupt. That OR
        # is sampled on sep_internal_interrupts[13].
        #
        # EVENT_ENABLE and ERROR_STATUS are clean here, so INTR_TEST is the only
        # source either bit can have.
        await self._clear_error_status()
        await self.spi.wr(INTR_TEST, 0)
        await self.spi.wr(INTR_ENABLE, 0)
        await self.spi.wr(INTR_STATE, INTR_STATE_MASK)  # W1C the event latch
        st = await self.spi.rd(INTR_STATE)
        assert st == 0, f"CHK-INTR baseline: INTR_STATE 0x{st:08x} with every source clear"
        await self.poll_internal_irq(_SPI_AGG, 0)

        # ERROR: Event latch, set with the enable clear, cleared only by W1C.
        await self.spi.wr(INTR_TEST, INTR_ERROR)
        st = await self.spi.rd(INTR_STATE)
        assert st & INTR_ERROR, (
            f"CHK-INTR ERROR: INTR_TEST did not set the state latch while "
            f"INTR_ENABLE is clear -- the enable gates the line, not the state "
            f"(0x{st:08x})"
        )
        await self.poll_internal_irq(_SPI_AGG, 0)
        await self.spi.wr(INTR_TEST, 0)
        st = await self.spi.rd(INTR_STATE)
        assert st & INTR_ERROR, (
            f"CHK-INTR ERROR: the state latch followed INTR_TEST down instead of "
            f"holding until W1C (0x{st:08x})"
        )
        await self.spi.wr(INTR_ENABLE, INTR_ERROR)
        await self.poll_internal_irq(_SPI_AGG, 1)
        await self.spi.wr(INTR_STATE, INTR_ERROR)
        st = await self.spi.rd(INTR_STATE)
        assert not (st & INTR_ERROR), f"CHK-INTR ERROR: W1C did not clear the latch (0x{st:08x})"
        await self.poll_internal_irq(_SPI_AGG, 0)
        await self.spi.wr(INTR_ENABLE, 0)

        # SPI_EVENT: Status-type, read-only, follows the INTR_TEST force level.
        await self.spi.wr(INTR_TEST, INTR_SPI_EVENT)
        st = await self.spi.rd(INTR_STATE)
        assert st & INTR_SPI_EVENT, (
            f"CHK-INTR SPI_EVENT: INTR_TEST did not force the status bit (0x{st:08x})"
        )
        await self.poll_internal_irq(_SPI_AGG, 0)
        await self.spi.wr(INTR_ENABLE, INTR_SPI_EVENT)
        await self.poll_internal_irq(_SPI_AGG, 1)
        await self.spi.wr(INTR_TEST, 0)
        st = await self.spi.rd(INTR_STATE)
        assert not (st & INTR_SPI_EVENT), (
            f"CHK-INTR SPI_EVENT: releasing INTR_TEST left the status bit set "
            f"(0x{st:08x}) -- a status interrupt tracks its source level"
        )
        await self.poll_internal_irq(_SPI_AGG, 0)
        await self.spi.wr(INTR_ENABLE, 0)
        self.logger.info(
            "CHK-INTR PASS: INTR_STATE.ERROR latches on INTR_TEST with INTR_ENABLE "
            "clear and aggregator [%d] held off, holds across an INTR_TEST release, "
            "raises the aggregator only after INTR_ENABLE, and clears both on W1C; "
            "INTR_STATE.SPI_EVENT tracks the INTR_TEST force level and the same "
            "enable gate",
            _SPI_AGG,
        )

    # ---- CHK-ERR-W1C ------------------------------------------------------
    async def _trigger_err(self, label: str, bit: int, trigger) -> None:
        await self._clear_error_status()
        es = await self.spi.rd(ERROR_STATUS)
        assert es == 0, f"CHK-ERR-W1C {label}: ERROR_STATUS not clean pre-trigger (0x{es:08x})"
        await trigger()
        es = await self.spi.rd(ERROR_STATUS)
        assert es & bit, f"CHK-ERR-W1C {label}: bit 0x{bit:06x} not set (ERROR_STATUS 0x{es:08x})"
        # Exclusivity: the baseline above established ERROR_STATUS == 0, so this
        # trigger is the only thing that can have set a bit. Without it a DUT that
        # raises every error bit on any stimulus passes all five sub-checks.
        assert es == bit, (
            f"CHK-ERR-W1C {label}: trigger also set 0x{es & ~bit & 0xFFFF_FFFF:06x} "
            f"(ERROR_STATUS 0x{es:08x}, expected only 0x{bit:06x})"
        )
        await self.spi.wr(ERROR_STATUS, bit)  # W1C the exact bit
        es = await self.spi.rd(ERROR_STATUS)
        assert not (es & bit), f"CHK-ERR-W1C {label}: W1C did not clear (0x{es:08x})"

    async def _chk_err_w1c(self) -> None:
        async def trig_underflow():
            await self.spi.rd(RXDATA)  # read empty RX FIFO

        async def trig_cmdinval():
            await self.spi.wr(CSID, 0)
            await self.spi.wr(COMMAND, CMD_DIR_TX | CMD_SPEED_RESERVED)  # SPEED=reserved

        async def trig_csidinval():
            # CSID is a full 32-bit field and the RDL fixes no NumCS, so the
            # trigger uses the top of the field: out of range for any NumCS, and
            # therefore not an assumption about this integration.
            await self.spi.wr(CSID, 0xFFFF_FFFF)
            await self.spi.wr(COMMAND, CMD_DIR_TX)  # otherwise-legal command
            await self.spi.wr(CSID, 0)  # restore

        async def trig_overflow():
            # Disable the core here rather than inheriting SPIEN=0 from an earlier
            # facet, so the TX FIFO never drains. Fill until the DUT reports
            # STATUS.TXFULL, then write ONE beat past it: the boundary comes from
            # the DUT's own occupancy report, so no depth is imported from the
            # design's source. The loop bound is a DV-owned runaway guard --
            # exhausting it fails the test.
            await self.spi.wr(CONTROL, CTRL_RESET)
            for _ in range(_FILL_LIMIT):
                if await self.spi.rd(STATUS) & ST_TXFULL:
                    break
                await self.spi.wr(TXDATA, 0x5A5A_5A5A)
            else:
                raise AssertionError(
                    f"CHK-ERR-W1C OVERFLOW: STATUS.TXFULL never set after "
                    f"{_FILL_LIMIT} TXDATA writes with the core disabled"
                )
            await self.spi.wr(TXDATA, 0x5A5A_5A5A)  # one beat past full

        async def trig_cmdbusy():
            # Enable the core with an empty TX FIFO so each TX command stalls in
            # the queue. Queue until the DUT drops STATUS.READY (queue full), then
            # write one more command: that write sets ERROR_STATUS.CMDBUSY. Same
            # shape as OVERFLOW -- the depth is observed, never imported.
            await self.spi.wr(CONTROL, CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN)
            for _ in range(_CMD_LIMIT):
                if not (await self.spi.rd(STATUS) & ST_READY):
                    break
                await self.spi.wr(COMMAND, CMD_DIR_TX)
            else:
                raise AssertionError(
                    f"CHK-ERR-W1C CMDBUSY: STATUS.READY never dropped after "
                    f"{_CMD_LIMIT} queued TX commands"
                )
            await self.spi.wr(COMMAND, CMD_DIR_TX)  # one command past a full queue

        await self._trigger_err("UNDERFLOW", ERR_UNDERFLOW, trig_underflow)
        await self._trigger_err("CMDINVAL", ERR_CMDINVAL, trig_cmdinval)
        await self._trigger_err("CSIDINVAL", ERR_CSIDINVAL, trig_csidinval)
        await self._trigger_err("OVERFLOW", ERR_OVERFLOW, trig_overflow)
        await self._sw_rst_pulse()  # drain the full TX FIFO
        await self._trigger_err("CMDBUSY", ERR_CMDBUSY, trig_cmdbusy)
        await self._sw_rst_pulse()
        # ACCESSINVAL is NOT graded here. The RDL defines it as a TXDATA write
        # with no bytes enabled (ERROR_STATUS.ACCESSINVAL), which is unreachable
        # from this path twice over: the AXI master cannot emit a zero-strobe
        # beat (ocah_axi_master_driver.check_strb rejects any partial strobe),
        # and the wrapper's bridge answers a zero-strobe write itself rather
        # than forwarding it (axi_lite_to_tlul ACK_ZERO_STROBE_WRITE). Any other
        # byte count that happens to raise the bit would be an expectation taken
        # from the device, so the condition stays unclaimed.
        self.logger.info(
            "CHK-ERR-W1C PASS: UNDERFLOW/CMDINVAL/CSIDINVAL/OVERFLOW/CMDBUSY each "
            "set by their own trigger + W1C-clear (ACCESSINVAL not claimed: its "
            "documented zero-byte-write trigger reaches neither the bus nor the core)"
        )

    # ---- CHK-WATERMARK ----------------------------------------------------
    async def _chk_watermark(self, half: str, wm: int, fill: int) -> None:
        await self._sw_rst_pulse()
        # Program TX_WATERMARK; keep core disabled so the FIFO does not drain.
        ctrl = CTRL_RESET | (wm << CTRL_TX_WM_LSB)
        await self.spi.wr(CONTROL, ctrl)
        st_empty = await self.spi.rd(STATUS)
        assert (st_empty & ST_TXQD) == 0, f"CHK-WATERMARK FIFO not empty: 0x{st_empty:08x}"
        # STATUS.TXWM: high while the amount of data in the TX FIFO has fallen
        # below CONTROL.TX_WATERMARK words -- so an empty FIFO sets it. The
        # polarity is the whole of this facet, so it is taken from the register
        # description rather than from the design.
        assert st_empty & ST_TXWM, (
            f"CHK-WATERMARK STATUS.TXWM clear while TXQD=0 < wm (0x{st_empty:08x})"
        )
        for _ in range(wm - 1):
            await self.spi.wr(TXDATA, 0xA5A5_A5A5)
        st_below = await self.spi.rd(STATUS)
        assert (st_below & ST_TXQD) == wm - 1, (
            f"CHK-WATERMARK TXQD={st_below & ST_TXQD} != {wm - 1} below wm={wm} (0x{st_below:08x})"
        )
        assert st_below & ST_TXWM, (
            f"CHK-WATERMARK STATUS.TXWM clear at TXQD={st_below & ST_TXQD} < wm={wm} "
            f"(0x{st_below:08x})"
        )
        await self.spi.wr(TXDATA, 0xA5A5_A5A5)  # the word that reaches the threshold
        st_at = await self.spi.rd(STATUS)
        assert (st_at & ST_TXQD) == wm, (
            f"CHK-WATERMARK TXQD={st_at & ST_TXQD} != {wm} at wm={wm} (0x{st_at:08x})"
        )
        assert not (st_at & ST_TXWM), (
            f"CHK-WATERMARK STATUS.TXWM still set at TXQD={st_at & ST_TXQD} == wm={wm} "
            f"(0x{st_at:08x})"
        )
        extra = fill - wm
        for _ in range(extra):
            await self.spi.wr(TXDATA, 0xA5A5_A5A5)
        st_full = await self.spi.rd(STATUS)
        txqd = st_full & ST_TXQD
        assert txqd == fill, f"CHK-WATERMARK TXQD 0x{txqd:x} != filled {fill} (wm={wm})"
        assert not (st_full & ST_TXWM), (
            f"CHK-WATERMARK STATUS.TXWM set after filling past wm={wm} (0x{st_full:08x})"
        )
        self.logger.info(
            "CHK-WATERMARK PASS: %s half wm=%d, observed TXQD/TXWM %d/%d -> %d/%d -> %d/%d "
            "-> %d/%d (tx_wm = qd < wm)",
            half,
            wm,
            st_empty & ST_TXQD,
            int(bool(st_empty & ST_TXWM)),
            st_below & ST_TXQD,
            int(bool(st_below & ST_TXWM)),
            st_at & ST_TXQD,
            int(bool(st_at & ST_TXWM)),
            txqd,
            int(bool(st_full & ST_TXWM)),
        )
        await self._sw_rst_pulse()

    # ---- CHK-ENABLE -------------------------------------------------------
    async def _queue_one_tx(self) -> None:
        """Leave exactly one word in the TX FIFO with a TX command queued."""
        await self._sw_rst_pulse()
        await self.spi.wr(TXDATA, 0xDEAD_BEEF)
        st = await self.spi.rd(STATUS)
        assert (st & ST_TXQD) == 1, f"one TXDATA write left TXQD={st & ST_TXQD} (0x{st:08x})"
        await self.spi.wr(COMMAND, CMD_DIR_TX)

    async def _poll_drain(self, budget: int) -> int:
        """Polls until STATUS.TXEMPTY, or 0 if it never drained within budget."""
        for i in range(1, budget + 1):
            if await self.spi.rd(STATUS) & ST_TXEMPTY:
                return i
        return 0

    async def _chk_enable(self) -> None:
        """CHK-ENABLE: SPIEN gates command execution.

        The negative leg needs a window long enough that "did not drain" means
        "was held off" rather than "is slow". Measure the enabled drain first and
        derive the window from it, so the bound is calibrated against this build
        instead of being a hand-picked constant.
        """
        # Calibrate: how long does the queued command take to execute when enabled?
        await self._queue_one_tx()
        await self.spi.wr(CONTROL, CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN)
        calib = await self._poll_drain(_ENABLED_POLLS)
        assert calib, (
            f"CHK-ENABLE: the queued command did not execute with SPIEN=1 within "
            f"{_ENABLED_POLLS} polls -- cannot calibrate the negative window"
        )
        # Floor the window: a 1-poll calibration would otherwise leave a 4-poll
        # negative window, which a device that ignored SPIEN but merely took five
        # polls to execute would pass.
        window = max(_NEG_WINDOW_MARGIN * calib, _NEG_WINDOW_FLOOR)

        # Negative leg: same stimulus, SPIEN=0, held for the calibrated window.
        # OUTPUT_EN only enables the pad buffers, and SPIEN alone gates
        # transactions, so the hold window runs with OUTPUT_EN=1: a device that
        # gated commands on OUTPUT_EN instead of SPIEN would execute here.
        await self._queue_one_tx()  # _sw_rst_pulse leaves SPIEN=0
        await self.spi.wr(CONTROL, CTRL_RESET | CTRL_OUTPUT_EN)
        ctrl_hold = await self.spi.rd(CONTROL)
        assert (ctrl_hold & (CTRL_SPIEN | CTRL_OUTPUT_EN)) == CTRL_OUTPUT_EN, (
            f"CHK-ENABLE: hold-window CONTROL 0x{ctrl_hold:08x} is not SPIEN=0 OUTPUT_EN=1"
        )
        assert not await self._poll_drain(window), (
            f"CHK-ENABLE: command executed while SPIEN=0 (drained within {window} "
            f"polls, at least {_NEG_WINDOW_MARGIN}x the {calib}-poll enabled drain)"
        )
        st_held = await self.spi.rd(STATUS)
        assert (st_held & ST_TXQD) == 1, (
            f"CHK-ENABLE: TXQD={st_held & ST_TXQD} after the SPIEN=0 window -- the "
            f"queued command consumed the FIFO without STATUS.TXEMPTY (0x{st_held:08x})"
        )
        assert not (st_held & ST_TXEMPTY), (
            f"CHK-ENABLE: TXEMPTY set while SPIEN=0 held the command (0x{st_held:08x})"
        )

        # Positive leg: setting SPIEN, and changing no other bit, releases that
        # same queued command.
        await self.spi.wr(CONTROL, ctrl_hold | CTRL_SPIEN)
        ctrl_rel = await self.spi.rd(CONTROL)
        assert ctrl_rel ^ ctrl_hold == CTRL_SPIEN, (
            f"CHK-ENABLE: release CONTROL 0x{ctrl_rel:08x} differs from the hold value "
            f"0x{ctrl_hold:08x} in more than SPIEN"
        )
        released = await self._poll_drain(_ENABLED_POLLS)
        assert released, "CHK-ENABLE: command did not execute after SPIEN=1"
        self.logger.info(
            "CHK-ENABLE PASS: CONTROL=0x%08x (SPIEN=0, OUTPUT_EN=1) held the command for "
            "%d polls (at least %dx the %d-poll enabled drain, TXQD stayed 1); "
            "CONTROL=0x%08x "
            "(SPIEN only changed) drained it in %d",
            ctrl_hold,
            window,
            _NEG_WINDOW_MARGIN,
            calib,
            ctrl_rel,
            released,
        )
        await self._sw_rst_pulse()
        await self._clear_error_status()

    # ======================================================================
    # Legs L1 to L4
    # ======================================================================
    async def _extension_legs(self) -> None:
        self.seed = self.random_seed()
        self.checks = 0
        self.draw = self._leg_draw(SepSeededRng(self.seed ^ _LEG_SALT))
        self._log_plan()
        self.pads = SepSpiPadSampler().start()
        self.ops = SepSpiHostOps(self, clock=self.pads.now)
        self.intr_en = self.draw["I"]
        self.ev_en = 0
        try:
            await self._leg_setup()
            self._window(True)
            await self._leg_l1()
            await self._leg_l2()
            await self._leg_l3()
            await self._leg_l4()
        finally:
            close_graded_window(self.logger)
            await self.pads.stop()
        self.logger.info(
            "RESULT %s seed=%d PASS checks=%d", TEST, self.seed, self.checks + _OPEN_CHECKS
        )

    # ---- draws ------------------------------------------------------------
    def _leg_draw(self, rng: SepSeededRng) -> dict:
        d: dict = {"I": rng.randrange(4)}
        d["state_ev"] = {
            t: sum(
                b
                for i, b in enumerate(_EVT[x] for x in _FIFO_SRCS)
                if (rng.getrandbits(4) >> i) & 1
            )
            for t in ("T1", "T2", "T3", "T4")
        }
        d["walk_order"] = [0, 1, 2, 3]
        rng.shuffle(d["walk_order"])
        d["state_order"] = ["T1", "T2", "T3", "T4"]
        rng.shuffle(d["state_order"])
        d["kind_order"] = list(_KIND_BIT)
        rng.shuffle(d["kind_order"])
        d["cmd_kind"] = rng.choice(_CMD_KINDS)
        d["depth"] = rng.randrange(2, 4)
        d["ud_order"] = ["UNDERFLOW", "OVERFLOW"]
        rng.shuffle(d["ud_order"])
        injected = 0
        for k in [d["cmd_kind"], *d["ud_order"][: d["depth"] - 1]]:
            injected |= _KIND_BIT[k]
        # A 6-bit mask with at least one injected bit inside and one outside.
        while True:
            mask = rng.getrandbits(6)
            if mask & injected and injected & ~mask:
                break
        d["clear_mask"] = mask
        d["masked_kind"] = rng.choice(list(_KIND_BIT))
        d["csid_v"] = rng.randrange(2, 0xFFFF_FFFF)
        d["pair_order"] = list(_STRB_PAIRS)
        rng.shuffle(d["pair_order"])
        d["strobe_order"] = {}
        for off in d["pair_order"]:
            order = list(_STROBES)
            rng.shuffle(order)
            d["strobe_order"][off] = order
        d["strb_data"] = self._draw_strobe_data(rng)
        d["swrst"] = self._draw_swrst(rng)
        n = rng.randrange(1, 4)
        d["spien_lens"] = rng.sample(range(64), n)
        return d

    @staticmethod
    def _draw_strobe_data(rng: SepSeededRng) -> dict:
        """Data words per (pair, strobe): implemented bits, unique per register, not the content."""
        content = {
            "INTR_ENABLE": 0,
            "CONFIGOPTS": 0,
            "CSID": 0,
            "ERROR_ENABLE": _ERR_EN_ALL,
            "EVENT_ENABLE": 0,
        }
        used: dict[str, set[int]] = {k: {v} for k, v in content.items()}
        out = {}
        for off, halves in _STRB_PAIRS.items():
            for strb in _STROBES:
                words = []
                for name, _addr, mask, w1c in halves:
                    if w1c:
                        words.append(_R.mask32(name))
                    elif name == "TXDATA":
                        words.append(rng.getrandbits(32))
                    else:
                        while True:
                            v = rng.getrandbits(32) & mask
                            if v not in used[name]:
                                break
                        used[name].add(v)
                        words.append(v)
                out[(off, strb)] = tuple(words)
        return out

    @staticmethod
    def _draw_swrst(rng: SepSeededRng) -> dict:
        rx_wm = rng.choice([v for v in range(256) if v != _CTRL_RX_WM_RESET])
        seg_cycles = 32 * _SWRST_SEG_WORDS
        return {
            # CLKDIV 1 to 3 keeps the segment short; FULLCYC stays 0.
            "configopts": configopts_word(
                clkdiv=rng.randrange(1, 4),
                csnidle=rng.randrange(16),
                csntrail=rng.randrange(16),
                csnlead=rng.randrange(16),
                cpha=rng.randrange(2),
                cpol=rng.randrange(2),
            ),
            "error_enable": rng.randrange(0, _ERR_EN_ALL),
            "event_enable": rng.randrange(1, 64),
            "control": _CTRL_BASE & ~CTRL_RX_WM
            | (rng.randrange(1, 256) << _CTRL_TX_WM_LSB)
            | (rx_wm << _CTRL_RX_WM_LSB),
            "t": rng.randrange(1, seg_cycles // 2 + 1),
            "extra": rng.randrange(1, 5),
            "clean_len": rng.randrange(0, 32),
        }

    def _log_plan(self) -> None:
        d = self.draw
        self.logger.info(
            "PLAN %s seed=%d legs=L1,L2,L3,L4 window_code=410 l1_states=F,T1,T2,T3,T4 "
            "passes=A,B walk_cells=16 kinds=5 strobe_cells=12",
            TEST,
            self.seed,
        )
        self.logger.info(
            "DRAW seed=%d intr_en=%d state_ev={%s} walk_order=%s state_order=%s kind_order=%s "
            "cmd_kind=%s depth=%d ud_order=%s clear_mask=0x%02x masked_kind=%s csid_v=0x%08x "
            "pair_order=%s strobe_order={%s} swrst={%s} spien_lens=%s",
            self.seed,
            d["I"],
            ",".join(f"{k}:0x{v:02x}" for k, v in d["state_ev"].items()),
            d["walk_order"],
            d["state_order"],
            d["kind_order"],
            d["cmd_kind"],
            d["depth"],
            d["ud_order"],
            d["clear_mask"],
            d["masked_kind"],
            d["csid_v"],
            [f"0x{o:02x}" for o in d["pair_order"]],
            ",".join(
                f"0x{o:02x}:" + "/".join(f"{s:02x}" for s in v)
                for o, v in d["strobe_order"].items()
            ),
            ",".join(f"{k}:0x{v:x}" for k, v in d["swrst"].items()),
            d["spien_lens"],
        )
        for (off, strb), words in d["strb_data"].items():
            self.logger.info(
                "DRAW seed=%d strb_data off=0x%02x strb=0x%02x lo=0x%08x hi=0x%08x",
                self.seed,
                off,
                strb,
                words[0],
                words[1],
            )

    # ---- common helpers ---------------------------------------------------
    def _window(self, graded: bool) -> None:
        if graded:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    def _pass(self, chk: str, values: str) -> None:
        self.checks += 1
        self.logger.info("%s PASS seed=%d %s", chk, self.seed, values)

    def _fail(self, chk: str, values: str) -> None:
        line = f"{chk} FAIL seed={self.seed} {values}"
        self.logger.error(line)
        raise AssertionError(line)

    def _grade(self, chk: str, ok: bool, values: str) -> None:
        if ok:
            self._pass(chk, values)
        else:
            self._fail(chk, values)

    def _ctrl_missing(self, values: str) -> None:
        line = f"CTRL-MISSING seed={self.seed} {values}"
        self.logger.error(line)
        raise AssertionError(line)

    async def _pic14(self) -> int:
        """PIC source 14 on the next clk_i edge."""
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        vec = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << _SPI_AGG)
        await NextTimeStep()
        return (vec >> _SPI_AGG) & 1

    async def _set_ev(self, value: int) -> None:
        await self.ops.wr(EVENT_ENABLE, value)
        self.ev_en = value

    async def _poll_reg(self, addr: int, mask: int, what: str) -> int:
        """Read ``addr`` until every ``mask`` bit reads 1, at most _POLL_READS reads."""
        got = 0
        for _ in range(_POLL_READS):
            got = await self.ops.rd(addr)
            if got & mask == mask:
                return got
        raise AssertionError(f"wait '{what}' expired after {_POLL_READS} reads (0x{got:08x})")

    async def _idle_done(self, what: str) -> SpiStatus:
        return await self.ops.poll_status(
            lambda s: s.active == 0 and s.cmdqd == 0, 2_000, f"{what}: ACTIVE=0 and CMDQD=0"
        )

    async def _segment(self, cmd: int, *, windows: int = 1) -> list:
        mark = self.pads.mark()
        await self.ops.issue_command(cmd)
        return await self.ops.wait_segment_done(
            self.pads, mark, windows=windows, bound_clks=_SEG_BOUND_CLKS
        )

    async def _leg_setup(self) -> None:
        await self.ops.clean_state()
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self.ops.write_configopts(_CFG_BASE)
        await self.ops.wr(CSID, 0)
        self.pads.set_idle_level(0)
        ist = await self.ops.rd(INTR_STATE)
        if ist & INTR_ERROR:
            self._ctrl_missing(f"INTR_STATE.ERROR=1 after the SPI clean state (0x{ist:08x})")
        self.logger.info("LEG-SETUP LOG seed=%d intr_state=0x%08x", self.seed, ist)

    # ---- L1 ---------------------------------------------------------------
    async def _state_read(self, tag: str, levels: dict[str, int], *, mask_step: int = 0) -> None:
        """Sample STATUS, INTR_STATE and PIC 14 at INTR_ENABLE=I and at the enabled twin."""
        selected = [s for s in _EVT if self.ev_en & _EVT[s]]
        unnamed = [s for s in selected if s not in levels]
        if unnamed:
            raise AssertionError(f"{tag}: selected sources {unnamed} have no named level")
        st = await self.ops.read_status()
        wrong = {s: _LEVEL[s](st) for s, lvl in levels.items() if _LEVEL[s](st) != lvl}
        if wrong:
            self._ctrl_missing(
                f"state={tag} named levels {levels} but STATUS shows {wrong} ({st.fmt()})"
            )
        expect_ev = int(any(levels[s] for s in selected))
        ist = await self.ops.rd(INTR_STATE)
        pic = await self._pic14()
        await self.ops.wr(INTR_ENABLE, 3)
        ist_twin = await self.ops.rd(INTR_STATE)
        twin = await self._pic14()
        await self.ops.wr(INTR_ENABLE, self.intr_en)
        event = int(bool(ist & INTR_SPI_EVENT))
        error = int(bool(ist & INTR_ERROR))
        src = ",".join(levels)
        lvl = "".join(str(levels[s]) for s in levels)
        self._grade(
            "CHK-SPI-EVENT",
            event == expect_ev,
            f"state={tag} ev_en=0x{self.ev_en:02x} src={src} level={lvl} event={event} "
            f"expect={expect_ev} mask_step={mask_step}",
        )
        i = self.intr_en
        expect_pic = expect_ev & (i >> 1)
        self._grade(
            "CHK-SPI-LINE",
            pic == expect_pic and twin == expect_ev and error == 0,
            f"state={tag} intr_en={i} pic14={pic} expect={expect_pic} twin_pic14={twin} "
            f"twin_expect={expect_ev} intr_error={error} twin_intr_state=0x{ist_twin:x}",
        )

    async def _l1_fifo_state(self, name: str, pass_ev: int) -> None:
        tx_wm, rx_wm, words, rx_bytes, lvls = _L1_STATES[name]
        await self._set_ev(pass_ev)
        await self.ops.clean_state()
        await self._set_ev(pass_ev)
        await self.ops.wr(CONTROL, _CTRL_BASE & ~CTRL_RX_WM | (tx_wm << _CTRL_TX_WM_LSB) | rx_wm)
        for w in range(words):
            await self.ops.push_tx(0x1100_0000 | w)
        if rx_bytes:
            await self._segment(command_word(rx_bytes - 1, direction=DIR_RX))
            await self.ops.poll_status(
                lambda s: s.rxqd == rx_bytes // 4 and s.active == 0, 2_000, f"{name}: RXQD"
            )
        else:
            await self.ops.poll_status(
                lambda s: s.txqd == words and s.active == 0, 2_000, f"{name}: TXQD={words}"
            )
        levels = dict(zip(_FIFO_SRCS, lvls))
        await self._state_read(name, levels)
        if pass_ev and name != "F":
            await self._set_ev(self.draw["state_ev"][name])
            await self._state_read(f"{name}-drawn", levels)

    async def _l1_rxfull_seq(self, ev: int) -> None:
        await self._set_ev(ev)
        await self.ops.clean_state()
        await self._set_ev(ev)
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self._state_read("RXFULL-pre", {"RXFULL": 0})
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(_RXFULL_SEG_BYTES - 1, direction=DIR_RX))
        st = await self.ops.poll_status(
            lambda s: s.rxfull == 1 and s.rxstall == 1, 20_000, "RXFULL=1 and RXSTALL=1"
        )
        self.logger.info("L1-RXFULL LOG seed=%d ev_en=0x%02x %s", self.seed, ev, st.fmt())
        await self._state_read("RXFULL-full", {"RXFULL": 1})
        words = 0
        for _ in range(_RX_DRAIN_READS):
            st = await self.ops.read_status()
            if not st.rxempty:
                await self.ops.rd(RXDATA)
                words += 1
            elif self.pads.count_windows(mark) >= 1 and st.active == 0 and st.cmdqd == 0:
                break
        else:
            raise AssertionError(f"RXFULL segment not drained after {_RX_DRAIN_READS} reads")
        self.logger.info("L1-RXFULL LOG seed=%d drained_words=%d", self.seed, words)
        await self._state_read("RXFULL-drained", {"RXFULL": 0})

    async def _stall_head(self, word: int) -> None:
        """Hold a Tx head segment in TXSTALL with ACTIVE=1.

        The segment is 8 bytes and one of its two words is queued, so the core
        sends that word and stalls inside the segment until one more TXDATA
        word arrives.
        """
        await self.ops.push_tx(word)
        await self.ops.issue_command(command_word(7, direction=DIR_TX))
        await self.ops.poll_status(
            lambda s: s.active == 1 and s.txstall == 1, 2_000, "ACTIVE=1 and TXSTALL=1"
        )

    async def _l1_ready_low(self) -> int:
        """Stall a Tx head segment and fill the queue until READY=0; returns accepted writes."""
        await self._stall_head(0x4400_0001)
        accepted = 0
        while True:
            st = await self.ops.read_status()
            if not st.ready:
                return accepted
            if accepted >= _READY_ACCEPT_LIMIT:
                self._ctrl_missing(f"READY=1 after {accepted} accepted COMMAND writes ({st.fmt()})")
            await self.ops.wr(COMMAND, _CMD_DUMMY)
            accepted += 1

    async def _leg_l1(self) -> None:
        await self.ops.wr(INTR_ENABLE, self.intr_en)
        for pass_ev in (_EV_FIFO_ALL, 0):
            for name in ["F", *self.draw["state_order"]]:
                await self._l1_fifo_state(name, pass_ev)
            await self._set_ev(pass_ev)
            await self.ops.clean_state()

        # TXEMPTY only, with the mask step.
        await self.ops.clean_state()
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self._set_ev(EVT_TXEMPTY)
        await self._state_read("TXEMPTY-only", {"TXEMPTY": 1})
        await self._set_ev(0)
        await self._state_read("TXEMPTY-mask", {"TXEMPTY": 1}, mask_step=1)
        await self._set_ev(EVT_TXEMPTY)
        await self.ops.push_tx(0x2200_0000)
        await self._state_read("TXEMPTY-word", {"TXEMPTY": 0})
        await self._segment(command_word(3, direction=DIR_TX))
        await self._state_read("TXEMPTY-sent", {"TXEMPTY": 1})

        # RXFULL only, then the same sequence with EVENT_ENABLE=0.
        await self._l1_rxfull_seq(EVT_RXFULL)
        await self._l1_rxfull_seq(0)

        # IDLE level.
        await self.ops.clean_state()
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self._set_ev(EVT_IDLE)
        await self._state_read("IDLE-idle", {"IDLE": 1})
        mark = self.pads.mark()
        await self._stall_head(0x3300_0001)
        await self._state_read("IDLE-active", {"IDLE": 0})
        await self.ops.push_tx(0x3300_0000)
        await self.ops.wait_segment_done(self.pads, mark, bound_clks=_SEG_BOUND_CLKS)
        await self._state_read("IDLE-done", {"IDLE": 1})

        # READY level.
        await self.ops.clean_state()
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self._set_ev(EVT_READY)
        await self._state_read("READY-ready", {"READY": 1})
        accepted = await self._l1_ready_low()
        self.logger.info("L1-READY LOG seed=%d accepted=%d", self.seed, accepted)
        await self._state_read("READY-low", {"READY": 0})
        await self._set_ev(0)
        await self._state_read("READY-low-masked", {"READY": 0})
        await self._set_ev(EVT_READY)
        await self.ops.push_tx(0x4400_0000)
        await self._idle_done("READY leg")
        await self._state_read("READY-done", {"READY": 1})

        await self._l1_line_walk()

    async def _l1_line_walk(self) -> None:
        for i in self.draw["walk_order"]:
            first_ctl = i in (0, 1, 2)
            self._window(not first_ctl)
            await self.ops.clean_state()
            await self._set_ev(0)
            await self.ops.wr(INTR_ENABLE, i)
            for n, (state, ev, err) in enumerate(_WALK):
                control = (state == "none" and i in (0, 1, 2)) or (state == "error" and i in (0, 1))
                if n:
                    self._window(not control)
                    if state == "error":
                        await self.ops.wr(INTR_TEST, INTR_ERROR)
                    elif state == "both":
                        await self._set_ev(EVT_TXEMPTY)
                    elif state == "event":
                        await self.ops.wr(INTR_STATE, INTR_ERROR)
                    else:
                        await self._set_ev(0)
                ist = await self.ops.rd(INTR_STATE)
                pic = await self._pic14()
                expect = (ev & (i >> 1)) | (err & i & 1)
                got_state = (int(bool(ist & INTR_SPI_EVENT)), int(bool(ist & INTR_ERROR)))
                values = (
                    f"intr_en={i} state={state} pic14={pic} expect={expect} "
                    f"intr_state=0x{ist & INTR_STATE_MASK:x} expect_state=0x{(ev << 1) | err:x}"
                )
                ok = pic == expect and got_state == (ev, err)
                if control:
                    self.logger.info("CTL-SPI-LINE LOG seed=%d %s", self.seed, values)
                    if not ok:
                        self._fail("CTL-SPI-LINE", values)
                else:
                    self._grade("CHK-SPI-LINE", ok, f"walk=1 {values}")
        self.intr_en = self.draw["I"]
        await self.ops.wr(INTR_ENABLE, self.intr_en)
        self._window(True)

    # ---- L2 ---------------------------------------------------------------
    async def _inject(self, kind: str, *, csid: int | None = None) -> None:
        """One error injection; every COMMAND write except the CMDBUSY one waits for READY=1."""
        if kind == "CSIDINVAL":
            await self.ops.wr(CSID, self.draw["csid_v"] if csid is None else csid)
            await self.ops.issue_command(_CMD_DUMMY)
            await self.ops.wr(CSID, 0)
        elif kind == "CMDINVAL":
            await self._inject_cmdinval()
        elif kind == "UNDERFLOW":
            await self.ops.poll_status(
                lambda s: s.rxempty == 1 and s.active == 0, 2_000, "RXEMPTY=1 and ACTIVE=0"
            )
            await self.ops.rd(RXDATA)
        elif kind == "OVERFLOW":
            for _ in range(_FILL_LIMIT):
                st = await self.ops.read_status()
                if st.txfull:
                    break
                await self.ops.wr(TXDATA, 0x5500_0000)
            else:
                self._ctrl_missing(f"TXFULL=0 after {_FILL_LIMIT} TXDATA writes")
            await self.ops.wr(TXDATA, 0x5500_0000)
        elif kind == "CMDBUSY":
            await self._l1_ready_low()
            await self.ops.wr(COMMAND, _CMD_DUMMY)
        else:
            raise ValueError(kind)

    async def _inject_cmdinval(self) -> None:
        """CMDINVAL: a reserved-SPEED COMMAND written with SPIEN=0, then the SW_RST helper.

        SPIEN=0 holds the command in the queue and SW_RST clears the queue, so
        the core never pops a reserved speed. ERROR_STATUS is a register and
        keeps CMDINVAL across SW_RST. CONTROL returns to its value before the
        injection once CMDQD reads 0.
        """
        ctrl = await self.ops.rd(CONTROL)
        await self.ops.wr(CONTROL, ctrl & ~CTRL_SPIEN)
        await self.ops.issue_command(command_word(0, speed=_SPEED_RESERVED))
        await self.ops.sw_rst()
        await self.ops.poll_status(
            lambda s: s.cmdqd == 0 and s.active == 0, 2_000, "CMDINVAL flush: CMDQD=0"
        )
        await self.ops.wr(CONTROL, ctrl)

    async def _kind_entry(self) -> tuple[int, int]:
        await self.ops.clean_state()
        await self.ops.wr(INTR_ENABLE, 0)
        await self._set_ev(0)
        es = await self.ops.rd(ERROR_STATUS)
        ie = int(bool(await self.ops.rd(INTR_STATE) & INTR_ERROR))
        if es or ie:
            self._ctrl_missing(
                f"ERROR_STATUS=0x{es:02x} INTR_STATE.ERROR={ie} after the clean state"
            )
        return es, ie

    async def _l2_single(self, kind: str, csid0_es: int) -> None:
        bit = _KIND_BIT[kind]
        _, ie0 = await self._kind_entry()
        await self._inject(kind)
        es = await self._poll_reg(ERROR_STATUS, bit, f"{kind}: own ERROR_STATUS bit")
        self.logger.info(
            "CTL-SPI-ERR-OWN LOG seed=%d kind=%s err_status=0x%02x own_bit=0x%02x",
            self.seed,
            kind,
            es,
            bit,
        )
        ie1 = int(bool(await self.ops.rd(INTR_STATE) & INTR_ERROR))
        if kind == "CSIDINVAL":
            self._grade(
                "CHK-SPI-CSID-RANGE",
                es == ERR_CSIDINVAL and ie1 == 1,
                f"csid=0x{self.draw['csid_v']:08x} err_status=0x{es:02x} "
                f"expect=0x{ERR_CSIDINVAL:02x} intr_error={ie1} "
                f"control_csid0_err_status=0x{csid0_es:02x}",
            )
        await self.ops.wr(ERROR_STATUS, bit)
        es2 = await self.ops.rd(ERROR_STATUS)
        ie2 = int(bool(await self.ops.rd(INTR_STATE) & INTR_ERROR))
        if es2 & bit:
            self._fail("CTL-SPI-ERR-W1C", f"kind={kind} err_status=0x{es2:02x} after its W1C")
        await self.ops.wr(INTR_STATE, INTR_ERROR)
        ie3 = int(bool(await self.ops.rd(INTR_STATE) & INTR_ERROR))
        self._grade(
            "CHK-SPI-ERR-KIND",
            (ie1, ie2, ie3) == (1, 1, 0),
            f"kind={kind} intr_error={ie1} after_status_w1c={ie2} after_intr_w1c={ie3} "
            f"control_intr_error_before={ie0} err_status=0x{es:02x}",
        )
        if kind == "CMDBUSY":
            await self.ops.push_tx(0x6600_0000)
            await self._idle_done("CMDBUSY release")

    async def _l2_csid1(self) -> None:
        self._window(False)
        await self._kind_entry()
        await self._inject("CSIDINVAL", csid=1)
        es = 0
        for _ in range(16):
            es = await self.ops.rd(ERROR_STATUS)
            if es & ERR_CSIDINVAL:
                break
        st = await self.ops.read_status()
        ie = int(bool(await self.ops.rd(INTR_STATE) & INTR_ERROR))
        self.logger.info(
            "OBS-SPI-CSID1 LOG seed=%d csid=0x1 err_status=0x%02x intr_error=%d active=%d cmdqd=%d",
            self.seed,
            es,
            ie,
            st.active,
            st.cmdqd,
        )
        await self.ops.clean_state()
        self._window(True)

    async def _l2_accumulate(self, kinds: list[str]) -> int:
        """Inject ``kinds`` in order with the SW_RST helper after each; returns the OR of bits."""
        await self.ops.clean_state()
        bits = 0
        for k in kinds:
            await self._inject(k)
            await self.ops.sw_rst()
            bits |= _KIND_BIT[k]
        return bits

    async def _leg_l2(self) -> None:
        d = self.draw
        # Control for CSID-RANGE: a COMMAND with CSID=0 sets no error bit.
        self._window(False)
        await self._kind_entry()
        await self._segment(_CMD_DUMMY)
        csid0_es = await self.ops.rd(ERROR_STATUS)
        self.logger.info("CTL-SPI-CSID0 LOG seed=%d err_status=0x%02x", self.seed, csid0_es)
        if csid0_es:
            self._ctrl_missing(f"ERROR_STATUS=0x{csid0_es:02x} after a COMMAND with CSID=0")
        self._window(True)

        for kind in d["kind_order"]:
            await self._l2_single(kind, csid0_es)
            if kind == "CSIDINVAL":
                await self._l2_csid1()

        # Accumulation and the drawn clear mask.
        kinds = [d["cmd_kind"], *d["ud_order"][: d["depth"] - 1]]
        expect_old = await self._l2_accumulate(kinds)
        old = await self.ops.rd(ERROR_STATUS)
        mask = d["clear_mask"]
        hit, kept = mask & expect_old, expect_old & ~mask
        if not (hit and kept):
            self._ctrl_missing(f"clear mask 0x{mask:02x} hit=0x{hit:02x} kept=0x{kept:02x}")
        await self.ops.wr(ERROR_STATUS, mask)
        got = await self.ops.rd(ERROR_STATUS)
        self._grade(
            "CHK-SPI-ERR-MASK",
            old == expect_old and got == kept,
            f"kinds={','.join(kinds)} old=0x{old:02x} expect_old=0x{expect_old:02x} "
            f"mask=0x{mask:02x} hit=0x{hit:02x} kept=0x{kept:02x} got=0x{got:02x} "
            f"expect=0x{kept:02x}",
        )

        # A write of 0 clears no bit.
        expect = await self._l2_accumulate([d["cmd_kind"], "UNDERFLOW", "OVERFLOW"])
        await self.ops.wr(ERROR_STATUS, 0)
        got = await self.ops.rd(ERROR_STATUS)
        self._grade(
            "CHK-SPI-ERR-MASK",
            got == expect,
            f"zero_write=1 cmd_kind={d['cmd_kind']} got=0x{got:02x} expect=0x{expect:02x}",
        )
        await self.ops.clean_state()

        # The masked kind is logged only.
        self._window(False)
        kind = d["masked_kind"]
        await self._kind_entry()
        await self.ops.wr(ERROR_ENABLE, _ERR_EN_ALL & ~_KIND_BIT[kind])
        await self._inject(kind)
        es = await self.ops.rd(ERROR_STATUS)
        ie = int(bool(await self.ops.rd(INTR_STATE) & INTR_ERROR))
        self.logger.info(
            "OBS-SPI-MASK seed=%d kind=%s err_status=0x%02x intr_error=%d", self.seed, kind, es, ie
        )
        await self.ops.wr(ERROR_ENABLE, _ERR_EN_ALL)
        await self.ops.clean_state()
        self._window(True)

        await self._l2_cmdbusy0()

    async def _l2_cmdbusy0(self) -> None:
        await self.ops.clean_state()
        await self.ops.wr(CONTROL, _CTRL_BASE & ~CTRL_SPIEN)
        await self.ops.wr(ERROR_ENABLE, _ERR_EN_ALL)
        accepted = 0
        control_busy = 0
        while True:
            st = await self.ops.read_status()
            if not st.ready and not st.active:
                break
            if not st.ready:
                self._ctrl_missing(f"READY=0 with ACTIVE=1 while SPIEN=0 ({st.fmt()})")
            if accepted >= _READY_ACCEPT_LIMIT:
                self._ctrl_missing(f"READY=1 after {accepted} accepted COMMAND writes ({st.fmt()})")
            await self.ops.wr(COMMAND, _CMD_DUMMY)
            accepted += 1
            control_busy |= await self.ops.rd(ERROR_STATUS) & ERR_CMDBUSY
        mark = self.pads.mark()
        await self.ops.wr(COMMAND, _CMD_DUMMY)
        es = 0
        for _ in range(_POLL_READS):
            es = await self.ops.rd(ERROR_STATUS)
            if es & ERR_CMDBUSY:
                break
        self._grade(
            "CHK-SPI-CMDBUSY0",
            bool(es & ERR_CMDBUSY) and not control_busy,
            f"writes={accepted} error_enable=0x{_ERR_EN_ALL:02x} ready={st.ready} "
            f"active={st.active} cmdbusy={int(bool(es & ERR_CMDBUSY))} "
            f"control_cmdbusy={int(bool(control_busy))} err_status=0x{es:02x}",
        )
        await self.ops.wr(ERROR_STATUS, ERR_CMDBUSY)
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self.pads.wait_windows(accepted, mark, _SEG_BOUND_CLKS)
        await self._idle_done("CMDBUSY0 release")
        await self.ops.clean_state()

    # ---- L3 ---------------------------------------------------------------
    async def _strobe_cell(self, off: int, strb: int) -> None:
        (lo_name, lo_addr, lo_mask, lo_w1c), (hi_name, hi_addr, hi_mask, hi_w1c) = _STRB_PAIRS[off]
        await self.ops.clean_state()
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self.ops.write_configopts(0)
        await self.ops.wr(CSID, 0)
        await self.ops.wr(ERROR_ENABLE, _ERR_EN_ALL)
        await self.ops.wr(INTR_ENABLE, 0)
        await self._set_ev(0)
        model = {
            "INTR_STATE": 0,
            "INTR_ENABLE": 0,
            "CONFIGOPTS": 0,
            "CSID": 0,
            "ERROR_ENABLE": _ERR_EN_ALL,
            "ERROR_STATUS": 0,
            "EVENT_ENABLE": 0,
        }
        if off == 0x00:
            await self.ops.wr(INTR_TEST, INTR_ERROR)
            model["INTR_STATE"] = INTR_ERROR
        elif off == 0x30:
            await self._inject_cmdinval()
            es = await self._poll_reg(
                ERROR_STATUS, ERR_CMDINVAL, "CMDINVAL before the strobed write"
            )
            if es != ERR_CMDINVAL:
                self._ctrl_missing(
                    f"ERROR_STATUS=0x{es:02x} before the strobed write, expected 0x08"
                )
            model["ERROR_STATUS"] = ERR_CMDINVAL
        tx = off == 0x28
        st0 = await self.ops.read_status()
        if tx and (st0.active or st0.txqd or st0.rxqd):
            self._ctrl_missing(f"pair 0x28 needs ACTIVE=0 and empty FIFOs ({st0.fmt()})")
        lo_old = None if tx else await self.ops.rd(lo_addr)
        hi_old = await self.ops.rd(hi_addr)
        for name, got, mask in ((lo_name, lo_old, lo_mask), (hi_name, hi_old, hi_mask)):
            if got is not None and not field_compare(got, model[name], mask).ok:
                self._ctrl_missing(
                    f"off=0x{off:02x} {name}=0x{got:08x} before the cell, expected "
                    f"0x{model[name]:08x} on mask 0x{mask:08x}"
                )
        lo_data, hi_data = self.draw["strb_data"][(off, strb)]
        resp = await self.ops.wr_strobed64(_SPI_BASE + off, (hi_data << 32) | lo_data, strb)
        lo_new = None if tx else await self.ops.rd(lo_addr)
        hi_new = await self.ops.rd(hi_addr)

        def expect(name: str, data: int, w1c: bool, strobed: bool) -> int:
            if not strobed:
                return model[name]
            return model[name] & ~data if w1c else data

        exp_hi = expect(hi_name, hi_data, hi_w1c, bool(strb & 0xF0))
        fc_hi = field_compare(hi_new, exp_hi, hi_mask)
        ok = resp == 0 and fc_hi.ok
        lo_txt = "lo=- expect_lo=- lo_mask=-"
        if not tx:
            exp_lo = expect(lo_name, lo_data, lo_w1c, bool(strb & 0x0F))
            fc_lo = field_compare(lo_new, exp_lo, lo_mask)
            ok = ok and fc_lo.ok
            lo_txt = (
                f"lo=0x{lo_new & lo_mask:08x} expect_lo=0x{exp_lo & lo_mask:08x} "
                f"lo_mask=0x{lo_mask:08x} lo_rsvd=0x{fc_lo.rsvd:x}"
            )
        self._grade(
            "CHK-SPI-STRB",
            ok,
            f"off=0x{off:02x} strb=0x{strb:02x} resp={'OKAY' if resp == 0 else resp} "
            f"{lo_txt} hi=0x{hi_new & hi_mask:08x} expect_hi=0x{exp_hi & hi_mask:08x} "
            f"hi_mask=0x{hi_mask:08x} hi_rsvd=0x{fc_hi.rsvd:x} pair={lo_name},{hi_name}",
        )
        if off != 0x30:
            es = await self.ops.rd(ERROR_STATUS)
            self.logger.info(
                "OBS-SPI-STRB-ACCESSINVAL seed=%d off=0x%02x strb=0x%02x accessinval=%d",
                self.seed,
                off,
                strb,
                int(bool(es & ERR_ACCESSINVAL)),
            )
        txqd_after = None
        if tx:
            txqd_after = await self._strobe_tx(strb, st0.txqd)
        if strb == 0xFF:
            hi_changed = (hi_new ^ hi_old) & hi_mask
            lo_changed = txqd_after != st0.txqd if tx else (lo_new ^ lo_old) & lo_mask
            self._grade(
                "CHK-SPI-STRB-CTRL",
                bool(hi_changed and lo_changed),
                f"off=0x{off:02x} strb=0xFF both_changed={int(bool(hi_changed and lo_changed))}",
            )

    async def _strobe_tx(self, strb: int, txqd_before: int) -> int:
        """Grade the TXDATA half by TXQD; return TXQD after the strobed write."""
        if strb & 0x0F:
            st = await self.ops.poll_status(
                lambda s: s.txqd == 1, 2_000, "TXQD=1 after TXDATA half"
            )
        else:
            st = await self.ops.read_status()
        exp_qd = txqd_before + (1 if strb & 0x0F else 0)
        exp_empty = 0 if strb & 0x0F else 1
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(3, direction=DIR_TX))
        if not strb & 0x0F:
            await self.ops.push_tx(0x7700_0000)
        await self.ops.wait_segment_done(self.pads, mark, bound_clks=_SEG_BOUND_CLKS)
        after = await self.ops.read_status()
        self._grade(
            "CHK-SPI-STRB-TX",
            st.txqd == exp_qd
            and st.txempty == exp_empty
            and after.txempty == 1
            and after.txqd == 0,
            f"strb=0x{strb:02x} txqd_before={txqd_before} txqd_after={st.txqd} "
            f"expect_txqd={exp_qd} txempty={st.txempty} "
            f"txempty_after_segment={after.txempty} txqd_after_segment={after.txqd}",
        )
        await self.ops.sw_rst()
        return st.txqd

    async def _leg_l3(self) -> None:
        for off in self.draw["pair_order"]:
            for strb in self.draw["strobe_order"][off]:
                await self._strobe_cell(off, strb)
        await self.ops.clean_state()
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self.ops.write_configopts(_CFG_BASE)

    # ---- L4 ---------------------------------------------------------------
    async def _leg_l4(self) -> None:
        await self._l4_swrst()
        await self._l4_spien()

    async def _l4_swrst(self) -> None:
        sw = self.draw["swrst"]
        armed = {
            "CONFIGOPTS": (CONFIGOPTS, sw["configopts"]),
            "ERROR_ENABLE": (ERROR_ENABLE, sw["error_enable"]),
            "EVENT_ENABLE": (EVENT_ENABLE, sw["event_enable"]),
            "CONTROL": (CONTROL, sw["control"]),
        }
        await self.ops.clean_state()
        await self.ops.write_configopts(sw["configopts"])
        await self.ops.wr(ERROR_ENABLE, sw["error_enable"])
        await self._set_ev(sw["event_enable"])
        await self.ops.wr(CONTROL, sw["control"])
        nonreset = 0
        for name, (addr, value) in armed.items():
            got = await self.ops.rd(addr)
            rst = _R.reset32(name)
            nonreset += int(value != rst)
            self.logger.info(
                "L4-SWRST-ARM LOG seed=%d reg=%s value=0x%08x read=0x%08x reset=0x%08x",
                self.seed,
                name,
                value,
                got,
                rst,
            )
        if nonreset != len(armed):
            self._ctrl_missing(f"{len(armed) - nonreset} armed L4 values equal the reset value")
        cpol = (sw["configopts"] >> _R.field_lsb("CONFIGOPTS", "cpol")) & 1
        self.pads.set_idle_level(cpol)
        mark = self.pads.mark()
        await self.ops.issue_command(command_word(4 * _SWRST_SEG_WORDS - 1, direction=DIR_TX))
        for w in range(_SWRST_SEG_WORDS + sw["extra"]):
            await self.ops.push_tx(0x8800_0000 | w)
        edges = await self.pads.wait_leading_edges(sw["t"], mark, _SEG_BOUND_CLKS)
        before = await self.ops.read_status()
        await self.ops.wr(CONTROL, sw["control"] | CTRL_SW_RST)
        self.logger.info(
            "L4-SWRST-POINT LOG seed=%d t=%d edges=%d cs_low=%d %s",
            self.seed,
            sw["t"],
            edges,
            int(self.pads.cs_low()),
            before.fmt(),
        )
        if not before.active and before.txqd + before.rxqd == 0:
            self._ctrl_missing(f"no work at the SW_RST point ({before.fmt()})")
        hold = int(bool(await self.ops.rd(CONTROL) & CTRL_SW_RST))
        empty = await self.ops.poll_status(
            lambda s: s.txempty == 1 and s.rxempty == 1, 2_000, "SW_RST: TXEMPTY=1 and RXEMPTY=1"
        )
        await self.ops.wr(CONTROL, sw["control"])
        rel = await self.ops.read_status()
        kept = []
        for name, (addr, value) in armed.items():
            fc = field_compare(await self.ops.rd(addr), value, _R.mask32(name))
            self.logger.info("L4-SWRST-REG LOG seed=%d reg=%s %s", self.seed, name, fc.fields())
            kept.append(fc.ok)
        await self.ops.wait_ready()
        wins = await self._segment(command_word(sw["clean_len"], direction=DIR_DUMMY))
        clean = wins[0].leading_edges
        exp = sw["clean_len"] + 1
        self._grade(
            "CHK-SPI-SWRST",
            hold == 1
            and empty.txempty == 1
            and empty.rxempty == 1
            and (rel.active, rel.txqd, rel.rxqd) == (0, 0, 0)
            and all(kept)
            and clean == exp,
            f"t={sw['t']} active_before={before.active} txqd_before={before.txqd} "
            f"rxqd_before={before.rxqd} hold_read={hold} txempty={empty.txempty} "
            f"rxempty={empty.rxempty} active={rel.active} txqd={rel.txqd} rxqd={rel.rxqd} "
            f"regs_kept={int(all(kept))} nonreset={nonreset} clean_cycles={clean}/{exp}",
        )
        await self.ops.clean_state()
        await self.ops.wr(CONTROL, _CTRL_BASE)
        await self.ops.write_configopts(_CFG_BASE)
        await self.ops.wr(ERROR_ENABLE, _ERR_EN_ALL)
        await self._set_ev(0)
        self.pads.set_idle_level(0)

    async def _l4_spien(self) -> None:
        lens = self.draw["spien_lens"]
        await self.ops.clean_state()
        self._window(False)
        ref = await self._segment(command_word(max(lens), direction=DIR_DUMMY))
        t_seg = ref[0].end - ref[0].start
        self._window(True)
        await self.ops.wr(CONTROL, _CTRL_BASE & ~CTRL_SPIEN)
        accepted = 0
        for ln in lens:
            st = await self.ops.read_status()
            if not st.ready:
                break
            await self.ops.wr(COMMAND, command_word(ln, direction=DIR_DUMMY))
            accepted += 1
        hold_mark = self.pads.mark()
        st = await self.ops.read_status()
        self.logger.info(
            "L4-SPIEN LOG seed=%d accepted=%d cmdqd=%d t_seg=%d",
            self.seed,
            accepted,
            st.cmdqd,
            t_seg,
        )
        if accepted < 1:
            self._ctrl_missing("no COMMAND accepted with SPIEN=0")
        window = 4 * t_seg
        await ClockCycles(cocotb.top.clk_i, window)
        quiet_wins = self.pads.windows_since(hold_mark, complete_only=False)
        quiet_edges = self.pads.sck_edges_between(hold_mark.clk + 1, self.pads.now() + 1)
        pad_activity = len(quiet_wins) + len(quiet_edges) + int(self.pads.cs_low())
        run_mark = self.pads.mark()
        await self.ops.wr(CONTROL, _CTRL_BASE)
        wins = await self.pads.wait_windows(accepted, run_mark, _SEG_BOUND_CLKS)
        await self._idle_done("SPIEN release")
        cycles = [w.leading_edges for w in wins]
        exp = [ln + 1 for ln in lens[:accepted]]
        self._grade(
            "CHK-SPI-SPIEN",
            st.cmdqd == accepted and pad_activity == 0 and cycles == exp and t_seg < window,
            f"n={len(lens)} accepted={accepted} cmdqd={st.cmdqd} t_seg={t_seg} "
            f"window_clk={window} pad_activity={pad_activity} "
            f"released_in_order={int(cycles == exp)} cycles={cycles} expect={exp}",
        )
        await self.ops.clean_state()
