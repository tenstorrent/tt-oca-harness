# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
OcahSepSpiFlash — SEP-specific octal-SPI flash BFM.

Binds the SEP octal-SPI pad bundle, one cocotb handle per pad:

    Controller outputs (DUT drives these):
        spi_cs_n_o          — active-low chip-select
        spi_clk_o           — serial clock
        spi_txd_o  [7:0]    — transmit data (DQ out from DUT)
        spi_dq_oe_n_o [7:0] — output-enable for DQ (active-low)
        spi_mem_rebar_opad_o — REBAR output pad

    Flash outputs (this BFM drives these):
        spi_rxd_i  [7:0]    — receive data (DQ in to DUT)
        spi_mem_rebar_ipad_i — REBAR input pad

The REBAR (reset bar) signal is the SEP SPI controller's flash-reset output.
This BFM models it as an active-low async reset: when rebar goes low the
internal memory is NOT wiped (only state machines reset), matching typical
NOR-flash power-on semantics.

DDR support
-----------
DDR (Double Data Rate) octal is out of scope: the class accepts
``mode="octal"`` but operates SDR (single data rate).

Pin naming in tests
-------------------
The pad names above document each pin's role; pass the cocotb handle of
each pin, whatever the DUT or its padring wrapper names it.
"""

from typing import Any, Optional

import cocotb
from cocotb.triggers import FallingEdge, First, RisingEdge

from .ocah_spi_flash import OcahSpiFlash, OcahSpiFlashError, SpiMode, _cancel_task
from .ocah_spi_types import SR1_WEL

__all__ = ["OcahSepSpiFlash", "OcahSepSpiFlashError"]


class OcahSepSpiFlashError(OcahSpiFlashError):
    """Raised when the SEP flash BFM encounters an unrecoverable error."""


class OcahSepSpiFlash(OcahSpiFlash):
    """
    SEP-specific SPI/QSPI/OSPI NOR-flash device BFM.

    Subclasses ``OcahSpiFlash`` and adds:
    - SEP-named pin mapping (``spi_txd_o``, ``spi_rxd_i``, ``spi_dq_oe_n_o``,
      ``spi_mem_rebar_*``).
    - REBAR handling (hardware reset of the flash state machine).
    - Output-enable awareness: MISO / DQ lines are only driven by this BFM
      when ``dq_oe_n`` indicates the DUT has released the bus.

    Parameters
    ----------
    cs_n : cocotb handle
        ``spi_cs_n_o`` — active-low chip-select from controller.
    sclk : cocotb handle
        ``spi_clk_o`` — serial clock from controller.
    dq_out : cocotb handle
        ``spi_txd_o[7:0]`` — DQ bus driven by the controller.  This BFM
        samples bit 0 (DQ0/MOSI) for the command/address phase.
    dq_in : cocotb handle
        ``spi_rxd_i[7:0]`` — DQ bus driven by this BFM (response data back
        to the controller).
    dq_oe_n : cocotb handle, optional
        ``spi_dq_oe_n_o[7:0]`` — Output-enable from controller (active-low).
        When provided, this BFM only drives ``dq_in`` while the corresponding
        OE bit is asserted low by the controller (i.e., the controller is not
        driving DQ).  If not provided, ``dq_in`` is driven unconditionally
        during the data-out phase.
    rebar_o : cocotb handle, optional
        ``spi_mem_rebar_opad_o`` — REBAR output from controller.  When this
        BFM observes a falling edge, it resets internal state (WEL, busy).
    rebar_i : cocotb handle, optional
        ``spi_mem_rebar_ipad_i`` — REBAR input to controller driven by this
        BFM.  Held high (not in reset) during normal operation.
    name : str
        Instance label.
    mode : str
        ``"single"``, ``"quad"``, or ``"octal"``.  Single-bit I/O is used in
        all modes.
    jedec_id : int
        3-byte JEDEC ID.  Default 0x20BA18.
    flash_size : int
        Flash capacity in bytes.  Default 16 MB.
    addr_bytes : int
        Number of address bytes.  Default 3.
    """

    def __init__(
        self,
        cs_n,
        sclk,
        *,
        dq_out,
        dq_in,
        dq_oe_n=None,
        rebar_o=None,
        rebar_i=None,
        name: str = "OcahSepSpiFlash",
        mode: str = "single",
        jedec_id: int = 0x20BA18,
        flash_size: int = 16 * 1024 * 1024,
        addr_bytes: int = 3,
        status_reg1: int = 0x00,
        status_reg2: int = 0x00,
        verbose: bool = False,
    ):
        # The base engine samples bit 0 of its mosi handle and drives bit 0 of
        # its miso handle, so in single mode the DQ buses pass as mosi/miso.
        if SpiMode(mode) == SpiMode.SINGLE:
            super().__init__(
                cs_n=cs_n,
                sclk=sclk,
                mosi=dq_out,
                miso=dq_in,
                name=name,
                mode=mode,
                jedec_id=jedec_id,
                flash_size=flash_size,
                addr_bytes=addr_bytes,
                status_reg1=status_reg1,
                status_reg2=status_reg2,
                verbose=verbose,
            )
        else:
            super().__init__(
                cs_n=cs_n,
                sclk=sclk,
                dq_out=dq_out,
                dq_in=dq_in,
                name=name,
                mode=mode,
                jedec_id=jedec_id,
                flash_size=flash_size,
                addr_bytes=addr_bytes,
                status_reg1=status_reg1,
                status_reg2=status_reg2,
                verbose=verbose,
            )

        self._dq_oe_n = dq_oe_n
        self._rebar_o = rebar_o
        self._rebar_i = rebar_i

        self._rebar_task: Optional[Any] = None

    # ------------------------------------------------------------------
    # Signal initialisation
    # ------------------------------------------------------------------

    def init_signals(self) -> None:
        """Drive all BFM output signals to idle state.

        Drives REBAR input (to controller) high, indicating the flash is not
        held in reset.  MISO / DQ inputs are initialised to 0.
        """
        super().init_signals()
        if self._rebar_i is not None:
            self._rebar_i.value = 1  # not in reset

    # ------------------------------------------------------------------
    # Lifecycle (override to add REBAR monitor)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the SEP flash BFM.

        In addition to the base protocol engine, starts a REBAR monitor task
        if a ``rebar_o`` handle was provided.
        """
        await super().start()
        if self._rebar_o is not None:
            self._rebar_task = cocotb.start_soon(self._rebar_monitor())
            self.log.info("%s: REBAR monitor started", self.name)

    async def stop(self) -> None:
        """Stop the SEP flash BFM."""
        if self._rebar_task is not None:
            _cancel_task(self._rebar_task)
            self._rebar_task = None
        await super().stop()

    # ------------------------------------------------------------------
    # REBAR monitor
    # ------------------------------------------------------------------

    async def _rebar_monitor(self) -> None:
        """Watch rebar_o for falling edges and reset internal state."""
        while self._running:
            await FallingEdge(self._rebar_o)
            if not self._running:
                break
            self.log.info("%s: REBAR asserted — resetting flash state machine", self.name)
            self._on_rebar_assert()

            await RisingEdge(self._rebar_o)
            self.log.info("%s: REBAR deasserted — flash resumed", self.name)
            if self._rebar_i is not None:
                self._rebar_i.value = 1

    def _on_rebar_assert(self) -> None:
        """Reset internal state machine (not flash contents) on REBAR."""
        self._wel = False
        self._sr1 = self._sr1 & ~SR1_WEL
        if self._rebar_i is not None:
            self._rebar_i.value = 0

    # ------------------------------------------------------------------
    # OE-aware drive helper (overrides base for SEP DQ bus)
    # ------------------------------------------------------------------

    async def _send_byte_single(self, byte_val: int) -> bool:
        """Send one byte on DQ, respecting dq_oe_n if provided.

        If ``dq_oe_n`` is connected, this BFM only drives DQ when the
        controller's output-enable is de-asserted for DQ0 (bit 0).
        This prevents bus contention during the turnaround phase.

        If ``dq_oe_n`` is not connected, DQ is driven unconditionally
        (same as base class behaviour).  Returns True when all eight bit
        slots passed, False when chip-select rose first.
        """
        sclk = self._sclk
        cs_n = self._cs_n

        for bit_idx in range(7, -1, -1):
            await First(FallingEdge(sclk), RisingEdge(cs_n))
            if int(cs_n.value) != 0:
                return False

            if self._dq_oe_n is not None:
                oe_val = int(self._dq_oe_n.value)
                # oe_val bit 0 corresponds to DQ0.  Low = controller driving.
                if not (oe_val & 0x1):
                    continue

            bit = (byte_val >> bit_idx) & 0x1
            # Drive DQ0 only; DQ[7:1] are not modified.
            dq_in = self._dq_in if self._dq_in is not None else self._miso
            if dq_in is not None:
                dq_in.value = bit
        return True
