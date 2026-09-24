# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read the captured trace back out of the sink RAM and cycle the sink's modes.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap` and :mod:`seq_lib.smc_cla_regmap`. The vendored
RTL is not a source for any value this sequence programs or compares against.

The trace leaves already on this branch fill the sink and stop there, so the
sink's read side is never used: its read pointer stays at its reset, the
buffer never reads non-empty against the write pointer, and the RAM data port
is never taken. This sequence drives the other half of the same register
contract, all of it ``sw = rw`` in ``dfd_dst_sink.rdl``:

* ``Trdstramrplow`` is walked across the window, and ``Trdstramdata``
  (``sw = r``, hardware-driven) is read at each position. The RAM is read once
  before any trace has run, so an all-zero baseline is on record and the
  non-zero words afterwards are the captured trace rather than whatever the
  port returns when nothing is there.
* ``Trdstramrplow`` is then placed on the last word of the window, which is
  the position the sink folds back to the window start from. Every position
  written has to read back exactly. The field is ``hw = rw`` and sits above two
  reserved bits, so the register's plain read-write mask leaves it out; the
  window and pointer registers are written through each field's own bit
  positions instead.
* Before the sink is deactivated the trace runs until the sink's wrap flag
  reports one full pass of the window, so every position read out holds a
  word the trace wrote.
* ``Trdstrammode`` is programmed to both values of its one-bit field with the
  sink active, since the sink picks its destination from it.
* ``Trdstramactive`` is taken from 1 to 0 with the sink enabled, which is the
  deactivation edge the sink acts on.
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

# dfd_dst.rdl Trdstformat: "2'b0 (No Compression)".
_DST_FORMAT_NONE = 0

