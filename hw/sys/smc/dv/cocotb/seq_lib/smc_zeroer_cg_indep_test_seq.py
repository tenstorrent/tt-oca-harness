# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_ZEROER_CG_INDEP_TEST ANCHOR: smc_zeroer_cg_indep_test
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from . import smc_addr_map as _addr
from . import smc_cg_obs_utils as cg
from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

# hyst=0 so register-idle gate-off can open while axi busy is still high.
HYST = 0
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256
BUSY_TIMEOUT_SMC = 512
ZEROER_WAIT_CYCLES = 512

# Declared minimum length of the S2 (register-active) observation window, in
# clk_smc_i cycles. The S2 stimulus is ONE AXI4-Lite access to the Zeroer
# register block, whose `zeroer_bus_active` span at this bench is the address
# phase plus the data phase, i.e. 2 clk_smc_i cycles; a shorter window means
# the access never really occupied the register interface, and the
# "reg_clk toggles every cycle" claim would rest on a single sample.
MIN_S2_WINDOW = 2

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
OUTPUT_FABRIC_MODEL_REGION = "zeroer_cg_indep_fabric"
OUTPUT_FABRIC_MODEL_SIZE = 0x1000
# Long enough that busy remains after programming bus_active clears (S1 window).
ZEROER_SIZE = 0x100
ZEROER_POISON = bytes([0xA5]) * ZEROER_SIZE


