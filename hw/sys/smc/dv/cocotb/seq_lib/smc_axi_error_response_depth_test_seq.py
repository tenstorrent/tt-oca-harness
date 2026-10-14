# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded AXI error-response checks over real SEP_IN AXI."""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    external_gpio_ctrl_addr,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_DECERR = 3

# Alive sentinel: always-OKAY local CSR (before/after fabric-alive proof).
ALIVE_SENTINEL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

# DECERR probes, each named for the region the authoritative map puts it in and
# each address built from generated symbols rather than a hand-computed offset
# ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
#
# The first probe is the last page of the unmapped gap below mmode_region,
# inside the local aperture (LOCAL_BASE .. LOCAL_BASE + REGION_SIZE at the
# generated resets), which the fabric error slave answers with DECERR. The
# full sweep of unmapped offsets inside the aperture is
# `smc_deadspace_decode_test`'s subject; this test needs one such page for its
# error-depth bursts.
_UNMAPPED_BELOW_MMODE = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR") - 0x1000
# The same page offset fourteen apertures above LOCAL_BASE: outside both the
# local and the global aperture at the generated resets, so the input fabric's
# window check answers it with DECERR before it reaches any region.
_ABOVE_APERTURE = (
    LOCAL_BASE_RESET + 14 * REGION_SIZE_RESET + (_UNMAPPED_BELOW_MMODE - LOCAL_BASE_RESET)
)
for _base in (LOCAL_BASE_RESET, GLOBAL_BASE_RESET):
    assert not _base <= _ABOVE_APERTURE < _base + REGION_SIZE_RESET, (
        f"0x{_ABOVE_APERTURE:08x} lies inside the aperture at 0x{_base:08x}"
    )

# EXTERNAL_MANDATORY GPIO_CTRL is a DECERR probe: the OSS tree carries no GPIO
# pad block behind that window (memmap.adoc lists it as technology-specific),
# and the reference integration terminates it with an error slave.
# OCA_I3C_WRAP is a real core and answers OKAY, so it is not a DECERR probe.
_GPIO_CTRL0 = external_gpio_ctrl_addr(0)

# Data expected alongside the error response: ``ERR_SLAVE_SIGNATURE`` is the
# word every error slave in the design returns, whether it is the fabric's
# own (unmapped-gap and above-aperture probes) or the reference integration's
# GPIO_CTRL terminator.
ERR_SLAVE_SIGNATURE = SmcCsrSeq.ERR_SLAVE_SIGNATURE

# (name, addr, expected AXI resp, expected rdata)
ERROR_PROBES: list[tuple[str, int, int, int]] = [
    ("UNMAPPED_BELOW_MMODE", _UNMAPPED_BELOW_MMODE, AXI_RESP_DECERR, ERR_SLAVE_SIGNATURE),
    ("ABOVE_APERTURE_WINDOW_CHECK", _ABOVE_APERTURE, AXI_RESP_DECERR, ERR_SLAVE_SIGNATURE),
    ("GPIO_CTRL_ERR_SLAVE", _GPIO_CTRL0, AXI_RESP_DECERR, ERR_SLAVE_SIGNATURE),
]


class smc_axi_error_response_depth_test_seq(SmcCsrSeq):
    """Probe invalid/boundary addresses and prove the fabric recovers."""

    def __init__(self, name: str = "smc_axi_error_response_depth_test_seq") -> None:
        super().__init__(name)
        self.error_responses = 0
        #: Sentinel word read before the probes, re-pinned after them.
        self.sentinel_word: int | None = None

    async def _error_probe(
        self, name: str, addr: int, expected_resp: int, expected_rdata: int
    ) -> None:
        item = SmcSysAxiItem(f"err_rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        item.expected_resp = expected_resp
        # With `allow_timeout` False, `SmcSysAxiDriver._timed_event` raises on a
        # no-response, so a wedged probe fails in the driver.
        item.allow_timeout = False
        item.timeout_ns = 500
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

        assert item.resp_code == expected_resp, (
            f"{name} @ 0x{addr:08x}: resp={item.resp_code}, expected {expected_resp}"
        )
        got = item.rdata & 0xFFFF_FFFF
        assert got == expected_rdata, (
            f"{name} @ 0x{addr:08x}: error-slave data 0x{got:08x}, expected "
            f"0x{expected_rdata:08x} (resp={item.resp_code})"
        )
        self.error_responses += 1

    async def body(self) -> None:
        # Tell the passive AXI monitor which DECERR addresses are by-design so
        # they are tallied rather than flagged as hard protocol errors. `env` is
        # assigned by `smc_base_test.start_seq` before `seq.start`, and `SmcEnv`
        # always builds `axi_monitor`, so a missing monitor is a bench-wiring
        # error and is asserted rather than skipped.
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        assert monitor is not None, (
            "no axi_monitor on this sequence's env; the by-design DECERR "
            "addresses cannot be registered and every probe below would be "
            "flagged as a protocol error"
        )
        decerr_addrs = [
            addr for _name, addr, resp, _data in ERROR_PROBES if resp == AXI_RESP_DECERR
        ]
        monitor.expected_decerr_addrs.update(decerr_addrs)
        cocotb.log.info(
            "AXI monitor: registered %d by-design DECERR address(es): %s",
            len(decerr_addrs),
            ", ".join(f"0x{a:08x}" for a in decerr_addrs),
        )

        baseline = await self.csr_read("ALIVE_SENTINEL_BASELINE", ALIVE_SENTINEL)
        self.sentinel_word = baseline

        for name, addr, expected_resp, expected_rdata in ERROR_PROBES:
            await self._error_probe(name, addr, expected_resp, expected_rdata)

        # Recovery means the sentinel returns the same word it held before the
        # probes, not merely that it still answers OKAY; `expected` makes the
        # scoreboard book the compare.
        await self.csr_read("ALIVE_SENTINEL_RECOVERY", ALIVE_SENTINEL, expected=baseline)

        # The error probes bypass `csr_read`, so `sys_axi_checks_seen` covering
        # all five accesses is what shows the analysis path is bound.
        self.assert_all_reachable(len(ERROR_PROBES) + 2, "AXI_ERROR_RESPONSE_DEPTH")
        sb = self.env.scoreboard
        assert sb.sys_axi_value_checks_seen >= 1, (
            "the recovery read booked no scoreboard value check, so the "
            "baseline/recovery compare never ran"
        )
        cocotb.log.info(
            "CHK-AXI-ERR-DEPTH: %d probe(s) answered resp=%d with the exact "
            "err-slave data (%s); ALIVE_SENTINEL @ 0x%08x returned 0x%08x "
            "before the probes and the same word after (value-checked); "
            "scoreboard value_checks=%d",
            len(ERROR_PROBES),
            AXI_RESP_DECERR,
            ", ".join(f"{n}@0x{a:08x}=0x{d:08x}" for n, a, _r, d in ERROR_PROBES),
            ALIVE_SENTINEL,
            baseline,
            sb.sys_axi_value_checks_seen,
        )
