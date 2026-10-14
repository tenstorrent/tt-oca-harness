# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_jtag_ic_reset_ext_override_test - IC_RESET external port and reset_hold gating.

Sources: hw/ip/jtag/jtag_ptap/doc/architecture.adoc (IC_RESET Support),
hw/sys/dtp/doc/clk_rst.adoc (IC_RESET Overrides), doc/programmer/src/dtp-programming.adoc,
doc/integrator/src/smu-composition.adoc

The IC_RESET TDR bit positions come from architecture.adoc (IC_RESET Support) and
smu-composition.adoc (IC_RESET TDR Structure): the TDR is 155 bits, the external port is port 0,
reset_hold is bit 0, reset_enable (active low) is bit 1 and reset_control is bit 2. The external
output follows `.ovrd = !reset_enable` and `.val = reset_control`. reset_hold = 1 lets
Test-Logic-Reset restore every bit to 1; reset_hold = 0 keeps the enable and control bits across
Test-Logic-Reset; TRST_n and power-on reset restore every bit including reset_hold.

Every image keeps the SMC and SEP slice bits [154:3] at 1, so only bits 0, 1 and 2 move. The
ports `jtag_ic_reset_ext_ovrd` and `jtag_ic_reset_ext_ctrl_n` are sampled 16 clk_smu_i cycles
after each Update-DR. Test-Logic-Reset is reached with TMS high only: the driver's reset_tap()
also pulses TRST_n, which would clear reset_hold-protected bits. The scenario runs 39 IC_RESET
scans. Edge timing is avoided by the sample point; the transient pulse when enable
and control change together is logged and not compared.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_IC_RESET,
    DTP_IR_WIDTH,
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_EXT_PORT,
    SMU_IC_RESET_LEN,
    ic_reset_control_bit,
    ic_reset_enable_bit,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from smu_base_test import smu_base_test


def _check_tdr_layout() -> None:
    """The IC_RESET TDR shape this leaf assumes; SMU_IC_RESET_NUM_SEP_PORTS is resolved from
    the elaborated top, so this runs inside the simulation, not at import."""
    assert SMU_IC_RESET_LEN == 155
    assert ic_reset_enable_bit(SMU_IC_RESET_EXT_PORT) == 1
    assert ic_reset_control_bit(SMU_IC_RESET_EXT_PORT) == 2


ENABLE_BIT = ic_reset_enable_bit(SMU_IC_RESET_EXT_PORT)
CONTROL_BIT = ic_reset_control_bit(SMU_IC_RESET_EXT_PORT)
HOLD_BIT = 0
SAMPLE_AFTER_UPDATE_SMU_CYCLES = 16
BOUND_TCK = 2000
BOUND_REF = 2000
BOUND_SMU_WINDOW = 64
TRST_CYCLES = 8
MAX_IC_RESET_SCANS = 45
EXPECTED_TIMEOUT_PATHS = 13
STEP_ORDER = [f"S{i}" for i in range(1, 13)]


def img(enable: int, control: int, hold: int) -> int:
    """IC_RESET image: all ones except the external port bits and reset_hold as given."""
    value = SMU_IC_RESET_DEFAULT
    for bit, level in ((ENABLE_BIT, enable), (CONTROL_BIT, control), (HOLD_BIT, hold)):
        value = (value & ~(1 << bit)) | (level << bit)
    return value


def _sample(signal, name: str) -> int:
    val = signal.value
    if isinstance(val, int):
        return val
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


def _ports(dut) -> tuple[int, int]:
    """(ovrd, ctrl_n) of the external reset override."""
    return (
        _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
        _sample(dut.jtag_ic_reset_ext_ctrl_n, "jtag_ic_reset_ext_ctrl_n"),
    )


