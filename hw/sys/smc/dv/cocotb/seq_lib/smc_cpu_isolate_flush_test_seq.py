# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Timeout-forced CPU reset recovery across the two AXI isolates."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import cpu_ctrl_u32, smc_addr, smc_indexed_addr
from .smc_cpu_vip_utils import CPU_RESET_VECTOR_ROM
from .smc_output_fabric_vip_utils import output_fabric_pass_all_cfg_seq

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
RESET_VECTORS = tuple(
    smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", i) for i in range(4)
)
SCRATCH_0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
SCRATCH_1 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 1)
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SPM_SIZE = smc_addr("SMC_TOP_SPM_MEMORY_SIZE")

CORE0_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE0_RESET_N_N0_SCAN_bm")
CORE_RESET_N = sum(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{i}_RESET_N_N0_SCAN_bm") for i in range(4)
)
UNCORE_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
TIMEOUT_MODE = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")

RESET_VECTOR_SCRATCH = SPM_BASE
TIMEOUT_CYCLES = 64
TIMEOUT_FORCE = TIMEOUT_MODE | TIMEOUT_CYCLES

WEDGE_READS = 4
WEDGE_WRITES = 8
WEDGE_BYTES = 64
WEDGE_READ_BASE = SPM_BASE + 0x20_000
WEDGE_WRITE_ADDR = SPM_BASE + 0x21_000
RECOVERY_PROBE_ADDR = SPM_BASE + 0x22_000
WEDGE_READ_AXI_ID = 1
WEDGE_WRITE_AXI_ID = 5

# Mailboxes occupy the last cache line of the 1 MiB SPM, above the linked image,
# its four 1 KiB stacks, and its fixed 2 KiB heap.
PHASE_FLAG_ADDR = SPM_BASE + SPM_SIZE - 0x40
GO_FLAG_ADDR = PHASE_FLAG_ADDR + 8
PHASE2_MAGIC = 0x1501_C0DE
GO_READ_MAGIC = 0x1501_600D
GO_WRITE_MAGIC = 0x1501_600E

STATUS_PHASE1_READY = 0x1501_0001
STATUS_PHASE1_BROKE = 0x1501_DEAD
STATUS_PHASE2_DONE = 0x1501_0003
FW_PASS = 0xACAF_ACA1
FW_FAIL = 0xFFFF_FFFF

STATE_BOUND = 4_000
BOOT_BOUND = 200_000
FW_POLL_COUNT = 4_000
FW_POLL_CYCLES = 50
STABLE_WINDOW_CYCLES = 32


