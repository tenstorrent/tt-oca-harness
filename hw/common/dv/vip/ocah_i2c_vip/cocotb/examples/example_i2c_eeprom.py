# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
example_i2c_eeprom.py — OcahI2cMaster / OcahI2cMemory usage examples.

Demonstrates:
  1. Master write + combined read (register-addressed EEPROM access).
  2. OcahI2cMemory preload and dump.
  3. OcahI2cDevice with a custom handler callback.
  4. OcahI2cMonitor passive observation.

These are NOT stand-alone cocotb tests; they show the API patterns a real
OCAH test would follow.  Replace ``dut.i2c_scl`` / ``dut.i2c_sda`` with the
actual signal handles in your testbench.

Assumptions
-----------
- ``cocotbext-i2c == 0.1.2`` is installed.
- The DUT exposes I2C master pins (SCL, SDA) that are wired to device
  emulators.  In a loopback configuration the device side is driven by the
  cocotb environment, not by RTL.
- 100 kHz (Standard mode) is used throughout; change ``speed=400_000`` for
  Fast mode.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

from ocah_i2c_vip import (
    OcahI2cMaster,
    OcahI2cDevice,
    OcahI2cMemory,
    OcahI2cMonitor,
)


# ---------------------------------------------------------------------------
# Example 1 — EEPROM write then register-addressed read via OcahI2cMemory
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_i2c_eeprom_write_read(dut):
    """Write bytes to an emulated EEPROM, then read them back."""

    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    # Device side: emulate an AT24C02-compatible EEPROM at address 0x50.
    eeprom = OcahI2cMemory(
        dut.i2c_scl,
        dut.i2c_sda,
        dut.clk,
        name="eeprom_0x50",
        addr=0x50,
        mem_size=256,
        addr_bytes=1,
        speed=100_000,
    )
    await eeprom.start()

    # Master side: drives the DUT's I2C master interface.
    master = OcahI2cMaster(
        dut.i2c_scl,
        dut.i2c_sda,
        dut.clk,
        name="i2c_master",
        speed=100_000,
    )
    master.init_signals()
    master.set_address(0x50)

    await Timer(200, units="ns")   # allow DUT to come out of reset

    # ---------- write three bytes at EEPROM offset 0x10 ----------
    # Protocol: first byte is the register address; remaining bytes are data.
    await master.write(0x50, bytes([0x10, 0xAA, 0xBB, 0xCC]))
    cocotb.log.info("Wrote [0xAA, 0xBB, 0xCC] at EEPROM offset 0x10")

    # ---------- combined read: set address pointer then read back ----------
    data = await master.combined(
        addr=0x50,
        write_data=bytes([0x10]),    # address pointer
        read_length=3,
    )
    assert data == bytes([0xAA, 0xBB, 0xCC]), (
        f"EEPROM read mismatch: got {data.hex()}"
    )
    cocotb.log.info("Read back from EEPROM: %s", data.hex())

    # ---------- direct memory dump ----------
    snapshot = eeprom.dump()
    assert snapshot[0x10] == 0xAA
    assert snapshot[0x11] == 0xBB
    assert snapshot[0x12] == 0xCC

    stats = master.get_statistics()
    cocotb.log.info("Master stats: %s", stats)

    await eeprom.stop()
    cocotb.log.info("example_i2c_eeprom_write_read PASSED")


# ---------------------------------------------------------------------------
# Example 2 — Preload EEPROM from a file or bytes blob
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_i2c_eeprom_preload(dut):
    """Preload EEPROM contents and verify via I2C read."""

    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    eeprom = OcahI2cMemory(
        dut.i2c_scl, dut.i2c_sda, dut.clk,
        name="eeprom_preload", addr=0x52, mem_size=256, addr_bytes=1,
    )

    # Preload from a bytes blob.
    preload_data = bytes(range(256))
    eeprom.preload(preload_data)

    # Alternatively, preload from a binary file:
    #   eeprom.preload("/tmp/eeprom_init.bin")

    await eeprom.start()

    master = OcahI2cMaster(
        dut.i2c_scl, dut.i2c_sda, dut.clk, name="master2", speed=100_000
    )
    master.init_signals()

    await Timer(100, units="ns")

    # Read the first 8 bytes.
    data = await master.combined(
        addr=0x52,
        write_data=bytes([0x00]),   # address 0
        read_length=8,
    )
    expected = bytes(range(8))
    assert data == expected, f"preload readback mismatch: {data.hex()} != {expected.hex()}"
    cocotb.log.info("Preload readback OK: %s", data.hex())

    await eeprom.stop()
    cocotb.log.info("example_i2c_eeprom_preload PASSED")


