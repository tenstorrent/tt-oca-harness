# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded AXI error-response checks over real SEP_IN AXI."""

from __future__ import annotations

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import external_gpio_ctrl_addr, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_DECERR = 3

# Alive sentinel: always-OKAY local CSR (before/after fabric-alive proof).
ALIVE_SENTINEL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)

# DECERR probes. These were described as "intentional unmapped holes" per
# memmap.adoc; that description is WRONG in two ways and is corrected here
# ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
#
# 1. Neither offset is a hole. `smc.rdl:101-105` declares three
#    `external remapped_region` blocks of 0x80_0000 each:
#      ecam_region   BASE+0x080_0000 .. BASE+0x0FF_FFFF
#      mmode_region  BASE+0x100_0000 .. BASE+0x17F_FFFF
#      xvisor_region BASE+0x180_0000 .. BASE+0x1FF_FFFF
#    `BASE + 0x0FF_F000` lies INSIDE ecam_region. What these probes actually
#    demonstrate is that an `external` region with no implementation behind it
#    on this bench answers DECERR -- which is worth locking, but it is not an
#    address-decode hole.
#
# 2. The high probe does not even reach the address written. The local fabric
#    rewrites every incoming address as {LOCAL_BASE[31:25], addr[24:0]}
#    (`smc_local_fabric.sv:66-78`, LOCAL_BASE reset 0xC000_0000; see #1237 /
#    #1249), so `BASE + 0x0FFF_F000` = 0xCFFF_F000 arrives as 0xC1FF_F000 --
#    inside xvisor_region, not 0x0F_FF_F000 of anything.
#
# There is no genuinely unmapped address left to probe on this path: the
# surviving offset field is [24:0], i.e. 0x000_0000..0x1FF_FFFF, and
# xvisor_region covers it up to the top. The probes are kept for what they do
# show, with their names and the evidence token corrected to match.
_SMC_TOP_BASE = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")
# Inside ecam_region; passes through the masking unchanged (bits [31:25] are
# already LOCAL_BASE's).
_UNIMPL_ECAM = _SMC_TOP_BASE + 0x00FF_F000
# Written as 0xCFFF_F000, ARRIVES as 0xC1FF_F000 inside xvisor_region.
_UNIMPL_XVISOR_VIA_MASK = _SMC_TOP_BASE + 0x0FFF_F000

# EXTERNAL_MANDATORY GPIO_CTRL is terminated with DECERR on the OSS DUT path
# (smc_ip_integration err_slv). Replaces the obsolete I3C-stub SLVERR probe —
# OCA_I3C_WRAP is a real core (OKAY) after open-source integration.
_GPIO_CTRL0 = external_gpio_ctrl_addr(0)

# (name, addr, expected AXI resp)
ERROR_PROBES: list[tuple[str, int, int]] = [
    ("UNIMPL_ECAM_REGION", _UNIMPL_ECAM, AXI_RESP_DECERR),
    ("UNIMPL_XVISOR_REGION_VIA_MASK", _UNIMPL_XVISOR_VIA_MASK, AXI_RESP_DECERR),
    ("GPIO_CTRL_ERR_SLAVE", _GPIO_CTRL0, AXI_RESP_DECERR),
]


class smc_axi_error_response_depth_test_seq(SmcCsrSeq):
    """Probe invalid/boundary addresses and prove the fabric recovers."""

    def __init__(self, name: str = "smc_axi_error_response_depth_test_seq") -> None:
        super().__init__(name)
        self.error_responses = 0

    async def _error_probe(self, name: str, addr: int, expected_resp: int) -> None:
        item = SmcSysAxiItem(f"err_rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        item.expected_resp = expected_resp
        # Timeout must fail: a claimed error response cannot soft-pass on wedge.
        item.allow_timeout = False
        item.timeout_ns = 500
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

        assert not item.timed_out, (
            f"{name} @ 0x{addr:08x}: timed out (expected AXI resp={expected_resp}, "
            "not a hang)"
        )
        assert item.resp_code == expected_resp, (
            f"{name} @ 0x{addr:08x}: resp={item.resp_code}, expected {expected_resp}"
        )
        self.error_responses += 1

    async def body(self) -> None:
        # Tell the passive AXI monitor which DECERR addresses are by-design so
        # they are tallied rather than flagged as hard protocol errors.
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update(
                addr
                for _name, addr, resp in ERROR_PROBES
                if resp == AXI_RESP_DECERR
            )

        await self.csr_read("ALIVE_SENTINEL_BASELINE", ALIVE_SENTINEL)

        for name, addr, expected_resp in ERROR_PROBES:
            await self._error_probe(name, addr, expected_resp)

        await self.csr_read("ALIVE_SENTINEL_RECOVERY", ALIVE_SENTINEL)

        assert self.timeouts == 0, (
            f"AXI error-response probes must not time out (timeouts={self.timeouts})"
        )
        assert self.error_responses == len(ERROR_PROBES), (
            f"expected {len(ERROR_PROBES)} error responses, "
            f"got {self.error_responses}"
        )
