# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read the trace sink out through its MMR port while the trace is still writing it.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap` and :mod:`seq_lib.smc_cla_regmap`. Values
programmed into a field come from that field's own RDL description, stated
here rather than quoted. The vendored RTL is not a source for any value this
sequence programs or compares against.

``smc_dfd_trace_sink_readout_test`` fills the sink and then stops the trace
before reading it back, so the sink is never reading and writing at once: its
read pointer only ever moves while the write pointer is parked. This sequence
keeps the trace running and drives the read side underneath it, so the write
pointer and the read pointer are both in motion and the RAM data port is taken
while frames are still arriving.

Three things are interleaved inside one live trace:

* the action field is driven, which is what keeps the trace producing;
* the read pointer is walked across the window and the RAM data port read at
  each position;
* the sink's destination mode is changed, so the mode selection is exercised
  with traffic in flight rather than on an idle sink.

The witnesses are the ones the other sink leaves use: the RAM data port reads
zero before any trace has run, the write pointer leaves the value it was given,
and the data port returns non-zero words. What makes this leaf different is
that the write-pointer movement and the read-side activity are required to
happen in the *same* phase. The trace first runs until the sink's wrap flag
reports one full pass of the window, so every position the read pointer is
sent to holds a word the trace wrote.

The sink's pointer fields sit above two reserved bits and hardware also writes
them, so they are programmed through each field's own mask rather than the
register's plain read-write mask, which leaves them out.

The compressed phase ends with the traced bus switched between two states an
odd number of bytes apart, so compressed packets are odd-sized and walk the
accumulator's write offset through the odd positions an uncompressed stream
never reaches. The CLA's own debug-bus mux, the last stage in front of the
trace, resets to its off mode and is put in normal mode for this; see
``_walk_odd_offsets``.

Two ways of stopping the trace close the leaf:

* **Clearing ``Trdstenable`` alone.** The DST is kept active, so its clock keeps
  running while the trace winds down, and the uncompressed stream is running
  with packets in flight when the enable drops. ``Trdstempty`` has to read 0
  and the sink write pointer has to move while that stream runs, and the
  pointer has to park once the enable has been cleared. ``Trdstempty`` after
  the stop is recorded, not required. Before the stop the stream runs at the
  longest frame length the field offers and then at the shortest frame and
  stream lengths.
* **The sink's stop-on-wrap setting.** With ``Trdstramstoponwrap`` set, the write
  pointer has to advance and then park inside the window while the trace is
  still being driven, rather than come round again. The sink enable is then
  cleared with the sink kept active and the setting still held, and the pointer
  has to stay where it parked.

After both, ``Trdstsyncmode`` is walked through every value of its field under
each timestamp source, on a fresh sink with the uncompressed stream running and
the restarting action held so the stream runs for many frames under each.

Before that, a RAM-mode window is placed with ``Trdstramstartlow`` one trace
RAM size above the RAM, a legal value for the field and out of the RAM's range
by construction, and the write pointer has to run through it.

The leaf ends in the sink's memory mode. The memory write-out is never
accepted in this bench, so the frames the sink stages in its local RAM are
never drained and it backpressures the DST. The trace is held on well past
that, and the sink is then re-armed in RAM mode, where the stream has to
resume. It comes last because a software stop after it does not empty the
packetizer.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import (
    DBM_MODE_IDENTIFIER,
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
    traced_bus,
)

# dfd_dst.rdl Trdstformat, the uncompressed value its description names, so
# every debug-bus sample becomes a packet and the sink stays busy.
_DST_FORMAT_NONE = 0
# The compressing value its description names. An uncompressed packet is a
# fixed size, so the accumulator's write boundary advances by the same step
# every time and only ever lands on even offsets; a compressed packet carries
# only the bytes that changed, so its length varies and the boundary can land
# on an odd offset.
_DST_FORMAT_XOR_VLT = 3

# A small window, so the write pointer comes round inside one action sweep and
# the read pointer chasing it is never far behind.
_SINK_WINDOW_BYTES = 0x400

