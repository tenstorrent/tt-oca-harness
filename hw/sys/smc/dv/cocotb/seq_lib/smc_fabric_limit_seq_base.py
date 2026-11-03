# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bring-up, hold-and-measure and teardown of the fabric limit leaves.

Spec source: fabric.adoc SMC Fabric Transaction Limits.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fabric_limit_probe_utils import (
    HeldRun,
    OutstandingProbe,
    hold_rready,
    read_item,
    release_rready,
    start_group,
    verify_items,
    wait_withheld,
)
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
GROUP_BOUND_NS = 100_000
WATCH_JOIN_BOUND_NS = 1_000
# Consecutive cycles the next AR must stay presented and withheld at the saturated count
# before the hold is released; the number of rises a hold may take to reach that.
WITHHELD_STREAK = 64
WITHHELD_BOUND_CYCLES = 4_000
INBOUND_PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
OUTSIDE_ADDR = 0x8000_0000
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x8_0000
SPM_WORDS = 16


def spm_addr(i: int) -> int:
    return SPM_BASE + 8 * i


def spm_word(i: int) -> int:
    return 0xF1B0_0000_0000_0000 | (i << 16) | 0x5A5A


class SmcFabricLimitSeqBase(SmcCsrSeq):
    """SEP_IN CSR sequence with probes on the fabric limiters and an RREADY hold."""

    #: Bench probe prefixes this leaf samples, besides the SEP_IN port itself.
    PROBES: tuple[tuple[str, dict], ...] = ()

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.probes: dict[str, OutstandingProbe] = {}
        self._watchers: list = []
        self._fails: list[str] = []
        self._chk_lines: list[str] = []
        self.waits: list[str] = []
        self.fuse_state = "not waited"

    # ---- bring-up and teardown --------------------------------------------------------------

    def _sequencer(self, port: str):
        return {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
        }[port].sequencer

    def _agent(self, port: str):
        return {"SEP": self.env.sys_axi_agent, "SYS": self.env.sys_in_axi_agent}[port]

    def _start_probes(self) -> None:
        dut = cocotb.top
        self.probes["s_axi"] = OutstandingProbe(dut, "s_axi", with_id=True)
        for prefix, kwargs in self.PROBES:
            self.probes[prefix] = OutstandingProbe(dut, prefix, **kwargs)
        self._watchers = [cocotb.start_soon(p.run()) for p in self.probes.values()]

    async def _stop_probes(self) -> None:
        for probe in self.probes.values():
            probe.stop = True
        await RisingEdge(cocotb.top.clk_smc_i)
        for task in self._watchers:
            await with_timeout(task, WATCH_JOIN_BOUND_NS, "ns")
        self.waits.append(f"probe_join bound {WATCH_JOIN_BOUND_NS} ns, all joined")

    async def _setup(self, seed_spm: bool = True) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.waits.append(
            f"wait_fuse_sense_done bound {FUSE_WAIT_BOUND_SMC_CYCLES} clk_smc_i rises, "
            f"last {self.fuse_state}"
        )
        if seed_spm:
            for i in range(SPM_WORDS):
                await self.csr_write(f"SPMW_{i}_SEED", spm_addr(i), spm_word(i), length=8)
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, INBOUND_PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_PASS_ALL_RB",
            INBOUND0_FILTER_CONFIG,
            expected=PASS_ALL_CONFIG,
            length=8,
        )
        self._start_probes()

    async def _teardown(self) -> None:
        for port in ("SEP", "SYS"):
            release_rready(self._agent(port))
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        await self._stop_probes()

    # ---- stimulus builders ------------------------------------------------------------------

    def decerr_reads(self, label: str, count: int, ids: list[int | None]) -> list[SmcSysAxiItem]:
        """`count` reads of the outside-window page, one per entry of `ids`."""
        assert len(ids) == count
        items = []
        for i, axi_id in enumerate(ids):
            addr = OUTSIDE_ADDR + 8 * i
            self.env.axi_monitor.expected_decerr_addrs.add(addr)
            items.append(read_item(f"{label}_{i}", addr, None, axi_id=axi_id, decerr=True))
        return items

    @staticmethod
    def spm_reads(
        label: str, count: int, axi_id: int | None, first: int = 0
    ) -> list[SmcSysAxiItem]:
        return [
            read_item(f"{label}_{k}", spm_addr(first + k), spm_word(first + k), 8, axi_id)
            for k in range(count)
        ]

    # ---- runs -------------------------------------------------------------------------------

    async def run_free(self, name: str, items: list[SmcSysAxiItem], port: str = "SEP") -> None:
        """Positive control: the same group with RREADY free; every member answers."""
        for p in self.probes.values():
            p.reset_counts()
        task = start_group(name, items, self._sequencer(port))
        await with_timeout(task, GROUP_BOUND_NS, "ns")
        self.accesses += len(items)
        self.waits.append(f"{name} ({port}) bound {GROUP_BOUND_NS} ns, all answered")
        verify_items(name, items)

    async def run_held(
        self,
        name: str,
        items: list[SmcSysAxiItem],
        probe: str,
        port: str = "SEP",
    ) -> HeldRun:
        """Issue `items` with RREADY held low until `probe` withholds an AR for the streak.

        The hold is released after the streak; the group then completes and every member
        is verified. The returned record carries the saturated count and the first
        handshakes after the release.
        """
        lim = self.probes[probe]
        s_axi = self.probes["s_axi"]
        for p in self.probes.values():
            p.reset_counts()
        hold_rready(self._agent(port))
        task = start_group(name, items, self._sequencer(port))
        try:
            release_cycle = await wait_withheld(lim, WITHHELD_STREAK, WITHHELD_BOUND_CYCLES)
        finally:
            release_rready(self._agent(port))
        run = HeldRun(lim, s_axi, release_cycle)
        await with_timeout(task, GROUP_BOUND_NS, "ns")
        self.accesses += len(items)
        self.waits.append(
            f"{name} ({port}) withheld streak {WITHHELD_STREAK} within "
            f"{WITHHELD_BOUND_CYCLES} rises, then bound {GROUP_BOUND_NS} ns, all answered"
        )
        verify_items(name, items)
        run.close(lim, s_axi)
        return run

    # ---- verdicts ---------------------------------------------------------------------------

    def check(self, token: str, ok: bool, text: str) -> None:
        """Log `token` as PASS or FAIL; a FAIL is raised at the end of the run."""
        if ok:
            cocotb.log.info("%s: %s", token, text)
        else:
            cocotb.log.error("%s FAIL: %s", token, text)
            self._fails.append(f"{token} FAIL: {text}")
        self._chk_lines.append(f"{token} {'PASS' if ok else 'FAIL'} @ {int(get_sim_time('ns'))} ns")

    @staticmethod
    def require(token: str, ok: bool, text: str) -> None:
        """An invariant of `token` that holds whatever number the limit measures; fails at once."""
        assert ok, f"{token} FAIL: {text}"

    def raise_fails(self) -> None:
        """Raise the collected failures as one line, so the runner's first-line match sees all."""
        assert not self._fails, " | ".join(self._fails)

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d AXI accesses each bounded by the driver timeout "
            "(allow_timeout False), all answered; own waits: %s; checks: %s",
            self.accesses,
            "; ".join(self.waits),
            ", ".join(self._chk_lines),
        )