# ---------------------------------------------------------------------------
# Example 3 — OcahI2cDevice with a custom handler callback
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_i2c_custom_device(dut):
    """Use OcahI2cDevice with a handler that implements a simple register map."""

    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    # Simple register map: address 0x00 returns 0xDE, address 0x01 returns 0xAD.
    REGS = {0x00: 0xDE, 0x01: 0xAD}
    current_reg = [0]

    def my_handler(addr, rw, data):
        if rw == "write" and data:
            current_reg[0] = data[0]
            cocotb.log.info("[device] reg pointer set to 0x%02X", current_reg[0])
            return None
        if rw == "read":
            val = REGS.get(current_reg[0], 0xFF)
            cocotb.log.info("[device] read reg 0x%02X -> 0x%02X", current_reg[0], val)
            return bytes([val])
        return None

    device = OcahI2cDevice(
        dut.i2c_scl, dut.i2c_sda, dut.clk,
        name="custom_dev", addr=0x55, speed=100_000,
    )
    device.register_handler(my_handler)
    await device.start()

    master = OcahI2cMaster(
        dut.i2c_scl, dut.i2c_sda, dut.clk, name="master3", speed=100_000
    )
    master.init_signals()

    await Timer(100, units="ns")

    # Write register pointer 0x00, then read back.
    data = await master.combined(
        addr=0x55,
        write_data=bytes([0x00]),
        read_length=1,
    )
    assert data == bytes([0xDE]), f"expected 0xDE, got {data.hex()}"

    # Write register pointer 0x01, then read back.
    data = await master.combined(
        addr=0x55,
        write_data=bytes([0x01]),
        read_length=1,
    )
    assert data == bytes([0xAD]), f"expected 0xAD, got {data.hex()}"

    dev_stats = device.get_statistics()
    cocotb.log.info("Device stats: %s", dev_stats)

    await device.stop()
    cocotb.log.info("example_i2c_custom_device PASSED")


# ---------------------------------------------------------------------------
# Example 4 — Passive bus monitoring with OcahI2cMonitor
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_i2c_monitor(dut):
    """Attach a passive monitor while master and device communicate."""

    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    eeprom = OcahI2cMemory(
        dut.i2c_scl, dut.i2c_sda, dut.clk,
        name="eeprom_mon_test", addr=0x50, mem_size=256, addr_bytes=1,
    )
    await eeprom.start()

    master = OcahI2cMaster(
        dut.i2c_scl, dut.i2c_sda, dut.clk, name="master4", speed=100_000
    )
    master.init_signals()

    # Passive monitor — does not drive any signal.
    monitor = OcahI2cMonitor(
        dut.i2c_scl, dut.i2c_sda, dut.clk, name="i2c_mon", speed=100_000
    )

    observed_writes = []
    observed_reads  = []

    monitor.add_write_callback(
        lambda addr, data: observed_writes.append({"addr": addr, "data": data})
    )
    monitor.add_read_callback(
        lambda addr, length, data: observed_reads.append(
            {"addr": addr, "length": length, "data": data}
        )
    )
    await monitor.start()

    await Timer(100, units="ns")

    # Issue one write and one combined read.
    await master.write(0x50, bytes([0x20, 0x11, 0x22]))
    await master.combined(0x50, bytes([0x20]), 2)

    await Timer(1_000, units="ns")   # allow monitor to dispatch
    await monitor.stop()

    mon_stats = monitor.get_statistics()
    cocotb.log.info("Monitor stats: %s", mon_stats)

    transactions = monitor.get_transactions()
    cocotb.log.info("Observed %d transactions", len(transactions))
    assert len(transactions) >= 2, (
        f"expected at least 2 transactions, got {len(transactions)}"
    )

    await eeprom.stop()
    cocotb.log.info("example_i2c_monitor PASSED")
