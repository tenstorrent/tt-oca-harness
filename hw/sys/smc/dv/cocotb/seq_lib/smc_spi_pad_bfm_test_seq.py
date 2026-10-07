# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U2-2: TB SPI host + OcahSepSpiFlash on lifted SMC SPI pads.

Architecture (smc_wrapper has no internal SPI host IP on this surface):
  * cocotb acts as the external SPI host driving ``tb_spi_*`` (controller
    inputs into smc padring mux).
  * ``OcahSepSpiFlash`` is the flash BFM; its MISO/DQ response is fed back
    through ``tb_spi_miso_ext`` -> ``tb_pad2core[0]`` -> ``tb_spi_rxd[0]``.

This proves the pad-lift + BFM bind path, not a DUT SPI-IP JEDEC proof.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_base_test_seq import smc_base_test_seq

try:
    from ocah_spi_vip import OcahSepSpiFlash

    _SPI_VIP_AVAILABLE = True
except Exception:  # noqa: BLE001
    OcahSepSpiFlash = None  # type: ignore[assignment]
    _SPI_VIP_AVAILABLE = False

SPI_JEDEC_ID = 0x20BA18
SPI_HALF_PERIOD_NS = 20


async def _host_write_byte(dut, value: int) -> None:
    """Shift out one byte MSB-first on DQ0 (mode 0: sample on rising).

    Leaves SCLK high after the last sampled bit so the subsequent host
    read can present a clean FallingEdge for the flash response phase.
    """
    for bit in range(7, -1, -1):
        dut.tb_spi_txd.value = (value >> bit) & 0x1
        dut.tb_spi_clk.value = 0
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")
        dut.tb_spi_clk.value = 1
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")


async def _host_read_byte(dut) -> int:
    """Shift in one byte MSB-first from tb_spi_rxd[0] (flash MISO)."""
    value = 0
    dut.tb_spi_txd.value = 0
    for _ in range(8):
        dut.tb_spi_clk.value = 0
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")
        dut.tb_spi_clk.value = 1
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")
        bit = int(dut.tb_spi_rxd.value) & 0x1
        value = (value << 1) | bit
    return value


class smc_spi_pad_bfm_test_seq(smc_base_test_seq):
    """Drive JEDEC 0x9F + READ preload through pad-lifted SPI flash BFM."""

    def __init__(self, name: str = "smc_spi_pad_bfm_test_seq") -> None:
        super().__init__(name)
        self.expected_bytes: bytes = bytes(
            [(SPI_JEDEC_ID >> 16) & 0xFF, (SPI_JEDEC_ID >> 8) & 0xFF, SPI_JEDEC_ID & 0xFF]
        )
        self.observed_bytes: bytes = b""
        self.preload_ok: bool = False

    async def body(self) -> None:
        assert _SPI_VIP_AVAILABLE, "ocah_spi_vip / OcahSepSpiFlash unavailable on PYTHONPATH"
        dut = cocotb.top
        assert hasattr(dut, "tb_spi_enable"), "tb_spi_* pads not lifted"
        assert hasattr(dut, "tb_spi_miso_ext"), "tb_spi_miso_ext not present"

        flash = OcahSepSpiFlash(
            cs_n=dut.tb_spi_cs_n,
            sclk=dut.tb_spi_clk,
            dq_out=dut.tb_spi_txd,
            dq_in=dut.tb_spi_miso_ext,
            dq_oe_n=dut.tb_spi_dq_oe_n,
            name="smc_spi_pad_flash",
            mode="single",
            jedec_id=SPI_JEDEC_ID,
        )
        # In-process preload, the same path +spi_flash_preload takes.
        _PRELOAD = bytes([0xDE, 0xAD, 0xBE, 0xEF])
        flash.preload(_PRELOAD)
        flash.init_signals()
        await flash.start()

        # Enable SPI mux into padring; host drives CS/CLK/DQ0.
        dut.tb_spi_enable.value = 1
        dut.tb_spi_cs_n.value = 1
        dut.tb_spi_clk.value = 0
        dut.tb_spi_txd.value = 0
        dut.tb_spi_cs_oe_n.value = 0
        dut.tb_spi_clk_oe_n.value = 0
        dut.tb_spi_dq_oe_n.value = 0xFE  # drive DQ0 only
        dut.tb_spi_dq_ie_n.value = 0xFE  # input-enable DQ0 for MISO path
        dut.tb_spi_cs_ie_n.value = 1
        dut.tb_spi_clk_ie_n.value = 1
        await Timer(100, unit="ns")

        dut.tb_spi_cs_n.value = 0
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")
        await _host_write_byte(dut, 0x9F)

        # Bus turnaround: release DQ0 OE before the flash response clocks.
        dut.tb_spi_dq_oe_n.value = 0xFF
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")

        b0 = await _host_read_byte(dut)
        b1 = await _host_read_byte(dut)
        b2 = await _host_read_byte(dut)
        dut.tb_spi_cs_n.value = 1
        dut.tb_spi_clk.value = 0
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")

        jedec = (b0 << 16) | (b1 << 8) | b2
        assert jedec == SPI_JEDEC_ID, (
            f"SPI pad BFM JEDEC mismatch: got 0x{jedec:06X}, expected 0x{SPI_JEDEC_ID:06X}"
        )
        self.observed_bytes = bytes([b0, b1, b2])

        # READ 0x03 @0 returns the preload, the same path +spi_flash_preload takes.
        dut.tb_spi_dq_oe_n.value = 0xFE
        dut.tb_spi_cs_n.value = 0
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")
        await _host_write_byte(dut, 0x03)
        await _host_write_byte(dut, 0x00)  # addr[23:16]
        await _host_write_byte(dut, 0x00)  # addr[15:8]
        await _host_write_byte(dut, 0x00)  # addr[7:0]
        dut.tb_spi_dq_oe_n.value = 0xFF
        await Timer(SPI_HALF_PERIOD_NS, unit="ns")
        rd = bytearray()
        for _ in range(len(_PRELOAD)):
            rd.append(await _host_read_byte(dut))
        dut.tb_spi_cs_n.value = 1
        dut.tb_spi_clk.value = 0
        assert bytes(rd) == _PRELOAD, (
            f"SPI pad BFM READ preload mismatch: got {bytes(rd).hex()}, expected {_PRELOAD.hex()}"
        )
        self.preload_ok = True
        cocotb.log.info(
            "CHK-SPI-PAD-JEDEC-PRELOAD: JEDEC 0x9F over the tb_spi_* host returned "
            "0x%06X (expected 0x%06X) and READ 0x03 @0 returned %s matching the "
            "%d-byte preload, both through tb_spi_miso_ext -> pad2core[0] -> spi_rxd[0]",
            jedec,
            SPI_JEDEC_ID,
            bytes(rd).hex(),
            len(_PRELOAD),
        )

        await flash.stop()
        dut.tb_spi_enable.value = 0
        dut.tb_spi_cs_n.value = 1
        dut.tb_spi_dq_oe_n.value = 0xFF
        dut.tb_spi_dq_ie_n.value = 0xFF
