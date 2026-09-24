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
  while that stream runs and come back to 1, its reset value, once the enable
  has been cleared. Before the stop the stream runs at the longest frame length
  the field offers and then at the shortest frame and stream lengths.
* **The sink's stop-on-wrap setting.** With ``Trdstramstoponwrap`` set, the write
  pointer has to advance and then park inside the window while the trace is
  still being driven, rather than come round again. The sink enable is then
  cleared with the sink kept active and the setting still held, and the pointer
  has to stay where it parked.

After both, ``Trdstsyncmode`` is walked through every value of its field under
each timestamp source, on a fresh sink with the uncompressed stream running and
the restarting action held so the stream runs for many frames under each.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import (
    checked_mask,
    dfd_register,
    dst_register,
    field_word,
    funnel_register,
    pack_fields,
    reg_field,
    sink_register,
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

# dfx_ctrl_status.rdl Dbmmode, the values its description names as normal debug
# mode and the mux identifier output mode.
_DBM_MODE_NORMAL = 1
_DBM_MODE_IDENTIFIER = 2
# Mode switches in the odd-offset walk: each makes one compressed packet, and a
# run of equal odd-sized packets visits every offset of the 64-byte accumulator
# within 64 packets, so this leaves room for a frame closing part way.
_ODD_SWITCHES = 160
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
        self.wrap_samples: list[int] = []
        self.sampled_mux = -1
        self.odd_bytes = 0
        self.odd_states = (0, 0)
        self.odd_start_action = -1
        self.odd_pointer = (0, 0)

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
        self, mode: int, label: str, window: int = _SINK_WINDOW_BYTES, stop_on_wrap: int = 0
    ) -> None:
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, f"{label}_off")
        for name, value in (
            ("Trdstramstartlow", 0),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", window),
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

    async def _snapshot(self, label: str) -> int:
        lo = cla_register("CDbgSignalSnapshotNode0Eap0Lo")
        hi = cla_register("CDbgSignalSnapshotNode0Eap0Hi")
        low = await self._read(lo, f"{label}_lo")
        high = await self._read(hi, f"{label}_hi")
        return (high << 32) | low

    async def _set_mux_mode(self, identity: int, mode: int, label: str) -> None:
        mux = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        await self._write(mux, pack_fields(mux, {"Dbmmode": mode, "Dbmid": identity}), label)

    async def _restart_compressed(self, logical_op: int, modes: tuple[int, int]) -> None:
        """Empty the DST, re-enable it compressed, and find an action that restarts the trace.

        Clearing the enable alone with the DST active empties the packetizer, so
        ``Trdstempty`` reads 1 before the restart. Which action code starts a trace
        is not published, so the action field is walked, the bus switched twice
        under each value, and the first value that makes ``Trdstempty`` read 0 is
        held: packets are arriving, so the trace is running.
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
        cla_mux = cla_register("CDbgMuxSelLo")
        for identity in range(1 << dbmid.width):
            await self._write(
                cla_mux,
                pack_fields(cla_mux, {"Dbmmode": _DBM_MODE_NORMAL, "Dbmid": identity}),
                f"clamux{identity}",
            )
        for identity in range(1 << dbmid.width):
            await self._set_mux_mode(identity, _DBM_MODE_IDENTIFIER, f"ident{identity}")
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        identifier_state = await self._snapshot("ident")
        for identity in range(1 << dbmid.width):
            await self._set_mux_mode(identity, _DBM_MODE_NORMAL, f"probe{identity}")
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            normal_state = await self._snapshot(f"probe{identity}")
            if normal_state != identifier_state:
                self.sampled_mux = identity
                break
        else:
            raise AssertionError(
                f"the Node0Eap0 debug-signal snapshot stayed 0x{identifier_state:016x} as each "
                f"of the {1 << dbmid.width} mux identifiers was returned to normal mode, so no "
                f"mux mode change reaches the bus the trace samples"
            )
        diff = identifier_state ^ normal_state
        self.odd_bytes = sum(1 for b in range(8) if (diff >> (8 * b)) & 0xFF)
        self.odd_states = (identifier_state, normal_state)
        assert self.odd_bytes % 2 == 1, (
            f"the two bus states 0x{identifier_state:016x} and 0x{normal_state:016x} differ in "
            f"{self.odd_bytes} bytes, an even count, so switching between them makes packets "
            f"no different in parity from the uncompressed ones"
        )
        modes = (_DBM_MODE_IDENTIFIER, _DBM_MODE_NORMAL)
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
        final = await self._snapshot("odd_end")
        assert final == normal_state, (
            f"after {_ODD_SWITCHES} switches ending in normal mode the snapshot reads "
            f"0x{final:016x}, not the normal-mode state 0x{normal_state:016x}, so the "
            f"switching did not move the bus between the two measured states"
        )
        for identity in range(1 << dbmid.width):
            await self._set_mux_mode(identity, _DBM_MODE_NORMAL, f"renormal{identity}")
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

    # -- stopping the trace -----------------------------------------------

    async def _stop_in_software(self, logical_op: int) -> None:
        """Run the uncompressed stream, then clear the enable with the DST kept active."""
        control = dst_register("Trdstcontrol")
        empty = reg_field(control, "Trdstempty")
        impl = dst_register("Trdstimpl")
        length = reg_field(impl, "Trdstvendorframelength")
        stream = reg_field(impl, "Trdstvendorstreamlength")
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
        await self._write_check(
            control,
            {"Trdstactive": 1, "Trdstenable": 0, "Trdstformat": _DST_FORMAT_NONE},
            "stop",
        )
        for poll in range(_DELIVER_POLLS):
            if await self._read(control, f"stop{poll}") & empty.mask:
                self.stop_polls = poll + 1
                break
        assert self.stop_polls, (
            f"DST Trdstempty stayed 0 for {_DELIVER_POLLS} polls after Trdstenable was cleared "
            f"with Trdstactive held at 1, so the trace did not wind down to empty"
        )
        self.value_checks += 2
        cocotb.log.info(
            "CHK-DST-CONCURRENT-STOP: with the uncompressed stream running, first at the "
            "longest frame length and then at the shortest frame and stream lengths, "
            "Trdstempty read 0; clearing Trdstenable alone with the DST kept active brought "
            "it back to 1 on poll %d of at most %d",
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
