# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Gate the trace stream at the funnel, then let it through into two sink windows.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap` and :mod:`seq_lib.smc_cla_regmap`. The vendored
RTL is not a source for any value this sequence programs or compares against.

``dfd_funnel.rdl`` splits ``Trfunneldisinput`` into a low half for the
N-trace sources and a high half for the DST sources, so setting that whole
upper half disables every DST source the funnel accepts without this sequence
having to know which bit belongs to which source. That gives a two-legged proof on the
same run:

* **Deny leg first.** With every DST source disabled the trace is started and
  the action field driven over its whole range. ``DST_SINK.Trdstramwplow`` has
  to stay at its RDL reset: nothing reached the sink. The leg is run first
  because the register's wrap flag is hardware-set and sticky, so a sink that
  has once taken data cannot be shown empty again.
* **Allow leg second.** The disable field is cleared and the DUT has to move
  ``Trdstramwplow`` off its reset, which is the same stream now reaching the
  sink. Without this leg the deny leg would also pass on a trace path that was
  dead for some other reason.

The allow leg keeps the stream running until the write pointer has passed the
size of the second, smaller window without wrapping in the first. The smaller
window is then programmed and the stream driven until the sink's wrap flag
sets, with every write-pointer sample required to stay inside it. The same
pointer that ran past that size in the large window is held under it in the
small one, so the limit register is what bounds it.

The window registers are written through each field's own bit positions: the
pointer and limit fields sit above two reserved bits and hardware writes them
too, so the register's plain read-write mask leaves them out.
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

# dfd_dst.rdl Trdstformat: "2'b0 (No Compression)", so every debug-bus sample
# becomes a packet and the two legs differ by the funnel alone.
_DST_FORMAT_NONE = 0

# The two sink windows, in bytes, both from the base the start registers reset
# to. The second is smaller so the sink is asked for a different bound.
_WINDOWS = (0x4000, 0x400)

_SETTLE_CYCLES = 32
_MOVE_POLLS = 32
# Action sweeps a leg may take to pass the small window or to wrap it.
_SWEEPS = 8


