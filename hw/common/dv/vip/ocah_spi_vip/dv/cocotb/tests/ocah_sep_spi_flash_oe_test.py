# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: the SEP flash model and the controller DQ0 enable.

``OcahSepSpiFlash`` drives a response bit only while the controller has
released DQ0 (``dq_oe_n`` bit 0 high). A response byte with a bit slot in
which the controller still drove DQ0 is not sent in full: it is not part of
the record's ``data_out``, the response ends there, and ``contended_bits``
counts the slots.

* CHK-SEP-FLASH-OE-FREE: with DQ0 released, a READ of the seeded preload
  returns it to the controller, the record's ``data_out`` equals it and
  ``contended_bits`` stays 0.
* CHK-SEP-FLASH-OE-CONTEND: with DQ0 driven by the controller through the
  response, the record's ``data_out`` is empty and ``contended_bits`` is 8
  (the first response byte). A model that records the byte as sent fails.
* CHK-SEP-FLASH-OE-RECOVER: a READ with DQ0 released after that returns the
  preload again.
* CHK-SEP-FLASH-OE-PARTIAL: a READ frame that ends inside the first response
  byte, with DQ0 driven by the controller, adds one to ``contended_bits`` for
  each response bit slot the model saw (each SCK falling edge after the last
  address bit, counted by the test), and leaves ``data_out`` empty.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Edge, First, RisingEdge, Timer
from ocah_spi_vip import OcahSepSpiFlash, OcahSpiMasterBfm
from ocah_spi_vip_harness import CLK_PERIOD_NS, HALF_PERIOD_NS, JEDEC_ID, PREFIX, scenario_rng

log = logging.getLogger("cocotb.tb.ocah_sep_spi_flash_oe_test")

DQ_RELEASED = 0xFF
DQ0_DRIVEN = 0xFE
READ = 0x03


async def _read(flash: OcahSepSpiFlash, bfm: OcahSpiMasterBfm, n: int) -> tuple[bytes, dict]:
    """READ ``n`` bytes at 0; return the controller's bytes and the new flash record."""
    before = len(flash.get_transactions())
    got = await bfm.read(0, n)
    await Timer(4 * HALF_PERIOD_NS, "ns")
    records = flash.get_transactions()
    if len(records) != before + 1:
        raise AssertionError(f"expected one new flash record, got {len(records) - before}")
    rec = records[-1]
    if rec["opcode"] != READ:
        raise AssertionError(f"flash record opcode=0x{rec['opcode']:02x}, expected 0x{READ:02x}")
    return bytes(got), rec


@cocotb.test()
async def ocah_sep_spi_flash_oe_test(dut) -> None:
    rng = scenario_rng("sep_flash_oe")
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())
    dut.spi_dq_oe_n.value = DQ_RELEASED
    preload = bytes(rng.randint(0, 255) for _ in range(rng.randint(4, 8)))
    flash = OcahSepSpiFlash(
        dut.spi_cs_n,
        dut.spi_sclk,
        dq_out=dut.spi_mosi,
        dq_in=dut.spi_miso,
        dq_oe_n=dut.spi_dq_oe_n,
        name="sep_oe_flash",
        mode="single",
        jedec_id=JEDEC_ID,
    )
    flash.preload(preload)
    flash.init_signals()
    bfm = OcahSpiMasterBfm.from_prefix(
        dut, PREFIX, name="sep_oe_host", half_period_ns=HALF_PERIOD_NS
    )
    bfm.init_signals()
    await flash.start()
    await Timer(HALF_PERIOD_NS, "ns")
    n = len(preload)

    got, rec = await _read(flash, bfm, n)
    line = (
        f"bytes={n} preload={preload.hex()} host={got.hex()} "
        f"data_out={bytes(rec['data_out']).hex()} contended_bits={flash.contended_bits}"
    )
    if got != preload or bytes(rec["data_out"]) != preload or flash.contended_bits:
        raise AssertionError(f"CHK-SEP-FLASH-OE-FREE FAIL {line}")
    log.info("CHK-SEP-FLASH-OE-FREE PASS %s", line)

    dut.spi_dq_oe_n.value = DQ0_DRIVEN
    got, rec = await _read(flash, bfm, n)
    dut.spi_dq_oe_n.value = DQ_RELEASED
    line = (
        f"bytes={n} data_out={bytes(rec['data_out']).hex() or '-'} "
        f"contended_bits={flash.contended_bits} expect_contended_bits=8"
    )
    if bytes(rec["data_out"]) or flash.contended_bits != 8:
        raise AssertionError(f"CHK-SEP-FLASH-OE-CONTEND FAIL {line}")
    log.info("CHK-SEP-FLASH-OE-CONTEND PASS %s", line)

    got, rec = await _read(flash, bfm, n)
    line = f"bytes={n} host={got.hex()} data_out={bytes(rec['data_out']).hex()}"
    if got != preload or bytes(rec["data_out"]) != preload or flash.contended_bits != 8:
        raise AssertionError(f"CHK-SEP-FLASH-OE-RECOVER FAIL {line}")
    log.info("CHK-SEP-FLASH-OE-RECOVER PASS %s", line)
    # A frame that ends inside the first response byte, DQ0 driven.
    k = rng.randint(1, 7)
    bits = [(READ >> (7 - i)) & 1 for i in range(8)] + [0] * 24 + [0] * k
    slots = {"rises": 0, "falls_after_addr": 0}

    async def count_slots() -> None:
        while True:
            await First(Edge(dut.spi_sclk), RisingEdge(dut.spi_cs_n))
            if int(dut.spi_cs_n.value):
                return
            if int(dut.spi_sclk.value):
                slots["rises"] += 1
            elif slots["rises"] >= 32:
                slots["falls_after_addr"] += 1

    before = flash.contended_bits
    n_rec = len(flash.get_transactions())
    dut.spi_dq_oe_n.value = DQ0_DRIVEN
    counter = cocotb.start_soon(count_slots())
    await bfm.raw_frame(bits)
    await counter
    dut.spi_dq_oe_n.value = DQ_RELEASED
    await Timer(4 * HALF_PERIOD_NS, "ns")
    records = flash.get_transactions()
    added = flash.contended_bits - before
    data_out = bytes(records[-1]["data_out"]) if len(records) > n_rec else b""
    line = (
        f"response_clocks={k} slots_seen={slots['falls_after_addr']} "
        f"contended_added={added} records_added={len(records) - n_rec} "
        f"data_out={data_out.hex() or '-'}"
    )
    if slots["falls_after_addr"] < 1 or added != slots["falls_after_addr"] or data_out:
        raise AssertionError(f"CHK-SEP-FLASH-OE-PARTIAL FAIL {line}")
    log.info("CHK-SEP-FLASH-OE-PARTIAL PASS %s", line)
    await flash.stop(require_closed=True)
