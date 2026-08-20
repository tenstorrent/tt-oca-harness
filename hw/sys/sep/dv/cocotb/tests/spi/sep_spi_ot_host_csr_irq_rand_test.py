# SPDX-License-Identifier: Apache-2.0
"""SEP OpenTitan-SPI host control-plane CSR / IRQ / error breadth (PyUVM, no_cpu).

SPI-subsystem Phase-2 rep SPI host CSR/IRQ breadth. A combined-per-group `[RAND-REP]` that folds the
reference suite OT-SPI host-control directed family (fw spi_ot_reg / clock_config / tx_fifo /
rx_fifo / cmd_queue / interrupt / error_handling / watermark / enable_disable /
mux_select) into ONE rep. Drives the SEP-integrated spi_controller host CSRs
(@0x10B0_0000, NUM_CS=1) directly over the CPU-LSU AXI splice (no_cpu, no
firmware, no flash BFM) -- this is the host CONTROL plane, DISTINCT from SPI flash command breadth
(flash command datapath) and #3 sep_spi_ot_dma_rx (flash READ + DMA).

Randomization (SINGLE source of randomness; AGENTS.md s9/s11): SepSpiHostCfg seeds
legal field values for the register R/W walk + the watermark threshold from the
runner seed. The golden is the documented reset values + RW/W1C/RO field semantics
(seq_lib/sep_spi_host_csr_seq.py, taken from the generated spi_controller reg
block).

Checks (each emits a positive CHK-X PASS line; assert fails the test on a bad DUT):
  CHK-RESET     : every control/status reg reads its documented reset value.
  CHK-REG-RW    : each RW reg write->readback exact; bits outside the writable
                  mask (RO/reserved) read 0.
  CHK-INTR      : INTR_TEST write-1 sets INTR_STATUS (ERROR, SPI_EVENT); W1C clears.
  CHK-ERR-W1C   : each drivable ERROR_STATUS bit is set by its exact trigger and
                  W1C-clears -- UNDERFLOW (read empty RXDATA), CMDINVAL (CMD
                  SPEED=reserved), CSIDINVAL (CSID>=NUM_CS + CMD), OVERFLOW (write
                  past the 72-deep TX FIFO with the core disabled).
  CHK-WATERMARK : STATUS.TXWM moves as the TX FIFO occupancy crosses TX_WATERMARK
                  (occupancy proven by STATUS.TXQD).
  CHK-ENABLE    : SPIEN=0 holds a queued TX command off (FIFO not drained);
                  SPIEN=1 lets it execute (FIFO drains).
  CHK-NONVAC    : a written reg reads back different from its reset value.

Deferred (documented, not silently dropped): ERROR_STATUS.CMDBUSY (needs a command
issued mid-busy -- timing) and .ACCESSINVAL (needs a non-contiguous TXDATA
byte-enable, which cocotbext-axi cannot express) are [GAP (deferred)]; RXWM and
the irq-line delivery are covered by the RX-path tests (#3, SPI flash command breadth) / delivery
tests (#14). the reference suite's mux-select is an OSS no-op (the OT SPI path is already the
active bare-SEP path).

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_spi_host_csr_seq import (
    SepSpiHostCfg, SepSpiHost, RESET_VALUES,
    STATUS, RXDATA, TXDATA, CMD, CTRL, CSID, CFG,
    INTR_STATUS, INTR_ENABLE, INTR_TEST, ERROR_STATUS,
    INTR_ERROR, INTR_SPI_EVENT,
    ERR_OVERFLOW, ERR_UNDERFLOW, ERR_CMDINVAL, ERR_CSIDINVAL, TX_FIFO_DEPTH,
    CMD_DIR_TX, CMD_SPEED_RESERVED,
    CTRL_SW_RST, CTRL_SPIEN, CTRL_OUTPUT_EN,
    ST_READY, ST_ACTIVE, ST_TXEMPTY, ST_RXEMPTY, ST_TXFULL, ST_RXFULL,
    ST_TXQD, ST_RXQD, ST_CMDQD, ST_TXWM,
)

_CTRL_RESET = 0x0000_007F


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
        """Hold then release the core soft-reset (clears FIFOs/state)."""
        await self.spi.wr(CTRL, _CTRL_RESET | CTRL_SW_RST)
        await self.spi.wr(CTRL, _CTRL_RESET)

    async def _clear_error_status(self) -> None:
        await self.spi.wr(ERROR_STATUS, 0x00FF_FFFF)

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
        assert not (st & (ST_TXQD | ST_RXQD | ST_CMDQD)), \
            f"CHK-RESET STATUS queue depths nonzero: 0x{st:08x}"
        self.logger.info("CHK-RESET PASS: %d control regs at documented reset + "
                         "STATUS idle (0x%08x)", len(RESET_VALUES), st)

    # ---- CHK-REG-RW (+ CHK-NONVAC) ---------------------------------------
    async def _chk_reg_rw(self) -> None:
        nonvac_seen = False
        for name, addr, wmask, val in self.scfg.rw_regs:
            # Observe the pre-write value rather than trusting the RESET_VALUES table.
            # CHK-NONVAC used to compare the readback against that table, but the
            # readback had already been asserted == val, so it reduced to
            # `val != RESET_VALUES[name]` -- this run's seeded random number against a
            # file-scope constant, with no DUT term left. Anchoring on an observed read
            # makes it a real statement about the register.
            pre = await self.spi.rd(addr)
            await self.spi.wr(addr, val)
            rb = await self.spi.rd(addr)
            assert rb == val, (f"CHK-REG-RW {name}@0x{addr:08x} readback 0x{rb:08x} "
                               f"!= written 0x{val:08x} (wmask 0x{wmask:08x})")
            # Probe the RO/reserved bits by writing them. Checking `rb & ~wmask == 0`
            # after `rb == val` proved nothing: val is built as getrandbits(32) & wmask,
            # so those bits were zero before the DUT ever saw them.
            if (~wmask & 0xFFFF_FFFF) != 0:
                await self.spi.wr(addr, val | (~wmask & 0xFFFF_FFFF))
                rb2 = await self.spi.rd(addr)
                assert (rb2 & ~wmask & 0xFFFF_FFFF) == 0, (
                    f"CHK-REG-RW {name} reserved bits are writable: "
                    f"0x{rb2 & ~wmask & 0xFFFF_FFFF:08x}")
                assert (rb2 & wmask) == val, (
                    f"CHK-REG-RW {name} writable bits disturbed by a reserved-bit "
                    f"write: 0x{rb2 & wmask:08x} != 0x{val:08x}")
            if rb != pre:
                nonvac_seen = True
        self.logger.info("CHK-REG-RW PASS: %d RW regs write->readback exact, "
                         "reserved bits reject writes", len(self.scfg.rw_regs))
        assert nonvac_seen, (
            "CHK-NONVAC: no register's readback differed from its observed pre-write "
            "value -- the writes changed nothing observable")
        self.logger.info(
            "CHK-NONVAC PASS: a written reg differs from its observed pre-write value")
        # Restore every walked reg to its reset value for the later facets.
        for name, addr, _, _ in self.scfg.rw_regs:
            if name in RESET_VALUES:
                await self.spi.wr(addr, RESET_VALUES[name][1])
            else:
                await self.spi.wr(addr, 0)

    # ---- CHK-INTR ---------------------------------------------------------
    async def _chk_intr(self) -> None:
        # This spi_controller drives INTR_STATUS as a LIVE mirror:
        #   INTR_STATUS.X = (source_X | INTR_TEST.X) & INTR_ENABLE.X
        # so INTR_ENABLE gates the state bit itself (not just the irq line), and
        # clearing the source/test deasserts it (no W1C). Prove the INTR_TEST path
        # AND the INTR_ENABLE mask for both bits. EVENT_ENABLE/ERROR_STATUS are
        # clean here, so INTR_TEST is the only source.
        await self._clear_error_status()
        for label, bit in (("ERROR", INTR_ERROR), ("SPI_EVENT", INTR_SPI_EVENT)):
            await self.spi.wr(INTR_ENABLE, 0)
            await self.spi.wr(INTR_TEST, 0)
            st = await self.spi.rd(INTR_STATUS)
            assert not (st & bit), f"CHK-INTR {label}: INTR_STATUS not clean (0x{st:08x})"
            # test asserted but disabled -> masked off.
            await self.spi.wr(INTR_TEST, bit)
            st = await self.spi.rd(INTR_STATUS)
            assert not (st & bit), \
                f"CHK-INTR {label}: INTR_ENABLE=0 did not mask INTR_TEST (0x{st:08x})"
            # enable -> the test source now reaches INTR_STATUS.
            await self.spi.wr(INTR_ENABLE, bit)
            st = await self.spi.rd(INTR_STATUS)
            assert st & bit, \
                f"CHK-INTR {label}: enabled INTR_TEST did not set INTR_STATUS (0x{st:08x})"
            # remove the source -> deasserts.
            await self.spi.wr(INTR_TEST, 0)
            st = await self.spi.rd(INTR_STATUS)
            assert not (st & bit), \
                f"CHK-INTR {label}: clearing INTR_TEST did not deassert (0x{st:08x})"
            await self.spi.wr(INTR_ENABLE, 0)
        self.logger.info("CHK-INTR PASS: INTR_TEST->INTR_STATUS gated by INTR_ENABLE "
                         "(mask proven), source-clear deasserts; ERROR+SPI_EVENT")

    # ---- CHK-ERR-W1C ------------------------------------------------------
    async def _trigger_err(self, label: str, bit: int, trigger) -> None:
        await self._clear_error_status()
        es = await self.spi.rd(ERROR_STATUS)
        assert es == 0, f"CHK-ERR-W1C {label}: ERROR_STATUS not clean pre-trigger (0x{es:08x})"
        await trigger()
        es = await self.spi.rd(ERROR_STATUS)
        assert es & bit, f"CHK-ERR-W1C {label}: bit 0x{bit:06x} not set (ERROR_STATUS 0x{es:08x})"
        await self.spi.wr(ERROR_STATUS, bit)                 # W1C the exact bit
        es = await self.spi.rd(ERROR_STATUS)
        assert not (es & bit), f"CHK-ERR-W1C {label}: W1C did not clear (0x{es:08x})"

    async def _chk_err_w1c(self) -> None:
        async def trig_underflow():
            await self.spi.rd(RXDATA)                        # read empty RX FIFO

        async def trig_cmdinval():
            await self.spi.wr(CSID, 0)
            await self.spi.wr(CMD, CMD_DIR_TX | CMD_SPEED_RESERVED)  # SPEED=reserved

        async def trig_csidinval():
            await self.spi.wr(CSID, 1)                       # >= NUM_CS(1)
            await self.spi.wr(CMD, CMD_DIR_TX)               # otherwise-legal command
            await self.spi.wr(CSID, 0)                       # restore

        async def trig_overflow():
            # Core disabled (SPIEN=0) so the TX FIFO never drains; write past its
            # depth -> the over-writes assert ERROR_STATUS.OVERFLOW.
            for _ in range(TX_FIFO_DEPTH + 8):
                await self.spi.wr(TXDATA, 0x5A5A_5A5A)

        await self._trigger_err("UNDERFLOW", ERR_UNDERFLOW, trig_underflow)
        await self._trigger_err("CMDINVAL", ERR_CMDINVAL, trig_cmdinval)
        await self._trigger_err("CSIDINVAL", ERR_CSIDINVAL, trig_csidinval)
        await self._trigger_err("OVERFLOW", ERR_OVERFLOW, trig_overflow)
        await self._sw_rst_pulse()                           # drain the full TX FIFO
        self.logger.info("CHK-ERR-W1C PASS: UNDERFLOW/CMDINVAL/CSIDINVAL/OVERFLOW each "
                         "set by their trigger + W1C-clear. CMDBUSY/ACCESSINVAL deferred "
                         "(mid-command timing / non-contiguous byte-enable infra-gated).")

    # ---- CHK-WATERMARK ----------------------------------------------------
    async def _chk_watermark(self) -> None:
        await self._sw_rst_pulse()
        # Program TX_WATERMARK; keep core disabled so the FIFO does not drain.
        ctrl = _CTRL_RESET | (self.scfg.tx_watermark << 8)
        await self.spi.wr(CTRL, ctrl)
        st_empty = await self.spi.rd(STATUS)
        assert (st_empty & ST_TXQD) == 0, f"CHK-WATERMARK FIFO not empty: 0x{st_empty:08x}"
        txwm_empty = bool(st_empty & ST_TXWM)
        for _ in range(self.scfg.tx_fill_words):
            await self.spi.wr(TXDATA, 0xA5A5_A5A5)
        st_full = await self.spi.rd(STATUS)
        txqd = st_full & ST_TXQD
        assert txqd == self.scfg.tx_fill_words, (
            f"CHK-WATERMARK TXQD 0x{txqd:x} != filled {self.scfg.tx_fill_words}")
        txwm_full = bool(st_full & ST_TXWM)
        assert txwm_empty != txwm_full, (
            f"CHK-WATERMARK STATUS.TXWM did not move across threshold "
            f"{self.scfg.tx_watermark} (empty={txwm_empty} full={txwm_full})")
        self.logger.info("CHK-WATERMARK PASS: TXWM moved %s->%s as TXQD crossed wm=%d "
                         "(filled %d)", txwm_empty, txwm_full, self.scfg.tx_watermark,
                         self.scfg.tx_fill_words)
        await self._sw_rst_pulse()

    # ---- CHK-ENABLE -------------------------------------------------------
    async def _chk_enable(self) -> None:
        await self._sw_rst_pulse()                           # clean, SPIEN=0
        await self.spi.wr(TXDATA, 0xDEAD_BEEF)               # one word into TX FIFO
        st = await self.spi.rd(STATUS)
        assert not (st & ST_TXEMPTY), f"CHK-ENABLE TX FIFO unexpectedly empty: 0x{st:08x}"
        await self.spi.wr(CMD, CMD_DIR_TX)                   # queue a 1-byte TX command
        drained_disabled = False
        for _ in range(50):
            st = await self.spi.rd(STATUS)
            if st & ST_TXEMPTY:
                drained_disabled = True
                break
        assert not drained_disabled, "CHK-ENABLE: command executed while SPIEN=0"
        # Enable -> the queued command runs -> FIFO drains.
        await self.spi.wr(CTRL, _CTRL_RESET | CTRL_SPIEN | CTRL_OUTPUT_EN)
        drained_enabled = False
        for _ in range(2000):
            st = await self.spi.rd(STATUS)
            if st & ST_TXEMPTY:
                drained_enabled = True
                break
        assert drained_enabled, "CHK-ENABLE: command did not execute after SPIEN=1"
        self.logger.info("CHK-ENABLE PASS: SPIEN=0 holds the command off; SPIEN=1 "
                         "drains the TX FIFO")
        await self._sw_rst_pulse()
        await self._clear_error_status()
