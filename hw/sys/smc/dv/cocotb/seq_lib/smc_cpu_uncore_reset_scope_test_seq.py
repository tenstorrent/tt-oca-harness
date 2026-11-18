# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A software uncore reset holds every core on its own edge and keeps the request up.

cpu.adoc, "Reset and Boot": "An uncore reset also holds every core in reset, on the
same clock edge, so no core keeps coherence state across a reset of the system bus it
depends on."

cpu.adoc, "Drain Handshake": "The cluster raises `drained_o`, and the control logic
applies the uncore reset, holding every core in reset with it. `isolate_req_i` stays
high until the uncore reset bit is set again. The boundary then reconnects."

A sampler records `tb_cpu_uncore_reset_n`, `tb_cpu_core_resets_n`, `tb_cpu_isolate_req`
and `tb_cpu_cluster_isolate` on every clk_smc_i rise. With the fabric idle and
`RESET_TIMEOUT` in force mode, the uncore reset bit is cleared with every core released:
the drain applies the reset (`reset_timeout` 0), the edge on which the uncore reset
reads 0 is the edge on which all four core resets read 0, and no core reset reads 0
earlier. The bit stays clear for 2000 rises after
`reset_applied`: `isolate_req` and `tb_cpu_cluster_isolate` read 1 on every one of
them. The bit is then set again: `isolate_req` falls only after that write and within
64 rises of it completing, the boundary de-isolates after the request falls, and no core
reset releases before the uncore reset.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_cpu_isolate_flush_test_seq import (
    BOOT_BOUND,
    CORE_RESET_N,
    RESET_CTRL,
    RESET_TIMEOUT,
    STATE_BOUND,
    TIMEOUT_FORCE,
    UNCORE_RESET_N,
    _CpuIsolateFlushSeq,
)

HOLD_SAMPLES = 2000
RELEASE_BOUND = 64
CORES_RELEASED = 0xF
(_UNC, _CORES, _REQ, _ISO, _APPLIED, _DRAINED, _TIMEOUT) = range(7)
_PROBES = (
    "tb_cpu_uncore_reset_n",
    "tb_cpu_core_resets_n",
    "tb_cpu_isolate_req",
    "tb_cpu_cluster_isolate",
    "tb_cpu_reset_applied",
    "tb_cpu_drained",
    "tb_cpu_reset_timeout",
)


