# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO primary-reset effect on interrupt state and on an in-flight access.

Contract SMC_GPIO_PAD_IRQ_024, anchor smc_gpio_rst_primary_test.
Allocated scenarios: PADIRQ-RST-PRIMARY.S2, PADIRQ-RST-PRIMARY.S3, PADIRQ-RST-PRIMARY.S4.
Spec sources: hw/ip/gpio/doc/architecture.adoc (Interrupts, Reset and Strap Capture),
hw/ip/gpio/regs/gpio_intf.rdl, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

WRAP = 60

DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", WRAP)
DATA_CTRL_ENABLE = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR", WRAP)

_RX_ENABLE = 2 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_IRQ_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
_TYPE_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bp")
_PAD2CORE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm")
_LSIO_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm")

CFG_LEVEL_HIGH = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | (0 << _TYPE_BP)
CFG_RISING_EDGE = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | (2 << _TYPE_BP)
CFG_IN_FLIGHT = _RX_ENABLE | _IF_ENABLE | _IRQ_ENABLE | (1 << _TYPE_BP)

# Registers read zero after the reset under the mask that drops the pad return and the
# hardware LSIO request status.
_RESET_READ_MASK = ~(_PAD2CORE | _LSIO_ENABLE) & 0xFFFF_FFFF

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
TERM_ORDER = ("IRQ_ASSERTED", "RESET_LEVEL", "RESET_EDGE", "RESET_ACCESS", "RESTORE")
CHK_ORDER = (
    ("S2", "CHK-RST-PRIMARY-LEVEL-IRQ"),
    ("S3", "CHK-RST-PRIMARY-EDGE"),
    ("S4", "CHK-RST-PRIMARY-AXI-BOUNDED"),
)

AFTER_RELEASE_CYCLES = 64
IRQ_RISE_BOUND_CYCLES = 64
PAD_SETTLE_BOUND_READS = 64
AXI_BOUND_CYCLES = 256
RESET_ASSERT_BOUND_CYCLES = 1024
RESET_RELEASE_BOUND_CYCLES = 8192
EDGE_SETUP_WINDOW_CYCLES = 4
AXI_LAUNCH_LEAD_CYCLES = 4
EDGE_LEAD_CYCLES = 2
IN_RESET_WINDOW_CYCLES = 64