_SINK_WINDOW_BYTES = 0x400
# Read-pointer positions walked across the window, as byte offsets.
_READ_POSITIONS = tuple(range(0, _SINK_WINDOW_BYTES, _SINK_WINDOW_BYTES // 16))

_SETTLE_CYCLES = 32
# Action sweeps the fill may take to come round the window once.
_FILL_SWEEPS = 8


class smc_dfd_trace_sink_readout_test_seq(SmcCsrSeq):
    """Fill the sink, read the trace back out of it, and cycle its mode and enables."""

    def __init__(self, name: str = "smc_dfd_trace_sink_readout_test_seq") -> None:
        super().__init__(name)
        self.baseline: int | None = None
        self.words_read = 0
        self.nonzero_words = 0
        self.modes_programmed: list[int] = []
        self.positions_landed = 0
        self.deactivated = False
        self.fill_sweeps = 0
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

    async def _seek(self, offset: int) -> None:
        """Place the sink read pointer on one byte offset and require it to read back."""
        rp = sink_register("Trdstramrplow")
        field = reg_field(rp, "Trdstramrplow")
        await self._write(rp, field_word(rp, "Trdstramrplow", offset), f"seek{offset:x}")
        readback = await self._read(rp, f"seek{offset:x}_rb")
        want = (offset & field.mask) >> field.offset
        got = (readback & field.mask) >> field.offset
        assert got == want, (
            f"DST_SINK Trdstramrplow @ 0x{rp.addr:08x} reads 0x{readback:08x} after the read "
            f"pointer was written to byte offset 0x{offset:x}; the field holds 0x{got:x}, not "
            f"0x{want:x}"
        )
        self.positions_landed += 1
        self.value_checks += 1

    # -- phases -----------------------------------------------------------

    async def _bring_up(self) -> None:
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write_check(clk, {"force_clk_en": 1}, "force")
        mux = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(mux, "Dbmid")
        for value in range(1 << dbmid.width):
            await self._write(
                mux, pack_fields(mux, {"Dbmmode": 1, "Dbmid": value}), f"normal_id{value}"
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
            await self._write(reg, field_word(reg, name, value), label)
        await self._write_check(
            sink_register("Trdstramcontrol"),
            {"Trdstramactive": 1, "Trdstramenable": 1, "Trdstrammode": mode},
            f"{label}_mode{mode}",
        )
        self.modes_programmed.append(mode)

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

    async def _run_actions(self, logical_op: int, label: str) -> None:
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        for value in range(1 << action.width):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"{label}{value}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)

    async def _fill_window(self, logical_op: int) -> None:
        """Keep the trace running until the sink reports one full pass of its window."""
        wp = sink_register("Trdstramwplow")
        wrap = reg_field(wp, "Trdstramwrap")
        for sweep in range(_FILL_SWEEPS):
            await self._run_actions(logical_op, f"fill{sweep}_")
            if await self._read(wp, f"fill{sweep}") & wrap.mask:
                self.fill_sweeps = sweep + 1
                self.value_checks += 1
                return
        raise AssertionError(
            f"the sink wrap flag stayed 0 through {_FILL_SWEEPS} sweeps of the action field, "
            f"so the trace never came round the 0x{_SINK_WINDOW_BYTES:x}-byte window and the "
            f"read-out positions would include words it never wrote"
        )

    async def _deactivate(self) -> None:
        """Take the sink from active to inactive with its enable still set."""
        control = sink_register("Trdstramcontrol")
        active = reg_field(control, "Trdstramactive")
        before = await self._read(control, "active_before")
        assert before & active.mask, (
            f"DST_SINK Trdstramcontrol @ 0x{control.addr:08x} reads 0x{before:08x}, with "
            f"Trdstramactive already clear, so taking it low would not be an edge"
        )
        await self._write_check(control, {"Trdstramactive": 0, "Trdstramenable": 1}, "deactivate")
        self.deactivated = True
        self.value_checks += 2
        cocotb.log.info(
            "CHK-DST-SINK-DEACTIVATE: Trdstramactive was taken from 1 to 0 with "
            "Trdstramenable held at 1 and the change read back, so the sink saw a "
            "deactivation edge with a captured trace still in its window"
        )

    async def _read_out(self) -> None:
        data = sink_register("Trdstramdata")
        for offset in list(_READ_POSITIONS) + [_SINK_WINDOW_BYTES - 4]:
            await self._seek(offset)
            word = await self._read(data, f"data{offset:x}")
            self.words_read += 1
            if word:
                self.nonzero_words += 1

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._bring_up()

        await self._open_sink(0, "baseline")
        data = sink_register("Trdstramdata")
        await self._seek(0)
        self.baseline = await self._read(data, "baseline")
        assert self.baseline == 0, (
            f"DST_SINK Trdstramdata @ 0x{data.addr:08x} reads 0x{self.baseline:08x} at read "
            f"pointer 0 before any trace has been captured; an empty sink RAM reads 0, so a "
            f"non-zero word afterwards would not be evidence of captured trace"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-SINK-BASELINE: the sink RAM data port reads 0x%08x at read pointer 0 "
            "with the sink armed and no trace yet captured, so the words the read-out below "
            "returns are the trace this run captured",
            self.baseline,
        )

        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "dst",
        )
        logical_op = await self._arm_cla()
        await self._fill_window(logical_op)
        await self._deactivate()
        await self._read_out()

        assert self.nonzero_words > 0, (
            f"all {self.words_read} words read out of the sink RAM across "
            f"{len(_READ_POSITIONS)} read-pointer positions in a 0x{_SINK_WINDOW_BYTES:x}-byte "
            f"window were zero, the same as the baseline before any trace ran, so nothing "
            f"the trace captured is readable through Trdstramdata"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-SINK-READOUT: after %d action sweep(s) brought the sink round its "
            "0x%x-byte window, the read pointer was driven to %d positions across it including "
            "its last word, each read back exactly (%d seeks in all with the baseline), and %d "
            "of the %d words the RAM data port returned were non-zero against a baseline of "
            "0x%08x read before the trace ran",
            self.fill_sweeps,
            _SINK_WINDOW_BYTES,
            self.words_read,
            self.positions_landed,
            self.nonzero_words,
            self.words_read,
            self.baseline,
        )

        # Both values of the one-bit destination-mode field, with the sink active.
        mode = reg_field(sink_register("Trdstramcontrol"), "Trdstrammode")
        for value in range(1 << mode.width):
            await self._open_sink(value, f"mode{value}")
            await self._run_actions(logical_op, f"mode{value}_")
        assert sorted(set(self.modes_programmed)) == list(range(1 << mode.width)), (
            f"the sink was only run in modes {sorted(set(self.modes_programmed))} of the "
            f"{1 << mode.width} its {mode.width}-bit Trdstrammode field offers"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-SINK-MODE: the sink was armed and run with Trdstrammode at both values "
            "of its %d-bit field, each written with the sink active and enabled and read "
            "back exactly",
            mode.width,
        )

        for reg in (
            dst_register("Trdstcontrol"),
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "restore")
