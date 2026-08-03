# SPDX-License-Identifier: Apache-2.0
"""Bounded AXI error-response checks over real SEP_IN AXI."""

from __future__ import annotations

import sys
from pathlib import Path

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    OCA_I3C_WRAP_0_REG_MAP_BASE_ADDR,
    SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_ADDR,
    SMC_TOP_REG_MAP_BASE_ADDR,
)

AXI_RESP_SLVERR = 2
AXI_RESP_DECERR = 3

# Alive sentinel: always-OKAY local CSR (before/after fabric-alive proof).
# I3C0 cannot serve this role: i3ccore_stub always returns SLVERR.
ALIVE_SENTINEL = SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_ADDR

# Intentional unmapped holes — SPEC: hw/sys/smc/doc/memmap.adoc
# "SMC Address Space Layout" (LOCAL_BASE = SMC_TOP_REG_MAP_BASE_ADDR).
# Offsets are not decoded CSR windows; fabric default slave returns DECERR.
_UNMAPPED_LOW = SMC_TOP_REG_MAP_BASE_ADDR + 0x00FF_F000
_UNMAPPED_HIGH = SMC_TOP_REG_MAP_BASE_ADDR + 0x0FFF_F000

# (name, addr, expected AXI resp). MISALIGNED_I3C hits i3ccore_stub → SLVERR.
ERROR_PROBES: list[tuple[str, int, int]] = [
    ("UNMAPPED_LOW", _UNMAPPED_LOW, AXI_RESP_DECERR),
    ("UNMAPPED_HIGH", _UNMAPPED_HIGH, AXI_RESP_DECERR),
    ("MISALIGNED_I3C", OCA_I3C_WRAP_0_REG_MAP_BASE_ADDR + 1, AXI_RESP_SLVERR),
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
        # they are tallied rather than flagged as hard protocol errors. SLVERR
        # probes (I3C stub) are not listed here.
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
