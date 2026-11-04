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
  frame lengths (128, 256 and 512 bytes), which move the end of the flush the
  arm causes, so the stop lands before, on and after that end.
* **The sink's memory write-out.** The bench accepts one write-out per reset,
  so each attempt starts with a cool reset. The trace is programmed afresh with
  256-byte frames and started, and after a delay the sink is switched to memory
  mode, read back in memory mode, and switched back to RAM mode. The delay
  between the start and the switch is walked over 64 values, so the switch
  back lands at every cycle of a frame's fill and of the sink's read-out of
  it.

The witnesses are the register contract: the sink control reads back in RAM
mode after every attempt, the chain reads node 0, and after the last attempt
the start action moves the write pointer.

Every frame length the sequence programs is one of the 1, 2, 4 and 8 that
``dfd_dst.rdl`` names as supported for ``Trdstimpl.Trdstvendorframelength``,
and the sink's ``Trdstramimpl.Trdstramvendorframelength`` is written the same
value, as both descriptions require. Before the phase walks, each of the four
lengths carries a short uncompressed stream from the start action to the stop
action in RAM mode; the parked write pointer has moved and is a multiple of
64 times the length, the frame boundary the sink description places at the
power of two of its frame length.
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
# dfd_dst.rdl Trdstimpl: the four supported frame length encodings (64, 128, 256
# and 512 bytes), the three the flush walk uses, and the reset stream-length
# encoding.
_SUPPORTED_FRAME_LENGTHS = (1, 2, 4, 8)
_FLUSH_FRAME_LENGTHS = (2, 4, 8)
_WRITEOUT_FRAME_LENGTH = 4
_STREAM_LENGTH = 4
_STOP_DELAYS = 16
_WRITEOUT_DELAYS = 64
# dfd.adoc: the eight trace RAMs hold 16 KiB; the alignment streams use all of it.
_ALIGNMENT_WINDOW_BYTES = 0x4000
_FRAME_UNIT_BYTES = 64


