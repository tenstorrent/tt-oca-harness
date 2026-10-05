# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_i2c_master_target_test / smc_i2c_p1_rdwr_protocol_test.

U4-2: DUT OpenTitan I2C0 host writes a byte into a cocotb EEPROM slave on
``tb_i2c0_*`` pads (not VIP↔VIP). Also proves the OVRD register -> pad gate.

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

from .smc_addr_map import (
    _REPO,
    I2C_CG_EN,
    _field_mask,
    smc_addr,
    smc_indexed_addr,
)

# Generated PeakRDL C headers for the OpenTitan-derived I2C core and for the SMC
# I2C wrapper's control block. Field masks and bit positions below are imported
# by symbol from these, like the register addresses, so a regenerated map moves
# this sequence with it ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
_I2C_H = _REPO / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c.h"
_I2C_CTRL_H = _REPO / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c_ctrl.h"


def _i2c_u32(symbol: str) -> int:
    """Field mask / bit position from generated ``i2c.h``."""
    return _field_mask(_I2C_H, symbol)


def _i2c_ctrl_u32(symbol: str) -> int:
    """Field mask / bit position from generated ``i2c_ctrl.h``."""
    return _field_mask(_I2C_CTRL_H, symbol)


def _i2c_field(reg: str, field: str, value: int) -> int:
    """Place ``value`` in ``reg.field`` using the generated mask/position."""
    mask = _i2c_u32(f"I2C__{reg}__{field}_bm")
    pos = _i2c_u32(f"I2C__{reg}__{field}_bp")
    packed = (value << pos) & mask
    assert packed >> pos == value, (
        f"{value:#x} does not fit I2C.{reg}.{field} (mask {mask:#x} at bit {pos})"
    )
    return packed


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

# I2C_CTRL (SMC wrapper): enable the instance and put it in controller mode.
I2C_WRAP_ENABLE_CONTROLLER = _i2c_ctrl_u32("I2C_CTRL__I2C_CTRL__I2C_EN_bm") | _i2c_ctrl_u32(
    "I2C_CTRL__I2C_CTRL__I2C_CONTROLLER_MODE_EN_bm"
)
I2C_CTRL_ENABLEHOST = _i2c_u32("I2C__CTRL__ENABLEHOST_bm")

# OVRD: TXOVRDEN enables the pin override; SCLVAL / SDAVAL are the driven
# levels, so "pull low" = override on with that value bit cleared.
_I2C_OVRD_TXOVRDEN = _i2c_u32("I2C__OVRD__TXOVRDEN_bm")
_I2C_OVRD_SCLVAL = _i2c_u32("I2C__OVRD__SCLVAL_bm")
_I2C_OVRD_SDAVAL = _i2c_u32("I2C__OVRD__SDAVAL_bm")
I2C_OVRD_RELEASE = _I2C_OVRD_TXOVRDEN | _I2C_OVRD_SCLVAL | _I2C_OVRD_SDAVAL
I2C_OVRD_PULL_SCL_LOW = _I2C_OVRD_TXOVRDEN | _I2C_OVRD_SDAVAL
I2C_OVRD_PULL_SDA_LOW = _I2C_OVRD_TXOVRDEN | _I2C_OVRD_SCLVAL
I2C_OVRD_PULL_BOTH_LOW = _I2C_OVRD_TXOVRDEN
I2C_OVRD_OFF = 0x0

I2C_FIFO_CTRL_RXRST_FMTRST = _i2c_u32("I2C__FIFO_CTRL__RXRST_bm") | _i2c_u32(
    "I2C__FIFO_CTRL__FMTRST_bm"
)
I2C_STATUS_HOSTIDLE = _i2c_u32("I2C__STATUS__HOSTIDLE_bm")
I2C_STATUS_RXEMPTY = _i2c_u32("I2C__STATUS__RXEMPTY_bm")
I2C_FDATA_START = _i2c_u32("I2C__FDATA__START_bm")
I2C_FDATA_STOP = _i2c_u32("I2C__FDATA__STOP_bm")
I2C_FDATA_READB = _i2c_u32("I2C__FDATA__READB_bm")

