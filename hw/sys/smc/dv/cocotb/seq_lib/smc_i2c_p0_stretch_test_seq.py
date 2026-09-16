# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C1 READ with TX_STRETCH_CTRL_EN; I2C0 TX_PENDING then TXDATA. Requires +smc_i2c_shared_bus."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_TX_STRETCH_CTRL_EN,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_FMTFULL,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_STATUS_RXFULL,
    I2C_TARGET_EVENTS_TX_PENDING,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_TARGET_ADDR = 0x10
# Settle bound for the post-read host check, in peripheral clock cycles so it
# scales with the randomised clk_periph_i period instead of against it. One SCL
# bit is thigh(0x1A)+tlow(0x32)=76 periph cycles at the TIMING0 programmed below,
# so 512 cycles per poll x 64 polls covers ~430 SCL bits of settle margin.
HOSTIDLE_SETTLE_CYCLES = 512
HOSTIDLE_SETTLE_POLLS = 64

_READ0 = 0xB1


def _pack_timing0(thigh: int, tlow: int) -> int:
    return (thigh & 0x1FFF) | ((tlow & 0x1FFF) << 16)


def _pack_timing1(t_r: int, t_f: int) -> int:
    return (t_r & 0x3FF) | ((t_f & 0x1FF) << 16)


def _pack_timing2(tsu_sta: int, thd_sta: int) -> int:
    return (tsu_sta & 0x1FFF) | ((thd_sta & 0x1FFF) << 16)


def _pack_timing3(tsu_dat: int, thd_dat: int) -> int:
    return (tsu_dat & 0x1FF) | ((thd_dat & 0x1FFF) << 16)


def _pack_timing4(tsu_sto: int, t_buf: int) -> int:
    return (tsu_sto & 0x1FFF) | ((t_buf & 0x1FFF) << 16)


def _target_id(address0: int, mask0: int = 0x7F) -> int:
    return (address0 & 0x7F) | ((mask0 & 0x7F) << 7)


