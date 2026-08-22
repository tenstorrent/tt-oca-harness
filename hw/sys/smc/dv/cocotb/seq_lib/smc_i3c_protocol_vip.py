# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I3C protocol VIP wrapper.

Thin DUT-local bind of ``ocah_i3c_vip`` split-port BFMs onto SMC
``tb_top.sv`` I3C0 pads:

* ``tb_i3c0_sda`` / ``tb_i3c0_scl`` — resolved bus outputs (cocotb reads)
* ``tb_i3c0_sda_ext_low`` / ``tb_i3c0_scl_ext_low`` — cocotb drives ``1`` to
  pull low

Public API
----------
SmcI3cSlaveVip(*, static_addr, name)
SmcI3cControllerVip(*, speed, name)
I3C_IMPORT_DIAGNOSTIC — human-readable import status from common VIP
"""

from __future__ import annotations

import cocotb

from ocah_i3c_vip import (
    I3C_IMPORT_DIAGNOSTIC,
    OcahI3cSplitPortController,
    OcahI3cSplitPortError,
    OcahI3cSplitPortTarget,
)

# Keep historical SMC error name for existing sequences.
SmcI3cVipError = OcahI3cSplitPortError


def _i3c0_pads():
    dut = cocotb.top
    return (
        dut.tb_i3c0_sda,
        dut.tb_i3c0_sda_ext_low,
        dut.tb_i3c0_scl,
        dut.tb_i3c0_scl_ext_low,
    )


class SmcI3cSlaveVip(OcahI3cSplitPortTarget):
    """I3C target-mode slave wired to `tb_i3c0_*` split-port signals."""

    def __init__(
        self,
        *,
        static_addr: int = 0x50,
        name: str = "smc_i3c0_slave",
    ) -> None:
        sda_i, sda_o, scl_i, scl_o = _i3c0_pads()
        try:
            super().__init__(
                sda_i,
                sda_o,
                scl_i,
                scl_o,
                address=static_addr,
                name=name,
            )
        except OcahI3cSplitPortError as exc:
            raise SmcI3cVipError(str(exc)) from exc


class SmcI3cControllerVip(OcahI3cSplitPortController):
    """I3C controller wired to `tb_i3c0_*` split-port signals."""

    def __init__(
        self,
        *,
        speed: float = 4e6,
        name: str = "smc_i3c0_ctrl",
    ) -> None:
        sda_i, sda_o, scl_i, scl_o = _i3c0_pads()
        try:
            super().__init__(
                sda_i,
                sda_o,
                scl_i,
                scl_o,
                speed=speed,
                name=name,
            )
        except OcahI3cSplitPortError as exc:
            raise SmcI3cVipError(str(exc)) from exc


__all__ = [
    "I3C_IMPORT_DIAGNOSTIC",
    "SmcI3cSlaveVip",
    "SmcI3cControllerVip",
    "SmcI3cVipError",
]