# W1C of every controller event (sticky NACK / timeouts / arbitration loss), so a
# prior attempt cannot leave the host halted in IDLE with SCL held.
I2C_CONTROLLER_EVENTS_ALL = (
    _i2c_u32("I2C__CONTROLLER_EVENTS__NACK_bm")
    | _i2c_u32("I2C__CONTROLLER_EVENTS__UNHANDLED_NACK_TIMEOUT_bm")
    | _i2c_u32("I2C__CONTROLLER_EVENTS__BUS_TIMEOUT_bm")
    | _i2c_u32("I2C__CONTROLLER_EVENTS__ARBITRATION_LOST_bm")
)

I2C_READABLE_REGS = [
    ("I2C0_INTR_STATE", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0), 0x0),
    ("I2C0_STATUS", I2C0_STATUS, None),
    ("I2C1_INTR_STATE", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 1), 0x0),
    ("I2C2_INTR_STATE", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 2), 0x0),
]


def _fdata(byte: int, flags: int = 0) -> int:
    """One FMT-FIFO word: the FBYTE payload plus START/STOP/READB control bits."""
    return _i2c_field("FDATA", "FBYTE", byte) | flags


def _pack_timing0(thigh: int, tlow: int) -> int:
    return _i2c_field("TIMING0", "THIGH", thigh) | _i2c_field("TIMING0", "TLOW", tlow)


def _pack_timing1(t_r: int, t_f: int) -> int:
    return _i2c_field("TIMING1", "T_R", t_r) | _i2c_field("TIMING1", "T_F", t_f)


def _pack_timing2(tsu_sta: int, thd_sta: int) -> int:
    return _i2c_field("TIMING2", "TSU_STA", tsu_sta) | _i2c_field("TIMING2", "THD_STA", thd_sta)


def _pack_timing3(tsu_dat: int, thd_dat: int) -> int:
    return _i2c_field("TIMING3", "TSU_DAT", tsu_dat) | _i2c_field("TIMING3", "THD_DAT", thd_dat)


def _pack_timing4(tsu_sto: int, t_buf: int) -> int:
    return _i2c_field("TIMING4", "TSU_STO", tsu_sto) | _i2c_field("TIMING4", "T_BUF", t_buf)


