# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded AXI error-response checks over real SEP_IN AXI."""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    LOCAL_FABRIC_KEEP_MASK,
    external_gpio_ctrl_addr,
    local_fabric_masked_addr,
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
# Neither probe is an address-decode hole. `smc.rdl:101-105` declares three
# `external remapped_region` blocks of 0x80_0000 each -- ecam_region,
# mmode_region, xvisor_region -- and `smc_addr.h` resolves them to
# 0xC080_0000, 0xC100_0000 and 0xC180_0000. What the two probes demonstrate is
# that an `external` region with no implementation behind it on this bench
# answers DECERR with the err_slv signature. No genuinely unmapped SEP_IN
# address is available to probe: the fold in `local_fabric_masked_addr` leaves
# only addr[24:0], i.e. 0x000_0000..0x1FF_FFFF, and xvisor_region covers that
# range up to the top.
#
# Last page of ecam_region. Its upper 7 bits are already LOCAL_BASE's, so the
# fold is the identity here and the request arrives where it was written.
_UNIMPL_ECAM = (
    smc_addr("SMC_TOP_ECAM_REGION_BASE_ADDR") + smc_addr("SMC_TOP_ECAM_REGION_SIZE") - 0x1000
)
# Last page of xvisor_region, reached only THROUGH the fold: the written
# address carries a different upper 7 bits, so the request arrives at
# `_XVISOR_TOP_PAGE` rather than at the address on the wire. The two asserts
# below fail if the generated map moves either region such that the probe stops
# demonstrating the fold.
_XVISOR_TOP_PAGE = (
    smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR") + smc_addr("SMC_TOP_XVISOR_REGION_SIZE") - 0x1000
)
_UNIMPL_XVISOR_VIA_MASK = 0xCE00_0000 | (_XVISOR_TOP_PAGE & LOCAL_FABRIC_KEEP_MASK)
assert _UNIMPL_XVISOR_VIA_MASK != _XVISOR_TOP_PAGE, (
    "the high probe must be written OUTSIDE the local aperture so it reaches "
    "xvisor_region only through the smc_local_fabric fold"
)
assert local_fabric_masked_addr(_UNIMPL_XVISOR_VIA_MASK) == _XVISOR_TOP_PAGE, (
    f"0x{_UNIMPL_XVISOR_VIA_MASK:08x} folds to "
    f"0x{local_fabric_masked_addr(_UNIMPL_XVISOR_VIA_MASK):08x}, not to the "
    f"xvisor_region top page 0x{_XVISOR_TOP_PAGE:08x}"
)

# EXTERNAL_MANDATORY GPIO_CTRL is terminated with DECERR on the OSS DUT path
# (smc_ip_integration err_slv). Replaces the obsolete I3C-stub SLVERR probe —
# OCA_I3C_WRAP is a real core (OKAY) after open-source integration.
_GPIO_CTRL0 = external_gpio_ctrl_addr(0)

# Data an AXI error slave returns alongside the error response. The two
# remap-region terminators are `prim_axi_lite_err_slv` instances at their
# default RESP_DATA; the smc_ip_integration GPIO_CTRL terminator drives zero.
ERR_SLAVE_SIGNATURE = SmcCsrSeq.ERR_SLAVE_SIGNATURE
_GPIO_CTRL_ERR_DATA = 0x0

# (name, addr, expected AXI resp, expected rdata)
ERROR_PROBES: list[tuple[str, int, int, int]] = [
    ("UNIMPL_ECAM_REGION", _UNIMPL_ECAM, AXI_RESP_DECERR, ERR_SLAVE_SIGNATURE),
    (
        "UNIMPL_XVISOR_REGION_VIA_MASK",
        _UNIMPL_XVISOR_VIA_MASK,
        AXI_RESP_DECERR,
        ERR_SLAVE_SIGNATURE,
    ),
    ("GPIO_CTRL_ERR_SLAVE", _GPIO_CTRL0, AXI_RESP_DECERR, _GPIO_CTRL_ERR_DATA),
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
        # `allow_timeout` False is what enforces [TIMEOUT-MUST-FAIL] here: on
        # expiry `SmcSysAxiDriver._timed_event` (env/smc_sys_axi_agent.py:159-173)
        # RAISES instead of returning, so a wedged probe fails the testcase in
        # the driver and no `not item.timed_out` assert downstream of this await
        # is reachable with `timed_out` set.
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

        # Recovery is pinned against the word the SAME register returned before
        # the probes, so "the fabric recovered" means "returns the same content",
        # not merely "still answers OKAY". The compare is booked by the
        # scoreboard (env/smc_scoreboard.py:711-718) because `expected` is set.
        await self.csr_read("ALIVE_SENTINEL_RECOVERY", ALIVE_SENTINEL, expected=baseline)

        # Reachability against the scoreboard's own tally rather than against
        # `self.error_responses`, which this sequence increments once per loop
        # iteration and so restates the loop ([NO-ZERO-ACTIVITY-PASS]). The
        # error probes bypass `csr_read`, so `sys_axi_checks_seen` advancing to
        # cover all five accesses is what shows the analysis path is bound.
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
