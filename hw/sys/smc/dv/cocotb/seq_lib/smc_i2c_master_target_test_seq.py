# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_i2c_master_target_test / smc_i2c_p1_rdwr_protocol_test.

U4-2: DUT OpenTitan I2C0 host writes a byte into a cocotb EEPROM slave on
``tb_i2c0_*`` pads (not VIP↔VIP). Also keeps the OVRD pin-level gate.

U4-2 SMBus (software framing on OT I2C; no HW PEC engine):
  * DUT host write-with-PEC to EEPROM
  * DUT host ARA read from VIP responder @ 0x0C
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_csr_seq_utils import SmcCsrSeq

try:
    from .smc_i2c_protocol_vip import SmcI2cEepromSlave, SmcI2cMasterVip

    _I2C_PROTOCOL_VIP_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional at import time
    SmcI2cEepromSlave = None  # type: ignore[assignment]
    SmcI2cMasterVip = None  # type: ignore[assignment]
    _I2C_PROTOCOL_VIP_AVAILABLE = False

_I2C_EEPROM_ADDR = 0x50
_I2C_WRITE_BYTE = 0xAB
_I2C_WRITE_OFFSET = 0x10
_SMBUS_PEC_OFFSET = 0x20
_SMBUS_PEC_DATA = 0xA5
_SMBUS_ARA_ADDR = 0x0C
_SMBUS_ARA_REPLY = _I2C_EEPROM_ADDR << 1  # 0xA0 — alerting slave addr<<1

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
I2C0_WRAP_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
I2C0_OVRD = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 0)
I2C0_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", 0)
I2C0_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 0)
I2C0_RDATA = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR", 0)
I2C0_FDATA = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR", 0)
I2C0_FIFO_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", 0)
I2C0_TIMING0 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", 0)
I2C0_TIMING1 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", 0)
I2C0_TIMING2 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", 0)
I2C0_TIMING3 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", 0)
I2C0_TIMING4 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", 0)
I2C0_CONTROLLER_EVENTS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR", 0)

I2C_WRAP_ENABLE_CONTROLLER = 0x11
I2C_CTRL_ENABLEHOST = 0x1
I2C_OVRD_RELEASE = 0x7
I2C_OVRD_PULL_SCL_LOW = 0x5
I2C_OVRD_PULL_SDA_LOW = 0x3
I2C_OVRD_PULL_BOTH_LOW = 0x1
I2C_OVRD_OFF = 0x0
I2C_FIFO_CTRL_RXRST_FMTRST = 0x3
I2C_STATUS_HOSTIDLE = 1 << 3
I2C_STATUS_RXEMPTY = 1 << 5
I2C_FDATA_START = 1 << 8
I2C_FDATA_STOP = 1 << 9
I2C_FDATA_READB = 1 << 10

I2C_READABLE_REGS = [
    ("I2C0_INTR_STATE", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0), 0x0),
    ("I2C0_STATUS", I2C0_STATUS, None),
    ("I2C1_INTR_STATE", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 1), 0x0),
    ("I2C2_INTR_STATE", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 2), 0x0),
]


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