class smc_i2c_master_target_test_seq(SmcCsrSeq):
    # Bounded poll budget for the OVRD register -> LSIO pad path, and the
    # number of consecutive matching samples required before the pad level is
    # accepted (a settled level, not a mid-transition glitch).
    OVRD_PAD_TIMEOUT_CYCLES = 400
    OVRD_PAD_STABLE_CYCLES = 8
    # Bounded poll budget for the pad-level EEPROM VIP to frame the STOP of a
    # DUT host transfer after the DUT host controller reports hostidle.
    SLAVE_STOP_TIMEOUT_US = 200

    def __init__(self, name: str = "smc_i2c_master_target_test_seq") -> None:
        super().__init__(name)
        self.clock_gate_value: int = 0
        self.dut_host_write_ok: bool = False
        #: START/STOP counts the EEPROM VIP framed for the repeated-START pair.
        self.dut_host_restart_starts: int = -1
        self.dut_host_restart_stops: int = -1
        self.dut_smbus_pec_ok: bool = False
        self.dut_smbus_ara_ok: bool = False
        # Bytes MEASURED on the DUT side of the bus (EEPROM VIP memory and
        # I2C0_RDATA). Consumers use these as protocol-VIP observed_bytes;
        # they are never copied from an expectation or from an OK flag.
        self.obs_host_write: bytes = b""
        self.obs_smbus_pec: bytes = b""
        self.obs_smbus_ara: bytes = b""

    @classmethod
    async def _check_line(cls, name: str, expected_scl: int, expected_sda: int) -> None:
        """Poll tb_i2c0_scl/sda until the OVRD-driven levels settle, or fail.

        Bounded poll on a real observable (the resolved pad nets) instead of a
        fixed settling delay: expiry raises with the last sampled state.
        """
        dut = cocotb.top
        last_scl: int | str = "?"
        last_sda: int | str = "?"
        stable = 0
        for _ in range(cls.OVRD_PAD_TIMEOUT_CYCLES):
            await ClockCycles(dut.clk_smc_i, 1)
            try:
                last_scl = int(dut.tb_i2c0_scl.value)
                last_sda = int(dut.tb_i2c0_sda.value)
            except ValueError:  # X/Z while the pad is still resolving
                last_scl = str(dut.tb_i2c0_scl.value)
                last_sda = str(dut.tb_i2c0_sda.value)
                stable = 0
                continue
            if last_scl == expected_scl and last_sda == expected_sda:
                stable += 1
                if stable >= cls.OVRD_PAD_STABLE_CYCLES:
                    cocotb.log.info(
                        "CHK-I2C0-OVRD-PAD: %s scl=%d sda=%d held for %d "
                        "clk_smc_i cycles, expected (%d,%d) dut_low=(%d,%d)",
                        name,
                        last_scl,
                        last_sda,
                        stable,
                        expected_scl,
                        expected_sda,
                        int(dut.tb_i2c0_scl_dut_low.value),
                        int(dut.tb_i2c0_sda_dut_low.value),
                    )
                    return
            else:
                stable = 0
        raise AssertionError(
            f"{name}: tb_i2c0 pads never held SCL={expected_scl} "
            f"SDA={expected_sda} for {cls.OVRD_PAD_STABLE_CYCLES} cycles "
            f"within {cls.OVRD_PAD_TIMEOUT_CYCLES} clk_smc_i cycles "
            f"(last scl={last_scl} sda={last_sda})"
        )

    async def _wait_slave_stop(self, label: str, base_stops: int) -> None:
        """Poll the EEPROM VIP until it frames a new STOP on ``tb_i2c0_*``.

        The VIP commits a received byte to ``mem`` on the ACK that precedes
        STOP, so a newly observed STOP is the completion handshake for the
        slave-side update. Expiry fails with the VIP's framing counters.
        """
        slave = self._i2c_slave
        assert slave is not None
        for _ in range(self.SLAVE_STOP_TIMEOUT_US):
            if slave.stops > base_stops:
                return
            await Timer(1, unit="us")
        raise AssertionError(
            f"{label}: EEPROM VIP framed no STOP on tb_i2c0_* within "
            f"{self.SLAVE_STOP_TIMEOUT_US} us of hostidle "
            f"(stops={slave.stops} base={base_stops} starts={slave.starts} "
            f"acks={slave.acks} bytes={slave.bytes})"
        )

    async def _program_i2c0_timing(self) -> None:
        """Load OpenTitan host timing (FW standard-mode defaults)."""
        # Conservative TIMING defaults.
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))

    async def _wait_hostidle(self, label: str) -> None:
        status = 0
        # Ensure the host actually left IDLE (FMT accepted) before waiting for
        # completion — otherwise a no-op FIFO write looks like instant success.
        left_idle = False
        for _ in range(200):
            status = await self.csr_read(f"{label}_BUSY", I2C0_STATUS)
            if not (status & I2C_STATUS_HOSTIDLE):
                left_idle = True
                break
            await Timer(1, unit="us")
        if not left_idle:
            cevents = await self.csr_read(f"{label}_CEVENTS_STUCK", I2C0_CONTROLLER_EVENTS)
            raise AssertionError(
                f"{label}: DUT I2C0 host never left hostidle after FMT push "
                f"(STATUS=0x{status:08x} CONTROLLER_EVENTS=0x{cevents:08x})"
            )
        # Completion bound: 200 polls x 10 us of sim time, well above a 3-byte host transfer.
        for _ in range(200):
            status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await Timer(10, unit="us")
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
        # W1C: clear sticky NACK/halt so a prior attempt cannot freeze IDLE+SCL.
        await self.csr_write(
            "I2C0_CONTROLLER_EVENTS_CLR",
            I2C0_CONTROLLER_EVENTS,
            I2C_CONTROLLER_EVENTS_ALL,
        )
        await self.csr_write("I2C0_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)

        base_stops = self._i2c_slave.stops
        base_starts = self._i2c_slave.starts
        addr_byte = (_I2C_EEPROM_ADDR << 1) | 0  # write
        # Two write frames joined by a repeated START: the first frame's last
        # entry carries no STOP, so the second frame's FDATA.START is issued
        # with the transaction still open and the controller has to release SDA
        # and re-drive the START condition rather than closing the bus. The
        # OpenTitan controller has no separate restart control -- the same
        # FDATA.START bit is a repeated START when a transaction is already in
        # flight (i2c_controller_fsm.sv) -- so the only difference from the
        # single-frame version is the dropped STOP.
        #
        # Both frames address the same EEPROM offset with the same byte, so the
        # payload expectation below is unchanged and the new evidence is purely
        # the framing: two STARTs against one STOP.
        for label, flags in (
            ("I2C0_FDATA_START_ADDR", I2C_FDATA_START),
            ("I2C0_FDATA_RESTART_ADDR", I2C_FDATA_START),
        ):
            await self.csr_write(label, I2C0_FDATA, _fdata(addr_byte, flags))
            await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(_I2C_WRITE_OFFSET))
            stop = I2C_FDATA_STOP if label == "I2C0_FDATA_RESTART_ADDR" else 0
            await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(_I2C_WRITE_BYTE, stop))

        await self._wait_hostidle("DUT_HOST_WRITE")
        cevents = await self.csr_read("DUT_HOST_WRITE_CEVENTS", I2C0_CONTROLLER_EVENTS)
        await self._wait_slave_stop("DUT_HOST_WRITE", base_stops)
        got = self._i2c_slave.read_mem(_I2C_WRITE_OFFSET, 1)
        self.obs_host_write = got
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
        # Framing check for the repeated START. Exact on both counters: two
        # STARTs say the second frame opened, one STOP says the bus was never
        # released between them. A controller that inserted a STOP -- the
        # behaviour every other I2C frame in this package produces -- reports
        # two STOPs here and fails, and a controller that dropped the second
        # frame reports one START and fails.
        new_starts = self._i2c_slave.starts - base_starts
        new_stops = self._i2c_slave.stops - base_stops
        assert new_starts == 2 and new_stops == 1, (
            f"DUT I2C0 repeated START: the EEPROM VIP framed {new_starts} "
            f"START(s) and {new_stops} STOP(s) on tb_i2c0_*, expected exactly "
            f"2 STARTs against 1 STOP for two write frames joined by a "
            f"repeated START"
        )
        self.dut_host_restart_starts = new_starts
        self.dut_host_restart_stops = new_stops
        cocotb.log.info(
            "CHK-I2C0-HOST-REPEATED-START: %d STARTs against %d STOP framed on "
            "tb_i2c0_* for the two write frames, so the second frame's "
            "FDATA.START was issued with the transaction still open",
            new_starts,
            new_stops,
        )
        self.dut_host_write_ok = True
        cocotb.log.info(
            "CHK-I2C0-HOST-WRITE: EEPROM VIP mem[0x%02X]=0x%s matches the "
            "0x%02X byte the DUT I2C0 host framed on tb_i2c0_*",
            _I2C_WRITE_OFFSET,
            got.hex(),
            _I2C_WRITE_BYTE,
        )

    async def _dut_i2c0_smbus_pec_write_proof(self) -> None:
        """DUT host SMBus write-with-PEC (SW CRC-8) into EEPROM on pads."""
        assert self._i2c_slave is not None
        assert SmcI2cMasterVip is not None

        payload = bytes([_SMBUS_PEC_OFFSET, _SMBUS_PEC_DATA])
        pec = SmcI2cMasterVip.smbus_pec(_I2C_EEPROM_ADDR, 0, payload)
        addr_byte = (_I2C_EEPROM_ADDR << 1) | 0

        await self.csr_write("I2C0_FIFO_RST_PEC", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        base_stops = self._i2c_slave.stops
        await self.csr_write("I2C0_FDATA_PEC_START", I2C0_FDATA, _fdata(addr_byte, I2C_FDATA_START))
        await self.csr_write("I2C0_FDATA_PEC_OFFSET", I2C0_FDATA, _fdata(_SMBUS_PEC_OFFSET))
        await self.csr_write("I2C0_FDATA_PEC_DATA", I2C0_FDATA, _fdata(_SMBUS_PEC_DATA))
        await self.csr_write("I2C0_FDATA_PEC_STOP", I2C0_FDATA, _fdata(pec, I2C_FDATA_STOP))

        await self._wait_hostidle("DUT_SMBUS_PEC")
        await self._wait_slave_stop("DUT_SMBUS_PEC", base_stops)
        stored = self._i2c_slave.read_mem(_SMBUS_PEC_OFFSET, 2)
        self.obs_smbus_pec = stored
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
        cocotb.log.info(
            "CHK-I2C0-SMBUS-PEC: EEPROM VIP mem[0x%02X]=0x%s matches data "
            "0x%02X + CRC-8 PEC 0x%02X framed by the DUT host",
            _SMBUS_PEC_OFFSET,
            stored.hex(),
            _SMBUS_PEC_DATA,
            pec,
        )

    async def _dut_i2c0_smbus_ara_read_proof(self) -> None:
        """DUT host ARA query: read 1 byte from VIP @ 0x0C on tb_i2c0_*."""
        assert _I2C_PROTOCOL_VIP_AVAILABLE and SmcI2cEepromSlave is not None

        ara_slave = SmcI2cEepromSlave(addr=_SMBUS_ARA_ADDR, name="smc_i2c0_ara")
        ara_slave.write_mem(0, bytes([_SMBUS_ARA_REPLY]))

        await self.csr_write("I2C0_FIFO_RST_ARA", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        addr_r = (_SMBUS_ARA_ADDR << 1) | 1
        await self.csr_write("I2C0_FDATA_ARA_START", I2C0_FDATA, _fdata(addr_r, I2C_FDATA_START))
        # READB + STOP + FBYTE=1: read one byte then NACK/STOP (OT host pattern).
        await self.csr_write(
            "I2C0_FDATA_ARA_READ",
            I2C0_FDATA,
            _fdata(1, I2C_FDATA_READB | I2C_FDATA_STOP),
        )

        rdata = 0
        saw_busy = False
        for _ in range(2000):
            status = await self.csr_read("I2C0_STATUS_ARA", I2C0_STATUS)
            if not (status & I2C_STATUS_HOSTIDLE):
                saw_busy = True
            if not (status & I2C_STATUS_RXEMPTY):
                rdata = await self.csr_read("I2C0_RDATA_ARA", I2C0_RDATA) & 0xFF
                self.obs_smbus_ara = bytes([rdata])
                break
            await Timer(10, unit="us")
        else:
            raise AssertionError(f"DUT SMBus ARA: RX FIFO stayed empty (STATUS=0x{status:08x})")

        # Transfer may already be back in hostidle by the time RX is readable, so
        # busy is not always sampled. Either way the FMT entries must be proven
        # to have run on the bus: `saw_busy` (the host left IDLE) or the ARA
        # responder framing a START addressed to it. Both are DUT observations,
        # and the CSR poll alone is not accepted as proof.
        ara_starts = ara_slave.starts
        assert saw_busy or ara_starts > 0, (
            "DUT_SMBUS_ARA: the host never left HOSTIDLE in any poll and the ARA "
            f"responder @0x{_SMBUS_ARA_ADDR:02X} framed no START on tb_i2c0_* "
            f"(starts={ara_starts} acks={ara_slave.acks} stops={ara_slave.stops} "
            f"bytes={ara_slave.bytes}, STATUS=0x{status:08x}): the FMT entries "
            "were never executed on the bus, so a readable RX FIFO is not "
            "evidence of an ARA transfer"
        )
        if not (status & I2C_STATUS_HOSTIDLE):
            await self._wait_hostidle("DUT_SMBUS_ARA")

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
        cocotb.log.info(
            "CHK-I2C0-SMBUS-ARA: I2C0_RDATA=0x%02X matches the alerting-slave "
            "address byte 0x%02X returned by the ARA responder @0x%02X "
            "(FMT execution proven by host_left_idle=%s / responder starts=%d)",
            rdata,
            _SMBUS_ARA_REPLY,
            _SMBUS_ARA_ADDR,
            saw_busy,
            ara_starts,
        )

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
        assert self.dut_host_write_ok and self.dut_smbus_pec_ok and self.dut_smbus_ara_ok, (
            "I2C U4-2/SMBus incomplete: "
            f"write={self.dut_host_write_ok} pec={self.dut_smbus_pec_ok} "
            f"ara={self.dut_smbus_ara_ok}"
        )
        cocotb.log.info(
            "CHK-I2C0-U4-2-SMBUS: host write 0x%02X@0x%02X + PEC store %s + "
            "ARA reply %s all matched (measured on tb_i2c0_* / I2C0_RDATA)",
            _I2C_WRITE_BYTE,
            _I2C_WRITE_OFFSET,
            self.obs_smbus_pec.hex(),
            self.obs_smbus_ara.hex(),
        )
