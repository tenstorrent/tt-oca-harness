# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_004 ANCHOR: smc_cg_zeroer_activity_bringup_test
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from . import smc_addr_map as _addr
from . import smc_cg_obs_utils as cg
from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

# Every record this sequence emits goes through `cocotb.log`: a module-level
# `logging.getLogger(__name__)` is not captured by the cocotb/pyuvm runner, so
# the STEP/CHK/FENCE evidence written through one never reaches the kept log
# ([EVIDENCE-TOKEN-CONDITIONAL]).

HYST = 0
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256
BUSY_TIMEOUT_SMC = 256

# Authoritative map (also re-exported via smc_cg_obs_utils).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
ZEROER_CG_EN = _addr.ZEROER_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK
INBOUND0_FILTER_CONFIG = _addr.INBOUND0_FILTER_CONFIG
INBOUND0_START = _addr.INBOUND0_START
INBOUND0_END = _addr.INBOUND0_END
OUTBOUND0_FILTER_CONFIG = _addr.OUTBOUND0_FILTER_CONFIG
OUTBOUND0_START = _addr.OUTBOUND0_START
OUTBOUND0_END = _addr.OUTBOUND0_END
PASS_ALL_CONFIG = cg.PASS_ALL_CONFIG
ZEROER_CTRL_DEST_ADDR = _addr.ZEROER_CTRL_DEST_ADDR
ZEROER_CTRL_SIZE = _addr.ZEROER_CTRL_SIZE
ZEROER_CTRL_STATUS = _addr.ZEROER_CTRL_STATUS

OUTPUT_FABRIC_ADDR = 0x0200_0000
OUTPUT_FABRIC_MODEL_REGION = "zeroer_activity_bringup_fabric"
OUTPUT_FABRIC_MODEL_SIZE = 0x1000
ZEROER_POISON = bytes.fromhex("b1b2b3b4b5b6b7b8")