class smc_i2c_p0_stretch_test_seq(SmcCsrSeq):
    """Software TX stretch via TX_PENDING + host RX."""

    def __init__(self, name: str = "smc_i2c_p0_stretch_test_seq") -> None:
        super().__init__(name)
        self.stretch_ok: bool = False
        self.read_ok: bool = False
        # Byte the host actually received; compared against _READ0 below.
        self.rx_byte: int = -1

    def _idx_addr(self, symbol: str, idx: int) -> int:
        return smc_indexed_addr(symbol, idx)

    async def _program_timing(self, idx: int) -> None:
        await self.csr_write(
            f"I2C{idx}_TIMING0",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", idx),
            _pack_timing0(0x1A, 0x32),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING1",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", idx),
            _pack_timing1(2, 2),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING2",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", idx),
            _pack_timing2(5, 4),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING3",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", idx),
            _pack_timing3(2, 5),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING4",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", idx),
            _pack_timing4(4, 5),
        )

    async def _wait_tx_pending(self) -> None:
        ev_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_EVENTS_BASE_ADDR", 0)
        ev = 0
        for _ in range(800):
            ev = await self.csr_read("TX_PENDING", ev_addr)
            if ev & I2C_TARGET_EVENTS_TX_PENDING:
                cocotb.log.info("CHK-I2C-P0-STRETCH: TX_PENDING TARGET_EVENTS=0x%x", ev)
                return
            await Timer(5, units="us")
        raise AssertionError(f"TX_PENDING not seen TARGET_EVENTS=0x{ev:08x}")

    async def _wait_rx_byte(self) -> int:
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 1)
        rdata_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR", 1)
        status = 0
        for _ in range(800):
            status = await self.csr_read("RX_STATUS", status_addr)
            if not (status & I2C_STATUS_RXEMPTY):
                return int(await self.csr_read("RDATA", rdata_addr)) & 0xFF
            await Timer(5, units="us")
        raise AssertionError(f"RX empty after stretch release STATUS=0x{status:08x}")

    async def _wait_hostidle(self) -> None:
        """Bounded wait for the host controller to settle after the read.

        The host's busy window is not reliably observable here: ``_wait_rx_byte``
        returns only after it has polled STATUS and then read RDATA, and the host
        completes its STOP during those two CSR accesses, so whether the window
        is still visible depends on where the 5 us RX poll grid lands relative to
        a transaction whose duration scales with ``cfg.periph_clk_period_ns``
        (randomised by ``SmcEnvCfg.randomize_timing``). That the host executed
        the read on the bus is established by ``body``, which compares the byte
        ``_wait_rx_byte`` returns against ``_READ0``. This wait establishes the
        settled state as an exact expectation over the bits this scenario
        determines:

          HOSTIDLE  = 1  the host FSM finished the transfer
          FMTEMPTY  = 1  the format FIFO drained -- no queued command remains
          FMTFULL   = 0  (implied, asserted so a stuck-full FIFO is caught)
          RXEMPTY   = 1  ``_wait_rx_byte`` drained the byte via the RDATA read
          RXFULL    = 0  (implied, same reason)

        The bound is in peripheral clock cycles rather than absolute time, so it
        scales with the randomised clock instead of shrinking against it.
        """
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 1)
        settled_set = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY | I2C_STATUS_RXEMPTY
        settled_clear = I2C_STATUS_FMTFULL | I2C_STATUS_RXFULL
        status = 0
        for _ in range(HOSTIDLE_SETTLE_POLLS):
            status = await self.csr_read("HOST_IDLE", status_addr)
            if (status & settled_set) == settled_set and not (status & settled_clear):
                cocotb.log.info(
                    "CHK-I2C-P0-HOST-SETTLED: I2C1 STATUS=0x%08x -- HOSTIDLE, "
                    "FMTEMPTY and RXEMPTY set, FMTFULL/RXFULL clear after the "
                    "stretched read (bound=%d clk_periph_i cycles per poll)",
                    status,
                    HOSTIDLE_SETTLE_CYCLES,
                )
                return
            await ClockCycles(cocotb.top.clk_periph_i, HOSTIDLE_SETTLE_CYCLES)
        raise AssertionError(
            f"host did not settle: STATUS=0x{status:08x}, expected "
            f"0x{settled_set:08x} set and 0x{settled_clear:08x} clear within "
            f"{HOSTIDLE_SETTLE_POLLS} polls of {HOSTIDLE_SETTLE_CYCLES} "
            f"clk_periph_i cycles"
        )

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError("smc_i2c_p0_stretch_test requires +smc_i2c_shared_bus")

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        wrap0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
        await self.csr_write("I2C0_WRAP_TGT", wrap0, I2C_WRAP_CTRL_TARGET)
        await self._program_timing(0)
        await self.csr_write(
            "I2C0_TARGET_ID",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 0),
            _target_id(_TARGET_ADDR),
        )
        await self.csr_write(
            "I2C0_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST,
        )
        await self.csr_write(
            "I2C0_CTRL_TGT",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN | I2C_CTRL_TX_STRETCH_CTRL_EN,
        )

        wrap1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 1)
        await self.csr_write("I2C1_WRAP_HOST", wrap1, I2C_WRAP_CTRL_HOST)
        await self._program_timing(1)
        await self.csr_write(
            "I2C1_OVRD",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 1),
            0,
        )
        await self.csr_write(
            "I2C1_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 1),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            "I2C1_CTRL_HOST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            I2C_CTRL_ENABLEHOST,
        )

        fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 1)
        txdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", 0)
        ev_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_EVENTS_BASE_ADDR", 0)
        addr_r = (_TARGET_ADDR << 1) | 1

        await self.csr_write("I2C1_FDATA_START", fdata, I2C_FDATA_START | addr_r)
        await self.csr_write(
            "I2C1_FDATA_READB",
            fdata,
            I2C_FDATA_READB | I2C_FDATA_STOP | 1,
        )
        await self._wait_tx_pending()
        self.stretch_ok = True
        await self.csr_write("I2C0_TXDATA", txdata, _READ0)
        await self.csr_write("I2C0_CLR_TX_PENDING", ev_addr, I2C_TARGET_EVENTS_TX_PENDING)
        got = await self._wait_rx_byte()
        self.rx_byte = got
        if got != _READ0:
            raise AssertionError(f"RX got 0x{got:02x} expect 0x{_READ0:02x}")
        await self._wait_hostidle()
        self.read_ok = True
        cocotb.log.info("CHK-I2C-P0-STRETCH: TX_PENDING+RX PASS byte=0x%02x", got)

        await self.csr_write(
            "I2C0_CTRL_OFF",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            0,
        )
        await self.csr_write(
            "I2C1_CTRL_OFF",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            0,
        )
