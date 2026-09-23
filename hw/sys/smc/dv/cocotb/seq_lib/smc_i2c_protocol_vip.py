# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I2C protocol VIP (clocked slave + timer master).

Open-drain pad model on ``tb_top.sv``:

* ``tb_i2c0_sda`` / ``tb_i2c0_scl`` — resolved bus (read)
* ``tb_i2c0_sda_ext_low`` / ``tb_i2c0_scl_ext_low`` — cocotb ``1`` pulls low

cocotbext-i2c Rising/FallingEdge waits on combinational OD nets miss updates on
Verilator, so the DUT host NACKs, sets CONTROLLER_EVENTS.NACK, and freezes with
SCL low (Idle + trans_started). This VIP avoids OD Edge waits so VCS and
Verilator run the same bus proofs.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import RisingEdge, Timer

SmcI2cVipError = RuntimeError

# Wired-AND votes for shared ext_low nets (multiple VIP entities on one bus).
_SDA_LOW: dict[int, set[int]] = {}
_SCL_LOW: dict[int, set[int]] = {}


def _pads():
    dut = cocotb.top
    # Prefer clk_smc_i (typically 2x periph) for VIP sampling. Do not use
    # `obj or fallback` — cocotb HierarchyObject is not bool-castable.
    sample_clk = getattr(dut, "clk_smc_i", None)
    if sample_clk is None:
        sample_clk = dut.clk_periph_i
    return (
        dut.tb_i2c0_sda,
        dut.tb_i2c0_sda_ext_low,
        dut.tb_i2c0_scl,
        dut.tb_i2c0_scl_ext_low,
        sample_clk,
    )


def _set_ext_low(handle, drivers: dict[int, set[int]], owner: int, pull_low: bool) -> None:
    key = id(handle)
    votes = drivers.setdefault(key, set())
    if pull_low:
        votes.add(owner)
    else:
        votes.discard(owner)
    handle.value = 1 if votes else 0


