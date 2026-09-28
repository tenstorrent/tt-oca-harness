# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CLA node 0 actions, programmed over JTAG2AXI, observed at the SMU.

The CLA node 0 event-action pair evaluates LogicalOp NOR over the two "none"
event types, so its actions hold for as long as the pair is programmed
(``smc_cla_boot.h`` programs the SEP release the same way). The custom actions
leave the SMC ungated (``smc_dfd_wrap.sv``); the cross-trigger actions leave it
through ``DEBUG_CTRL.XTRIG_CLK_HALT_MASK[0]``, and the clock-halt action is a
sticky flop (``cla_action_gen.sv``) reported as ``clocks_stopped_by_cla`` while
the SMU ``DEBUG_CONTROL`` CLA clock-stop enable is set.

S1: each custom action k in 0..15, programmed alone, drives exactly bit k of
    the custom action bus; a pair with neither custom enable clears the bus.
S2: with the mask bit set and a pulse width programmed, XTRIGGER0_OUT and
    XTRIGGER1_OUT raise both SMC cross-trigger lanes into the DTP, and once
    the actions are cleared the lanes fall within the pulse width.
S3: with local clock halt disabled and the clock-stop enable set, CLOCK_HALT
    raises clocks_stopped_by_cla and the DTP clock-stop request lane 0;
    clearing the enable drops both.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.smu_addr_map import cla_u32, dfx_ctrl_status_u32, smc_addr, smc_indexed_addr
from seq_lib.smu_axi_out_addr_len_size_test_seq import smu_axi_out_addr_len_size_test_seq
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    pack_debug_control,
)
from seq_lib.smu_tb_pins import smu_scope

CTRLSTATUS = smc_indexed_addr("SMC_TOP_SMC_CLA_CLA_CDBGCLACTRLSTATUS_BASE_ADDR", 0)
EAP0 = smc_indexed_addr("SMC_TOP_SMC_CLA_CLA_CDBGNODE0EAP0_BASE_ADDR", 0)
EAP1 = smc_indexed_addr("SMC_TOP_SMC_CLA_CLA_CDBGNODE0EAP1_BASE_ADDR", 0)
STRETCH = smc_indexed_addr("SMC_TOP_SMC_CLA_CLA_CDBGCLAXTRIGGERTIMESTRETCH_BASE_ADDR", 0)
DEBUG_CTRL = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR")

_EAP = "DFD_CLA__CDBGNODE0EAP0__"
_CTRL = "DFD_CLA__CDBGCLACTRLSTATUS__"


def _field(prefix: str, name: str, value: int) -> int:
    return (value << cla_u32(f"{prefix}{name}_bp")) & cla_u32(f"{prefix}{name}_bm")


# cla_pkg.svh action codes and the "none" event types the SEP release uses.
ACTION_CLOCK_HALT = 1
ACTION_XTRIGGER0_OUT = 7
ACTION_XTRIGGER1_OUT = 8
LOGICAL_OP_NOR = 3
EVENT_NONE0 = 63
EVENT_NONE1 = 62
NUM_CUSTOM = 16

EAP_ALWAYS = (
    _field(_EAP, "LOGICALOP", LOGICAL_OP_NOR)
    | _field(_EAP, "EVENTTYPE0", EVENT_NONE0)
    | _field(_EAP, "EVENTTYPE1", EVENT_NONE1)
)
CTRL_ENABLE = cla_u32(f"{_CTRL}ENABLECLA_bm") | cla_u32(f"{_CTRL}ENABLEEAP_bm")
CTRL_NO_LOCAL_HALT = CTRL_ENABLE | cla_u32(f"{_CTRL}DISABLELOCALCLOCKHALT_bm")
XTRIG_MASK0 = 1 << dfx_ctrl_status_u32("DFX_CTRL_STATUS__DEBUG_CTRL__XTRIG_CLK_HALT_MASK_bp")

SETTLE_CYCLES = 64
# Cross-trigger pulse width in CLA clocks. With a width of 0 the stretch
# circuit holds the output until reset (xtrigger_stretch_circuit.sv).
XTRIGGER_STRETCH = 0x40
STRETCH_BOTH = _field(
    "DFD_CLA__CDBGCLAXTRIGGERTIMESTRETCH__", "XTRIGGER0STRETCH", XTRIGGER_STRETCH
) | _field("DFD_CLA__CDBGCLAXTRIGGERTIMESTRETCH__", "XTRIGGER1STRETCH", XTRIGGER_STRETCH)
PULSE_DRAIN_CYCLES = 2000


def eap_custom(k: int) -> int:
    """Node 0 pair firing custom action k on both custom slots."""
    return (
        EAP_ALWAYS
        | _field(_EAP, "CUSTOMACTION0", k)
        | _field(_EAP, "CUSTOMACTION1", k)
        | cla_u32(f"{_EAP}CUSTOMACTION0ENABLE_bm")
        | cla_u32(f"{_EAP}CUSTOMACTION1ENABLE_bm")
    )


def eap_actions(action0: int, action1: int) -> int:
    return EAP_ALWAYS | _field(_EAP, "ACTION0", action0) | _field(_EAP, "ACTION1", action1)


