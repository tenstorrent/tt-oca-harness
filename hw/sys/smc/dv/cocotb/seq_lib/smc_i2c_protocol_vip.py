# SPDX-License-Identifier: Apache-2.0
"""SMC OSS I2C protocol VIP wrapper.

Thin DUT-local bind of ``ocah_i2c_vip`` split-port BFMs onto SMC
``tb_top.sv`` I2C0 pads:

* ``tb_i2c0_sda`` / ``tb_i2c0_scl`` — resolved bus outputs (cocotb reads)
* ``tb_i2c0_sda_ext_low`` / ``tb_i2c0_scl_ext_low`` — cocotb drives ``1`` to
  pull low

SMBus / PMBus helpers remain on ``SmcI2cMasterVip`` because they are SMC
test-sequence conveniences, not generic I2C BFM features.

Public API
----------
SmcI2cEepromSlave(*, addr, size, addr_bytes, name)
SmcI2cBusMonitor(*, name)
SmcI2cMasterVip(*, speed, name) — plus smbus_* / pmbus_* helpers
"""

from __future__ import annotations

import cocotb

from ocah_i2c_vip import (
    OcahI2cImportError,
    OcahI2cSplitPortError,
    OcahI2cSplitPortMaster,
    OcahI2cSplitPortMemory,
    OcahI2cSplitPortMonitor,
)

# Keep the historical SMC error name for existing sequences.
SmcI2cVipError = OcahI2cSplitPortError


def _i2c0_pads():
    dut = cocotb.top
    return (
        dut.tb_i2c0_sda,
        dut.tb_i2c0_sda_ext_low,
        dut.tb_i2c0_scl,
        dut.tb_i2c0_scl_ext_low,
    )


class SmcI2cEepromSlave(OcahI2cSplitPortMemory):
    """I2C EEPROM slave wired to `tb_i2c0_*` split-port signals."""

    def __init__(
        self,
        *,
        addr: int = 0x50,
        size: int = 256,
        addr_bytes: int = 1,  # retained for call-site compatibility; unused by BFM
        name: str = "smc_i2c0_eeprom",
    ) -> None:
        _ = addr_bytes  # historical kwarg; cocotbext I2cMemory owns addressing
        sda, sda_o, scl, scl_o = _i2c0_pads()
        try:
            super().__init__(
                sda,
                sda_o,
                scl,
                scl_o,
                addr=addr,
                size=size,
                name=name,
            )
        except OcahI2cImportError as exc:
            raise SmcI2cVipError("cocotbext-i2c is not installed") from exc


class SmcI2cBusMonitor(OcahI2cSplitPortMonitor):
    """Passive I2C observer that records SMC I2C0 bus events."""

    def __init__(self, name: str = "smc_i2c0_monitor") -> None:
        sda, sda_o, scl, scl_o = _i2c0_pads()
        try:
            super().__init__(sda, sda_o, scl, scl_o, name=name)
        except OcahI2cImportError as exc:
            raise SmcI2cVipError("cocotbext-i2c is not installed") from exc


class SmcI2cMasterVip(OcahI2cSplitPortMaster):
    """Active I2C master on `tb_i2c0_*`, plus SMBus/PMBus helpers."""

    def __init__(
        self,
        *,
        speed: int = 100_000,
        name: str = "smc_i2c0_master",
    ) -> None:
        sda, sda_o, scl, scl_o = _i2c0_pads()
        try:
            super().__init__(
                sda,
                sda_o,
                scl,
                scl_o,
                speed=speed,
                name=name,
            )
        except OcahI2cImportError as exc:
            raise SmcI2cVipError("cocotbext-i2c is not installed") from exc

    # ------------------------------------------------------------------
    # P2-A / P2-11: SMBus + PMBus helpers
    # ------------------------------------------------------------------

    @staticmethod
    def smbus_pec(addr7: int, rw: int, data: bytes) -> int:
        """Compute SMBus PEC (CRC-8, polynomial 0x07) over an SMBus frame."""
        crc = 0
        frame = bytes([(addr7 << 1) | (rw & 1)]) + data
        for b in frame:
            crc ^= b
            for _ in range(8):
                crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        return crc & 0xFF

    async def smbus_write_with_pec(self, addr: int, data: bytes) -> int:
        """SMBus write-byte with PEC appended. Returns the computed PEC."""
        pec = self.smbus_pec(addr, 0, data)
        payload = bytes(data) + bytes([pec])
        await self.write(addr, payload)
        self.log.info(
            "SMBus write-with-PEC: addr=0x%02X data=%s pec=0x%02X",
            addr,
            data.hex(),
            pec,
        )
        return pec

    async def smbus_host_notify(self, target_addr7: int, data16: int) -> bytes:
        """SMBus Host Notify (SMBus 2.0 §5.5.11) to host address 0x08."""
        host_addr = 0x08
        payload = bytes(
            [
                (target_addr7 & 0x7F) << 1,
                data16 & 0xFF,
                (data16 >> 8) & 0xFF,
            ]
        )
        await self.write(host_addr, payload)
        self.log.info(
            "SMBus Host Notify: host=0x%02X target=0x%02X data=0x%04X payload=%s",
            host_addr,
            target_addr7,
            data16 & 0xFFFF,
            payload.hex(),
        )
        return payload

    async def smbus_query_ara(self) -> int:
        """SMBus Alert Response Address query (fixed slave 0x0C, read)."""
        ara_slave = 0x0C
        data = await self.read(ara_slave, 1)
        resp = data[0] if data else 0xFF
        self.log.info(
            "SMBus ARA (0x0C) reply=0x%02X -> slave_addr=0x%02X",
            resp,
            (resp >> 1) & 0x7F,
        )
        return resp

    @staticmethod
    def pmbus_encode_linear11(value_amps: float) -> int:
        """Encode a positive real value as PMBus Linear11."""
        if value_amps <= 0.0:
            return 0
        exp = 0
        v = value_amps
        while v > 1023 and exp < 15:
            v /= 2
            exp += 1
        while v < 512 and exp > -16:
            v *= 2
            exp -= 1
        mant = int(round(v)) & 0x7FF
        e5 = exp & 0x1F
        return ((e5 & 0x1F) << 11) | (mant & 0x7FF)

    @staticmethod
    def pmbus_decode_linear11(word: int) -> float:
        """Decode a PMBus Linear11 16-bit word to a real value."""
        mant = word & 0x7FF
        if mant & 0x400:
            mant -= 0x800
        exp = (word >> 11) & 0x1F
        if exp & 0x10:
            exp -= 0x20
        return mant * (2**exp)

    @staticmethod
    def pmbus_encode_linear16(value: float, exponent: int) -> int:
        """Encode a non-negative value as PMBus Linear16 mantissa (fixed Y)."""
        if value <= 0.0:
            return 0
        scaled = value / (2**exponent)
        mant = int(round(scaled))
        if mant < 0:
            mant = 0
        if mant > 0xFFFF:
            mant = 0xFFFF
        return mant & 0xFFFF

    @staticmethod
    def pmbus_decode_linear16(word: int, exponent: int) -> float:
        """Decode a PMBus Linear16 mantissa with a fixed exponent Y."""
        return (word & 0xFFFF) * (2**exponent)