class SmcI2cEepromSlave:
    """Clocked I2C EEPROM slave (1-byte address pointer) on ``tb_i2c0_*``."""

    def __init__(
        self,
        *,
        addr: int = 0x50,
        size: int = 256,
        addr_bytes: int = 1,
        name: str = "smc_i2c0_eeprom",
    ) -> None:
        _ = addr_bytes
        self.addr = addr & 0x7F
        self.mem = bytearray(size)
        self.log = logging.getLogger(name)
        sda, sda_ext, scl, scl_ext, clk = _pads()
        self._sda = sda
        self._sda_ext = sda_ext
        self._scl = scl
        self._scl_ext = scl_ext
        self._clk = clk
        self._id = id(self)
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, False)
        _set_ext_low(self._scl_ext, _SCL_LOW, self._id, False)
        self._ptr = 0
        self.starts = 0
        self.acks = 0
        self.stops = 0
        self.bytes = 0
        self.log.info("%s bound: addr=0x%02X size=%d (clocked)", name, self.addr, size)
        self._task = cocotb.start_soon(self._run())

    def preload(self, data: bytes) -> None:
        n = min(len(data), len(self.mem))
        self.mem[:n] = data[:n]

    def read_mem(self, offset: int, length: int) -> bytes:
        return bytes(self.mem[offset : offset + length])

    def write_mem(self, offset: int, data: bytes) -> None:
        for i, b in enumerate(data):
            if 0 <= offset + i < len(self.mem):
                self.mem[offset + i] = b

    def _pull_sda(self, low: bool) -> None:
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, low)

    def _drive_bit(self, bit: int) -> None:
        # logical 0 → pull low; logical 1 → release
        self._pull_sda(not bool(bit))

    async def _run(self) -> None:
        prev_scl = 1
        prev_sda = 1
        # idle | addr | aack | wdata | wack | rprep | rdata | rack
        phase = "idle"
        bit_i = 0
        shift = 0
        rw = 0
        have_ptr = False

        while True:
            await RisingEdge(self._clk)
            try:
                scl = int(self._scl.value)
                sda = int(self._sda.value)
            except ValueError:
                # X/Z: treat as released (idle-high) so START/edge detect still
                # works under Verilator when pullups are weak/ignored.
                scl = 1
                sda = 1
            rose = (not prev_scl) and scl
            fell = prev_scl and (not scl)
            start = prev_scl and scl and prev_sda and (not sda)
            stop = prev_scl and scl and (not prev_sda) and sda

            if start:
                self.starts += 1
                phase = "addr"
                bit_i = 0
                shift = 0
                have_ptr = False
                self._pull_sda(False)
            elif stop:
                self.stops += 1
                phase = "idle"
                self._pull_sda(False)
            elif phase == "addr" and rose:
                shift = ((shift << 1) | sda) & 0xFF
                bit_i += 1
                if bit_i >= 8:
                    phase = "aack"
                    bit_i = 0
            elif phase == "aack" and fell:
                addr7 = (shift >> 1) & 0x7F
                rw = shift & 1
                if addr7 != self.addr:
                    self._pull_sda(False)
                    phase = "idle"
                else:
                    self._pull_sda(True)  # ACK
                    self.acks += 1
                    phase = "rprep" if rw else "wack_hold"
                    if rw:
                        shift = self.mem[self._ptr % len(self.mem)]
                        bit_i = 0
                    else:
                        shift = 0
                        have_ptr = False
                        bit_i = 0
            elif phase == "wack_hold" and rose:
                # Master sampled address/data ACK.
                phase = "wack_rel"
            elif phase == "wack_rel" and fell:
                self._pull_sda(False)
                phase = "wdata"
            elif phase == "wdata" and rose:
                shift = ((shift << 1) | sda) & 0xFF
                bit_i += 1
                if bit_i >= 8:
                    phase = "wack"
                    bit_i = 0
            elif phase == "wack" and fell:
                self._pull_sda(True)
                if not have_ptr:
                    self._ptr = shift % len(self.mem)
                    have_ptr = True
                else:
                    self.mem[self._ptr % len(self.mem)] = shift
                    self.bytes += 1
                    self._ptr = (self._ptr + 1) % len(self.mem)
                shift = 0
                phase = "wack_hold"
            elif phase == "rprep" and rose:
                # Master sampled address ACK; prepare first data bit on fall.
                phase = "rdata"
                bit_i = 0
            elif phase == "rdata" and fell:
                if bit_i < 8:
                    self._drive_bit((shift >> (7 - bit_i)) & 1)
                else:
                    self._pull_sda(False)
                    phase = "rack"
            elif phase == "rdata" and rose:
                bit_i += 1
            elif phase == "rack" and rose:
                if sda:
                    phase = "idle"
                    self._pull_sda(False)
                else:
                    self._ptr = (self._ptr + 1) % len(self.mem)
                    shift = self.mem[self._ptr % len(self.mem)]
                    bit_i = 0
                    phase = "rdata"

            prev_scl = scl
            prev_sda = sda


