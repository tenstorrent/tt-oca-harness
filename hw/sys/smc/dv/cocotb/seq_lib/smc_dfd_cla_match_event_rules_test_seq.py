# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Grade the CLA match-event sense, the dead time match, the idle mux selects and the GPIO action.

Every address, field position, width, reset value and software-access type
comes from the generated register map through :mod:`seq_lib.smc_rdl_regmap`
and :mod:`seq_lib.smc_cla_regmap`. Values programmed into a field come from
that field's own RDL description or from the two bus states this sequence
measures, the way `smc_dfd_cla_live_bus_test_seq` measures them: the CLA mux in
normal mode, the DEBUG_BUS_MUX identifier that feeds it found by measurement,
and its identifier and normal modes read through the node 0 pair 0 snapshot as
states A and B. The vendored RTL is not a source for any value this sequence
programs or compares against.

Four sentences are graded, each on the measured states:

* `dfd_cla.rdl` `CDbgSignalMask<k>Lo` / `CDbgSignalMatch<k>Lo`: "The positive
  match event (0x2) fires when debug_bus & mask = match; the negative match
  event (0x3) fires when debug_bus & mask != match", and the same for the
  pairs 0x4 / 0x5, 0x1C / 0x1D and 0x1E / 0x1F. With the mask on the bits that
  differ and the match taken from state A, then from state B, node 0 pair 1
  selecting the positive code twice is walked over every relation value with
  the bus held in A and then in B; a relation under which the pair is set in
  the matching state and clear in the other is required, and under that
  relation the negative code is clear in the matching state and set in the
  other. The second match value proves the comparator reads the match
  register rather than its reset.
* `dfx_ctrl_status.rdl` `DEBUG_BUS_MUX.Muxselseg4` to `Muxselseg7` and
  `dfd_cla.rdl` `CDbgMuxSelLo.Muxselseg4` to `Muxselseg7`: "No effect in the
  SMC". Every value of each field on both registers leaves the snapshot in
  state B, while a value of `Muxselseg0` on each register moves it.
* `dfd.adoc` SMC CLA event types, Time match: "Unavailable in this
  integration. Its timestamp input is tied to zero. The comparator requires a
  nonzero match value, so the event cannot fire; it does not use the local CLA
  timestamp register." The set of `EventType0` indices seen live on node 0
  pair 1 is the same with `CDbgClaTimeMatch` at 0, at 1 and at all ones, while
  `CDbgClaTimestamp` reads past 1.
* `dfd.adoc` Actions and Cross-Triggering, GPIO toggle: "SMC terminates it on
  an unused local signal; it does not drive a pad." `tb_core2pad_o` and
  `tb_core2pad_en_o` are sampled on every clock, first over a baseline window
  with the pair live on action 0, then across every `Action0` value of node 0
  pair 0 fired under the activating relation; the bits that move during the
  sweep are a subset of the bits that move on their own during the baseline
  (the AVSBus clock pad among them), and the sweep raises `tb_cla_interrupt`.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

from .smc_cla_regmap import cla_field, cla_register
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dfd_trace_accumulator_fill_test_seq import (
    DBM_MODE_IDENTIFIER,
    DBM_MODE_NORMAL,
    checked_mask,
    cla_mux_normal,
    dfd_register,
    find_sampled_mux,
    pack_fields,
    reg_field,
    set_dbm,
    traced_bus,
)

CHK_NEGATE = "CHK-CLA-MATCH-NEGATE"
CHK_MUXSEL = "CHK-DFX-MUXSEL47-NO-EFFECT"
CHK_TIME = "CHK-CLA-TIME-MATCH-DEAD"
CHK_GPIO = "CHK-CLA-GPIO-ACTION-NO-PAD"

_SETTLE_CYCLES = 16
# dfd_cla.rdl: the (positive, negative) match-event codes of the four
# mask/match register pairs, in register order.
_MATCH_CODES = ((0x2, 0x3), (0x4, 0x5), (0x1C, 0x1D), (0x1E, 0x1F))
_STATE_A = "A"
_STATE_B = "B"
_IDLE_SELECTS = ("Muxselseg4", "Muxselseg5", "Muxselseg6", "Muxselseg7")
# dfd_cla.rdl CDbgClaTimeMatch: 0 stops the match event; the other two are the
# smallest nonzero value and the largest the field holds.
_TIME_MATCH_VALUES = (0, 1, (1 << 64) - 1)
_PADS = ("tb_core2pad_o", "tb_core2pad_en_o")
# Clock rises over which the pads are watched with no action changing, so a
# pad that moves on its own (a clock output) is told from one an action moves.
_PAD_BASELINE_CYCLES = 4096


