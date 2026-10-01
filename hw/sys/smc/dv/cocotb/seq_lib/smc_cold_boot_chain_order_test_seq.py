# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cold boot chain ordering on one timeline: power-good, fuse sense, cluster release, first fetch.

``cpu.adoc`` (Memory Repair, Boot Sequence Integration) orders the cold boot:
power-on reset deasserts and eFuse sensing begins, ``smc_fuse_sense_done_o``
triggers repair, MBIST follows, and "the CPU cluster reset releases after both
repair and MBIST complete"; ``rom.adoc`` pins the cold-reset CPU vector at
``0xC004_0000``; ``cpu.adoc`` (CPU AXI Isolation) states the boundary
"self-isolates on cold boot, releasing only once SRAM initialization completes
and the cores and uncore are out of reset".

A second cold reset is driven through the reset agent (power-good dropped and
restored, cold pin asserted and released) while a monitor samples every
``clk_smc_i`` edge and records the first cycle at which each boundary
observable reaches its boot level:

* ``powergood_stable_o`` = 1, ``smc_fuse_sense_done_o`` = 1, ``smc_init_mem_done_o`` = 1,
  core 0 ``tb_cpu_core_reset_n`` = 1, cluster ``tb_cpu_cluster_isolate`` = 0,
  and the first retired hart-0 instruction with its PC, taken from
  ``tb_cpu_trace_valid_unmasked`` / ``tb_cpu_trace_pc_unmasked``: the retire
  record without the core-reset mask the other trace probes carry, so a retire
  stamped while the core reset is still asserted is seen and fails the
  ordering compare instead of being hidden by the probe. On a four-state
  simulator the unmasked record is X until the core has run; an unresolvable
  sample is not a retire.

Every observable is first required at its reset level, so each recorded rise
is a bring-up event of this reset and not a stale level. The ordering asserts
are strict inequalities between those cycle stamps; the first fetch PC is
compared against the specification's vector, not against the CPU_CTRL reset
value the DUT reads back.

What this bench cannot show is named and left open: ``smc_disable_sram_auto_init_i``
is tied high in ``tb_top`` so the automatic SRAM zeroing never runs
(``smc_init_mem_done_o`` rises as soon as the cluster reset releases), the repair
and MBIST done inputs are tied high (no repair engine to observe), and the
uncore reset has no separate probe.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_reset_item import SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase

# rom.adoc: "The cold-reset CPU vector is 0xC004_0000".
SPEC_ROM_RESET_VECTOR = 0xC004_0000
# Cycles the cold pin is held asserted after power-good returns, mirroring the
# bring-up in smc_base_test (10 clk_ref_i cycles).
POWERGOOD_TO_COLD_RELEASE_REF_CYCLES = 10
# The boot chain from cold release to first fetch is a few thousand SMC
# clocks (fuse sense, 255-cycle cold extender, cluster reset release); the
# monitor gives up, and the test fails, well beyond that.
FIRST_FETCH_BOUND_SMC_CYCLES = 60_000
RELEASE_BOUND_REF_CYCLES = 2000
# Bound for every observable to reach its reset level once the cold pin is low.
RESET_LEVEL_BOUND_SMC_CYCLES = 4000

# name -> (tb_top signal, boot level)
_BOOT_EVENTS = {
    "powergood_stable": ("powergood_stable_o", 1),
    "fuse_sense_done": ("smc_fuse_sense_done_o", 1),
    "init_mem_done": ("smc_init_mem_done_o", 1),
    "core_reset_release": ("tb_cpu_core_reset_n", 1),
    "isolate_release": ("tb_cpu_cluster_isolate", 0),
}