class SmcI2cNackSlave:
    """Clocked I2C target that injects address- or data-phase NACKs.

    Used by ``smc_i2c_p0_nack_test``. Drives SDA ACK/NACK on ``tb_i2c0_*``.
    """

    def __init__(
        self,
        *,
        addr: int = 0x10,
        nack_at_address: bool = False,
        nack_at_data: bool = False,
        name: str = "smc_i2c0_nack",
    ) -> None:
        if nack_at_address == nack_at_data:
            raise ValueError("exactly one of nack_at_address / nack_at_data")
        self.addr = addr & 0x7F
        self.nack_at_address = nack_at_address
        self.nack_at_data = nack_at_data
        self.log = logging.getLogger(name)
        self.addr_nacks = 0
        self.data_nacks = 0
        self.addr_acks = 0
        sda, sda_ext, scl, scl_ext, clk = _pads()
        self._sda = sda
        self._sda_ext = sda_ext
        self._scl = scl
        self._scl_ext = scl_ext
        self._clk = clk
        self._id = id(self)
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, False)
        _set_ext_low(self._scl_ext, _SCL_LOW, self._id, False)
        self.log.info(
            "%s bound: addr=0x%02X nack_addr=%s nack_data=%s",
            name,
            self.addr,
            nack_at_address,
            nack_at_data,
        )
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if hasattr(self, "_task") and self._task is not None:
            self._task.cancel()
            self._task = None
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, False)
        _set_ext_low(self._scl_ext, _SCL_LOW, self._id, False)

    def _pull_sda(self, low: bool) -> None:
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, low)

    async def _run(self) -> None:
        prev_scl = 1
        prev_sda = 1
        phase = "idle"
        bit_i = 0
        shift = 0

        while True:
            await RisingEdge(self._clk)
            try:
                scl = int(self._scl.value)
                sda = int(self._sda.value)
            except ValueError:
                scl = 1
                sda = 1
            rose = (not prev_scl) and scl
            fell = prev_scl and (not scl)
            start = prev_scl and scl and prev_sda and (not sda)
            stop = prev_scl and scl and (not prev_sda) and sda

            if start:
                phase = "addr"
                bit_i = 0
                shift = 0
                self._pull_sda(False)
            elif stop:
                phase = "idle"
                self._pull_sda(False)
            elif phase == "addr" and rose:
                shift = ((shift << 1) | sda) & 0xFF
                bit_i += 1
                if bit_i >= 8:
                    phase = "aack"
                    bit_i = 0
            elif phase == "aack" and fell:
                addr7 = (shift >> 1) & 0x7F
                if addr7 != self.addr:
                    self._pull_sda(False)
                    phase = "idle"
                elif self.nack_at_address:
                    # Hold released SDA through the 9th SCL rise (NACK sample).
                    self._pull_sda(False)
                    self.addr_nacks += 1
                    phase = "nack_hold"
                else:
                    self._pull_sda(True)  # ACK address
                    self.addr_acks += 1
                    phase = "wack_hold"
                    shift = 0
                    bit_i = 0
            elif phase == "nack_hold" and rose:
                phase = "idle"
                self._pull_sda(False)
            elif phase == "wack_hold" and rose:
                phase = "wack_rel"
            elif phase == "wack_rel" and fell:
                self._pull_sda(False)
                phase = "wdata"
            elif phase == "wdata" and rose:
                shift = ((shift << 1) | sda) & 0xFF
                bit_i += 1
                if bit_i >= 8:
                    phase = "wack"
                    bit_i = 0
            elif phase == "wack" and fell:
                if self.nack_at_data:
                    self._pull_sda(False)  # NACK data — hold through sample
                    self.data_nacks += 1
                    phase = "nack_hold"
                else:
                    self._pull_sda(True)
                    phase = "wack_hold"
                    shift = 0

            prev_scl = scl
            prev_sda = sda


class SmcI2cBusMonitor:
    """Passive START/STOP observer (never ACKs)."""

    def __init__(self, name: str = "smc_i2c0_monitor") -> None:
        self.log = logging.getLogger(name)
        self.transactions: list[dict] = []
        sda, sda_ext, scl, scl_ext, clk = _pads()
        self._sda = sda
        self._scl = scl
        self._clk = clk
        self._sda_ext = sda_ext
        self._scl_ext = scl_ext
        self._id = id(self)
        # Join the wired-AND vote registry; do not clear other VIP pulls.
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, False)
        _set_ext_low(self._scl_ext, _SCL_LOW, self._id, False)
        self.log.info("%s bound (clocked, passive)", name)
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        prev_scl = 1
        prev_sda = 1
        while True:
            await RisingEdge(self._clk)
            try:
                scl = int(self._scl.value)
                sda = int(self._sda.value)
            except ValueError:
                scl = 1
                sda = 1
            if prev_scl and scl and prev_sda and (not sda):
                self.transactions.append({"ev": "START"})
            elif prev_scl and scl and (not prev_sda) and sda:
                self.transactions.append({"ev": "STOP"})
            prev_scl = scl
            prev_sda = sda