class _Sampler:
    """Per-clk_smc_i-edge record of tb_gpio_interrupt[WRAP] and the primary reset level."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.irq: list[int] = []
        self.rst_n: list[int] = []
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._task.cancel()

    async def _run(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smc_i)
            vec = dut.tb_gpio_interrupt.value
            rst = dut.rst_primary_smc_clk_no.value
            assert vec.is_resolvable, f"tb_gpio_interrupt is X/Z: {vec}"
            assert rst.is_resolvable, f"rst_primary_smc_clk_no is X/Z: {rst}"
            self.irq.append((int(vec) >> WRAP) & 1)
            self.rst_n.append(int(rst) & 1)

    @property
    def count(self) -> int:
        return len(self.irq)


class smc_gpio_rst_primary_test_seq(SmcCsrSeq):
    """Cold reset against an asserted level interrupt, an edge in flight and a write."""

    def __init__(self, name: str = "smc_gpio_rst_primary_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.latency = 0

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    @staticmethod
    def _drive(dut, level: int | None) -> None:
        en = int(dut.tb_gpio_ext_drive_en.value)
        val = int(dut.tb_gpio_ext_drive_value.value)
        mask = 1 << WRAP
        if level is None:
            en &= ~mask
        else:
            en |= mask
            val = (val | mask) if level else (val & ~mask)
        dut.tb_gpio_ext_drive_en.value = en
        dut.tb_gpio_ext_drive_value.value = val

    async def _reset_op(self, op: SmcResetOp) -> None:
        item = SmcResetItem(op.value.lower())
        item.op = op
        await self.dispatch_reset(item)

    def _rst_level(self, label: str) -> int:
        value = cocotb.top.rst_primary_smc_clk_no.value
        assert value.is_resolvable, f"{label}: rst_primary_smc_clk_no is X/Z"
        return int(value)

    async def _edges_until_rst(self, want: int, bound: int, label: str) -> int:
        """clk_smc_i edges from now until rst_primary_smc_clk_no reads `want`."""
        dut = cocotb.top
        last = None
        for n in range(bound + 1):
            last = self._rst_level(label)
            if last == want:
                return n
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"{label}: rst_primary_smc_clk_no never reached {want} within {bound} "
            f"clk_smc_i cycles (last={last})"
        )

    async def _hold_and_release(self, label: str) -> int:
        """Hold the effective reset, release rst_cold_ni; returns the release-to-rise cycles."""
        await ClockCycles(cocotb.top.clk_smc_i, IN_RESET_WINDOW_CYCLES)
        await self._reset_op(SmcResetOp.COLD_RST_HI)
        return await self._edges_until_rst(1, RESET_RELEASE_BOUND_CYCLES, f"{label} release")

    async def _assert_pin(self) -> None:
        """Assert rst_cold_ni on a clk_ref_i edge so the pin-to-reset latency repeats."""
        await RisingEdge(cocotb.top.clk_ref_i)
        await self._reset_op(SmcResetOp.COLD_RST_LO)

    async def _reset_cycle(self, sampler: _Sampler, label: str) -> tuple[int, int, int, int]:
        """Assert rst_cold_ni, hold it in effect, release it.

        Returns the two sample indices, L and the release-to-rise cycle count.
        """
        dut = cocotb.top
        await self._assert_pin()
        latency = await self._edges_until_rst(0, RESET_ASSERT_BOUND_CYCLES, f"{label} assert")
        in_reset = sampler.count
        rise = await self._hold_and_release(label)
        released = sampler.count
        await ClockCycles(dut.clk_smc_i, AFTER_RELEASE_CYCLES)
        return in_reset, released, latency, rise

    async def _await_irq(self, sampler: _Sampler, label: str) -> int:
        start = sampler.count
        for _ in range(IRQ_RISE_BOUND_CYCLES):
            if 1 in sampler.irq[start:]:
                return sampler.irq[start:].index(1) + 1
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: tb_gpio_interrupt[{WRAP}] never read 1 within {IRQ_RISE_BOUND_CYCLES} "
            f"clk_smc_i cycles (last={sampler.irq[-1:]})"
        )

    async def _await_pad2core(self, want: int, label: str) -> None:
        last = None
        for _ in range(PAD_SETTLE_BOUND_READS):
            word = await self.csr_read(label, DATA_CTRL)
            last = (word & _PAD2CORE) != 0
            if last == bool(want):
                return
        raise AssertionError(
            f"{label}: DATA_CTRL.pad2core never read {want} within {PAD_SETTLE_BOUND_READS} "
            f"reads (last={last})"
        )

    async def _step_level(self, dut, sampler: _Sampler) -> str:
        pre = sampler.count
        in_reset, released, latency, rise = await self._reset_cycle(sampler, "S2")
        self.latency = latency
        irq, rst = sampler.irq, sampler.rst_n
        before = [i for i in range(pre, in_reset) if rst[i] == 1]
        assert before and irq[before[-1]] == 1, (
            f"pre-reset level interrupt missing: last pre-reset samples {irq[pre:in_reset][-4:]}"
        )
        window = list(range(in_reset - 1, sampler.count))
        low = [i for i in window if rst[i] == 0 or i >= released]
        bad = [i for i in low if irq[i] != 0]
        assert not bad, (
            f"tb_gpio_interrupt[{WRAP}] read 1 at {len(bad)} of {len(low)} samples from the "
            f"reset assertion on (first at sample {bad[0]}, rst_primary_smc_clk_no="
            f"{rst[bad[0]]}, release at sample {released})"
        )
        in_rst = sum(1 for i in window if rst[i] == 0)
        post = sampler.count - released
        assert in_rst > 0 and post >= AFTER_RELEASE_CYCLES, (
            f"empty window: {in_rst} reset samples, {post} post-release samples"
        )
        return (
            f"tb_gpio_interrupt[{WRAP}] read 1 before the reset (last pre-reset sample "
            f"{irq[before[-1]]}) and 0 at all {in_rst} samples with rst_primary_smc_clk_no=0 "
            f"and all {post} samples after its release, pad still high and DATA_CTRL not "
            f"re-programmed; the reset source is rst_cold_ni (SF-020: cold-only is not "
            f"separable from primary at the SMC boundary); L={latency} clk_smc_i cycles from the "
            f"rst_cold_ni assert to the fall of rst_primary_smc_clk_no, {rise} cycles from the "
            f"rst_cold_ni release to its rise"
        )

    async def _step_edge(self, dut, sampler: _Sampler) -> str:
        await self.csr_write("EDGE_PAD_LOW_PREP", DATA_CTRL, 0)
        self._drive(dut, 0)
        await self.csr_write("EDGE_PROGRAM_CONTROL", DATA_CTRL, CFG_RISING_EDGE)
        await self._await_pad2core(0, "EDGE_CONTROL_PAD_LOW")
        quiet = sampler.count
        assert not any(sampler.irq[quiet - 8 :]), "edge control: interrupt already 1 with pad low"
        self._drive(dut, 1)
        control_at = await self._await_irq(sampler, "edge control")
        self._drive(dut, 0)
        await self._await_pad2core(0, "EDGE_CONTROL_RELEASE_LOW")
        control_start = quiet
        control_pulses = sum(sampler.irq[control_start:])

        await self.csr_write("EDGE_PROGRAM", DATA_CTRL, CFG_RISING_EDGE)
        await self._await_pad2core(0, "EDGE_PAD_LOW")
        latency = self.latency
        assert latency > EDGE_LEAD_CYCLES, f"L={latency} too small for the edge lead"
        await self._assert_pin()
        for _ in range(latency - EDGE_LEAD_CYCLES):
            await RisingEdge(dut.clk_smc_i)
        at_rise = self._rst_level("S3 pad rise")
        assert at_rise == 1, (
            f"rst_primary_smc_clk_no already {at_rise} when the pad rose (L={latency}); "
            f"the edge is not inside the synchroniser window"
        )
        pre = sampler.count
        self._drive(dut, 1)
        fall = None
        for n in range(1, EDGE_SETUP_WINDOW_CYCLES + 1):
            await RisingEdge(dut.clk_smc_i)
            if self._rst_level("S3 fall") == 0:
                fall = n
                break
        assert fall is not None, (
            f"rst_primary_smc_clk_no not 0 within {EDGE_SETUP_WINDOW_CYCLES} clk_smc_i cycles "
            f"after the pad rose (L={latency})"
        )
        in_reset = sampler.count
        rise = await self._hold_and_release("S3")
        released = sampler.count
        await ClockCycles(dut.clk_smc_i, AFTER_RELEASE_CYCLES)
        irq = sampler.irq
        pre_reset_pulses = sum(irq[pre:in_reset])
        in_window = sum(irq[in_reset:released])
        after = irq[released : released + AFTER_RELEASE_CYCLES]
        assert len(after) == AFTER_RELEASE_CYCLES, f"only {len(after)} post-release samples"
        assert control_pulses >= 1, "edge control: no pulse for a rising edge on the pad"
        return (
            f"control run: rising edge raised tb_gpio_interrupt[{WRAP}] {control_pulses} "
            f"sample(s) high, first {control_at} cycles after the pad rose; reset run: "
            f"rst_primary_smc_clk_no read 1 on the cycle the pad rose and 0 {fall} clk_smc_i "
            f"cycle(s) after it (pad raised {latency - EDGE_LEAD_CYCLES} cycles after the "
            f"rst_cold_ni assert, L={latency}); tb_gpio_interrupt[{WRAP}] high samples: "
            f"{pre_reset_pulses} before the fall, {in_window} from the fall to the rise, "
            f"{sum(after)} of the {len(after)} after the rise ({rise} cycles after the "
            f"rst_cold_ni release), measured only (SF-021: edge detector state at release with "
            f"the pad at the active level; SF-020: cold-only reset not separable)"
        )

    async def _step_access(self, dut, sampler: _Sampler) -> str:
        latency = self.latency
        assert latency > AXI_LAUNCH_LEAD_CYCLES, f"L={latency} too small for the launch lead"
        driver_bound_ns = self.cfg.axi_timeout_ns
        item = SmcSysAxiItem("wr_in_flight_DATA_CTRL")
        item.op = SmcSysAxiOp.WRITE
        item.addr = DATA_CTRL
        item.length = 4
        item.wdata = CFG_IN_FLIGHT
        item.allow_reset_abort = True
        outcome = {"done": False}

        async def write() -> None:
            await self.start_item(item)
            await self.finish_item(item)
            outcome["done"] = True

        await self._assert_pin()
        for _ in range(latency - AXI_LAUNCH_LEAD_CYCLES):
            await RisingEdge(dut.clk_smc_i)
        has_aw = hasattr(dut, "s_axi_awvalid")
        assert has_aw, "s_axi_awvalid probe missing"
        task = cocotb.start_soon(write())
        fall = issued = done_at = None
        for cycle in range(AXI_BOUND_CYCLES + 1):
            rst = self._rst_level("S4 write")
            aw = dut.s_axi_awvalid.value
            assert aw.is_resolvable, "s_axi_awvalid is X/Z"
            if issued is None and int(aw):
                issued = cycle
            if fall is None and rst == 0:
                fall = cycle
            if outcome["done"]:
                done_at = cycle
                break
            if cycle < AXI_BOUND_CYCLES:
                await RisingEdge(dut.clk_smc_i)
        state = (
            f"issued={issued} fall={fall} resp_code={item.resp_code} timed_out={item.timed_out} "
            f"reset_aborted={item.reset_aborted} "
            f"rst_primary_smc_clk_no={self._rst_level('S4 state')}"
        )
        assert done_at is not None, (
            f"in-flight write to 0x{DATA_CTRL:08x} neither answered nor reset-aborted within "
            f"{AXI_BOUND_CYCLES} clk_smc_i cycles of the launch ({state})"
        )
        assert task.done(), "write coroutine did not finish"
        self.accesses += 1
        after_fall = fall is not None and (
            fall <= done_at if item.reset_aborted else fall < done_at
        )
        assert issued is not None and after_fall and issued <= fall, (
            f"write not outstanding across the effective reset fall: launch-to-AW {issued}, "
            f"launch-to-fall {fall}, launch-to-completion {done_at} (L={latency})"
        )
        resp = "reset-aborted: no response" if item.reset_aborted else f"resp={item.resp_code}"
        rise = await self._hold_and_release("S4")
        await self.wait_fuse_sense_done()
        ctrl = await self.csr_read("S4_DATA_CTRL_RB", DATA_CTRL)
        enable = await self.csr_read("S4_DATA_CTRL_ENABLE_RB", DATA_CTRL_ENABLE)
        assert ctrl & _RESET_READ_MASK == 0 and enable & _RESET_READ_MASK == 0, (
            f"after the reset DATA_CTRL read 0x{ctrl:08x} and DATA_CTRL_ENABLE 0x{enable:08x}; "
            f"non-zero under mask 0x{_RESET_READ_MASK:08x}"
        )
        return (
            f"the write of DATA_CTRL=0x{CFG_IN_FLIGHT:08x} launched "
            f"{latency - AXI_LAUNCH_LEAD_CYCLES} cycles after the rst_cold_ni assert "
            f"(L={latency}) was issued {issued} cycles after the launch, "
            f"rst_primary_smc_clk_no fell {fall} cycles after the launch and the "
            f"write completed with {resp} (0 OKAY, 2 SLVERR, 3 DECERR) {done_at} cycles after the "
            f"launch, bound {AXI_BOUND_CYCLES} cycles (SEP_IN driver bound {driver_bound_ns} ns); "
            f"effective reset rose {rise} cycles after the release; after it DATA_CTRL read "
            f"0x{ctrl:08x} and DATA_CTRL_ENABLE 0x{enable:08x}, zero under mask "
            f"0x{_RESET_READ_MASK:08x} (SF-020: cold-only reset not separable)"
        )

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(TERM_ORDER),
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_gpio_interrupt"), "tb_gpio_interrupt probe missing"
        assert hasattr(dut, "rst_primary_smc_clk_no"), "rst_primary_smc_clk_no probe missing"
        await self.wait_fuse_sense_done()
        sampler = _Sampler(dut)
        sampler.start()

        # S1
        self._drive(dut, 1)
        await self.csr_write("LEVEL_PROGRAM", DATA_CTRL, CFG_LEVEL_HIGH)
        asserted_at = await self._await_irq(sampler, "S1 level interrupt")
        self._mark("S1")

        # S2
        text = await self._step_level(dut, sampler)
        await self.wait_fuse_sense_done()
        self._mark("S2")
        self._chk("S2", "CHK-RST-PRIMARY-LEVEL-IRQ", f"{text}; asserted {asserted_at} cycles in")

        # S3
        text = await self._step_edge(dut, sampler)
        await self.wait_fuse_sense_done()
        self._mark("S3")
        self._chk("S3", "CHK-RST-PRIMARY-EDGE", text)

        # S4
        text = await self._step_access(dut, sampler)
        self._mark("S4")
        self._chk("S4", "CHK-RST-PRIMARY-AXI-BOUNDED", text)

        # S5
        self._drive(dut, None)
        await self.csr_write("RESTORE_DATA_CTRL", DATA_CTRL, 0)
        await self.csr_read("RESTORE_DATA_CTRL_RB", DATA_CTRL, expected=0)
        sampler.stop()
        self._mark("S5")
        self._nonvac()
        self.assert_all_reachable(self.accesses, "GPIO_RST_PRIMARY")