class smc_i2c_master_target_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_i2c_master_target_test_seq") -> None:
        super().__init__(name)
        self.clock_gate_value: int = 0
        self.dut_host_write_ok: bool = False
        self.dut_smbus_pec_ok: bool = False
        self.dut_smbus_ara_ok: bool = False

    @staticmethod
    async def _check_line(name: str, expected_scl: int, expected_sda: int) -> None:
        dut = cocotb.top
        await ClockCycles(dut.clk_smc_i, 100)
        scl = int(dut.tb_i2c0_scl.value)
        sda = int(dut.tb_i2c0_sda.value)
        cocotb.log.info(
            "%s: scl=%d sda=%d dut_low=(%d,%d)",
            name,
            scl,
            sda,
            int(dut.tb_i2c0_scl_dut_low.value),
            int(dut.tb_i2c0_sda_dut_low.value),
        )
        assert scl == expected_scl, f"{name}: SCL={scl}, expected {expected_scl}"
        assert sda == expected_sda, f"{name}: SDA={sda}, expected {expected_sda}"

    async def _program_i2c0_timing(self) -> None:
        """Load OpenTitan host timing (FW standard-mode defaults)."""
        # Conservative defaults from fw/smc/common/i2c_opentitan.c
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))

    async def _wait_hostidle(self, label: str) -> None:
        status = 0
        # Ensure the host actually left Idle (FMT accepted) before waiting for
        # completion — otherwise a no-op FIFO write looks like instant success.
        left_idle = False
        for _ in range(200):
            status = await self.csr_read(f"{label}_BUSY", I2C0_STATUS)
            if not (status & I2C_STATUS_HOSTIDLE):
                left_idle = True
                break
            await Timer(1, units="us")
        if not left_idle:
            cevents = await self.csr_read(f"{label}_CEVENTS_STUCK", I2C0_CONTROLLER_EVENTS)
            raise AssertionError(
                f"{label}: DUT I2C0 host never left hostidle after FMT push "
                f"(STATUS=0x{status:08x} CONTROLLER_EVENTS=0x{cevents:08x})"
            )
        # VCS completes a 3-byte host write in ~40 us; allow 2 ms of sim time.
        for _ in range(200):
            status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await Timer(10, units="us")
        cevents = await self.csr_read(f"{label}_CEVENTS", I2C0_CONTROLLER_EVENTS)
        raise AssertionError(
            f"{label}: DUT I2C0 host did not reach hostidle "
            f"(STATUS=0x{status:08x} CONTROLLER_EVENTS=0x{cevents:08x})"
        )

    async def _dut_i2c0_host_write_proof(self) -> None:
        """DUT I2C0 host -> VIP EEPROM slave byte write on tb_i2c0_*."""
        assert self._i2c_slave is not None

        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self._program_i2c0_timing()
        await self.csr_write("I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        # W1C: clear sticky NACK/halt so a prior attempt cannot freeze Idle+SCL.
        await self.csr_write("I2C0_CONTROLLER_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, 0xF)
        await self.csr_write("I2C0_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)

        addr_byte = (_I2C_EEPROM_ADDR << 1) | 0  # write
        await self.csr_write(
            "I2C0_FDATA_START_ADDR",
            I2C0_FDATA,
            I2C_FDATA_START | addr_byte,
        )
        await self.csr_write("I2C0_FDATA_OFFSET", I2C0_FDATA, _I2C_WRITE_OFFSET)
        await self.csr_write(
            "I2C0_FDATA_DATA_STOP",
            I2C0_FDATA,
            I2C_FDATA_STOP | _I2C_WRITE_BYTE,
        )

        await self._wait_hostidle("DUT_HOST_WRITE")
        cevents = await self.csr_read("DUT_HOST_WRITE_CEVENTS", I2C0_CONTROLLER_EVENTS)
        await Timer(50, units="us")
        got = self._i2c_slave.read_mem(_I2C_WRITE_OFFSET, 1)
        cocotb.log.info(
            "DUT I2C0 host write: slave.mem[0x%02X]=%s expected 0x%02X "
            "CONTROLLER_EVENTS=0x%08x VIP(starts=%s acks=%s stops=%s bytes=%s)",
            _I2C_WRITE_OFFSET,
            got.hex(),
            _I2C_WRITE_BYTE,
            cevents,
            getattr(self._i2c_slave, "starts", "?"),
            getattr(self._i2c_slave, "acks", "?"),
            getattr(self._i2c_slave, "stops", "?"),
            getattr(self._i2c_slave, "bytes", "?"),
        )
        assert got == bytes([_I2C_WRITE_BYTE]), (
            f"DUT I2C0 host write: slave mem 0x{got.hex()}, "
            f"expected 0x{_I2C_WRITE_BYTE:02X} "
            f"(CONTROLLER_EVENTS=0x{cevents:08x})"
        )
        self.dut_host_write_ok = True

    async def _dut_i2c0_smbus_pec_write_proof(self) -> None:
        """DUT host SMBus write-with-PEC (SW CRC-8) into EEPROM on pads."""
        assert self._i2c_slave is not None
        assert SmcI2cMasterVip is not None

        payload = bytes([_SMBUS_PEC_OFFSET, _SMBUS_PEC_DATA])
        pec = SmcI2cMasterVip.smbus_pec(_I2C_EEPROM_ADDR, 0, payload)
        addr_byte = (_I2C_EEPROM_ADDR << 1) | 0

        await self.csr_write("I2C0_FIFO_RST_PEC", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("I2C0_FDATA_PEC_START", I2C0_FDATA, I2C_FDATA_START | addr_byte)
        await self.csr_write("I2C0_FDATA_PEC_OFFSET", I2C0_FDATA, _SMBUS_PEC_OFFSET)
        await self.csr_write("I2C0_FDATA_PEC_DATA", I2C0_FDATA, _SMBUS_PEC_DATA)
        await self.csr_write("I2C0_FDATA_PEC_STOP", I2C0_FDATA, I2C_FDATA_STOP | pec)

        await self._wait_hostidle("DUT_SMBUS_PEC")
        await Timer(50, units="us")
        stored = self._i2c_slave.read_mem(_SMBUS_PEC_OFFSET, 2)
        cocotb.log.info(
            "DUT SMBus PEC write: slave.mem[0x%02X]=%s expected data=0x%02X pec=0x%02X",
            _SMBUS_PEC_OFFSET,
            stored.hex(),
            _SMBUS_PEC_DATA,
            pec,
        )
        assert stored == bytes([_SMBUS_PEC_DATA, pec]), (
            f"DUT SMBus PEC write mismatch: got {stored.hex()}, "
            f"expected {_SMBUS_PEC_DATA:02x}{pec:02x}"
        )
        self.dut_smbus_pec_ok = True

    async def _dut_i2c0_smbus_ara_read_proof(self) -> None:
        """DUT host ARA query: read 1 byte from VIP @ 0x0C on tb_i2c0_*."""
        assert _I2C_PROTOCOL_VIP_AVAILABLE and SmcI2cEepromSlave is not None

        ara_slave = SmcI2cEepromSlave(addr=_SMBUS_ARA_ADDR, name="smc_i2c0_ara")
        ara_slave.write_mem(0, bytes([_SMBUS_ARA_REPLY]))

        await self.csr_write("I2C0_FIFO_RST_ARA", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        addr_r = (_SMBUS_ARA_ADDR << 1) | 1
        await self.csr_write("I2C0_FDATA_ARA_START", I2C0_FDATA, I2C_FDATA_START | addr_r)
        # READB + STOP + FBYTE=1: read one byte then NACK/STOP (OT host pattern).
        await self.csr_write(
            "I2C0_FDATA_ARA_READ",
            I2C0_FDATA,
            I2C_FDATA_READB | I2C_FDATA_STOP | 1,
        )

        rdata = 0
        saw_busy = False
        for _ in range(2000):
            status = await self.csr_read("I2C0_STATUS_ARA", I2C0_STATUS)
            if not (status & I2C_STATUS_HOSTIDLE):
                saw_busy = True
            if not (status & I2C_STATUS_RXEMPTY):
                rdata = await self.csr_read("I2C0_RDATA_ARA", I2C0_RDATA) & 0xFF
                break
            await Timer(10, units="us")
        else:
            raise AssertionError(f"DUT SMBus ARA: RX FIFO stayed empty (STATUS=0x{status:08x})")

        # Transfer may already be back in hostidle by the time RX is readable;
        # only require that we observed busy if still mid-transaction.
        if not (status & I2C_STATUS_HOSTIDLE):
            await self._wait_hostidle("DUT_SMBUS_ARA")
        elif not saw_busy:
            # RX filled while we only sampled idle — still prove FMT ran.
            cocotb.log.warning(
                "DUT_SMBUS_ARA: RX ready while HOSTIDLE stayed set "
                "(STATUS=0x%08x); accepting completed read",
                status,
            )

        cocotb.log.info(
            "DUT SMBus ARA: RDATA=0x%02X expected 0x%02X (slave_addr=0x%02X)",
            rdata,
            _SMBUS_ARA_REPLY,
            (rdata >> 1) & 0x7F,
        )
        assert rdata == _SMBUS_ARA_REPLY, (
            f"DUT SMBus ARA mismatch: got 0x{rdata:02X}, expected 0x{_SMBUS_ARA_REPLY:02X}"
        )
        self.dut_smbus_ara_ok = True

    async def body(self) -> None:
        # Bind EEPROM slave only — DUT is the I2C master for U4-2.
        self._i2c_slave = None
        if _I2C_PROTOCOL_VIP_AVAILABLE:
            try:
                self._i2c_slave = SmcI2cEepromSlave(addr=_I2C_EEPROM_ADDR)
                cocotb.log.info(
                    "I2C EEPROM slave (0x%02X) bound on tb_i2c0_* for DUT host",
                    _I2C_EEPROM_ADDR,
                )
            except Exception as exc:  # noqa: BLE001 - defensive
                cocotb.log.warning("I2C EEPROM slave bind skipped: %s", exc)

        self.clock_gate_value = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)

        for name, addr, expected in I2C_READABLE_REGS:
            await self.csr_read(name, addr, expected)

        ungated = self.clock_gate_value & ~I2C_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_UNGATE_I2C", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_UNGATED", CLOCK_GATE_CONTROL, expected=ungated)

        await self.csr_write(
            "I2C0_WRAP_ENABLE_CONTROLLER",
            I2C0_WRAP_CTRL,
            I2C_WRAP_ENABLE_CONTROLLER,
        )
        await self.csr_read(
            "I2C0_WRAP_ENABLED",
            I2C0_WRAP_CTRL,
            expected=I2C_WRAP_ENABLE_CONTROLLER,
        )
        # I2C_EN must CDC into LSIO before host/VIP traffic (same on VCS/Verilator).
        await self.wait_i2c0_lsio_ready("I2C0_WRAP_ENABLE")

        # OVRD pin-level gate (register -> pad).
        await self.csr_write("I2C0_OVRD_RELEASE", I2C0_OVRD, I2C_OVRD_RELEASE)
        await self._check_line("i2c_release", expected_scl=1, expected_sda=1)
        await self.csr_write("I2C0_OVRD_PULL_SCL_LOW", I2C0_OVRD, I2C_OVRD_PULL_SCL_LOW)
        await self._check_line("i2c_scl_low", expected_scl=0, expected_sda=1)
        await self.csr_write("I2C0_OVRD_PULL_SDA_LOW", I2C0_OVRD, I2C_OVRD_PULL_SDA_LOW)
        await self._check_line("i2c_sda_low", expected_scl=1, expected_sda=0)
        await self.csr_write("I2C0_OVRD_PULL_BOTH_LOW", I2C0_OVRD, I2C_OVRD_PULL_BOTH_LOW)
        await self._check_line("i2c_both_low", expected_scl=0, expected_sda=0)
        await self.csr_write("I2C0_OVRD_RELEASE_RESTORE", I2C0_OVRD, I2C_OVRD_RELEASE)
        await self._check_line("i2c_release_restore", expected_scl=1, expected_sda=1)

        # U4-2 hard gate: DUT controller must own the bus (VCS and Verilator).
        if self._i2c_slave is None:
            raise AssertionError("I2C EEPROM slave VIP unavailable; cannot prove DUT host path")
        await self._dut_i2c0_host_write_proof()
        await self._dut_i2c0_smbus_pec_write_proof()
        await self._dut_i2c0_smbus_ara_read_proof()

        await self.csr_write("I2C0_CTRL_DISABLE", I2C0_CTRL, 0)
        await self.csr_write(
            "CLOCK_GATE_CONTROL_RESTORE",
            CLOCK_GATE_CONTROL,
            self.clock_gate_value,
        )
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RESTORED",
            CLOCK_GATE_CONTROL,
            expected=self.clock_gate_value,
        )
        cocotb.log.info(
            "I2C U4-2/SMBus complete: host write + PEC + ARA OK "
            "(write=0x%02X@0x%02X pec_ok=%s ara_ok=%s)",
            _I2C_WRITE_BYTE,
            _I2C_WRITE_OFFSET,
            self.dut_smbus_pec_ok,
            self.dut_smbus_ara_ok,
        )