class smc_cpu_uncore_reset_scope_test_seq(_CpuIsolateFlushSeq):
    """Per-edge record of the core and uncore resets around a held uncore reset."""

    def __init__(self, name: str = "smc_cpu_uncore_reset_scope_test_seq") -> None:
        super().__init__(name)
        self.rec: list[tuple[int, ...]] = []
        self.fall_edge: int | None = None
        self.held_samples = 0

    async def _sampler(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.rec.append(tuple(self._value(getattr(dut, p), p) for p in _PROBES))

    async def _wait_recorded(self, count: int, label: str) -> None:
        dut = cocotb.top
        for _ in range(count + STATE_BOUND):
            if len(self.rec) >= count:
                return
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(f"{label}: the sampler recorded {len(self.rec)} edges, not {count}")

    def _first(self, start: int, test, label: str) -> int:
        for edge in range(start, len(self.rec)):
            if test(self.rec[edge]):
                return edge
        raise AssertionError(f"{label}: no recorded edge from {start} satisfies it")

    async def body(self) -> None:
        await self._wait_eq("tb_cpu_cluster_isolate", 0, BOOT_BOUND, "CPU cluster boundary at boot")
        reset_ctrl = await self.csr_read("RESET_CTRL_SAVE", RESET_CTRL, length=8)
        assert reset_ctrl & UNCORE_RESET_N and reset_ctrl & CORE_RESET_N == CORE_RESET_N, (
            f"RESET_CTRL 0x{reset_ctrl:x}: the uncore and every core are expected released"
        )
        await self.csr_write("RESET_TIMEOUT_FORCE", RESET_TIMEOUT, TIMEOUT_FORCE, length=8)
        sampler = cocotb.start_soon(self._sampler())
        try:
            await RisingEdge(cocotb.top.clk_smc_i)
            issue = len(self.rec)
            await self.csr_write(
                "RESET_CTRL_UNCORE_LOW", RESET_CTRL, reset_ctrl & ~UNCORE_RESET_N, length=8
            )
            await self._wait_eq("tb_cpu_uncore_reset_n", 0, STATE_BOUND, "uncore reset asserted")
            await self._wait_eq("tb_cpu_reset_applied", 1, STATE_BOUND, "uncore reset applied")
            rec = self.rec
            fall = self._first(issue, lambda t: t[_UNC] == 0, "uncore reset fall")
            early = [e for e in range(issue, fall) if rec[e][_CORES] != CORES_RELEASED]
            assert fall > issue and not early, (
                f"a core reset output fell before the uncore reset (uncore fell at edge {fall}, "
                f"write issued at edge {issue}): core_resets_n at edges {early[:8]} read "
                f"{[hex(rec[e][_CORES]) for e in early[:8]]}"
            )
            assert rec[fall][_CORES] == 0, (
                f"on the edge the uncore reset read 0 (edge {fall}) tb_cpu_core_resets_n read "
                f"0x{rec[fall][_CORES]:x}, not 0x0: a core was not held with the uncore"
            )
            assert (rec[fall][_DRAINED], rec[fall][_TIMEOUT]) == (1, 0), (
                f"at the uncore fall edge {fall} drained read {rec[fall][_DRAINED]} and "
                f"reset_timeout {rec[fall][_TIMEOUT]}: the reset was not applied by the drain"
            )
            self.fall_edge = fall
            cocotb.log.info(
                "CHK-UNCORE-HOLDS-ALL-CORES-SAME-EDGE: tb_cpu_uncore_reset_n read 1 on edges "
                "%d..%d after the RESET_CTRL write and 0 at edge %d; tb_cpu_core_resets_n read "
                "0xf on every one of those %d edges and 0x0 at edge %d: all four cores fell on "
                "the uncore's edge and none earlier (applied by the drain: drained %d, "
                "reset_timeout %d at that edge)",
                issue,
                fall - 1,
                fall,
                fall - issue,
                fall,
                rec[fall][_DRAINED],
                rec[fall][_TIMEOUT],
            )

            start = len(rec)
            await self._wait_recorded(start + HOLD_SAMPLES, "uncore hold window")
            window = rec[start : start + HOLD_SAMPLES]
            bad = [
                (start + i, t)
                for i, t in enumerate(window)
                if (t[_REQ], t[_ISO], t[_UNC], t[_CORES], t[_APPLIED]) != (1, 1, 0, 0, 1)
            ]
            assert not bad, (
                f"the held uncore reset did not keep (isolate_req, cluster_isolate, "
                f"uncore_reset_n, core_resets_n, reset_applied) = (1, 1, 0, 0, 1) on every edge: "
                f"first {len(bad)} deviations {bad[:4]}"
            )
            self.held_samples = len(window)

            release_issue = len(rec)
            await self.csr_write("RESET_CTRL_RELEASE", RESET_CTRL, reset_ctrl, length=8)
            release_done = len(rec)
            await self._wait_eq("tb_cpu_isolate_req", 0, RELEASE_BOUND, "CPU isolate request")
            await self._wait_eq(
                "tb_cpu_cluster_isolate", 0, RELEASE_BOUND, "CPU cluster boundary de-isolated"
            )
            await self._wait_eq("tb_cpu_uncore_reset_n", 1, RELEASE_BOUND, "uncore reset released")
            await self._wait_eq(
                "tb_cpu_core_resets_n", CORES_RELEASED, RELEASE_BOUND, "core resets released"
            )
            req_fall = self._first(start, lambda t: t[_REQ] == 0, "isolate_req fall")
            iso_fall = self._first(start, lambda t: t[_ISO] == 0, "cluster_isolate fall")
            unc_rise = self._first(start, lambda t: t[_UNC] == 1, "uncore reset rise")
            core_rise = self._first(start, lambda t: t[_CORES] != 0, "first core reset release")
            assert req_fall > release_issue and req_fall - release_done <= RELEASE_BOUND, (
                f"isolate_req fell at edge {req_fall}; the release write was issued at edge "
                f"{release_issue} and completed at edge {release_done} (bound {RELEASE_BOUND})"
            )
            assert iso_fall >= req_fall, (
                f"tb_cpu_cluster_isolate fell at edge {iso_fall}, before isolate_req at {req_fall}"
            )
            assert core_rise >= unc_rise, (
                f"a core reset released at edge {core_rise} (core_resets_n "
                f"0x{rec[core_rise][_CORES]:x}), before the uncore at {unc_rise}"
            )
            cocotb.log.info(
                "CHK-ISOLATE-REQ-HELD-UNTIL-RELEASE: with the uncore bit clear, tb_cpu_isolate_req "
                "and tb_cpu_cluster_isolate read 1 on all %d edges %d..%d after reset_applied; "
                "isolate_req fell at edge %d, %d edges after the write setting the bit again "
                "was issued (edge %d) and %d after it completed (bound %d); the boundary "
                "de-isolated at edge %d, the uncore reset released at edge %d and the first "
                "core at edge %d",
                self.held_samples,
                start,
                start + HOLD_SAMPLES - 1,
                req_fall,
                req_fall - release_issue,
                release_issue,
                req_fall - release_done,
                RELEASE_BOUND,
                iso_fall,
                unc_rise,
                core_rise,
            )
            await self._wait_reset_released()
        finally:
            sampler.cancel()
        await self.csr_read(
            "RESET_TIMEOUT_RELEASED", RESET_TIMEOUT, length=8, expected=TIMEOUT_FORCE
        )
        await self.csr_write("RESET_TIMEOUT_CLEAR", RESET_TIMEOUT, 0, length=8)
        await self.csr_read("RESET_CTRL_RESTORED", RESET_CTRL, length=8, expected=reset_ctrl)
