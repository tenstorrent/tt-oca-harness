# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Drive the DST's trace control through stream lengths, action loops and sink flushes.

Every address, field position, width, reset value and software-access type
comes from the generated register map through :mod:`seq_lib.smc_rdl_regmap`
and :mod:`seq_lib.smc_cla_regmap`. Values programmed into a field come from
that field's own RDL description or from what this sequence measures. The
vendored RTL is not a source for any value this sequence programs or compares
against.

The other trace leaves start the trace with one measured action and stop it
by clearing ``Trdstenable``. This sequence measures, over the whole
``Action0`` field of node 0 pair 0, which values start the uncompressed trace,
which stop it and which leave it as it is, using the sink write pointer as the
witness: it moves while packets arrive and stops once they do not. Those three
values then drive:

* **Register-only corners.** ``Trdstvendorstreamlength`` is written and read
  back in every encoding. The sink is armed twice in memory mode at one start,
  the second time with its limit one 64-byte line above that start, and once
  more in RAM mode with the same window. With the sink set to stop on wrap and
  disabled, which holds the DST back, ``Trfunneldisinput`` takes the bits its
  description gives the DST sources.
* **Streams.** With compression on and the bus still, the only packets are the
  full ones sent at each start and stop. Start/stop pairs run under every
  ``Trdstsyncmode`` value until the write pointer has advanced 64 frames of 64
  bytes, the stream that stream-length encoding 0 describes, so a stream
  fills with the bus idle between packets. Then, uncompressed at the reset
  stream length, the trace runs 128 frames inside a window that does not wrap,
  and the stream length drops to encoding 0 under the running trace, below the
  frames already sent; the write pointer has to keep moving.
* **Action loops.** Node 0 pair 0 starts the trace and moves to node 1, whose
  pair 0 stops it and moves back, so the trace starts and stops on
  consecutive cycles. ``CurrentNode`` has to read 1 once node 1 is made to
  stay, and 0 once both are sent home.
* **Timestamp phases.** With ``Trdstsyncmode`` at the value its description
  names and ``Trdstsyncmax`` at 0, a timestamp is due every 16 cycles. The
  delay between the start and a stop action, and between the start and
  clearing ``Trdstenable``, is walked over 32 values, two periods, so each
  lands at every phase of that period.
* **Frame changes mid-frame.** With ``FrameClosureMode`` 1 the frame length is
  toggled between 128 and 64 bytes 64 times under the running trace, with a
  varying delay between toggles; the write pointer has to keep moving.
* **Sink flushes.** Arming the sink in memory mode with the trace running
  flushes the DST from the sink side. It is armed once with the trace
  running on the neutral action, then four times under each of six loops
  of the start, stop and neutral actions over up to four nodes, so the flush
  reaches the DST while it is tracing, stopping and stopped. The sink is
  re-armed in RAM mode after each, and at the end the start action has to
  move the write pointer again.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import (
    DBM_MODE_NORMAL,
    checked_mask,
    cla_mux_normal,
    dfd_register,
    dst_register,
    field_word,
    find_sampled_mux,
    funnel_register,
    pack_fields,
    reg_field,
    sink_register,
)

