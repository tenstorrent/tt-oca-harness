# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read the captured trace back out of the sink RAM and cycle the sink's modes.

Every address, field position, field width, reset value and software-access
type comes from the generated register map through
:mod:`seq_lib.smc_rdl_regmap` and :mod:`seq_lib.smc_cla_regmap`. The vendored
RTL is not a source for any value this sequence programs or compares against.

The other trace leaves fill the sink and stop there, so the sink's read side
stays idle: its read pointer stays at its reset, the buffer never reads
non-empty against the write pointer, and the RAM data port is not taken. This
sequence drives the other half of the same register
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
* The read pointer is also placed on every 8-byte word inside the window's
  first 64-byte set, not only on set boundaries.
* Before the sink is deactivated the trace runs until the sink's wrap flag
  reports one full pass of the window, so every position read out holds a
  word the trace wrote.
* ``Trdstrammode`` is programmed to both values of its one-bit field with the
  sink active, since the sink picks its destination from it.
* ``Trdstramactive`` is taken from 1 to 0 with the sink enabled, which is the
  deactivation edge the sink acts on.

A second leg then traces the CLA debug-bus mux in toggle mode
(``CDbgMuxSelLo.Dbmmode`` 3, ``Dbmid`` 0) into a window spanning the whole
16 KiB the eight trace RAMs hold (``hw/sys/smc/doc/dfd.adoc``), uncompressed:

* ``Trdstramrplow`` is read before and after each empty-buffer data read and
  both values are logged beside the documented behaviour, a read with no
  unread data leaving it in place; the bench is observed to advance it.
* The fill is a bounded poll of ``Trdstramwplow`` until the write pointer has
  been seen at or beyond the window's midpoint and, at a later sample, below
  the highest position seen, which is the pointer wrapping round the window.
  The wrap flag is sticky once an earlier leg has set it, so it is logged with
  every sample and never required. A poll that finds the register where the
  previous one left it drives the action field over its range again. The trace
  is then stopped by clearing the DST enable.
* Each of the eight 2 KiB segments is read out with 512 ``Trdstramdata`` reads
  from its start. A read that returns unread data advances the read pointer by
  one word, and from ``Trdstramlimitlow`` it wraps to ``Trdstramstartlow``, so
  every pointer sample has to equal the segment start plus one word per
  data-returning read, and once a read returns nothing the pointer stays put.
  How many reads return data and which bits the words carry are logged, not
  compared: the RAM address map, the unread-data accounting after a wrap and
  the toggle payload format are not documented.
* The read pointer is placed on the limit and one data read has to take it
  back to the window start.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

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
# Eight-byte steps inside the window's first 64-byte set. The positions above
# all start a set; these put the read pointer at every other 8-byte word of one.
_SET_OFFSETS = tuple(range(8, 64, 8))

_SETTLE_CYCLES = 32
# Action sweeps the fill may take to come round the window once.
_FILL_SWEEPS = 8

# dfd_cla.rdl Dbmmode: "3: Toggle Mode".
_DBM_MODE_TOGGLE = 3
# dfd.adoc: eight trace RAMs of 256 x 64 bits, 16 KiB in total.
_TRACE_RAMS = 8
_TOGGLE_WINDOW_BYTES = _TRACE_RAMS * 256 * 8
_SEGMENT_BYTES = _TOGGLE_WINDOW_BYTES // _TRACE_RAMS
_SEGMENT_READS = _SEGMENT_BYTES // 4
# Data reads of a segment after which the read pointer is sampled.
_RP_SAMPLES = tuple(range(1, 17)) + (_SEGMENT_READS,)
# Write-pointer polls the toggle fill may take to report one full pass.
_TOGGLE_FILL_POLLS = 8192

