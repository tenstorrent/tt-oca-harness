# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CLA node 0 actions, programmed over JTAG2AXI, observed at the SMU.

The CLA register description (``dfd_cla.rdl``) gives each field's position
but not the encodings of ACTION0/ACTION1, LOGICALOP or EVENTTYPE0/1. The pair
is LogicalOp NOR over two "none" event types, as the SMC CLA boot firmware
programs it (``smc_cla_boot.h``), which holds its actions for as long as it
is programmed. The action codes 1, 7 and 8, for clock halt and the two
cross-trigger outputs, have no documented source. No compare depends on what
those codes mean: the nets they drive are recorded, and the compares are the
ones the register descriptions state.

S1: CUSTOMACTION0/1 "select the bit position of custom action bus to be set
    when EAP trigger is met" (``dfd_cla.rdl``), so each custom action k in
    0..15, programmed alone with both custom enables, drives exactly bit k of
    the custom action bus, and a pair with neither custom enable clears it.
S2: DEBUG_CTRL.XTRIG_CLK_HALT_MASK is "Mask==0 (default) -> disabled"
    (``dfx_ctrl_status.rdl``): with every mask bit clear, the pair programmed
    with the two cross-trigger action codes leaves both SMC cross-trigger
    lanes into the DTP low. With mask bit 0 set and a pulse width programmed,
    the lanes the same pair raises, and their level once it is cleared, are
    recorded.
S3: DEBUG_CONTROL.cla_clock_stop_en gates the CLA clock stop: "the clocks
    will actually have been stopped only when cla_clock_stop_en is set"
    (``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``). With local clock halt
    disabled and the enable set, a pair with no action leaves
    clocks_stopped_by_cla and DTP clock-stop request lane 0 low; the clock
    halt action code is then programmed and both are recorded; clearing the
    enable with the action still programmed drops the request, and the
    report left after the enable, then the action, is cleared is recorded.
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


# The "none" event types smc_cla_boot.h pairs under LogicalOp NOR, and the
# action codes; no register description gives these encodings.
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
XTRIG_MASK_ALL = dfx_ctrl_status_u32("DFX_CTRL_STATUS__DEBUG_CTRL__XTRIG_CLK_HALT_MASK_bm")

SETTLE_CYCLES = 64
# Cross-trigger pulse width in CLA clocks.
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

    async def _xtrigger_pass(self) -> list[int]:
        seen, stop = [0, 0], [False]
        watcher = cocotb.start_soon(self._watch_lanes(seen, stop))
        await self._program(
            self._jtag, CTRL_ENABLE, eap_actions(ACTION_XTRIGGER0_OUT, ACTION_XTRIGGER1_OUT)
        )
        stop[0] = True
        await watcher
        await self._program(self._jtag, CTRL_ENABLE, EAP_ALWAYS)
        await ClockCycles(self.dut.clk_smu_i, PULSE_DRAIN_CYCLES)
        return seen

    async def _xtrigger(self, jtag, sb) -> int:
        self._jtag = jtag
        debug_ctrl = await self._rd(jtag, DEBUG_CTRL, "DEBUG_CTRL")
        await self._wr(jtag, STRETCH, STRETCH_BOTH, "XTRIGGERTIMESTRETCH")
        await self._wr(jtag, DEBUG_CTRL, debug_ctrl & ~XTRIG_MASK_ALL, "DEBUG_CTRL")
        masked = tuple(await self._xtrigger_pass())
        await self._wr(jtag, DEBUG_CTRL, (debug_ctrl & ~XTRIG_MASK_ALL) | XTRIG_MASK0, "DEBUG_CTRL")
        raised = tuple(await self._xtrigger_pass())
        dropped = (self._smu("smc_xtrigger_ss_o"), self._smu("dtp_xtrig_ctm_dst_req") & 0x3)
        self._log(f"CHK-CLA-XTRIGGER masked={masked}")
        self._log(f"OBSERVATION CHK-CLA-XTRIGGER mask0 raised={raised} after clear={dropped}")
        sb.expect_eq(
            "CHK-CLA-XTRIGGER every mask bit clear holds both cross-trigger lanes low",
            masked,
            (0, 0),
            evidence="CHK-CLA-XTRIGGER",
        )
        self.steps["S2"] = True
        return debug_ctrl

    def _halt_state(self) -> tuple[int, int]:
        return (
            self._smu("tdr_dbg_ctrl_clocks_stopped_by_cla"),
            self._smu("dtp_xtrig_clk_stop_req") & 0x1,
        )

    async def _clock_halt(self, jtag, sb, debug_ctrl: int) -> None:
        await jtag.write("DEBUG_CONTROL", pack_debug_control(cla_clock_stop_en=1))
        await self._program(jtag, CTRL_NO_LOCAL_HALT, EAP_ALWAYS)
        idle = self._halt_state()
        await self._program(jtag, CTRL_NO_LOCAL_HALT, eap_actions(ACTION_CLOCK_HALT, 0))
        raised = self._halt_state()
        await jtag.write("DEBUG_CONTROL", pack_debug_control())
        await ClockCycles(self.dut.clk_smu_i, SETTLE_CYCLES)
        disabled = self._halt_state()
        await self._program(jtag, CTRL_NO_LOCAL_HALT, EAP_ALWAYS)
        cleared = self._halt_state()
        await self._wr(jtag, DEBUG_CTRL, debug_ctrl, "DEBUG_CTRL")
        self._log(f"CHK-CLA-CLOCK-HALT idle={idle} request_with_enable_clear={disabled[1]}")
        self._log(
            f"OBSERVATION CHK-CLA-CLOCK-HALT (report, request) action={raised} "
            f"enable_cleared={disabled} action_cleared={cleared}"
        )
        sb.expect_eq(
            "CHK-CLA-CLOCK-HALT",
            (idle, disabled[1]),
            ((0, 0), 0),
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
