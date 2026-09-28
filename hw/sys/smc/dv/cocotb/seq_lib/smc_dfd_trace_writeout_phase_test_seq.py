# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the phase of sink-mode writes against the DST flush and the memory write-out.

Every address, field position, width, reset value and software-access type
comes from the generated register map through :mod:`seq_lib.smc_rdl_regmap`
and :mod:`seq_lib.smc_cla_regmap`. Values programmed into a field come from
that field's own RDL description or from what this sequence measures. The
vendored RTL is not a source for any value this sequence programs or compares
against.

Two control events of the trace path last only a few cycles, and a register
write lands on them only at the right delay:

* **The flush a memory-mode arm causes.** With the trace running on the
  neutral action, the sink is armed in memory mode, and the stop action is
  written a delay after the arm. The delay is walked over 16 values under three
  frame lengths (128, 192 and 256 bytes), which move the end of the flush the
  arm causes, so the stop lands before, on and after that end.
* **The sink's memory write-out.** The bench accepts one write-out per reset,
  so each attempt starts with a cool reset. The trace is programmed afresh with
  256-byte frames and started, and after a delay the sink is switched to memory
  mode and at once back to RAM mode. The delay between the start and the
  switch is walked over 64 values, so the switch back lands at every cycle of
  a frame's fill and of the sink's read-out of it.

The witnesses are the register contract: the sink control reads back in RAM
mode after every attempt, the chain reads node 0, and after the last attempt
the start action moves the write pointer.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_reset_item import SmcResetOp

from .smc_cla_regmap import cla_field, cla_register
from .smc_dfd_trace_accumulator_fill_test_seq import (
    dfd_register,
    dst_register,
    funnel_register,
    pack_fields,
    reg_field,
    sink_register,
)
from .smc_dfd_trace_reset_test_seq import smc_dfd_trace_reset_test_seq

# clk_ref_i edges. The assert bound exceeds the cool reset's 32-sample
# de-glitch window; the release bound covers the release and warm re-release.
_COOL_ASSERT_BOUND_REF = 400
_COOL_RELEASE_BOUND_REF = 4000
_SETTLE_CYCLES = 16
# dfd_dst.rdl Trdstimpl: frame length encodings of 128, 192 and 256 bytes, and
# the reset stream-length encoding.
_FLUSH_FRAME_LENGTHS = (2, 3, 4)
_WRITEOUT_FRAME_LENGTH = 4
_STREAM_LENGTH = 4
_STOP_DELAYS = 16
_WRITEOUT_DELAYS = 64