class SmcI2cMasterVip:
    """Timer bit-bang I2C master (level-based stretch wait, no OD Edge)."""

    #: Half periods the wait for SCL allowed before this became configurable.
    #: The default bound is expressed in those terms so an existing caller
    #: sees the same behaviour it always did.
    DEFAULT_SCL_TIMEOUT_HALF_PERIODS = 100000

    def __init__(
        self,
        *,
        speed: int = 100_000,
        name: str = "smc_i2c0_master",
        scl_timeout_ns: int | None = None,
    ) -> None:
        self.log = logging.getLogger(name)
        self.speed = speed
        sda, sda_ext, scl, scl_ext, _clk = _pads()
        self._sda = sda
        self._sda_ext = sda_ext
        self._scl = scl
        self._scl_ext = scl_ext
        self._id = id(self)
        self._bit_ns = max(1, int(1e9 / speed))
        self._half_ns = max(1, self._bit_ns // 2)
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, False)
        _set_ext_low(self._scl_ext, _SCL_LOW, self._id, False)
        self._active = False
        self.scl_timeout_ns = (
            scl_timeout_ns
            if scl_timeout_ns is not None
            else self.DEFAULT_SCL_TIMEOUT_HALF_PERIODS * self._half_ns
        )
        #: How long the last wait for SCL took, in ns. Published so a caller
        #: can report a hold it tolerated as well as one it failed on.
        self.last_scl_hold_ns = 0
        self.log.info(
            "%s bound: speed=%d scl_timeout=%d ns (timer bit-bang)",
            name,
            speed,
            self.scl_timeout_ns,
        )

    def set_speed(self, speed: int) -> None:
        """Change the bit rate, including part-way through a transfer.

        A controller that changes rate mid-transfer is the only way to give a
        target one bit period at one rate and the next at another, which is
        what a test of the target's own timing thresholds needs. The timeout
        for a held clock is left where the caller set it, since it bounds the
        other device's behaviour rather than this one's.
        """
        self.speed = speed
        self._bit_ns = max(1, int(1e9 / speed))
        self._half_ns = max(1, self._bit_ns // 2)
        self.log.info(
            "%s speed changed: %d (half period %d ns)", self.log.name, speed, self._half_ns
        )

    def _pull_sda(self, low: bool) -> None:
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, low)

    def _pull_scl(self, low: bool) -> None:
        _set_ext_low(self._scl_ext, _SCL_LOW, self._id, low)

    async def _wait_scl_high(self) -> None:
        """Wait for SCL to be released, giving up after ``scl_timeout_ns``.

        Another device holding the clock is the normal way an I2C transfer is
        paused, so this waits rather than failing immediately. What it does
        not do is wait without a stated bound: the hold is measured, published
        on ``last_scl_hold_ns``, and named in the error, so a caller that
        wedges here reports how long the clock was held instead of running to
        the end of its own timeout.
        """
        waited = 0
        while waited < self.scl_timeout_ns:
            if int(self._scl.value):
                self.last_scl_hold_ns = waited
                return
            await Timer(self._half_ns, unit="ns")
            waited += self._half_ns
        self.last_scl_hold_ns = waited
        raise SmcI2cVipError(
            f"SCL stayed low for {waited} ns (bound {self.scl_timeout_ns} ns): another "
            f"device is holding the clock"
        )

    async def send_start(self) -> None:
        if self._active:
            self._pull_sda(False)
            await Timer(self._half_ns, unit="ns")
            self._pull_scl(False)
            await self._wait_scl_high()
            await Timer(self._half_ns, unit="ns")
        self._pull_sda(True)
        await Timer(self._half_ns, unit="ns")
        self._pull_scl(True)
        await Timer(self._half_ns, unit="ns")
        self._active = True

    async def send_stop(self) -> None:
        if not self._active:
            return
        self._pull_sda(True)
        await Timer(self._half_ns, unit="ns")
        self._pull_scl(False)
        await self._wait_scl_high()
        await Timer(self._half_ns, unit="ns")
        self._pull_sda(False)
        await Timer(self._half_ns, unit="ns")
        self._active = False

    async def send_bit(self, bit: int) -> None:
        self._pull_sda(not bool(bit))
        await Timer(self._half_ns, unit="ns")
        self._pull_scl(False)
        await self._wait_scl_high()
        await Timer(self._bit_ns, unit="ns")
        self._pull_scl(True)
        await Timer(self._half_ns, unit="ns")

    async def recv_bit(self) -> int:
        self._pull_sda(False)
        await Timer(self._half_ns, unit="ns")
        self._pull_scl(False)
        await self._wait_scl_high()
        await Timer(self._half_ns, unit="ns")
        val = int(self._sda.value)
        await Timer(self._half_ns, unit="ns")
        self._pull_scl(True)
        await Timer(self._half_ns, unit="ns")
        return val

    async def send_byte(self, value: int) -> int:
        for i in range(8):
            await self.send_bit((value >> (7 - i)) & 1)
        return await self.recv_bit()

    async def recv_byte(self, ack: bool) -> int:
        value = 0
        for _ in range(8):
            value = (value << 1) | await self.recv_bit()
        await self.send_bit(0 if ack else 1)
        return value & 0xFF

    async def write(self, addr: int, data: bytes) -> None:
        self.log.info("Write %s to device at I2C address 0x%02x", data, addr)
        await self.send_start()
        if await self.send_byte((addr & 0x7F) << 1):
            await self.send_stop()
            raise SmcI2cVipError(f"I2C write addr 0x{addr:02X} NACK")
        for b in data:
            if await self.send_byte(b):
                await self.send_stop()
                raise SmcI2cVipError(f"I2C write data NACK (addr=0x{addr:02X})")
        await self.send_stop()

    async def read(self, addr: int, count: int) -> bytes:
        self.log.info("Read %d bytes from device at I2C address 0x%02x", count, addr)
        await self.send_start()
        if await self.send_byte(((addr & 0x7F) << 1) | 1):
            await self.send_stop()
            # Match cocotbext-i2c: address NACK → return 0xFF bytes (no raise).
            return bytes([0xFF] * count)
        out = bytearray()
        for i in range(count):
            out.append(await self.recv_byte(ack=(i != count - 1)))
        await self.send_stop()
        return bytes(out)

    @staticmethod
    def smbus_pec(addr7: int, rw: int, data: bytes) -> int:
        crc = 0
        frame = bytes([(addr7 << 1) | (rw & 1)]) + data
        for b in frame:
            crc ^= b
            for _ in range(8):
                crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        return crc & 0xFF

    async def smbus_write_with_pec(self, addr: int, data: bytes) -> int:
        pec = self.smbus_pec(addr, 0, data)
        await self.write(addr, bytes(data) + bytes([pec]))
        self.log.info(
            "SMBus write-with-PEC: addr=0x%02X data=%s pec=0x%02X",
            addr,
            data.hex(),
            pec,
        )
        return pec

    async def smbus_host_notify(self, target_addr7: int, data16: int) -> bytes:
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
        data = await self.read(0x0C, 1)
        resp = data[0] if data else 0xFF
        self.log.info(
            "SMBus ARA (0x0C) reply=0x%02X -> slave_addr=0x%02X",
            resp,
            (resp >> 1) & 0x7F,
        )
        return resp

    @staticmethod
    def pmbus_encode_linear11(value_amps: float) -> int:
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
        return ((exp & 0x1F) << 11) | (mant & 0x7FF)

    @staticmethod
    def pmbus_decode_linear11(word: int) -> float:
        mant = word & 0x7FF
        if mant & 0x400:
            mant -= 0x800
        exp = (word >> 11) & 0x1F
        if exp & 0x10:
            exp -= 0x20
        return mant * (2**exp)

    @staticmethod
    def pmbus_encode_linear16(value: float, exponent: int) -> int:
        if value <= 0.0:
            return 0
        mant = int(round(value / (2**exponent)))
        return max(0, min(0xFFFF, mant)) & 0xFFFF

    @staticmethod
    def pmbus_decode_linear16(word: int, exponent: int) -> float:
        return (word & 0xFFFF) * (2**exponent)
