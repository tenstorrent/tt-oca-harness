# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U7-3: CPU JTAG DMI smoke — dmactive + dmstatus.version.

Hard gates:
  * DTMCS version == 0x1 (Debug Spec 0.13 DTM)
  * After dmcontrol.dmactive=1, dmstatus.version == 2 (DM 0.13)

Prerequisites (TB):
  * CPU_CTRL.RESET_CTRL.debug_reset_n (bit 24) released — RDL default 0 holds
    the Rocket DM in reset (inner DMI bypassed; dmactiveAck stuck).
  * JTAG reset pulsed *with TCK running* — DMI TL xbar uses sync reset on TCK.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap


class smc_jtag_dmi_smoke_test_seq(SmcCsrSeq):
    """Release debug_reset_n -> TAP reset -> IDCODE -> DTMCS -> DMI dmstatus."""

    def __init__(self, name: str = "smc_jtag_dmi_smoke_test_seq") -> None:
        super().__init__(name)
        self.idcode: int = 0
        self.dtmcs: int = 0
        self.dmstatus: int = 0
        self.dmi_ok: bool = False

    async def body(self) -> None:
        await self.csr_write(
            "CPU_CTRL_DEBUG_RESET_RELEASE",
            CPU_CTRL_RESET_CTRL,
            CPU_RESET_CTRL_DEBUG_RELEASE,
            length=8,
        )
        await ClockCycles(cocotb.top.clk_smc_i, 64)
        reset_ctrl = await self.csr_read("CPU_CTRL_RESET_CTRL_RB", CPU_CTRL_RESET_CTRL, length=8)
        assert reset_ctrl & (1 << 24), f"debug_reset_n not set in RESET_CTRL (got 0x{reset_ctrl:X})"

        tap = SmcJtagTap(name="smc_jtag_dmi")
        tap.init_signals()
        await tap.reset_tap()
        self.idcode = await tap.read_idcode(check=True)
        self.dtmcs = await tap.read_dtmcs()
        dtmcs_ver = self.dtmcs & 0xF
        assert dtmcs_ver == 0x1, (
            f"DTMCS version=0x{dtmcs_ver:X} != 0x1 (got DTMCS=0x{self.dtmcs:08X})"
        )

        self.dmstatus = await tap.read_dmstatus()
        dm_ver = self.dmstatus & 0xF
        assert dm_ver == 2, (
            f"dmstatus.version={dm_ver} != 2 (Debug Spec 0.13); dmstatus=0x{self.dmstatus:08X}"
        )
        assert self.dmstatus != 0, "dmstatus read as zero after dmactive"
        self.dmi_ok = True
        # Emitted only after the three exact compares above pass; the line
        # carries the captured words, not the expected constants.
        cocotb.log.info(
            "CHK-JTAG-DMI-SMOKE: IDCODE=0x%08X DTMCS=0x%08X dmstatus=0x%08X "
            "(DTMCS.version=0x%X, dmstatus.version=%d)",
            self.idcode,
            self.dtmcs,
            self.dmstatus,
            self.dtmcs & 0xF,
            self.dmstatus & 0xF,
        )
