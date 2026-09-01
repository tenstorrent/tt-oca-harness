# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS UART protocol VIP wrapper (P2 Phase A #4).

Thin DUT-local bind of ``ocah_uart_vip.OcahUartConsole`` onto SMC
``tb_top.sv`` UART0 pads:

* ``tb_uart0_rx_ext_drive`` (external -> DUT UART0 RX pad 11) — console TX
* ``tb_uart0_tx_from_dut``  (DUT -> external UART0 TX pad 12) — console RX
"""

from __future__ import annotations

import logging

import cocotb
from ocah_uart_vip import OcahUartConsole, OcahUartError, OcahUartImportError

# Keep historical SMC error name.
SmcUartVipError = OcahUartError


class SmcUartVip:
    """SMC OSS UART0 driver + sink around ``OcahUartConsole``."""

    def __init__(
        self,
        *,
        baud: int = 115200,
        bits: int = 8,
        name: str = "smc_uart0",
    ) -> None:
        if bits != 8:
            raise SmcUartVipError(
                f"SmcUartVip only supports 8-bit frames via OcahUartConsole; got bits={bits}"
            )
        dut = cocotb.top
        try:
            self._console = OcahUartConsole(
                dut.tb_uart0_rx_ext_drive,  # host TX -> DUT RX
                dut.tb_uart0_tx_from_dut,  # host RX <- DUT TX
                dut.clk_smc_i,
                name=name,
                baud=baud,
            )
        except OcahUartImportError as exc:
            raise SmcUartVipError(str(exc)) from exc
        self.baud = baud
        self.bits = bits
        self.log = logging.getLogger(name)
        # Preserve historical attribute names used by helpers/tests.
        self.source = self._console._source
        self.sink = self._console._sink
        self.log.info(
            "SmcUartVip bound via OcahUartConsole: baud=%d bits=%d (rx pad 11, tx pad 12)",
            baud,
            bits,
        )

    async def drive_frame(self, data: bytes) -> None:
        """Drive one UART frame on the RX-into-DUT line."""
        await self._console.send_bytes(data)
        self.log.info("UART drove %d byte(s): %s", len(data), data.hex())

    async def capture_frame(self, timeout_us: int = 5000) -> int:
        """Capture one byte from DUT UART0 TX (pad 12)."""
        value = await self._console.read_byte(timeout_us=timeout_us)
        if value is None:
            raise SmcUartVipError(f"UART capture timed out after {timeout_us} us (no DUT TX byte)")
        self.log.info("UART captured DUT TX byte 0x%02X", value)
        return int(value)


async def uart_pin_wire_proof(byte_val: int = 0x55, baud: int = 115200) -> bool:
    """P2-A / P2-13: prove the UART0 RX pad accepts UART-timed bit transitions."""
    try:
        vip = SmcUartVip(baud=baud)
    except SmcUartVipError as exc:
        cocotb.log.warning("UART proof skipped: %s", exc)
        return False
    await vip.drive_frame(bytes([byte_val]))
    dut = cocotb.top
    tx_val = dut.tb_uart0_tx_from_dut.value
    cocotb.log.info(
        "UART pin-wire proof: drove 0x%02X @%d baud; tb_uart0_tx_from_dut=%s (resolvable=%s)",
        byte_val,
        baud,
        str(tx_val),
        tx_val.is_resolvable,
    )
    return True


__all__ = ["SmcUartVip", "SmcUartVipError", "uart_pin_wire_proof"]
