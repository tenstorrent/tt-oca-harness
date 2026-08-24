# SPDX-License-Identifier: Apache-2.0
"""I2C1 StretchTimeout while I2C0 target holds SCL. Requires +smc_i2c_shared_bus."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_INTR_ENABLE_STRETCH_TIMEOUT,
    I2C_INTR_STATE_STRETCH_TIMEOUT,
    I2C_TIMEOUT_CTRL_EN,
    I2C_TIMEOUT_CTRL_VAL,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)
CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)

_TARGET_ADDR = 0x10
_STRETCH_TIMEOUT_CYCLES = 2000


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


class smc_i2c_p0_timeout_test_seq(SmcCsrSeq):
    """Stretch-timeout IRQ when target TX is empty during host READ."""

    def __init__(self, name: str = "smc_i2c_p0_timeout_test_seq") -> None:
        super().__init__(name)
        self.stretch_ok: bool = False

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

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError(
                "smc_i2c_p0_timeout_test requires +smc_i2c_shared_bus"
            )

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write(
            "CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN
        )

        # I2C0 target, TX empty
        wrap0 = self._idx_addr(
            "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0
        )
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
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        # I2C1 host with stretch timeout enabled
        wrap1 = self._idx_addr(
            "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 1
        )
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
        # TIMEOUT_CTRL: VAL | EN; MODE=0 is StretchTimeout (MODE=1 is BusTimeout).
        await self.csr_write(
            "I2C1_TIMEOUT_CTRL",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR", 1),
            (_STRETCH_TIMEOUT_CYCLES & I2C_TIMEOUT_CTRL_VAL)
            | I2C_TIMEOUT_CTRL_EN,
        )
        await self.csr_write(
            "I2C1_INTR_ENABLE",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 1),
            I2C_INTR_ENABLE_STRETCH_TIMEOUT,
        )
        await self.csr_write(
            "I2C1_INTR_CLR",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 1),
            0xFFFFFFFF,
        )
        await self.csr_write(
            "I2C1_CTRL_HOST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            I2C_CTRL_ENABLEHOST,
        )

        fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 1)
        addr_r = (_TARGET_ADDR << 1) | 1
        await self.csr_write("I2C1_FDATA_START", fdata, I2C_FDATA_START | addr_r)
        await self.csr_write(
            "I2C1_FDATA_READB_STOP",
            fdata,
            I2C_FDATA_READB | I2C_FDATA_STOP | 1,
        )

        intr_addr = self._idx_addr(
            "SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 1
        )
        intr = 0
        for _ in range(800):
            intr = await self.csr_read("I2C1_INTR_POLL", intr_addr)
            if intr & I2C_INTR_STATE_STRETCH_TIMEOUT:
                cocotb.log.info(
                    "CHK-I2C-P0-TIMEOUT: STRETCH_TIMEOUT INTR_STATE=0x%x "
                    "cycles=%d",
                    intr,
                    _STRETCH_TIMEOUT_CYCLES,
                )
                self.stretch_ok = True
                break
            await Timer(5, units="us")
        if not self.stretch_ok:
            raise AssertionError(
                f"STRETCH_TIMEOUT not seen INTR_STATE=0x{intr:08x}"
            )

        # Clean release
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
