# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SW_RESET_N clears only its own domain, fabric gaps raise a bus-error NMI, and the WDT bites.

OCAH provenance: ``sep_reset_ctrl_csr_test`` checks reset-control CSRs and
domains, and ``wdt_sanity_test`` checks watchdog bark, pet, disable and bite.

The reset_wdt_sanity firmware:
  * checks SW_RESET_N default 0x7E, that pulsing each crypto/TRNG/ABR reset bit clears that
    domain's probe CSRs and leaves every probe outside that reset bit unchanged, and that each
    probe is writable again after release;
  * checks that a write and a read to an unmapped fabric gap each raise a D-bus-error NMI
    (count == 2);
  * exercises WDT bark -> NMI, pet, disable-freeze and re-bark, then lets the WDT run to BITE.

fw/startup/crt0.s emits PASS/FAIL magic from main()'s return code. After PASS the test also
observes the BITE reset request on the ``sep`` output ``wdt_timer_rst_req_o``.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``. OTBN/AES/HMAC/KMAC are
JTAG-held across ``rst_ni`` release and fuse sense so they raise no crypto ``edn_req`` while the
fabric opens. The hold must end with sense: a held engine's registers are unreachable, so the
firmware's reset-wire probe write would trap.
"""

from __future__ import annotations

import os
import re
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
_SWRST_DEFAULT_NEEDLE = "PASS: SW_RESET_N default"
_RESET_WIRE_IPS = ("otbn", "aes", "hmac", "kmac", "abr", "esrc", "csrng", "edn")
# Reset bit of each probe's domain: esrc, csrng and edn share the TRNG bit.
_RESET_DOMAIN = {ip: ("trng" if ip in ("esrc", "csrng", "edn") else ip) for ip in _RESET_WIRE_IPS}
# Each reset-wire line ends with the count of other-domain probes the firmware
# found unchanged after the pulse.
_WIRE_LINE_RE = re.compile(
    r"(\w+) reset wire OK, writable after release, other-domain probes unchanged 0x([0-9a-f]{8})"
)
# The firmware prints this after "<ip>" only once the probe, rewritten after the
# release, reads back its non-reset value.
_WRITABLE_SUFFIX = " reset wire OK, writable after release"
_BANNER = "SEP reset+WDT sanity test"
# After the firmware PASSes (2nd bark), the WDT runs on to BITE. At ~5 us/tick and
# a few ticks of bark->bite margin, give generous headroom for the reset request.
_BITE_POLL_CYCLES = 40_000


@pyuvm.test()
class sep_reset_wdt_sanity_test(sep_base_test):
    """reset_ctrl CSR, WDT bark/pet/disable legs pass, and the BITE raises wdt_timer_rst_req_o."""

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
        # PASS magic alone cannot say which of them ran: an image without a leg
        # reaches PASS with that contract never exercised. Gate on the line each
        # leg prints, and emit the record the VPLAN row names for it.
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
        unchanged = {m.group(1): int(m.group(2), 16) for m in _WIRE_LINE_RE.finditer(console)}
        want_unchanged = {
            ip: sum(1 for nb in _RESET_WIRE_IPS if _RESET_DOMAIN[nb] != _RESET_DOMAIN[ip])
            for ip in _RESET_WIRE_IPS
        }
        assert unchanged == want_unchanged, (
            f"CHK-SWRST-WIRE FAIL: other-domain probes found unchanged per pulse "
            f"{unchanged}, expected {want_unchanged}; a pulse that checked fewer "
            f"domains leaves a cross-wired reset bit unseen. Console was:\n{console}"
        )
        self.logger.info(
            "CHK-SWRST-WIRE PASS: %d reset bits each returned their probe and left every "
            "probe outside that bit unchanged (per pulse: %s)",
            len(wired),
            ", ".join(f"{ip}={unchanged[ip]}" for ip in _RESET_WIRE_IPS),
        )
        writable = [ip for ip in _RESET_WIRE_IPS if f"{ip}{_WRITABLE_SUFFIX}" in console]
        assert len(writable) == len(_RESET_WIRE_IPS), (
            f"firmware console reports a post-release write/readback for "
            f"{sorted(writable)}, expected all {sorted(_RESET_WIRE_IPS)}; a missing "
            f"domain was never shown writable after its reset release. "
            f"Console was:\n{console}"
        )
        self.logger.info(
            "CHK-SWRST-WRITABLE PASS: %d reset domains each read back a non-reset "
            "probe value written after the release",
            len(writable),
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