class smc_cold_boot_chain_order_test_seq(SmcResetSeqBase):
    """Cold reset with the boot-chain observables stamped on one clk_smc_i timeline."""

    def __init__(self, name: str = "smc_cold_boot_chain_order_test_seq") -> None:
        super().__init__(name)
        self.stamps: dict[str, int] = {}
        self.first_fetch_cycle: int | None = None
        self.first_fetch_pc: int | None = None
        self.reset_levels_seen = False
        self.cycle = 0

    @staticmethod
    def _bit(dut, name: str) -> int:
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is not resolvable: {value}"
        return int(value)

    @staticmethod
    def _retire_seen(dut) -> bool:
        """Unmasked retire valid; X (a four-state run before the core has run) is not a retire."""
        value = dut.tb_cpu_trace_valid_unmasked.value
        return bool(value.is_resolvable and int(value))

    async def _await_reset_levels(self, dut) -> None:
        """Every boot observable must first sit at its reset level."""
        for _ in range(RESET_LEVEL_BOUND_SMC_CYCLES):
            levels = {n: self._bit(dut, sig) for n, (sig, _lvl) in _BOOT_EVENTS.items()}
            if all(levels[n] != lvl for n, (_sig, lvl) in _BOOT_EVENTS.items()):
                self.reset_levels_seen = True
                return
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            "not every boot observable reached its reset level while the cold pin was held: "
            + ", ".join(f"{n}={self._bit(dut, sig)}" for n, (sig, _lvl) in _BOOT_EVENTS.items())
        )

    async def _monitor(self, dut) -> None:
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.cycle += 1
            for name, (sig, level) in _BOOT_EVENTS.items():
                if name not in self.stamps and self._bit(dut, sig) == level:
                    self.stamps[name] = self.cycle
            if self.first_fetch_cycle is None and self._retire_seen(dut):
                self.first_fetch_cycle = self.cycle
                self.first_fetch_pc = int(dut.tb_cpu_trace_pc_unmasked.value)

    async def body(self) -> None:
        dut = cocotb.top
        await self._send(SmcResetOp.SAMPLE)

        await self._send(SmcResetOp.POWERGOOD_LO)
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "COLD_ASSERTED",
            expect_powergood_stable=0,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._await_reset_levels(dut)

        monitor = cocotb.start_soon(self._monitor(dut))
        try:
            await self._send(SmcResetOp.POWERGOOD_HI)
            for _ in range(POWERGOOD_TO_COLD_RELEASE_REF_CYCLES):
                await RisingEdge(dut.clk_ref_i)
            await self._send(SmcResetOp.COLD_RST_HI)
            await self._wait_released("COLD_RELEASED", bound=RELEASE_BOUND_REF_CYCLES)
            for _ in range(FIRST_FETCH_BOUND_SMC_CYCLES):
                if self.first_fetch_cycle is not None and len(self.stamps) == len(_BOOT_EVENTS):
                    break
                await RisingEdge(dut.clk_smc_i)
        finally:
            monitor.cancel()

        missing = [n for n in _BOOT_EVENTS if n not in self.stamps]
        assert not missing, (
            f"boot observables never reached their boot level within {FIRST_FETCH_BOUND_SMC_CYCLES} "
            f"clk_smc_i cycles of the cold release: {missing}; stamps so far {self.stamps}"
        )
        assert self.first_fetch_cycle is not None, (
            f"hart 0 retired no instruction within {FIRST_FETCH_BOUND_SMC_CYCLES} clk_smc_i cycles "
            f"of the cold release; stamps {self.stamps}"
        )
        s = self.stamps
        assert s["powergood_stable"] < s["fuse_sense_done"], (
            f"fuse sense completed (cycle {s['fuse_sense_done']}) before power-good was stable "
            f"(cycle {s['powergood_stable']})"
        )
        assert s["fuse_sense_done"] < s["core_reset_release"], (
            f"core reset released (cycle {s['core_reset_release']}) before fuse sense completed "
            f"(cycle {s['fuse_sense_done']})"
        )
        # The retire stamp comes from the unmasked trace probe, so this compare
        # is between two independently sampled events and can fail.
        assert s["core_reset_release"] <= self.first_fetch_cycle, (
            f"hart 0 retired an instruction (cycle {self.first_fetch_cycle}) before its reset was "
            f"released (cycle {s['core_reset_release']})"
        )
        pc = self.first_fetch_pc & 0xFFFF_FFFF_FFFF_FF
        assert pc == SPEC_ROM_RESET_VECTOR, (
            f"first retired PC 0x{pc:x} is not the cold-reset ROM vector 0x{SPEC_ROM_RESET_VECTOR:x}"
        )
        assert s["isolate_release"] > s["init_mem_done"], (
            f"cluster isolation released (cycle {s['isolate_release']}) no later than "
            f"smc_init_mem_done_o rose (cycle {s['init_mem_done']})"
        )
        assert s["isolate_release"] > s["core_reset_release"], (
            f"cluster isolation released (cycle {s['isolate_release']}) no later than the core "
            f"reset (cycle {s['core_reset_release']})"
        )

        cocotb.log.info(
            "CHK-COLD-BOOT-ORDER: clk_smc_i cycle stamps after power-good return: "
            "powergood_stable=%d < fuse_sense_done=%d < core_reset_release=%d <= first_fetch=%d "
            "(PC 0x%x == ROM vector 0x%x); init_mem_done=%d",
            s["powergood_stable"],
            s["fuse_sense_done"],
            s["core_reset_release"],
            self.first_fetch_cycle,
            pc,
            SPEC_ROM_RESET_VECTOR,
            s["init_mem_done"],
        )
        cocotb.log.info(
            "CHK-COLD-BOOT-FIRST-FETCH-AT-ROM-VECTOR: hart 0 first retired PC 0x%x at cycle %d, "
            "%d cycle(s) after its reset released",
            pc,
            self.first_fetch_cycle,
            self.first_fetch_cycle - s["core_reset_release"],
        )
        cocotb.log.info(
            "CHK-CLUSTER-SELF-ISOLATED-AT-COLD-BOOT: tb_cpu_cluster_isolate read 1 while the cold "
            "pin was held and released at cycle %d, after smc_init_mem_done_o (cycle %d) and the core "
            "reset release (cycle %d)",
            s["isolate_release"],
            s["init_mem_done"],
            s["core_reset_release"],
        )
        cocotb.log.info(
            "CHK-COLD-BOOT-NOT-CLOSED: sram-auto-init-runs (smc_disable_sram_auto_init_i tied 1 in "
            "tb_top, smc_init_mem_done_o rose %d cycle(s) after core reset release), "
            "repair-triggered-by-fuse-sense-done and the repair/MBIST steps (mem_repair_done_i / "
            "mbist_done_i tied 1, no engine to observe), release-requires-uncore-out-of-reset (no "
            "separate uncore reset probe)",
            s["init_mem_done"] - s["core_reset_release"],
        )
        for line in self._timeout_paths:
            cocotb.log.info("CHK-TIMEOUT-PATHS: %s", line)
