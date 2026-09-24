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
happen in the *same* phase.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import (
    dfd_register,
    dst_register,
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

_SETTLE_CYCLES = 16
_DELIVER_POLLS = 32


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
        assert readback & reg.rw_mask == word & reg.rw_mask, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: wrote 0x{word & reg.rw_mask:x} into its "
            f"software-writable bits, reads 0x{readback & reg.rw_mask:x}"
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

    async def _open_sink(self, mode: int, label: str) -> None:
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, f"{label}_off")
        for name, value in (
            ("Trdstramstartlow", 0),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", _SINK_WINDOW_BYTES),
            ("Trdstramlimithigh", 0),
            ("Trdstramwplow", 0),
            ("Trdstramrplow", 0),
        ):
            reg = sink_register(name)
            await self._write(reg, value & reg.rw_mask, label)
        await self._write_check(
            control,
            {"Trdstramactive": 1, "Trdstramenable": 1, "Trdstrammode": mode},
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
                await self._write(rp, offset & rp.rw_mask, f"seek{offset:x}")
                self.positions_driven += 1
                word = await self._read(data, f"data{offset:x}")
                self.words_read += 1
                if word:
                    self.nonzero_words += 1
                self.wp_samples.append(await self._read(wp, f"wp{offset:x}"))
        await self._write(eap, eap.reset_word, "quiet")

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

        for reg in (
            dst_register("Trdstcontrol"),
            dst_register("Trdstimpl"),
            dst_register("CDbgDebugTraceCfg"),
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "restore")