_TERMS = (
    "EXISTING_LEGS",
    "EMPTY_RP",
    "TOGGLE_SETUP",
    "FILL",
    "READOUT",
    "WRAP",
    "RESTORE",
)


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
        self.fill_last = 0
        self.value_checks = 0
        self.logical_op = -1
        self.empty_rp: list[tuple[int, int, int]] = []
        self.toggle_polls = 0
        self.toggle_reissues = 0
        self.toggle_wp_samples: list[int] = []
        self.toggle_peak = -1
        self.segment_words: list[int] = []
        # term -> [first access stamp (ps), last stamp (ps), accesses at start, at end]
        self._terms: dict[str, list[int]] = {}

    def _term_start(self, term: str) -> None:
        now = int(get_sim_time("ps"))
        self._terms[term] = [now, now, self.accesses, self.accesses]

    def _term_end(self, term: str) -> None:
        entry = self._terms[term]
        entry[1] = int(get_sim_time("ps"))
        entry[3] = self.accesses

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
            self.fill_last = await self._read(wp, f"fill{sweep}")
            if self.fill_last & wrap.mask:
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
        for offset in list(_READ_POSITIONS) + [_SINK_WINDOW_BYTES - 4] + list(_SET_OFFSETS):
            await self._seek(offset)
            word = await self._read(data, f"data{offset:x}")
            self.words_read += 1
            if word:
                self.nonzero_words += 1

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        self._term_start("EXISTING_LEGS")
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
        # The same empty buffer with the write and read pointers placed together on
        # each 8-byte word inside the first set: still nothing to read.
        wp = sink_register("Trdstramwplow")
        rp = sink_register("Trdstramrplow")
        self._term_start("EMPTY_RP")
        for offset in _SET_OFFSETS:
            await self._write(wp, field_word(wp, "Trdstramwplow", offset), f"empty_wp{offset:x}")
            await self._write(rp, field_word(rp, "Trdstramrplow", offset), f"empty_rp{offset:x}")
            rp_before = await self._read(rp, f"empty_rp{offset:x}_before")
            word = await self._read(data, f"empty{offset:x}")
            rp_after = await self._read(rp, f"empty_rp{offset:x}_after")
            assert word == 0, (
                f"DST_SINK Trdstramdata reads 0x{word:08x} with the write and read pointers both "
                f"at byte offset 0x{offset:x} and no trace captured; an empty sink RAM reads 0"
            )
            self.empty_rp.append((rp_before, rp_after, word))
            self.value_checks += 1
        await self._write(wp, 0, "empty_wp_restore")
        await self._write(rp, 0, "empty_rp_restore")
        self._term_end("EMPTY_RP")
        cocotb.log.info(
            "CHK-DST-SINK-BASELINE: the sink RAM data port reads 0x%08x at read pointer 0, "
            "and 0 with the write and read pointers together on each 8-byte word of the first "
            "set, with the sink armed and no trace yet captured, so the words the read-out below "
            "returns are the trace this run captured",
            self.baseline,
        )

        await self._write_check(
            dst_register("Trdstcontrol"),
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "dst",
        )
        logical_op = await self._arm_cla()
        self.logical_op = logical_op
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
            "its last word and every 8-byte word of its first set, each read back exactly (%d "
            "seeks in all with the baseline), and %d "
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

        self._term_end("EXISTING_LEGS")
        cocotb.log.info(
            "CHK-DST-TOGGLE-EMPTY-RP: %d empty reads, rp before/after/data per position %s; "
            "documented unchanged (LINKED-ISSUE SF-041)",
            len(self.empty_rp),
            " ".join(f"before=0x{b:x} after=0x{a:x} data=0x{d:x}" for b, a, d in self.empty_rp),
        )

        await self._toggle_leg()

        self._term_start("RESTORE")
        for reg in (
            cla_register("CDbgMuxSelLo"),
            sink_register("Trdstramstartlow"),
            sink_register("Trdstramlimitlow"),
            sink_register("Trdstramwplow"),
            sink_register("Trdstramrplow"),
            dst_register("Trdstcontrol"),
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgClaCtrlStatus"),
            funnel_register("Trfunnelcontrol"),
            sink_register("Trdstramcontrol"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            dfd_register("dfx_ctrl/DEBUG_CTRL"),
        ):
            await self._write(reg, reg.reset_word, "restore")
        self._term_end("RESTORE")
        self._fence()

    # -- toggle-mode leg ----------------------------------------------------

    async def _action_writes(self, label: str) -> None:
        """Drive Action0 over its range back to back, with the pair's relation kept."""
        eap = cla_register("CDbgNode0Eap0")
        action = cla_field(eap, "Action0")
        for value in range(1 << action.width):
            await self._write(
                eap,
                pack_fields(eap, {"LogicalOp": self.logical_op, "DestNode": 0, "Action0": value}),
                f"{label}{value}",
            )

    def _rp_expected(self, start: int, reads: int) -> int:
        """Read-pointer byte address after ``reads`` data-returning reads from ``start``."""
        return (start + 4 * reads) % _TOGGLE_WINDOW_BYTES

    async def _toggle_leg(self) -> None:
        mux = cla_register("CDbgMuxSelLo")
        dst = dst_register("Trdstcontrol")
        wp = sink_register("Trdstramwplow")
        rp = sink_register("Trdstramrplow")
        data = sink_register("Trdstramdata")
        wp_field = reg_field(wp, "Trdstramwplow")
        rp_field = reg_field(rp, "Trdstramrplow")
        wrap = reg_field(wp, "Trdstramwrap")
        limit = _TOGGLE_WINDOW_BYTES - 4

        # S3: toggle set-up.
        self._term_start("TOGGLE_SETUP")
        await self._write_check(mux, {"Dbmmode": _DBM_MODE_TOGGLE, "Dbmid": 0}, "toggle")
        control = sink_register("Trdstramcontrol")
        await self._write(control, control.reset_word, "toggle_off")
        for name, value in (
            ("Trdstramstartlow", 0),
            ("Trdstramstarthigh", 0),
            ("Trdstramlimitlow", limit),
            ("Trdstramlimithigh", 0),
            ("Trdstramwplow", 0),
            ("Trdstramrplow", 0),
        ):
            reg = sink_register(name)
            await self._write(reg, field_word(reg, name, value), "toggle")
        await self._write_check(
            control,
            {"Trdstramactive": 1, "Trdstramenable": 1, "Trdstrammode": 0},
            "toggle_sink",
        )
        armed = await self._read(wp, "toggle_armed")
        await self._write_check(
            dst,
            {"Trdstactive": 1, "Trdstenable": 1, "Trdstformat": _DST_FORMAT_NONE},
            "toggle_dst",
        )
        await self._action_writes("toggle_start")
        self._term_end("TOGGLE_SETUP")

        # S4: fill, a bounded poll on the write pointer until it has passed the
        # window's midpoint and later come back below the highest position seen.
        self._term_start("FILL")
        midpoint = _TOGGLE_WINDOW_BYTES // 2
        last = armed
        peak = -1
        wrapped_to = -1
        for poll in range(_TOGGLE_FILL_POLLS):
            word = await self._read(wp, f"toggle_poll{poll}")
            self.toggle_wp_samples.append(word)
            self.toggle_polls = poll + 1
            pointer = word & wp_field.mask
            if peak >= midpoint and pointer < peak:
                wrapped_to = pointer
                break
            peak = max(peak, pointer)
            if word == last:
                self.toggle_reissues += 1
                await self._action_writes(f"toggle_re{self.toggle_reissues}_")
            last = word
        self.toggle_peak = peak
        assert wrapped_to >= 0, (
            f"through {_TOGGLE_FILL_POLLS} polls of Trdstramwplow ({self.toggle_reissues} "
            f"action re-issues) the write pointer peaked at 0x{peak:x} and "
            f"{'never reached' if peak < midpoint else 'never came back below that after reaching'}"
            f" the midpoint 0x{midpoint:x}, last 0x{self.toggle_wp_samples[-1]:08x}, so the "
            f"toggle-mode trace never came round the 0x{_TOGGLE_WINDOW_BYTES:x}-byte window the "
            f"eight trace RAMs hold"
        )
        self.value_checks += 1
        await self._write_check(
            dst,
            {"Trdstactive": 1, "Trdstenable": 0, "Trdstformat": _DST_FORMAT_NONE},
            "toggle_stop",
        )
        stopped = await self._read(wp, "toggle_stopped")
        runs: list[list[int]] = []
        for w in self.toggle_wp_samples:
            if runs and runs[-1][0] == w:
                runs[-1][1] += 1
            else:
                runs.append([w, 1])
        cocotb.log.info(
            "CHK-DST-TOGGLE-FILL: Dbmmode=%d Dbmid=0 Trdstformat=%d read back; wp max=0x%x "
            "(>= 0x%x) then wrapped to 0x%x after %d polls (bound %d, %d action re-issues) over "
            "a 0x%x-byte window; wp after re-arm 0x%x flag=%d; wp/wrap-flag samples "
            "(pointer/flag/2KiB-segment, xN repeats) %s; wp after stop 0x%x flag=%d (flag "
            "logged, LINKED-ISSUE SF-042; RAM address map LINKED-ISSUE SF-022)",
            _DBM_MODE_TOGGLE,
            _DST_FORMAT_NONE,
            peak,
            midpoint,
            wrapped_to,
            self.toggle_polls,
            _TOGGLE_FILL_POLLS,
            self.toggle_reissues,
            _TOGGLE_WINDOW_BYTES,
            armed & wp_field.mask,
            armed & wrap.mask,
            ",".join(
                f"0x{w & wp_field.mask:x}/{w & wrap.mask}/"
                f"{(w & wp_field.mask) // _SEGMENT_BYTES}" + (f"x{n}" if n > 1 else "")
                for w, n in runs
            ),
            stopped & wp_field.mask,
            stopped & wrap.mask,
        )
        self._term_end("FILL")

        # S5: read every segment out.
        self._term_start("READOUT")
        sample_total = 0
        payload: list[str] = []
        for seg in range(_TRACE_RAMS):
            start = seg * _SEGMENT_BYTES
            await self._seek(start)
            returned = 0
            stalled = False
            words: list[int] = []
            prev = start
            for read in range(1, _SEGMENT_READS + 1):
                word = await self._read(data, f"seg{seg}_r{read}")
                words.append(word)
                if read not in _RP_SAMPLES:
                    continue
                got = (await self._read(rp, f"seg{seg}_rp{read}")) & rp_field.mask
                sample_total += 1
                if read <= 16:
                    if got == self._rp_expected(start, read):
                        assert not stalled, (
                            f"segment {seg}: Trdstramrplow reads 0x{got:x} after data read "
                            f"{read}, moving again after an earlier read left it in place at "
                            f"0x{prev:x}"
                        )
                        returned = read
                    else:
                        assert got == prev, (
                            f"segment {seg}: Trdstramrplow reads 0x{got:x} after data read "
                            f"{read}; one read moves it by one word to "
                            f"0x{self._rp_expected(start, read):x} or leaves it at 0x{prev:x}"
                        )
                        stalled = True
                else:
                    if stalled:
                        assert got == prev, (
                            f"segment {seg}: Trdstramrplow reads 0x{got:x} after data read "
                            f"{read}, having stopped at 0x{prev:x} by read 16"
                        )
                    else:
                        moved = [
                            n for n in range(16, read + 1) if self._rp_expected(start, n) == got
                        ]
                        assert moved, (
                            f"segment {seg}: Trdstramrplow reads 0x{got:x} after data read "
                            f"{read}, not the segment start 0x{start:x} plus a whole number of "
                            f"words between 16 and {read}"
                        )
                        returned = moved[0]
                prev = got
            assert returned >= 1, (
                f"segment {seg}: Trdstramrplow stayed at the segment start 0x{start:x} after "
                f"the first Trdstramdata read, so the segment returned no word after a full "
                f"pass of the window"
            )
            self.value_checks += len(_RP_SAMPLES) + 1
            self.segment_words.append(returned)
            got_words = words[:returned]
            distinct = len(set(got_words))
            ones = 0
            zeros = 0
            for w in got_words:
                ones |= w
                zeros |= ~w & 0xFFFFFFFF
            assert distinct > 1, (
                f"segment {seg}: all {returned} words read out of the toggle-mode capture are "
                f"0x{got_words[0]:08x}, one constant word"
            )
            self.value_checks += 1
            payload.append(
                f"seg{seg} words={returned} distinct={distinct} ones=0x{ones:08x} "
                f"zeros=0x{zeros:08x}"
            )
        muxed = await self._read(mux, "toggle_after")
        mode_field = cla_field(mux, "Dbmmode")
        id_field = cla_field(mux, "Dbmid")
        mux_mode = (muxed & mode_field.mask) >> mode_field.offset
        mux_id = (muxed & id_field.mask) >> id_field.offset
        assert (mux_mode, mux_id) == (_DBM_MODE_TOGGLE, 0), (
            f"CDbgMuxSelLo @ 0x{mux.addr:08x} reads 0x{muxed:x} after the read-out: Dbmmode "
            f"{mux_mode}, Dbmid {mux_id}, not the Dbmmode {_DBM_MODE_TOGGLE} / Dbmid 0 written"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-TOGGLE-RP-ADVANCE: segment 0..7 words returned=%s rp==start+n at %d "
            "samples (%d per segment, after reads %s), one word per data-returning read and "
            "no move after a read that returned none (count of data-returning reads "
            "LINKED-ISSUE SF-022)",
            ",".join(str(n) for n in self.segment_words),
            sample_total,
            len(_RP_SAMPLES),
            ",".join(str(n) for n in _RP_SAMPLES),
        )
        cocotb.log.info(
            "CHK-DST-TOGGLE-PAYLOAD: %s; every segment more than one distinct word; mux "
            "after=%d/%d (bit masks LINKED-ISSUE SF-020 SF-021 SF-022)",
            "; ".join(payload),
            mux_mode,
            mux_id,
        )
        self._term_end("READOUT")

        # S6: wrap from the limit to the start.
        self._term_start("WRAP")
        await self._seek(limit)
        at_limit = await self._read(data, "toggle_limit")
        wrapped = (await self._read(rp, "toggle_limit_rp")) & rp_field.mask
        assert wrapped == 0, (
            f"DST_SINK Trdstramrplow reads 0x{wrapped:x} after a Trdstramdata read with the "
            f"read pointer on Trdstramlimitlow 0x{limit:x}; from the limit it wraps to "
            f"Trdstramstartlow 0x0"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DST-TOGGLE-RP-WRAP: rp limit=0x%x -> 0x%x == start 0x0 (data 0x%08x)",
            limit,
            wrapped,
            at_limit,
        )
        self._term_end("WRAP")

    def _fence(self) -> None:
        missing = [t for t in _TERMS if t not in self._terms]
        assert not missing, f"fence terms never reached: {missing}"
        starts = [self._terms[t][0] for t in _TERMS]
        assert all(b > a for a, b in zip(starts, starts[1:])), (
            f"fence terms out of order: {dict(zip(_TERMS, starts))}"
        )
        for term in _TERMS:
            first, last, at_start, at_end = self._terms[term]
            assert at_end > at_start and last > first, (
                f"fence term {term} issued {at_end - at_start} accesses from {first} to {last} ps"
            )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 2 bounded waits, 0 expired: existing fill bound=%d action "
            "sweeps last=0x%08x after %d; toggle fill bound=%d Trdstramwplow polls last=0x%08x "
            "after %d (peak 0x%x); expiry raises AssertionError",
            _FILL_SWEEPS,
            self.fill_last,
            self.fill_sweeps,
            _TOGGLE_FILL_POLLS,
            self.toggle_wp_samples[-1],
            self.toggle_polls,
            self.toggle_peak,
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; %s",
            "<".join(_TERMS),
            " ".join(
                f"{t}=[{self._terms[t][0]}..{self._terms[t][1]}ps "
                f"{self._terms[t][3] - self._terms[t][2]} accesses]"
                for t in _TERMS
            ),
        )
