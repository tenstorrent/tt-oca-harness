# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OCTS pulse timing on pads 55 and 56, the role masks and the TIMER_GPIO_ENABLE pad effect.

Statements graded, from `hw/ip/system_timer_octs/doc/interface.adoc` (OCTS Synchronization
Interface), `architecture.adoc` (OCTS credit management; Pulse Generation and Clock
Crossing) and `regs/system_timer_octs.rdl` (TIMER_GPIO_ENABLE):

* a PRIMARY asserts `timer_sync_load_o` for `CTRL.PULSE_WIDTH` cycles when START is written
  and `timer_cnt_credit_o` for `CTRL.PULSE_WIDTH` cycles every `CTRL.CREDIT_VAL` cycles; a
  `PULSE_WIDTH` of zero is treated as one;
* START clears the primary's interval counter;
* the pulse FSM accepts triggers only while idle and does not queue them: START reloads the
  count while an active pulse prevents a new load pulse;
* any synchronization input is ignored in PRIMARY mode; in SECONDARY mode the outputs remain
  inactive;
* `TIMER_GPIO_ENABLE.GPIO_ENABLE` enables the GPIO pad LSIO interface for the timer, which
  `smc_padring` places on pads 55 (sync load) and 56 (credit): driven on a primary, sampled on
  a secondary.

The bench samples `tb_octs_sync_load_from_dut` (pad 55 data), `tb_octs_cnt_credit_from_dut`
(pad 56 data), the timer's own pulse ports on either side of the padring
(`tb_octs_core_*_out`, `tb_octs_core_*_in`) and the live count `tb_octs_timer_count` on every
`clk_smc_i` rise, the clock the timer counts on, so a pulse width, a credit spacing and a
count step are cycle counts of that trace. The role masks are graded where each sentence
places them: a SECONDARY's outputs at the timer ports and at the pads; a PRIMARY's inputs by
the count, with the pulses that reached the timer's input ports reported, since the padring
disables the pad receivers of a PRIMARY before the timer masks a synchronized edge. A START's landing cycle is read from the trace as the cycle the count reloads to
the preset, so no leg depends on the latency of the AXI write that carries it.

The SECONDARY phase runs first: switching a chiplet to SECONDARY with a live count would
leave the count ahead of the expected count the sync pulse sets.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, with_timeout

from .smc_addr_map import gpio_intf_u32, reg_field_encode, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_octs_dual_sync_test_seq import (
    _OCTS_COUNT_HI,
    _OCTS_COUNT_LO,
    _OCTS_CTRL,
    _OCTS_GPIO_ENABLE,
    _OCTS_H,
    _OCTS_PRESET_HI,
    _OCTS_PRESET_LO,
    _OCTS_START,
    _OCTS_STATUS,
    _OCTS_STATUS_MODE,
    _OCTS_STATUS_RUNNING,
    _OCTS_TIMER_GPIO_ENABLE,
    _OCTS_TIMER_START,
)
from .smc_octs_sync_bfm import drive_secondary_sync_then_credits, pulse_high
from .smc_pad_table import pad_index

