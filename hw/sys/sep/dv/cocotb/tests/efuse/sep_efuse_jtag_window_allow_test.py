# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""At TEST_DEV, JTAG accesses of the eFuse windows that PROD denies return OKAY.

``sep_efuse_jtag_axil_el2_cpu_mux_test`` senses PROD, where the JTAG port
may reach the MMR token block and must be refused (SLVERR or DECERR) on
the shadow map and on ``EFUSE_PROGRAM_CTRL``. This leaf senses TEST_DEV,
which is not a restricted lifecycle state, and reads those same two
windows. OKAY here and a refusal there is the per-window gate.

The leaf also reaches the shim span over JTAG: the controller sends every
address outside the MAP window to the end of the last register window to the
shim's bank control registers. A JTAG read and a JTAG write of the map address
of ``EFUSE_BANK_INIT_TIME`` answer OKAY (CHK-JTAG-SHIM-ALLOW), the positive
control of the PROD and RMA_SIP shim-span deny in
``sep_efuse_jtag_access_rand_test``. No TT text maps a JTAG address to a shim
register offset, so the read data and the read-back after the write are logged
(OBS-JTAG-SHIM-ALLOW-DATA), not graded. The leaf then writes the RDL reset value
back.
"""

from __future__ import annotations

import pyuvm
from env.sep_lcc_golden import LC_TEST_DEV
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sym

_EFUSE_SHADOW_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
_EFUSE_IFACE_PROGRAM = sym("EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_REG_ADDR")
_SHIM = RegBlock("SEP_EXTERNAL_EFUSE_SHIM_CTRL")
_SHIM_REG = "EFUSE_BANK_INIT_TIME"
_SHIM_ADDR = _SHIM.addr(_SHIM_REG)
_SHIM_RESET = _SHIM.reset(_SHIM_REG)
# A value other than the reset value and 0, inside the field.
_SHIM_WDATA = (_SHIM_RESET << 1) & _SHIM.mask_all(_SHIM_REG)
_MAX_SENSE_CYCLES = 20_000
_OKAY = 0


@pyuvm.test()
class sep_efuse_jtag_window_allow_test(sep_base_test):
    """TEST_DEV JTAG reads of shadow and EFUSE_PROGRAM_CTRL, and a JTAG read and write
    of the shim span, return OKAY.

    The LSU scoreboard counts CPU-master transactions. This leaf's
    transactions are on the JTAG AXI-Lite port, so that scoreboard is not
    built. The CHK lines are the verdict.
    """

    build_env = False
    # The TEST_DEV image must be sensed before the windows are read; the shared
    # backdoor compare of the sensed shadow is the proof of that step.
    required_evidence = ("CHK-SENSE-BACKDOOR", "CHK-JTAG-WINDOW-ALLOW", "CHK-JTAG-SHIM-ALLOW")

    async def _allow(self, label: str, addr: int) -> None:
        code, rdata = await self.jtag_axil_op(write=False, addr=addr)
        assert code == _OKAY, (
            f"CHK-JTAG-WINDOW-ALLOW FAIL: JTAG {label} @0x{addr:08x} in "
            f"TEST_DEV must be OKAY; got resp={code} rdata=0x{rdata:08x}"
        )
        self.logger.info(
            "CHK-JTAG-WINDOW-ALLOW PASS: JTAG %s @0x%08x OKAY in TEST_DEV (rdata=0x%08x)",
            label,
            addr,
            rdata,
        )

    async def _shim_allow(self) -> None:
        """CHK-JTAG-SHIM-ALLOW: the JTAG read and the JTAG write of ``_SHIM_ADDR`` answer
        OKAY. OBS-JTAG-SHIM-ALLOW-DATA logs the read data, the read-back after the write
        and the response codes of the read-back and of the restore write."""
        rd_code, rdata = await self.jtag_axil_op(write=False, addr=_SHIM_ADDR)
        wr_code, _ = await self.jtag_axil_op(write=True, addr=_SHIM_ADDR, wdata=_SHIM_WDATA)
        back_code, back = await self.jtag_axil_op(write=False, addr=_SHIM_ADDR)
        restore_code, _ = await self.jtag_axil_op(write=True, addr=_SHIM_ADDR, wdata=_SHIM_RESET)
        self.logger.info(
            "OBS-JTAG-SHIM-ALLOW-DATA addr=0x%08x rdata=0x%08x wdata=0x%08x readback=0x%08x "
            "readback_resp=%d restore=0x%08x restore_resp=%d",
            _SHIM_ADDR,
            rdata,
            _SHIM_WDATA,
            back,
            back_code,
            _SHIM_RESET,
            restore_code,
        )
        assert rd_code == _OKAY and wr_code == _OKAY, (
            f"CHK-JTAG-SHIM-ALLOW FAIL: JTAG read and write of the shim span @0x{_SHIM_ADDR:08x} "
            f"in TEST_DEV must be OKAY; got rd_resp={rd_code} wr_resp={wr_code}"
        )
        self.logger.info(
            "CHK-JTAG-SHIM-ALLOW PASS: JTAG read and write @0x%08x OKAY in TEST_DEV "
            "(rd_resp=%d wr_resp=%d)",
            _SHIM_ADDR,
            rd_code,
            wr_code,
        )

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(lc_raw=LC_TEST_DEV)
        assert image.lc_raw() == LC_TEST_DEV, (
            f"test bug: image LC_STATE is not TEST_DEV (0x{image.lc_raw():x}); "
            "a restricted image would refuse these windows"
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self._allow("shadow", _EFUSE_SHADOW_BASE)
        await self._allow("EFUSE_PROGRAM_CTRL", _EFUSE_IFACE_PROGRAM)
        await self._shim_allow()