class smu_cla_action_test_seq(smu_axi_out_addr_len_size_test_seq):
    """CLA custom, cross-trigger and clock-halt actions from JTAG2AXI programming."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps = {"S1": False, "S2": False, "S3": False}

    def _smu(self, name: str) -> int:
        return sample(hier(smu_scope(self.dut), name), name)

    async def _wr(self, jtag, addr: int, data: int, name: str) -> None:
        status, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:x} status={status}")

    async def _rd(self, jtag, addr: int, name: str) -> int:
        status, data = await jtag2axi_single_read(jtag, addr, require_complete=True)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} @0x{addr:x} status={status}")
        return data

    async def _program(self, jtag, ctrl: int, eap0: int) -> None:
        await self._wr(jtag, CTRLSTATUS, ctrl, "CTRLSTATUS")
        await self._wr(jtag, EAP0, eap0, "EAP0")
        await self._wr(jtag, EAP1, 0, "EAP1")
        await ClockCycles(self.dut.clk_smu_i, SETTLE_CYCLES)

    async def _custom(self, jtag, sb) -> None:
        observed, want = {}, {}
        for k in range(NUM_CUSTOM):
            await self._program(jtag, CTRL_ENABLE, eap_custom(k))
            observed[k] = self._smu("cla_ext_action_custom")
            want[k] = 1 << k
        await self._program(jtag, CTRL_ENABLE, EAP_ALWAYS)
        observed["cleared"] = self._smu("cla_ext_action_custom")
        want["cleared"] = 0
        self._log(f"CHK-CLA-CUSTOM-ACTION {observed}")
        sb.expect_eq("CHK-CLA-CUSTOM-ACTION", observed, want, evidence="CHK-CLA-CUSTOM-ACTION")
        self.steps["S1"] = True

    async def _watch_lanes(self, seen: list[int], stop: list[bool]) -> None:
        while not stop[0]:
            await ClockCycles(self.dut.clk_smu_i, 1)
            seen[0] |= self._smu("smc_xtrigger_ss_o")
            seen[1] |= self._smu("dtp_xtrig_ctm_dst_req") & 0x3

    async def _xtrigger(self, jtag, sb) -> int:
        debug_ctrl = await self._rd(jtag, DEBUG_CTRL, "DEBUG_CTRL")
        await self._wr(jtag, DEBUG_CTRL, debug_ctrl | XTRIG_MASK0, "DEBUG_CTRL")
        await self._wr(jtag, STRETCH, STRETCH_BOTH, "XTRIGGERTIMESTRETCH")
        seen, stop = [0, 0], [False]
        watcher = cocotb.start_soon(self._watch_lanes(seen, stop))
        await self._program(
            jtag, CTRL_ENABLE, eap_actions(ACTION_XTRIGGER0_OUT, ACTION_XTRIGGER1_OUT)
        )
        stop[0] = True
        await watcher
        await self._program(jtag, CTRL_ENABLE, EAP_ALWAYS)
        await ClockCycles(self.dut.clk_smu_i, PULSE_DRAIN_CYCLES)
        dropped = (self._smu("smc_xtrigger_ss_o"), self._smu("dtp_xtrig_ctm_dst_req") & 0x3)
        raised = tuple(seen)
        self._log(f"CHK-CLA-XTRIGGER raised={raised} dropped={dropped}")
        sb.expect_eq(
            "CHK-CLA-XTRIGGER",
            (raised, dropped),
            ((0x3, 0x3), (0, 0)),
            evidence="CHK-CLA-XTRIGGER",
        )
        self.steps["S2"] = True
        return debug_ctrl

    async def _clock_halt(self, jtag, sb, debug_ctrl: int) -> None:
        await jtag.write("DEBUG_CONTROL", pack_debug_control(cla_clock_stop_en=1))
        await self._program(jtag, CTRL_NO_LOCAL_HALT, eap_actions(ACTION_CLOCK_HALT, 0))
        raised = (
            self._smu("tdr_dbg_ctrl_clocks_stopped_by_cla"),
            self._smu("dtp_xtrig_clk_stop_req") & 0x1,
        )
        await self._program(jtag, CTRL_NO_LOCAL_HALT, EAP_ALWAYS)
        await jtag.write("DEBUG_CONTROL", pack_debug_control())
        await ClockCycles(self.dut.clk_smu_i, SETTLE_CYCLES)
        dropped = (
            self._smu("tdr_dbg_ctrl_clocks_stopped_by_cla"),
            self._smu("dtp_xtrig_clk_stop_req") & 0x1,
        )
        await self._wr(jtag, DEBUG_CTRL, debug_ctrl, "DEBUG_CTRL")
        self._log(f"CHK-CLA-CLOCK-HALT raised={raised} dropped={dropped}")
        sb.expect_eq(
            "CHK-CLA-CLOCK-HALT",
            (raised, dropped),
            ((1, 1), (0, 0)),
            evidence="CHK-CLA-CLOCK-HALT",
        )
        self.steps["S3"] = True

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(self.dut.clk_smu_i, 16)
        jtag = await self._bring_up_tap()
        await self._custom(jtag, sb)
        debug_ctrl = await self._xtrigger(jtag, sb)
        await self._clock_halt(jtag, sb, debug_ctrl)
        await ClockCycles(self.dut.clk_smu_i, 2)
        cocotb.log.info("CLA action sweep complete")
