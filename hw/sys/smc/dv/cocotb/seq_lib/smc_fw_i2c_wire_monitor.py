# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive byte-level decoder for the resolved I2C0 pad bus.

`SmcI2cBusMonitor` in smc_i2c_protocol_vip.py counts START and STOP only. The
firmware I2C leaves need what was said between them: which address was
called, in which direction, whether it was acknowledged, and how many data
bytes followed. That is what turns "the CPU says the transfer worked" into
"the bench saw a write of N bytes to 0x10 acknowledged on the wire".

Sampling is on clk_smc_i. tb_i2c0_scl / tb_i2c0_sda are the wired-AND of every
open-drain pull (DUT instances and cocotb VIPs); with +smc_i2c_shared_bus the
I2C1 and I2C2 pads carry the same resolved value, so an I2C0<->I2C1 transfer
inside the DUT is visible here bit for bit. The monitor never drives a line.

Frame boundaries follow the bus: a START (SDA falls while SCL is high) opens a
frame, a STOP (SDA rises while SCL is high) closes it, and a START inside an
open frame is a repeated START that closes the old frame and opens a new one.
Bits are the SDA level on each SCL rising edge; nine make a byte and its
acknowledge (ACK = SDA low). Clock stretching only delays the rising edge and
does not disturb the decode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import RisingEdge


@dataclass
class I2cWireFrame:
    addr7: int | None = None
    read: bool | None = None
    addr_acked: bool | None = None
    #: (byte, acked) in wire order, after the address byte.
    data: list[tuple[int, bool]] = field(default_factory=list)

    @property
    def rw(self) -> str:
        if self.read is None:
            return "?"
        return "R" if self.read else "W"

    def data_bytes(self, *, acked_only: bool) -> int:
        if acked_only:
            return sum(1 for _, ack in self.data if ack)
        return len(self.data)

    def __str__(self) -> str:
        addr = "none" if self.addr7 is None else f"0x{self.addr7:02x}{self.rw}"
        ack = "?" if self.addr_acked is None else ("ACK" if self.addr_acked else "NACK")
        payload = " ".join(f"{b:02x}{'+' if a else '-'}" for b, a in self.data)
        return f"[{addr} {ack} | {payload}]"


class SmcFwI2cWireMonitor:
    """Decode frames on tb_i2c0_scl/sda from construction until `stop()`."""

    def __init__(self, name: str = "smc_fw_i2c0_wire") -> None:
        dut = cocotb.top
        self.name = name
        self._scl = dut.tb_i2c0_scl
        self._sda = dut.tb_i2c0_sda
        self._clk = dut.clk_smc_i
        self.frames: list[I2cWireFrame] = []
        self.starts = 0
        self.stops = 0
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        prev_scl = 1
        prev_sda = 1
        bits: list[int] = []
        frame: I2cWireFrame | None = None
        while True:
            await RisingEdge(self._clk)
            if not (self._scl.value.is_resolvable and self._sda.value.is_resolvable):
                continue
            scl = int(self._scl.value)
            sda = int(self._sda.value)
            if prev_scl and scl:
                if prev_sda and not sda:
                    self.starts += 1
                    frame = I2cWireFrame()
                    self.frames.append(frame)
                    bits = []
                elif (not prev_sda) and sda:
                    self.stops += 1
                    frame = None
                    bits = []
            elif (not prev_scl) and scl and frame is not None:
                bits.append(sda)
                if len(bits) == 9:
                    byte = 0
                    for bit in bits[:8]:
                        byte = (byte << 1) | bit
                    acked = bits[8] == 0
                    if frame.addr7 is None:
                        frame.addr7 = byte >> 1
                        frame.read = bool(byte & 1)
                        frame.addr_acked = acked
                    else:
                        frame.data.append((byte, acked))
                    bits = []
            prev_scl, prev_sda = scl, sda

    def stop(self) -> None:
        self._task.cancel()

    def frames_to(self, addr7: int, *, read: bool | None = None) -> list[I2cWireFrame]:
        return [f for f in self.frames if f.addr7 == addr7 and (read is None or f.read == read)]

    def summary(self) -> str:
        by_addr: dict[str, int] = {}
        for f in self.frames:
            key = "none" if f.addr7 is None else f"0x{f.addr7:02x}{f.rw}"
            by_addr[key] = by_addr.get(key, 0) + 1
        per_addr = " ".join(f"{k}:{v}" for k, v in sorted(by_addr.items()))
        return f"starts={self.starts} stops={self.stops} frames={len(self.frames)} {per_addr}"
