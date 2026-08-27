# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CSR-only FMT/TX full and RX/ACQ empty. No pad traffic."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_FMTRST,
    I2C_FIFO_CTRL_RXRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_HOST_FIFO_STATUS_RXLVL_BM,
    I2C_HOST_FIFO_STATUS_RXLVL_BP,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_ACQFULL,
    I2C_STATUS_FMTFULL,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_RXEMPTY,
    I2C_STATUS_RXFULL,
    I2C_STATUS_TXEMPTY,
    I2C_STATUS_TXFULL,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)

CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)

_FMT_DEPTH = 64
_TX_DEPTH = 64
_TARGET_ADDR = 0x10
_STATUS_POLL_ITERS = 64
_STATUS_POLL_STEP_NS = 100


def _rx_lvl(status: int) -> int:
    return (int(status) & I2C_HOST_FIFO_STATUS_RXLVL_BM) >> (
        I2C_HOST_FIFO_STATUS_RXLVL_BP
    )


def _acq_lvl(status: int) -> int:
    return (int(status) & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> (
        I2C_TARGET_FIFO_STATUS_ACQLVL_BP
    )


def _target_id(address0: int, mask0: int = 0x7F) -> int:
    return (address0 & 0x7F) | ((mask0 & 0x7F) << 7)


class smc_i2c_fifo_full_test_seq(SmcCsrSeq):
    """FMT/TX full+empty and RX/ACQ empty STATUS proofs."""

    def __init__(self, name: str = "smc_i2c_fifo_full_test_seq") -> None:
        super().__init__(name)
        self.fmt_ok: bool = False
        self.rx_ok: bool = False
        self.tx_ok: bool = False
        self.acq_ok: bool = False

    def _addr(self, symbol: str, idx: int) -> int:
        return smc_indexed_addr(symbol, idx)

    async def _await_status(
        self,
        label: str,
        status_a: int,
        *,
        want_set: int = 0,
        want_clear: int = 0,
    ) -> int:
        """Poll STATUS until want_set bits are 1 and want_clear bits are 0."""
        st = 0
        for i in range(_STATUS_POLL_ITERS):
            st = await self.csr_read(f"{label}_{i}", status_a)
            if (st & want_set) == want_set and (st & want_clear) == 0:
                return st
            await Timer(_STATUS_POLL_STEP_NS, units="ns")
        raise AssertionError(
            f"{label} timeout STATUS=0x{st:08x} "
            f"want_set=0x{want_set:x} want_clear=0x{want_clear:x}"
        )

    async def _await_lvl_zero(
        self, label: str, lvl_a: int, lvl_fn
    ) -> None:
        lvl = -1
        for i in range(_STATUS_POLL_ITERS):
            lvl = lvl_fn(await self.csr_read(f"{label}_{i}", lvl_a))
            if lvl == 0:
                return
            await Timer(_STATUS_POLL_STEP_NS, units="ns")
        raise AssertionError(f"{label} level stuck at {lvl}")

    async def _test_fmt(self) -> None:
        idx = 0
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        fdata_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", idx)

        await self.csr_write("FMT_RST", fifo_a, I2C_FIFO_CTRL_FMTRST)
        await self._await_status(
            "FMT_EMPTY0",
            status_a,
            want_set=I2C_STATUS_FMTEMPTY,
            want_clear=I2C_STATUS_FMTFULL,
        )

        for i in range(_FMT_DEPTH + 10):
            st = await self.csr_read(f"FMT_FILL_ST_{i}", status_a)
            if st & I2C_STATUS_FMTFULL:
                break
            await self.csr_write(f"FMT_FDATA_{i}", fdata_a, 0xAA + (i & 0xFF))
        else:
            raise AssertionError("FMTFULL never set while filling FDATA")

        await self._await_status(
            "FMT_FULL", status_a, want_set=I2C_STATUS_FMTFULL
        )

        await self.csr_write("FMT_RST2", fifo_a, I2C_FIFO_CTRL_FMTRST)
        await self._await_status(
            "FMT_EMPTY1",
            status_a,
            want_set=I2C_STATUS_FMTEMPTY,
            want_clear=I2C_STATUS_FMTFULL,
        )
        cocotb.log.info("CHK-I2C-FIFO-FULL-FMT: FMTFULL then FMTEMPTY after reset")
        self.fmt_ok = True

    async def _test_rx_empty(self) -> None:
        idx = 0
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        host_fifo = self._addr(
            "SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR", idx
        )

        await self.csr_write("RX_RST", fifo_a, I2C_FIFO_CTRL_RXRST)
        await self._await_status(
            "RX_ST",
            status_a,
            want_set=I2C_STATUS_RXEMPTY,
            want_clear=I2C_STATUS_RXFULL,
        )
        await self._await_lvl_zero("RX_LVL", host_fifo, _rx_lvl)
        cocotb.log.info("CHK-I2C-FIFO-FULL-RX: RXEMPTY after RXRST")
        self.rx_ok = True

    async def _test_tx(self) -> None:
        idx = 1
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        tx_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", idx)

        await self.csr_write("TX_RST", fifo_a, I2C_FIFO_CTRL_TXRST)
        await self._await_status(
            "TX_EMPTY0",
            status_a,
            want_set=I2C_STATUS_TXEMPTY,
            want_clear=I2C_STATUS_TXFULL,
        )

        for i in range(_TX_DEPTH + 10):
            st = await self.csr_read(f"TX_FILL_ST_{i}", status_a)
            if st & I2C_STATUS_TXFULL:
                break
            await self.csr_write(f"TX_DATA_{i}", tx_a, 0xBB + (i & 0xFF))
        else:
            raise AssertionError("TXFULL never set while filling TXDATA")

        await self._await_status(
            "TX_FULL", status_a, want_set=I2C_STATUS_TXFULL
        )

        await self.csr_write("TX_RST2", fifo_a, I2C_FIFO_CTRL_TXRST)
        await self._await_status(
            "TX_EMPTY1",
            status_a,
            want_set=I2C_STATUS_TXEMPTY,
            want_clear=I2C_STATUS_TXFULL,
        )
        cocotb.log.info("CHK-I2C-FIFO-FULL-TX: TXFULL then TXEMPTY after reset")
        self.tx_ok = True

    async def _test_acq_empty(self) -> None:
        idx = 1
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        tgt_fifo = self._addr(
            "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR", idx
        )

        await self.csr_write("ACQ_RST", fifo_a, I2C_FIFO_CTRL_ACQRST)
        await self._await_status(
            "ACQ_ST",
            status_a,
            want_set=I2C_STATUS_ACQEMPTY,
            want_clear=I2C_STATUS_ACQFULL,
        )
        await self._await_lvl_zero("ACQ_LVL", tgt_fifo, _acq_lvl)
        cocotb.log.info("CHK-I2C-FIFO-FULL-ACQ: ACQEMPTY after ACQRST")
        self.acq_ok = True

    async def body(self) -> None:
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        wrap0 = self._addr(
            "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0
        )
        wrap1 = self._addr(
            "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 1
        )
        await self.csr_write("I2C0_WRAP_HOST", wrap0, I2C_WRAP_CTRL_HOST)
        await self.csr_write("I2C1_WRAP_TGT", wrap1, I2C_WRAP_CTRL_TARGET)

        # Leave ENABLEHOST=0 so FMT fills do not drain onto the bus.
        await self.csr_write(
            "I2C0_CTRL",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            0,
        )
        await self.csr_write(
            "I2C1_TARGET_ID",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 1),
            _target_id(_TARGET_ADDR),
        )
        await self.csr_write(
            "I2C1_CTRL",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        await self._test_fmt()
        await self._test_rx_empty()
        await self._test_tx()
        await self._test_acq_empty()
        cocotb.log.info(
            "CHK-I2C-FIFO-FULL-BASIC: fmt=%s rx=%s tx=%s acq=%s",
            self.fmt_ok,
            self.rx_ok,
            self.tx_ok,
            self.acq_ok,
        )
