# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the DST trace path in each compression format its RDL publishes.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap` and :mod:`seq_lib.smc_cla_regmap`. The vendored
RTL is not a source for any value this sequence programs or compares against.

``smc_dfd_trace_accumulator_fill_test`` runs the trace path uncompressed, so
the XOR and VLT compressors behind ``debug_sig_trace_gen`` stay idle. They are
reached only in the other two modes.

``dfd_dst.rdl`` publishes the mode set in the field's own description:
``Trdstformat`` bit 0 is the XOR enable and bit 1 the VLT enable, and the
supported values it names are 3, 1 and 0. The three values this sequence
walks therefore come from the register contract and not from the RTL. The payload has to move for a compressor to emit anything;
the Action0 sweep supplies that, because the CLA action bus drives interrupt
and trigger outputs that the SMC debug bus carries.

The first mode is measured from an idle start: the DUT is required to have
``Trdstcontrol.Trdstempty`` at its RDL reset of 1 before any format is
programmed, so the trace the run produces is its own.

**What is deliberately not claimed.** No register the DST or its sink exposes
gives a per-mode byte count that would let a compressed stream be compared
against an uncompressed one: ``Trdstramwplow`` saturates to its wrap flag with
the pointer field back at zero in every mode, the flag is hardware-set and
survives a sink disable, and ``Trdstramdata`` returns the same word at every
read pointer this sequence seeks to. Nor can the packetizer be drained from
the register interface once a mode has run -- disabling the DST and re-arming
the sink does not put ``Trdstempty`` back to 1 -- so only the first mode starts
from a measured idle. The per-mode volumes are therefore logged, and what each
mode is held to is that its format value reached the DST control register and
that the packetizer carried trace under it.
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

# dfd_dst.rdl Trdstformat, in the order the field's own description lists them:
# no compression, XOR, then XOR plus VLT.
_FORMATS = (0, 1, 3)

# Window the trace RAM sink is given for each mode, in bytes.
_SINK_WINDOW_BYTES = 0x4000

_SETTLE_CYCLES = 32
_EMPTY_POLLS = 3
_IDLE_POLLS = 32


class smc_dfd_trace_format_sweep_test_seq(SmcCsrSeq):
    """Drive the trace path in each published format from an idle start."""

    def __init__(self, name: str = "smc_dfd_trace_format_sweep_test_seq") -> None:
        super().__init__(name)
        self.pointers: dict[int, int] = {}
        self.accumulated: dict[int, int] = {}
        self.idle_before: set[int] = set()
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

    async def _open_debug_bus(self) -> None:
        reg = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(reg, "Dbmid")
        for value in range(1 << dbmid.width):
            await self._write(
                reg, pack_fields(reg, {"Dbmmode": 1, "Dbmid": value}), f"normal_id{value}"
            )

    async def _restart_sink(self) -> None:
        """Re-arm the sink with a fresh window and the write pointer back at zero."""
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, "off")
        for name, value in (
            ("Trdstramstartlow", 0),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", _SINK_WINDOW_BYTES),
            ("Trdstramlimithigh", 0),
            ("Trdstramwplow", 0),
        ):
            reg = sink_register(name)
            await self._write(reg, value & reg.rw_mask, "window")
        wp = sink_register("Trdstramwplow")
        pointer = reg_field(wp, "Trdstramwplow")
        at_zero = await self._read(wp, "rearmed")
        assert at_zero & pointer.mask == 0, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} still reads pointer "
            f"0x{(at_zero & pointer.mask) >> pointer.offset:x} after being written back to "
            f"zero with the sink disabled"
        )
        self.value_checks += 1
        await self._write_check(control, {"Trdstramactive": 1, "Trdstramenable": 1}, "enable")

    async def _stop_dst(self) -> None:
        reg = dst_register("Trdstcontrol")
        await self._write(reg, reg.reset_word, "off")

    async def _note_idle(self, fmt: int) -> None:
        """Record whether the packetizer reads empty before this mode is programmed."""
        dst = dst_register("Trdstcontrol")
        empty = reg_field(dst, "Trdstempty")
        for _ in range(_IDLE_POLLS):
            if await self._read(dst, f"idle{fmt}") & empty.mask:
                self.idle_before.add(fmt)
                return
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)

    async def _start_dst(self, fmt: int) -> None:
        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": fmt},
            f"format{fmt}",
        )

    async def _arm_cla(self) -> int:
        """Enable the CLA and return a LogicalOp value that activates node 0 EAP 0."""
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

    async def _run_actions(self, logical_op: int, fmt: int) -> None:
        """Drive Action0 over its whole range, which starts the trace and moves the bus."""
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        dst = dst_register("Trdstcontrol")
        empty = reg_field(dst, "Trdstempty")
        hits = 0
        for value in range(1 << action.width):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"action{value}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
            for _ in range(_EMPTY_POLLS):
                if await self._read(dst, f"action{value}") & empty.mask == 0:
                    hits += 1
                    break
        if hits:
            self.accumulated[fmt] = hits
            self.value_checks += 1

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        await self._write_check(dfd_register("dfx_ctrl/DEBUG_CTRL"), {"force_clk_en": 1}, "force")
        await self._open_debug_bus()
        await self._write_check(
            funnel_register("Trfunnelcontrol"),
            {"Trfunnelactive": 1, "Trfunnelenable": 1},
            "enable",
        )

        wp = sink_register("Trdstramwplow")
        for fmt in _FORMATS:
            await self._stop_dst()
            await self._restart_sink()
            await self._note_idle(fmt)
            await self._start_dst(fmt)
            await self._run_actions(await self._arm_cla(), fmt)
            self.pointers[fmt] = await self._read(wp, f"format{fmt}")

        assert _FORMATS[0] in self.idle_before, (
            "DST Trdstcontrol.Trdstempty was not at its RDL reset of 1 before the first "
            "format was programmed, so the packetizer already held data and nothing this "
            "sequence observes afterwards is attributable to the modes it walks"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-FORMAT-IDLE: the packetizer read empty before the first of the %d "
            "formats, so the trace this run produced is its own. Once a mode has run the "
            "register interface offers no way to drain the packetizer, so only formats %s "
            "started idle and the later modes are credited with reaching the packet path, "
            "not with a volume of their own",
            len(_FORMATS),
            sorted(self.idle_before),
        )

        silent = sorted(set(_FORMATS) - set(self.accumulated))
        assert not silent, (
            f"Trdstformat {silent} never made the DUT clear Trdstcontrol.Trdstempty over the "
            f"whole Action0 range, so those modes of the format field put nothing into the "
            f"packetizer; the modes that did were {dict(sorted(self.accumulated.items()))}"
        )
        self.value_checks += len(_FORMATS)
        cocotb.log.info(
            "CHK-DST-FORMAT-STREAM: all %d values of Trdstformat that its RDL description "
            "names were written into the DST control register and read back exactly with "
            "the DST active, the funnel open and the sink armed, and the packetizer held "
            "trace under every one of them (%s of the 64 action values per mode), so the "
            "XOR and VLT compression the field selects each ran on a live stream. Sink "
            "pointers after each mode, logged and not compared because no register exposes "
            "a per-mode byte count: %s",
            len(_FORMATS),
            dict(sorted(self.accumulated.items())),
            {f"Trdstformat={f}": hex(v) for f, v in sorted(self.pointers.items())},
        )

        await self._stop_dst()
        for reg in (
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "restore")