# dfd_dst.rdl Trdstformat: 0 is no compression, 3 is XOR and VLT compression.
_DST_FORMAT_NONE = 0
_DST_FORMAT_XOR_VLT = 3
# dfd_dst.rdl Trdstsyncmode: the one value its description names, which sends a
# timestamp every 2^(Trdstsyncmax + 4) cycles; 16 at Trdstsyncmax 0.
_SYNC_MODE_TIMESTAMP = 2
_TIMESTAMP_PERIOD = 16
# dfd_funnel.rdl Trfunneldisinput: bits 15:8 are the DST sources.
_FUNNEL_DST_INPUTS = 0xFF00
# Sink windows, as byte addresses: the working window, one the size of the
# 16 KB trace RAM for the stream legs so the write pointer never wraps, and the
# start and one-line limit of the memory-mode re-arms.
_SINK_WINDOW_BYTES = 0x400
_STREAM_WINDOW_BYTES = 0x4000
_PRELOAD_START = 0x1000
_ONE_LINE_BYTES = 0x40
# dfd_dst.rdl Trdstimpl: frame length encoding 1 is 64 bytes; stream length
# encoding 0 is 32 * 2^(0 + 1) = 64 frames.
_FRAME_BYTES = 64
_SHORT_STREAM_FRAMES = 64
# Frames the uncompressed trace runs before its stream length drops to encoding
# 0: twice that stream, and fewer than the 256 frames the stream window holds.
_OVERRUN_FRAMES = 2 * _SHORT_STREAM_FRAMES
# Frame length encodings toggled mid-frame (128 and 64 bytes) and the toggles.
_TOGGLE_LENGTHS = (2, 1)
_FRAME_TOGGLES = 64
_SETTLE_CYCLES = 16
# Bounds on the start/stop pairs and the overrun polls; ceilings on loops that
# end on the write pointer, never the checked quantity.
_MAX_PAIRS = 1024
_MAX_POLLS = 128
# Neutral-action writes that keep the trace running before the first memory arm.
_RUNNING_WRITES = 24
# Arms per action loop, each after one more cycle of delay.
_ARMS_PER_LOOP = 4
_NODES = 4


