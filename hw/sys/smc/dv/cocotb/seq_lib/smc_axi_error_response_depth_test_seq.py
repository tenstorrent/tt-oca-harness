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

# Intentional unmapped holes — SPEC: hw/sys/smc/doc/memmap.adoc
# "SMC Address Space Layout". Offsets are not decoded CSR windows; fabric
# default slave returns DECERR.
_SMC_TOP_BASE = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")
_UNMAPPED_LOW = _SMC_TOP_BASE + 0x00FF_F000
_UNMAPPED_HIGH = _SMC_TOP_BASE + 0x0FFF_F000

# EXTERNAL_MANDATORY GPIO_CTRL is terminated with DECERR on the OSS DUT path
# (smc_ip_integration err_slv). Replaces the obsolete I3C-stub SLVERR probe —
# OCA_I3C_WRAP is a real core (OKAY) after open-source integration.
_GPIO_CTRL0 = external_gpio_ctrl_addr(0)

# (name, addr, expected AXI resp)
ERROR_PROBES: list[tuple[str, int, int]] = [
    ("UNMAPPED_LOW", _UNMAPPED_LOW, AXI_RESP_DECERR),
    ("UNMAPPED_HIGH", _UNMAPPED_HIGH, AXI_RESP_DECERR),
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
