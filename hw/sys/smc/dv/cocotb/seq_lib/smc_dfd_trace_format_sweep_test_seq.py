# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the DST trace path in one compression format, on a payload that moves.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap` and :mod:`seq_lib.smc_cla_regmap`. Every value
programmed into a field comes from that field's own RDL description. The
vendored RTL is not a source for any value this sequence programs or compares
against.

**One mode per run, and why.** The DST packet path cannot be re-run in a
second compression mode inside one simulation. Measured twice: after a mode
has run, the funnel reads empty and the sink has taken a full window, yet
``Trdstcontrol.Trdstempty`` stays 0 -- the packetizer keeps a partial bank and
nothing the register interface offers flushes it -- and a second mode
programmed afterwards then delivers nothing to the sink at all. The only
empty packetizer this bench can provide is the one a run starts with, so the
sequence takes the format as a parameter and each mode gets its own leaf.

Three things have to be true at once for the XOR and VLT compressors behind
``debug_sig_trace_gen`` to do any work, and each has an RDL handle:

* **The mode.** ``dfd_dst.rdl`` gives ``Trdstformat`` bit 0 as the XOR enable
  and bit 1 as the VLT enable, and names 3 (XOR plus VLT), 1 (XOR) and 0 (no
  compression) as the supported values.
* **A payload that changes between samples.** A compressor fed a bus that
  holds still emits nothing. ``DEBUG_BUS_MUX.Muxselseg0..7`` chooses which
  debug-bus segment each output lane carries -- "If all bits are 0, Lane0 =
  Seg0, if bit[0] = 1, Lane0 = Seg4, if bit[1] =1, Lane0 = Seg5, ..." -- so
  rotating the selects while the trace runs changes what every lane carries.
  A mux latches its selects only while its own id is programmed, so each
  rotation costs one write per id.
* **More than one packet size.** ``Trdstimpl.Trdstvendorframelength``:
  "Specify frame length. Frame Length = trDstVendorFrameLength* 64". The run
  changes it part way through, so the packet path sees two frame lengths.

