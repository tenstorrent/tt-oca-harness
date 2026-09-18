# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP reset-controller + WDT sanity test (PyUVM).

OSS port combining the reference suite ``sep_reset_ctrl_csr_test`` and ``wdt_sanity_test``.
Boots the VeeR EL2 core and runs the reset_wdt_sanity firmware, which:
  * verifies SW_RESET_N default 0x7E and that pulsing each crypto/TRNG/ABR reset bit
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
# Console anchors. Each names a leg the firmware scores separately, so a stale image
# that dropped one is visible here rather than hiding behind the PASS magic.
_BADADDR_LINE = "reset_ctrl bad-address NMI count == 2 OK"
_SWRST_DEFAULT_NEEDLE = "SW_RESET_N default"
_RESET_WIRE_IPS = ("otbn", "aes", "hmac", "kmac", "abr", "esrc", "csrng", "edn")
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

        async def _bite_idle() -> None:
            assert self.rd_known(cocotb.top.wdt_timer_rst_req_o) == 0, (
                "CHK-BITE FAIL: wdt_timer_rst_req_o asserted before firmware "
                "enabled the WDT, so a later 1 cannot be attributed to BITE"
            )

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
            after_bring_up_hook=_bite_idle,
        )

        # The firmware scores the reset_ctrl legs into its own error count, and the
        # PASS magic alone cannot say which of them ran: an image built before a leg
        # existed reaches PASS with that contract never exercised. Gate on the line
        # each leg prints, and emit the record the VPLAN card names for it.
        console = self.sb.console_text()
        assert _BADADDR_LINE in console, (
            f"firmware console has no {_BADADDR_LINE!r} line, so the unmapped-gap "
            f"bus-error count was not checked. Console was:\n{console}"
        )
        self.logger.info("CHK-BADADDR PASS: firmware reported the bad-address NMI count == 2")
        wired = [ip for ip in _RESET_WIRE_IPS if f"{ip} reset wire OK" in console]
        assert len(wired) == len(_RESET_WIRE_IPS), (
            f"firmware console reports a reset wire for {sorted(wired)}, expected all "
            f"{sorted(_RESET_WIRE_IPS)}; a missing domain is an unexercised reset bit. "
            f"Console was:\n{console}"
        )
        self.logger.info(
            "CHK-SWRST-WIRE PASS: %d reset domains each returned their probe and left "
            "the neighbour untouched",
            len(wired),
        )
        assert _SWRST_DEFAULT_NEEDLE in console, (
            f"firmware console has no {_SWRST_DEFAULT_NEEDLE!r} in its verdict line, so "
            f"the SW_RESET_N default was not checked. Console was:\n{console}"
        )
        self.logger.info("CHK-SWRST-DEFAULT PASS: firmware reported the SW_RESET_N default")

        # Now observe the BITE: the still-enabled WDT reaches BITE_THOLD
        # and asserts the real wdt_timer_rst_req_o output.
        dut = cocotb.top
        bite_seen = self.rd_known(dut.wdt_timer_rst_req_o) == 1
        for _ in range(_BITE_POLL_CYCLES):
            if bite_seen:
                break
            await RisingEdge(dut.clk_i)
            if self.rd_known(dut.wdt_timer_rst_req_o):
                bite_seen = True
                break
        assert bite_seen, (
            "CHK-BITE: wdt_timer_rst_req_o never asserted after re-bark "
            "(BITE reset request not observed)"
        )
        self.logger.info(
            "CHK-BITE PASS: wdt_timer_rst_req_o asserted -> WDT BITE reset request observed"
        )