class smc_dfd_trace_writeout_phase_test_seq(smc_dfd_trace_reset_test_seq):
    """Walk sink-mode and stop writes across the flush and write-out windows."""

    def __init__(self, name: str = "smc_dfd_trace_writeout_phase_test_seq") -> None:
        super().__init__(name)
        self.stop_attempts = 0
        self.writeout_attempts = 0
        self.parked: dict[int, int] = {}
        self.flush_modes: list[int] = []
        self.writeout_pointers: list[int] = []

    async def _cool_reset(self) -> None:
        await self._send(SmcResetOp.COOL_RST_LO, item_name="cool_rst_lo")
        await self._await_level("rst_primary_smc_clk_no", 0, _COOL_ASSERT_BOUND_REF, "ASSERT")
        await self._send(SmcResetOp.COOL_RST_HI, item_name="cool_rst_hi")
        await self._await_level("rst_primary_smc_clk_no", 1, _COOL_RELEASE_BOUND_REF, "RELEASE")
        await self._await_level("tb_rst_warm_smc_clk_n", 1, _COOL_RELEASE_BOUND_REF, "RELEASE_WARM")
        await self.wait_fuse_sense_done()

    async def _impl(self, length: int, label: str) -> None:
        """One frame length on the DST and the same value on the sink."""
        assert length in _SUPPORTED_FRAME_LENGTHS, f"frame length {length} is not supported"
        await self._write_check(
            dst_register("Trdstimpl"),
            {"Trdstvendorframelength": length, "Trdstvendorstreamlength": _STREAM_LENGTH},
            label,
        )
        await self._write_check(
            sink_register("Trdstramimpl"), {"Trdstramvendorframelength": length}, f"{label}_sink"
        )

    async def _action_landed(self, value: int, label: str) -> None:
        """Read node 0 pair 0 back and require its Action0 field to hold `value`."""
        eap = cla_register("CDbgNode0Eap0")
        field = cla_field(eap, "Action0")
        word = await self._read(eap, label)
        landed = (word & field.mask) >> field.offset
        assert landed == value, (
            f"CDbgNode0Eap0.Action0 reads {landed} after the write of {value} [{label}]"
        )
        self.value_checks += 1

    async def _frame_alignment(self) -> None:
        """Park the stream under each supported frame length and read the pointer."""
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        for length in _SUPPORTED_FRAME_LENGTHS:
            label = f"align{length}"
            await self._impl(length, label)
            await self._open_sink(0, label, window=_ALIGNMENT_WINDOW_BYTES)
            await self._action(self.start_action, f"{label}_start")
            await self._settle(2 * _SETTLE_CYCLES)
            await self._action(self.stop_action, f"{label}_stop")
            await self._settle(4 * _SETTLE_CYCLES)
            await self._action_landed(self.stop_action, f"{label}_stop_rb")
            first = await self._read(wp, f"{label}_wp0") & pointer.mask
            await self._settle(2 * _SETTLE_CYCLES)
            second = await self._read(wp, f"{label}_wp1") & pointer.mask
            frame_bytes = _FRAME_UNIT_BYTES * length
            assert second == first and 0 < first <= _ALIGNMENT_WINDOW_BYTES, (
                f"CHK-DST-FRAME-LENGTH-MATCH FAIL: with Trdstvendorframelength and "
                f"Trdstramvendorframelength {length} the write pointer read 0x{first:x} then "
                f"0x{second:x} after the stop action, not parked inside the "
                f"0x{_ALIGNMENT_WINDOW_BYTES:x}-byte window past the start"
            )
            assert first % frame_bytes == 0, (
                f"CHK-DST-FRAME-LENGTH-MATCH FAIL: with Trdstvendorframelength and "
                f"Trdstramvendorframelength {length} the write pointer parked at 0x{first:x} "
                f"after the stop action, not a multiple of the {frame_bytes}-byte frame"
            )
            self.parked[length] = first
            self.value_checks += 2
            await self._action(self.neutral_action, f"{label}_quiet")
        cocotb.log.info(
            "CHK-DST-FRAME-LENGTH-MATCH: with the DST and sink frame lengths equal at each of "
            "%s, the stream from the start action parked the write pointer at %s after the "
            "stop action, each a multiple of 64 times the length and each past the start",
            list(_SUPPORTED_FRAME_LENGTHS),
            {length: hex(word) for length, word in self.parked.items()},
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
                await self._action_landed(self.neutral_action, f"{label}_run_rb")
                assert await self._moving(f"{label}_run"), (
                    f"the write pointer is not moving on the neutral action after the start "
                    f"action under frame length {length} at delay {delay}, so the memory-mode "
                    f"arm would land on a dead trace"
                )
                await self._open_sink(1, f"{label}_mem")
                await ClockCycles(cocotb.top.clk_smc_i, 1 + delay)
                await self._action(self.stop_action, f"{label}_stop")
                await self._settle(4 * _SETTLE_CYCLES)
                await self._action_landed(self.stop_action, f"{label}_stop_rb")
                mode = await self._sink_mode(f"{label}_armed")
                self.flush_modes.append(mode)
                assert mode == 1, (
                    f"Trdstrammode reads {mode} after the memory-mode arm and the stop action "
                    f"under frame length {length} at delay {delay}; the arm did not take"
                )
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
            wp = sink_register("Trdstramwplow")
            pointer = reg_field(wp, "Trdstramwplow")
            before = await self._read(wp, f"{label}_wp0") & pointer.mask
            await self._action(self.start_action, f"{label}_start")
            await ClockCycles(cocotb.top.clk_smc_i, 1 + delay)
            await self._sink(1, 1, 0, f"{label}_mem")
            armed = await self._sink_mode(f"{label}_armed")
            assert armed == 1, (
                f"Trdstrammode reads {armed} after the switch to memory mode at delay {delay}; "
                f"the switch did not take"
            )
            await self._sink(0, 1, 0, f"{label}_back")
            await self._settle(8 * _SETTLE_CYCLES)
            mode = await self._sink_mode(f"{label}_mode")
            assert mode == 0, (
                f"Trdstrammode reads {mode} after the switch back to RAM mode at delay {delay}"
            )
            after = await self._read(wp, f"{label}_wp1") & pointer.mask
            self.writeout_pointers.append(after)
            cocotb.log.info(
                "OBS-DST-WRITEOUT-POINTER delay=%d wp_armed=0x%x wp_after_switch=0x%x",
                1 + delay,
                before,
                after,
            )
            await self._open_sink(0, f"{label}_rearm")
            assert await self._moving(f"{label}_rearm"), (
                f"after the memory-mode switch and the switch back {1 + delay} cycles after the "
                f"start, the re-armed RAM-mode sink's write pointer does not move with the start "
                f"action still selected; the trace path is dead after that switch"
            )
            self.writeout_attempts += 1
            self.value_checks += 3

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

        await self._frame_alignment()
        await self._stop_phases()
        cocotb.log.info(
            "CHK-DST-PHASE-FLUSH: the stop action was written %d cycle delays after a "
            "memory-mode arm under each of %d frame lengths, each length read back on the DST "
            "and the sink, %d attempts; before each arm the neutral action read back and the "
            "write pointer was moving, after each stop the stop action read back and the sink "
            "still read memory mode (%d of %d reads 1), and the sink read back in RAM mode "
            "once re-armed",
            _STOP_DELAYS,
            len(_FLUSH_FRAME_LENGTHS),
            self.stop_attempts,
            self.flush_modes.count(1),
            len(self.flush_modes),
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
            "sink switched to memory mode, read back in memory mode, and switched back to RAM "
            "mode 1 to %d cycles after the start; the sink read back in RAM mode each time "
            "and, re-armed in RAM mode, its write "
            "pointer moved with the start action still selected; the pointer after each switch "
            "is logged (%d distinct values, %s); the chain read node 0 and the start action "
            "moved the write pointer",
            self.writeout_attempts,
            _WRITEOUT_DELAYS,
            len(set(self.writeout_pointers)),
            sorted(hex(v) for v in set(self.writeout_pointers))[:8],
        )

        for reg, _ in self._programmed():
            await self._write(reg, reg.reset_word, "restore")
        sink_impl = sink_register("Trdstramimpl")
        await self._write(sink_impl, sink_impl.reset_word, "restore")