class smc_dfd_trace_writeout_phase_test_seq(smc_dfd_trace_reset_test_seq):
    """Walk sink-mode and stop writes across the flush and write-out windows."""

    def __init__(self, name: str = "smc_dfd_trace_writeout_phase_test_seq") -> None:
        super().__init__(name)
        self.stop_attempts = 0
        self.writeout_attempts = 0

    async def _cool_reset(self) -> None:
        await self._send(SmcResetOp.COOL_RST_LO, item_name="cool_rst_lo")
        await self._await_level("rst_primary_smc_clk_no", 0, _COOL_ASSERT_BOUND_REF, "ASSERT")
        await self._send(SmcResetOp.COOL_RST_HI, item_name="cool_rst_hi")
        await self._await_level("rst_primary_smc_clk_no", 1, _COOL_RELEASE_BOUND_REF, "RELEASE")
        await self._await_level("tb_rst_warm_smc_clk_n", 1, _COOL_RELEASE_BOUND_REF, "RELEASE_WARM")
        await self.wait_fuse_sense_done()

    async def _impl(self, length: int, label: str) -> None:
        impl = dst_register("Trdstimpl")
        await self._write(
            impl,
            pack_fields(
                impl,
                {"Trdstvendorframelength": length, "Trdstvendorstreamlength": _STREAM_LENGTH},
            ),
            label,
        )

    async def _path(self, label: str) -> None:
        """Program the trace path from reset, the CLA armed but not yet acting."""
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write(clk, pack_fields(clk, {"force_clk_en": 1}), f"{label}_force")
        funnel = funnel_register("Trfunnelcontrol")
        await self._write(
            funnel,
            pack_fields(funnel, {"Trfunnelactive": 1, "Trfunnelenable": 1}),
            f"{label}_funnel",
        )
        await self._impl(_WRITEOUT_FRAME_LENGTH, f"{label}_impl")
        await self._open_sink(0, f"{label}_ram")
        await self._dst(1, f"{label}_dst")
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        await self._write(
            ctrl,
            pack_fields(
                ctrl,
                {
                    "EnableCla": 1,
                    "EnableEap": 1,
                    "DisableGlobalClockHalt": 1,
                    "DisableLocalClockHalt": 1,
                    "ClaChainLoopDelay": (ctrl.reset_word & chain.mask) >> chain.offset,
                },
            ),
            f"{label}_cla",
        )

    async def _sink_mode(self, label: str) -> int:
        control = sink_register("Trdstramcontrol")
        mode = reg_field(control, "Trdstrammode")
        return (await self._read(control, label) & mode.mask) >> mode.offset

    async def _stop_phases(self) -> None:
        for length in _FLUSH_FRAME_LENGTHS:
            await self._impl(length, f"flush{length}")
            for delay in range(_STOP_DELAYS):
                label = f"flush{length}_{delay}"
                await self._open_sink(0, f"{label}_ram")
                await self._action(self.start_action, f"{label}_start")
                await self._settle()
                await self._action(self.neutral_action, f"{label}_run")
                await self._settle()
                await self._open_sink(1, f"{label}_mem")
                await ClockCycles(cocotb.top.clk_smc_i, 1 + delay)
                await self._action(self.stop_action, f"{label}_stop")
                await self._settle(4 * _SETTLE_CYCLES)
                await self._action(self.neutral_action, f"{label}_quiet")
                self.stop_attempts += 1
        await self._open_sink(0, "flush_done")
        mode = await self._sink_mode("flush_done")
        assert mode == 0, f"Trdstrammode reads {mode} after the RAM-mode re-arm"
        self.value_checks += 1

    async def _writeout_phases(self) -> None:
        for delay in range(_WRITEOUT_DELAYS):
            label = f"out{delay}"
            await self._cool_reset()
            await self._path(label)
            await self._action(self.start_action, f"{label}_start")
            await ClockCycles(cocotb.top.clk_smc_i, 1 + delay)
            await self._sink(1, 1, 0, f"{label}_mem")
            await self._sink(0, 1, 0, f"{label}_back")
            await self._settle(8 * _SETTLE_CYCLES)
            mode = await self._sink_mode(f"{label}_mode")
            assert mode == 0, (
                f"Trdstrammode reads {mode} after the switch back to RAM mode at delay {delay}"
            )
            self.writeout_attempts += 1
            self.value_checks += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._bring_up()
        await self._arm_cla()
        await self._measure_actions()
        cocotb.log.info(
            "CHK-DST-PHASE-ACTIONS: of the Action0 values of node 0 pair 0, %s started the "
            "uncompressed trace and %s stopped it, judged by the sink write pointer; value %d "
            "left a running trace running",
            self.starts,
            self.stops,
            self.neutral_action,
        )

        await self._stop_phases()
        cocotb.log.info(
            "CHK-DST-PHASE-FLUSH: the stop action was written %d cycle delays after a "
            "memory-mode arm under each of %d frame lengths, %d attempts, and the sink read "
            "back in RAM mode once re-armed",
            _STOP_DELAYS,
            len(_FLUSH_FRAME_LENGTHS),
            self.stop_attempts,
        )

        await self._writeout_phases()
        home = await self._current_node("out_home")
        assert home == 0, f"CurrentNode reads {home} after the write-out attempts"
        await self._action(self.start_action, "out_restart")
        assert await self._moving("out_restart"), (
            f"after {self.writeout_attempts} cool resets each followed by a memory-mode switch "
            f"and back, the start action does not move the write pointer"
        )
        self.value_checks += 2
        cocotb.log.info(
            "CHK-DST-PHASE-WRITEOUT: %d times a cool reset, a fresh trace path started, then the "
            "sink switched to memory mode and back to RAM mode 1 to %d cycles after the start; "
            "the sink read back in RAM mode each time, the chain read node 0 and the start "
            "action moved the write pointer",
            self.writeout_attempts,
            _WRITEOUT_DELAYS,
        )

        for reg, _ in self._programmed():
            await self._write(reg, reg.reset_word, "restore")
