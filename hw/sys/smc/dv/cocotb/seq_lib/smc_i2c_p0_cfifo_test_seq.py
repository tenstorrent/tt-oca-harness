# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FMT_THRESHOLD when FMTLVL=0 and FMT_THRESH>0. RX threshold is out of scope."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_HOST_FIFO_CONFIG_FMT_THRESH_BP,
    I2C_HOST_FIFO_STATUS_FMTLVL_BM,
    I2C_INTR_ENABLE_FMT_THRESHOLD,
    I2C_INTR_STATE_FMT_THRESHOLD,
    I2C_WRAP_CTRL_HOST,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_FMT_THRESH = 4


def _fmt_lvl(status: int) -> int:
    return int(status) & I2C_HOST_FIFO_STATUS_FMTLVL_BM


class smc_i2c_p0_cfifo_test_seq(SmcCsrSeq):
    """Controller FMT empty-threshold interrupt after FMTRST."""

    def __init__(self, name: str = "smc_i2c_p0_cfifo_test_seq") -> None:
        super().__init__(name)
        self.fmt_ok: bool = False

    def _idx_addr(self, symbol: str, idx: int) -> int:
        return smc_indexed_addr(symbol, idx)

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        wrap0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
        await self.csr_write("I2C0_WRAP_HOST", wrap0, I2C_WRAP_CTRL_HOST)
        await self.csr_write(
            "I2C0_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            "I2C0_HOST_FIFO_CFG",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_CONFIG_BASE_ADDR", 0),
            (_FMT_THRESH & 0xFFF) << I2C_HOST_FIFO_CONFIG_FMT_THRESH_BP,
        )
        await self.csr_write(
            "I2C0_INTR_ENABLE",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0),
            I2C_INTR_ENABLE_FMT_THRESHOLD,
        )
        await self.csr_write(
            "I2C0_INTR_CLR",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0),
            0xFFFFFFFF,
        )

        fifo_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR", 0)
        intr_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
        fifo_st = 0
        intr = 0
        lvl = 0
        for _ in range(200):
            fifo_st = await self.csr_read("I2C0_HOST_FIFO_STATUS", fifo_addr)
            intr = await self.csr_read("I2C0_INTR_STATE", intr_addr)
            lvl = _fmt_lvl(fifo_st)
            if lvl < _FMT_THRESH and (intr & I2C_INTR_STATE_FMT_THRESHOLD):
                cocotb.log.info(
                    "CHK-I2C-P0-CFIFO: FMTLVL=%d < thresh=%d INTR_STATE.FMT_THRESHOLD fifo_st=0x%x",
                    lvl,
                    _FMT_THRESH,
                    fifo_st,
                )
                self.fmt_ok = True
                return
            await Timer(1, unit="us")
        raise AssertionError(
            f"FMT_THRESHOLD not seen FMTLVL={lvl} thresh={_FMT_THRESH} "
            f"INTR=0x{intr:08x} fifo_st=0x{fifo_st:08x}"
        )
