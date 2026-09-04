# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DUT-internal SMBALERT, ARA, and SMBSUS. Requires +smc_i2c_shared_bus."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_INTR_ENABLE_SMBALERT,
    I2C_INTR_STATE_SMBALERT,
    I2C_SMBUS_CTRL_SMBALERT,
    I2C_SMBUS_CTRL_SMBSUS,
    I2C_SMBUS_STATUS_SMBALERT,
    I2C_SMBUS_STATUS_SMBSUS,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_WRAP_CTRL_HOST_SMBUS,
    I2C_WRAP_CTRL_TARGET_SMBUS,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_TARGET_IDX = 0
_HOST_IDX = 1
_TARGET_ADDR = 0x10
_ARA_ADDR = 0x0C
_ARA_REPLY = (_TARGET_ADDR & 0x7F) << 1
_POLL_ITERS = 500
_POLL_STEP_US = 10


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


def _pack_target_id(address0: int, mask0: int = 0x7F, address1: int = 0, mask1: int = 0) -> int:
    return (
        (address0 & 0x7F)
        | ((mask0 & 0x7F) << 7)
        | ((address1 & 0x7F) << 14)
        | ((mask1 & 0x7F) << 21)
    )


class smc_smbus_alert_suspend_test_seq(SmcCsrSeq):
    """DUT I2C0↔I2C1 SMBALERT/ARA + SMBSUS sideband proof."""

    def __init__(self, name: str = "smc_smbus_alert_suspend_test_seq") -> None:
        super().__init__(name)
        self.alert_seen: bool = False
        self.ara_ok: bool = False
        # Byte the host read back; compared against _ARA_REPLY above.
        self.ara_reply: int = -1
        self.alert_cleared: bool = False
        self.suspend_ok: bool = False

    def _addr(self, symbol: str, idx: int) -> int:
        return smc_indexed_addr(symbol, idx)

    async def _program_timing(self, idx: int) -> None:
        await self.csr_write(
            f"I2C{idx}_TIMING0",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", idx),
            _pack_timing0(0x1A, 0x32),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING1",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", idx),
            _pack_timing1(2, 2),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING2",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", idx),
            _pack_timing2(5, 4),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING3",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", idx),
            _pack_timing3(2, 5),
        )
        await self.csr_write(
            f"I2C{idx}_TIMING4",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", idx),
            _pack_timing4(4, 5),
        )

    async def _await_smbus_status(
        self, label: str, idx: int, *, want_set: int = 0, want_clear: int = 0
    ) -> int:
        st_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR", idx)
        st = 0
        for i in range(_POLL_ITERS):
            st = await self.csr_read(f"{label}_{i}", st_a)
            if (st & want_set) == want_set and (st & want_clear) == 0:
                return st
            await Timer(_POLL_STEP_US, units="us")
        raise AssertionError(
            f"{label} timeout SMBUS_STATUS=0x{st:08x} "
            f"want_set=0x{want_set:x} want_clear=0x{want_clear:x}"
        )

    async def _await_intr(self, label: str, idx: int, *, want_set: bool) -> int:
        ir_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", idx)
        ir = 0
        for i in range(_POLL_ITERS):
            ir = await self.csr_read(f"{label}_{i}", ir_a)
            bit = bool(ir & I2C_INTR_STATE_SMBALERT)
            if bit == want_set:
                return ir
            await Timer(_POLL_STEP_US, units="us")
        raise AssertionError(f"{label} timeout INTR_STATE=0x{ir:08x} want_set={want_set}")

    async def _await_smbus_ctrl_alert(self, label: str, idx: int, *, want_set: bool) -> int:
        ctrl_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR", idx)
        ctrl = 0
        for i in range(_POLL_ITERS):
            ctrl = await self.csr_read(f"{label}_{i}", ctrl_a)
            bit = bool(ctrl & I2C_SMBUS_CTRL_SMBALERT)
            if bit == want_set:
                return ctrl
            await Timer(_POLL_STEP_US, units="us")
        raise AssertionError(f"{label} timeout SMBUS_CTRL=0x{ctrl:08x} want_alert={want_set}")

    async def _host_ara_read(self) -> int:
        idx = _HOST_IDX
        fifo_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", idx)
        fdata_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", idx)
        status_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx)
        rdata_a = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR", idx)

        await self.csr_write("HOST_FIFO_RST", fifo_a, I2C_FIFO_CTRL_RXRST_FMTRST)
        addr_r = (_ARA_ADDR << 1) | 1
        await self.csr_write("ARA_START", fdata_a, I2C_FDATA_START | addr_r)
        await self.csr_write("ARA_READ", fdata_a, I2C_FDATA_READB | I2C_FDATA_STOP | 1)

        rdata = 0
        status = 0
        for i in range(2000):
            status = await self.csr_read(f"ARA_ST_{i}", status_a)
            if not (status & I2C_STATUS_RXEMPTY):
                rdata = await self.csr_read("ARA_RDATA", rdata_a) & 0xFF
                break
            await Timer(10, units="us")
        else:
            raise AssertionError(f"ARA RX empty timeout STATUS=0x{status:08x}")

        for i in range(400):
            status = await self.csr_read(f"ARA_IDLE_{i}", status_a)
            if status & I2C_STATUS_HOSTIDLE:
                return rdata
            await Timer(10, units="us")
        raise AssertionError(
            f"ARA HOSTIDLE timeout after RDATA=0x{rdata:02x} STATUS=0x{status:08x}"
        )

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError("smc_smbus_alert_suspend_test requires +smc_i2c_shared_bus")

        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        wrap_t = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", _TARGET_IDX)
        wrap_h = self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", _HOST_IDX)
        await self.csr_write("I2C0_WRAP_TGT_SMBUS", wrap_t, I2C_WRAP_CTRL_TARGET_SMBUS)
        await self.csr_write("I2C1_WRAP_HOST_SMBUS", wrap_h, I2C_WRAP_CTRL_HOST_SMBUS)

        await self._program_timing(_TARGET_IDX)
        await self._program_timing(_HOST_IDX)

        await self.csr_write(
            "I2C0_TARGET_ID",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", _TARGET_IDX),
            _pack_target_id(_TARGET_ADDR, 0x7F, _ARA_ADDR, 0x7F),
        )
        await self.csr_write(
            "I2C0_FIFO_RST",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", _TARGET_IDX),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST,
        )
        await self.csr_write(
            "I2C0_TX_ARA",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", _TARGET_IDX),
            _ARA_REPLY,
        )
        await self.csr_write(
            "I2C0_CTRL_TGT",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", _TARGET_IDX),
            I2C_CTRL_ENABLETARGET,
        )

        await self.csr_write(
            "I2C1_FIFO_RST",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", _HOST_IDX),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            "I2C1_CTRL_HOST",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", _HOST_IDX),
            I2C_CTRL_ENABLEHOST,
        )

        # Clear sideband + host IRQ before stimulus.
        await self.csr_write(
            "I2C0_SMBUS_CLR",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR", _TARGET_IDX),
            0,
        )
        await self.csr_write(
            "I2C1_SMBUS_CLR",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR", _HOST_IDX),
            0,
        )
        await self.csr_write(
            "I2C1_INTR_EN_ALERT",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", _HOST_IDX),
            I2C_INTR_ENABLE_SMBALERT,
        )
        await self.csr_write(
            "I2C1_INTR_CLR_ALERT",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", _HOST_IDX),
            I2C_INTR_STATE_SMBALERT,
        )

        # ---- ALERT: target -> host ----
        await self.csr_write(
            "I2C0_ALERT_ASSERT",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR", _TARGET_IDX),
            I2C_SMBUS_CTRL_SMBALERT,
        )
        await self._await_smbus_status(
            "HOST_ALERT_ST",
            _HOST_IDX,
            want_set=I2C_SMBUS_STATUS_SMBALERT,
        )
        await self._await_intr("HOST_ALERT_IRQ", _HOST_IDX, want_set=True)
        await self._await_smbus_ctrl_alert("TGT_ALERT_HELD", _TARGET_IDX, want_set=True)
        self.alert_seen = True
        cocotb.log.info("CHK-SMBUS-ALERT-SUS-ALERT: host STATUS+IRQ after target assert")

        rdata = await self._host_ara_read()
        if rdata != _ARA_REPLY:
            raise AssertionError(f"ARA reply 0x{rdata:02x} != expected 0x{_ARA_REPLY:02x}")
        self.ara_ok = True
        self.ara_reply = rdata
        cocotb.log.info("CHK-SMBUS-ALERT-SUS-ARA: reply=0x%02x", rdata)

        await self._await_smbus_ctrl_alert("TGT_ALERT_CLR", _TARGET_IDX, want_set=False)
        await self.csr_write(
            "I2C1_INTR_CLR_POST",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", _HOST_IDX),
            I2C_INTR_STATE_SMBALERT,
        )
        await self._await_smbus_status(
            "HOST_ALERT_CLR",
            _HOST_IDX,
            want_clear=I2C_SMBUS_STATUS_SMBALERT,
        )
        self.alert_cleared = True
        cocotb.log.info("CHK-SMBUS-ALERT-SUS-CLR: target CTRL + host STATUS cleared")

        # ---- SUSPEND: host -> target ----
        await self.csr_write(
            "I2C1_SUS_ASSERT",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR", _HOST_IDX),
            I2C_SMBUS_CTRL_SMBSUS,
        )
        await self._await_smbus_status(
            "TGT_SUS_ST",
            _TARGET_IDX,
            want_set=I2C_SMBUS_STATUS_SMBSUS,
        )
        await self.csr_write(
            "I2C1_SUS_DEASSERT",
            self._addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR", _HOST_IDX),
            0,
        )
        await self._await_smbus_status(
            "TGT_SUS_CLR",
            _TARGET_IDX,
            want_clear=I2C_SMBUS_STATUS_SMBSUS,
        )
        self.suspend_ok = True
        cocotb.log.info("CHK-SMBUS-ALERT-SUS-SUSPEND: target STATUS follows host SMBSUS")
        cocotb.log.info(
            "CHK-SMBUS-ALERT-SUS-BASIC: alert=%s ara=%s clr=%s sus=%s",
            self.alert_seen,
            self.ara_ok,
            self.alert_cleared,
            self.suspend_ok,
        )
