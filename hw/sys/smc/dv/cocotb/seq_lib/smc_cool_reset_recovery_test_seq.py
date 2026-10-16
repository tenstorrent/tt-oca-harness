# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Recovery after the ``rst_cool_ni`` pin collides with the FLR cool-reset hold.

Spec sources: hw/sys/smc/doc/clk_rst.adoc (the primary reset is the AND of the stable cold
reset, the de-glitched cool-reset pin and the FLR cool reset; the warm reset is the AND of the
primary reset, the watchdog reset and the fuse reset; ``u_reset_unit_reg``, ``SS_CONFIG`` and
``SS_COLD_RESET_N`` are reset by the primary reset while the isolation registers and FLR
counters are reset only by the stable cold reset; the FLR edge sets ``ISOLATE_REQ_SMC_REG``
and a software write clears it; a zero hold count disables the timed reset but still sets the
latch), hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl, hw/sys/smc/doc/cpu.adoc (reset vector
``0xC004_0000``).

The pin is driven and the reset probes sampled on reference-clock edges. Reset-unit registers
are compared against their RDL reset values; the I2C timing, CPU_CTRL scratch and reset vector
words are printed as measured.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import cpu_ctrl_u32, reset_unit_u32, smc_addr, smc_indexed_addr
from .smc_cool_reset_deglitch_window_test_seq import (
    _ISO_BOUND,
    _RELEASE_BOUND,
    OUTPUTS,
)
from .smc_cool_reset_pin_flr_overlap_test_seq import (
    _CDC_REF,
    COLD_PROBES,
    PIN_AFTER_FALL,
    PIN_PAST_HOLD,
    smc_cool_reset_pin_flr_overlap_test_seq,
)
from .smc_i2c_master_target_test_seq import I2C0_TIMING0, _i2c_u32
from .smc_isolate_pin_utils import await_skip_mem_repair, drive_isolate_pin

SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")
SS_COLD_RESET_N = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR")
SMCEN = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR")
SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
ISOLATE_VIS = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_VIS_BASE_ADDR")
FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
RESET_VECTOR_0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", 0)
SCRATCH_0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)

SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")
SS_CONFIG_RESET = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_reset")
SS_COLD_RESET_N_RESET = reset_unit_u32("RESET_UNIT__SS_COLD_RESET_N__RESET_N_N0_SCAN_reset")
VIS_PIN_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__ISOLATE_REQ_PIN_bm")
VIS_COOL_I_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_I_bm")
VIS_COOL_O_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_O_bm")
VIS_COOL_I_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_I_reset")
VIS_COOL_O_RESET = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_O_reset")
VIS_COOL_I_BP = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_I_bp")
VIS_COOL_O_BP = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__COOL_RESET_N_O_bp")
VIS_PIN_BP = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_VIS__ISOLATE_REQ_PIN_bp")
RESET_VECTOR_RESET = cpu_ctrl_u32("CPU_CTRL__RESET_VECTOR__VECTOR_reset")
THIGH_BM = _i2c_u32("I2C__TIMING0__THIGH_bm")

# Programmed FLR counters: the pre-reset count leaves room to read the latch before the cool
# reset starts, the hold count is above the 96 cycles the pin collision needs.
_P = 0x100
_H = 0x80
_SMCEN = 0xFFFFFFFF
_SS_CONFIG_PAT = 0xA5A5A5A5
_SS_COLD_PAT = 0x5A5A5A5A
_TIMING0_PAT = 0x25 & THIGH_BM
_SCRATCH_PAT = 0x13579BDF
_ALL_ONES = 0xFFFFFFFF
_LOW_LANE = 0x1

_IDLE = 4
_FALL_BOUND = _P + 128
_RISE_BOUND = _H + 128
_WARM_BOUND = 50_000
_LATCH_POLLS = _ISO_BOUND
_S5_WATCH = _P + 128
_S5_BOUND = _S5_WATCH

