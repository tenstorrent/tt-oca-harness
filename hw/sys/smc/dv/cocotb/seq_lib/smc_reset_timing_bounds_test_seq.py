# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cycle counts of the reset controller and the pins that follow a reset without a synchroniser.

`clk_rst.adoc` states, in SMC Reset Unit, that `powergood_i` "is stretched by 32
reference clock cycles into `powergood_stable`" and that the cold reset's
"release is extended by 255 cycles" (Power-Good and Cold Reset: "A 255-cycle
reference-clock extension holds cold reset after the filtered input releases.
Incoming cool reset has the same low-sample filter but no cold-reset
extension."); in SMC Reset Distribution, that `rst_cold_stable_smc_clk_no`
"disables the GPIO outputs while it is low"; and in SMC Reset Unit, that "the
per-subsystem cold and warm resets leave `ss_reset_ctrl_o` unsynchronised".

The cold and cool pins share the de-glitcher, the primary-reset AND and the
reference-clock release synchroniser, so the extension is the difference
between the two pin-release-to-`rst_primary_ref_clk_no` counts, measured with
one loop at one reference period: 255 exactly. The powergood count is the
number of `clk_ref_i` rising edges from `powergood_i` rising, a third of a
period after an edge, to `powergood_stable_o` reading 1 once the edge has
settled: 32 exactly.
During the cold pin's low window and its extension every `core2pad_en_o` bit
reads 0 at every `clk_smc_i` edge on which `rst_primary_smc_clk_no` reads 0,
after GPIO wrap 0 had its output enabled, and the same programming enables it
again after the chain releases; the GPIO registers are on the primary reset,
which is asserted throughout that window, so the level is graded at the SMC
boundary and the cold gate is not separated from the register reset. `ss_reset_ctrl_o[5]` follows an
`SS_WARM_RESET_N` write the same number of `clk_smc_i` after the write's W
handshake as `isolate_req_o[3]` follows an `ISOLATE_REQ_REG` write, a path that
`clk_rst.adoc` (Isolation and FLR) gives as reaching the output directly, and
the JTAG cold override within one `clk_smc_i` of the override.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_addr_map import jtag_smc_reset_ctrl_bit, reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_gpio_output_driveback_test_seq import (
    GPIO0_DATA_CTRL,
    OUT_DISABLE,
    OUT_DRIVE_HIGH,
    smc_gpio_output_driveback_test_seq,
)
from .smc_reset_seq_base import SmcResetSeqBase

CHK_EXTENSION = "CHK-COLD-EXTENSION-255"
CHK_STRETCH = "CHK-POWERGOOD-STRETCH-32"
CHK_GPIO = "CHK-GPIO-OUT-DISABLED-IN-COLD"
CHK_SS = "CHK-SS-RESET-PIN-UNSYNC-LATENCY"

COLD_EXTENSION_CYCLES = 255
POWERGOOD_STRETCH_CYCLES = 32
PIN_LOW_SAMPLES = 64
MIN_COLD_HOLD_SAMPLES = 64
RELEASE_BOUND_REF_CYCLES = 600
STRETCH_BOUND_REF_CYCLES = 100
GLITCH_EFFECT_BOUND_REF_CYCLES = 64
GLITCH_HOLD_REF_CYCLES = 40
RECOVER_BOUND_REF_CYCLES = 2000
PAD_BOUND_SMC_CYCLES = 64
SS_PIN_BOUND_SMC_CYCLES = 64
SS_UNSYNC_LATENCY_SMC_CYCLES = 1
SS_INDEX = 5
ISO_INDEX = 3
SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
ISO_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
SS_WARM_RESET = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset")
SS_COLD_RESET = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_reset")
_resolve_int = smc_gpio_output_driveback_test_seq._resolve_int


def _now_ps() -> int:
    return int(round(get_sim_time("ps")))


class _SmcClockMonitor:
    """Per-`clk_smc_i` record of the SEP_IN W and B handshakes and three reset-unit outputs."""

    def __init__(self) -> None:
        self.cycle = 0
        self.w_cycle: int | None = None
        self.b_cycle: int | None = None
        self.changes: dict[str, list[tuple[int, int]]] = {"warm": [], "cold": [], "iso": []}
        self._last: dict[str, int | None] = {"warm": None, "cold": None, "iso": None}

    def start(self) -> None:
        cocotb.start_soon(self._run())

    @staticmethod
    def _bit(sig, bit: int) -> int:
        return (_resolve_int(sig) >> bit) & 1

    def _note(self, name: str, value: int) -> None:
        if value != self._last[name]:
            self.changes[name].append((self.cycle, value))
            self._last[name] = value

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.cycle += 1
            if int(dut.s_axi_wvalid.value) and int(dut.s_axi_wready.value):
                self.w_cycle = self.cycle
            if int(dut.s_axi_bvalid.value) and int(dut.s_axi_bready.value):
                self.b_cycle = self.cycle
            self._note("warm", self._bit(dut.tb_ss_warm_reset_n, SS_INDEX))
            self._note("cold", self._bit(dut.tb_ss_cold_reset_n, SS_INDEX))
            self._note("iso", self._bit(dut.tb_isolate_req_o, ISO_INDEX))


class smc_reset_timing_bounds_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Cold and cool pin release counts, the powergood stretch, pad enables in cold, SS pins."""

    RELEASE_BOUND_REF_CYCLES = RECOVER_BOUND_REF_CYCLES

    def __init__(self, name: str = "smc_reset_timing_bounds_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.passes: list[str] = []

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    @staticmethod
    def _level(sig, what: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{what} is not resolvable: {value}"
        return int(value)

    async def _drive_after_edge(self, op: SmcResetOp) -> int:
        """Drive `op` a third of a period after a `clk_ref_i` edge; return the drive time (ps)."""
        clk = cocotb.top.clk_ref_i
        third_ps = int(round(self.cfg.ref_clk_period_ns * 1000)) // 3
        await RisingEdge(clk)
        t_edge = _now_ps()
        await Timer(third_ps, unit="ps")
        await self._send(op)
        t_drive = _now_ps()
        assert t_drive - t_edge < 3 * third_ps, (
            f"{op.value} was driven {t_drive - t_edge} ps after the clk_ref_i edge, past the period"
        )
        return t_drive

    async def _count_release(self, what: str) -> int:
        """`clk_ref_i` edges from the pin release to `rst_primary_ref_clk_no` reading 1."""
        dut = cocotb.top
        level = 0
        for n in range(1, RELEASE_BOUND_REF_CYCLES + 1):
            await RisingEdge(dut.clk_ref_i)
            level = self._level(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no")
            if level == 1:
                return n
        raise AssertionError(
            f"{what}: rst_primary_ref_clk_no still {level} {RELEASE_BOUND_REF_CYCLES} clk_ref_i "
            f"cycles after the pin release"
        )

    async def _await_pad(self, want: int, pad_bit: int, label: str) -> int:
        dut = cocotb.top
        en = 0
        for n in range(1, PAD_BOUND_SMC_CYCLES + 1):
            await RisingEdge(dut.clk_smc_i)
            en = _resolve_int(dut.tb_core2pad_en_o)
            if ((en >> pad_bit) & 1) == want:
                return n
        raise AssertionError(
            f"{label}: core2pad_en_o[{pad_bit}] did not read {want} within {PAD_BOUND_SMC_CYCLES} "
            f"clk_smc_i cycles (core2pad_en_o=0x{en:x})"
        )

    async def _gpio_enable(self, label: str) -> int:
        """Enable GPIO wrap 0's output; return the one pad bit that newly asserted."""
        dut = cocotb.top
        await ClockCycles(dut.clk_smc_i, 4)
        base_en = _resolve_int(dut.tb_core2pad_en_o)
        await self.csr_write(f"GPIO0_TX_{label}", GPIO0_DATA_CTRL, OUT_DRIVE_HIGH)
        new = 0
        for _ in range(PAD_BOUND_SMC_CYCLES):
            await RisingEdge(dut.clk_smc_i)
            new = _resolve_int(dut.tb_core2pad_en_o) & ~base_en
            if new:
                break
        assert new and new & (new - 1) == 0, (
            f"{label}: GPIO wrap 0 TX enable raised {bin(new).count('1')} new core2pad_en_o bits "
            f"within {PAD_BOUND_SMC_CYCLES} clk_smc_i cycles (delta 0x{new:x} over base "
            f"0x{base_en:x}), want exactly one"
        )
        return new.bit_length() - 1

    async def _pad_hold_sampler(self, result: dict) -> None:
        """Every `clk_smc_i` edge with `rst_primary_smc_clk_no` 0: `core2pad_en_o` is 0.

        The SMC-clock cold-stable reset that the GPIO wraps take releases on the
        same `clk_smc_i` edge as the SMC-clock primary reset after a cold pulse,
        and `tb_top` exports the latter.
        """
        dut = cocotb.top
        rst = dut.rst_primary_smc_clk_no
        while self._level(rst, "rst_primary_smc_clk_no") == 1:
            await RisingEdge(dut.clk_smc_i)
        result["samples"] = 0
        while self._level(rst, "rst_primary_smc_clk_no") == 0:
            en = _resolve_int(dut.tb_core2pad_en_o)
            if en != 0:
                result["violation"] = en
                return
            result["samples"] += 1
            await RisingEdge(dut.clk_smc_i)

    async def _cold_leg(self, pad_bit: int) -> tuple[int, int, int]:
        """Cold pin low 64 edges then released; return (n_rel, hold samples, en at edge 1)."""
        dut = cocotb.top
        hold: dict = {}
        sampler = cocotb.start_soon(self._pad_hold_sampler(hold))
        await self._drive_after_edge(SmcResetOp.COLD_RST_LO)
        await RisingEdge(dut.clk_ref_i)
        en_first = _resolve_int(dut.tb_core2pad_en_o)
        await ClockCycles(dut.clk_ref_i, PIN_LOW_SAMPLES - 1)
        assert self._level(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no") == 0, (
            "rst_primary_ref_clk_no reads 1 at the end of the cold pin low window"
        )
        assert "samples" in hold, (
            f"rst_primary_smc_clk_no never read 0 during the {PIN_LOW_SAMPLES}-edge cold pin low "
            f"window"
        )
        await Timer(int(round(self.cfg.ref_clk_period_ns * 1000)) // 3, unit="ps")
        await self._send(SmcResetOp.COLD_RST_HI)
        n_rel = await self._count_release("cold")
        assert sampler.done(), "the SMC-clock reset is still asserted after rst_primary_ref_clk_no"
        assert "violation" not in hold, (
            f"{CHK_GPIO} FAIL: core2pad_en_o reads 0x{hold['violation']:x} with "
            f"rst_primary_smc_clk_no 0, at checked clk_smc_i sample {hold['samples'] + 1} of the "
            f"cold hold"
        )
        assert (en_first >> pad_bit) & 1 == 1, (
            f"core2pad_en_o[{pad_bit}] reads 0 at the first clk_ref_i edge after the cold pin "
            f"fell, before the de-glitcher could assert (core2pad_en_o=0x{en_first:x})"
        )
        assert hold["samples"] >= MIN_COLD_HOLD_SAMPLES, (
            f"the cold hold spanned {hold['samples']} checked clk_smc_i samples, fewer than "
            f"{MIN_COLD_HOLD_SAMPLES}"
        )
        return n_rel, hold["samples"], en_first

    async def _cool_leg(self) -> int:
        dut = cocotb.top
        await self._drive_after_edge(SmcResetOp.COOL_RST_LO)
        await ClockCycles(dut.clk_ref_i, PIN_LOW_SAMPLES)
        assert self._level(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no") == 0, (
            "rst_primary_ref_clk_no reads 1 at the end of the cool pin low window"
        )
        assert self._level(dut.rst_cold_stable_ref_clk_no, "rst_cold_stable_ref_clk_no") == 1, (
            "rst_cold_stable_ref_clk_no reads 0 during the cool pin low window"
        )
        await Timer(int(round(self.cfg.ref_clk_period_ns * 1000)) // 3, unit="ps")
        await self._send(SmcResetOp.COOL_RST_HI)
        return await self._count_release("cool")

    async def _powergood_leg(self) -> int:
        dut = cocotb.top
        await self._send(SmcResetOp.POWERGOOD_LO)
        await self._send(
            SmcResetOp.WAIT_STATE,
            expect_powergood_stable=0,
            expect_left_stable=True,
            timeout_ref_cycles=GLITCH_EFFECT_BOUND_REF_CYCLES,
        )
        await self._hold_raw(
            "powergood low",
            hold=GLITCH_HOLD_REF_CYCLES,
            expect_powergood_stable=0,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
        )
        await self._drive_after_edge(SmcResetOp.POWERGOOD_HI)
        level = 0
        for n in range(1, STRETCH_BOUND_REF_CYCLES + 1):
            await RisingEdge(dut.clk_ref_i)
            await ReadOnly()
            level = self._level(dut.powergood_stable_o, "powergood_stable_o")
            if level == 1:
                return n
        raise AssertionError(
            f"powergood_stable_o still {level} {STRETCH_BOUND_REF_CYCLES} clk_ref_i cycles after "
            f"powergood_i rose"
        )

    async def _recover(self, label: str) -> None:
        await self._wait_released(label, bound=RECOVER_BOUND_REF_CYCLES)
        await self.wait_fuse_sense_done()

    async def _write_leg(
        self, mon: _SmcClockMonitor, name: str, addr: int, word: int, want: int, label: str
    ) -> tuple[int, int]:
        """Write `word`; return the watched output's change cycle relative to the W and B handshakes."""
        dut = cocotb.top
        before = len(mon.changes[name])
        await self.csr_write(f"{label}", addr, word)
        w_cycle, b_cycle = mon.w_cycle, mon.b_cycle
        assert w_cycle is not None and b_cycle is not None, (
            f"{label}: no W or B handshake was seen on SEP_IN"
        )
        for _ in range(SS_PIN_BOUND_SMC_CYCLES):
            if len(mon.changes[name]) > before:
                break
            await RisingEdge(dut.clk_smc_i)
        changes = mon.changes[name][before:]
        assert len(changes) == 1 and changes[0][1] == want, (
            f"{label}: {name} output changes after the write: {changes}, want one change to "
            f"{want} within {SS_PIN_BOUND_SMC_CYCLES} clk_smc_i cycles"
        )
        await self.csr_read(f"{label}_RB", addr, expected=word)
        return changes[0][0] - w_cycle, changes[0][0] - b_cycle

    async def _ss_override_leg(self, mon: _SmcClockMonitor, ovrd: int, want: int, label: str):
        dut = cocotb.top
        before = len(mon.changes["cold"])
        await RisingEdge(dut.clk_smc_i)
        start = mon.cycle
        dut.tb_jtag_reset_ctrl.value = ovrd
        for _ in range(SS_PIN_BOUND_SMC_CYCLES):
            if len(mon.changes["cold"]) > before:
                break
            await RisingEdge(dut.clk_smc_i)
        changes = mon.changes["cold"][before:]
        assert len(changes) == 1 and changes[0][1] == want, (
            f"{label}: tb_ss_cold_reset_n[{SS_INDEX}] changes after the override: {changes}, "
            f"want one change to {want} within {SS_PIN_BOUND_SMC_CYCLES} clk_smc_i cycles"
        )
        return changes[0][0] - start

    async def _ss_leg(self) -> None:
        dut = cocotb.top
        all_released = SS_WARM_RESET
        assert all_released != 0, f"SS_WARM_RESET_N reset 0x{all_released:x} asserts subsystems"
        assert (SS_COLD_RESET >> SS_INDEX) & 1 == 0, (
            f"SS_COLD_RESET_N reset 0x{SS_COLD_RESET:x} releases subsystem {SS_INDEX}"
        )
        assert self._level(dut.tb_jtag_reset_ctrl, "tb_jtag_reset_ctrl") == 0, (
            "a JTAG reset override is already driven"
        )
        mon = _SmcClockMonitor()
        mon.start()
        await ClockCycles(dut.clk_smc_i, 4)
        await self.csr_read("SS_WARM_IDLE", SS_WARM, expected=all_released)
        await self.csr_read("ISO_REG_IDLE", ISO_REG, expected=0)
        warm_idle = mon._bit(dut.tb_ss_warm_reset_n, SS_INDEX)
        cold_idle = mon._bit(dut.tb_ss_cold_reset_n, SS_INDEX)
        iso_idle = mon._bit(dut.tb_isolate_req_o, ISO_INDEX)
        assert warm_idle == 1 and cold_idle == 0 and iso_idle == 0, (
            f"idle subsystem {SS_INDEX} pins warm={warm_idle} cold={cold_idle} and "
            f"isolate_req_o[{ISO_INDEX}]={iso_idle}, want 1, 0 and 0"
        )
        iso_bit = 1 << ISO_INDEX
        iso_set = await self._write_leg(mon, "iso", ISO_REG, iso_bit, 1, "ISO_REG_SET")
        iso_clr = await self._write_leg(mon, "iso", ISO_REG, 0, 0, "ISO_REG_CLR")
        ss_assert = await self._write_leg(
            mon, "warm", SS_WARM, all_released & ~(1 << SS_INDEX), 0, "SS_WARM_ASSERT"
        )
        ss_release = await self._write_leg(mon, "warm", SS_WARM, all_released, 1, "SS_WARM_RELEASE")
        ovrd = (1 << jtag_smc_reset_ctrl_bit("ss_cold_reset_n_ovrd", SS_INDEX)) | (
            1 << jtag_smc_reset_ctrl_bit("ss_cold_reset_n_val", SS_INDEX)
        )
        d_ovrd = await self._ss_override_leg(mon, ovrd, 1, "OVRD")
        d_idle = await self._ss_override_leg(mon, 0, 0, "IDLE")
        wrong = []
        if ss_assert[0] != iso_set[0] or ss_release[0] != iso_clr[0]:
            wrong.append(
                f"tb_ss_warm_reset_n[{SS_INDEX}] changed {ss_assert[0]} and {ss_release[0]} "
                f"clk_smc_i after the W handshake where isolate_req_o[{ISO_INDEX}] changed "
                f"{iso_set[0]} and {iso_clr[0]}"
            )
        if max(d_ovrd, d_idle) > SS_UNSYNC_LATENCY_SMC_CYCLES:
            wrong.append(
                f"tb_ss_cold_reset_n[{SS_INDEX}] changed {d_ovrd} and {d_idle} clk_smc_i after the "
                f"JTAG override (bound {SS_UNSYNC_LATENCY_SMC_CYCLES})"
            )
        assert not wrong, f"{CHK_SS} FAIL: {'; '.join(wrong)}"
        cocotb.log.info(
            "%s PASS: tb_ss_warm_reset_n[%d] changed %d and %d clk_smc_i cycles after the W "
            "handshake of the SS_WARM_RESET_N writes that assert and release it (%d and %d after "
            "the B handshake), the same counts as isolate_req_o[%d] after the ISOLATE_REQ_REG "
            "writes that set and clear it (%d and %d after W), whose path from its register is "
            "combinational; tb_ss_cold_reset_n[%d] changed %d and %d clk_smc_i cycles after the "
            "JTAG cold override was driven and cleared (bound %d)",
            CHK_SS,
            SS_INDEX,
            ss_assert[0],
            ss_release[0],
            ss_assert[1],
            ss_release[1],
            ISO_INDEX,
            iso_set[0],
            iso_clr[0],
            SS_INDEX,
            d_ovrd,
            d_idle,
            SS_UNSYNC_LATENCY_SMC_CYCLES,
        )
        self.passes.append(CHK_SS)

    async def body(self) -> None:
        dut = cocotb.top
        for name in (
            "rst_primary_ref_clk_no",
            "rst_primary_smc_clk_no",
            "rst_cold_stable_ref_clk_no",
            "powergood_stable_o",
            "tb_core2pad_en_o",
            "tb_ss_warm_reset_n",
            "tb_ss_cold_reset_n",
            "tb_isolate_req_o",
            "tb_jtag_reset_ctrl",
        ):
            assert hasattr(dut, name), f"tb_top has no {name}"
        ref_ns = self.cfg.ref_clk_period_ns
        await self.wait_fuse_sense_done()
        s0 = await self._send(SmcResetOp.SAMPLE)
        assert s0.resolvable and s0.rst_primary_ref_clk_n == 1, s0

        # S1: GPIO wrap 0 output enabled, then the cold pin low for 64 edges and released.
        pad_bit = await self._gpio_enable("BEFORE")
        n_cold, hold_samples, en_first = await self._cold_leg(pad_bit)
        await self._recover("after the cold pin")
        pad_again = await self._gpio_enable("AFTER")
        assert pad_again == pad_bit, (
            f"GPIO wrap 0 enabled pad {pad_again} after the cold reset, pad {pad_bit} before it"
        )
        await self.csr_write("GPIO0_DISABLE", GPIO0_DATA_CTRL, OUT_DISABLE)
        await self._await_pad(0, pad_bit, "GPIO0_DISABLE")
        cocotb.log.info(
            "%s PASS: GPIO wrap 0 drove core2pad_en_o[%d]=1 (0x%x at the first clk_ref_i edge of "
            "the cold pin low window); core2pad_en_o read 0 at all %d checked clk_smc_i edges on "
            "which rst_primary_smc_clk_no read 0, through the pin release and the extension; "
            "after the chain released the same write enabled pad %d again",
            CHK_GPIO,
            pad_bit,
            en_first,
            hold_samples,
            pad_again,
        )
        self.passes.append(CHK_GPIO)

        # S2: the cool pin through the same low window and count.
        n_cool = await self._cool_leg()
        await self._recover("after the cool pin")
        assert n_cold - n_cool == COLD_EXTENSION_CYCLES, (
            f"{CHK_EXTENSION} FAIL: cold pin release to rst_primary_ref_clk_no=1 took {n_cold} "
            f"clk_ref_i cycles and the cool pin {n_cool}, a difference of {n_cold - n_cool}, "
            f"want {COLD_EXTENSION_CYCLES} at ref {ref_ns} ns"
        )
        cocotb.log.info(
            "%s PASS: rst_primary_ref_clk_no read 1 %d clk_ref_i cycles after the cold pin "
            "release and %d after the cool pin release at ref %s ns, both after a %d-edge low "
            "window; the difference %d is the 255-cycle cold extension",
            CHK_EXTENSION,
            n_cold,
            n_cool,
            ref_ns,
            PIN_LOW_SAMPLES,
            n_cold - n_cool,
        )
        self.passes.append(CHK_EXTENSION)

        # S3: powergood_i low then high; count edges to powergood_stable_o=1.
        n_pg = await self._powergood_leg()
        await self._recover("after the powergood glitch")
        assert n_pg == POWERGOOD_STRETCH_CYCLES, (
            f"{CHK_STRETCH} FAIL: powergood_stable_o read 1 {n_pg} clk_ref_i edges after "
            f"powergood_i rose, want {POWERGOOD_STRETCH_CYCLES}"
        )
        cocotb.log.info(
            "%s PASS: powergood_stable_o read 0 while powergood_i was low for %d checked "
            "clk_ref_i edges and read 1 at clk_ref_i edge %d after the powergood_i rise at ref "
            "%s ns (want %d, each edge sampled once it has settled)",
            CHK_STRETCH,
            GLITCH_HOLD_REF_CYCLES,
            n_pg,
            ref_ns,
            POWERGOOD_STRETCH_CYCLES,
        )
        self.passes.append(CHK_STRETCH)

        # S4: subsystem 5 warm pin after a register write, cold pin after a JTAG override.
        await self._ss_leg()
        sb = self.env.scoreboard
        assert sb.reset_raw_checks_seen >= GLITCH_HOLD_REF_CYCLES, (
            f"expected {GLITCH_HOLD_REF_CYCLES} checked powergood-low samples, scoreboard saw "
            f"{sb.reset_raw_checks_seen}"
        )
