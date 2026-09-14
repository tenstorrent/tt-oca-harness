# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ACQ_THRESHOLD (I2C1→I2C0, +smc_i2c_shared_bus) and TX_THRESHOLD on empty TX FIFO."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_INTR_ENABLE_ACQ_THRESHOLD,
    I2C_INTR_ENABLE_TX_THRESHOLD,
    I2C_INTR_STATE_ACQ_THRESHOLD,
    I2C_INTR_STATE_TX_THRESHOLD,
    I2C_STATUS_HOSTIDLE,
    I2C_TARGET_FIFO_CONFIG_ACQ_THRESH_BP,
    I2C_TARGET_FIFO_CONFIG_TX_THRESH_BP,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_TARGET_FIFO_STATUS_TXLVL_BM,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_TARGET_ADDR = 0x10
_ACQ_THRESH = 4
# Payload bytes so START + data(+STOP) push ACQLVL > _ACQ_THRESH.
_ACQ_PAYLOAD = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4]
_TX_THRESH = 5


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


def _acq_lvl(status: int) -> int:
    return (int(status) & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> (I2C_TARGET_FIFO_STATUS_ACQLVL_BP)


def _tx_lvl(status: int) -> int:
    return int(status) & I2C_TARGET_FIFO_STATUS_TXLVL_BM


class smc_i2c_p0_fifo_test_seq(SmcCsrSeq):
    """ACQ / TX FIFO threshold interrupt proof on I2C0 (+ I2C1 host)."""

    def __init__(self, name: str = "smc_i2c_p0_fifo_test_seq") -> None:
        super().__init__(name)
        self.acq_ok: bool = False
        self.tx_ok: bool = False

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

    async def _wait_hostidle(self, host: int, label: str) -> None:
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", host)
        status = 0
        left = False
        for _ in range(200):
            status = await self.csr_read(f"{label}_BUSY", status_addr)
            if not (status & I2C_STATUS_HOSTIDLE):
                left = True
                break
            await Timer(1, units="us")
        if not left:
            raise AssertionError(f"{label}: never left hostidle STATUS=0x{status:08x}")
        for _ in range(400):
            status = await self.csr_read(f"{label}_STATUS", status_addr)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await Timer(10, units="us")
        raise AssertionError(f"{label}: stuck busy STATUS=0x{status:08x}")

    async def _acq_threshold_leg(self) -> None:
        # I2C0 target
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
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_ACQRST,
        )
        # ACQ_THRESH in [27:16]
        await self.csr_write(
            "I2C0_TGT_FIFO_CFG",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR", 0),
            (_ACQ_THRESH & 0xFFF) << I2C_TARGET_FIFO_CONFIG_ACQ_THRESH_BP,
        )
        await self.csr_write(
            "I2C0_INTR_ENABLE_ACQ",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0),
            I2C_INTR_ENABLE_ACQ_THRESHOLD,
        )
        await self.csr_write(
            "I2C0_INTR_CLR",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0),
            0xFFFFFFFF,
        )
        await self.csr_write(
            "I2C0_CTRL_TGT",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        # I2C1 host write
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
        addr_w = (_TARGET_ADDR << 1) | 0
        await self.csr_write("I2C1_FDATA_START", fdata, I2C_FDATA_START | addr_w)
        for i, b in enumerate(_ACQ_PAYLOAD[:-1]):
            await self.csr_write(f"I2C1_FDATA_{i}", fdata, b)
        await self.csr_write("I2C1_FDATA_STOP", fdata, I2C_FDATA_STOP | _ACQ_PAYLOAD[-1])
        await self._wait_hostidle(1, "ACQ_HOST")

        fifo_st = await self.csr_read(
            "I2C0_TGT_FIFO_STATUS",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR", 0),
        )
        intr = await self.csr_read(
            "I2C0_INTR_STATE",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0),
        )
        lvl = _acq_lvl(fifo_st)
        if lvl <= _ACQ_THRESH:
            raise AssertionError(
                f"ACQ lvl={lvl} not > thresh={_ACQ_THRESH} (fifo_st=0x{fifo_st:08x})"
            )
        if not (intr & I2C_INTR_STATE_ACQ_THRESHOLD):
            raise AssertionError(f"ACQ_THRESHOLD not set INTR_STATE=0x{intr:08x} lvl={lvl}")
        cocotb.log.info(
            "CHK-I2C-P0-FIFO-ACQ: ACQLVL=%d > thresh=%d INTR_STATE.ACQ_THRESHOLD fifo_st=0x%x",
            lvl,
            _ACQ_THRESH,
            fifo_st,
        )
        self.acq_ok = True
        await self.csr_write(
            "I2C0_INTR_CLR_ACQ",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0),
            0xFFFFFFFF,
        )

    async def _tx_threshold_empty_leg(self) -> None:
        # Reconfigure I2C0 target TX_THRESH; empty TXFIFO → TXLVL < thresh.
        await self.csr_write(
            "I2C0_FIFO_TXRST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0),
            I2C_FIFO_CTRL_TXRST,
        )
        await self.csr_write(
            "I2C0_TGT_FIFO_CFG_TX",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR", 0),
            (_TX_THRESH & 0xFFF) << I2C_TARGET_FIFO_CONFIG_TX_THRESH_BP,
        )
        await self.csr_write(
            "I2C0_INTR_ENABLE_TX",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0),
            I2C_INTR_ENABLE_TX_THRESHOLD,
        )
        await self.csr_write(
            "I2C0_INTR_CLR_TX",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0),
            0xFFFFFFFF,
        )
        fifo_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR", 0)
        intr_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
        fifo_st = 0
        intr = 0
        lvl = 0
        for _ in range(200):
            fifo_st = await self.csr_read("I2C0_TGT_FIFO_STATUS_TX", fifo_addr)
            intr = await self.csr_read("I2C0_INTR_STATE_TX", intr_addr)
            lvl = _tx_lvl(fifo_st)
            if lvl < _TX_THRESH and (intr & I2C_INTR_STATE_TX_THRESHOLD):
                break
            await Timer(1, units="us")
        else:
            raise AssertionError(
                f"TX_THRESHOLD not seen with empty TX "
                f"lvl={lvl} thresh={_TX_THRESH} INTR=0x{intr:08x} "
                f"fifo_st=0x{fifo_st:08x}"
            )
        cocotb.log.info(
            "CHK-I2C-P0-FIFO-TX: TXLVL=%d < thresh=%d INTR_STATE.TX_THRESHOLD",
            lvl,
            _TX_THRESH,
        )
        self.tx_ok = True

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError("smc_i2c_p0_fifo_test requires +smc_i2c_shared_bus")
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self._acq_threshold_leg()
        await self._tx_threshold_empty_leg()
        cocotb.log.info(
            "CHK-I2C-P0-FIFO: ACQ+TX threshold legs PASS acq=%s tx=%s",
            self.acq_ok,
            self.tx_ok,
        )
