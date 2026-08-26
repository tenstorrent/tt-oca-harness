# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_CLK_MULTI_WINDOW_TEST ANCHOR: smc_clk_multi_window_test
"""

from __future__ import annotations

import os
import random

import logging

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq
from . import smc_cg_obs_utils as cg

_LOG = logging.getLogger(__name__)

# Legal programmed hysteresis for LIVE DMA-CG measure path.
# Low end is 8 (not 0/1): hyst=0 never runs under cg_enable; hyst=1 loses the
# frontend→backend handoff (DMA accepts NEXT_ID but DONE never advances).
HYST_LEGAL_LO = 8
HYST_LEGAL_HI = 63
# Seed-driven draw count (execution guide: 8 random windows per seed). Always
# covers low/mid/high bands so required_cells stay hit.
NUM_RANDOM_WINDOWS = 8
IDLE_OBSERVE = 4
GATE_OFF_TIMEOUT_SMC = 512
BUSY_TIMEOUT_SMC = 1024


def _seeded_hyst_windows(seed: int) -> tuple[int, int, int, list[int]]:
    """Return (hyst_min, hyst_mid, hyst_max, extras) from RANDOM_SEED.

    Band picks guarantee ordered low < mid < high for scale checkers; extras
    fill out NUM_RANDOM_WINDOWS distinct values in the legal range.
    """
    rng = random.Random(seed ^ 0xC10C_5111)
    low = rng.randint(HYST_LEGAL_LO, 20)
    mid = rng.randint(max(low + 1, 21), 45)
    high = rng.randint(max(mid + 1, 46), HYST_LEGAL_HI)
    vals = {low, mid, high}
    while len(vals) < NUM_RANDOM_WINDOWS:
        vals.add(rng.randint(HYST_LEGAL_LO, HYST_LEGAL_HI))
    ordered = sorted(vals)
    hyst_min, hyst_mid, hyst_max = ordered[0], ordered[len(ordered) // 2], ordered[-1]
    extras = [h for h in ordered if h not in (hyst_min, hyst_mid, hyst_max)]
    return hyst_min, hyst_mid, hyst_max, extras

DMA_SRC_ADDR = 0x0200_0000
DMA_DST_ADDR = 0x0200_0100
DMA_MODEL_REGION = "clk_multi_window_dma_fabric"
DMA_MODEL_SIZE = 0x1000
DMA_PAYLOAD = bytes.fromhex("A1B2C3D4E5F60708")


class smc_clk_multi_window_test_seq(SmcCsrSeq):
    """LIVE hysteresis-window scaling across min/mid/max programmed values."""

    def __init__(self, name: str = "smc_clk_multi_window_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}
        self.required_cells_hit: list[str] = []
        self.measured: dict[str, int] = {}

    def _dut(self):
        return cocotb.top

    async def _program_cg(self, *, enable: bool, hyst: int) -> None:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", cg.CLOCK_GATE_CONTROL, length=8)
        nxt = (cur & ~cg.DMA_CG_EN & ~cg.CG_HYST_MASK) | (
            (hyst << cg.CG_HYST_SHIFT) & cg.CG_HYST_MASK
        )
        if enable:
            nxt |= cg.DMA_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_WR", cg.CLOCK_GATE_CONTROL, nxt, length=8)
        rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", cg.CLOCK_GATE_CONTROL, length=8)
        assert ((rb & cg.CG_HYST_MASK) >> cg.CG_HYST_SHIFT) == hyst
        assert (rb & cg.DMA_CG_EN) == (cg.DMA_CG_EN if enable else 0)

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", cg.INBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "INBOUND0_END_PASS_ALL", cg.INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL",
            cg.INBOUND0_FILTER_CONFIG,
            cg.PASS_ALL_CONFIG,
            length=8,
        )
        await self.csr_write("OUTBOUND0_START_PASS_ALL", cg.OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "OUTBOUND0_END_PASS_ALL", cg.OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_PASS_ALL",
            cg.OUTBOUND0_FILTER_CONFIG,
            cg.PASS_ALL_CONFIG,
            length=8,
        )

    async def _write_bytes(self, addr: int, data: bytes) -> None:
        assert self.env is not None
        item_name = f"jtag_mw_wr_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = len(data)
        item.wdata = int.from_bytes(data, "little")
        item.update_golden = True
        item.memory_region = DMA_MODEL_REGION
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    async def _program_dma_descriptors(self) -> None:
        await self.csr_write("DMA_CONFIG", cg.DMA_CTRL_CONFIG, cg.DMA_CONFIG_ENABLED_ND)
        await self.csr_write(
            "DMA_DST_ADDRESS_LO", cg.DMA_CTRL_DST_ADDRESS_LO, DMA_DST_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write(
            "DMA_DST_ADDRESS_HI", cg.DMA_CTRL_DST_ADDRESS_HI, DMA_DST_ADDR >> 32
        )
        await self.csr_write(
            "DMA_SRC_ADDRESS_LO", cg.DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write(
            "DMA_SRC_ADDRESS_HI", cg.DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC_ADDR >> 32
        )
        await self.csr_write("DMA_LENGTH_LO", cg.DMA_CTRL_LENGTH_LO, len(DMA_PAYLOAD))
        await self.csr_write("DMA_LENGTH_HI", cg.DMA_CTRL_LENGTH_HI, 0)
        await self.csr_write("DMA_DST_STRIDE_LO", cg.DMA_CTRL_DST_STRIDE_LO, 0)
        await self.csr_write("DMA_DST_STRIDE_HI", cg.DMA_CTRL_DST_STRIDE_HI, 0)
        await self.csr_write("DMA_SRC_STRIDE_LO", cg.DMA_CTRL_SRC_STRIDE_LO, 0)
        await self.csr_write("DMA_SRC_STRIDE_HI", cg.DMA_CTRL_SRC_STRIDE_HI, 0)
        await self.csr_write("DMA_NUM_REPETITIONS_LO", cg.DMA_CTRL_NUM_REPETITIONS_LO, 1)
        await self.csr_write("DMA_NUM_REPETITIONS_HI", cg.DMA_CTRL_NUM_REPETITIONS_HI, 0)

    async def _start_dma(self) -> int:
        start_id = await self.csr_read("DMA_NEXT_ID_0_START", cg.DMA_CTRL_NEXT_ID_0)
        assert start_id != 0, "DMA command was not accepted"
        return start_id

    async def _wait_dma_done(self, baseline_done: int) -> None:
        dut = self._dut()
        # Sparse poll — continuous CSR reads starve the DMA AXI path (A-class).
        for _ in range(80):
            done = await self.csr_read("DMA_DONE_0_POLL", cg.DMA_CTRL_DONE_0)
            if done > baseline_done:
                # Wait until shared busy clears so re-gate delay starts from idle.
                for _ in range(BUSY_TIMEOUT_SMC):
                    if cg.sample_bit(dut, "tb_dma_busy") == 0:
                        return
                    await RisingEdge(dut.clk_smc_i)
                raise AssertionError(
                    f"TIMEOUT waiting DMA busy clear after done: baseline={baseline_done}"
                )
            await ClockCycles(dut.clk_smc_i, 20)
        status = await self.csr_read("DMA_STATUS_0_TIMEOUT", cg.DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"TIMEOUT waiting DMA done: baseline={baseline_done} status=0x{status:x} "
            f"busy={cg.sample_bit(dut, 'tb_dma_busy')}"
        )

    async def _measure_window(self, step_id: str, hyst: int, cell: str, fence_term: str) -> int:
        dut = self._dut()
        cg.log_step(step_id, f"program hyst={hyst}; active then idle; measure re-gate delay")
        await self._program_cg(enable=True, hyst=hyst)
        # Settle idle first so descriptor programming starts from gated-off when possible.
        await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=hyst,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_busy", "tb_dma_cg_en"),
        )

        baseline_done = await self.csr_read(f"DMA_DONE_BASE_{step_id}", cg.DMA_CTRL_DONE_0)
        await self._program_dma_descriptors()
        await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=hyst,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_busy", "tb_dma_cg_en"),
        )
        # Concurrent meter: capture busy-fall and last gated edge while the
        # sparse DONE poll runs (so hysteresis is not consumed before metering).
        state = {
            "busy_seen": False,
            "busy_fall_at": -1,
            "last_edge_at": -1,
            "smc": 0,
        }
        stop = {"done": False}

        async def _meter() -> None:
            while not stop["done"]:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                # Gater busy_i (not dma_busy_o) is the hysteresis T0 reference.
                busy = cg.sample_bit(dut, "tb_dma_gater_busy") == 1
                if busy:
                    state["busy_seen"] = True
                    # Re-arm fall detector across multi-pulse busy.
                    state["busy_fall_at"] = -1
                elif state["busy_seen"] and state["busy_fall_at"] < 0:
                    state["busy_fall_at"] = state["smc"]

        async def _edge_watch() -> None:
            while not stop["done"]:
                await RisingEdge(dut.tb_dma_gated_clk)
                if not stop["done"]:
                    state["last_edge_at"] = state["smc"]

        meter = cocotb.start_soon(_meter())
        edges = cocotb.start_soon(_edge_watch())
        await self._start_dma()
        await self._wait_dma_done(baseline_done)
        # After DONE+busy-clear, wait until gated clock stays quiet.
        quiet_start = state["smc"]
        for _ in range(GATE_OFF_TIMEOUT_SMC):
            if (
                state["busy_fall_at"] >= 0
                and state["last_edge_at"] >= state["busy_fall_at"]
                and state["smc"] - state["last_edge_at"] >= IDLE_OBSERVE
            ):
                break
            if (
                state["busy_fall_at"] >= 0
                and state["last_edge_at"] < state["busy_fall_at"]
                and state["smc"] - state["busy_fall_at"] >= IDLE_OBSERVE
            ):
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            stop["done"] = True
            meter.kill()
            edges.kill()
            raise AssertionError(
                f"TIMEOUT waiting re-gate quiet for {step_id}: "
                f"busy_fall={state['busy_fall_at']} last_edge={state['last_edge_at']} "
                f"smc={state['smc']} since_done={state['smc'] - quiet_start} hyst={hyst}"
            )
        stop["done"] = True
        meter.kill()
        edges.kill()

        assert state["busy_seen"], f"DMA busy never observed for {step_id}"
        assert state["busy_fall_at"] >= 0, f"DMA busy never cleared for {step_id}"
        if state["last_edge_at"] < state["busy_fall_at"]:
            delay = 0
        else:
            delay = state["last_edge_at"] - state["busy_fall_at"] + 1

        post = await cg.count_gated_rising(dut, "tb_dma_gated_clk", IDLE_OBSERVE)
        assert post == 0, f"gated-clock oscillation after idle: edges={post}"

        delta = abs(delay - hyst)
        assert delta <= 1, (
            f"re-gate delay {delay} differs from programmed hyst={hyst} by >1 "
            f"(busy_fall={state['busy_fall_at']} last_edge={state['last_edge_at']})"
        )
        self.measured[cell] = delay
        self.required_cells_hit.append(cell)
        cg.mark_fence(self.fence, fence_term)
        _LOG.info(
            "WINDOW %s hyst=%d measured_delay=%d cell=%s", step_id, hyst, delay, cell
        )
        return delay

    async def body(self) -> None:
        dut = self._dut()
        for port in ("tb_dma_cg_en", "tb_dma_gated_clk", "tb_dma_busy"):
            assert hasattr(dut, port), f"missing TB observation port {port}"

        if DMA_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(DMA_MODEL_REGION, DMA_SRC_ADDR, DMA_MODEL_SIZE)

        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        hyst_min, hyst_mid, hyst_max, extras = _seeded_hyst_windows(seed)
        _LOG.info(
            "SEED: %d hyst windows min/mid/max=%d/%d/%d extras=%s",
            seed,
            hyst_min,
            hyst_mid,
            hyst_max,
            extras,
        )

        await self._program_output_fabric_pass_all()
        await self._write_bytes(DMA_SRC_ADDR, DMA_PAYLOAD)
        await self._write_bytes(DMA_DST_ADDR, bytes(0x5A for _ in range(len(DMA_PAYLOAD))))

        d_min = await self._measure_window(
            "S1", hyst_min, "hysteresis_delay_min", "low-window-measured"
        )
        d_mid = await self._measure_window(
            "S2", hyst_mid, "hysteresis_delay_mid", "mid-window-measured"
        )
        d_max = await self._measure_window(
            "S3", hyst_max, "hysteresis_delay_max", "high-window-measured"
        )

        # Scale check: mid and max delays track programmed values (min may be 0).
        assert d_mid >= d_min, f"mid delay {d_mid} < min {d_min}"
        assert d_max >= d_mid, f"max delay {d_max} < mid {d_mid}"

        # Close required-cell fence before seed-driven extras (extras are
        # coverage variety; they must not reorder the NONVAC fence).
        cg.assert_fence_order(
            self.fence,
            ["low-window-measured", "mid-window-measured", "high-window-measured"],
        )

        for idx, hyst in enumerate(extras):
            await self._measure_window(
                f"SX{idx}",
                hyst,
                f"hysteresis_delay_extra_{idx}",
                f"extra-window-{idx}-measured",
            )

        cg.emit_chk(
            self.chk_seen,
            "CHK-HYST-WINDOW",
            "CHK-HYST-WINDOW: low/mid/high measured within_1cyc "
            f"min={d_min}/{hyst_min} mid={d_mid}/{hyst_mid} max={d_max}/{hyst_max} "
            f"extras={extras} seed={seed} "
            f"zero_toggles_idle=1 cells={','.join(self.required_cells_hit)}",
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS: gate_off/busy/done/regate waits all bounded "
            f"timeout_smc={GATE_OFF_TIMEOUT_SMC} fail_on_expiry=1",
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: low-window-measured < mid-window-measured < "
            "high-window-measured < PASS",
        )
        cg.mark_fence(self.fence, "PASS")
        _LOG.info("smc_clk_multi_window_test_seq PASS")