@pyuvm.test()
class smu_jtag_ic_reset_ext_override_test(smu_base_test):
    """IC_RESET external override follows Update-DR; reset_hold gates Test-Logic-Reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        _check_tdr_layout()
        dut = cocotb.top
        sb = self.env.scoreboard
        self.timeout_paths: list[str] = []
        self.steps: list[str] = []
        self.scans = 0

        await self.cfg.reset_done.wait()
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()

        # S1 SETUP
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await self._confirm_state(jtag, OcahJtagState.RUN_TEST_IDLE, "s1_rti", hold_tms=0)
        await self._check_idcode(jtag, "S1")
        base = _ports(dut)
        self.logger.info("S1 baseline (ovrd, ctrl_n)=%s", base)
        sb.expect_eq("S1 baseline (ovrd, ctrl_n)", base, (0, 1))
        self._step("S1")

        # S2 ICEXT_EXT_ON
        await self._write(jtag, img(0, 0, 1))
        on_low = await self._sampled(dut)
        await self._write(jtag, img(0, 1, 1))
        on_high = await self._sampled(dut)
        await self._write(jtag, img(1, 1, 1))
        cleared = (await self._sampled(dut))[0]
        self.logger.info(
            "S2 (ovrd, ctrl_n) enable=0: %s %s; cleared ovrd=%d", on_low, on_high, cleared
        )
        sb.expect_eq(
            "ext override on follows reset_control, cleared by reset_enable=1",
            (on_low, on_high, cleared),
            ((1, 0), (1, 1), 0),
            evidence="ICEXT_EXT_ON",
        )
        self._step("S2")

        # S3 ICEXT_EXT_OFF
        await self._write(jtag, img(1, 0, 1))
        off_low = await self._sampled(dut)
        await self._write(jtag, img(1, 1, 1))
        off_high = await self._sampled(dut)
        self.logger.info(
            "S3 (ovrd, ctrl_n) enable=1: %s %s; the upstream reset passing through is not "
            "observable at the SMU boundary beyond ovrd == 0",
            off_low,
            off_high,
        )
        sb.expect_eq(
            "ext override off, ctrl_n follows reset_control",
            (off_low, off_high),
            ((0, 0), (0, 1)),
            evidence="ICEXT_EXT_OFF",
        )
        self._step("S3")

        # S4 ICEXT_EXT_INDEP
        walk = []
        want = []
        for background, image in (
            (None, img(0, 1, 1)),
            (None, img(1, 0, 1)),
            (img(0, 0, 1), img(1, 0, 1)),
            (None, img(0, 1, 1)),
        ):
            if background is not None:
                await self._write(jtag, background)
            await self._write(jtag, image)
            ports = await self._sampled(dut)
            readback = await self._read(jtag, dut, image, "S4 readback")
            enable = (image >> ENABLE_BIT) & 1
            control = (image >> CONTROL_BIT) & 1
            walk.append((readback == image, ports))
            want.append((True, (1 - enable, control)))
        await self._write(jtag, img(1, 1, 1))
        self.logger.info(
            "S4 walk (readback == written, (ovrd, ctrl_n)): %s; the default stub has one "
            "external port, so the walk covers that port's two bits and every other TDR bit "
            "must read back unchanged",
            walk,
        )
        sb.expect_eq(
            "single 0 and single 1 walk over the external port bits",
            walk,
            want,
            evidence="ICEXT_EXT_INDEP",
        )
        self._step("S4")

        # S5 ICEXT_EXT_2STEP
        await self._write(jtag, img(1, 0, 1))
        step1 = await self._sampled(dut)
        await self._write(jtag, img(0, 0, 1))
        step2 = await self._sampled(dut)
        await self._write(jtag, img(1, 1, 1))
        sb.expect_eq(
            "control first moves val only, enable second moves ovrd only",
            (step1, step2),
            ((0, 0), (1, 0)),
            evidence="ICEXT_EXT_2STEP",
        )
        self._step("S5")

        # S6 ICEXT_EXT_BOTH
        settled_on, pulses_on, seen_on = await self._both_scan(
            jtag, dut, img(0, 0, 1), "s6_both_on"
        )
        settled_off, pulses_off, seen_off = await self._both_scan(
            jtag, dut, img(1, 1, 1), "s6_both_off"
        )
        self.logger.info(
            "S6 pulse_transitions=%d first=%s last=%s (enable 1->0, control 1->0) "
            "pulse_transitions=%d first=%s last=%s (enable 0->1, control 0->1); "
            "transient pulse not compared",
            pulses_on,
            seen_on[0],
            seen_on[-1],
            pulses_off,
            seen_off[0],
            seen_off[-1],
        )
        sb.expect_eq(
            "enable and control changed together settle to the written values",
            (settled_on, settled_off),
            ((1, 0), (0, 1)),
            evidence="ICEXT_EXT_BOTH",
        )
        self._step("S6")

        # S7 ICEXT_EXT_UPDONLY
        await self._write(jtag, img(1, 0, 1))
        await self._write(jtag, img(0, 0, 1))
        held = await self._sampled(dut)
        samples, moved = await self._scan_without_update(jtag, dut)
        await self._confirm_state(jtag, OcahJtagState.RUN_TEST_IDLE, "s7_rti", hold_tms=0)
        self.logger.info("S7 samples=%d moved=%d held=%s", samples, moved, held)
        assert samples > 0, "S7 watcher took no samples"
        assert held == (1, 0), f"S7 start state {held}"
        sb.expect_eq(
            "outputs never leave (1, 0) across Capture-DR, Shift-DR, Pause-DR and Update-DR",
            moved,
            0,
            evidence="ICEXT_EXT_UPDONLY",
        )
        await self._write(jtag, img(1, 1, 1))
        self._step("S7")

        # S8 ICEXT_HOLD_1
        await self._write(jtag, img(1, 0, 1))
        await self._write(jtag, img(0, 0, 1))
        pre = (await self._sampled(dut))[0]
        await self._tlr(jtag, "s8_tlr")
        after_tlr = await self._sampled(dut)
        readback = await self._read(jtag, dut, SMU_IC_RESET_DEFAULT, "S8 readback")
        after_read = await self._sampled(dut)
        sb.expect_eq(
            "hold=1: Test-Logic-Reset restores every enable and control bit",
            (pre, after_tlr[0], readback == SMU_IC_RESET_DEFAULT, after_read[0]),
            (1, 0, True, 0),
            evidence="ICEXT_HOLD_1",
        )
        self._step("S8")

        # S9 ICEXT_HOLD_0
        await self._write(jtag, img(1, 0, 0))
        await self._write(jtag, img(0, 0, 0))
        pre = await self._sampled(dut)
        await self._tlr(jtag, "s9_tlr")
        after_tlr = await self._sampled(dut)
        readback = await self._read(jtag, dut, img(0, 0, 0), "S9 readback")
        after_read = await self._sampled(dut)
        sb.expect_eq(
            "hold=0: Test-Logic-Reset keeps enable, control and the override",
            (pre, after_tlr, readback == img(0, 0, 0), after_read),
            ((1, 0), (1, 0), True, (1, 0)),
            evidence="ICEXT_HOLD_0",
        )
        self._step("S9")

        # S10 ICEXT_HOLD_TRST
        await jtag.assert_trst(tck_cycles=TRST_CYCLES, tms=1)
        await jtag.release_trst()
        await self._wait_tap_ref(dut, OcahJtagState.TEST_LOGIC_RESET, "s10_trst_tlr")
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        after_trst = await self._sampled(dut)
        readback = await self._read(jtag, dut, SMU_IC_RESET_DEFAULT, "S10 readback")
        sb.expect_eq(
            "TRST_n restores every IC_RESET bit including reset_hold",
            (readback == SMU_IC_RESET_DEFAULT, after_trst[0]),
            (True, 0),
            evidence="ICEXT_HOLD_TRST",
        )
        self._step("S10")

        # S11 ICEXT_HOLD_POR
        await self._write(jtag, img(1, 0, 0))
        await self._write(jtag, img(0, 0, 0))
        pre = await self._sampled(dut)
        assert _sample(dut.jtag_trst, "jtag_trst") == 1, "S11 requires TRST_n released"
        dut.powergood_i.value = 0
        await self._wait_tap_ref(dut, OcahJtagState.TEST_LOGIC_RESET, "s11_por_tlr")
        low_ovrd = _ports(dut)[0]
        self.logger.info("S11 ovrd while powergood is low: %d", low_ovrd)
        dut.powergood_i.value = 1
        await self._wait_high(dut, dut.obs_powergood_stable_o, "s11_pg_stable")
        await self._wait_high(dut, dut.rst_cold_n_o, "s11_cold_n")
        await self._wait_high(dut, dut.rst_primary_smc_clk_n_o, "s11_smc_n")
        assert _sample(dut.jtag_trst, "jtag_trst") == 1, "S11 TRST_n pulsed during the POR leg"
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        before_read = (await self._sampled(dut))[0]
        readback = await self._read(jtag, dut, SMU_IC_RESET_DEFAULT, "S11 readback")
        after_por = await self._sampled(dut)
        await self._check_idcode(jtag, "S11")
        sb.expect_eq(
            "power-on reset restores every IC_RESET bit including reset_hold",
            (pre, low_ovrd, before_read, readback == SMU_IC_RESET_DEFAULT, after_por[0]),
            ((1, 0), 0, 0, True, 0),
            evidence="ICEXT_HOLD_POR",
        )
        self._step("S11")

        # S12 ICEXT_HOLD_SELF
        await self._write(jtag, img(1, 1, 0))
        await self._tlr(jtag, "s12_tlr_hold0")
        rb0 = await self._read(jtag, dut, img(1, 1, 0), "S12 readback hold=0")
        await self._write(jtag, img(1, 1, 1))
        await self._tlr(jtag, "s12_tlr_hold1")
        rb1 = await self._read(jtag, dut, SMU_IC_RESET_DEFAULT, "S12 readback hold=1")
        upper = SMU_IC_RESET_DEFAULT >> 1

        def hold_of(value: int) -> int:
            return (value & 1) if (value >> 1) == upper else -1

        sb.expect_eq(
            "Test-Logic-Reset leaves reset_hold unchanged",
            (hold_of(rb0), hold_of(rb1)),
            (0, 1),
            evidence="ICEXT_HOLD_SELF",
        )
        self._step("S12")

        # S13 CHK-TIMEOUT-PATHS
        for line in self.timeout_paths:
            self.logger.info("TIMEOUT-PATH %s", line)
        assert not any("EXPIRED" in line for line in self.timeout_paths)
        sb.expect_eq(
            "bounded wait sites",
            len(self.timeout_paths),
            EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step("PASS")
        sb.expect_eq(
            "ordered step fence",
            self.steps,
            [*STEP_ORDER, "PASS"],
            evidence="CHK-NONVAC",
        )
        assert self.scans <= MAX_IC_RESET_SCANS, f"{self.scans} IC_RESET scans"
        self.logger.info("IC_RESET scans: %d", self.scans)
        self.logger.info("CHK-NONVAC: PASS (ordered fence S1<S2<...<S12<PASS)")

    def _step(self, step_id: str) -> None:
        self.steps.append(step_id)
        self.logger.info("STEP %s done", step_id)

    def _record(self, label: str, bound: int, last: str) -> None:
        self.timeout_paths.append(f"{label}: bound={bound} ok last={last}")

    async def _sampled(self, dut) -> tuple[int, int]:
        await ClockCycles(dut.clk_smu_i, SAMPLE_AFTER_UPDATE_SMU_CYCLES)
        return _ports(dut)

    async def _write(self, jtag, image: int) -> None:
        self.scans += 1
        await jtag.write("IC_RESET", image)

    async def _read(self, jtag, dut, image: int, where: str) -> int:
        """Read IC_RESET leaving `image` in the register; fail on X/Z TDO while it is driven."""
        self.scans += 1
        bad: list[str] = []
        dr_driven = [0]

        async def watch() -> None:
            while True:
                await RisingEdge(dut.jtag_tck)
                oen = dut.jtag_tdo_oen.value
                tdo = dut.jtag_tdo.value
                if not oen.is_resolvable:
                    bad.append(f"jtag_tdo_oen={oen}")
                elif int(oen):
                    if jtag.get_current_state() is OcahJtagState.SHIFT_DR:
                        dr_driven[0] += 1
                    if not tdo.is_resolvable:
                        bad.append(f"jtag_tdo={tdo}")

        watcher = cocotb.start_soon(watch())
        try:
            readback = await jtag.read("IC_RESET", shift_value=image)
        finally:
            watcher.cancel()
        require_jtag_tdo_resolved(where)
        if bad:
            raise AssertionError(f"X/Z on TDO during {where}: {bad[:8]}")
        if dr_driven[0] < SMU_IC_RESET_LEN:
            raise AssertionError(f"{where}: {dr_driven[0]} driven Shift-DR TDO bits")
        return int(readback)

    async def _check_idcode(self, jtag, where: str) -> None:
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(
                f"{where} IDCODE got=0x{idcode:08x} expect=0x{DTP_DEFAULT_IDCODE:08x}"
            )

    async def _confirm_state(
        self, jtag, expect: OcahJtagState, label: str, *, hold_tms: int
    ) -> None:
        """Bounded TCK wait for the TAP state; hold_tms is driven between samples."""
        last = None
        for _ in range(BOUND_TCK):
            last = _sample(cocotb.top.jtag_ptap_state, "jtag_ptap_state")
            if last == int(expect):
                self._record(label, BOUND_TCK, f"0x{last:x}")
                return
            await jtag.step_tms(hold_tms)
        self.timeout_paths.append(f"{label}: bound={BOUND_TCK} EXPIRED last=0x{last:x}")
        raise AssertionError(
            f"TIMEOUT {label}: bound={BOUND_TCK} last_state=0x{last:x} expect={expect.name}"
        )

    async def _tlr(self, jtag, label: str) -> None:
        """Test-Logic-Reset through TMS high only; TRST_n stays released."""
        for _ in range(5):
            await jtag.step_tms(1)
        await self._confirm_state(jtag, OcahJtagState.TEST_LOGIC_RESET, label, hold_tms=1)

    async def _wait_tap_ref(self, dut, expect: OcahJtagState, label: str) -> None:
        last = None
        for _ in range(BOUND_REF):
            await RisingEdge(dut.clk_ref_i)
            last = _sample(dut.jtag_ptap_state, "jtag_ptap_state")
            if last == int(expect):
                self._record(label, BOUND_REF, f"0x{last:x}")
                return
        self.timeout_paths.append(f"{label}: bound={BOUND_REF} EXPIRED last=0x{last:x}")
        raise AssertionError(
            f"TIMEOUT {label}: bound={BOUND_REF} last_state=0x{last:x} expect={expect.name}"
        )

    async def _wait_high(self, dut, signal, label: str) -> None:
        last = None
        for _ in range(BOUND_REF):
            await RisingEdge(dut.clk_ref_i)
            last = signal.value
            if last.is_resolvable and int(last) == 1:
                self._record(label, BOUND_REF, "1")
                return
        self.timeout_paths.append(f"{label}: bound={BOUND_REF} EXPIRED last={last}")
        raise AssertionError(f"TIMEOUT {label}: bound={BOUND_REF} last={last}")

    async def _window(self, dut, label: str) -> list[tuple[int, int]]:
        """From the next jtag_tck rising edge (Update-DR entry), sample both ports on 64 edges."""
        await RisingEdge(dut.jtag_tck)
        seen = []
        for _ in range(BOUND_SMU_WINDOW):
            await RisingEdge(dut.clk_smu_i)
            seen.append(_ports(dut))
        self._record(label, BOUND_SMU_WINDOW, f"(ovrd, ctrl_n)={seen[-1]}")
        return seen

    async def _both_scan(
        self, jtag, dut, image: int, label: str
    ) -> tuple[tuple[int, int], int, list[tuple[int, int]]]:
        """Shift `image`, open the sample window at the Update-DR edge, return to Run-Test/Idle."""
        self.scans += 1
        await jtag.shift_ir(DTP_IR_IC_RESET, width=DTP_IR_WIDTH, back_to_rti=False)
        await jtag.goto_state(OcahJtagState.SHIFT_DR)
        for bit_idx in range(SMU_IC_RESET_LEN):
            last = bit_idx == SMU_IC_RESET_LEN - 1
            await jtag.step(1 if last else 0, (image >> bit_idx) & 1)
        window = cocotb.start_soon(self._window(dut, label))
        await jtag.step_tms(1)
        await jtag.step_tms(0)
        seen = await window
        return seen[-1], sum(1 for a, b in zip(seen, seen[1:]) if a != b), seen

    async def _scan_without_update(self, jtag, dut) -> tuple[int, int]:
        """Shift a different image and then the original one back, sampling on every TCK."""
        samples = [0]
        moved = [0]

        async def watch() -> None:
            while True:
                await RisingEdge(dut.jtag_tck)
                samples[0] += 1
                if _ports(dut) != (1, 0):
                    moved[0] += 1

        async def shift_image(image: int) -> None:
            for bit_idx in range(SMU_IC_RESET_LEN):
                last = bit_idx == SMU_IC_RESET_LEN - 1
                await jtag.step(1 if last else 0, (image >> bit_idx) & 1)

        watcher = cocotb.start_soon(watch())
        try:
            self.scans += 2
            await jtag.shift_ir(DTP_IR_IC_RESET, width=DTP_IR_WIDTH, back_to_rti=False)
            await jtag.goto_state(OcahJtagState.SHIFT_DR)
            await shift_image(img(1, 1, 1))
            await jtag.step_tms(0)
            await jtag.step_tms(1)
            await jtag.step_tms(0)
            await shift_image(img(0, 0, 1))
            await jtag.step_tms(1)
            await jtag.step_tms(0)
        finally:
            watcher.cancel()
        return samples[0], moved[0]
