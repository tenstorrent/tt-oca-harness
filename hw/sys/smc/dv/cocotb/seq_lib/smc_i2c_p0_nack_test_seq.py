# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C1 ACK at 0x20 (+smc_i2c_shared_bus); address/data NACK via SmcI2cNackSlave at 0x10. HOSTIDLE may already be 1 after FMT STOP."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_STATUS_HOSTIDLE,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_protocol_vip import SmcI2cNackSlave

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_VIP_ADDR = 0x10
_INTERNAL_TARGET_ADDR = 0x20
_ALLOW_PAYLOAD = 0x5A
_DATA_NACK_BYTE = 0xAA


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


class smc_i2c_p0_nack_test_seq(SmcCsrSeq):
    """I2C0 host NACK proof: allow-path + address NACK + data NACK."""

    def __init__(self, name: str = "smc_i2c_p0_nack_test_seq") -> None:
        super().__init__(name)
        self.accesses: int = 0
        self.allow_ok: bool = False
        self.tc1_ok: bool = False
        self.tc2_ok: bool = False

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

    async def _wait_hostidle(self, label: str, *, expect_leave: bool = True) -> None:
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 0)
        status = 0
        if expect_leave:
            left_idle = False
            for _ in range(200):
                status = await self.csr_read(f"{label}_BUSY", status_addr)
                if not (status & I2C_STATUS_HOSTIDLE):
                    left_idle = True
                    break
                await Timer(1, units="us")
            if not left_idle:
                raise AssertionError(
                    f"{label}: I2C0 host never left hostidle (STATUS=0x{status:08x})"
                )
        for _ in range(400):
            status = await self.csr_read(f"{label}_STATUS", status_addr)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await Timer(10, units="us")
        raise AssertionError(f"{label}: I2C0 host stuck busy (STATUS=0x{status:08x})")

    async def _clear_events(self) -> None:
        await self.csr_write(
            "I2C0_CEVENTS_CLR",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR", 0),
            I2C_CONTROLLER_EVENTS_ALL,
        )

    async def _recover_after_nack(self, label: str) -> None:
        await self._clear_events()
        await self.csr_write(
            f"{label}_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self._wait_hostidle(f"{label}_RECOVER", expect_leave=False)

    async def _await_nack_event(self, label: str) -> tuple[int, int]:
        """Poll until CONTROLLER_EVENTS.NACK; return (events, status).

        HOSTIDLE may already be 1 after FMT STOP. Wire NACK is the VIP
        counter; this bit is the DUT sticky proof.
        """
        status_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 0)
        ev_addr = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR", 0)
        status = 0
        events = 0
        for _ in range(2000):
            events = await self.csr_read(f"{label}_EVENTS", ev_addr)
            status = await self.csr_read(f"{label}_STATUS", status_addr)
            if events & I2C_CONTROLLER_EVENTS_NACK:
                return events, status
            await Timer(10, units="us")
        raise AssertionError(
            f"{label}: timeout waiting for CONTROLLER_EVENTS.NACK "
            f"(STATUS=0x{status:08x} EVENTS=0x{events:08x})"
        )

    async def _setup_host(self) -> None:
        wrap0 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
        await self.csr_write("I2C0_WRAP_HOST", wrap0, I2C_WRAP_CTRL_HOST)
        await self._program_timing(0)
        await self.csr_write(
            "I2C0_OVRD_OFF",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 0),
            0,
        )
        await self.csr_write(
            "I2C0_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self._clear_events()
        await self.csr_write(
            "I2C0_ENABLEHOST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0),
            I2C_CTRL_ENABLEHOST,
        )

    async def _setup_internal_target(self) -> None:
        wrap1 = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 1)
        await self.csr_write("I2C1_WRAP_TARGET", wrap1, I2C_WRAP_CTRL_TARGET)
        await self._program_timing(1)
        await self.csr_write(
            "I2C1_TARGET_ID",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", 1),
            _target_id(_INTERNAL_TARGET_ADDR),
        )
        await self.csr_write(
            "I2C1_FIFO_RST",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 1),
            I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            "I2C1_CTRL_TARGET",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 1),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

    async def _allow_path(self) -> None:
        await self._clear_events()
        fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 0)
        addr_w = (_INTERNAL_TARGET_ADDR << 1) | 0
        await self.csr_write("I2C0_FDATA_START", fdata, I2C_FDATA_START | addr_w)
        await self.csr_write("I2C0_FDATA_PAYLOAD_STOP", fdata, I2C_FDATA_STOP | _ALLOW_PAYLOAD)
        await self._wait_hostidle("ALLOW_PATH")
        events = await self.csr_read(
            "ALLOW_EVENTS",
            self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR", 0),
        )
        if events & I2C_CONTROLLER_EVENTS_NACK:
            raise AssertionError(f"allow-path unexpected NACK EVENTS=0x{events:08x}")
        cocotb.log.info(
            "CHK-I2C-P0-NACK-ALLOW: I2C0→I2C1 @0x%02x write 0x%02x idle no NACK",
            _INTERNAL_TARGET_ADDR,
            _ALLOW_PAYLOAD,
        )
        self.allow_ok = True
        await self._clear_events()

    async def _tc1_addr_nack(self) -> None:
        vip = SmcI2cNackSlave(addr=_VIP_ADDR, nack_at_address=True, name="nack_addr")
        try:
            await self._clear_events()
            fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 0)
            addr_w = (_VIP_ADDR << 1) | 0
            await self.csr_write(
                "I2C0_FDATA_START_STOP",
                fdata,
                I2C_FDATA_START | I2C_FDATA_STOP | addr_w,
            )
            events, status = await self._await_nack_event("TC1_ADDR_NACK")
            if vip.addr_nacks < 1:
                raise AssertionError(
                    f"TC1: VIP did not drive address NACK (count={vip.addr_nacks})"
                )
            cocotb.log.info(
                "CHK-I2C-P0-NACK-TC1: addr-phase NACK @0x%02x EVENTS=0x%x STATUS=0x%x vip_nacks=%d",
                _VIP_ADDR,
                events,
                status,
                vip.addr_nacks,
            )
            self.tc1_ok = True
        finally:
            vip.stop()
        await self._recover_after_nack("TC1")

    async def _tc2_data_nack(self) -> None:
        vip = SmcI2cNackSlave(addr=_VIP_ADDR, nack_at_data=True, name="nack_data")
        try:
            await self._clear_events()
            fdata = self._idx_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 0)
            addr_w = (_VIP_ADDR << 1) | 0
            await self.csr_write("I2C0_FDATA_START_ADDR", fdata, I2C_FDATA_START | addr_w)
            await self.csr_write(
                "I2C0_FDATA_DATA_STOP",
                fdata,
                I2C_FDATA_STOP | _DATA_NACK_BYTE,
            )
            events, status = await self._await_nack_event("TC2_DATA_NACK")
            if vip.addr_acks < 1:
                raise AssertionError(f"TC2: VIP never ACKed address (acks={vip.addr_acks})")
            if vip.data_nacks < 1:
                raise AssertionError(f"TC2: VIP did not drive data NACK (count={vip.data_nacks})")
            cocotb.log.info(
                "CHK-I2C-P0-NACK-TC2: data-phase NACK @0x%02x byte=0x%02x "
                "EVENTS=0x%x STATUS=0x%x vip_acks=%d vip_data_nacks=%d",
                _VIP_ADDR,
                _DATA_NACK_BYTE,
                events,
                status,
                vip.addr_acks,
                vip.data_nacks,
            )
            self.tc2_ok = True
        finally:
            vip.stop()

    async def body(self) -> None:
        if "smc_i2c_shared_bus" not in cocotb.plusargs:
            raise AssertionError(
                "smc_i2c_p0_nack_test requires +smc_i2c_shared_bus "
                "(I2C1 allow-path positive control)"
            )

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        await self._setup_internal_target()
        await self._setup_host()
        await self._allow_path()
        await self._tc1_addr_nack()
        await self._tc2_data_nack()