SYNC_PAD = pad_index("System Timer Sync Load")
CREDIT_PAD = pad_index("System Timer Credit Count")
SYNC_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_BASE_ADDR", SYNC_PAD)
CREDIT_DATA_CTRL = smc_indexed_addr(
    "SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_BASE_ADDR", CREDIT_PAD
)
#: DATA_CTRL word that makes the register path own a pad as an output driving 1.
REG_DRIVES_ONE = (
    gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
    | (1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp"))
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
)
#: The preset every START reloads; the count runs well past it between starts, so a reload
#: is the one cycle the trace drops.
PRESET = 0x100
SHORT_CREDIT = 0x10
LONG_CREDIT = 0xFF
#: (CREDIT_VAL, PULSE_WIDTH, high run the document gives) graded on both pads.
PULSE_SETTINGS = (
    (SHORT_CREDIT, 2, 2),
    (SHORT_CREDIT, 7, 7),
    (SHORT_CREDIT, 0, 1),
    (LONG_CREDIT, 2, 2),
)
#: The pulse that covers most of a LONG_CREDIT interval, so a START written on a credit rise
#: lands inside it.
WIDE_PULSE = 0xF0
INJECT_PULSES = 3
INJECT_WIDTH = 4
INJECT_GAP = 20
#: Rises a bounded trace wait may take: a reload after a completed START write, a credit rise
#: after a START, a pad level after a DATA_CTRL write.
TRACE_BOUND = 2 * LONG_CREDIT + 32
START_ATTEMPTS = 4
#: Cycles the SECONDARY outputs are watched for after the inject, in credit intervals.
QUIET_INTERVALS = 4


def _ctrl(credit: int, pulse: int) -> int:
    return reg_field_encode(
        _OCTS_H, "SYSTEM_TIMER_OCTS", "CTRL", credit_val=credit, pulse_width=pulse, step=1
    )


class _OctsTrace:
    """Per-`clk_smc_i` samples of pad 55, pad 56, the timer's pulse ports and the live count."""

    PORTS = (
        "tb_octs_core_sync_load_out",
        "tb_octs_core_credit_out",
        "tb_octs_core_sync_load_in",
        "tb_octs_core_credit_in",
    )

    def __init__(self, dut) -> None:
        self.dut = dut
        self.sync: list[int] = []
        self.credit: list[int] = []
        self.count: list[int] = []
        self.ports: dict[str, list[int]] = {name: [] for name in self.PORTS}
        self.stop = False

    @property
    def cycle(self) -> int:
        return len(self.sync)

    async def run(self) -> None:
        clk = self.dut.clk_smc_i
        while not self.stop:
            await RisingEdge(clk)
            await ReadOnly()
            samples = []
            for name in ("tb_octs_sync_load_from_dut", "tb_octs_cnt_credit_from_dut"):
                value = getattr(self.dut, name).value
                assert value.is_resolvable, f"{name} unresolvable at trace cycle {self.cycle}"
                samples.append(int(value))
            count = self.dut.tb_octs_timer_count.value
            assert count.is_resolvable, f"tb_octs_timer_count unresolvable at {self.cycle}"
            self.sync.append(samples[0])
            self.credit.append(samples[1])
            self.count.append(int(count))
            for name in self.PORTS:
                value = getattr(self.dut, name).value
                assert value.is_resolvable, f"{name} unresolvable at trace cycle {self.cycle}"
                self.ports[name].append(int(value))

    def port_high(self, name: str, lo: int, hi: int) -> int:
        """Samples of timer port `name` at 1 in [lo, hi)."""
        return sum(self.ports[name][lo:hi])

    @staticmethod
    def rises(samples: list[int], lo: int, hi: int) -> list[int]:
        """Cycles in (lo, hi] at which `samples` goes 0 -> 1."""
        return [i for i in range(lo + 1, hi + 1) if samples[i] and not samples[i - 1]]

    @staticmethod
    def runs(samples: list[int], lo: int, hi: int) -> list[tuple[int, int]]:
        """(start, length) of every high run that starts after lo and ends at or before hi."""
        out = []
        start = None
        for i in range(lo + 1, hi + 1):
            if samples[i] and not samples[i - 1]:
                start = i
            elif not samples[i] and start is not None:
                out.append((start, i - start))
                start = None
        return out

    def reload_after(self, mark: int) -> int | None:
        """The first cycle after `mark` at which the count drops."""
        for i in range(mark + 1, self.cycle):
            if self.count[i] < self.count[i - 1]:
                return i
        return None


class smc_octs_pulse_timing_test_seq(SmcCsrSeq):
    """Grade the OCTS pulse widths, credit spacing, START rules, role masks and pad enable."""

    def __init__(self, name: str = "smc_octs_pulse_timing_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self.waits: list[str] = []
        self.dropped_starts = 0
        self.sync_runs_per_start = 0

    def _chk(self, token: str, text: str) -> None:
        cocotb.log.info("%s: %s", token, text)
        self.chk_seen.add(token)

    # ---- bench samples ---------------------------------------------------------------------

    @staticmethod
    def _bit(name: str, pad: int) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} unresolvable"
        return (int(value) >> pad) & 1

    def _pad_state(self) -> dict[str, int]:
        return {
            f"{n}[{p}]": self._bit(n, p)
            for n in ("tb_lsio_interface_select", "tb_core2pad_en_o", "tb_pad2core_en_o")
            for p in (SYNC_PAD, CREDIT_PAD)
        }

    async def _await_pad(self, label: str, name: str, pad: int, want: int) -> int:
        """Poll `name[pad]` every rise until it reads `want`; expiry fails."""
        clk = cocotb.top.clk_smc_i
        last = None
        for cycle in range(1, TRACE_BOUND + 1):
            await RisingEdge(clk)
            await ReadOnly()
            last = self._bit(name, pad)
            if last == want:
                self.waits.append(f"{label}: {name}[{pad}]=={want} after {cycle} rises")
                await RisingEdge(clk)
                return cycle
        raise AssertionError(
            f"{label}: {name}[{pad}] read {last}, not {want}, within {TRACE_BOUND} clk_smc_i"
        )

    async def _await_trace(self, label: str, trace: _OctsTrace, found) -> int:
        """Advance the trace until `found(trace)` returns a cycle; expiry fails."""
        clk = cocotb.top.clk_smc_i
        for cycle in range(1, TRACE_BOUND + 1):
            await RisingEdge(clk)
            hit = found(trace)
            if hit is not None:
                self.waits.append(f"{label}: trace cycle {hit} after {cycle} rises")
                return hit
        raise AssertionError(f"{label}: not seen within {TRACE_BOUND} clk_smc_i")

    async def _read_count(self, label: str) -> int:
        lo = await self.csr_read(f"{label}_LO", _OCTS_COUNT_LO)
        hi = await self.csr_read(f"{label}_HI", _OCTS_COUNT_HI)
        return (hi << 32) | lo

    async def _start(self, label: str, trace: _OctsTrace) -> int:
        """Write START and return the trace cycle at which the count reloaded."""
        mark = trace.cycle
        await self.csr_write(label, _OCTS_TIMER_START, _OCTS_START)
        reload = await self._await_trace(f"{label} reload", trace, lambda t: t.reload_after(mark))
        assert trace.count[reload] == PRESET, (
            f"{label}: the count reloaded to 0x{trace.count[reload]:x} at trace cycle {reload}, "
            f"not to the preset 0x{PRESET:x}"
        )
        return reload

    async def _start_outside_credit_pulse(self, label: str, trace: _OctsTrace) -> int:
        """Write START until one lands while no credit pulse is out; returns its reload cycle.

        A START written during a credit pulse reloads the count and emits no load pulse, the
        rule `_pulse_no_queue` grades; a width leg needs the other case.
        """
        for attempt in range(START_ATTEMPTS):
            reload = await self._start(f"{label}_{attempt}", trace)
            if not trace.credit[reload - 1]:
                return reload
            self.dropped_starts += 1
        raise AssertionError(
            f"{label}: every one of {START_ATTEMPTS} STARTs landed in a credit pulse"
        )

    # ---- legs --------------------------------------------------------------------------------

    async def _entry(self) -> None:
        status = await self.csr_read("STATUS_ENTRY", _OCTS_STATUS)
        assert not status & (_OCTS_STATUS_MODE | _OCTS_STATUS_RUNNING), (
            f"STATUS=0x{status:08x} at entry; the strap is PRIMARY and nothing started the timer"
        )
        gpio_enable = await self.csr_read("GPIO_ENABLE_ENTRY", _OCTS_TIMER_GPIO_ENABLE)
        assert not gpio_enable & _OCTS_GPIO_ENABLE, f"TIMER_GPIO_ENABLE=0x{gpio_enable:x} at entry"
        state = self._pad_state()
        assert all(state[f"tb_lsio_interface_select[{p}]"] == 0 for p in (SYNC_PAD, CREDIT_PAD)), (
            f"pads {SYNC_PAD}/{CREDIT_PAD} LSIO-selected with TIMER_GPIO_ENABLE clear: {state}"
        )
        await self.csr_write("CTRL_ENTRY", _OCTS_CTRL, _ctrl(SHORT_CREDIT, 2))
        await self.csr_write("PRESET_LO", _OCTS_PRESET_LO, PRESET)
        await self.csr_write("PRESET_HI", _OCTS_PRESET_HI, 0)

    async def _secondary_phase(self, trace: _OctsTrace) -> dict[str, int]:
        """SECONDARY strap with the pads enabled: direction, inject, then quiet outputs."""
        dut = cocotb.top
        clk = dut.clk_smc_i
        await self.csr_write("GPIO_ENABLE_SET", _OCTS_TIMER_GPIO_ENABLE, _OCTS_GPIO_ENABLE)
        await self.csr_read(
            "GPIO_ENABLE_SET_RB", _OCTS_TIMER_GPIO_ENABLE, expected=_OCTS_GPIO_ENABLE
        )
        dut.tb_chiplet_is_primary.value = 0
        dut.tb_octs_sync_load_ext.value = 0
        dut.tb_octs_cnt_credit_ext.value = 0
        status = await self.csr_read("STATUS_SECONDARY", _OCTS_STATUS)
        assert status & _OCTS_STATUS_MODE, f"STATUS=0x{status:08x} under the SECONDARY strap"
        await self._await_pad("SEC_IE", "tb_pad2core_en_o", SYNC_PAD, 1)
        secondary = self._pad_state()
        assert all(
            secondary[f"tb_lsio_interface_select[{p}]"] == 1 for p in (SYNC_PAD, CREDIT_PAD)
        ), f"TIMER_GPIO_ENABLE=1 did not select pads {SYNC_PAD}/{CREDIT_PAD}: {secondary}"
        assert all(
            secondary[f"tb_core2pad_en_o[{p}]"] == 0 and secondary[f"tb_pad2core_en_o[{p}]"] == 1
            for p in (SYNC_PAD, CREDIT_PAD)
        ), f"SECONDARY pads are not inputs: {secondary}"

        mark = trace.cycle
        await drive_secondary_sync_then_credits(
            dut, clk, pulse_width=INJECT_WIDTH, num_credits=2, credit_gap_cycles=SHORT_CREDIT + 4
        )
        count = await self._read_count("COUNT_SECONDARY")
        status = await self.csr_read("STATUS_SECONDARY_RUN", _OCTS_STATUS)
        assert status & _OCTS_STATUS_RUNNING, (
            f"STATUS=0x{status:08x}: the injected sync did not start the SECONDARY"
        )
        lo, hi = PRESET + SHORT_CREDIT, PRESET + 2 * SHORT_CREDIT + 16
        assert lo <= count <= hi, (
            f"SECONDARY COUNT 0x{count:x} after a sync and 2 credits, expected [0x{lo:x}, 0x{hi:x}]"
        )
        await ClockCycles(clk, QUIET_INTERVALS * SHORT_CREDIT)
        end = trace.cycle
        high = sum(trace.sync[mark:end]) + sum(trace.credit[mark:end])
        rises = len(trace.rises(trace.sync, mark, end - 1)) + len(
            trace.rises(trace.credit, mark, end - 1)
        )
        quiet = self._pad_state()
        core_high = trace.port_high("tb_octs_core_sync_load_out", mark, end) + trace.port_high(
            "tb_octs_core_credit_out", mark, end
        )
        assert high == 0 and rises == 0 and core_high == 0, (
            f"SECONDARY running (COUNT 0x{count:x}) drove pad {SYNC_PAD}/{CREDIT_PAD} data high on "
            f"{high} samples with {rises} rises and its own pulse outputs high on {core_high} "
            f"samples over {end - mark} clk_smc_i; the outputs remain inactive in SECONDARY mode"
        )
        assert all(quiet[f"tb_core2pad_en_o[{p}]"] == 0 for p in (SYNC_PAD, CREDIT_PAD)), (
            f"SECONDARY output enable set after the inject: {quiet}"
        )
        self._chk(
            "CHK-OCTS-SECONDARY-OUTPUTS-QUIET",
            f"SECONDARY strap, sync then 2 credits injected on pads {SYNC_PAD}/{CREDIT_PAD}: "
            f"RUNNING=1, COUNT=0x{count:x} in [0x{lo:x}, 0x{hi:x}]; over the {end - mark} clk_smc_i "
            f"from the inject to {QUIET_INTERVALS} x CREDIT_VAL 0x{SHORT_CREDIT:x} past it, the "
            f"timer's sync_load/credit outputs high on {core_high} samples and pad data high on "
            f"{high} samples, {rises} rises; core2pad_en[{SYNC_PAD}]="
            f"{quiet[f'tb_core2pad_en_o[{SYNC_PAD}]']} core2pad_en[{CREDIT_PAD}]="
            f"{quiet[f'tb_core2pad_en_o[{CREDIT_PAD}]']}",
        )
        return secondary

    async def _gpio_enable_pads(self, trace: _OctsTrace, secondary: dict[str, int]) -> None:
        """PRIMARY strap: GPIO_ENABLE 0 leaves the pads to the registers, 1 to the timer."""
        dut = cocotb.top
        clk = dut.clk_smc_i
        dut.tb_chiplet_is_primary.value = 1
        status = await self.csr_read("STATUS_PRIMARY", _OCTS_STATUS)
        assert not status & _OCTS_STATUS_MODE, f"STATUS=0x{status:08x} under the PRIMARY strap"
        await self.csr_write("GPIO_ENABLE_CLR", _OCTS_TIMER_GPIO_ENABLE, 0)
        await self.csr_read("GPIO_ENABLE_CLR_RB", _OCTS_TIMER_GPIO_ENABLE, expected=0)
        await self._await_pad("CLR_SEL", "tb_lsio_interface_select", SYNC_PAD, 0)
        released = self._pad_state()
        assert all(
            released[f"tb_lsio_interface_select[{p}]"] == 0 for p in (SYNC_PAD, CREDIT_PAD)
        ), f"pads still LSIO-selected with TIMER_GPIO_ENABLE clear: {released}"
        await self.csr_write("SYNC_PAD_REG", SYNC_DATA_CTRL, REG_DRIVES_ONE)
        await self.csr_write("CREDIT_PAD_REG", CREDIT_DATA_CTRL, REG_DRIVES_ONE)
        await self._await_pad("REG_OE", "tb_core2pad_en_o", CREDIT_PAD, 1)
        owned = self._pad_state()
        assert all(owned[f"tb_core2pad_en_o[{p}]"] == 1 for p in (SYNC_PAD, CREDIT_PAD)), (
            f"DATA_CTRL did not take pads {SYNC_PAD}/{CREDIT_PAD} with the select clear: {owned}"
        )
        reload = await self._start("START_PADS_OFF", trace)
        status = await self.csr_read("STATUS_PADS_OFF", _OCTS_STATUS)
        assert status & _OCTS_STATUS_RUNNING, f"STATUS=0x{status:08x} after START"
        await ClockCycles(clk, 2 * SHORT_CREDIT)
        end = trace.cycle
        low = (end - reload) * 2 - sum(trace.sync[reload:end]) - sum(trace.credit[reload:end])
        off_rises = len(trace.rises(trace.sync, reload - 1, end - 1)) + len(
            trace.rises(trace.credit, reload - 1, end - 1)
        )
        assert low == 0 and off_rises == 0, (
            f"with TIMER_GPIO_ENABLE clear the timer reached pads {SYNC_PAD}/{CREDIT_PAD}: data "
            f"low on {low} samples, {off_rises} rises over {end - reload} clk_smc_i after the "
            f"START at trace cycle {reload}, although DATA_CTRL holds both pads at 1"
        )

        await self.csr_write("GPIO_ENABLE_SET2", _OCTS_TIMER_GPIO_ENABLE, _OCTS_GPIO_ENABLE)
        await self.csr_read(
            "GPIO_ENABLE_SET2_RB", _OCTS_TIMER_GPIO_ENABLE, expected=_OCTS_GPIO_ENABLE
        )
        await self._await_pad("TIMER_DATA", "tb_octs_sync_load_from_dut", 0, 0)
        primary = self._pad_state()
        assert all(
            primary[f"tb_lsio_interface_select[{p}]"] == 1
            and primary[f"tb_core2pad_en_o[{p}]"] == 1
            and primary[f"tb_pad2core_en_o[{p}]"] == 0
            for p in (SYNC_PAD, CREDIT_PAD)
        ), f"PRIMARY pads with TIMER_GPIO_ENABLE set are not timer outputs: {primary}"
        mark = trace.cycle
        await ClockCycles(clk, 2 * SHORT_CREDIT + 4)
        end = trace.cycle
        credit_rises = trace.rises(trace.credit, mark, end - 1)
        sync_high = sum(trace.sync[mark:end])
        assert len(credit_rises) >= 2 and sync_high == 0, (
            f"with TIMER_GPIO_ENABLE set pad {CREDIT_PAD} showed {len(credit_rises)} credit rises "
            f"(need >= 2) and pad {SYNC_PAD} was high on {sync_high} samples with no START, over "
            f"{end - mark} clk_smc_i, although DATA_CTRL holds both pads at 1"
        )
        await self.csr_write("SYNC_PAD_RESTORE", SYNC_DATA_CTRL, 0)
        await self.csr_write("CREDIT_PAD_RESTORE", CREDIT_DATA_CTRL, 0)
        self._chk(
            "CHK-OCTS-GPIO-ENABLE-PADS",
            f"GPIO_ENABLE=1 SECONDARY: select[{SYNC_PAD}:{CREDIT_PAD}]=1, core2pad_en=0/0, "
            f"pad2core_en=1/1; GPIO_ENABLE=0 PRIMARY: select=0/0, DATA_CTRL=0x{REG_DRIVES_ONE:x} "
            f"took both pads (core2pad_en=1/1) and a START at trace cycle {reload} left them at 1 "
            f"({low} low samples, {off_rises} rises over {2 * SHORT_CREDIT} clk_smc_i); "
            f"GPIO_ENABLE=1 PRIMARY: select=1/1, core2pad_en=1/1, pad2core_en=0/0, pad "
            f"{CREDIT_PAD} carried {len(credit_rises)} credit rises and pad {SYNC_PAD} stayed 0 "
            f"over {end - mark} clk_smc_i with DATA_CTRL still 0x{REG_DRIVES_ONE:x}; "
            f"secondary state {secondary}",
        )

    async def _pulse_width_and_period(self, trace: _OctsTrace) -> None:
        clk = cocotb.top.clk_smc_i
        widths: list[str] = []
        periods: list[str] = []
        for credit, pulse, want in PULSE_SETTINGS:
            label = f"CV{credit:02X}_PW{pulse:02X}"
            ctrl = _ctrl(credit, pulse)
            await self.csr_write(f"CTRL_{label}", _OCTS_CTRL, ctrl)
            await self.csr_read(f"CTRL_{label}_RB", _OCTS_CTRL, expected=ctrl)
            reload = await self._start_outside_credit_pulse(f"START_{label}", trace)
            await ClockCycles(clk, 3 * credit + want + 4)
            end = trace.cycle - 1
            sync_runs = trace.runs(trace.sync, reload - 1, end)
            credit_runs = trace.runs(trace.credit, reload, end)
            credit_rises = trace.rises(trace.credit, reload, end)
            assert sync_runs and sync_runs[0][0] == reload, (
                f"{label}: no load pulse starts at the reload cycle {reload}; runs {sync_runs}"
            )
            assert [n for _, n in sync_runs] == [want], (
                f"{label}: load pulse high runs {[n for _, n in sync_runs]} clk_smc_i after the START "
                f"at {reload}, expected one run of {want} (PULSE_WIDTH {pulse})"
            )
            assert len(credit_runs) >= 2 and all(n == want for _, n in credit_runs), (
                f"{label}: credit pulse high runs {[n for _, n in credit_runs]} clk_smc_i, expected "
                f">= 2 runs of {want} (PULSE_WIDTH {pulse})"
            )
            gaps = [b - a for a, b in zip(credit_rises, credit_rises[1:])]
            assert credit_rises[0] - reload == credit and all(g == credit for g in gaps), (
                f"{label}: credit rises at {credit_rises} after the START at {reload}: first at "
                f"+{credit_rises[0] - reload}, spacings {gaps}, expected every one == CREDIT_VAL "
                f"{credit}"
            )
            self.sync_runs_per_start += 1
            widths.append(
                f"PW {pulse}: load {sync_runs[0][1]}, credit {[n for _, n in credit_runs]}"
            )
            periods.append(
                f"CREDIT_VAL 0x{credit:02x}: first +{credit_rises[0] - reload}, spacings {gaps}"
            )
        self._chk(
            "CHK-OCTS-PULSE-WIDTH",
            "high run of every load and credit pulse in clk_smc_i == PULSE_WIDTH, 0 -> 1: "
            + "; ".join(widths)
            + f"; {self.dropped_starts} STARTs landed in a credit pulse and were repeated",
        )
        self._chk(
            "CHK-OCTS-CREDIT-PERIOD",
            "credit rises spaced CREDIT_VAL clk_smc_i, the first one CREDIT_VAL after the START: "
            + "; ".join(periods),
        )

    async def _start_clears_interval(self, trace: _OctsTrace) -> None:
        clk = cocotb.top.clk_smc_i
        credit, pulse = LONG_CREDIT, 2
        ctrl = _ctrl(credit, pulse)
        await self.csr_write("CTRL_INTERVAL", _OCTS_CTRL, ctrl)
        mark = trace.cycle
        last = await self._await_trace(
            "INTERVAL credit rise",
            trace,
            lambda t: (t.rises(t.credit, mark, t.cycle - 1) or [None])[0],
        )
        await ClockCycles(clk, credit // 3)
        reload = await self._start("START_INTERVAL", trace)
        assert not trace.credit[reload - 1], (
            f"the START landed at {reload} inside a credit pulse (rise {last}); no load pulse"
        )
        phase = (reload - last) % credit
        assert phase, (
            f"the START landed at {reload}, on the old credit phase (rise {last}, CREDIT_VAL "
            f"{credit}); the leg cannot tell a cleared interval from an untouched one"
        )
        old_next = last + credit * ((reload - last + credit - 1) // credit)
        await ClockCycles(clk, credit + pulse + 4)
        end = trace.cycle - 1
        rises = trace.rises(trace.credit, reload, end)
        assert rises and rises[0] == reload + credit and rises[0] != old_next, (
            f"after the START at {reload} ({phase} cycles into an interval that began at {last}) "
            f"the credit rises are {rises}: expected the first at {reload + credit} (START + "
            f"CREDIT_VAL), the old phase would have given {old_next}"
        )
        self._chk(
            "CHK-OCTS-START-CLEARS-INTERVAL",
            f"CREDIT_VAL 0x{credit:02x}: credit rise at {last}, START landed at {reload} "
            f"({phase} cycles into the interval), next credit at {rises[0]} == START + CREDIT_VAL; "
            f"the untouched interval would have pulsed at {old_next}",
        )

    async def _pulse_no_queue(self, trace: _OctsTrace) -> None:
        clk = cocotb.top.clk_smc_i
        credit, pulse = LONG_CREDIT, WIDE_PULSE
        ctrl = _ctrl(credit, pulse)
        await self.csr_write("CTRL_WIDE", _OCTS_CTRL, ctrl)
        await self.csr_read("CTRL_WIDE_RB", _OCTS_CTRL, expected=ctrl)
        mark = trace.cycle
        rise = await self._await_trace(
            "WIDE credit rise",
            trace,
            lambda t: (t.rises(t.credit, mark, t.cycle - 1) or [None])[0],
        )
        reload = await self._start("START_IN_PULSE", trace)
        before = trace.count[reload - 1]
        assert trace.credit[reload - 1] and reload - rise < pulse, (
            f"the START landed at {reload}, outside the credit pulse that rose at {rise} "
            f"(width {pulse}); the no-queue rule needs a START inside a pulse"
        )
        await ClockCycles(clk, credit + pulse + 8)
        end = trace.cycle - 1
        sync_high = sum(trace.sync[rise : end + 1])
        credit_runs = trace.runs(trace.credit, rise - 1, end)
        credit_rises = trace.rises(trace.credit, reload, end)
        assert sync_high == 0, (
            f"the START at {reload}, {reload - rise} cycles into the credit pulse of {pulse}, "
            f"drove pad {SYNC_PAD} high on {sync_high} samples; a trigger during a pulse is not "
            f"queued"
        )
        assert credit_runs and credit_runs[0] == (rise, pulse), (
            f"the credit pulse under the START ran {credit_runs[:1]} (start, length), expected "
            f"({rise}, {pulse})"
        )
        assert credit_rises and credit_rises[0] == reload + credit, (
            f"credit rises after the in-pulse START at {reload}: {credit_rises}, expected the "
            f"first at {reload + credit}"
        )
        assert before > PRESET, (
            f"count 0x{before:x} the cycle before the START is not above the preset"
        )
        self._chk(
            "CHK-OCTS-PULSE-NO-QUEUE",
            f"CREDIT_VAL 0x{credit:02x} PULSE_WIDTH 0x{pulse:02x}: START landed at {reload}, "
            f"{reload - rise} cycles into the credit pulse that rose at {rise}: count reloaded "
            f"0x{before:x} -> 0x{PRESET:x}, pad {SYNC_PAD} high on {sync_high} samples over "
            f"{end - rise} clk_smc_i, the credit pulse ran {credit_runs[0][1]} cycles, next credit "
            f"at {credit_rises[0]} == START + CREDIT_VAL; {self.sync_runs_per_start} STARTs "
            f"outside a pulse each gave one load pulse",
        )

    async def _primary_ignores_inputs(self, trace: _OctsTrace) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        credit, pulse = SHORT_CREDIT, 2
        await self.csr_write("CTRL_INJECT", _OCTS_CTRL, _ctrl(credit, pulse))
        mark = trace.cycle
        for _ in range(INJECT_PULSES):
            await pulse_high(dut.tb_octs_sync_load_ext, clk, INJECT_WIDTH, INJECT_GAP)
            await pulse_high(dut.tb_octs_cnt_credit_ext, clk, INJECT_WIDTH, INJECT_GAP)
        dut.tb_octs_sync_load_ext.value = 0
        dut.tb_octs_cnt_credit_ext.value = 0
        await ClockCycles(clk, 2 * credit)
        end = trace.cycle - 1
        deltas = [trace.count[i] - trace.count[i - 1] for i in range(mark + 1, end + 1)]
        off = [(mark + 1 + i, d) for i, d in enumerate(deltas) if d != 1]
        status = await self.csr_read("STATUS_INJECT", _OCTS_STATUS)
        assert not off, (
            f"PRIMARY count left its +1 course at (cycle, step) {off[:8]} while {INJECT_PULSES} "
            f"sync and {INJECT_PULSES} credit pulses were injected on pads {SYNC_PAD}/{CREDIT_PAD}"
        )
        assert (status & (_OCTS_STATUS_MODE | _OCTS_STATUS_RUNNING)) == _OCTS_STATUS_RUNNING, (
            f"STATUS=0x{status:08x} after the inject under the PRIMARY strap"
        )
        rises = trace.rises(trace.credit, mark, end)
        gaps = [b - a for a, b in zip(rises, rises[1:])]
        reached = trace.port_high("tb_octs_core_sync_load_in", mark, end + 1) + trace.port_high(
            "tb_octs_core_credit_in", mark, end + 1
        )
        assert len(rises) >= 3 and all(g == credit for g in gaps), (
            f"PRIMARY credit rises during the inject {rises}, spacings {gaps}, expected CREDIT_VAL "
            f"{credit}"
        )
        self._chk(
            "CHK-OCTS-PRIMARY-IGNORES-INPUTS",
            f"PRIMARY running, {INJECT_PULSES} sync and {INJECT_PULSES} credit pulses of "
            f"{INJECT_WIDTH} clk_smc_i injected on pads {SYNC_PAD}/{CREDIT_PAD}: all "
            f"{len(deltas)} count steps == 1 (count 0x{trace.count[mark]:x} -> "
            f"0x{trace.count[end]:x}), STATUS=0x{status:08x}, own credit rises {len(rises)} "
            f"spaced {sorted(set(gaps))}; the timer's sync_load/credit input ports were high on "
            f"{reached} samples (the padring disables a PRIMARY's pad receivers); the same pins "
            f"loaded the SECONDARY count earlier in this run",
        )

    def _timeout_paths(self, trace: _OctsTrace) -> None:
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{self.accesses} SEP_IN accesses bounded by the AXI driver timeout; {len(self.waits)} "
            f"trace waits bounded by {TRACE_BOUND} clk_smc_i: " + "; ".join(self.waits) + f"; "
            f"trace {trace.cycle} cycles",
        )

    async def body(self) -> None:
        dut = cocotb.top
        trace = _OctsTrace(dut)
        task = cocotb.start_soon(trace.run())
        try:
            await self._entry()
            secondary = await self._secondary_phase(trace)
            await self._gpio_enable_pads(trace, secondary)
            await self._pulse_width_and_period(trace)
            await self._start_clears_interval(trace)
            await self._pulse_no_queue(trace)
            await self._primary_ignores_inputs(trace)
            self._timeout_paths(trace)
        finally:
            trace.stop = True
            await with_timeout(task, 1_000, "ns")