class smc_zeroer_cg_indep_test_seq(SmcCsrSeq):
    """LIVE Zeroer axi_clk vs reg_clk gating independence (INT-ZEROER-CG-INDEP)."""

    def __init__(self, name: str = "smc_zeroer_cg_indep_test_seq") -> None:
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
        item_name = f"jtag_zindep_wr_0x{addr:x}"
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
        for _ in range(ZEROER_WAIT_CYCLES):
            if cg.sample_bit(dut, "tb_zeroer_busy") == 0:
                return
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            "TIMEOUT waiting zeroer_busy_o clear "
            f"busy={cg.sample_bit(dut, 'tb_zeroer_busy')} "
            f"bus_active={cg.sample_bit(dut, 'tb_zeroer_bus_active')}"
        )

    async def _trigger_zeroer(self) -> None:
        await self.csr_write(
            "ZEROER_DEST_ADDR", ZEROER_CTRL_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8
        )
        await self.csr_write("ZEROER_SIZE", ZEROER_CTRL_SIZE, ZEROER_SIZE, length=8)
        await self.csr_write("ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, 0x1, length=8)

    async def _observe_axi_active_reg_idle(self) -> tuple[int, int, int]:
        """S1 window after programming settles: busy=1, bus_active=0, reg gated.

        Observation starts only once register-idle is established (no AXI4-Lite
        and reg_clk already gated off); every subsequent busy cycle must keep
        axi_clk enabled and reg_clk gated.
        """
        dut = self._dut()
        state = {
            "window_cycles": 0,
            "axi_hits": 0,
            "reg_hits": 0,
            "busy_seen": False,
            "reg_idle_seen": False,
            "window_started": False,
            "done": False,
            "smc": 0,
        }

        async def _mon() -> None:
            while not state["done"] and state["smc"] < BUSY_TIMEOUT_SMC * 16:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                await ReadOnly()
                busy = cg.sample_bit(dut, "tb_zeroer_busy") == 1
                bus_act = cg.sample_bit(dut, "tb_zeroer_bus_active") == 1
                axi_v = dut.tb_zeroer_gated_axi_clk.value
                reg_v = dut.tb_zeroer_gated_reg_clk.value
                if axi_v.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_axi_clk sample is X/Z")
                if reg_v.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_reg_clk sample is X/Z")
                axi_on = int(axi_v) == 1
                reg_on = int(reg_v) == 1
                await Timer(1, unit="ps")
                if busy:
                    state["busy_seen"] = True
                # Arm when programming activity has cleared and reg domain gated.
                if busy and not bus_act and not reg_on:
                    state["reg_idle_seen"] = True
                    state["window_started"] = True
                if state["window_started"] and busy:
                    # Fail closed if register activity resumes mid-window.
                    if bus_act:
                        state["reg_resume"] = True
                        state["done"] = True
                        return
                    state["window_cycles"] += 1
                    if axi_on:
                        state["axi_hits"] += 1
                    if reg_on:
                        state["reg_hits"] += 1
                elif state["window_started"] and not busy:
                    state["done"] = True
                    return
                elif state["busy_seen"] and not busy and not state["window_started"]:
                    state["done"] = True
                    return

        state["reg_resume"] = False
        mon = cocotb.start_soon(_mon())
        await self._trigger_zeroer()
        for _ in range(BUSY_TIMEOUT_SMC * 16):
            if state["done"]:
                break
            await RisingEdge(dut.clk_smc_i)
        mon.cancel()
        assert state["busy_seen"], "zeroer_busy never asserted (S1)"
        assert not state["reg_resume"], "S1 register access resumed during observation window"
        assert state["reg_idle_seen"], (
            "S1 register-idle never established while busy "
            "(reg_clk never gated off during axi-active)"
        )
        assert state["window_started"], (
            "S1 register-idle/axi-active window never opened "
            "(busy cleared before register-idle settled)"
        )
        assert state["done"], (
            "TIMEOUT waiting S1 busy clear during dual-clock monitor "
            f"window_cycles={state['window_cycles']} "
            f"busy={cg.sample_bit(dut, 'tb_zeroer_busy')} "
            f"bus_active={cg.sample_bit(dut, 'tb_zeroer_bus_active')}"
        )
        return state["window_cycles"], state["axi_hits"], state["reg_hits"]

    async def _observe_reg_active_axi_idle(self) -> tuple[int, int, int, int]:
        """S2: register-active + axi-idle after reg_clk resume (same as regclk card).

        Returns (post_resume_cycles, axi_hits_post, reg_hits_post, axi_hits_all_active).
        Every-cycle reg enable is proven from resume through bus_active; axi must stay
        gated for the entire bus_active window while busy=0.
        """
        dut = self._dut()
        state = {
            "active_at": -1,
            "resume_at": -1,
            "post_resume_cycles": 0,
            "axi_hits_post": 0,
            "reg_hits_post": 0,
            "axi_hits_all": 0,
            "active_cycles": 0,
            "done": False,
            "smc": 0,
            "busy_during": False,
        }

        async def _mon() -> None:
            while not state["done"] and state["smc"] < BUSY_TIMEOUT_SMC * 8:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                await ReadOnly()
                busy = cg.sample_bit(dut, "tb_zeroer_busy") == 1
                bus_act = cg.sample_bit(dut, "tb_zeroer_bus_active") == 1
                axi_v = dut.tb_zeroer_gated_axi_clk.value
                reg_v = dut.tb_zeroer_gated_reg_clk.value
                if axi_v.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_axi_clk sample is X/Z")
                if reg_v.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_reg_clk sample is X/Z")
                axi_on = int(axi_v) == 1
                reg_on = int(reg_v) == 1
                await Timer(1, unit="ps")
                if bus_act:
                    if busy:
                        state["busy_during"] = True
                    if state["active_at"] < 0:
                        state["active_at"] = state["smc"]
                    state["active_cycles"] += 1
                    if axi_on:
                        state["axi_hits_all"] += 1
                    if state["resume_at"] < 0 and reg_on:
                        state["resume_at"] = state["smc"]
                    if state["resume_at"] >= 0:
                        state["post_resume_cycles"] += 1
                        if axi_on:
                            state["axi_hits_post"] += 1
                        if reg_on:
                            state["reg_hits_post"] += 1
                elif state["active_at"] >= 0 and not bus_act:
                    state["done"] = True
                    return

        mon = cocotb.start_soon(_mon())
        # SF-004: any AXI4-Lite access to Zeroer register block.
        _ = await self.csr_read("ZEROER_DEST_ADDR_ACT", ZEROER_CTRL_DEST_ADDR, length=8)
        for _ in range(BUSY_TIMEOUT_SMC * 8):
            if state["done"]:
                break
            await RisingEdge(dut.clk_smc_i)
        mon.cancel()
        assert state["active_at"] >= 0, "zeroer bus_active never asserted (S2)"
        assert not state["busy_during"], (
            "S2 violated axi-idle: zeroer_busy asserted during register access"
        )
        assert state["resume_at"] >= 0, "reg_clk did not resume after access (S2)"
        resume_delta = max(0, state["resume_at"] - state["active_at"])
        assert resume_delta <= 1, (
            f"S2 reg_clk resume not within 1 cycle of bus_active: delta={resume_delta}"
        )
        assert state["done"], (
            "TIMEOUT waiting S2 bus_active clear during dual-clock monitor "
            f"post_resume_cycles={state['post_resume_cycles']} "
            f"busy={cg.sample_bit(dut, 'tb_zeroer_busy')} "
            f"bus_active={cg.sample_bit(dut, 'tb_zeroer_bus_active')}"
        )
        return (
            state["post_resume_cycles"],
            state["axi_hits_post"],
            state["reg_hits_post"],
            state["axi_hits_all"],
        )

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_zeroer_cg_en",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            "tb_zeroer_busy",
            "tb_zeroer_bus_active",
            "rst_cool_ni",
            "rst_primary_smc_clk_no",
        ):
            assert hasattr(dut, port), f"missing TB port {port}"

        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_MODEL_SIZE
            )
        await self._program_output_fabric_pass_all()
        # Seed the first 8 bytes of the destination; the Zeroer SIZE provides
        # the busy window.
        await self._write_bytes(OUTPUT_FABRIC_ADDR, ZEROER_POISON[:8])

        # disable_cg=0 (zeroer_cg_en=1), out of reset.
        await self._program_cg(zeroer_en=True, hyst=HYST)
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 1
        assert int(dut.rst_primary_smc_clk_no.value) == 1

        # ---- S1: axi-active + register-idle → axi on / reg off ----
        cg.log_step(
            "S1",
            "disable_cg=0: axi-active (busy) + register-idle → "
            "axi_clk every cycle, reg_clk gated off",
        )
        w1, axi1, reg1 = await self._observe_axi_active_reg_idle()
        assert w1 > 0, "S1 observation window empty"
        assert axi1 == w1, f"S1 axi_clk missing toggles while busy: axi_hits={axi1} window={w1}"
        assert reg1 == 0, (
            f"S1 reg_clk still toggling in register-idle window: reg_hits={reg1} window={w1}"
        )
        # Coupled = both enabled or both gated under the asymmetric cell.
        coupled_s1 = (axi1 == w1 and reg1 == w1) or (axi1 == 0 and reg1 == 0)
        assert not coupled_s1, f"S1 domains coupled: axi_hits={axi1} reg_hits={reg1} window={w1}"
        await self._wait_zeroer_idle()
        s1_ok = int(axi1 == w1 and reg1 == 0)
        cg.mark_fence(self.fence, "axi-active-reg-idle-decoupled-observed")

        # Settle both domains idle/gated before S2.
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_axi_clk",
            hyst=HYST,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_busy", "tb_zeroer_cg_en"),
        )
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_reg_clk",
            hyst=HYST,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_bus_active", "tb_zeroer_cg_en"),
        )
        assert cg.sample_bit(dut, "tb_zeroer_busy") == 0

        # ---- S2: register-active + axi-idle → reg on / axi off ----
        cg.log_step(
            "S2",
            "disable_cg=0: register-active (AXI4-Lite) + axi-idle → "
            "reg_clk every cycle, axi_clk gated off",
        )
        w2, axi2_post, reg2, axi2_all = await self._observe_reg_active_axi_idle()
        assert w2 >= MIN_S2_WINDOW, (
            f"S2 post-resume observation window too short to support an "
            f"'every cycle' claim: post_resume_cycles={w2} < "
            f"MIN_S2_WINDOW={MIN_S2_WINDOW}"
        )
        assert reg2 == w2, (
            f"S2 reg_clk missing toggles after resume: reg_hits={reg2} post_resume_cycles={w2}"
        )
        assert axi2_all == 0, (
            f"S2 axi_clk still toggling while idle: axi_hits_all={axi2_all} post_resume_cycles={w2}"
        )
        coupled_s2 = (axi2_post == w2 and reg2 == w2) or (axi2_post == 0 and reg2 == 0)
        assert not coupled_s2, (
            f"S2 domains coupled: axi_hits_post={axi2_post} reg_hits={reg2} post_resume_cycles={w2}"
        )
        s2_ok = int(reg2 == w2 and axi2_all == 0)
        cg.mark_fence(self.fence, "reg-active-axi-idle-decoupled-observed")

        cg.emit_chk(
            self.chk_seen,
            "CHK-ZINDEP-DECOUPLE",
            "CHK-ZINDEP-DECOUPLE: (S1 axi-active-reg-idle-decoupled) with disable_cg=0 "
            f"and out of reset, during the axi-active / register-idle window "
            f"axi_clk toggles every cycle and reg_clk is gated off for the whole "
            f"window (s1_ok={s1_ok} window={w1} axi_hits={axi1} reg_hits={reg1}); "
            f"(S2 reg-active-axi-idle-decoupled) during the register-active / "
            f"axi-idle window reg_clk toggles every cycle and axi_clk is gated off "
            f"for the whole window (s2_ok={s2_ok} post_resume_cycles={w2} "
            f"reg_hits={reg2} axi_hits_all={axi2_all})",
        )

        # `assert_fence_progress` requires strictly increasing simulation
        # timestamps across the listed phases (order alone holds by
        # construction) and returns them for the token below.
        fence_times = cg.assert_fence_progress(
            self.fence,
            [
                "axi-active-reg-idle-decoupled-observed",
                "reg-active-axi-idle-decoupled-observed",
            ],
        )
        # Measured contrast carried in the token: in each window one domain ran
        # every cycle while the OTHER was gated off for the whole window. A
        # coupled (or dead) pair of clocks fails here, not silently.
        assert axi1 == w1 and reg1 == 0 and w1 > 0, (
            f"S1 NONVAC contrast absent: window={w1} axi_hits={axi1} reg_hits={reg1}"
        )
        assert reg2 == w2 and axi2_all == 0 and w2 >= MIN_S2_WINDOW, (
            f"S2 NONVAC contrast absent: post_resume_cycles={w2} "
            f"reg_hits={reg2} axi_hits_all={axi2_all}"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: axi-active-reg-idle-decoupled-observed@{}ns < "
            "reg-active-axi-idle-decoupled-observed@{}ns < PASS "
            "S1(window={} axi_hits={} reg_hits={}) "
            "S2(post_resume_cycles={} min={} reg_hits={} axi_hits_all={})".format(
                fence_times[0],
                fence_times[1],
                w1,
                axi1,
                reg1,
                w2,
                MIN_S2_WINDOW,
                reg2,
                axi2_all,
            ),
        )
        cg.mark_fence(self.fence, "PASS")
        cocotb.log.info("smc_zeroer_cg_indep_test_seq PASS")
