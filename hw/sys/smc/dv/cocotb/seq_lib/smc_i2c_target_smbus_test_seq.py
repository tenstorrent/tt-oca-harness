# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target SMBALERT# + VIP ARA; external SMBSUS# on pad40. Not DUT-internal host SMBSUS."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_SMBUS_CTRL_SMBALERT,
    I2C_SMBUS_STATUS_SMBSUS,
    I2C_WRAP_CTRL_TARGET_SMBUS,
)

try:
    from .smc_i2c_protocol_vip import SmcI2cMasterVip

    _I2C_VIP_AVAILABLE = True
except Exception:  # noqa: BLE001
    SmcI2cMasterVip = None  # type: ignore[assignment]
    _I2C_VIP_AVAILABLE = False

_TARGET_ADDR = 0x10
_ARA_ADDR = 0x0C
_ARA_REPLY = (_TARGET_ADDR & 0x7F) << 1
_SMBSUS_PAD = 40
_POLL_ITERS = 500
_POLL_STEP_US = 10

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
I2C0_WRAP_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
I2C0_OVRD = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 0)
I2C0_SMBUS_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR", 0)
I2C0_SMBUS_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR", 0)
I2C0_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0)
I2C0_FIFO_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0)
I2C0_TARGET_ID = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 0)
I2C0_TXDATA = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", 0)
I2C0_TIMING0 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", 0)
I2C0_TIMING1 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", 0)
I2C0_TIMING2 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", 0)
I2C0_TIMING3 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", 0)
I2C0_TIMING4 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", 0)


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


class smc_i2c_target_smbus_test_seq(SmcCsrSeq):
    """VIP ARA + external SMBSUS# into DUT I2C0 target."""

    def __init__(self, name: str = "smc_i2c_target_smbus_test_seq") -> None:
        super().__init__(name)
        self.alert_asserted: bool = False
        self.ara_ok: bool = False
        self.alert_cleared: bool = False
        self.suspend_ok: bool = False
        self.expected_bytes: bytes = bytes([_ARA_REPLY])
        self.observed_bytes: bytes = b""

    async def _program_timing(self) -> None:
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))

    async def _wait_smbalert(self, expect_low: bool, timeout_us: int = 5000) -> bool:
        dut = cocotb.top
        assert hasattr(dut, "tb_i2c0_smbalert"), "tb_i2c0_smbalert not lifted"
        want = 0 if expect_low else 1
        for _ in range(timeout_us):
            if int(dut.tb_i2c0_smbalert.value) == want:
                return True
            await Timer(1, units="us")
        return False

    async def _await_smbsus_status(self, *, want_set: bool) -> None:
        st = 0
        for i in range(_POLL_ITERS):
            st = await self.csr_read(f"SMBSUS_ST_{i}", I2C0_SMBUS_STATUS)
            bit = bool(st & I2C_SMBUS_STATUS_SMBSUS)
            if bit == want_set:
                return
            await Timer(_POLL_STEP_US, units="us")
        raise AssertionError(f"SMBSUS STATUS timeout want_set={want_set} SMBUS_STATUS=0x{st:08x}")

    def _drive_smbsus(self, assert_low: bool) -> None:
        """Drive I2C0 SMBSUS# pad 40 via tb_gpio_ext_drive (active-low)."""
        dut = cocotb.top
        assert hasattr(dut, "tb_gpio_ext_drive_en"), "tb_gpio_ext_drive_en missing"
        en = int(dut.tb_gpio_ext_drive_en.value)
        val = int(dut.tb_gpio_ext_drive_value.value)
        mask = 1 << _SMBSUS_PAD
        en |= mask
        if assert_low:
            val &= ~mask
        else:
            val |= mask
        dut.tb_gpio_ext_drive_en.value = en
        dut.tb_gpio_ext_drive_value.value = val

    def _release_smbsus(self) -> None:
        dut = cocotb.top
        en = int(dut.tb_gpio_ext_drive_en.value)
        val = int(dut.tb_gpio_ext_drive_value.value)
        mask = 1 << _SMBSUS_PAD
        en &= ~mask
        val |= mask
        dut.tb_gpio_ext_drive_en.value = en
        dut.tb_gpio_ext_drive_value.value = val

    async def body(self) -> None:
        assert _I2C_VIP_AVAILABLE, "I2C protocol VIP unavailable"
        await self.prove_dut_i2c0_pins()

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_TARGET_SMBUS", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET_SMBUS)
        await self.wait_i2c0_lsio_ready("I2C0_TARGET_SMBUS_WRAP")
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, 0)
        await self._program_timing()
        await self.csr_write(
            "I2C0_FIFO_RST",
            I2C0_FIFO_CTRL,
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST,
        )
        await self.csr_write(
            "I2C0_TARGET_ID_ARA",
            I2C0_TARGET_ID,
            _pack_target_id(_TARGET_ADDR, 0x7F, _ARA_ADDR, 0x7F),
        )
        await self.csr_write("I2C0_TXDATA_ARA", I2C0_TXDATA, _ARA_REPLY)
        await self.csr_write("I2C0_ENABLETARGET", I2C0_CTRL, I2C_CTRL_ENABLETARGET)
        await ClockCycles(cocotb.top.clk_smc_i, 20)

        idle = int(cocotb.top.tb_i2c0_smbalert.value)
        if idle != 1:
            raise AssertionError(f"SMBALERT# idle expected high, got {idle}")

        await self.csr_write("I2C0_SMBUS_CTRL_ALERT", I2C0_SMBUS_CTRL, I2C_SMBUS_CTRL_SMBALERT)
        self.alert_asserted = await self._wait_smbalert(expect_low=True)
        if not self.alert_asserted:
            raise AssertionError("SMBALERT# (pad39) did not go low after CTRL write")
        cocotb.log.info("CHK-I2C-TGT-SMBUS-ALERT: SMBALERT# asserted (pad39=0)")

        master = SmcI2cMasterVip(speed=100_000, name="smc_target_smbus_ara")
        resp = await master.smbus_query_ara()
        self.observed_bytes = bytes([resp & 0xFF])
        if resp != _ARA_REPLY:
            raise AssertionError(
                f"ARA reply mismatch: got 0x{resp:02X}, expected 0x{_ARA_REPLY:02X}"
            )
        self.ara_ok = True
        self.alert_cleared = await self._wait_smbalert(expect_low=False, timeout_us=5000)
        if not self.alert_cleared:
            raise AssertionError("SMBALERT# stayed low after ARA (expected hwclr)")
        cocotb.log.info("CHK-I2C-TGT-SMBUS-ARA: reply=0x%02X; SMBALERT# cleared", resp)

        # External SMBSUS# on GPIO[40].
        self._drive_smbsus(assert_low=True)
        await self._await_smbsus_status(want_set=True)
        cocotb.log.info("CHK-I2C-TGT-SMBUS-SUS-ASSERT: STATUS.SMBSUS after pad40=0")
        self._drive_smbsus(assert_low=False)
        await self._await_smbsus_status(want_set=False)
        self._release_smbsus()
        self.suspend_ok = True
        cocotb.log.info("CHK-I2C-TGT-SMBUS-SUS-CLR: STATUS.SMBSUS cleared after release")

        await self.csr_write("I2C0_CTRL_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("CLOCK_GATE_RESTORE", CLOCK_GATE_CONTROL, cg)
