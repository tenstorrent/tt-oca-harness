# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Driving an I2C transaction up to a chosen bit slot, and parking the bus there.

Several target-side behaviours are global overrides: they act from whatever
state the state machine happens to be in, so reaching them across the state
space means holding the bus in a chosen slot rather than sending a particular
byte. `hw/ip/i2c/regs/i2c.rdl` and `hw/ip/i2c/doc/architecture.adoc` name three
that this bench can drive from the pads:

* a **bus timeout**, which `TIMEOUT_CTRL` arms and which counts SCL low time
  from every source -- "the counter resets when SCL goes high, so this count
  only accumulates during a single bit transfer", so parking SCL low is what
  makes it expire,
* a **bus inactive timeout**, which `HOST_TIMEOUT_CTRL` arms and which the bus
  monitor counts while the bus is busy and idling with SCL high, and
* **arbitration lost or SDA interference**, which the bus monitor raises when a
  device attempts to transmit a logic high while another pulls SDA low.

A slot is one call to the VIP's `send_bit`, so the positions here come from the
bit timing the VIP already owns rather than from any design constant.
"""

from __future__ import annotations

from cocotb.triggers import Timer

from .smc_i2c_protocol_vip import SmcI2cMasterVip

# Slots a transaction can be held at. "addr" k is after k bits of the address
# byte, "addrack" after the address acknowledge has been clocked, "data" k
# after k bits of the payload byte, "dataack" after the payload acknowledge.
POST_ADDR_SLOTS = [("addrack", 0)] + [("data", k) for k in range(1, 8)] + [("dataack", 0)]


async def drive_to_slot(
    vip: SmcI2cMasterVip,
    addr7: int,
    data_byte: int,
    phase: str,
    k: int,
    read: bool = False,
) -> None:
    """Drive a transaction up to ``phase``/``k`` and stop clocking there."""
    addr_byte = ((addr7 & 0x7F) << 1) | int(read)
    await vip.send_start()
    for i in range(k if phase == "addr" else 8):
        await vip.send_bit((addr_byte >> (7 - i)) & 1)
    if phase == "addr":
        return
    await vip.recv_bit()
    if phase == "addrack":
        return
    for i in range(k if phase == "data" else 8):
        await vip.send_bit((data_byte >> (7 - i)) & 1)
    if phase == "data":
        return
    await vip.recv_bit()


async def park_scl_low(vip: SmcI2cMasterVip, hold_ns: int) -> None:
    """Hold SCL low for ``hold_ns``, then release it.

    The bus timeout counter only accumulates while SCL is low and resets when
    it goes high, so a hold longer than the programmed value is what makes it
    expire. The VIP's own pad pulls are used so the hold matches the bit
    timing of the transaction it interrupts.
    """
    vip._pull_scl(True)
    await Timer(hold_ns, unit="ns")
    vip._pull_scl(False)
    await vip._wait_scl_high()
    await Timer(vip._half_ns, unit="ns")


async def park_scl_high(vip: SmcI2cMasterVip, hold_ns: int) -> None:
    """Leave SCL released for ``hold_ns`` in the middle of a transaction.

    No STOP is sent, so the bus stays busy while it idles, which is the
    condition the bus monitor counts its inactive timeout against.
    """
    vip._pull_scl(False)
    await vip._wait_scl_high()
    await Timer(hold_ns, unit="ns")


async def pull_sda_low(vip: SmcI2cMasterVip, hold_ns: int) -> None:
    """Pull SDA low for ``hold_ns`` while another device is driving it high."""
    vip._pull_sda(True)
    await Timer(hold_ns, unit="ns")
    vip._pull_sda(False)


async def release_bus(vip: SmcI2cMasterVip) -> None:
    """Return the pads to idle after an interrupted transaction."""
    vip._pull_sda(False)
    vip._pull_scl(False)
    await Timer(vip._bit_ns, unit="ns")
    vip._active = False
