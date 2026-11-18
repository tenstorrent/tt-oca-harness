# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The system inbound filter clock is gated while SYS_IN is idle and runs under traffic.

Spec source: fabric.adoc Fabric Topology ("The system AXI input passes the inbound traffic
filter, whose clock can be gated while the port is idle").
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, with_timeout

from .smc_addr_map import (
    CG_HYST_MASK,
    CG_HYST_SHIFT,
    CLOCK_GATE_CONTROL,
    CLOCK_GATE_CONTROL_RESET,
    FILTER_IB_AXI_CG_EN,
    REGION_SIZE_RESET,
    smc_addr,
)
from .smc_fabric_limit_probe_utils import read_item, start_group, verify_items
from .smc_fabric_limit_seq_base import GROUP_BOUND_NS, SmcFabricLimitSeqBase

HYST_CYCLES = 8
# Idle cycles the gate is given to close after the last SYS_IN handshake: the hysteresis
# plus the gater's own reload and countdown latency, well inside one hundred rises.
GATE_OFF_BOUND_CYCLES = 128
IDLE_WINDOW_CYCLES = 256
WAKE_BOUND_CYCLES = 256
REGION_SIZE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")


class smc_sys_in_filter_idle_clock_gate_test_seq(SmcFabricLimitSeqBase):
    """Idle window with the filter clock stopped, a SYS_IN read that wakes it, idle again."""

    def __init__(self, name: str = "smc_sys_in_filter_idle_clock_gate_test_seq") -> None:
        super().__init__(name)
        self.cg_word = 0

    async def body(self) -> None:
        await self._setup(seed_spm=False)
        try:
            await self._step_gate()
        finally:
            await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, self.cg_word, 8)
            await self.csr_read(
                "CLOCK_GATE_CONTROL_RESTORE_RB", CLOCK_GATE_CONTROL, expected=self.cg_word, length=8
            )
            await self._teardown()

    @staticmethod
    def _bit(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z"
        return int(value)

    async def _sys_read(self, label: str) -> None:
        items = [read_item(label, REGION_SIZE_ADDR, REGION_SIZE_RESET, 8)]
        task = start_group(label, items, self._sequencer("SYS"))
        await with_timeout(task, GROUP_BOUND_NS, "ns")
        self.accesses += 1
        self.waits.append(f"{label} (SYS) bound {GROUP_BOUND_NS} ns, answered")
        verify_items(label, items)

    async def _wait_gate_off(self, label: str) -> int:
        """Rises until `tb_sys_in_filter_clk_active` reads 0, bounded."""
        clk = cocotb.top.clk_smc_i
        for n in range(GATE_OFF_BOUND_CYCLES):
            await RisingEdge(clk)
            await ReadOnly()
            if self._bit("tb_sys_in_filter_clk_active") == 0:
                self.waits.append(
                    f"{label} gate off after {n + 1} rises (bound {GATE_OFF_BOUND_CYCLES})"
                )
                return n + 1
        raise AssertionError(
            f"{label}: tb_sys_in_filter_clk_active still 1 after {GATE_OFF_BOUND_CYCLES} rises "
            f"with bus_active={self._bit('tb_sys_in_filter_bus_active')}"
        )

    async def _idle_window(self) -> tuple[int, int]:
        """Samples of the idle window with the clock active, and with the bus active."""
        clk = cocotb.top.clk_smc_i
        active = busy = 0
        for _ in range(IDLE_WINDOW_CYCLES):
            await RisingEdge(clk)
            await ReadOnly()
            active += self._bit("tb_sys_in_filter_clk_active")
            busy += self._bit("tb_sys_in_filter_bus_active")
        return active, busy

    async def _wake_watch(self, done) -> dict[str, int | None]:
        """Cycles of the first SYS_IN ARVALID, of the AR handshake at the port, of the
        clock-active rise, of the AR handshake into the filter and of the R handshake."""
        clk = cocotb.top.clk_smc_i
        seen: dict[str, int | None] = {
            "arvalid": None,
            "port_ar_hs": None,
            "active": None,
            "filter_ar_hs": None,
            "r_hs": None,
        }
        for cycle in range(1, WAKE_BOUND_CYCLES + 1):
            await RisingEdge(clk)
            await ReadOnly()
            arvalid = self._bit("sys_axi_arvalid")
            if arvalid and seen["arvalid"] is None:
                seen["arvalid"] = cycle
            if arvalid and self._bit("sys_axi_arready") and seen["port_ar_hs"] is None:
                seen["port_ar_hs"] = cycle
            if self._bit("tb_sys_in_filter_clk_active") and seen["active"] is None:
                seen["active"] = cycle
            if (
                self._bit("tb_sys_in_filter_arvalid")
                and self._bit("tb_sys_in_filter_arready")
                and seen["filter_ar_hs"] is None
            ):
                seen["filter_ar_hs"] = cycle
            if self._bit("sys_axi_rvalid") and self._bit("sys_axi_rready") and seen["r_hs"] is None:
                seen["r_hs"] = cycle
            if done.done() and seen["r_hs"] is not None:
                break
        return seen

    async def _step_gate(self) -> None:
        self.cg_word = await self.csr_read(
            "CLOCK_GATE_CONTROL_BASELINE", CLOCK_GATE_CONTROL, length=8
        )
        assert self.cg_word == CLOCK_GATE_CONTROL_RESET, (
            f"CLOCK_GATE_CONTROL reads 0x{self.cg_word:X}, want reset 0x{CLOCK_GATE_CONTROL_RESET:X}"
        )
        programmed = (
            (self.cg_word & ~CG_HYST_MASK) | FILTER_IB_AXI_CG_EN | (HYST_CYCLES << CG_HYST_SHIFT)
        )
        await self.csr_write("CLOCK_GATE_CONTROL_IB_CG", CLOCK_GATE_CONTROL, programmed, length=8)
        await self.csr_read("CLOCK_GATE_CONTROL_IB_CG_RB", CLOCK_GATE_CONTROL, programmed, length=8)
        active_before = self._bit("tb_sys_in_filter_clk_active")

        await self._sys_read("SYS_READ_ADMIT")
        off_after = await self._wait_gate_off("after_admitting_read")
        idle_active, idle_busy = await self._idle_window()

        wake_items = [read_item("SYS_READ_WAKE", REGION_SIZE_ADDR, REGION_SIZE_RESET, 8)]
        task = start_group("SYS_READ_WAKE", wake_items, self._sequencer("SYS"))
        wake = await self._wake_watch(task)
        await with_timeout(task, GROUP_BOUND_NS, "ns")
        self.accesses += 1
        self.waits.append(f"SYS_READ_WAKE (SYS) bound {GROUP_BOUND_NS} ns, answered")
        verify_items("SYS_READ_WAKE", wake_items)
        off_again = await self._wait_gate_off("after_wake_read")
        idle2_active, idle2_busy = await self._idle_window()

        woke_before_hs = (
            wake["arvalid"] is not None
            and wake["active"] is not None
            and wake["filter_ar_hs"] is not None
            and wake["r_hs"] is not None
            and wake["arvalid"] < wake["active"] <= wake["filter_ar_hs"]
        )
        self.check(
            "CHK-SYS-IN-FILTER-CLK-IDLE-GATED",
            idle_active == 0
            and idle_busy == 0
            and idle2_active == 0
            and idle2_busy == 0
            and woke_before_hs,
            f"CLOCK_GATE_CONTROL 0x{programmed:X} (FILTER_IB_AXI_CG_EN, hysteresis {HYST_CYCLES}; "
            f"clk_active {active_before} before the first read): after an admitted SYS_IN read "
            f"tb_sys_in_filter_clk_active fell within {off_after} rises and read 0 on "
            f"{IDLE_WINDOW_CYCLES - idle_active} of {IDLE_WINDOW_CYCLES} idle samples "
            f"(bus_active 1 on {idle_busy}); a SYS_IN REGION_SIZE read then raised ARVALID at "
            f"cycle {wake['arvalid']} (accepted into the port's register slice at cycle "
            f"{wake['port_ar_hs']}), clk_active rose at cycle {wake['active']}, the filter "
            f"accepted the AR at cycle {wake['filter_ar_hs']} and the R handshake was at cycle "
            f"{wake['r_hs']} with 0x{REGION_SIZE_RESET:X}; the gate closed again within "
            f"{off_again} rises and "
            f"read 0 on {IDLE_WINDOW_CYCLES - idle2_active} of {IDLE_WINDOW_CYCLES} samples "
            f"(bus_active 1 on {idle2_busy})",
        )
