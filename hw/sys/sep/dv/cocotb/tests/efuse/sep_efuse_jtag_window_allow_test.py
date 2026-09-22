# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG allow leg for the eFuse windows PROD denies.

``sep_efuse_jtag_axil_el2_cpu_mux_test`` senses PROD, where the JTAG port
may reach the MMR token block and must DECERR on the shadow map and on
``EFUSE_PROGRAM_CTRL``. This leaf senses TEST_DEV, which is not a
restricted lifecycle state, and reads those same two windows. OKAY here
and DECERR there is the per-window gate.
"""

from __future__ import annotations

import pyuvm
from env.sep_lcc_golden import LC_TEST_DEV
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_EFUSE_SHADOW_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
_EFUSE_IFACE_PROGRAM = sym("EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_REG_ADDR")
_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_jtag_window_allow_test(sep_base_test):
    """TEST_DEV JTAG reads of shadow and EFUSE_PROGRAM_CTRL return OKAY."""

    async def _allow(self, label: str, addr: int) -> None:
        code, rdata = await self.jtag_axil_op(write=False, addr=addr)
        assert code == 0, (
            f"CHK-JTAG-WINDOW-ALLOW FAIL: JTAG {label} @0x{addr:08x} in "
            f"TEST_DEV must be OKAY; got resp={code} rdata=0x{rdata:08x}"
        )
        self.logger.info(
            "CHK-JTAG-WINDOW-ALLOW PASS: JTAG %s @0x%08x OKAY in TEST_DEV (rdata=0x%08x)",
            label,
            addr,
            rdata,
        )

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(lc_raw=LC_TEST_DEV)
        assert image.lc_raw() == LC_TEST_DEV, (
            f"test bug: image LC_STATE is not TEST_DEV (0x{image.lc_raw():x}); "
            "a restricted image would DECERR these windows"
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self._allow("shadow", _EFUSE_SHADOW_BASE)
        await self._allow("EFUSE_PROGRAM_CTRL", _EFUSE_IFACE_PROGRAM)
