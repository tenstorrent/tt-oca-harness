# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BH-SMC bench hook: the SMC aperture inputs and the SMC responder.

The hook is a top-port drive (docs/SEP_TB_ARCH.adoc, HDL Top port table): tb_top
drives ``smc_global_base_addr_i`` and ``smc_region_size_i`` of the DUT and
enables a responder on ``sep_ext_to_smc_axi`` (tb/sep_smc_route_mem.sv). It
exists in every build without ``SEP_SMC_MEM_MODEL``.

Two ways to set it, both before reset release:

* a leaf calls :func:`drive_bh_smc` with the values it drew from its seed;
* a run passes ``+sep_smc_aperture_base=<hex>`` and
  ``+sep_smc_aperture_size=<hex>``.

The port drive wins over the plusargs. With neither, both inputs are 0 and the
responder stays idle.

The responder stores written bytes and returns them. A word that no write has
touched reads ``{~a, a}``, where ``a`` is the low 32 bits of the 8-byte-aligned
address (:func:`smc_unwritten_word`).
"""

from __future__ import annotations

import cocotb

ADDR_MASK = (1 << 56) - 1


def drive_bh_smc(base: int, size: int, dut=None) -> None:
    """Enable BH-SMC with one aperture. Call before reset release."""
    dut = dut if dut is not None else cocotb.top
    dut.bh_smc_base_i.value = base & ADDR_MASK
    dut.bh_smc_size_i.value = size & ADDR_MASK
    dut.bh_smc_en_i.value = 1


def release_bh_smc(dut=None) -> None:
    """Leave the hook to the plusargs or to its idle state."""
    dut = dut if dut is not None else cocotb.top
    dut.bh_smc_en_i.value = 0
    dut.bh_smc_base_i.value = 0
    dut.bh_smc_size_i.value = 0


def smc_unwritten_word(addr: int) -> int:
    """The 64-bit word the responder returns for an address no write touched."""
    a = addr & 0xFFFF_FFF8
    return ((~a & 0xFFFF_FFFF) << 32) | a