class _PadSampler:
    """Per clk_smc_i rise, the bits of each pad vector that differ from its first sample."""

    def __init__(self) -> None:
        self.first: dict[str, int] = {}
        self.moved: dict[str, int] = {name: 0 for name in _PADS}
        self.samples = 0
        self.stop = False

    async def run(self) -> None:
        top = cocotb.top
        while not self.stop:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for name in _PADS:
                value = getattr(top, name).value
                assert value.is_resolvable, f"{name} is X/Z ({value})"
                word = int(value)
                self.first.setdefault(name, word)
                self.moved[name] |= word ^ self.first[name]
            self.samples += 1


class smc_dfd_cla_match_event_rules_test_seq(SmcCsrSeq):
    """Match-event sense, idle mux selects, the dead time match and the GPIO action."""

    def __init__(self, name: str = "smc_dfd_cla_match_event_rules_test_seq") -> None:
        super().__init__(name)
        self.sampled_mux = -1
        self.states: tuple[int, int] = (0, 0)
        self.logical_op = -1
        self.match_results: dict[tuple[int, str, int, int], tuple[int, int]] = {}
        self.match_relations: list[int] = []
        self.idle_samples = 0
        self.controls: dict[str, int] = {}
        self.live_sets: dict[int, list[int]] = {}
        self.timestamp_words: list[int] = []
        self.pad_samples = 0
        self.pads_baseline: dict[str, int] = {}
        self.pads_sweep: dict[str, int] = {}
        self.irq_values: list[int] = []
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

    async def _ctrl(self, label: str) -> None:
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
            label,
        )

    async def _settle(self) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, _SETTLE_CYCLES)

    async def _pair(self, eap: int, fields: dict[str, int], label: str) -> None:
        reg = cla_register(f"CDbgNode0Eap{eap}")
        await self._write(reg, pack_fields(reg, {**fields, "DestNode": 0}), label)

    async def _clear(self, eap: int, label: str) -> None:
        status = cla_register("CDbgEapStatus")
        w2c = cla_field(status, f"Node0Eap{eap}W2C")
        await self._write(status, w2c.mask, f"{label}_w2c")
        await self._write(status, 0, f"{label}_w2c0")

    async def _status(self, eap: int, label: str) -> int:
        status = cla_register("CDbgEapStatus")
        bit = cla_field(status, f"Node0Eap{eap}")
        return 1 if await self._read(status, label) & bit.mask else 0

    async def _activating_op(self) -> int:
        """A relation value measured to activate node 0 pair 0 on its reset events."""
        reg = cla_register("CDbgNode0Eap0")
        for value in range(1 << cla_field(reg, "LogicalOp").width):
            await self._pair(0, {"LogicalOp": value}, f"op{value}")
            await self._settle()
            if await self._status(0, f"op{value}"):
                self.value_checks += 1
                return value
        raise AssertionError(
            "no value of the LogicalOp field activated node 0 pair 0, so the snapshot cannot "
            "follow the bus and no action can be fired"
        )

    async def _bus(self, state: str, label: str) -> None:
        mode = DBM_MODE_IDENTIFIER if state == _STATE_A else DBM_MODE_NORMAL
        await set_dbm(self, {"Dbmmode": mode, "Dbmid": self.sampled_mux}, label)
        await self._settle()

    @staticmethod
    def _pin(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    # -- legs -------------------------------------------------------------

    async def _match_negate(self) -> None:
        first, second = self.states
        diff = first ^ second
        pair = cla_register("CDbgNode0Eap1")
        ops = range(1 << cla_field(pair, "LogicalOp").width)
        for index, (positive, negative) in enumerate(_MATCH_CODES):
            await self._write_check(cla_register(f"CDbgSignalMask{index}Lo"), {"Value": diff}, "m")
            for hit, other in ((_STATE_A, _STATE_B), (_STATE_B, _STATE_A)):
                match = (first if hit == _STATE_A else second) & diff
                await self._write_check(
                    cla_register(f"CDbgSignalMatch{index}Lo"), {"Value": match}, f"v{hit}"
                )
                for code in (positive, negative):
                    for op in ops:
                        seen = {}
                        for state in (_STATE_A, _STATE_B):
                            label = f"c{code:x}_m{hit}_op{op}_{state}"
                            await self._bus(state, label)
                            await self._pair(
                                1, {"LogicalOp": op, "EventType0": code, "EventType1": code}, label
                            )
                            await self._clear(1, label)
                            await self._settle()
                            seen[state] = await self._status(1, label)
                        self.match_results[(index, hit, code, op)] = (seen[hit], seen[other])
                        await self._pair(1, {}, f"c{code:x}_m{hit}_op{op}_quiet")
                        await self._clear(1, f"c{code:x}_m{hit}_op{op}_quiet")
                relation = next(
                    (op for op in ops if self.match_results[(index, hit, positive, op)] == (1, 0)),
                    None,
                )
                assert relation is not None, (
                    f"{CHK_NEGATE} FAIL: positive match code 0x{positive:x} with mask 0x{diff:x} "
                    f"and match 0x{match:x} (state {hit}) never set node 0 pair 1 in state {hit} "
                    f"while leaving it clear in state {other} under any relation value: "
                    f"{self._results_of(index, hit, positive)}"
                )
                observed = self.match_results[(index, hit, negative, relation)]
                assert observed == (0, 1), (
                    f"{CHK_NEGATE} FAIL: negative match code 0x{negative:x} with match 0x{match:x} "
                    f"(state {hit}) under relation {relation}, which set code 0x{positive:x} in "
                    f"{hit} and not in {other}, reads ({hit}, {other}) = {observed}, want (0, 1): "
                    f"{self._results_of(index, hit, negative)}"
                )
                self.match_relations.append(relation)
                self.value_checks += 2
        expected = len(_MATCH_CODES) * 2 * 2 * len(ops)
        assert len(self.match_results) == expected, (
            f"{len(self.match_results)} (pair, match state, code, relation) observations, want "
            f"{expected}"
        )
        cocotb.log.info(
            "%s: with mask 0x%x and the match taken from state A 0x%016x (0x%x) and then from "
            "state B 0x%016x (0x%x), each positive code of %s set node 0 pair 1 in the matching "
            "state and not in the other under relations %s, and under the same relation its "
            "negative code set the pair in the other state and not in the matching one; %d "
            "(pair, match state, code, relation) observations, each a status read in both states",
            CHK_NEGATE,
            diff,
            first,
            first & diff,
            second,
            second & diff,
            [f"0x{p:x}/0x{n:x}" for p, n in _MATCH_CODES],
            self.match_relations,
            len(self.match_results),
        )

    def _results_of(self, index: int, hit: str, code: int) -> dict[int, tuple[int, int]]:
        return {
            op: ab
            for (i, h, c, op), ab in self.match_results.items()
            if (i, h, c) == (index, hit, code)
        }

    async def _idle_selects(self) -> None:
        second = self.states[1]
        dbm = dfd_register("dfx_ctrl/DEBUG_BUS_MUX")
        cla_mux = cla_register("CDbgMuxSelLo")
        await self._bus(_STATE_B, "idle_base")
        base = await traced_bus(self, "idle_base")
        assert base == second, (
            f"the snapshot reads 0x{base:016x} with the sampled mux in normal mode, not the "
            f"measured state B 0x{second:016x}"
        )
        for reg, write, control_range in (
            (dbm, self._write_dbm, range(1, 5)),
            (cla_mux, self._write_cla_mux, range(1, 13)),
        ):
            for name in _IDLE_SELECTS:
                field = reg_field(reg, name)
                for value in range(1 << field.width):
                    await write({name: value}, f"{name}_{value}")
                    snapshot = await traced_bus(self, f"{self._short(reg)}_{name}_{value}")
                    self.idle_samples += 1
                    assert snapshot == second, (
                        f"{CHK_MUXSEL} FAIL: {reg.path}.{name} = {value} moved the node 0 pair "
                        f"0 snapshot to 0x{snapshot:016x} from state B 0x{second:016x}"
                    )
                await write({name: 0}, f"{name}_restore")
            moved = None
            for value in control_range:
                await write({"Muxselseg0": value}, f"control_{value}")
                snapshot = await traced_bus(self, f"{self._short(reg)}_control_{value}")
                if snapshot != second:
                    moved = value
                    break
            assert moved is not None, (
                f"{CHK_MUXSEL} FAIL: no value of {reg.path}.Muxselseg0 in "
                f"{list(control_range)} moved the snapshot from 0x{second:016x}, so the "
                f"snapshot does not follow this register's lane selects"
            )
            self.controls[self._short(reg)] = moved
            await write({"Muxselseg0": 0}, "control_restore")
            restored = await traced_bus(self, f"{self._short(reg)}_control_restore")
            assert restored == second, (
                f"{reg.path}.Muxselseg0 back at 0 leaves the snapshot at 0x{restored:016x}, "
                f"not state B 0x{second:016x}"
            )
            self.value_checks += 2
        cocotb.log.info(
            "%s: with the bus in state B 0x%016x, every one of the %d values of Muxselseg4 to "
            "Muxselseg7 on DEBUG_BUS_MUX and on CDbgMuxSelLo left the node 0 pair 0 snapshot at "
            "that state, %d samples; Muxselseg0 moved it at %s on each register and 0 brought "
            "it back",
            CHK_MUXSEL,
            second,
            1 << reg_field(dbm, _IDLE_SELECTS[0]).width,
            self.idle_samples,
            self.controls,
        )

    async def _write_dbm(self, selects: dict[str, int], label: str) -> None:
        await set_dbm(
            self, {"Dbmmode": DBM_MODE_NORMAL, "Dbmid": self.sampled_mux, **selects}, label
        )
        await self._settle()

    async def _write_cla_mux(self, selects: dict[str, int], label: str) -> None:
        reg = cla_register("CDbgMuxSelLo")
        await self._write(
            reg, pack_fields(reg, {"Dbmmode": DBM_MODE_NORMAL, "Dbmid": 0, **selects}), label
        )
        await self._settle()

    async def _watch_pads(self, cycles: int, label: str) -> _PadSampler:
        sampler = _PadSampler()
        task = cocotb.start_soon(sampler.run())
        await ClockCycles(cocotb.top.clk_smc_i, cycles)
        sampler.stop = True
        await task
        assert sampler.samples >= cycles, f"{label}: {sampler.samples} pad samples, want {cycles}"
        return sampler

    @staticmethod
    def _bits(word: int) -> list[int]:
        return [i for i in range(word.bit_length()) if word >> i & 1]

    async def _gpio_action(self) -> None:
        eap = cla_register("CDbgNode0Eap0")
        span = 1 << cla_field(eap, "Action0").width
        await self._pair(0, {"LogicalOp": self.logical_op}, "gpio_base")
        baseline = await self._watch_pads(_PAD_BASELINE_CYCLES, "baseline")
        self.pads_baseline = dict(baseline.moved)

        sampler = _PadSampler()
        task = cocotb.start_soon(sampler.run())
        for value in range(span):
            await self._pair(0, {"LogicalOp": self.logical_op, "Action0": value}, f"gpio{value}")
            await self._settle()
            self.irq_values.append(self._pin("tb_cla_interrupt"))
        await self._pair(0, {"LogicalOp": self.logical_op}, "gpio_quiet")
        await self._settle()
        sampler.stop = True
        await task
        self.pads_sweep = dict(sampler.moved)
        self.pad_samples = sampler.samples
        for name in _PADS:
            driven = self.pads_sweep[name] & ~self.pads_baseline[name]
            assert driven == 0, (
                f"{CHK_GPIO} FAIL: {name} bits {self._bits(driven)} moved across the {span} "
                f"Action0 values on activating LogicalOp {self.logical_op} and not during the "
                f"{_PAD_BASELINE_CYCLES}-cycle baseline (baseline-moving bits "
                f"{self._bits(self.pads_baseline[name])}, sweep-moving bits "
                f"{self._bits(self.pads_sweep[name])})"
            )
        assert any(self.irq_values), (
            f"{CHK_GPIO} FAIL: tb_cla_interrupt never read 1 across the {span} Action0 values "
            f"on LogicalOp {self.logical_op}, so the sweep fired no action"
        )
        assert self.pad_samples >= span * _SETTLE_CYCLES, (
            f"{self.pad_samples} pad samples across the sweep, want at least {span * _SETTLE_CYCLES}"
        )
        self.value_checks += 3
        cocotb.log.info(
            "%s: across all %d Action0 values of node 0 pair 0 on activating LogicalOp %d, "
            "sampled on %d clock rises, the only tb_core2pad_o bits that moved were %s and the "
            "only tb_core2pad_en_o bits %s, each already moving on its own over the %d-cycle "
            "baseline (tb_core2pad_o %s, tb_core2pad_en_o %s); tb_cla_interrupt rose at "
            "Action0 = %d",
            CHK_GPIO,
            span,
            self.logical_op,
            self.pad_samples,
            self._bits(self.pads_sweep["tb_core2pad_o"]),
            self._bits(self.pads_sweep["tb_core2pad_en_o"]),
            _PAD_BASELINE_CYCLES,
            self._bits(self.pads_baseline["tb_core2pad_o"]),
            self._bits(self.pads_baseline["tb_core2pad_en_o"]),
            self.irq_values.index(1),
        )

    async def _time_match(self) -> None:
        pair = cla_register("CDbgNode0Eap1")
        selector = cla_field(pair, "EventType0")
        time_match = cla_register("CDbgClaTimeMatch")
        timestamp = cla_register("CDbgClaTimestamp")
        await self._bus(_STATE_B, "time_base")
        for value in _TIME_MATCH_VALUES:
            await self._write_check(time_match, {"TimeMatchVal": value}, f"tmv{value:x}")
            live: list[int] = []
            for index in range(1 << selector.width):
                label = f"tmv{value:x}_ev{index}"
                await self._pair(1, {"EventType0": index}, label)
                await self._clear(1, label)
                await self._settle()
                if await self._status(1, label):
                    live.append(index)
                await self._pair(1, {}, f"{label}_quiet")
                await self._clear(1, f"{label}_quiet")
            self.live_sets[value] = live
            self.timestamp_words.append(await self._read(timestamp, f"tmv{value:x}_ts"))
        await self._write_check(time_match, {"TimeMatchVal": 0}, "tmv_off")
        sets = list(self.live_sets.values())
        assert sets[0] and len(sets[0]) < 1 << selector.width, (
            f"{CHK_TIME} FAIL: EventType0 on node 0 pair 1 read live on {sets[0]} with "
            f"CDbgClaTimeMatch 0; the sweep needs at least one live and one idle index"
        )
        assert all(s == sets[0] for s in sets), (
            f"{CHK_TIME} FAIL: the live EventType0 indices differ across CDbgClaTimeMatch "
            f"values: {self._live_by_value()} with CDbgClaTimestamp at "
            f"{[hex(w) for w in self.timestamp_words]}"
        )
        assert all(word > 1 for word in self.timestamp_words), (
            f"{CHK_TIME} FAIL: CDbgClaTimestamp read {[hex(w) for w in self.timestamp_words]}, "
            f"not past the match value 1"
        )
        self.value_checks += 3
        cocotb.log.info(
            "%s: the live EventType0 indices of node 0 pair 1 were %s with CDbgClaTimeMatch at "
            "0, 1 and 0x%x alike, each sweep of %d indices with the bus held in state B, while "
            "CDbgClaTimestamp read %s, past every value a timestamp could match at",
            CHK_TIME,
            sets[0],
            _TIME_MATCH_VALUES[-1],
            1 << selector.width,
            [hex(w) for w in self.timestamp_words],
        )

    def _live_by_value(self) -> dict[str, list[int]]:
        return {hex(value): live for value, live in self.live_sets.items()}

    # -- body -------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        await self._write(clk, pack_fields(clk, {"force_clk_en": 1}), "force")
        await self._ctrl("arm")
        self.logical_op = await self._activating_op()
        await cla_mux_normal(self, "clamux")
        self.sampled_mux, first, second = await find_sampled_mux(self, _SETTLE_CYCLES, "live")
        self.states = (first, second)

        await self._match_negate()
        await self._idle_selects()
        await self._gpio_action()
        await self._time_match()

        for reg in (
            cla_register("CDbgNode0Eap0"),
            cla_register("CDbgNode0Eap1"),
            *(cla_register(f"CDbgSignalMask{i}Lo") for i in range(len(_MATCH_CODES))),
            *(cla_register(f"CDbgSignalMatch{i}Lo") for i in range(len(_MATCH_CODES))),
            cla_register("CDbgClaCtrlStatus"),
            cla_register("CDbgMuxSelLo"),
            dfd_register("dfx_ctrl/DEBUG_BUS_MUX"),
            clk,
        ):
            await self._write(reg, reg.reset_word, "restore")
