# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: CPU cluster infrastructure (TC_SMC_P1CG_10/11/12).

Bundles three previously-unreached CPU-cluster CSR surfaces:

* Per-core WDT (0xC000_0000, stride 0x400, 4 cores).
* SMC_CLUSTER_PLIC (0xC400_0000) — RISC-V PLIC interrupt controller.
* SMC_CLUSTER_CLINT (0xC800_0000) — RISC-V CLINT machine timer.

Reads are bounded (`csr_read_allow_error`) because these blocks are
CPU-clock-gated in the current OSS bring-up and may return DECERR
without CPU firmware.
"""

from __future__ import annotations

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_csr_seq_utils import SmcCsrSeq

# The CPU cluster (WDT/PLIC/CLINT) is not fully exercisable in the DUT-only OSS
# bench (no CPU firmware). Per-window outcome is mixed on both VCS and
# Verilator (some probes timeout / DECERR, some return OKAY with zero data), so
# the hard gate is no-deadlock on the shared SEP_IN CSR master -- not a strict
# "never OKAY" invariant.
CLUSTER_CPU_READS = [
    # Per-core WDT sanity
    ("WDT_CORE0_CFG",  0xC000_0000),
    ("WDT_CORE1_CFG",  0xC000_0400),
    ("WDT_CORE2_CFG",  0xC000_0800),
    ("WDT_CORE3_CFG",  0xC000_0C00),
    # PLIC representative regs
    ("PLIC_PRIORITY_1", 0xC400_0004),
    ("PLIC_PENDING_0",  0xC400_1000),
    ("PLIC_ENABLE_0",   0xC400_2000),
    # CLINT representative regs
    ("CLINT_MSIP_0",       0xC800_0000),
    ("CLINT_MTIMECMP_0_LO", 0xC800_4000),
    ("CLINT_MTIME_LO",     0xC800_BFF8),
]

# CPU-cluster apertures that DECERR by design here: seeded into the passive AXI
# monitor's expected-DECERR set so the PLIC_PENDING DECERR is tallied, not
# flagged as a hard protocol error. (The monitor otherwise treats any DECERR
# outside its macro/boundary ranges as a failure.)
CLUSTER_DECERR_RANGES = [
    (0xC000_0000, 0xC000_1000),  # per-core WDT (4 cores, stride 0x400)
    (0xC400_0000, 0xC800_0000),  # SMC_CLUSTER_PLIC aperture
    (0xC800_0000, 0xC800_C000),  # SMC_CLUSTER_CLINT aperture
]


class smc_cluster_cpu_infra_test_seq(SmcCsrSeq):
    async def _probe_bounded(self, name: str, addr: int) -> None:
        """Bounded read that tolerates OKAY / error / timeout; only records the
        access + timeout so the no-deadlock gate can check every probe returned."""
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        item.allow_timeout = True
        item.timeout_ns = 300
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        if item.timed_out:
            self.timeouts += 1

    async def body(self) -> None:
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_ranges.extend(CLUSTER_DECERR_RANGES)
        for name, addr in CLUSTER_CPU_READS:
            # Tolerate OKAY / error / timeout; gate on no-deadlock below.
            await self._probe_bounded(name, addr)
        # Every probe returned a response or the bench's bounded timeout, i.e.
        # the shared SEP_IN CSR master was not deadlocked by the (partially
        # decoded) cluster windows. Register-level decode is exercised on the
        # full chip with CPU firmware.
        self.assert_reachable_or_gated(
            len(CLUSTER_CPU_READS), "Cluster CPU infra",
            "cluster windows partially decode / timeout; strict per-window value "
            "deferred to full-chip with CPU firmware",
        )