class _CpuIsolateFlushSeq(output_fabric_pass_all_cfg_seq):
    """Common bounded waits and reset/boot operations."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.contracts: set[str] = set()
        self.pending_axi_events: list[object] = []

    @staticmethod
    def _value(signal, label: str) -> int:
        value = signal.value
        if not value.is_resolvable:
            raise AssertionError(f"{label} is X/Z: {value}")
        return int(value)

    async def _wait_eq(self, signal_name: str, want: int, bound: int, label: str) -> int:
        dut = cocotb.top
        signal = getattr(dut, signal_name)
        last = None
        for cycle in range(bound + 1):
            value = signal.value
            last = int(value) if value.is_resolvable else None
            if last == want:
                cocotb.log.info("%s reached %d after %d clk_smc_i cycle(s)", label, want, cycle)
                return want
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label} did not reach {want} within {bound} clk_smc_i cycles "
            f"(last={'X/Z' if last is None else last})"
        )

    async def _wait_nonzero(self, signal_name: str, bound: int, label: str) -> int:
        dut = cocotb.top
        signal = getattr(dut, signal_name)
        last = None
        for cycle in range(bound + 1):
            value = signal.value
            last = int(value) if value.is_resolvable else None
            if last is not None and last != 0:
                cocotb.log.info("%s became 0x%x after %d clk_smc_i cycle(s)", label, last, cycle)
                return last
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label} stayed zero or X/Z for {bound} clk_smc_i cycles "
            f"(last={'X/Z' if last is None else last})"
        )

    async def _wait_at_least(
        self, signal_name: str, want: int, bound: int, label: str
    ) -> int:
        dut = cocotb.top
        signal = getattr(dut, signal_name)
        last = None
        for cycle in range(bound + 1):
            value = signal.value
            last = int(value) if value.is_resolvable else None
            if last is not None and last >= want:
                cocotb.log.info(
                    "%s reached 0x%x after %d clk_smc_i cycle(s)",
                    label,
                    last,
                    cycle,
                )
                return last
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label} did not reach {want} within {bound} clk_smc_i cycles "
            f"(last={'X/Z' if last is None else last})"
        )

    async def _hold_value(self, signal_name: str, want: int, cycles: int, label: str) -> None:
        dut = cocotb.top
        signal = getattr(dut, signal_name)
        for cycle in range(cycles):
            await RisingEdge(dut.clk_smc_i)
            got = self._value(signal, signal_name)
            assert got == want, (
                f"{label} did not remain {want} for its {cycles}-cycle stability window: "
                f"got {got} at window cycle {cycle + 1}"
            )
        cocotb.log.info("%s remained %d for %d-cycle stability window", label, want, cycles)

    async def _hold_nonzero(self, signal_name: str, cycles: int, label: str) -> None:
        dut = cocotb.top
        signal = getattr(dut, signal_name)
        for cycle in range(cycles):
            await RisingEdge(dut.clk_smc_i)
            got = self._value(signal, signal_name)
            assert got != 0, (
                f"{label} cleared during its {cycles}-cycle stability window "
                f"at window cycle {cycle + 1}"
            )
        cocotb.log.info("%s stayed nonzero for %d-cycle stability window", label, cycles)

    async def _wait_handshake(
        self,
        valid_name: str,
        ready_name: str,
        bound: int,
        label: str,
        *,
        last_name: str | None = None,
    ) -> None:
        dut = cocotb.top
        for cycle in range(1, bound + 1):
            await RisingEdge(dut.clk_smc_i)
            valid = self._value(getattr(dut, valid_name), valid_name)
            ready = self._value(getattr(dut, ready_name), ready_name)
            last = 1 if last_name is None else self._value(getattr(dut, last_name), last_name)
            if valid and ready and last:
                cocotb.log.info("%s handshook after %d clk_smc_i cycle(s)", label, cycle)
                return
        raise AssertionError(f"{label} did not handshake within {bound} clk_smc_i cycles")

    async def _wait_addr_handshake(
        self,
        valid_name: str,
        ready_name: str,
        addr_name: str,
        expected_addr: int,
        bound: int,
        label: str,
    ) -> None:
        dut = cocotb.top
        last_addr = None
        for cycle in range(1, bound + 1):
            await RisingEdge(dut.clk_smc_i)
            valid = self._value(getattr(dut, valid_name), valid_name)
            ready = self._value(getattr(dut, ready_name), ready_name)
            if valid and ready:
                last_addr = self._value(getattr(dut, addr_name), addr_name)
                if last_addr == expected_addr:
                    cocotb.log.info(
                        "%s accepted address 0x%x after %d clk_smc_i cycle(s)",
                        label,
                        expected_addr,
                        cycle,
                    )
                    return
        raise AssertionError(
            f"{label} did not accept 0x{expected_addr:x} within {bound} clk_smc_i cycles "
            f"(last accepted={'none' if last_addr is None else hex(last_addr)})"
        )

    async def _wait_counter_advance(
        self, signal_name: str, baseline: int, bound: int, label: str
    ) -> int:
        dut = cocotb.top
        signal = getattr(dut, signal_name)
        last = baseline
        for cycle in range(bound + 1):
            last = self._value(signal, signal_name)
            if last > baseline:
                cocotb.log.info(
                    "%s advanced 0x%x -> 0x%x after %d clk_smc_i cycle(s)",
                    label,
                    baseline,
                    last,
                    cycle,
                )
                return last
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label} did not advance beyond {baseline} within {bound} clk_smc_i cycles "
            f"(last={last})"
        )

    async def _wait_task(self, task, bound: int, label: str) -> None:
        dut = cocotb.top
        for _ in range(bound + 1):
            if task.done():
                await task
                cocotb.log.info("%s completed", label)
                return
            await RisingEdge(dut.clk_smc_i)
        task.cancel()
        raise AssertionError(f"{label} did not complete within {bound} clk_smc_i cycles")

    async def _wait_scratch(self, addr: int, want: int, label: str) -> int:
        last = None
        for poll in range(FW_POLL_COUNT):
            last = await self.csr_read(f"{label}_{poll}", addr, length=8)
            if last == FW_FAIL or (last & 0xFFFF_0000) == 0xBAD0_0000:
                raise AssertionError(f"{label}: firmware reported failure 0x{last:08x}")
            if last == want:
                cocotb.log.info("%s observed 0x%08x after %d poll(s)", label, want, poll + 1)
                return last
            if last == STATUS_PHASE1_BROKE:
                raise AssertionError(
                    f"{label}: phase-1 external access returned before reset (status=0x{last:08x})"
                )
            for _ in range(FW_POLL_CYCLES):
                await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: 0x{want:08x} not observed after {FW_POLL_COUNT} polls "
            f"(last={'none' if last is None else hex(last)})"
        )

    async def _program_vectors(self, vector: int, label: str) -> None:
        for hart, addr in enumerate(RESET_VECTORS):
            await self.csr_write(f"{label}_VECTOR{hart}", addr, vector, length=8)

    @staticmethod
    def _release_boot_stall() -> None:
        dut = cocotb.top
        mask = 1 << 57
        enable = int(dut.tb_gpio_ext_drive_en.value) | mask
        value = int(dut.tb_gpio_ext_drive_value.value) & ~mask
        dut.tb_gpio_ext_drive_en.value = enable
        dut.tb_gpio_ext_drive_value.value = value

    async def _request_forced_reset(self, reset_ctrl: int, *, pending_name: str) -> None:
        request = reset_ctrl & ~(CORE0_RESET_N | UNCORE_RESET_N)
        await self.csr_write("RESET_CTRL_CORE0_UNCORE_ASSERT", RESET_CTRL, request, length=8)
        await self._wait_eq("tb_cpu_isolate_req", 1, STATE_BOUND, "CPU isolate request")
        pending = self._value(getattr(cocotb.top, pending_name), pending_name)
        assert pending != 0, (
            f"{pending_name} cleared before RESET_TIMEOUT fired; the intended "
            f"drain wedge was not present"
        )
        assert self._value(cocotb.top.tb_cpu_drained, "tb_cpu_drained") == 0, (
            "CPU boundary reported drained while the wedged transaction was still pending"
        )
        await self._wait_eq("tb_cpu_reset_timeout", 1, STATE_BOUND, "RESET_TIMEOUT fired")
        await self._wait_eq("tb_cpu_reset_applied", 1, STATE_BOUND, "forced reset applied")
        await self._wait_eq("tb_cpu_uncore_reset_n", 0, STATE_BOUND, "uncore reset asserted")
        self.contracts.add("forced_reset")

    async def _wait_forced_drain(self, isolate_name: str, flush_name: str) -> None:
        await self._wait_eq("tb_cpu_drained", 1, STATE_BOUND, "CPU boundary drained")
        await self._wait_eq(isolate_name, 1, STATE_BOUND, f"{isolate_name} isolated")
        await self._wait_eq(flush_name, 1, STATE_BOUND, f"{flush_name} open")
        await self._hold_value(
            "tb_cpu_reset_timeout",
            1,
            STABLE_WINDOW_CYCLES,
            "RESET_TIMEOUT held through the active reset request",
        )
        self.contracts.add("drained_while_blocked")

    async def _release_reset(self, reset_ctrl: int) -> None:
        await self.csr_write("RESET_CTRL_RELEASE", RESET_CTRL, reset_ctrl, length=8)
        await self._wait_eq("tb_cpu_isolate_req", 0, STATE_BOUND, "CPU isolate request released")
        await self._wait_eq("tb_cpu_reset_timeout", 0, STATE_BOUND, "RESET_TIMEOUT cleared")
        await self._wait_eq("tb_cpu_uncore_reset_n", 1, STATE_BOUND, "uncore reset released")
        await self._wait_eq(
            "tb_cpu_cluster_isolate", 0, BOOT_BOUND, "CPU cluster boundary de-isolated"
        )

    async def _probe_front_port(self) -> None:
        await self.csr_read("FRONT_PORT_RECOVERY", RECOVERY_PROBE_ADDR, length=8)
        self.contracts.add("front_port_recovered")

class smc_cpu_l2_read_wedge_test_seq(_CpuIsolateFlushSeq):
    """Flush an L2 read drain while SEP_IN still refuses R responses."""

    async def body(self) -> None:
        dut = cocotb.top
        axi = self.env.sys_axi_agent.driver.axi
        assert axi is not None, "SEP_IN AXI event API is not ready after bring-up"

        await self._wait_eq("tb_cpu_cluster_isolate", 0, BOOT_BOUND, "CPU cluster boundary at boot")
        reset_ctrl = await self.csr_read("RESET_CTRL_SAVE", RESET_CTRL, length=8)
        await self.csr_write("RESET_TIMEOUT_FORCE", RESET_TIMEOUT, TIMEOUT_FORCE, length=8)

        dut.tb_sep_axi_r_hold.value = 1
        try:
            # Event API is intentional: these reads must remain pending while
            # ordinary RESET_CTRL accesses continue through the sequencer/checker.
            self.pending_axi_events.extend(
                axi.init_read(
                    address=WEDGE_READ_BASE + i * WEDGE_BYTES,
                    length=WEDGE_BYTES,
                    size=3,
                    id=WEDGE_READ_AXI_ID,
                )
                for i in range(WEDGE_READS)
            )
            await self._wait_nonzero("tb_cpu_l2_pending_ar", STATE_BOUND, "L2 pending AR count")
            await self._hold_nonzero(
                "tb_cpu_l2_pending_ar",
                STABLE_WINDOW_CYCLES,
                "L2 read wedge",
            )

            await self._request_forced_reset(
                reset_ctrl,
                pending_name="tb_cpu_l2_pending_ar",
            )
            await self._wait_forced_drain("tb_cpu_l2_isolated", "tb_cpu_l2_flush_active")
            await self._wait_eq(
                "tb_cpu_l2_pending_ar", 0, STATE_BOUND, "flushed L2 pending AR count"
            )

            await self._hold_value(
                "tb_cpu_l2_pending_ar",
                0,
                STABLE_WINDOW_CYCLES,
                "flushed L2 pending AR count",
            )
            # This response is buffered above the isolate, outside its
            # absorber. Keep that upstream path parked and prove a different
            # fabric master/ID can use the recovered L2 path.
            self.contracts.add("blocked_master_isolated")

            await self._release_reset(reset_ctrl)
            await self._wait_eq("tb_cpu_l2_flush_active", 0, STATE_BOUND, "L2 flush window closed")
            await self._wait_eq("tb_cpu_l2_isolated", 0, STATE_BOUND, "L2 isolate reopened")
            self.contracts.add("cluster_reopened")
            await self.csr_write("RESET_TIMEOUT_CLEAR", RESET_TIMEOUT, 0, length=8)
        except BaseException:
            dut.tb_sep_axi_r_hold.value = 0
            raise


class smc_cpu_l2_write_wedge_test_seq(_CpuIsolateFlushSeq):
    """Flush an L2 write drain while SEP_IN refuses B responses."""

    async def body(self) -> None:
        dut = cocotb.top
        axi = self.env.sys_axi_agent.driver.axi
        assert axi is not None, "SEP_IN AXI event API is not ready after bring-up"

        await self._wait_eq("tb_cpu_cluster_isolate", 0, BOOT_BOUND, "CPU cluster boundary at boot")
        reset_ctrl = await self.csr_read("RESET_CTRL_SAVE", RESET_CTRL, length=8)
        await self.csr_write("RESET_TIMEOUT_FORCE", RESET_TIMEOUT, TIMEOUT_FORCE, length=8)

        request_task = None
        dut.tb_sep_axi_b_hold.value = 1
        try:
            self.pending_axi_events.extend(
                axi.init_write(
                    address=WEDGE_WRITE_ADDR + i * WEDGE_BYTES,
                    data=bytes(range(WEDGE_BYTES)),
                    size=3,
                    id=WEDGE_WRITE_AXI_ID + i,
                )
                for i in range(WEDGE_WRITES)
            )
            await self._wait_at_least(
                "tb_cpu_l2_pending_aw",
                2,
                STATE_BOUND,
                "L2 pending AW count",
            )
            await self._wait_eq(
                "tb_cpu_l2_pending_w",
                0,
                STATE_BOUND,
                "L2 write data completed before B hold",
            )
            await self._hold_nonzero(
                "tb_cpu_l2_pending_aw",
                STABLE_WINDOW_CYCLES,
                "L2 write response wedge",
            )

            request = reset_ctrl & ~(CORE0_RESET_N | UNCORE_RESET_N)
            request_task = cocotb.start_soon(
                self.csr_write(
                    "RESET_CTRL_CORE0_UNCORE_ASSERT",
                    RESET_CTRL,
                    request,
                    length=8,
                )
            )
            await self._wait_eq("tb_cpu_isolate_req", 1, STATE_BOUND, "CPU isolate request")
            assert self._value(dut.tb_cpu_drained, "tb_cpu_drained") == 0, (
                "CPU boundary reported drained while L2 write responses were still pending"
            )
            await self._wait_eq("tb_cpu_reset_timeout", 1, STATE_BOUND, "RESET_TIMEOUT fired")
            await self._wait_eq("tb_cpu_reset_applied", 1, STATE_BOUND, "forced reset applied")
            await self._wait_eq("tb_cpu_uncore_reset_n", 0, STATE_BOUND, "uncore reset asserted")
            self.contracts.add("forced_reset")

            await self._wait_forced_drain("tb_cpu_l2_isolated", "tb_cpu_l2_flush_active")
            await self._wait_eq(
                "tb_cpu_l2_pending_aw", 0, STATE_BOUND, "flushed L2 pending AW count"
            )
            await self._wait_eq("tb_cpu_l2_pending_w", 0, STATE_BOUND, "flushed L2 pending W count")

            await self._hold_value(
                "tb_cpu_l2_pending_aw",
                0,
                STABLE_WINDOW_CYCLES,
                "flushed L2 pending AW count",
            )
            # B responses already buffered above the isolate are outside its
            # absorber. Keep that upstream path parked; releasing it after the
            # cluster reset can expose response metadata the reset invalidated.
            self.contracts.add("blocked_master_isolated")
        except BaseException:
            dut.tb_sep_axi_b_hold.value = 0
            if request_task is not None and not request_task.done():
                request_task.cancel()
            raise


class _CpuMmioWedgeSeq(_CpuIsolateFlushSeq):
    """Shared two-phase firmware flow for MMIO R/B response wedges."""

    go_magic = 0
    pending_name = ""
    other_pending_name = ""
    output_valid_name = ""
    output_ready_name = ""
    output_addr_name = ""
    output_count_name = ""
    flavor = ""

    async def _boot_phase1(self) -> int:
        plusargs = cocotb.plusargs or {}
        assert "smc_hold_cpu_boot" in plusargs, "MMIO wedge firmware requires +smc_hold_cpu_boot"
        image = plusargs.get("smc_scratch_ram_hex")
        assert image and str(image).endswith("mmio_wedge.ecc.hex"), (
            "MMIO wedge firmware requires staged +smc_scratch_ram_hex=mmio_wedge.ecc.hex"
        )

        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        reset_ctrl = await self.csr_read("RESET_CTRL_SAVE", RESET_CTRL, length=8)
        await self.csr_write("FW_STATUS0_CLEAR", SCRATCH_0, 0, length=8)
        await self.csr_write("FW_STATUS1_CLEAR", SCRATCH_1, 0, length=8)
        await self._program_vectors(RESET_VECTOR_SCRATCH, "PHASE1")
        await self.csr_write("RESET_TIMEOUT_FORCE", RESET_TIMEOUT, TIMEOUT_FORCE, length=8)
        await self.csr_write("RESET_CTRL_RELEASE_ALL", RESET_CTRL, reset_ctrl, length=8)

        self._release_boot_stall()
        await self._wait_eq("tb_fuse_reset_n", 1, BOOT_BOUND, "fuse reset released")
        await self._wait_eq("tb_rst_warm_smc_clk_n", 1, BOOT_BOUND, "warm reset domain released")
        await self._wait_eq(
            "tb_cpu_cluster_isolate", 0, BOOT_BOUND, "phase-1 CPU boundary de-isolated"
        )
        await self._wait_scratch(SCRATCH_1, STATUS_PHASE1_READY, "PHASE1_READY")
        return reset_ctrl

    async def _release_to_rom(self, reset_ctrl: int) -> None:
        await self._program_vectors(CPU_RESET_VECTOR_ROM, "ROM_RECOVERY")
        await self._release_reset(reset_ctrl)
        await self._wait_eq("tb_cpu_mmio_flush_active", 0, STATE_BOUND, "MMIO flush window closed")
        await self._wait_eq("tb_cpu_mmio_isolated", 0, STATE_BOUND, "MMIO de-isolated")
        await self._wait_eq("tb_cpu_l2_isolated", 0, STATE_BOUND, "L2 de-isolated")

    async def _boot_phase2(self, reset_ctrl: int) -> None:
        await self.csr_write("PHASE2_FLAG", PHASE_FLAG_ADDR, PHASE2_MAGIC, length=8)
        await self.csr_write("PHASE2_GO_CLEAR", GO_FLAG_ADDR, 0, length=8)
        await self.csr_write("FW_STATUS0_CLEAR_PHASE2", SCRATCH_0, 0, length=8)
        await self.csr_write("FW_STATUS1_CLEAR_PHASE2", SCRATCH_1, 0, length=8)
        await self._program_vectors(RESET_VECTOR_SCRATCH, "PHASE2")

        hold_cores = reset_ctrl & ~CORE_RESET_N
        await self.csr_write("PHASE2_HOLD_CORES", RESET_CTRL, hold_cores, length=8)
        await self._wait_eq("tb_cpu_isolate_req", 1, STATE_BOUND, "phase-2 reset request")
        await self._wait_eq("tb_cpu_drained", 1, STATE_BOUND, "phase-2 clean drain")
        await self._wait_eq("tb_cpu_reset_applied", 1, STATE_BOUND, "phase-2 core reset applied")
        await self._release_reset(reset_ctrl)

    async def body(self) -> None:
        dut = cocotb.top
        reset_ctrl = await self._boot_phase1()
        output_before = self._value(getattr(dut, self.output_count_name), self.output_count_name)
        dut.tb_output_axi_resp_hold.value = 1
        try:
            request_seen = cocotb.start_soon(
                self._wait_addr_handshake(
                    self.output_valid_name,
                    self.output_ready_name,
                    self.output_addr_name,
                    0xB000_0000,
                    BOOT_BOUND,
                    f"cluster MMIO {self.flavor}",
                )
            )
            await self.csr_write("PHASE1_GO", GO_FLAG_ADDR, self.go_magic, length=8)
            await request_seen
            await self._wait_nonzero(self.pending_name, STATE_BOUND, f"MMIO {self.flavor} count")
            if self.flavor == "write":
                # AW/B remains outstanding, but every W beat must already have
                # reached SYS_OUT; this is a response wedge, not a W wedge.
                await self._wait_eq(
                    "tb_cpu_mmio_pending_w",
                    0,
                    STATE_BOUND,
                    "MMIO write data completed before B hold",
                )
            await self._hold_nonzero(
                self.pending_name,
                STABLE_WINDOW_CYCLES,
                f"MMIO {self.flavor} wedge",
            )

            await self._request_forced_reset(
                reset_ctrl,
                pending_name=self.pending_name,
            )
            await self._wait_forced_drain("tb_cpu_mmio_isolated", "tb_cpu_mmio_flush_active")
            await self._wait_eq(self.pending_name, 0, STATE_BOUND, "flushed MMIO count")

            dut.tb_output_axi_resp_hold.value = 0
            await self._wait_counter_advance(
                self.output_count_name,
                output_before,
                STATE_BOUND,
                f"released stale SYS_OUT {self.flavor} response",
            )
            assert self._value(dut.tb_cpu_mmio_isolated, "tb_cpu_mmio_isolated") == 1, (
                "MMIO isolate reopened while the timeout-forced reset was still held"
            )
            await self._hold_value(
                self.pending_name,
                0,
                STABLE_WINDOW_CYCLES,
                "flushed MMIO pending count",
            )
            self.contracts.add("stale_response_absorbed")

            await self._release_to_rom(reset_ctrl)
            phase2_reads = self._value(dut.tb_output_axi_read_count, "tb_output_axi_read_count")
            await self._boot_phase2(reset_ctrl)
            await self._wait_scratch(SCRATCH_1, STATUS_PHASE2_DONE, "PHASE2_DONE")
            await self._wait_scratch(SCRATCH_0, FW_PASS, "PHASE2_PASS")
            assert (
                self._value(dut.tb_output_axi_read_count, "tb_output_axi_read_count") > phase2_reads
            ), "firmware reached phase-2 PASS without a completed external recovery read"
            self.contracts.add("firmware_recovered")

            await self._probe_front_port()
            await self.csr_write("RESET_TIMEOUT_CLEAR", RESET_TIMEOUT, 0, length=8)
        finally:
            dut.tb_output_axi_resp_hold.value = 0


class smc_cpu_mmio_read_wedge_test_seq(_CpuMmioWedgeSeq):
    """MMIO read response withheld at SYS_OUT."""

    go_magic = GO_READ_MAGIC
    pending_name = "tb_cpu_mmio_pending_ar"
    other_pending_name = "tb_cpu_mmio_pending_aw"
    output_valid_name = "tb_output_axi_arvalid"
    output_ready_name = "tb_output_axi_arready"
    output_addr_name = "tb_output_axi_araddr"
    output_count_name = "tb_output_axi_read_count"
    flavor = "read"


class smc_cpu_mmio_write_wedge_test_seq(_CpuMmioWedgeSeq):
    """MMIO write response withheld at SYS_OUT."""

    go_magic = GO_WRITE_MAGIC
    pending_name = "tb_cpu_mmio_pending_aw"
    other_pending_name = "tb_cpu_mmio_pending_ar"
    output_valid_name = "tb_output_axi_awvalid"
    output_ready_name = "tb_output_axi_awready"
    output_addr_name = "tb_output_axi_awaddr"
    output_count_name = "tb_output_axi_write_count"
    flavor = "write"
