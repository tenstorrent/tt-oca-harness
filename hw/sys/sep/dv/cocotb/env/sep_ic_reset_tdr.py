# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""IC_RESET TDR driver for the SEP slice instantiated in ``tb_top``.

``tb_top`` holds the real ``jtag_ic_reset_reg`` sized for the SEP slice and
routes its outputs to the DUT reset-control port while
``jtag_ic_reset_tdr_en_i`` is 1. The TAP that selects this TDR is outside
this DUT, so the driver presents the scan-control pins directly: Capture-DR,
a shift of every bit LSB first, then Update-DR.

Sources, both DV-owned transcriptions of the spec:

* Port order: ``doc/integrator/src/smu.adoc``, SEP slice (TDI to TDO). The
  first name is nearest TDI, so the last name is port 0.
* Field layout: ``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``, IC_RESET
  field table. Bit 0 is ``reset_hold``. Port ``n`` stores ``reset_enable`` at
  ``2*n+1`` and ``reset_control`` at ``2*n+2``. ``reset_enable`` is active
  low: 0 applies the override, and ``reset_control`` is then the active-low
  reset value.

Pin writes use ``Immediate`` so that each value is on the pin before the TCK
edge that samples it, on both simulators.
"""

from __future__ import annotations

from typing import Callable

import cocotb
from cocotb.handle import Immediate
from cocotb.triggers import ReadWrite, Timer

SEP_SLICE_TDI_TO_TDO: tuple[str, ...] = (
    "abr_jtag_rst_n",
    "trng_jtag_rst_n",
    "sep_reset_n",
    "kmac_jtag_rst_n",
    "hmac_jtag_rst_n",
    "aes_jtag_rst_n",
    "otbn_jtag_rst_n",
    "km_jtag_rst_n",
)
IC_RESET_PORTS = len(SEP_SLICE_TDI_TO_TDO)
IC_RESET_BITS = (2 * IC_RESET_PORTS) + 1
IC_RESET_IDLE = (1 << IC_RESET_BITS) - 1
TCK_HALF_NS = 5


def port_index(name: str) -> int:
    """Port number of a SEP-slice reset. Port 0 is nearest TDO."""
    return IC_RESET_PORTS - 1 - SEP_SLICE_TDI_TO_TDO.index(name)


def tdr_word(*, apply: tuple[str, ...] = (), hold: tuple[str, ...] = ()) -> int:
    """TDR word from the idle value (every bit 1).

    ``apply`` clears ``reset_enable`` of each named port, so JTAG drives that
    reset. ``hold`` clears ``reset_control`` of each named port, so the
    driven value is "in reset". A port in ``hold`` but not in ``apply`` is
    staged: its value is loaded, and the override is not yet on.
    """
    value = IC_RESET_IDLE
    for name in apply:
        value &= ~(1 << (2 * port_index(name) + 1))
    for name in hold:
        value &= ~(1 << (2 * port_index(name) + 2))
    return value


class SepIcResetTdr:
    """Drives the tb_top IC_RESET TDR pins."""

    def __init__(self, read_known: Callable[..., int]) -> None:
        self.dut = cocotb.top
        self._rd = read_known

    def _set(self, name: str, value: int) -> None:
        getattr(self.dut, name).value = Immediate(value)

    async def _tck(self) -> None:
        self._set("jtag_ic_reset_tck_i", 0)
        await Timer(TCK_HALF_NS, unit="ns")
        self._set("jtag_ic_reset_tck_i", 1)
        await Timer(TCK_HALF_NS, unit="ns")
        self._set("jtag_ic_reset_tck_i", 0)

    async def reset_and_select(self) -> None:
        """TRST the register to its idle value, then route it to the DUT."""
        for name in (
            "jtag_ic_reset_tdr_en_i",
            "jtag_ic_reset_select_i",
            "jtag_ic_reset_shift_en_i",
            "jtag_ic_reset_capture_en_i",
            "jtag_ic_reset_update_en_i",
            "jtag_ic_reset_rst_n_i",
            "jtag_ic_reset_trst_n_i",
        ):
            self._set(name, 0)
        await Timer(20, unit="ns")
        self._set("jtag_ic_reset_rst_n_i", 1)
        self._set("jtag_ic_reset_trst_n_i", 1)
        await Timer(5, unit="ns")
        self._set("jtag_ic_reset_tdr_en_i", 1)
        await ReadWrite()

    async def capture_shift_update(self, value: int) -> int:
        """Capture-DR, shift ``value`` LSB first, Update-DR. Returns the captured word."""
        self._set("jtag_ic_reset_select_i", 1)
        self._set("jtag_ic_reset_capture_en_i", 1)
        self._set("jtag_ic_reset_shift_en_i", 0)
        self._set("jtag_ic_reset_update_en_i", 0)
        await self._tck()
        self._set("jtag_ic_reset_capture_en_i", 0)
        self._set("jtag_ic_reset_shift_en_i", 1)
        captured = 0
        for bit in range(IC_RESET_BITS):
            captured |= self._rd(self.dut.jtag_ic_reset_tdo_o) << bit
            self._set("jtag_ic_reset_tdi_i", (value >> bit) & 1)
            await self._tck()
        self._set("jtag_ic_reset_shift_en_i", 0)
        self._set("jtag_ic_reset_tdi_i", 0)
        self._set("jtag_ic_reset_update_en_i", 1)
        await self._tck()
        self._set("jtag_ic_reset_update_en_i", 0)
        self._set("jtag_ic_reset_select_i", 0)
        await ReadWrite()
        return captured
