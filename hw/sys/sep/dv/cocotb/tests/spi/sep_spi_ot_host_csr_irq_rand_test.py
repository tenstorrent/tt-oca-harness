# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OpenTitan-SPI host control-plane CSR / IRQ / error breadth (PyUVM, no_cpu).

SPI host CSR/IRQ breadth. A combined-per-group `[RAND-REP]` that folds the
reference suite OT-SPI host-control directed family (fw spi_ot_reg / tx_fifo /
cmd_queue / interrupt / error_handling / watermark / enable_disable) into ONE rep.
Not folded, because nothing here checks them: clock_config (CFG.CLKDIV is
R/W-walked but no transfer runs at a programmed divider), rx_fifo (the only RX
touch is the empty-FIFO read that triggers UNDERFLOW), and mux_select (a no-op --
the OT SPI host is already the active bare-SEP path). Drives the SEP-integrated spi_controller host CSRs
(@0x10B0_0000, NUM_CS=1) directly over the CPU-LSU AXI splice (no_cpu, no
firmware, no flash BFM) -- this is the host CONTROL plane, DISTINCT from SPI flash command breadth
(flash command datapath) and `sep_spi_ot_dma_rx_test` (flash READ + DMA).

Randomization (SINGLE source of randomness): SepSpiHostCfg seeds
legal field values for the register R/W walk + the watermark threshold from the
runner seed. The golden is the documented reset values + RW/W1C/RO field semantics
(seq_lib/sep_spi_host_csr_seq.py, taken from the generated spi_controller reg
block).

Checks (each emits a positive CHK-X PASS line; assert fails the test on a bad DUT):
  CHK-RESET     : every control/status reg reads its documented reset value.
  CHK-REG-RW    : each RW reg write->readback exact; bits outside the writable
                  mask (RO/reserved) read 0.
  CHK-INTR      : INTR_STATUS is a live mirror, (source | INTR_TEST) & INTR_ENABLE.
                  INTR_TEST reaches INTR_STATUS only while INTR_ENABLE is set, and
                  clearing the source deasserts it. There is no W1C on this register.
  CHK-ERR-W1C   : each drivable ERROR_STATUS bit is set by its exact trigger and
                  W1C-clears -- UNDERFLOW (read empty RXDATA), CMDINVAL (CMD
                  SPEED=reserved), CSIDINVAL (CSID>=NUM_CS + CMD), OVERFLOW (write
                  past the 72-deep TX FIFO with the core disabled), CMDBUSY
                  (command FIFO full), ACCESSINVAL (3-byte TXDATA beat).
  CHK-WATERMARK : STATUS.TXWM moves as the TX FIFO occupancy crosses TX_WATERMARK
                  (occupancy proven by STATUS.TXQD).
  CHK-ENABLE    : SPIEN=0 holds a queued TX command off (FIFO not drained);
                  SPIEN=1 lets it execute (FIFO drains).
  CHK-NONVAC    : every walked reg reads back different from its observed pre-write
                  value, so no entry in the walk is a no-op against a tied-off decode.

RXWM and irq-line delivery are covered by the RX-path tests
(`sep_spi_ot_flash_cmd_rand_test` / `sep_spi_ot_dma_rx_test`) and the delivery
tests (`sep_irq_ip_to_aggregator_test`).

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    CMD,
    CMD_DIR_TX,
    CMD_FIFO_DEPTH,
    CMD_SPEED_RESERVED,
    CSID,
    CTRL,
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
    INTR_STATUS,
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
    TX_FIFO_DEPTH,
    TXDATA,
    SepSpiHost,
    SepSpiHostCfg,
)

# Bounded-wait budgets. Every one of these fails its own checker on expiry.
# CHK-ENABLE's negative window is not a constant: it is _NEG_WINDOW_MARGIN times
# the drain latency the enabled leg measures on this build.
_DRAIN_POLLS = 200
_ENABLED_POLLS = 2000
_NEG_WINDOW_MARGIN = 4