# Read-pointer positions walked during the live trace, as byte offsets.
_READ_POSITIONS = tuple(range(0, _SINK_WINDOW_BYTES, _SINK_WINDOW_BYTES // 8))

# The stop-on-wrap window, several times the live one, so the write pointer
# is seen moving through it before it parks.
_WRAP_WINDOW_BYTES = 0x2000

_SETTLE_CYCLES = 16
_DELIVER_POLLS = 32
# Write-pointer samples that have to agree for the pointer to count as parked.
_PARKED_SAMPLES = 3

# Mode switches in the odd-offset walk: each makes one compressed packet, and a
# run of equal odd-sized packets visits every offset of the 64-byte accumulator
# within 64 packets, so this leaves room for a frame closing part way.
_ODD_SWITCHES = 160
# Writes of the restarting action with the sink in memory mode, each followed
# by the settle time: several times what the uncompressed stream needs to fill
# the sink's staging threshold. Then the writes that restart the stream after
# the sink returns to RAM mode.
_MEMORY_HOLD_WRITES = 100
# dfd_dst.rdl Trdstsyncmode: the one value its description names, which sends a
# timestamp.
_SYNC_MODE_TIMESTAMP = 2
_MEMORY_EXIT_WRITES = 8
# Sink control reads in memory mode after the stop, each after the settle time,
# and action writes after the recovery, each followed by four data-port reads.
_MEMORY_STOP_READS = 8
_MEMORY_EXIT_READS = 8
# A RAM-mode window start one trace RAM size (16 KB) up: a legal value for the
# byte-address field, out of the RAM's range by construction.
_HIGH_START_BYTES = 0x4000
# One 64-byte line, the smallest window the sink's byte-address fields describe,
# and the action writes the trace is held on for in that window.
_ONE_LINE_BYTES = 0x40
_EDGE_WRITES = 8
# Writes of the restarting action per sync-mode value, each followed by the
# settle time: long enough at 64-byte frames to pass the shortest stream length
# more than once.
_HOLD_WRITES = 24


class smc_dfd_trace_sink_concurrent_test_seq(SmcCsrSeq):
    """Drive the sink's read side while the trace is still writing into it."""

    def __init__(self, name: str = "smc_dfd_trace_sink_concurrent_test_seq") -> None:
        super().__init__(name)
        self.baseline_data = None
        self.baseline_wp = 0
        self.wp_samples: list[int] = []
        self.words_read = 0
        self.nonzero_words = 0
        self.positions_driven = 0
        self.modes_live: list[int] = []
        self.frame_shapes: set[tuple[int, int]] = set()
        self.value_checks = 0
        self.fill_bursts = 0
        self.sync_modes: list[tuple[int, int]] = []
        self.stop_polls = 0
        self.stop_wp_samples: list[int] = []
        self.wrap_samples: list[int] = []
        self.sampled_mux = -1
        self.odd_bytes = 0
        self.odd_states = (0, 0)
        self.odd_start_action = -1
        self.odd_pointer = (0, 0)
        self.memory_exit_pointer = 0
        self.high_pointer = 0
        self.frame_off_empty_poll = 0

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

    # -- bring-up ---------------------------------------------------------

    async def _bring_up(self) -> None:
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write_check(clk, {"force_clk_en": 1}, "force")
        mux = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(mux, "Dbmid")
        for identity in range(1 << dbmid.width):
            await self._write(
                mux, pack_fields(mux, {"Dbmmode": 1, "Dbmid": identity}), f"normal{identity}"
            )
        await self._write_check(
            funnel_register("Trfunnelcontrol"),
            {"Trfunnelactive": 1, "Trfunnelenable": 1},
            "funnel",
        )

    async def _open_sink(
        self,
        mode: int,
        label: str,
        window: int = _SINK_WINDOW_BYTES,
        stop_on_wrap: int = 0,
        start: int = 0,
    ) -> None:
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, f"{label}_off")
        for name, value in (
            ("Trdstramstartlow", start),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", start + window),
            ("Trdstramlimithigh", 0),
            ("Trdstramwplow", 0),
            ("Trdstramrplow", 0),
        ):
            reg = sink_register(name)
            await self._write(reg, field_word(reg, name, value), label)
        await self._write_check(
            control,
            {
                "Trdstramactive": 1,
                "Trdstramenable": 1,
                "Trdstrammode": mode,
                "Trdstramstoponwrap": stop_on_wrap,
            },
            f"{label}_mode{mode}",
        )
        self.modes_live.append(mode)

    async def _arm_cla(self) -> int:
        ctrl = cla_register("CDbgClaCtrlStatus")
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        eap = cla_register("CDbgNode0Eap0")
        status = cla_register("CDbgEapStatus")
        await self._write(eap, eap.reset_word, "reset")
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
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            if await self._read(status, f"op{value}") & activated.mask:
                self.value_checks += 1
                return value
        raise AssertionError(
            "no value of the 2-bit LogicalOp field activated node 0 EAP 0, so no action of "
            "that pair can be driven and no trace can be captured to read back"
        )

    # -- the concurrent phase ---------------------------------------------

    async def _walk_frame_shape(self, logical_op: int) -> None:
        """Walk the frame controls under a compressed stream.

        The accumulator's write boundary is where a packet lands in the bank,
        and no register addresses it. What the register contract does offer is
        the frame shape: the frame length sets where a frame closes, and the
        closure mode decides whether a packet crossing that boundary is pushed
        back or the frame is closed early. Both move the offsets packets land
        on, so walking them is the widest aim at the boundary available from
        software.
        """
        impl = dst_register("Trdstimpl")
        length = reg_field(impl, "Trdstvendorframelength")
        stream = reg_field(impl, "Trdstvendorstreamlength")
        cfg = dst_register("CDbgDebugTraceCfg")
        closure = reg_field(cfg, "FrameClosureMode")
        held_stream = (impl.reset_word & stream.mask) >> stream.offset
        for mode in range(1 << closure.width):
            await self._write_check(
                cfg,
                {
                    "FrameClosureMode": mode,
                    "FrameModeEnable": 1,
                    "TraceSourceId": 0,
                    "TraceFrameFillByte": 0,
                    "FrameLenghtInBytes": 0,
                },
                f"closure{mode}",
            )
            for value in range(1 << length.width):
                await self._write_check(
                    impl,
                    {
                        "Trdstvendorframelength": value,
                        "Trdstvendorstreamlength": held_stream,
                        "Trdsttimestampconfig": 0,
                    },
                    f"framelen{mode}_{value}",
                )
                self.frame_shapes.add((mode, value))
                await self._drive_actions(logical_op, 4, f"shape{mode}_{value}")

    async def _fill_window(self, logical_op: int) -> None:
        """Keep the trace producing until the sink reports one pass of its window."""
        eap = cla_register("CDbgNode0Eap0")
        span = 1 << cla_field(eap, "Action0").width
        wp = sink_register("Trdstramwplow")
        wrap = reg_field(wp, "Trdstramwrap")
        for burst in range(_DELIVER_POLLS):
            await self._drive_actions(logical_op, span, f"fill{burst}")
            if await self._read(wp, f"fill{burst}") & wrap.mask:
                self.fill_bursts = burst + 1
                self.value_checks += 1
                return
        raise AssertionError(
            f"the sink wrap flag stayed 0 through {_DELIVER_POLLS} sweeps of the action field, "
            f"so the trace never came round the 0x{_SINK_WINDOW_BYTES:x}-byte window and the "
            f"positions the read pointer is sent to would hold words it never wrote"
        )

    async def _drive_actions(self, logical_op: int, count: int, label: str) -> None:
        """A short burst of action values, to keep the stream producing."""
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        span = 1 << action.width
        for step in range(count):
            await self._write(
                eap,
                pack_fields(
                    eap,
                    {
                        "LogicalOp": logical_op,
                        "DestNode": 0,
                        "Action0": (step * span // count) % span,
                    },
                ),
                f"{label}_a{step}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)

    async def _stream_and_drain(self, logical_op: int) -> None:
        """Drive the action field, the read pointer and the data port together."""
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        wp = sink_register("Trdstramwplow")
        rp = sink_register("Trdstramrplow")
        data = sink_register("Trdstramdata")
        span = 1 << action.width
        step = span // len(_READ_POSITIONS)
        for value in range(span):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"action{value}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            if value % step == 0:
                offset = _READ_POSITIONS[value // step]
                await self._write(rp, field_word(rp, "Trdstramrplow", offset), f"seek{offset:x}")
                self.positions_driven += 1
                word = await self._read(data, f"data{offset:x}")
                self.words_read += 1
                if word:
                    self.nonzero_words += 1
                self.wp_samples.append(await self._read(wp, f"wp{offset:x}"))
        await self._write(eap, eap.reset_word, "quiet")

    # -- odd write offsets --------------------------------------------------

    async def _set_mux_mode(self, identity: int, mode: int, label: str) -> None:
        mux = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        await self._write(mux, pack_fields(mux, {"Dbmmode": mode, "Dbmid": identity}), label)

    async def _restart_compressed(self, logical_op: int, modes: tuple[int, int]) -> None:
        """Empty the DST, re-enable it compressed, and find an action that restarts the trace.

        The enable is cleared alone with the DST active, and ``Trdstempty`` has
        to read 1 within ``_DELIVER_POLLS`` polls before the restart. Which
        action code starts a trace is not published, so the action field is
        walked, the bus switched twice under each value, and the first value
        that makes ``Trdstempty`` read 0 is held: packets are arriving, so the
        trace is running.
        """
        control = dst_register("Trdstcontrol")
        empty = reg_field(control, "Trdstempty")
        stopped = {"Trdstactive": 1, "Trdstenable": 0, "Trdstformat": _DST_FORMAT_XOR_VLT}
        await self._write_check(control, stopped, "oddflush")
        for poll in range(_DELIVER_POLLS):
            if await self._read(control, f"oddflush{poll}") & empty.mask:
                break
        else:
            raise AssertionError(
                f"DST Trdstempty stayed 0 for {_DELIVER_POLLS} polls after the enable was "
                f"cleared with the DST active, so the odd-offset run cannot start empty"
            )
        await self._write_check(
            control,
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_XOR_VLT},
            "oddrun",
        )
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        for value in range(1 << action.width):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"oddstart{value}",
            )
            for mode in modes:
                await self._set_mux_mode(self.sampled_mux, mode, f"oddstart{value}_{mode}")
                await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            if not await self._read(control, f"oddstart{value}") & empty.mask:
                self.odd_start_action = value
                self.value_checks += 1
                return
        raise AssertionError(
            f"Trdstempty stayed 1 under every value of the {action.width}-bit Action0 field "
            f"with the bus switching between the two measured states, so no action restarts "
            f"the compressed trace"
        )

    async def _walk_odd_offsets(self, logical_op: int) -> None:
        """Switch the compressed stream between two bus states an odd number of bytes apart.

        An uncompressed packet is a fixed size, so it only lands the accumulator's
        write offset on even positions. A compressed packet carries the bytes that
        changed since the last sample, so a bus that alternates between two
        states differing in an odd number of bytes makes odd-sized packets, and a
        long run of them walks the offset through every position of a frame.

        Two mux arrays sit in front of the trace. The CLA's own mux, programmed
        through ``CDbgMuxSelLo``, is the last stage and resets to its off mode, so
        it is put in normal debug mode first; it takes the mode only while the
        programmed identifier is its own, so the mode is written once per
        identifier value. The DEBUG_BUS_MUX array feeds it. Its description gives
        two modes to work with: normal debug mode, and an identifier output mode
        in which a mux drives its own identifier. Every DEBUG_BUS_MUX identifier is
        put in the identifier mode, then each in turn is put back in normal mode
        until the debug-signal snapshot of the active pair changes. That mux is
        one whose output the trace samples, found by measurement rather than
        named. Its two modes give the two bus states, both read through the
        snapshot, and the leaf requires them to differ in an odd number of bytes
        before switching between them.
        """
        dbmid = reg_field(dfd_register("dfx_ctrl/DEBUG_BUS_MUX"), "Dbmid")
        impl = dst_register("Trdstimpl")
        length = reg_field(impl, "Trdstvendorframelength")
        stream = reg_field(impl, "Trdstvendorstreamlength")
        await self._write_check(
            impl,
            {
                "Trdstvendorframelength": (1 << length.width) - 1,
                "Trdstvendorstreamlength": (impl.reset_word & stream.mask) >> stream.offset,
                "Trdsttimestampconfig": 0,
            },
            "oddframe",
        )
        eap = cla_register("CDbgNode0Eap0")
        await self._write(eap, pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0}), "odd")
        await cla_mux_normal(self, "clamux")
        self.sampled_mux, identifier_state, normal_state = await find_sampled_mux(
            self, _SETTLE_CYCLES, "odd"
        )
        diff = identifier_state ^ normal_state
        self.odd_bytes = sum(1 for b in range(8) if (diff >> (8 * b)) & 0xFF)
        self.odd_states = (identifier_state, normal_state)
        assert self.odd_bytes % 2 == 1, (
            f"the two bus states 0x{identifier_state:016x} and 0x{normal_state:016x} differ in "
            f"{self.odd_bytes} bytes, an even count, so switching between them makes packets "
            f"no different in parity from the uncompressed ones"
        )
        modes = (DBM_MODE_IDENTIFIER, DBM_MODE_NORMAL)
        await self._restart_compressed(logical_op, modes)
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        before = await self._read(wp, "odd_before") & pointer.mask
        for step in range(_ODD_SWITCHES):
            await self._set_mux_mode(self.sampled_mux, modes[step % 2], f"odd{step}")
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        after = await self._read(wp, "odd_after") & pointer.mask
        assert after != before, (
            f"the sink write pointer stayed at 0x{before:x} across {_ODD_SWITCHES} bus switches "
            f"with the trace running, so the odd-sized packets never reached the sink"
        )
        self.odd_pointer = (before, after)
        # The last switch left the mux in normal mode; the snapshot must say so.
        final = await traced_bus(self, "odd_end")
        assert final == normal_state, (
            f"after {_ODD_SWITCHES} switches ending in normal mode the snapshot reads "
            f"0x{final:016x}, not the normal-mode state 0x{normal_state:016x}, so the "
            f"switching did not move the bus between the two measured states"
        )
        for identity in range(1 << dbmid.width):
            await self._set_mux_mode(identity, DBM_MODE_NORMAL, f"renormal{identity}")
        self.value_checks += 4
        cocotb.log.info(
            "CHK-DST-CONCURRENT-ODDBYTES: with the CLA mux in normal mode, DEBUG_BUS_MUX "
            "identifier %d was measured as one the trace samples; its identifier and normal "
            "modes put 0x%016x and 0x%016x on the bus, %d byte(s) apart. After an emptying "
            "stop, action %d restarted the compressed trace at the longest frame length, and "
            "%d switches between the two states moved the sink write pointer from 0x%x to "
            "0x%x, ending on the normal-mode state",
            self.sampled_mux,
            identifier_state,
            normal_state,
            self.odd_bytes,
            self.odd_start_action,
            _ODD_SWITCHES,
            self.odd_pointer[0],
            self.odd_pointer[1],
        )

    # -- a window above the RAM --------------------------------------------

    async def _high_start(self, logical_op: int) -> None:
        """Run the trace into a RAM-mode window that starts above the sink RAM.

        ``Trdstramstartlow`` is a plain byte-address field, so a start past the
        end of the 16 KB trace RAM is a legal register value even though no RAM
        word lives there. The window is placed at 0x4000 bytes, one RAM size up;
        the RAM indexes the low address bits, so the trace still lands in it,
        and the write pointer has to run from the programmed start through the
        window, which is what the register view shows.
        """
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        eap = cla_register("CDbgNode0Eap0")
        hold = pack_fields(
            eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": self.odd_start_action}
        )
        await self._open_sink(0, "high", start=_HIGH_START_BYTES)
        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "high",
        )
        for step in range(_MEMORY_EXIT_WRITES):
            await self._write(eap, hold, f"high{step}")
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        for poll in range(_DELIVER_POLLS):
            self.high_pointer = await self._read(wp, f"high{poll}") & pointer.mask
            if self.high_pointer > _HIGH_START_BYTES:
                break
        limit = _HIGH_START_BYTES + _SINK_WINDOW_BYTES
        assert _HIGH_START_BYTES < self.high_pointer <= limit, (
            f"the write pointer reads 0x{self.high_pointer:x} with the window programmed at "
            f"0x{_HIGH_START_BYTES:x}..0x{limit:x} and the trace held on, so it did not run "
            f"from the programmed start through that window"
        )
        start = sink_register("Trdstramstartlow")
        await self._write(start, start.reset_word, "high_restore")
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-CONCURRENT-HIGHSTART: with Trdstramstartlow at 0x%x, one trace RAM size "
            "above the RAM's own range, and the limit 0x%x bytes past it, the held trace moved "
            "the write pointer to 0x%x inside that window; the start register was then "
            "written back to its reset",
            _HIGH_START_BYTES,
            _SINK_WINDOW_BYTES,
            self.high_pointer,
        )

    async def _window_edges(self, logical_op: int) -> None:
        """A window whose limit is one 64-byte line above its start.

        That is the smallest window the sink's byte-address fields describe; the
        limit has to read back, and the trace is then run into the window.
        """
        eap = cla_register("CDbgNode0Eap0")
        hold = pack_fields(
            eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": self.odd_start_action}
        )
        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "edges",
        )
        await self._open_sink(0, "oneline", _ONE_LINE_BYTES)
        limit = sink_register("Trdstramlimitlow")
        field = reg_field(limit, "Trdstramlimitlow")
        read = await self._read(limit, "oneline_limit") & field.mask
        assert read == _ONE_LINE_BYTES, (
            f"Trdstramlimitlow reads 0x{read:x} after being written 0x{_ONE_LINE_BYTES:x}"
        )
        for step in range(_EDGE_WRITES):
            await self._write(eap, hold, f"oneline{step}")
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-CONCURRENT-EDGES: Trdstramlimitlow took the one-line limit 0x%x, read it "
            "back, and the trace was held on into that window for %d action writes",
            _ONE_LINE_BYTES,
            _EDGE_WRITES,
        )

    # -- memory mode ------------------------------------------------------

    async def _memory_backpressure(self, logical_op: int) -> None:
        """Run the uncompressed trace into the sink's memory mode, then recover in RAM mode.

        In memory mode the sink stages frames in its local RAM for a memory
        write-out this bench never accepts, so the staged frames are never
        drained: the sink applies backpressure once they pass its threshold and
        the DST holds data it cannot hand on. The trace is held on the
        restarting action well past that point, ``Trdstempty`` has to read 0
        afterwards, and the sink is then re-armed in RAM mode, where the write
        pointer has to move within a bounded number of polls. Every wait is
        bounded, so a sink that never leaves backpressure fails the leaf rather
        than stalling it.
        """
        control = dst_register("Trdstcontrol")
        empty = reg_field(control, "Trdstempty")
        eap = cla_register("CDbgNode0Eap0")
        hold = pack_fields(
            eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": self.odd_start_action}
        )
        # Uncompressed, so a packet asks for space every sample, with the periodic
        # timestamp on at its shortest period and the traced bus switching under
        # every hold write, so data and timestamp packets keep asking for space the
        # backpressured sink does not free and have to be retried.
        timestamped = {
            "Trdstactive": 1,
            "Trdstformat": _DST_FORMAT_NONE,
            "Trdstsyncmode": _SYNC_MODE_TIMESTAMP,
            "Trdstsyncmax": 0,
        }
        await self._open_sink(1, "memory")
        await self._write_check(control, {**timestamped, "Trdstenable": 1}, "memory")
        modes = (DBM_MODE_IDENTIFIER, DBM_MODE_NORMAL)
        for step in range(_MEMORY_HOLD_WRITES):
            await self._write(eap, hold, f"memory{step}")
            await self._set_mux_mode(self.sampled_mux, modes[step % 2], f"memory{step}_bus")
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        held = await self._read(control, "memory_held")
        assert not held & empty.mask, (
            f"DST Trdstcontrol reads 0x{held:08x} after {_MEMORY_HOLD_WRITES} writes of the "
            f"restarting action with the sink in memory mode: Trdstempty is 1, so the DST was "
            f"not holding back data the sink refused"
        )
        # Still in memory mode: the sink enable is cleared with the sink active and
        # its stop-on-wrap setting on, and the trace is stopped the same way, so the
        # sink's memory-mode stop terms and its empty computation see staged
        # frames with nothing arriving. Nothing is claimed about the empty flag
        # here: the reads only carry the sink through those states.
        sink_control = sink_register("Trdstramcontrol")
        await self._write_check(
            sink_control,
            {
                "Trdstramactive": 1,
                "Trdstramenable": 0,
                "Trdstrammode": 1,
                "Trdstramstoponwrap": 1,
            },
            "memory_stop",
        )
        await self._write_check(control, {**timestamped, "Trdstenable": 0}, "memory_stop")
        for poll in range(_MEMORY_STOP_READS):
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            await self._read(sink_control, f"memory_stop{poll}")
        await self._write_check(control, {**timestamped, "Trdstenable": 1}, "memory_restart")
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        await self._open_sink(0, "memexit")
        for step in range(_MEMORY_EXIT_WRITES):
            await self._write(eap, hold, f"memexit{step}")
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        for poll in range(_DELIVER_POLLS):
            self.memory_exit_pointer = await self._read(wp, f"memexit{poll}") & pointer.mask
            if self.memory_exit_pointer:
                break
        assert self.memory_exit_pointer, (
            f"the sink write pointer stayed at 0 for {_DELIVER_POLLS} polls after the sink was "
            f"re-armed in RAM mode with the trace held on, so the stream did not resume after "
            f"the memory-mode backpressure"
        )
        # The RAM data port read back to back while the resumed stream is still
        # writing, so reads meet the sink's RAM writes. Only the pointer's first
        # word has been written for certain, so the read pointer stays on it.
        data = sink_register("Trdstramdata")
        for step in range(_MEMORY_EXIT_READS):
            await self._write(eap, hold, f"memread{step}")
            for burst in range(4):
                await self._read(data, f"memread{step}_{burst}")
        self.value_checks += 2
        cocotb.log.info(
            "CHK-DST-CONCURRENT-MEMORY: with the sink in memory mode and the uncompressed "
            "trace held on for %d action writes, Trdstempty read 0, the DST holding data the "
            "sink would not take; re-armed in RAM mode, the stream resumed and moved the "
            "write pointer to 0x%x",
            _MEMORY_HOLD_WRITES,
            self.memory_exit_pointer,
        )

    async def _frame_mode_off(self, logical_op: int) -> None:
        """Run and stop the trace with frame mode off; nothing is claimed about emptying.

        ``FrameModeEnable`` is cleared, the uncompressed stream is held on and the
        enable cleared with the DST active, and ``Trdstempty`` is read over a
        bounded number of polls and recorded. It runs last because the stop is
        not required to empty the packetizer here.
        """
        await self._write_check(
            dst_register("CDbgDebugTraceCfg"),
            {
                "FrameClosureMode": 0,
                "FrameModeEnable": 0,
                "TraceSourceId": 0,
                "TraceFrameFillByte": 0,
                "FrameLenghtInBytes": 0,
            },
            "frameoff",
        )
        control = dst_register("Trdstcontrol")
        empty = reg_field(control, "Trdstempty")
        eap = cla_register("CDbgNode0Eap0")
        hold = pack_fields(
            eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": self.odd_start_action}
        )
        await self._write_check(
            control,
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "frameoff_run",
        )
        for step in range(_MEMORY_EXIT_WRITES):
            await self._write(eap, hold, f"frameoff{step}")
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        await self._write_check(
            control,
            {"Trdstactive": 1, "Trdstenable": 0, "Trdstformat": _DST_FORMAT_NONE},
            "frameoff_stop",
        )
        for poll in range(_DELIVER_POLLS):
            if await self._read(control, f"frameoff_stop{poll}") & empty.mask:
                self.frame_off_empty_poll = poll + 1
                break
        cocotb.log.info(
            "Frame mode off: after the stop Trdstempty read 1 on poll %d (0 means not within "
            "%d polls)",
            self.frame_off_empty_poll,
            _DELIVER_POLLS,
        )

    # -- stopping the trace -----------------------------------------------

    async def _stop_in_software(self, logical_op: int) -> None:
        """Run the uncompressed stream, then clear the enable with the DST kept active.

        While the stream runs, ``Trdstempty`` has to read 0 and the sink write
        pointer has to move between two back-to-back reads. Once the enable is
        cleared, the pointer has to park: ``_PARKED_SAMPLES`` back-to-back reads
        agree within ``_DELIVER_POLLS`` reads. A read takes a fixed number of
        core-clock cycles and the DST, the sink and the read path all run on
        that clock, so the bound holds at every sys-clock period. ``Trdstempty``
        is then read over ``_DELIVER_POLLS`` polls and recorded, not required:
        whether this stop empties the packetizer depends on where the stop
        falls against a frame boundary (see the card's open observations).
        """
        control = dst_register("Trdstcontrol")
        empty = reg_field(control, "Trdstempty")
        enable = reg_field(control, "Trdstenable")
        active = reg_field(control, "Trdstactive")
        impl = dst_register("Trdstimpl")
        length = reg_field(impl, "Trdstvendorframelength")
        stream = reg_field(impl, "Trdstvendorstreamlength")
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        # The longest frame the field offers first. Uncompressed packets are a
        # fixed size, so a 64-byte frame closes after a handful of them and
        # only a long frame carries the running offset through every even
        # position of the accumulator before the frame closes.
        await self._write_check(
            impl,
            {
                "Trdstvendorframelength": (1 << length.width) - 1,
                "Trdstvendorstreamlength": (impl.reset_word & stream.mask) >> stream.offset,
                "Trdsttimestampconfig": 0,
            },
            "longframe",
        )
        await self._write_check(
            control,
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "restart",
        )
        await self._drive_actions(logical_op, 16, "longframe")
        # Then the shortest frame and the shortest stream the two fields offer:
        # a frame of 64 bytes, and the smallest stream-length encoding.
        await self._write_check(
            impl,
            {"Trdstvendorframelength": 1, "Trdstvendorstreamlength": 0, "Trdsttimestampconfig": 0},
            "shortstream",
        )
        await self._drive_actions(logical_op, 16, "shortstream")
        running = await self._read(control, "running")
        assert not running & empty.mask, (
            f"DST Trdstcontrol reads 0x{running:08x} with the uncompressed stream running: "
            f"Trdstempty is already 1, so there is nothing in flight for the stop below to "
            f"wind down and clearing the enable would prove nothing"
        )
        live = [await self._read(wp, f"live{i}") & pointer.mask for i in range(2)]
        assert live[0] != live[1], (
            f"the sink write pointer read 0x{live[0]:x} twice back to back with the "
            f"uncompressed stream running, so the trace was not reaching the sink and a "
            f"pointer that parks after the stop would prove nothing"
        )
        await self._write_check(
            control,
            {"Trdstactive": 1, "Trdstenable": 0, "Trdstformat": _DST_FORMAT_NONE},
            "stop",
        )
        self.stop_wp_samples = []
        for poll in range(_DELIVER_POLLS):
            self.stop_wp_samples.append(await self._read(wp, f"stopwp{poll}") & pointer.mask)
            tail = self.stop_wp_samples[-_PARKED_SAMPLES:]
            if len(tail) == _PARKED_SAMPLES and len(set(tail)) == 1:
                break
        tail = self.stop_wp_samples[-_PARKED_SAMPLES:]
        assert len(tail) == _PARKED_SAMPLES and len(set(tail)) == 1, (
            f"the sink write pointer read {[hex(w) for w in self.stop_wp_samples]} over "
            f"{len(self.stop_wp_samples)} reads after Trdstenable was cleared with Trdstactive "
            f"held at 1, never {_PARKED_SAMPLES} equal reads in a row, so the trace kept "
            f"writing the sink"
        )
        self.stop_polls = 0
        word = running
        for poll in range(_DELIVER_POLLS):
            word = await self._read(control, f"stop{poll}")
            if word & empty.mask:
                self.stop_polls = poll + 1
                break
        assert not word & enable.mask and word & active.mask, (
            f"DST Trdstcontrol reads 0x{word:08x} after the stop: Trdstenable has to read 0 "
            f"and Trdstactive 1, as written"
        )
        self.value_checks += 4
        cocotb.log.info(
            "CHK-DST-CONCURRENT-STOP: with the uncompressed stream running, first at the "
            "longest frame length and then at the shortest frame and stream lengths, "
            "Trdstempty read 0 and the sink write pointer moved from 0x%x to 0x%x between two "
            "back-to-back reads; once Trdstenable was cleared with Trdstactive held at 1 the "
            "pointer parked at 0x%x, %d equal reads in a row after %d reads (%s) of at most %d",
            live[0],
            live[1],
            tail[-1],
            _PARKED_SAMPLES,
            len(self.stop_wp_samples),
            ", ".join(hex(w) for w in self.stop_wp_samples),
            _DELIVER_POLLS,
        )
        cocotb.log.info(
            "Software stop: after the pointer parked Trdstempty read 1 on poll %d (0 means "
            "not within %d polls)",
            self.stop_polls,
            _DELIVER_POLLS,
        )

    async def _stop_on_wrap(self, logical_op: int) -> None:
        """Let the trace run into a sink that is set to stop when it wraps."""
        control = sink_register("Trdstramcontrol")
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        await self._open_sink(0, "wrap", _WRAP_WINDOW_BYTES, stop_on_wrap=1)
        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "rewrap",
        )
        for burst in range(8):
            await self._drive_actions(logical_op, 16, f"wrap{burst}")
            self.wrap_samples.append(await self._read(wp, f"wrap{burst}") & pointer.mask)
        parked = self.wrap_samples[-1]
        assert any(0 < w < parked for w in self.wrap_samples), (
            f"the write pointer read {[hex(w) for w in self.wrap_samples]} across the trace, "
            f"never between 0 and where it ended, so it was not seen moving through the window"
        )
        assert all(w == parked for w in self.wrap_samples[-_PARKED_SAMPLES:]), (
            f"the last {_PARKED_SAMPLES} write-pointer samples "
            f"{[hex(w) for w in self.wrap_samples[-_PARKED_SAMPLES:]]} differ while the trace "
            f"was still being driven, so the sink did not stop"
        )
        assert parked <= _WRAP_WINDOW_BYTES, (
            f"the write pointer parked at 0x{parked:x}, past the 0x{_WRAP_WINDOW_BYTES:x}-byte "
            f"window it was given"
        )
        await self._write_check(
            control,
            {"Trdstramactive": 1, "Trdstramenable": 0, "Trdstramstoponwrap": 1},
            "wrapoff",
        )
        await self._drive_actions(logical_op, 4, "wrapoff")
        after = await self._read(wp, "wrapoff") & pointer.mask
        assert after == parked, (
            f"the write pointer moved from 0x{parked:x} to 0x{after:x} after the sink enable "
            f"was cleared with stop-on-wrap still set"
        )
        self.value_checks += 4
        cocotb.log.info(
            "CHK-DST-CONCURRENT-STOPWRAP: with Trdstramstoponwrap set the write pointer moved "
            "through the 0x%x-byte window (%s) and parked at 0x%x for the last %d samples while "
            "the trace was still driven, and stayed there once the sink enable was cleared with "
            "the setting held",
            _WRAP_WINDOW_BYTES,
            ", ".join(hex(w) for w in self.wrap_samples),
            parked,
            _PARKED_SAMPLES,
        )

    async def _hold_action(self, logical_op: int, label: str) -> None:
        """Keep the trace running on the action measured to restart it.

        A sweep of the action field passes values that stop the trace as well
        as ones that start it, so a sweep alone runs the stream for a few
        frames and leaves it stopped. Holding the restarting action keeps it
        running across many frames at the shortest frame length.
        """
        eap = cla_register("CDbgNode0Eap0")
        word = pack_fields(
            eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": self.odd_start_action}
        )
        for step in range(_HOLD_WRITES):
            await self._write(eap, word, f"{label}_{step}")
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)

    async def _walk_sync_modes(self, logical_op: int) -> None:
        """Every sync mode under each timestamp source, with the stream running.

        The RDL description of ``Trdstsyncmode`` publishes one value, the one
        that sends a timestamp, and marks the others as not applicable, so the
        walk covers the whole field range. ``Trdsttimestampconfig`` picks where
        that timestamp comes from, an external source or the CLA timesync, and
        both are walked. Under each value a short action burst is followed by
        the restarting action measured in the odd-offset walk, held so the
        stream runs for many frames. The witness is the exact readback of each
        value with the stream running under it. The walk comes last: the packetizer can be
        left holding a partial frame after it, and nothing afterwards needs it
        empty.
        """
        control = dst_register("Trdstcontrol")
        sync = reg_field(control, "Trdstsyncmode")
        impl = dst_register("Trdstimpl")
        source = reg_field(impl, "Trdsttimestampconfig")
        await self._open_sink(0, "sync")
        for ts in range(1 << source.width):
            await self._write_check(
                impl,
                {
                    "Trdstvendorframelength": 1,
                    "Trdstvendorstreamlength": 0,
                    "Trdsttimestampconfig": ts,
                },
                f"tsource{ts}",
            )
            for value in range(1 << sync.width):
                await self._write_check(
                    control,
                    {
                        "Trdstactive": 1,
                        "Trdstenable": 1,
                        "Trdstformat": _DST_FORMAT_NONE,
                        "Trdstsyncmode": value,
                    },
                    f"sync{ts}_{value}",
                )
                self.sync_modes.append((ts, value))
                await self._drive_actions(logical_op, 8, f"sync{ts}_{value}")
                await self._hold_action(logical_op, f"hold{ts}_{value}")
        expected = [(t, v) for t in range(1 << source.width) for v in range(1 << sync.width)]
        assert self.sync_modes == expected, (
            f"the sync-mode walk wrote {self.sync_modes}, not every sync mode under every "
            f"timestamp source"
        )
        cocotb.log.info(
            "CHK-DST-CONCURRENT-SYNCWALK: Trdstsyncmode was written and read back exactly in "
            "all %d values of its %d-bit field under both timestamp sources, at the shortest "
            "frame and stream lengths, with a burst of the uncompressed stream driven under each",
            1 << sync.width,
            sync.width,
        )

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._bring_up()
        await self._open_sink(0, "first")

        data = sink_register("Trdstramdata")
        wp = sink_register("Trdstramwplow")
        self.baseline_data = await self._read(data, "baseline")
        self.baseline_wp = await self._read(wp, "baseline")
        assert self.baseline_data == 0, (
            f"DST_SINK Trdstramdata @ 0x{data.addr:08x} reads 0x{self.baseline_data:08x} "
            f"before any trace has been captured; an empty sink RAM reads 0, so a non-zero "
            f"word during the live phase would not be evidence of captured trace"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-CONCURRENT-IDLE: the sink RAM data port reads 0x%08x and the write "
            "pointer 0x%08x with the sink armed and no trace yet captured, so what the "
            "live phase below reads is the trace it is producing",
            self.baseline_data,
            self.baseline_wp,
        )

        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "dst",
        )
        logical_op = await self._arm_cla()
        await self._fill_window(logical_op)
        await self._stream_and_drain(logical_op)

        assert self.positions_driven == len(_READ_POSITIONS), (
            f"the live phase drove {self.positions_driven} read-pointer positions, not the "
            f"{len(_READ_POSITIONS)} across the 0x{_SINK_WINDOW_BYTES:x}-byte window"
        )
        assert self.nonzero_words > 0, (
            f"all {self.words_read} words the RAM data port returned during the live trace "
            f"were zero, the same as the baseline before it started, so nothing the trace "
            f"was writing was readable while it ran"
        )
        moved = [w for w in self.wp_samples if w != self.baseline_wp]
        assert moved, (
            f"the sink write pointer stayed at 0x{self.baseline_wp:08x} for all "
            f"{len(self.wp_samples)} samples taken during the live phase, so the trace was "
            f"not writing while the read side was being driven and this leaf proves nothing "
            f"the readout leaf does not"
        )
        self.value_checks += 3
        cocotb.log.info(
            "CHK-DST-CONCURRENT-DRAIN: inside one live trace the read pointer was driven to "
            "%d positions across the 0x%x-byte window, the RAM data port returned %d "
            "non-zero words of the %d it was read for against a zero baseline, and the "
            "write pointer was sampled away from its starting value on %d of %d samples, so "
            "the sink was reading and writing at the same time",
            self.positions_driven,
            _SINK_WINDOW_BYTES,
            self.nonzero_words,
            self.words_read,
            len(moved),
            len(self.wp_samples),
        )

        # The destination mode again, this time with the trace still armed.
        mode = reg_field(sink_register("Trdstramcontrol"), "Trdstrammode")
        await self._open_sink(1, "live")
        await self._stream_and_drain(logical_op)
        assert sorted(set(self.modes_live)) == list(range(1 << mode.width)), (
            f"the sink ran in modes {sorted(set(self.modes_live))} of the "
            f"{1 << mode.width} its {mode.width}-bit field offers"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-CONCURRENT-MODE: the sink was armed and driven through a live trace in "
            "both values of its %d-bit destination-mode field, each written with the sink "
            "active and enabled and read back exactly, with the read side driven underneath "
            "in each",
            mode.width,
        )

        # A compressed stream, with the frame shape walked underneath it.
        await self._open_sink(0, "shaped")
        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_XOR_VLT},
            "compressed",
        )
        await self._walk_frame_shape(logical_op)
        cfg = dst_register("CDbgDebugTraceCfg")
        closure = reg_field(cfg, "FrameClosureMode")
        length = reg_field(dst_register("Trdstimpl"), "Trdstvendorframelength")
        expected = {(m, v) for m in range(1 << closure.width) for v in range(1 << length.width)}
        assert self.frame_shapes == expected, (
            f"the frame-shape walk covered {len(self.frame_shapes)} of the {len(expected)} "
            f"combinations of the {closure.width}-bit closure mode and the {length.width}-bit "
            f"frame length"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-CONCURRENT-FRAMEWALK: under a compressed stream the frame shape was "
            "walked through all %d combinations of the closure mode and the frame length, "
            "each written and read back exactly, so the offsets packets land on inside the "
            "accumulator were moved across every frame geometry the register contract "
            "offers; no register addresses that offset directly",
            len(expected),
        )

        await self._walk_odd_offsets(logical_op)
        await self._stop_in_software(logical_op)
        await self._stop_on_wrap(logical_op)
        await self._walk_sync_modes(logical_op)
        await self._high_start(logical_op)
        await self._window_edges(logical_op)
        # A software stop after memory mode does not empty the packetizer, so
        # nothing may follow that needs it to.
        await self._memory_backpressure(logical_op)
        await self._frame_mode_off(logical_op)

        for reg in (
            dst_register("Trdstcontrol"),
            dst_register("Trdstimpl"),
            dst_register("CDbgDebugTraceCfg"),
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            cla_register("CDbgMuxSelLo"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "restore")
