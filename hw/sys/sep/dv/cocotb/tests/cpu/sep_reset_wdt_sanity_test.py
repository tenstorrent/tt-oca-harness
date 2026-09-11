# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP reset-controller + WDT sanity test (PyUVM).

OSS port combining the reference suite ``sep_reset_ctrl_csr_test`` and ``wdt_sanity_test``.
Boots the VeeR EL2 core and runs the reset_wdt_sanity firmware, which:
  * verifies SW_RESET_N default 0x3E and that pulsing each crypto/TRNG reset bit
    clears the corresponding probe CSRs;
  * proves a write + a read to an unmapped fabric gap each raise a D-bus-error
    NMI (count == 2);
  * exercises the WDT bark -> NMI, pet, disable-freeze, and re-bark; then lets the
    WDT run on to BITE.

Firmware-self-checking (start.S emits PASS/FAIL magic from main()'s return code).
On top of that, this test observes the BITE reset request on the real ``sep``
output ``wdt_timer_rst_req_o`` (brought out in tb_top): after the firmware PASSes
(2nd bark), the still-enabled WDT advances to BITE_THOLD and asserts the reset
request, which the cocotb side must see -- the WDT's headline safety function.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
JTAG-holds OTBN/AES/HMAC/KMAC across ``rst_ni`` release and fuse sense so they
never raise crypto ``edn_req`` while the fabric is opening, then drops the
override. The hold must not outlast sense: the firmware probes each engine's
reset wire, and a held engine's registers are unreachable, so the probe write
traps instead of landing.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "reset_wdt_sanity_test")
_ITCM_HEX = os.path.join(_FW_DIR, "reset_wdt_sanity_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "reset_wdt_sanity_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP reset+WDT sanity test"
# After the firmware PASSes (2nd bark), the WDT runs on to BITE. At ~5 us/tick and
# a few ticks of bark->bite margin, give generous headroom for the reset request.
_BITE_POLL_CYCLES = 40_000


@pyuvm.test()
class sep_reset_wdt_sanity_test(sep_base_test):
    """Boot VeeR EL2; verify reset_ctrl CSR + WDT bark/pet/disable + BITE reset."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
            park=("otbn", "aes", "hmac", "kmac"),
            release_park=True,
        )

        # The firmware PASS gates the reset_ctrl + WDT bark/pet/disable/re-bark
        # checks. Now observe the BITE: the still-enabled WDT reaches BITE_THOLD
        # and asserts the real wdt_timer_rst_req_o output.
        dut = cocotb.top
        bite_seen = False
        for _ in range(_BITE_POLL_CYCLES):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.wdt_timer_rst_req_o):
                bite_seen = True
                break
        assert bite_seen, (
            "CHK-BITE: wdt_timer_rst_req_o never asserted after re-bark "
            "(BITE reset request not observed)"
        )
        self.logger.info(
            "CHK-BITE PASS: wdt_timer_rst_req_o asserted -> WDT BITE reset request observed"
        )
