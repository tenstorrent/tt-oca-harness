# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
example_jedec_id.py — OcahSpiFlash JEDEC-ID read snippet.

Demonstrates:
  1. Instantiating OcahSpiFlash in single-SPI mode.
  2. Hooking a passive OcahSpiMonitor alongside the flash BFM.
  3. Driving the SPI controller to issue READ JEDEC ID (0x9F).
  4. Verifying the returned ID against the configured value.

This is not a stand-alone simulation test; it shows the API patterns that a
real DUT-level cocotb test would follow.  Replace the signal handles
(``dut.spi_cs_n``, etc.) with the actual signal paths in your testbench.

Assumptions
-----------
- The DUT is an SPI controller that drives CS_N, SCK, and MOSI.
- CS_N and SCK are driven by the DUT; this snippet mimics that with direct
  signal assignments for illustration purposes.
- All signal names follow the generic single-SPI convention.  For SEP xSPI
  tests, use OcahSepSpiFlash and the ``spi_*_o / spi_*_i`` port names.
"""

import cocotb
from cocotb.triggers import Timer

from ocah_spi_vip import OcahSpiFlash, OcahSpiMonitor

# ---------------------------------------------------------------------------
# Testbench-level clock helper
# ---------------------------------------------------------------------------

_SPI_PERIOD_NS = 20  # 50 MHz SPI clock


async def _spi_clk_cycle(clk_sig):
    """Drive one complete SPI clock cycle (low then high)."""
    clk_sig.value = 1
    await Timer(_SPI_PERIOD_NS // 2, units="ns")
    clk_sig.value = 0
    await Timer(_SPI_PERIOD_NS // 2, units="ns")


# ---------------------------------------------------------------------------
# Low-level SPI master helpers (stand-in for real DUT SPI controller)
# ---------------------------------------------------------------------------


async def _spi_transfer_byte(clk_sig, mosi_sig, miso_sig, byte_val: int) -> int:
    """Transfer one byte MSB-first over SPI Mode 0; return received byte."""
    rx = 0
    for bit_idx in range(7, -1, -1):
        # Setup MOSI before rising edge.
        mosi_sig.value = (byte_val >> bit_idx) & 0x1
        await Timer(2, units="ns")  # setup time
        clk_sig.value = 1
        await Timer(_SPI_PERIOD_NS // 2, units="ns")
        # Sample MISO on rising edge.
        rx = (rx << 1) | (int(miso_sig.value) & 0x1)
        clk_sig.value = 0
        await Timer(_SPI_PERIOD_NS // 2, units="ns")
    return rx


# ---------------------------------------------------------------------------
# Example test
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_jedec_id(dut):
    """
    Issue READ JEDEC ID (0x9F) and verify the 3-byte response.

    Signal mapping assumed from testbench:
        dut.spi_cs_n  — active-low chip-select (test drives this)
        dut.spi_sclk  — serial clock           (test drives this)
        dut.spi_mosi  — data to flash           (test drives this)
        dut.spi_miso  — data from flash         (flash drives this)

    The flash BFM responds as the slave device.
    """

    # -----------------------------------------------------------------
    # Step 1: configure and start the flash BFM
    # -----------------------------------------------------------------
    TARGET_JEDEC_ID = 0xEF4018  # 24-bit generic NOR JEDEC ID (no brand)

    flash = OcahSpiFlash(
        cs_n=dut.spi_cs_n,
        sclk=dut.spi_sclk,
        mosi=dut.spi_mosi,
        miso=dut.spi_miso,
        name="flash0",
        mode="single",
        jedec_id=TARGET_JEDEC_ID,
    )

    flash.init_signals()

    # -----------------------------------------------------------------
    # Step 2: attach a passive monitor
    # -----------------------------------------------------------------
    observed_txns = []

    def on_transaction(txn):
        observed_txns.append(txn)
        cocotb.log.info(
            "[monitor] opcode=0x%02X addr=0x%06X miso=%s",
            txn["opcode"],
            txn["addr"],
            txn["data_miso"].hex(),
        )

    monitor = OcahSpiMonitor(
        cs_n=dut.spi_cs_n,
        sclk=dut.spi_sclk,
        mosi=dut.spi_mosi,
        miso=dut.spi_miso,
        name="spi_mon",
    )
    monitor.add_transaction_callback(on_transaction)
    await monitor.start()

    # -----------------------------------------------------------------
    # Step 3: start the flash BFM
    # -----------------------------------------------------------------
    await flash.start()

    # -----------------------------------------------------------------
    # Step 4: drive the SPI controller to assert CS and send 0x9F
    # -----------------------------------------------------------------
    # Drive initial idle state.
    dut.spi_cs_n.value = 1
    dut.spi_sclk.value = 0
    dut.spi_mosi.value = 0
    await Timer(100, units="ns")

    # Assert CS_N (active low).
    dut.spi_cs_n.value = 0
    await Timer(10, units="ns")

    # Send READ JEDEC ID command byte 0x9F.
    await _spi_transfer_byte(dut.spi_sclk, dut.spi_mosi, dut.spi_miso, 0x9F)

    # Receive 3 response bytes (manufacturer, memory type, capacity).
    b1 = await _spi_transfer_byte(dut.spi_sclk, dut.spi_mosi, dut.spi_miso, 0x00)
    b2 = await _spi_transfer_byte(dut.spi_sclk, dut.spi_mosi, dut.spi_miso, 0x00)
    b3 = await _spi_transfer_byte(dut.spi_sclk, dut.spi_mosi, dut.spi_miso, 0x00)

    # Deassert CS_N.
    dut.spi_cs_n.value = 1
    await Timer(50, units="ns")  # let monitor dispatch

    # -----------------------------------------------------------------
    # Step 5: verify
    # -----------------------------------------------------------------
    received_id = (b1 << 16) | (b2 << 8) | b3

    assert received_id == TARGET_JEDEC_ID, (
        f"JEDEC ID mismatch: expected 0x{TARGET_JEDEC_ID:06X}, got 0x{received_id:06X}"
    )

    # Verify the monitor captured one transaction with opcode 0x9F.
    assert len(observed_txns) >= 1, "Monitor did not capture any transaction"
    assert observed_txns[-1]["opcode"] == 0x9F, (
        f"Monitor saw wrong opcode: 0x{observed_txns[-1]['opcode']:02X}"
    )

    # -----------------------------------------------------------------
    # Step 6: tear down
    # -----------------------------------------------------------------
    await monitor.stop()
    await flash.stop()

    stats = monitor.get_statistics()
    cocotb.log.info("Monitor stats: %s", stats)
    cocotb.log.info("example_jedec_id PASSED — JEDEC=0x%06X", received_id)
