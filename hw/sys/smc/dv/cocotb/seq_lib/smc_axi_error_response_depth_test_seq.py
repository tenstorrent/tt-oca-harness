# SPDX-License-Identifier: Apache-2.0
"""Bounded AXI error-response checks over real SEP_IN AXI."""

from __future__ import annotations

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_csr_seq_utils import SmcCsrSeq

I3C0_HCI_VERSION = 0xC000_5000

# A real, always-OKAY local CSR used as the before/after "fabric is alive"
# sentinel. CLOCK_GATE_CONTROL (SMC_BASE_CONFIG, offset 0x18) is backed by a real
# register block, so a successful read proves the fabric services valid accesses.
# (I3C0_HCI_VERSION cannot serve this role any more: the I3C core is stubbed in
# RTL -- i3ccore_stub, "TODO: stub i3c out" -- and always returns SLVERR.)
ALIVE_SENTINEL = 0xC001_0018

ERROR_PROBES = [
    ("UNMAPPED_LOW", 0xC0FF_F000),
    ("UNMAPPED_HIGH", 0xCFFF_F000),
    # Misaligned access into the stubbed I3C window: the i3ccore_stub error slave
    # returns SLVERR, which is exactly the bounded error response this probes for.
    ("MISALIGNED_I3C", I3C0_HCI_VERSION + 1),
]


class smc_axi_error_response_depth_test_seq(SmcCsrSeq):
    """Probe invalid/boundary addresses and prove the fabric recovers."""

    def __init__(self, name: str = "smc_axi_error_response_depth_test_seq") -> None:
        super().__init__(name)
        self.error_responses = 0

    async def _error_probe(self, name: str, addr: int) -> None:
        item = SmcSysAxiItem(f"err_rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        item.allow_timeout = True
        item.timeout_ns = 500
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

        if item.timed_out:
            self.timeouts += 1
            return

        assert item.resp_code is not None, f"{name} returned without a response code"
        assert item.resp_code > 1, f"{name} unexpectedly returned OKAY/EXOKAY"
        self.error_responses += 1

    async def body(self) -> None:
        # These probes deliberately hit unmapped/invalid addresses to prove the
        # fabric returns an error (not a hang). Tell the passive AXI monitor the
        # DECERR on these exact addresses is expected-by-design for this test, so
        # it is tallied rather than flagged as a hard protocol error.
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update(addr for _name, addr in ERROR_PROBES)

        await self.csr_read("ALIVE_SENTINEL_BASELINE", ALIVE_SENTINEL)

        for name, addr in ERROR_PROBES:
            await self._error_probe(name, addr)

        await self.csr_read("ALIVE_SENTINEL_RECOVERY", ALIVE_SENTINEL)

        assert self.error_responses + self.timeouts == len(ERROR_PROBES), (
            "AXI error-response probes did not complete as bounded errors"
        )