class smc_dfd_trace_flush_corner_test_seq(SmcCsrSeq):
    """Measure the trace actions and drive the DST's control corners with them."""

    def __init__(self, name: str = "smc_dfd_trace_flush_corner_test_seq") -> None:
        super().__init__(name)
        self.logical_op = -1
        self.sampled_mux = -1
        self.starts: list[int] = []
        self.stops: list[int] = []
        self.start_action = -1
        self.stop_action = -1
        self.neutral_action = -1
        self.stream_pairs: list[int] = []
        self.overrun_advance: list[int] = []
        self.loop_nodes: tuple[int, int] = (-1, -1)
        self.memory_arms = 0
        self.value_checks = 0

    # -- register helpers -------------------------------------------------

    @staticmethod
    def _short(reg) -> str:
        return reg.path.rsplit("/", 1)[1]

    async def _read(self, reg, label: str) -> int:
        return await self.csr_read(f"{self._short(reg)}:{label}", reg.addr, length=reg.width_bytes)

    async def _write(self, reg, word: int, label: str) -> None:
        await self.csr_write(f"{self._short(reg)}:{label}", reg.addr, word, length=reg.width_bytes)

    async def _write_check(self, reg, values: dict[str, int], label: str) -> None:
        word = pack_fields(reg, values)
        await self._write(reg, word, label)
        readback = await self._read(reg, f"{label}_rb")
        mask = checked_mask(reg, values)
        assert readback & mask == word & mask, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: wrote 0x{word & mask:x} into its "
            f"software-writable bits, reads 0x{readback & mask:x}"
        )
        self.value_checks += 1

    async def _settle(self, cycles: int = _SETTLE_CYCLES) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, cycles)

    async def _dst(
        self, enable: int, label: str, fmt: int = _DST_FORMAT_NONE, sync: int = 0
    ) -> None:
        control = dst_register("Trdstcontrol")
        await self._write(
            control,
            pack_fields(
                control,
                {
                    "Trdstactive": 1,
                    "Trdstenable": enable,
                    "Trdstformat": fmt,
                    "Trdstsyncmode": sync,
                    "Trdstsyncmax": 0,
                },
            ),
            label,
        )

    async def _sink(self, mode: int, enable: int, stop_on_wrap: int, label: str) -> None:
        control = sink_register("Trdstramcontrol")
        await self._write(
            control,
            pack_fields(
                control,
                {
                    "Trdstramactive": 1,
                    "Trdstramenable": enable,
                    "Trdstrammode": mode,
                    "Trdstramstoponwrap": stop_on_wrap,
                },
            ),
            label,
        )

    async def _open_sink(
        self, mode: int, label: str, window: int = _SINK_WINDOW_BYTES, start: int = 0
    ) -> None:
        """Arm the sink afresh: off, then the window and pointers, then on."""
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, f"{label}_off")
        for name, value in (
            ("Trdstramstartlow", start),
            ("Trdstramlimitlow", start + window),
            ("Trdstramwplow", start),
            ("Trdstramrplow", start),
        ):
            reg = sink_register(name)
            await self._write(reg, field_word(reg, name, value), label)
        await self._sink(mode, 1, 0, label)

    async def _action(self, value: int, label: str, node: int = 0, dest: int = 0) -> None:
        eap = cla_register(f"CDbgNode{node}Eap0")
        await self._write(
            eap,
            pack_fields(eap, {"LogicalOp": self.logical_op, "DestNode": dest, "Action0": value}),
            label,
        )

    async def _moving(self, label: str) -> bool:
        """Whether the sink write pointer moves across two settle periods."""
        wp = sink_register("Trdstramwplow")
        first = await self._read(wp, f"{label}_wp0")
        await self._settle(2 * _SETTLE_CYCLES)
        return await self._read(wp, f"{label}_wp1") != first

    async def _current_node(self, label: str) -> int:
        ctrl = cla_register("CDbgClaCtrlStatus")
        current = cla_field(ctrl, "CurrentNode")
        return (await self._read(ctrl, label) & current.mask) >> current.offset

    # -- bring-up ---------------------------------------------------------

    async def _bring_up(self) -> None:
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write_check(clk, {"force_clk_en": 1}, "force")
        mux = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(mux, "Dbmid")
        for identity in range(1 << dbmid.width):
            await self._write(
                mux,
                pack_fields(mux, {"Dbmmode": DBM_MODE_NORMAL, "Dbmid": identity}),
                f"normal{identity}",
            )
        await self._write_check(
            funnel_register("Trfunnelcontrol"),
            {"Trfunnelactive": 1, "Trfunnelenable": 1},
            "funnel",
        )
        await self._open_sink(0, "first")
        await self._dst(1, "enable")

    async def _arm_cla(self) -> None:
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        eap = cla_register("CDbgNode0Eap0")
        status = cla_register("CDbgEapStatus")
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
            "arm",
        )
        logical_op = cla_field(eap, "LogicalOp")
        activated = cla_field(status, "Node0Eap0")
        for value in range(1 << logical_op.width):
            await self._write(
                eap, pack_fields(eap, {"LogicalOp": value, "DestNode": 0}), f"op{value}"
            )
            await self._settle()
            if await self._read(status, f"op{value}") & activated.mask:
                self.logical_op = value
                self.value_checks += 1
                return
        raise AssertionError(
            f"no value of the {logical_op.width}-bit LogicalOp field activated node 0 pair 0, "
            f"so no action of that pair can be driven"
        )

    # -- register-only corners ----------------------------------------------

    async def _stream_lengths(self) -> None:
        impl = dst_register("Trdstimpl")
        stream = reg_field(impl, "Trdstvendorstreamlength")
        for value in range(1 << stream.width):
            await self._write_check(
                impl,
                {"Trdstvendorframelength": 1, "Trdstvendorstreamlength": value},
                f"stream{value}",
            )

    async def _memory_rearms(self) -> None:
        limit = sink_register("Trdstramlimitlow")
        field = reg_field(limit, "Trdstramlimitlow")
        await self._open_sink(1, "rearm0", start=_PRELOAD_START)
        for label, mode in (("rearm1", 1), ("rearm2", 0)):
            await self._open_sink(mode, label, window=_ONE_LINE_BYTES, start=_PRELOAD_START)
            read = await self._read(limit, f"{label}_limit") & field.mask
            assert read == _PRELOAD_START + _ONE_LINE_BYTES, (
                f"Trdstramlimitlow reads 0x{read:x} after being written "
                f"0x{_PRELOAD_START + _ONE_LINE_BYTES:x} in sink mode {mode}"
            )
            self.value_checks += 1
        await self._open_sink(0, "rearm_done")

    async def _disabled_inputs(self) -> None:
        disinput = funnel_register("Trfunneldisinput")
        await self._sink(0, 0, 1, "held")
        await self._write_check(disinput, {"Trfunneldisinput": _FUNNEL_DST_INPUTS}, "disinput")
        await self._write_check(disinput, {"Trfunneldisinput": 0}, "disinput_off")
        await self._open_sink(0, "held_done")

    # -- action measurement -------------------------------------------------

    async def _measure_actions(self) -> None:
        """Sort every Action0 value into starting, stopping and neither.

        A value starts the trace if, written with the DST disabled and the DST
        then enabled, it makes the write pointer move. A value stops it if,
        written after a starting value with the trace running, it leaves the
        write pointer still once the packets in flight have landed.
        """
        span = 1 << cla_field(cla_register("CDbgNode0Eap0"), "Action0").width
        for value in range(span):
            await self._dst(0, f"start{value}_off")
            await self._action(value, f"start{value}")
            await self._dst(1, f"start{value}_on")
            await self._settle()
            if await self._moving(f"start{value}"):
                self.starts.append(value)
        assert self.starts, (
            f"no value of the {span}-value Action0 field started the uncompressed trace: "
            f"the write pointer never moved"
        )
        self.start_action = self.starts[0]
        for value in range(span):
            await self._action(self.start_action, f"stop{value}_start")
            await self._settle()
            await self._action(value, f"stop{value}")
            await self._settle(4 * _SETTLE_CYCLES)
            if not await self._moving(f"stop{value}"):
                self.stops.append(value)
            elif value not in self.starts and self.neutral_action < 0:
                self.neutral_action = value
        assert self.stops, (
            f"no Action0 value stopped the running trace: the write pointer kept moving after "
            f"each of the {span} values was written behind start action {self.start_action}"
        )
        assert not set(self.stops) & set(self.starts), (
            f"values {sorted(set(self.stops) & set(self.starts))} both started the trace and "
            f"stopped it"
        )
        assert self.neutral_action >= 0, (
            f"every Action0 value either starts the trace ({self.starts}) or stops it "
            f"({self.stops}), so none leaves a running trace as it is"
        )
        self.stop_action = self.stops[0]
        self.value_checks += 3

    # -- streams ------------------------------------------------------------

    async def _start_stop_streams(self) -> None:
        impl = dst_register("Trdstimpl")
        sync = reg_field(dst_register("Trdstcontrol"), "Trdstsyncmode")
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        target = _SHORT_STREAM_FRAMES * _FRAME_BYTES
        await self._write_check(
            impl, {"Trdstvendorframelength": 1, "Trdstvendorstreamlength": 0}, "pairs_short"
        )
        for value in range(1 << sync.width):
            await self._action(self.neutral_action, f"pairs{value}_quiet")
            await self._dst(0, f"pairs{value}_off")
            await self._open_sink(0, f"pairs{value}", window=_STREAM_WINDOW_BYTES)
            await self._dst(1, f"pairs{value}_on", fmt=_DST_FORMAT_XOR_VLT, sync=value)
            advance = 0
            pairs = 0
            while advance < target:
                assert pairs < _MAX_PAIRS, (
                    f"the write pointer advanced 0x{advance:x} bytes in {_MAX_PAIRS} start/stop "
                    f"pairs under Trdstsyncmode {value}, short of the 0x{target:x}-byte stream"
                )
                await self._action(self.start_action, f"pairs{value}_s{pairs}")
                await self._settle()
                await self._action(self.stop_action, f"pairs{value}_t{pairs}")
                await self._settle()
                pairs += 1
                advance = await self._read(wp, f"pairs{value}_{pairs}") & pointer.mask
            self.stream_pairs.append(pairs)
        self.value_checks += 1

    async def _stream_overrun(self) -> None:
        impl = dst_register("Trdstimpl")
        stream = reg_field(impl, "Trdstvendorstreamlength")
        held = (impl.reset_word & stream.mask) >> stream.offset
        sync = reg_field(dst_register("Trdstcontrol"), "Trdstsyncmode")
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        target = _OVERRUN_FRAMES * _FRAME_BYTES
        for value in range(1 << sync.width):
            await self._action(self.neutral_action, f"over{value}_quiet")
            await self._dst(0, f"over{value}_off")
            await self._write_check(
                impl,
                {"Trdstvendorframelength": 1, "Trdstvendorstreamlength": held},
                f"over{value}_long",
            )
            await self._open_sink(0, f"over{value}", window=_STREAM_WINDOW_BYTES)
            await self._dst(1, f"over{value}_on", sync=value)
            await self._action(self.start_action, f"over{value}_start")
            advance = 0
            for poll in range(_MAX_POLLS):
                await self._settle()
                now = await self._read(wp, f"over{value}_{poll}") & pointer.mask
                assert now >= advance, (
                    f"the write pointer went from 0x{advance:x} to 0x{now:x} under Trdstsyncmode "
                    f"{value}: it wrapped the 0x{_STREAM_WINDOW_BYTES:x}-byte window"
                )
                advance = now
                if advance >= target:
                    break
            assert target <= advance < _STREAM_WINDOW_BYTES, (
                f"the write pointer advanced 0x{advance:x} bytes under Trdstsyncmode {value}, "
                f"not at least 0x{target:x} inside the window"
            )
            self.overrun_advance.append(advance)
            await self._write_check(
                impl,
                {"Trdstvendorframelength": 1, "Trdstvendorstreamlength": 0},
                f"over{value}_short",
            )
            for step in range(8):
                await self._action(self.start_action, f"over{value}_hold{step}")
                await self._settle()
            assert await self._moving(f"over{value}_after"), (
                f"the write pointer stopped after the stream length dropped to encoding 0 "
                f"under Trdstsyncmode {value} with the trace held on"
            )
            self.value_checks += 2
        await self._write_check(
            impl, {"Trdstvendorframelength": 1, "Trdstvendorstreamlength": held}, "over_restore"
        )

    # -- action loops -------------------------------------------------------

    async def _node_loop(self) -> None:
        await self._action(self.neutral_action, "loop_quiet")
        await self._dst(0, "loop_off")
        await self._dst(1, "loop_on")
        await self._action(self.stop_action, "loop_n1", node=1, dest=0)
        await self._action(self.start_action, "loop_n0", node=0, dest=1)
        await self._settle(4 * _SETTLE_CYCLES)
        await self._action(self.stop_action, "loop_park", node=1, dest=1)
        parked = await self._current_node("loop_parked")
        await self._action(self.neutral_action, "loop_home1", node=1, dest=0)
        await self._action(self.neutral_action, "loop_home0", node=0, dest=0)
        home = await self._current_node("loop_home")
        self.loop_nodes = (parked, home)
        assert self.loop_nodes == (1, 0), (
            f"CurrentNode read {parked} once node 1 pair 0 named node 1, and {home} once both "
            f"pairs named node 0; expected 1 and 0"
        )
        reg = cla_register("CDbgNode1Eap0")
        await self._write(reg, reg.reset_word, "loop_reset1")
        self.value_checks += 1

    # -- timestamp phases ---------------------------------------------------

    async def _timestamp_phases(self) -> None:
        await self._open_sink(0, "phase")
        for delay in range(2 * _TIMESTAMP_PERIOD):
            await self._dst(1, f"phase{delay}_on", sync=_SYNC_MODE_TIMESTAMP)
            await self._action(self.start_action, f"phase{delay}_start")
            await self._settle(1 + delay)
            await self._action(self.stop_action, f"phase{delay}_stop")
            await self._settle()
        for delay in range(2 * _TIMESTAMP_PERIOD):
            await self._action(self.neutral_action, f"off{delay}_quiet")
            await self._dst(0, f"off{delay}_pre", sync=_SYNC_MODE_TIMESTAMP)
            await self._dst(1, f"off{delay}_on", sync=_SYNC_MODE_TIMESTAMP)
            await self._action(self.start_action, f"off{delay}_start")
            await self._settle(1 + delay)
            await self._dst(0, f"off{delay}_off", sync=_SYNC_MODE_TIMESTAMP)
            await self._settle()

    async def _frame_toggles(self) -> None:
        cfg = dst_register("CDbgDebugTraceCfg")
        impl = dst_register("Trdstimpl")
        stream = reg_field(impl, "Trdstvendorstreamlength")
        held = (impl.reset_word & stream.mask) >> stream.offset
        await self._write_check(cfg, {"FrameClosureMode": 1, "FrameModeEnable": 1}, "closure")
        await self._action(self.neutral_action, "toggle_quiet")
        await self._dst(0, "toggle_off")
        await self._open_sink(0, "toggle")
        await self._dst(1, "toggle_on")
        await self._action(self.start_action, "toggle_start")
        for step in range(_FRAME_TOGGLES):
            for length in _TOGGLE_LENGTHS:
                await self._write(
                    impl,
                    pack_fields(
                        impl, {"Trdstvendorframelength": length, "Trdstvendorstreamlength": held}
                    ),
                    f"toggle{step}_{length}",
                )
            await self._settle(1 + step % 7)
        assert await self._moving("toggle_after"), (
            f"the write pointer stopped after {_FRAME_TOGGLES} frame-length toggles under the "
            f"running trace with FrameClosureMode 1"
        )
        await self._write(cfg, cfg.reset_word, "closure_restore")
        self.value_checks += 1

    # -- sink flushes -------------------------------------------------------

    async def _memory_arms(self) -> None:
        start, stop, neutral = self.start_action, self.stop_action, self.neutral_action
        await self._open_sink(0, "flush_ram")
        await self._dst(1, "flush_on")
        await self._action(start, "flush_start")
        for step in range(_RUNNING_WRITES):
            await self._action(neutral, f"flush_run{step}")
            await self._settle()
        await self._open_sink(1, "flush_mem")
        await self._settle(4 * _SETTLE_CYCLES)
        await self._open_sink(0, "flush_back")
        self.memory_arms += 1
        loops = (
            (start, stop, neutral),
            (start, neutral, stop),
            (start, stop, neutral, neutral),
            (start, neutral, neutral, stop),
            (start, neutral, stop, neutral),
            (start, stop),
        )
        for index, loop in enumerate(loops):
            for arm in range(_ARMS_PER_LOOP):
                label = f"loop{index}_{arm}"
                for node in reversed(range(len(loop))):
                    await self._action(
                        loop[node], f"{label}_n{node}", node=node, dest=(node + 1) % len(loop)
                    )
                await self._settle(1 + arm)
                await self._open_sink(1, f"{label}_mem")
                await self._settle(4 * _SETTLE_CYCLES)
                for node in range(1, _NODES):
                    await self._action(neutral, f"{label}_park{node}", node=node, dest=1)
                await self._action(neutral, f"{label}_home1", node=1, dest=0)
                await self._action(neutral, f"{label}_home0", node=0, dest=0)
                await self._open_sink(0, f"{label}_ram")
                self.memory_arms += 1
        for node in range(1, _NODES):
            reg = cla_register(f"CDbgNode{node}Eap0")
            await self._write(reg, reg.reset_word, f"flush_reset{node}")
        home = await self._current_node("flush_home")
        assert home == 0, f"CurrentNode reads {home} after every loop was sent home to node 0"
        await self._action(start, "flush_restart")
        assert await self._moving("flush_restart"), (
            f"after {self.memory_arms} memory-mode arms under running traces, each followed by "
            f"a RAM-mode re-arm, the start action does not move the write pointer"
        )
        self.value_checks += 2

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._bring_up()
        await self._arm_cla()
        await cla_mux_normal(self, "clamux")
        self.sampled_mux, _, _ = await find_sampled_mux(self, _SETTLE_CYCLES, "flush")

        await self._stream_lengths()
        await self._memory_rearms()
        await self._disabled_inputs()
        stream = reg_field(dst_register("Trdstimpl"), "Trdstvendorstreamlength")
        cocotb.log.info(
            "CHK-DST-FLUSH-REGS: Trdstvendorstreamlength took and read back all %d encodings; "
            "the sink was armed twice in memory mode at 0x%x, the second time with the limit "
            "0x%x bytes above, then in RAM mode with that window, the limit reading back "
            "each time; with the sink stopped on wrap and disabled, Trfunneldisinput took and "
            "read back 0x%04x, the DST sources",
            1 << stream.width,
            _PRELOAD_START,
            _ONE_LINE_BYTES,
            _FUNNEL_DST_INPUTS,
        )

        await self._measure_actions()
        cocotb.log.info(
            "CHK-DST-FLUSH-ACTIONS: of the Action0 values of node 0 pair 0, %s started the "
            "uncompressed trace and %s stopped it, judged by the sink write pointer; value %d "
            "left a running trace running without starting a stopped one",
            self.starts,
            self.stops,
            self.neutral_action,
        )

        await self._start_stop_streams()
        await self._stream_overrun()
        cocotb.log.info(
            "CHK-DST-FLUSH-STREAMS: compressed with the bus still, start/stop pairs moved the "
            "write pointer 0x%x bytes under each Trdstsyncmode value in %s pairs; "
            "uncompressed at the reset stream length the trace ran 0x%x bytes or more (%s) "
            "without wrapping, and the write pointer kept moving after the stream length "
            "dropped to encoding 0",
            _SHORT_STREAM_FRAMES * _FRAME_BYTES,
            self.stream_pairs,
            _OVERRUN_FRAMES * _FRAME_BYTES,
            [hex(v) for v in self.overrun_advance],
        )

        await self._node_loop()
        cocotb.log.info(
            "CHK-DST-FLUSH-LOOP: node 0 pair 0 with start action %d and node 1 pair 0 with "
            "stop action %d named each other; CurrentNode read %d once node 1 named itself "
            "and %d once both named node 0",
            self.start_action,
            self.stop_action,
            *self.loop_nodes,
        )

        await self._timestamp_phases()
        await self._frame_toggles()
        cocotb.log.info(
            "CHK-DST-FLUSH-PHASES: with a timestamp due every %d cycles, a stop action and a "
            "Trdstenable clear each landed %d different delays after the start; with "
            "FrameClosureMode 1 the frame length toggled %d times between encodings %s under "
            "the running trace and the write pointer kept moving",
            _TIMESTAMP_PERIOD,
            2 * _TIMESTAMP_PERIOD,
            _FRAME_TOGGLES,
            list(_TOGGLE_LENGTHS),
        )

        await self._memory_arms()
        cocotb.log.info(
            "CHK-DST-FLUSH-MEMARMS: the sink was armed in memory mode %d times with the trace "
            "running on the neutral action or on loops of the start, stop and neutral actions "
            "over up to %d nodes, re-armed in RAM mode after each; the chain came home to node "
            "0 and the start action moved the write pointer again",
            self.memory_arms,
            _NODES,
        )

        for reg in (
            dst_register("Trdstcontrol"),
            dst_register("Trdstimpl"),
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            cla_register("CDbgMuxSelLo"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "restore")