class smc_cg_zeroer_activity_bringup_test_seq(SmcCsrSeq):
    """LIVE Zeroer axi_clk + reg_clk activity-driven gate/ungate triggered by one
    zero operation (SMCCGP0_004)."""

    def __init__(self, name: str = "smc_cg_zeroer_activity_bringup_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}

    def _dut(self):
        return cocotb.top

    async def _program_cg(self, *, zeroer_en: bool, hyst: int = HYST) -> None:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        nxt = (cur & ~ZEROER_CG_EN & ~CG_HYST_MASK) | ((hyst << CG_HYST_SHIFT) & CG_HYST_MASK)
        if zeroer_en:
            nxt |= ZEROER_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_WR", CLOCK_GATE_CONTROL, nxt, length=8)
        rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        assert (rb & ZEROER_CG_EN) == (ZEROER_CG_EN if zeroer_en else 0)

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL",
            INBOUND0_FILTER_CONFIG,
            PASS_ALL_CONFIG,
            length=8,
        )
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "OUTBOUND0_END_PASS_ALL", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_PASS_ALL",
            OUTBOUND0_FILTER_CONFIG,
            PASS_ALL_CONFIG,
            length=8,
        )

    async def _write_bytes(self, addr: int, data: bytes) -> None:
        assert self.env is not None
        item_name = f"jtag_zact_wr_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = len(data)
        item.wdata = int.from_bytes(data, "little")
        item.update_golden = True
        item.memory_region = OUTPUT_FABRIC_MODEL_REGION
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    async def _wait_zeroer_idle(self) -> None:
        dut = self._dut()
        for _ in range(BUSY_TIMEOUT_SMC * 8):
            if cg.sample_bit(dut, "tb_zeroer_busy") == 0:
                return
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError("TIMEOUT waiting zeroer_busy_o clear")

    async def _trigger_and_monitor(self) -> dict:
        """One zero-operation trigger with concurrent observation of:

        - ``tb_zeroer_gated_reg_clk`` toggling while the DEST_ADDR/SIZE/
          CTRL_STATUS register writes are in flight (S2), and
        - ``tb_zeroer_gated_axi_clk`` resuming with / toggling every cycle of
          the ``tb_zeroer_busy`` interval that the CTRL_STATUS start write
          produces (S3), through to completion (S4, bounded).
        """
        dut = self._dut()
        state = {
            "smc": 0,
            "writing": False,
            "reg_toggle_count": 0,
            "first_reg_toggle_smc": -1,
            "busy_at": -1,
            "axi_resume_at": -1,
            "post_resume_cycles": 0,
            "axi_enabled_hits": 0,
            "done": False,
        }

        async def _mon() -> None:
            while not state["done"] and state["smc"] < BUSY_TIMEOUT_SMC * 8:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                await ReadOnly()
                regv = dut.tb_zeroer_gated_reg_clk.value
                axiv = dut.tb_zeroer_gated_axi_clk.value
                busyv = dut.tb_zeroer_busy.value
                if regv.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_reg_clk sample is X/Z")
                if axiv.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_axi_clk sample is X/Z")
                if busyv.is_resolvable is False:
                    raise AssertionError("tb_zeroer_busy sample is X/Z")
                reg_on = int(regv) == 1
                axi_on = int(axiv) == 1
                busy = int(busyv) == 1
                await Timer(1, unit="ps")
                if state["writing"] and reg_on:
                    state["reg_toggle_count"] += 1
                    if state["first_reg_toggle_smc"] < 0:
                        state["first_reg_toggle_smc"] = state["smc"]
                if state["busy_at"] < 0 and busy:
                    state["busy_at"] = state["smc"]
                if state["busy_at"] >= 0 and state["axi_resume_at"] < 0 and axi_on:
                    state["axi_resume_at"] = state["smc"]
                if state["axi_resume_at"] >= 0 and busy:
                    state["post_resume_cycles"] += 1
                    if axi_on:
                        state["axi_enabled_hits"] += 1
                elif state["busy_at"] >= 0 and not busy:
                    state["done"] = True
                    return

        mon = cocotb.start_soon(_mon())
        state["writing"] = True
        await self.csr_write(
            "ZEROER_DEST_ADDR", ZEROER_CTRL_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8
        )
        await self.csr_write("ZEROER_SIZE", ZEROER_CTRL_SIZE, len(ZEROER_POISON), length=8)
        await self.csr_write("ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, 0x1, length=8)
        state["writing"] = False
        for _ in range(BUSY_TIMEOUT_SMC * 8):
            if state["done"]:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            mon.cancel()
            raise AssertionError(
                "TIMEOUT waiting zero-operation completion: "
                f"bound_smc_cycles={BUSY_TIMEOUT_SMC * 8} busy_at={state['busy_at']} "
                f"axi_resume_at={state['axi_resume_at']} "
                f"reg_toggle_count={state['reg_toggle_count']} "
                f"last_zeroer_busy={cg.sample_bit(dut, 'tb_zeroer_busy')}"
            )
        mon.cancel()
        return state

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_zeroer_cg_en",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            "tb_zeroer_busy",
        ):
            assert hasattr(dut, port), f"missing TB port {port}"

        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_MODEL_SIZE
            )
        await self._program_output_fabric_pass_all()
        await self._write_bytes(OUTPUT_FABRIC_ADDR, ZEROER_POISON)

        # ---- S1: idle gate-off with no register activity and zeroer_busy_o=0 ----
        cg.log_step(
            "S1",
            "frontdoor-write CLOCK_GATE_CONTROL ZEROER_CG_EN=1; no register activity, "
            "zeroer_busy_o=0; sample zeroer_reg_gated_clk for a fixed window",
        )
        # Positive control: free-run via disable_cg, confirming the tap itself toggles.
        await self._program_cg(zeroer_en=False)
        await ClockCycles(dut.clk_smc_i, 4)
        free = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_reg_clk", 4)
        assert free == 4, f"reg_clk not free-running under disable_cg: {free}"
        await self._program_cg(zeroer_en=True)
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 1
        assert cg.sample_bit(dut, "tb_zeroer_busy") == 0
        gate_off_lat = await cg.measure_gate_off_latency(
            dut,
            "tb_zeroer_gated_reg_clk",
            max_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en", "tb_zeroer_busy"),
        )
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE)
        assert edges == 0, f"reg_clk still toggling idle: {edges}"
        cg.emit_chk(
            self.chk_seen,
            "CHK-REG-CLK-IDLE-GATED",
            f"CHK-REG-CLK-IDLE-GATED: toggle_count={edges} sample_window={IDLE_OBSERVE} "
            f"gate_off_latency={gate_off_lat} zeroer_cg_en=1 zeroer_busy_o=0",
        )
        cg.mark_fence(self.fence, "reg-clk-idle-gated-observed")

        # ---- S2/S3: trigger one zero operation; observe reg_clk across the register
        # writes and axi_clk across the busy interval; S4: bounded to completion ----
        cg.log_step(
            "S2",
            "program DEST_ADDR/SIZE and write CTRL_STATUS to start one zero operation "
            "over a small region, sampling zeroer_reg_gated_clk across the register "
            "writes",
        )
        cg.log_step(
            "S3",
            "sample zeroer_axi_gated_clk and zeroer_busy_o from operation start through completion",
        )
        cg.log_step(
            "S4",
            "bounded wait for zero-operation completion (zeroer_busy_o=0), TIMEOUT "
            "fails with last state",
        )
        state = await self._trigger_and_monitor()
        assert state["reg_toggle_count"] > 0, (
            "no zeroer_reg_gated_clk toggle observed during the DEST_ADDR/SIZE/"
            "CTRL_STATUS register-write window"
        )
        assert state["first_reg_toggle_smc"] >= 0, (
            "reg_clk toggle window never opened during register writes"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-REG-ACCESS-UNGATES-REG-CLK",
            f"CHK-REG-ACCESS-UNGATES-REG-CLK: toggle_count={state['reg_toggle_count']} "
            f"first_toggle_smc={state['first_reg_toggle_smc']} "
            "toggled_during_write_window=1 toggled_before_first_write=0",
        )
        cg.mark_fence(self.fence, "reg-access-ungates-reg-clk-observed")

        assert state["busy_at"] >= 0, "zeroer_busy_o never asserted after trigger"
        assert state["axi_resume_at"] >= 0, "zeroer_axi_gated_clk did not resume"
        assert state["done"], "TIMEOUT waiting zeroer_busy_o clear during toggle monitor"
        delta = max(0, state["axi_resume_at"] - state["busy_at"])
        assert delta <= 1, f"axi_clk resume not within 1 cycle of busy: {delta}"
        assert state["post_resume_cycles"] > 0, "post-resume busy window empty"
        assert state["axi_enabled_hits"] == state["post_resume_cycles"], (
            f"axi_clk missing toggles during busy: hits={state['axi_enabled_hits']} "
            f"post_resume_cycles={state['post_resume_cycles']}"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-BUSY-UNGATES-AXI-CLK",
            f"CHK-BUSY-UNGATES-AXI-CLK: resume_within_1cyc={int(delta <= 1)} "
            f"resume_cyc={delta} toggles_every_cycle="
            f"{int(state['axi_enabled_hits'] == state['post_resume_cycles'])} "
            f"enabled_hits={state['axi_enabled_hits']} "
            f"post_resume_cycles={state['post_resume_cycles']}",
        )
        cg.mark_fence(self.fence, "busy-ungates-axi-clk-observed")

        cg.emit_chk(
            self.chk_seen,
            "CHK-TIMEOUT-PATHS",
            f"CHK-TIMEOUT-PATHS: bound_smc_cycles={BUSY_TIMEOUT_SMC * 8} expired=0 "
            f"zeroer_busy_at_completion={cg.sample_bit(dut, 'tb_zeroer_busy')}",
        )

        # Re-settle idle so the sequence ends in a clean, re-observable state.
        await self._wait_zeroer_idle()

        cg.assert_fence_order(
            self.fence,
            [
                "reg-clk-idle-gated-observed",
                "reg-access-ungates-reg-clk-observed",
                "busy-ungates-axi-clk-observed",
            ],
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: reg-clk-idle-gated-observed < reg-access-ungates-reg-clk-observed "
            "< busy-ungates-axi-clk-observed < PASS",
        )
        cg.mark_fence(self.fence, "PASS")
        cocotb.log.info("smc_cg_zeroer_activity_bringup_test_seq PASS")