class smc_dfd_trace_sink_window_test_seq(SmcCsrSeq):
    """Block the trace at the funnel, release it, and take it into two windows."""

    def __init__(self, name: str = "smc_dfd_trace_sink_window_test_seq") -> None:
        super().__init__(name)
        self.denied_pointer: int | None = None
        self.allowed_pointer: int | None = None
        self.windows_taken: dict[int, int] = {}
        self.large_sweeps = 0
        self.small_samples: list[int] = []
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

    # -- bring-up ---------------------------------------------------------

    async def _open_sink(self, window: int, label: str) -> None:
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, f"{label}_off")
        for name, value in (
            ("Trdstramstartlow", 0),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", window),
            ("Trdstramlimithigh", 0),
            ("Trdstramwplow", 0),
        ):
            reg = sink_register(name)
            await self._write(reg, field_word(reg, name, value), label)
        await self._write_check(control, {"Trdstramactive": 1, "Trdstramenable": 1}, label)

    async def _set_funnel(self, disable_dst: bool, label: str) -> None:
        control = funnel_register("Trfunnelcontrol")
        await self._write_check(
            control, {"Trfunnelactive": 1, "Trfunnelenable": 1}, f"{label}_enable"
        )
        disin = funnel_register("Trfunneldisinput")
        field = reg_field(disin, "Trfunneldisinput")
        # The upper half of the field is the DST source half, per the split its
        # own RDL description states; the lower half is left enabled either way.
        upper = ((1 << (field.width // 2)) - 1) << (field.width // 2)
        word = (upper if disable_dst else 0) << field.offset
        await self._write(disin, word, label)
        readback = await self._read(disin, f"{label}_rb")
        assert readback & field.mask == word & field.mask, (
            f"{disin.path} @ 0x{disin.addr:08x} [{label}]: wrote 0x{word & field.mask:x}, "
            f"reads 0x{readback & field.mask:x}"
        )
        self.value_checks += 1

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
            "that pair can be driven and no trace can start"
        )

    async def _run_actions(self, logical_op: int, label: str) -> None:
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        for value in range(1 << action.width):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": logical_op, "DestNode": 0, "Action0": value}),
                f"{label}_action{value}",
            )
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)

    async def _await_pointer_move(self, label: str) -> int:
        wp = sink_register("Trdstramwplow")
        word = wp.reset_word
        for _ in range(_MOVE_POLLS):
            word = await self._read(wp, label)
            if word != wp.reset_word:
                return word
            await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)
        return word

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write_check(clk, {"force_clk_en": 1}, "force")
        mux = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        dbmid = reg_field(mux, "Dbmid")
        for value in range(1 << dbmid.width):
            await self._write(
                mux, pack_fields(mux, {"Dbmmode": 1, "Dbmid": value}), f"normal_id{value}"
            )

        wp = sink_register("Trdstramwplow")
        await self._open_sink(_WINDOWS[0], "deny")
        await self._set_funnel(disable_dst=True, label="deny")
        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "enable",
        )

        at_reset = await self._read(wp, "deny_pre")
        assert at_reset == wp.reset_word, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} reads 0x{at_reset:08x} before the "
            f"trace was started; its RDL reset is 0x{wp.reset_word:08x}, so the deny leg "
            f"below could not fail"
        )
        self.value_checks += 1

        logical_op = await self._arm_cla()
        await self._run_actions(logical_op, "deny")
        self.denied_pointer = await self._read(wp, "deny_post")
        assert self.denied_pointer == wp.reset_word, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} reads 0x{self.denied_pointer:08x} "
            f"after the whole Action0 range was driven with every DST source disabled in "
            f"the funnel; its RDL reset is 0x{wp.reset_word:08x}, so the funnel passed "
            f"trace it was told to block"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-FUNNEL-DENY: with the DST half of Trfunneldisinput set the sink write "
            "pointer stayed at its RDL reset of 0x%08x across the whole Action0 range, so "
            "the funnel blocked the stream; the allow leg below is what makes this "
            "distinguishable from a dead trace path",
            wp.reset_word,
        )

        pointer = reg_field(wp, "Trdstramwplow")
        wrap = reg_field(wp, "Trdstramwrap")
        await self._set_funnel(disable_dst=False, label="allow")
        await self._run_actions(logical_op, "allow")
        self.allowed_pointer = await self._await_pointer_move("allow_post")
        assert self.allowed_pointer & pointer.mask, (
            f"DST_SINK Trdstramwplow @ 0x{wp.addr:08x} reads 0x{self.allowed_pointer:08x} "
            f"after the DST sources were re-enabled in the funnel and the action range driven "
            f"again: the write pointer field is still 0, so nothing reaches the sink either "
            f"way and the deny leg above proves nothing"
        )
        self.value_checks += 1
        self.windows_taken[_WINDOWS[0]] = self.allowed_pointer
        cocotb.log.info(
            "CHK-DST-FUNNEL-ALLOW: clearing the DST half of Trfunneldisinput moved the sink "
            "write pointer off its reset to 0x%08x under the same stimulus that the deny "
            "leg blocked, so the funnel's input disable is what stopped the stream",
            self.allowed_pointer,
        )

        large, small = _WINDOWS
        word = self.allowed_pointer
        while word & pointer.mask <= small and self.large_sweeps < _SWEEPS:
            self.large_sweeps += 1
            await self._run_actions(logical_op, f"large{self.large_sweeps}")
            word = await self._read(wp, f"large{self.large_sweeps}")
        assert word & pointer.mask > small and not word & wrap.mask, (
            f"DST_SINK Trdstramwplow reads 0x{word:08x} after {self.large_sweeps} further "
            f"sweeps in the 0x{large:x}-byte window: the pointer has to pass 0x{small:x} "
            f"without wrapping for the small window below to be a bound it would otherwise "
            f"cross"
        )
        self.windows_taken[large] = word
        await self._open_sink(small, f"window{small:x}")
        for sweep in range(_SWEEPS):
            await self._run_actions(logical_op, f"window{small:x}_{sweep}")
            word = await self._read(wp, f"window{small:x}_{sweep}")
            self.small_samples.append(word)
            if word & wrap.mask:
                break
        outside = [w for w in self.small_samples if w & pointer.mask > small]
        assert not outside, (
            f"DST_SINK Trdstramwplow read {[hex(w) for w in outside]} with the sink armed over "
            f"a 0x{small:x}-byte window, past the limit it was given"
        )
        assert self.small_samples[-1] & wrap.mask, (
            f"the sink wrap flag stayed 0 through {len(self.small_samples)} sweeps in the "
            f"0x{small:x}-byte window, so the stream never reached the limit and the samples "
            f"above do not show it bounding anything"
        )
        self.windows_taken[small] = self.small_samples[-1]
        self.value_checks += 3
        cocotb.log.info(
            "CHK-DST-SINK-WINDOW: in the 0x%x-byte window the write pointer ran to 0x%08x, "
            "past 0x%x, without wrapping; re-armed over a 0x%x-byte window the same stream "
            "set the wrap flag with every one of %d samples (%s) inside that window, so "
            "Trdstramlimitlow is what bounds the pointer",
            large,
            self.windows_taken[large],
            small,
            small,
            len(self.small_samples),
            ", ".join(hex(w) for w in self.small_samples),
        )

        for reg in (
            dst_register("Trdstcontrol"),
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            funnel_register("Trfunneldisinput"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            mux,
            clk,
        ):
            await self._write(reg, reg.reset_word, "restore")