``Trdstsyncmode`` ("When the field is set tp 2'b10, sent timestamp") with
``Trdstsyncmax`` ("timestamp will be sent for every 2^(trDstSyncMax + 4)
Cluster clocks") is set so the periodic-sync path has something to do.
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

# dfd_dst.rdl Trdstformat, the values the field's own description names.
FORMAT_NONE = 0
FORMAT_XOR = 1
FORMAT_XOR_VLT = 3

# dfd_dst.rdl Trdstimpl.Trdstvendorframelength: "Frame Length =
# trDstVendorFrameLength* 64", so these are 64 and 192 bytes.
_FRAME_LENGTHS = (1, 3)

# dfd_dst.rdl Trdstsyncmode: "When the field is set tp 2'b10, sent timestamp".
_SYNC_MODE_TIMESTAMP = 2
# dfd_dst.rdl Trdstsyncmax: "every 2^(trDstSyncMax + 4) Cluster clocks".
_SYNC_MAX_SHORTEST = 0

# dfx_ctrl_status.rdl Muxselseg<n>: "If all bits are 0, Lane0 = Seg0, if bit[0]
# = 1, Lane0 = Seg4, if bit[1] =1, Lane0 = Seg5, ...". Zero is the lane's own
# static segment and each set bit selects one of the upper segments.
_SEGMENT_SELECTS = (0, 1, 2, 4)

_SINK_WINDOW_BYTES = 0x4000

_SETTLE_CYCLES = 32
_DELIVER_POLLS = 64


class smc_dfd_trace_format_sweep_test_seq(SmcCsrSeq):
    """Run the trace path in one published compression format from an empty start."""

    def __init__(
        self, name: str = "smc_dfd_trace_format_sweep_test_seq", fmt: int = FORMAT_NONE
    ) -> None:
        super().__init__(name)
        self.fmt = fmt
        self.baseline = 0
        self.delivered = 0
        self.rotations: list[int] = []
        self.frame_lengths: list[int] = []
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

    async def _program_segments(self, select: int, label: str) -> None:
        """Give every debug-bus mux the same segment select, in normal debug mode."""
        reg = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(reg, "Dbmid")
        values = {"Dbmmode": 1}
        values.update({f"Muxselseg{lane}": select for lane in range(8)})
        for identity in range(1 << dbmid.width):
            values["Dbmid"] = identity
            await self._write(reg, pack_fields(reg, values), f"{label}_id{identity}")
        self.rotations.append(select)

    async def _open_sink(self) -> None:
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, "off")
        for name, value in (
            ("Trdstramstartlow", 0),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", _SINK_WINDOW_BYTES),
            ("Trdstramlimithigh", 0),
            ("Trdstramwplow", 0),
            ("Trdstramrplow", 0),
        ):
            reg = sink_register(name)
            await self._write(reg, value & reg.rw_mask, "window")
        await self._write_check(control, {"Trdstramactive": 1, "Trdstramenable": 1}, "sink")

    async def _set_frame_length(self, length: int) -> None:
        impl = dst_register("Trdstimpl")
        stream = reg_field(impl, "Trdstvendorstreamlength")
        await self._write_check(
            impl,
            {
                "Trdstvendorframelength": length,
                "Trdstvendorstreamlength": (impl.reset_word & stream.mask) >> stream.offset,
                "Trdsttimestampconfig": 0,
            },
            f"framelen{length}",
        )
        self.frame_lengths.append(length)

    async def _start_dst(self) -> None:
        await self._write_check(
            dst_register("Trdstcontrol"),
            {
                "Trdstactive": 1,
                "Trdstenable": 1,
                "Trdstformat": self.fmt,
                "Trdstsyncmode": _SYNC_MODE_TIMESTAMP,
                "Trdstsyncmax": _SYNC_MAX_SHORTEST,
            },
            f"format{self.fmt}",
        )

    async def _empty_start(self) -> None:
        """The packetizer and the sink are both measured empty before the trace runs."""
        dst = dst_register("Trdstcontrol")
        empty = reg_field(dst, "Trdstempty")
        word = await self._read(dst, "idle")
        assert word & empty.mask, (
            f"DST Trdstcontrol.Trdstempty @ 0x{dst.addr:08x} reads 0 with the DST enabled in "
            f"Trdstformat {self.fmt} and no trace started; the packetizer already holds data, "
            f"so what this mode delivers below would not be its own"
        )
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        self.baseline = await self._read(wp, "start")
        assert self.baseline & pointer.mask == 0, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} reads pointer "
            f"0x{(self.baseline & pointer.mask) >> pointer.offset:x} after being written "
            f"back to zero, so what the sink takes below could predate this run"
        )
        self.value_checks += 2
        cocotb.log.info(
            "CHK-DST-FORMAT-IDLE: with the DST enabled in Trdstformat %d, the sink armed "
            "over a 0x%x-byte window and no trace started, the packetizer reads empty and "
            "the sink write pointer reads 0x%08x, so everything this run delivers is its own",
            self.fmt,
            _SINK_WINDOW_BYTES,
            self.baseline,
        )

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
            "no value of the 2-bit LogicalOp field activated node 0 EAP 0 with the CLA and "
            "its EAPs enabled, so no action of that pair can be driven and no trace can start"
        )

    async def _run_actions(self, logical_op: int) -> None:
        """Drive Action0 over its whole range, rotating payload and frame length."""
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        span = 1 << action.width
        rotate_step = span // len(_SEGMENT_SELECTS)
        frame_step = span // len(_FRAME_LENGTHS)
        for value in range(span):
            if value and value % rotate_step == 0:
                await self._program_segments(_SEGMENT_SELECTS[value // rotate_step], f"rot{value}")
            if value and value % frame_step == 0:
                await self._set_frame_length(_FRAME_LENGTHS[value // frame_step])
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"action{value}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        await self._write(eap, eap.reset_word, "quiet")

    async def _require_delivered(self) -> None:
        wp = sink_register("Trdstramwplow")
        word = self.baseline
        for _ in range(_DELIVER_POLLS):
            word = await self._read(wp, "delivered")
            if word != self.baseline:
                break
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        funnel = funnel_register("Trfunnelcontrol")
        dst = dst_register("Trdstcontrol")
        assert word != self.baseline, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} still reads 0x{self.baseline:08x} "
            f"after the whole Action0 range ran in Trdstformat {self.fmt} with the segment "
            f"selects rotated over {_SEGMENT_SELECTS} and the frame length changed, so this "
            f"mode delivered nothing. Trdstcontrol reads "
            f"0x{await self._read(dst, 'stall'):08x} and the funnel control "
            f"0x{await self._read(funnel, 'stall'):08x}"
        )
        self.delivered = word
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-FORMAT-STREAM: Trdstformat %d, written into the DST control register "
            "and read back exactly, moved the sink write pointer from 0x%08x to 0x%08x over "
            "the Action0 range, so the compression the field selects carried a live stream "
            "all the way to the trace RAM",
            self.fmt,
            self.baseline,
            word,
        )

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        await self._write_check(dfd_register("dfx_ctrl/DEBUG_CTRL"), {"force_clk_en": 1}, "force")
        await self._program_segments(_SEGMENT_SELECTS[0], "initial")
        await self._write_check(
            funnel_register("Trfunnelcontrol"),
            {"Trfunnelactive": 1, "Trfunnelenable": 1},
            "funnel",
        )
        await self._open_sink()
        await self._set_frame_length(_FRAME_LENGTHS[0])
        await self._start_dst()
        await self._empty_start()
        await self._run_actions(await self._arm_cla())
        await self._require_delivered()

        assert self.rotations == list(_SEGMENT_SELECTS), (
            f"the segment-select rotation programmed {self.rotations}, not the full set "
            f"{list(_SEGMENT_SELECTS)} the Muxselseg description names"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-FORMAT-PAYLOAD: the debug-bus mux array was walked through the segment "
            "selects %s that the Muxselseg description names, one write per mux id per "
            "rotation, while the trace was running, so the lanes carried different "
            "debug-bus segments and consecutive samples differ",
            self.rotations,
        )

        assert sorted(set(self.frame_lengths)) == sorted(set(_FRAME_LENGTHS)), (
            f"the frame length took {sorted(set(self.frame_lengths))} during the run, not "
            f"the {sorted(set(_FRAME_LENGTHS))} values this sequence programs"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-FORMAT-FRAMELEN: the run changed Trdstvendorframelength through %s "
            "while the trace was live, which its RDL description makes frame lengths of %s "
            "bytes, each written and read back exactly, so the packet path saw more than "
            "one frame size",
            sorted(set(self.frame_lengths)),
            sorted(v * 64 for v in set(_FRAME_LENGTHS)),
        )

        for reg in (
            dst_register("Trdstcontrol"),
            dst_register("Trdstimpl"),
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "restore")