@pyuvm.test()
class sep_spi_ot_host_csr_irq_rand_test(sep_base_test):
    """Walk the OT SPI host control plane (CSR/IRQ/error/watermark/enable)."""

    async def run_scenario(self) -> None:
        self.scfg = SepSpiHostCfg(self.random_seed())
        self.spi = SepSpiHost(self)
        self.logger.info("SPI host CSR config: %s", self.scfg.summary())

        await self.bring_up_no_cpu()

        await self._chk_reset()
        await self._chk_reg_rw()
        await self._chk_intr()
        await self._chk_err_w1c()
        await self._chk_watermark()
        await self._chk_enable()
        self.logger.info("SPI host CSR/IRQ breadth ALL CHECKS PASS")

    # ---- helpers ----------------------------------------------------------
    async def _sw_rst_pulse(self) -> None:
        """Hold then release the core soft-reset, then confirm both FIFOs drained.

        spi_controller.rdl documents that SW_RST drains the CDC FIFOs rather than
        resetting them, and that software must confirm both are empty before
        releasing the IP. A release with residue left in the TX FIFO would make
        the occupancy assertions in the watermark and CMDBUSY facets read a depth
        this test did not create, so the drain is checked here rather than assumed.
        """
        await self.spi.wr(CTRL, CTRL_RESET | CTRL_SW_RST)
        await self.spi.wr(CTRL, CTRL_RESET)
        for _ in range(_DRAIN_POLLS):
            st = await self.spi.rd(STATUS)
            if (st & ST_TXEMPTY) and (st & ST_RXEMPTY) and (st & (ST_TXQD | ST_RXQD)) == 0:
                return
        raise AssertionError(
            f"SW_RST released but the FIFOs did not drain in {_DRAIN_POLLS} polls "
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
            # The reference for CHK-NONVAC is the observed pre-write value, not the
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
            # not from wmask: CTRL's SW_RST is implemented but outside the walk,
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

    # ---- CHK-INTR ---------------------------------------------------------
    async def _chk_intr(self) -> None:
        # spi_controller.rdl INTR_STATUS: each bit is
        #   (source | INTR_TEST) & INTR_ENABLE
        # so INTR_ENABLE gates the status bit itself (not just the irq line), and
        # clearing the source/test deasserts it (no W1C). Prove the INTR_TEST path
        # AND the INTR_ENABLE mask for both bits. EVENT_ENABLE/ERROR_STATUS are
        # clean here, so INTR_TEST is the only source.
        await self._clear_error_status()
        for label, bit in (("ERROR", INTR_ERROR), ("SPI_EVENT", INTR_SPI_EVENT)):
            # Cleanliness is only observable with the enable SET: INTR_STATUS is
            # ANDed with INTR_ENABLE, so a read taken with the enable clear reads
            # zero whatever the source is doing.
            await self.spi.wr(INTR_TEST, 0)
            await self.spi.wr(INTR_ENABLE, bit)
            st = await self.spi.rd(INTR_STATUS)
            assert not (st & bit), (
                f"CHK-INTR {label}: INTR_STATUS set with the source and INTR_TEST "
                f"both clear (0x{st:08x})"
            )
            # test asserted but disabled -> masked off.
            await self.spi.wr(INTR_ENABLE, 0)
            await self.spi.wr(INTR_TEST, bit)
            st = await self.spi.rd(INTR_STATUS)
            assert not (st & bit), (
                f"CHK-INTR {label}: INTR_ENABLE=0 did not mask INTR_TEST (0x{st:08x})"
            )
            # enable -> the test source now reaches INTR_STATUS.
            await self.spi.wr(INTR_ENABLE, bit)
            st = await self.spi.rd(INTR_STATUS)
            assert st & bit, (
                f"CHK-INTR {label}: enabled INTR_TEST did not set INTR_STATUS (0x{st:08x})"
            )
            # remove the source -> deasserts.
            await self.spi.wr(INTR_TEST, 0)
            st = await self.spi.rd(INTR_STATUS)
            assert not (st & bit), (
                f"CHK-INTR {label}: clearing INTR_TEST did not deassert (0x{st:08x})"
            )
            await self.spi.wr(INTR_ENABLE, 0)
        self.logger.info(
            "CHK-INTR PASS: INTR_TEST->INTR_STATUS gated by INTR_ENABLE "
            "(mask proven), source-clear deasserts; ERROR+SPI_EVENT"
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
        # raises every error bit on any stimulus passes all six sub-checks.
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
            await self.spi.wr(CMD, CMD_DIR_TX | CMD_SPEED_RESERVED)  # SPEED=reserved

        async def trig_csidinval():
            await self.spi.wr(CSID, 1)  # >= NUM_CS(1)
            await self.spi.wr(CMD, CMD_DIR_TX)  # otherwise-legal command
            await self.spi.wr(CSID, 0)  # restore

        async def trig_overflow():
            # Disable the core here rather than inheriting SPIEN=0 from an earlier
            # facet, so the TX FIFO never drains; write past its depth -> the
            # over-writes assert ERROR_STATUS.OVERFLOW.
            await self.spi.wr(CTRL, CTRL_RESET)
            for _ in range(TX_FIFO_DEPTH + 8):
                await self.spi.wr(TXDATA, 0x5A5A_5A5A)

        async def trig_cmdbusy():
            # Command FIFO is 4 deep. Enable the core with an empty TX FIFO so
            # each TX command stalls in the queue; the write that finds it full
            # sets ERROR_STATUS.CMDBUSY.
            await self.spi.wr(CTRL, CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN)
            for _ in range(CMD_FIFO_DEPTH + 2):
                await self.spi.wr(CMD, CMD_DIR_TX)

        async def trig_accessinval():
            # RTL access_valid accepts 1/2/4-byte contiguous strobes, not 3-byte
            # 4'b0111. A 32-bit beat of length 3 is a real DUT write, not a
            # non-contiguous strobe the AXI master cannot express.
            await self.spi.wr(
                TXDATA, 0x00A5A5A5, length=3, size=2, allow_unverified_write_resp=True
            )

        await self._trigger_err("UNDERFLOW", ERR_UNDERFLOW, trig_underflow)
        await self._trigger_err("CMDINVAL", ERR_CMDINVAL, trig_cmdinval)
        await self._trigger_err("CSIDINVAL", ERR_CSIDINVAL, trig_csidinval)
        await self._trigger_err("OVERFLOW", ERR_OVERFLOW, trig_overflow)
        await self._sw_rst_pulse()  # drain the full TX FIFO
        await self._trigger_err("CMDBUSY", ERR_CMDBUSY, trig_cmdbusy)
        await self._sw_rst_pulse()
        await self._trigger_err("ACCESSINVAL", ERR_ACCESSINVAL, trig_accessinval)
        await self._sw_rst_pulse()
        self.logger.info(
            "CHK-ERR-W1C PASS: UNDERFLOW/CMDINVAL/CSIDINVAL/OVERFLOW/"
            "CMDBUSY/ACCESSINVAL each set by their trigger + W1C-clear"
        )

    # ---- CHK-WATERMARK ----------------------------------------------------
    async def _chk_watermark(self) -> None:
        await self._sw_rst_pulse()
        # Program TX_WATERMARK; keep core disabled so the FIFO does not drain.
        ctrl = CTRL_RESET | (self.scfg.tx_watermark << CTRL_TX_WM_LSB)
        await self.spi.wr(CTRL, ctrl)
        st_empty = await self.spi.rd(STATUS)
        assert (st_empty & ST_TXQD) == 0, f"CHK-WATERMARK FIFO not empty: 0x{st_empty:08x}"
        # RTL: tx_wm = tx_qd < tx_watermark (asserted while there is room below the mark).
        assert st_empty & ST_TXWM, (
            f"CHK-WATERMARK STATUS.TXWM clear while TXQD=0 < wm (0x{st_empty:08x})"
        )
        wm = self.scfg.tx_watermark
        for _ in range(wm - 1):
            await self.spi.wr(TXDATA, 0xA5A5_A5A5)
        st_below = await self.spi.rd(STATUS)
        assert st_below & ST_TXWM, (
            f"CHK-WATERMARK STATUS.TXWM clear at TXQD={st_below & ST_TXQD} < wm={wm} "
            f"(0x{st_below:08x})"
        )
        await self.spi.wr(TXDATA, 0xA5A5_A5A5)  # the word that reaches the threshold
        st_at = await self.spi.rd(STATUS)
        assert not (st_at & ST_TXWM), (
            f"CHK-WATERMARK STATUS.TXWM still set at TXQD={st_at & ST_TXQD} == wm={wm} "
            f"(0x{st_at:08x})"
        )
        extra = self.scfg.tx_fill_words - wm
        for _ in range(extra):
            await self.spi.wr(TXDATA, 0xA5A5_A5A5)
        st_full = await self.spi.rd(STATUS)
        txqd = st_full & ST_TXQD
        assert txqd == self.scfg.tx_fill_words, (
            f"CHK-WATERMARK TXQD 0x{txqd:x} != filled {self.scfg.tx_fill_words}"
        )
        assert not (st_full & ST_TXWM), (
            f"CHK-WATERMARK STATUS.TXWM set after filling past wm={wm} (0x{st_full:08x})"
        )
        self.logger.info(
            "CHK-WATERMARK PASS: TXWM 1->0 at exact wm=%d (TXQD %d->%d->%d, tx_wm = qd < wm)",
            wm,
            wm - 1,
            wm,
            txqd,
        )
        await self._sw_rst_pulse()

    # ---- CHK-ENABLE -------------------------------------------------------
    async def _queue_one_tx(self) -> None:
        """Leave exactly one word in the TX FIFO with a TX command queued."""
        await self._sw_rst_pulse()
        await self.spi.wr(TXDATA, 0xDEAD_BEEF)
        st = await self.spi.rd(STATUS)
        assert (st & ST_TXQD) == 1, f"one TXDATA write left TXQD={st & ST_TXQD} (0x{st:08x})"
        await self.spi.wr(CMD, CMD_DIR_TX)

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
        await self.spi.wr(CTRL, CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN)
        calib = await self._poll_drain(_ENABLED_POLLS)
        assert calib, (
            f"CHK-ENABLE: the queued command did not execute with SPIEN=1 within "
            f"{_ENABLED_POLLS} polls -- cannot calibrate the negative window"
        )
        window = _NEG_WINDOW_MARGIN * calib

        # Negative leg: same stimulus, SPIEN=0, held for the calibrated window.
        await self._queue_one_tx()  # _sw_rst_pulse leaves SPIEN=0
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

        # Positive leg: enabling the core releases that same queued command.
        await self.spi.wr(CTRL, CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN)
        released = await self._poll_drain(_ENABLED_POLLS)
        assert released, "CHK-ENABLE: command did not execute after SPIEN=1"
        self.logger.info(
            "CHK-ENABLE PASS: SPIEN=0 held the command for %d polls (%dx the %d-poll "
            "enabled drain, TXQD stayed 1); SPIEN=1 drained it in %d",
            window,
            _NEG_WINDOW_MARGIN,
            calib,
            released,
        )
        await self._sw_rst_pulse()
        await self._clear_error_status()