STEPS = ("S1", "S2", "S3", "S4", "S5")
CHK_ORDER = (
    "CHK-COOLRST-PRIMARY-RELEASE",
    "CHK-COOLRST-WARM-FOLLOWS",
    "CHK-COOLRST-COLD-STAYS",
    "CHK-COOLRST-RESET-VECTOR",
    "CHK-COOLRST-ISOLATE-VIS",
    "CHK-COOLRST-CSR-RECOVERY",
    "CHK-COOLRST-OTHER-CSR-MEASURED",
    "CHK-COOLRST-LATCH-SET-HOLD",
    "CHK-COOLRST-LATCH-CLEAR",
    "CHK-COOLRST-LATCH-HOLD0",
)
FENCE_TERMS = {
    "S1": "CSRS_STAGED",
    "S2": "COLLISION_RUN",
    "S3": "RECOVERY_READS",
    "S4": "LATCH_CLEARED",
    "S5": "HOLD_COUNT_0",
}


class smc_cool_reset_recovery_test_seq(smc_cool_reset_pin_flr_overlap_test_seq):
    """CSR and reset-output recovery after the pin collides with the FLR hold; FLR latch."""

    def __init__(self, name: str = "smc_cool_reset_recovery_test_seq") -> None:
        super().__init__(name)
        self.recovery_ok: bool = False
        self._warm: dict[int, int] = {}
        self._iso: dict[int, int] = {}

    async def _tick(self) -> int:
        tick = await super()._tick()
        dut = cocotb.top
        self._warm[tick] = self._int(dut.tb_rst_warm_smc_clk_n) & 1
        self._iso[tick] = self._int(dut.tb_isolate_req_o)
        return tick

    def _last_state(self) -> str:
        warm = self._warm.get(self._tick_no)
        return f"{super()._last_state()} warm_n={warm}"

    def _assert_fence(self) -> None:
        steps = [e for e in self._events if e[0] == "step"]
        assert [e[1] for e in steps] == list(STEPS), f"step order {[e[1] for e in steps]}"
        stamps = [e[2] for e in steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chks = [e for e in self._events if e[0] == "chk"]
        assert [c[1] for c in chks] == list(CHK_ORDER), f"checker order {[c[1] for c in chks]}"
        index = {e: i for i, e in enumerate(self._events)}
        assert all(index[c] > index[steps[-1]] for c in chks), "checker line before step stamp"
        assert all(c[2] >= stamps[-1] for c in chks), "a checker printed before the last step"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[e[1]] for e in steps),
            ", ".join(c[1] for c in chks),
            ",".join(str(s) for s in stamps),
        )

    async def _idle(self) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, _IDLE)

    async def _wr(self, name: str, addr: int, data: int) -> None:
        await self.csr_write(name, addr, data)
        await self._idle()

    async def _rd(self, name: str, addr: int, want: int | None = None) -> int:
        got = await self.csr_read(name, addr)
        await self._idle()
        if want is not None:
            assert got == want, (
                f"{name}: read 0x{got:08x}, expected 0x{want:08x}; {self._last_state()}"
            )
        return got

    async def _stage(self, name: str, addr: int, data: int) -> int:
        await self._wr(name, addr, data)
        return await self._rd(f"{name}_RB", addr, data)

    async def _cool_fall(self, flr: dict) -> None:
        flr["fall"] = await self._until(
            f"{flr['label']}_COOL_FALL", _FALL_BOUND, lambda t: self._samples[t][2] == 0
        )
        cocotb.top.tb_cfg_flr_pf_active.value = 0

    async def _cool_rise(self, flr: dict) -> None:
        flr["rise"] = await self._until(
            f"{flr['label']}_COOL_RISE", _RISE_BOUND, lambda t: self._samples[t][2] == 1
        )

    async def _poll_latch(self, label: str) -> int:
        last = 0
        for _ in range(_LATCH_POLLS):
            last = await self._rd(f"{label}_SMC_REG_POLL", SMC_REG)
            if last & SMC_BIT:
                self._waits.append(f"{label}_LATCH_SET={_LATCH_POLLS}polls last=0x{last:x}")
                return last
        raise AssertionError(f"{label}: SMC_REG=0x{last:x} still 0 after {_LATCH_POLLS} polls")

    async def _s1(self) -> dict:
        await self._program("S1", _P, _H)
        await self._tick()
        assert self._samples[self._tick_no] == (1, 1, 1), (
            f"resets not released before the collision: {self._last_state()}"
        )
        pre = {}
        pre["ss_config"] = await self._stage("S1_SS_CONFIG", SS_CONFIG, _SS_CONFIG_PAT)
        pre["ss_cold"] = await self._stage("S1_SS_COLD_RESET_N", SS_COLD_RESET_N, _SS_COLD_PAT)
        pre["smcen"] = await self._stage("S1_SMCEN", SMCEN, _SMCEN)
        pre["delay"] = await self._rd("S1_FLR_DELAY", FLR_DELAY, _P)
        pre["hold"] = await self._rd("S1_FLR_HOLD", FLR_HOLD, _H)
        pre["timing"] = await self._stage("S1_I2C_TIMING0", I2C0_TIMING0, _TIMING0_PAT)
        pre["scratch"] = await self._stage("S1_SCRATCH0", SCRATCH_0, _SCRATCH_PAT)
        pre["vector"] = await self._rd("S1_RESET_VECTOR0", RESET_VECTOR_0)
        assert _SS_CONFIG_PAT != SS_CONFIG_RESET and _SS_COLD_PAT != SS_COLD_RESET_N_RESET
        assert _TIMING0_PAT != 0 and _SCRATCH_PAT != 0, "staged patterns must be nonzero"
        await self._tick()
        assert self._samples[self._tick_no] == (1, 1, 1), (
            f"resets not released after the staging: {self._last_state()}"
        )
        self._step_done("S1")
        return pre

    async def _s2(self) -> dict:
        run = {"latch_pre": await self._rd("S2_SMC_REG_PRE", SMC_REG, 0)}
        flr = self._flr_raise("S2")
        run["latch_edge"] = await self._poll_latch("S2")
        await self._tick()
        assert self._samples[self._tick_no] == (1, 1, 1), (
            f"latch reads ended after the cool reset began: {self._last_state()}"
        )
        await self._cool_fall(flr)
        await self._ticks(PIN_AFTER_FALL)
        run["pin_low"] = self._pin(0)
        await self._cool_rise(flr)
        await self._ticks(PIN_PAST_HOLD)
        run["pin_high"] = self._pin(1)
        start = flr["set"]
        asserted = max(self._first(o, 0, start) for o in OUTPUTS)
        await self._until(
            "S2_RELEASE",
            _RELEASE_BOUND,
            lambda t: (
                t > max(asserted, run["pin_high"])
                and self._samples[t][0] == 1
                and self._samples[t][1] == 1
            ),
        )
        flr["assert"] = {o: self._first(o, 0, start) for o in OUTPUTS}
        flr["release"] = {o: self._first(o, 1, flr["rise"]) for o in OUTPUTS}
        run["warm_release"] = await self._until(
            "S2_WARM_RELEASE", _WARM_BOUND, lambda t: self._warm[t] == 1 and t > flr["rise"]
        )
        run["flr"] = flr
        self._step_done("S2")
        return run

    async def _s3(self) -> dict:
        dut = cocotb.top
        post = {}
        post["ss_config"] = await self._rd("S3_SS_CONFIG", SS_CONFIG)
        post["ss_cold"] = await self._rd("S3_SS_COLD_RESET_N", SS_COLD_RESET_N)
        post["vis"] = await self._rd("S3_ISOLATE_VIS", ISOLATE_VIS)
        post["cool_ni"] = self._int(dut.rst_cool_ni) & 1
        post["cool_from_flr"] = self._int(dut.tb_rst_cool_from_flr) & 1
        post["smcen"] = await self._rd("S3_SMCEN", SMCEN)
        post["delay"] = await self._rd("S3_FLR_DELAY", FLR_DELAY)
        post["hold"] = await self._rd("S3_FLR_HOLD", FLR_HOLD)
        post["latch"] = await self._rd("S3_SMC_REG", SMC_REG)
        post["timing"] = await self._rd("S3_I2C_TIMING0", I2C0_TIMING0)
        post["scratch"] = await self._rd("S3_SCRATCH0", SCRATCH_0)
        post["vector"] = await self._rd("S3_RESET_VECTOR0", RESET_VECTOR_0)
        self._step_done("S3")
        return post

    async def _s4(self) -> dict:
        s4 = {"before": await self._rd("S4_SMC_REG_BEFORE", SMC_REG, SMC_BIT)}
        await self.csr_write_strobed("S4_SMC_REG_CLR", SMC_REG, _ALL_ONES, _LOW_LANE)
        await self._idle()
        s4["after"] = await self._rd("S4_SMC_REG_AFTER", SMC_REG, 0)
        self._step_done("S4")
        return s4

    async def _s5(self) -> dict:
        dut = cocotb.top
        await self._wr("S5_FLR_HOLD_0", FLR_HOLD, 0)
        await self._rd("S5_FLR_HOLD_0_RB", FLR_HOLD, 0)
        await self._ticks(_CDC_REF)
        self._waits.append(f"S5_cdc_allowance={_CDC_REF}ref")
        s5 = {"before": await self._rd("S5_SMC_REG_BEFORE", SMC_REG, 0)}
        flr = self._flr_raise("S5")
        await self._ticks(_S5_WATCH)
        dut.tb_cfg_flr_pf_active.value = 0
        self._waits.append(f"S5_WATCH={_S5_WATCH}ref last={self._last_state()}")
        s5["after"] = await self._rd("S5_SMC_REG_AFTER", SMC_REG)
        s5["window"] = (flr["set"], self._tick_no)
        s5["samples"] = [self._samples[t] for t in range(flr["set"] + 1, self._tick_no + 1)]
        await self._wr("S5_SMC_REG_CLR", SMC_REG, 0)
        s5["cleared"] = await self._rd("S5_SMC_REG_CLR_RB", SMC_REG, 0)
        await self._wr("S5_FLR_HOLD_RESTORE", FLR_HOLD, _H)
        s5["hold_restored"] = await self._rd("S5_FLR_HOLD_RESTORE_RB", FLR_HOLD, _H)
        self._step_done("S5")
        return s5

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_cfg_flr_pf_active"), "tb_cfg_flr_pf_active missing"
        dut.tb_cfg_flr_pf_active.value = 0
        dut.rst_cool_ni.value = 1
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "isolate pin low, no FLR")

        pre = await self._s1()
        run = await self._s2()
        post = await self._s3()
        s4 = await self._s4()
        s5 = await self._s5()
        await ClockCycles(dut.clk_ref_i, 2)

        flr = run["flr"]
        pin_low, pin_high = run["pin_low"], run["pin_high"]
        assert flr["fall"] <= pin_low < flr["rise"], "pin low not inside the hold"
        assert pin_high - pin_low >= 32 and flr["rise"] - pin_low >= 32, "pin low under 32 cycles"
        assert pin_high > flr["rise"], "pin released before the hold ended"

        # CHK-COOLRST-PRIMARY-RELEASE
        rel = {}
        for o in OUTPUTS:
            first = flr["assert"][o]
            assert first is not None, f"{o}: never asserted; {self._last_state()}"
            bad = [t for t in range(first, pin_high) if self._level(t, o) != 0]
            assert not bad, f"{o}: released samples {bad[:8]} before the sources ended"
            assert flr["release"][o] > pin_high, f"{o}: released before the pin"
            rel[o] = flr["release"][o] - pin_high
        self._chk(
            "CHK-COOLRST-PRIMARY-RELEASE",
            f"rst_primary_smc_clk_no asserted at tick {flr['assert']['smc']} and "
            f"rst_primary_ref_clk_no at {flr['assert']['ref']}, both low at every sample until "
            f"the pin released at {pin_high} (cool rise {flr['rise']}); measured release "
            f"smc={rel['smc']} ref={rel['ref']} cycles after the last source ended",
        )

        # CHK-COOLRST-WARM-FOLLOWS
        win = range(flr["set"] + 1, flr["release"]["smc"])
        bad = [t for t in win if self._level(t, "smc") == 0 and self._warm[t] != 0]
        assert not bad, f"warm released at ticks {bad[:8]} while primary asserted"
        warm_assert = self._first_warm(0, flr["set"] + 1)
        assert warm_assert is not None and warm_assert <= flr["assert"]["smc"] + 1, (
            f"warm never asserted with primary: {warm_assert} vs {flr['assert']['smc']}"
        )
        assert run["warm_release"] >= flr["release"]["smc"], (
            f"warm released at {run['warm_release']} before primary at {flr['release']['smc']}"
        )
        self._chk(
            "CHK-COOLRST-WARM-FOLLOWS",
            f"tb_rst_warm_smc_clk_n low at all {sum(1 for t in win if self._level(t, 'smc') == 0)} "
            f"samples with rst_primary_smc_clk_no low; warm asserted at tick {warm_assert}, "
            f"primary smc released at {flr['release']['smc']}, warm released at "
            f"{run['warm_release']} ({run['warm_release'] - flr['release']['smc']} cycles later)",
        )

        # CHK-COOLRST-COLD-STAYS
        stop = max(flr["release"].values())
        count = self._cold_released(flr["set"] + 1, stop)
        control = {
            o: sum(1 for t in range(flr["set"] + 1, stop) if self._level(t, o) == 0)
            for o in OUTPUTS
        }
        assert all(v > 0 for v in control.values()), f"primary never asserted: {control}"
        self._chk(
            "CHK-COOLRST-COLD-STAYS",
            f"{COLD_PROBES[0]} and {COLD_PROBES[1]} deasserted at all {count} samples of "
            f"ticks {flr['set'] + 1}..{stop}; positive control: primary reset asserted at "
            f"smc={control['smc']} ref={control['ref']} of those samples",
        )

        # CHK-COOLRST-RESET-VECTOR
        self._chk(
            "CHK-COOLRST-RESET-VECTOR",
            f"measured CPU_CTRL.RESET_VECTOR[0] low word 0x{pre['vector']:08x} before the "
            f"collision and 0x{post['vector']:08x} after recovery, next to the reset vector "
            f"0x{RESET_VECTOR_RESET:08x}; nothing compared",
        )

        # CHK-COOLRST-ISOLATE-VIS
        vis = post["vis"]
        cool_i = (vis & VIS_COOL_I_BM) >> VIS_COOL_I_BP
        cool_o = (vis & VIS_COOL_O_BM) >> VIS_COOL_O_BP
        pin = (vis & VIS_PIN_BM) >> VIS_PIN_BP
        assert post["cool_ni"] == 1 and post["cool_from_flr"] == 1, (
            f"cool resets not released at the read: ni={post['cool_ni']} "
            f"from_flr={post['cool_from_flr']}"
        )
        assert cool_i == VIS_COOL_I_RESET, f"cool_reset_n_i={cool_i}, vis=0x{vis:08x}"
        assert cool_o == VIS_COOL_O_RESET, f"cool_reset_n_o={cool_o}, vis=0x{vis:08x}"
        self._chk(
            "CHK-COOLRST-ISOLATE-VIS",
            f"ISOLATE_REQ_VIS=0x{vis:08x} after the cool reset with rst_cool_ni={post['cool_ni']} "
            f"and rst_cool_no={post['cool_from_flr']}: cool_reset_n_i={cool_i} and "
            f"cool_reset_n_o={cool_o} equal the RDL reset values {VIS_COOL_I_RESET} and "
            f"{VIS_COOL_O_RESET}; isolate_req_pin={pin} measured, not compared",
        )

        # CHK-COOLRST-CSR-RECOVERY
        assert post["ss_config"] == SS_CONFIG_RESET, f"SS_CONFIG 0x{post['ss_config']:08x}"
        assert post["ss_cold"] == SS_COLD_RESET_N_RESET, f"SS_COLD 0x{post['ss_cold']:08x}"
        assert post["smcen"] == _SMCEN, f"SMCEN 0x{post['smcen']:08x}"
        assert post["delay"] == _P, f"FLR_COUNTER 0x{post['delay']:08x}"
        assert post["hold"] == _H, f"FLR_RESET_COUNTER 0x{post['hold']:08x}"
        self._chk(
            "CHK-COOLRST-CSR-RECOVERY",
            f"before the collision SS_CONFIG=0x{pre['ss_config']:08x} "
            f"SS_COLD_RESET_N=0x{pre['ss_cold']:08x} SMCEN=0x{pre['smcen']:08x} "
            f"FLR_COUNTER=0x{pre['delay']:x} FLR_RESET_COUNTER=0x{pre['hold']:x} read back as "
            f"written; after: SS_CONFIG=0x{post['ss_config']:x} and "
            f"SS_COLD_RESET_N=0x{post['ss_cold']:x} equal their reset values, SMCEN="
            f"0x{post['smcen']:08x} FLR_COUNTER=0x{post['delay']:x} "
            f"FLR_RESET_COUNTER=0x{post['hold']:x} retained",
        )

        # CHK-COOLRST-OTHER-CSR-MEASURED
        self._chk(
            "CHK-COOLRST-OTHER-CSR-MEASURED",
            f"measured I2C0 TIMING0 0x{pre['timing']:08x} before and 0x{post['timing']:08x} after; "
            f"CPU_CTRL SCRATCH[0] 0x{pre['scratch']:08x} before and 0x{post['scratch']:08x} "
            f"after; nothing compared",
        )

        # CHK-COOLRST-LATCH-SET-HOLD
        assert run["latch_pre"] == 0 and run["latch_edge"] == SMC_BIT
        assert post["latch"] == SMC_BIT, f"latch 0x{post['latch']:x} after the cool reset"
        self._chk(
            "CHK-COOLRST-LATCH-SET-HOLD",
            f"ISOLATE_REQ_SMC_REG read 0x{run['latch_pre']:x} before the FLR edge, "
            f"0x{run['latch_edge']:x} after it and 0x{post['latch']:x} after the cool reset "
            f"ended with every reset output released",
        )

        # CHK-COOLRST-LATCH-CLEAR
        self._chk(
            "CHK-COOLRST-LATCH-CLEAR",
            f"ISOLATE_REQ_SMC_REG read 0x{s4['before']:x} before a write of "
            f"0x{_ALL_ONES:08x} with byte strobe 0x{_LOW_LANE:x} and 0x{s4['after']:x} after it",
        )

        # CHK-COOLRST-LATCH-HOLD0
        quiet = [s for s in s5["samples"] if s != (1, 1, 1)]
        assert not quiet, f"reset activity with hold count 0: {quiet[:4]}"
        assert s5["before"] == 0 and s5["after"] == SMC_BIT
        assert s5["cleared"] == 0 and s5["hold_restored"] == _H
        self._chk(
            "CHK-COOLRST-LATCH-HOLD0",
            f"with ISOLATE_REQ_FLR_RESET_COUNTER_VALUE=0 ISOLATE_REQ_SMC_REG read "
            f"0x{s5['before']:x} before the FLR edge and 0x{s5['after']:x} after it; "
            f"rst_primary_smc_clk_no, rst_primary_ref_clk_no and rst_cool_no stayed released at "
            f"all {len(s5['samples'])} samples of ticks {s5['window'][0] + 1}..{s5['window'][1]}; "
            f"latch cleared to 0x{s5['cleared']:x} and hold counter restored to "
            f"0x{s5['hold_restored']:x}",
        )

        drive_isolate_pin(dut, None)
        iso = [self._iso[t] for t in range(flr["set"] + 1, stop + 1)]
        cocotb.log.info(
            "measured: S2 FLR set=%d fall=%d rise=%d pin low=%d high=%d assert=%s release=%s "
            "warm_release=%d; tb_isolate_req_o over the collision min=0x%x max=0x%x",
            flr["set"],
            flr["fall"],
            flr["rise"],
            pin_low,
            pin_high,
            flr["assert"],
            flr["release"],
            run["warm_release"],
            min(iso),
            max(iso),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; cool_fall=%d cool_rise=%d release=%d "
            "warm=%d ref latch_polls=%d s5_watch=%d enforced-by=this sequence "
            "fail-on-expiry=AssertionError with the last sampled levels and register values",
            len(self._waits),
            " ".join(self._waits),
            _FALL_BOUND,
            _RISE_BOUND,
            _RELEASE_BOUND,
            _WARM_BOUND,
            _LATCH_POLLS,
            _S5_BOUND,
        )
        self._assert_fence()
        self.recovery_ok = True

    def _first_warm(self, level: int, start: int) -> int | None:
        for tick in range(start, self._tick_no + 1):
            if self._warm[tick] == level:
                return tick
        return None
