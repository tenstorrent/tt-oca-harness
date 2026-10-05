# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OT SPI host CSRs, interrupts, error bits, watermark and enable follow the spi_host spec.

A combined-per-group `[RAND-REP]` that folds the OCAH OT-SPI host-control firmware
tests (`spi_ot_reg`, `tx_fifo`, `cmd_queue`, `interrupt`, `error_handling`,
`watermark`, `enable_disable`) into one representative. Not folded, because nothing
here checks them: clock_config (CFG.CLKDIV is R/W-walked but no transfer runs at a
programmed divider) and rx_fifo (the only RX touch is the empty-FIFO read that
triggers UNDERFLOW). Drives the upstream OpenTitan spi_host CSRs (@0x10B0_0000,
NUM_CS=1) directly over the CPU-LSU AXI splice (no_cpu, no firmware, no flash BFM).
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

Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_spec_tables import agg_from_pic
from sep_base_test import sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    CMD_DIR_TX,
    CMD_SPEED_RESERVED,
    COMMAND,
    CONTROL,
    CSID,
    CTRL_OUTPUT_EN,
    CTRL_RESET,
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
    ERROR_STATUS,
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
    )

    async def run_scenario(self) -> None:
        self.scfg = SepSpiHostCfg(self.random_seed())
        self.spi = SepSpiHost(self)
        self.logger.info("SPI host CSR config: %s", self.scfg.summary())

        await self.bring_up_no_cpu()

        await self._chk_reset()
        await self._chk_reg_rw()
        await self._chk_zero_strb()
        await self._chk_intr()
        await self._chk_err_w1c()
        for half, wm, fill in self.scfg.tx_wm_reps:
            await self._chk_watermark(half, wm, fill)
        await self._chk_enable()
        self.logger.info("SPI host CSR/IRQ breadth ALL CHECKS PASS")

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
            f"polls, {_NEG_WINDOW_MARGIN}x the {calib}-poll enabled drain)"
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
            "%d polls (%dx the %d-poll enabled drain, TXQD stayed 1); CONTROL=0x%08x "
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
