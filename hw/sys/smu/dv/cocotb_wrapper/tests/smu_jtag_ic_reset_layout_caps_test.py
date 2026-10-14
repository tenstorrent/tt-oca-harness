# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_jtag_ic_reset_layout_caps_test - IC_RESET TDR layout and JTAG_CAPS readback.

Sources: hw/ip/jtag/jtag_ptap/doc/architecture.adoc (IC_RESET Support, JTAG Capabilities),
doc/integrator/src/smu-composition.adoc (IC_RESET TDR Structure, JTAG Configuration
Parameters, Cross Trigger Parameters), hw/sys/dtp/doc/clk_rst.adoc, hw/sys/dtp/doc/overview.adoc

IC_RESET TDR: 2 * (68 SMC + 8 SEP + 1 external) + 1 = 155 bits. From TDI to TDO the slices are
SMC, SEP, external, then the single reset_hold bit (bit 0). Port n occupies bit 2n + 1
(reset_enable, nearer TDO) and bit 2n + 2 (reset_control, nearer TDI). Port numbering derived
from the declaration order of the two documents: port 0 = external; SEP ports 1..8 =
km_jtag_rst_n, otbn_jtag_rst_n, aes_jtag_rst_n, hmac_jtag_rst_n, kmac_jtag_rst_n, sep_reset_n,
trng_jtag_rst_n, abr_jtag_rst_n; SMC ports 9..76 = fuse_reset_n, warm_reset_n, cool_reset_n,
cold_reset_n, ss_cold_reset_n[0..31] = 13..44, ss_warm_reset_n[0..31] = 45..76. The default
external stub has one port, so port 0 and the last external port are the same pair. The index
mapping is not stated by either document.

Only reset_control bits are ever cleared, one at a time, with every reset_enable bit at 1, so no
override is asserted. reset_hold is cleared for one scan in S3 and restored by the next scan. The
slice buses are read hierarchically as passive observation. The default image after power-on
reset and after TRST_n is all ones. A 163-bit marker scan and 61-bit JTAG_CAPS marker scans
measure the DR lengths. The S6 legs pass through Test-Logic-Reset: the power-on reset leg
leaves it by TMS only (no TRST_n pulse) and the TRST_n leg holds TMS high. Both legs start from
an image with reset_hold and one control bit cleared, which only a reset can restore.

JTAG_CAPS expected value: field map from architecture.adoc (JTAG Capabilities) with the default
configuration values of smu-composition.adoc: num_xtrig_ctp 16, num_xtra_stap 1, stap_io_en,
sep_dbg_en and smc_dbg_en 1, num_smc_ic_rst 68, num_sep_ic_rst 8, num_ext_ic_rst 1, every
instruction enable 1, och_ver 8'h00 (JTAG_OCH_VER). num_xtrig_int_ct is the SMU-exposed 8 or
8 plus the 2 SMC-reserved lanes (dtp overview.adoc: the first two lanes connect to the SMC DFD
CLA); the owner has not fixed num_xtrig_int_ct, so bits 59:54 are accepted in {8, 10} and
excluded from the exact compare.

Scan budget: 33 IC_RESET scans (S1 1, S2 2, S3 7, S4 2, S5 11, S6 6, S7 3, final verify 1) and
5 JTAG_CAPS scans (S8 1, S9 4). Samples are taken 16 clk_smu_i cycles after each Update-DR.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState
from seq_lib.smu_compose_helpers import hier
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_IC_RESET,
    DTP_IR_JTAG_CAPS,
    DTP_IR_WIDTH,
    DTP_JTAG_CAPS_LEN,
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_EXT_PORT,
    SMU_IC_RESET_LEN,
    SMU_IC_RESET_NUM_SEP_PORTS,
    SMU_IC_RESET_NUM_SMC_PORTS,
    SMU_IC_RESET_SMC_COLD_PORT,
    SMU_IC_RESET_SMC_COOL_PORT,
    SMU_IC_RESET_SMC_FUSE_PORT,
    SMU_IC_RESET_SMC_SS_COLD0_PORT,
    SMU_IC_RESET_SMC_SS_WARM0_PORT,
    SMU_IC_RESET_SMC_WARM_PORT,
    ic_reset_control_bit,
    ic_reset_enable_bit,
    make_smu_jtag_tap,
    read_smc_reset_ctrl_bit,
    require_jtag_tdo_resolved,
    smc_reset_ctrl_packed_bit,
)
from seq_lib.smu_tb_pins import smu_scope
from smu_base_test import smu_base_test


def _check_tdr_layout() -> None:
    """The IC_RESET TDR shape this leaf assumes; SMU_IC_RESET_NUM_SEP_PORTS is resolved from
    the elaborated top, so this runs inside the simulation, not at import."""
    assert SMU_IC_RESET_LEN == 155
    assert SMU_IC_RESET_NUM_SMC_PORTS == 68
    assert SMU_IC_RESET_NUM_SEP_PORTS == 8
    assert SMU_IC_RESET_EXT_PORT == 0
    assert SMU_IC_RESET_SMC_FUSE_PORT == 9
    assert SMU_IC_RESET_SMC_WARM_PORT == 10
    assert SMU_IC_RESET_SMC_COOL_PORT == 11
    assert SMU_IC_RESET_SMC_COLD_PORT == 12
    assert SMU_IC_RESET_SMC_SS_COLD0_PORT == 13
    assert SMU_IC_RESET_SMC_SS_WARM0_PORT == 45
    assert (SMU_IC_RESET_SMC_SS_COLD0_PORT + 31, SMU_IC_RESET_SMC_SS_WARM0_PORT + 31) == (44, 76)
    assert ic_reset_enable_bit(5) == 11 and ic_reset_control_bit(5) == 12
    assert DTP_JTAG_CAPS_LEN == 60
    assert DTP_IR_JTAG_CAPS == 0x19
    assert smc_reset_ctrl_packed_bit("fuse_reset_n_val") == 0


SAMPLE_AFTER_UPDATE_SMU_CYCLES = 16
BOUND_TCK = 2000
BOUND_REF = 2000
TRST_CYCLES = 8
N_SMC = SMU_IC_RESET_NUM_SMC_PORTS
N_SEP = SMU_IC_RESET_NUM_SEP_PORTS
SMC_ALL = (1 << N_SMC) - 1
SEP_ALL = (1 << N_SEP) - 1
D = SMU_IC_RESET_DEFAULT
MARKER_LEN = SMU_IC_RESET_LEN + 8
EXPECTED_TIMEOUT_PATHS = 6
STEP_ORDER = [f"S{i}" for i in range(1, 10)]

PORT_EXT = SMU_IC_RESET_EXT_PORT
PORT_KM = 1
PORT_ABR = 8
PORT_FUSE = SMU_IC_RESET_SMC_FUSE_PORT
PORT_WARM = SMU_IC_RESET_SMC_WARM_PORT
PORT_COOL = SMU_IC_RESET_SMC_COOL_PORT
PORT_COLD = SMU_IC_RESET_SMC_COLD_PORT
PORT_SS_COLD0 = SMU_IC_RESET_SMC_SS_COLD0_PORT
PORT_SS_WARM0 = SMU_IC_RESET_SMC_SS_WARM0_PORT
PORT_SS_COLD31 = PORT_SS_COLD0 + 31
PORT_SS_WARM31 = PORT_SS_WARM0 + 31

# (name, port, SMC leaf field, SMC vector index)
NAMED_PORTS = [
    ("ss_warm_reset_n[31]", PORT_SS_WARM31, "ss_warm_reset_n", 31),
    ("ss_warm_reset_n[0]", PORT_SS_WARM0, "ss_warm_reset_n", 0),
    ("ss_cold_reset_n[31]", PORT_SS_COLD31, "ss_cold_reset_n", 31),
    ("ss_cold_reset_n[0]", PORT_SS_COLD0, "ss_cold_reset_n", 0),
    ("cold_reset_n", PORT_COLD, "cold_reset_n", None),
    ("cool_reset_n", PORT_COOL, "cool_reset_n", None),
    ("warm_reset_n", PORT_WARM, "warm_reset_n", None),
    ("fuse_reset_n", PORT_FUSE, "fuse_reset_n", None),
    ("abr_jtag_rst_n", PORT_ABR, None, None),
    ("km_jtag_rst_n", PORT_KM, None, None),
]


def img_ctrl0(port: int) -> int:
    """Default image with only the reset_control bit of `port` cleared."""
    return D & ~(1 << ic_reset_control_bit(port))


def hier_expect(port: int | None) -> tuple[int, int, int, int]:
    """(smc ovrd, smc val, sep ovrd, sep val) with only `port`'s control bit cleared.

    SMC port p is bit p - 9 of the SMC val half (fuse first); SEP port p is bit p - 1 of the SEP
    val half (km_jtag_rst_n first). Port 0 and None leave both slices all ones.
    """
    smc_val, sep_val = SMC_ALL, SEP_ALL
    if port is not None and port >= PORT_FUSE:
        smc_val &= ~(1 << (port - PORT_FUSE))
    elif port is not None and port >= PORT_KM:
        sep_val &= ~(1 << (port - PORT_KM))
    return (0, smc_val, 0, sep_val)


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


def _slices(dut) -> tuple[int, int, int, int]:
    """(smc ovrd half, smc val half, sep ovrd half, sep val half) of the IC_RESET slices."""
    smu = smu_scope(dut)
    smc_slice = hier(smu, "jtag_smc_reset_ctrl")
    sep_slice = hier(smu, "jtag_sep_reset_ctrl")
    widths = (len(smc_slice), len(sep_slice))
    if widths != (2 * N_SMC, 2 * N_SEP):
        raise AssertionError(f"IC_RESET slice widths {widths} do not match the TDR geometry")
    smc = _sample(smc_slice, "jtag_smc_reset_ctrl")
    sep = _sample(sep_slice, "jtag_sep_reset_ctrl")
    return (smc >> N_SMC, smc & SMC_ALL, sep >> N_SEP, sep & SEP_ALL)


def _caps_expected() -> int:
    """JTAG_CAPS default configuration with bits 59:54 (num_xtrig_int_ct) left zero."""
    return (
        (16 << 48)
        | (1 << 44)
        | (1 << 43)
        | (1 << 42)
        | (1 << 41)
        | (N_SMC << 33)
        | (N_SEP << 25)
        | (1 << 17)
        | (0x1FF << 8)
        | 0x00
    )


CAPS_MASK = (1 << 54) - 1
CAPS_FIELDS = [
    ("num_xtrig_int_ct", 54, 6),
    ("num_xtrig_ctp", 48, 6),
    ("num_xtra_stap", 44, 4),
    ("stap_io_en", 43, 1),
    ("sep_dbg_en", 42, 1),
    ("smc_dbg_en", 41, 1),
    ("num_smc_ic_rst", 33, 8),
    ("num_sep_ic_rst", 25, 8),
    ("num_ext_ic_rst", 17, 8),
    ("ic_rst_inst_en", 16, 1),
    ("tmp_inst_en", 15, 1),
    ("runbist_inst_en", 14, 1),
    ("highz_inst_en", 13, 1),
    ("clamp_inst_en", 12, 1),
    ("intest_inst_en", 11, 1),
    ("extest_pulse_en", 10, 1),
    ("extest_train_en", 9, 1),
    ("bsr_inst_en", 8, 1),
    ("och_ver", 0, 8),
]


@pyuvm.test()
class smu_jtag_ic_reset_layout_caps_test(smu_base_test):
    """IC_RESET TDR length, slice order, port positions and JTAG_CAPS default readback."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        _check_tdr_layout()
        dut = cocotb.top
        sb = self.env.scoreboard
        self.timeout_paths: list[str] = []
        self.steps: list[str] = []
        self.scans = 0
        self.cur = D

        await self.cfg.reset_done.wait()
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()

        # S1 SETUP
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await self._confirm_state(jtag, OcahJtagState.RUN_TEST_IDLE, "s1_rti")
        await self._check_idcode(jtag, "S1")
        readback_ok, slices, ports = await self._chain(jtag, dut, D, "S1 read")
        self.logger.info(
            "S1 default readback_ok=%s slices=%s (ovrd, ctrl_n)=%s", readback_ok, slices, ports
        )
        assert readback_ok, "S1 IC_RESET default readback is not all ones"
        assert slices == hier_expect(None), f"S1 slices {slices}"
        assert ports == (0, 1), f"S1 ports {ports}"
        self._step("S1")

        # S2 ICLAY_IC_LEN
        stream = await self._marker_ic_reset(jtag, dut)
        bits = [(stream >> i) & 1 for i in range(MARKER_LEN)]
        first_zero = bits.index(0) if 0 in bits else -1
        tail = bits[SMU_IC_RESET_LEN:]
        rb_ok, slices, ports = await self._chain(jtag, dut, D, "S2 read")
        self.logger.info(
            "S2 marker first_zero=%d tail(155..162)=%s readback_ok=%s ports=%s",
            first_zero,
            tail,
            rb_ok,
            ports,
        )
        sb.expect_eq(
            "163-bit marker emerges after exactly 155 TCKs, default image restored",
            (first_zero, tail, rb_ok, ports),
            (SMU_IC_RESET_LEN, [0] + [1] * 7, True, (0, 1)),
            evidence="ICLAY_IC_LEN",
        )
        self._step("S2")

        # S3 ICLAY_IC_SLICE
        cells = [
            ("smc-first ss_warm_reset_n[31] bit 154", PORT_SS_WARM31, img_ctrl0(PORT_SS_WARM31)),
            ("sep-after-smc fuse_reset_n bit 20", PORT_FUSE, img_ctrl0(PORT_FUSE)),
            ("sep abr_jtag_rst_n bit 18", PORT_ABR, img_ctrl0(PORT_ABR)),
            ("ext-after-sep km_jtag_rst_n bit 4", PORT_KM, img_ctrl0(PORT_KM)),
            ("external bit 2", PORT_EXT, img_ctrl0(PORT_EXT)),
            ("hold-nearest-tdo bit 0", None, D & ~1),
        ]
        assert ic_reset_control_bit(PORT_SS_WARM31) == 154
        assert ic_reset_control_bit(PORT_FUSE) == 20
        assert ic_reset_control_bit(PORT_ABR) == 18
        assert ic_reset_control_bit(PORT_KM) == 4
        assert ic_reset_control_bit(PORT_EXT) == 2
        got, want = [], []
        prev_image = D
        for label, port, image in cells:
            rb_ok, slices, ports = await self._chain(jtag, dut, image, f"S3 {label}")
            ctrl_n = 0 if port == PORT_EXT else 1
            got.append((label, rb_ok, slices, ports))
            want.append((label, True, hier_expect(port), (0, ctrl_n)))
            self.logger.info("S3 %s readback_ok=%s slices=%s ports=%s", label, rb_ok, slices, ports)
            prev_image = image
        assert prev_image == D & ~1
        rb_ok, slices, ports = await self._chain(jtag, dut, D, "S3 restore")
        got.append(("restore", rb_ok, slices, ports))
        want.append(("restore", True, hier_expect(None), (0, 1)))
        sb.expect_eq(
            "one cleared control bit per slice boundary lands at its documented position",
            got,
            want,
            evidence="ICLAY_IC_SLICE",
        )
        self._step("S3")

        # S4 ICLAY_IC_PAIR
        pair_img = img_ctrl0(PORT_EXT)
        assert (pair_img >> 1) & 1 == 1 and (pair_img >> 2) & 1 == 0
        rb_a, slices_a, ports_a = await self._chain(jtag, dut, pair_img, "S4 write")
        rb_b, slices_b, ports_b = await self._chain(jtag, dut, D, "S4 restore")
        self.logger.info(
            "S4 control=bit 2 (nearer TDI), enable=bit 1 (nearer TDO): write ports=%s "
            "slices=%s restore ports=%s readback_ok=%s",
            ports_a,
            slices_a,
            ports_b,
            rb_b,
        )
        sb.expect_eq(
            "external port 0 control bit 2 drives val without override; enable is bit 1",
            (rb_a, ports_a, slices_a, rb_b, ports_b, slices_b),
            (True, (0, 0), hier_expect(None), True, (0, 1), hier_expect(None)),
            evidence="ICLAY_IC_PAIR",
        )
        self._step("S4")

        # S5 ICLAY_IC_NAMED
        got, want = [], []
        for name, port, field, idx in NAMED_PORTS:
            rb_ok, slices, ports = await self._chain(jtag, dut, img_ctrl0(port), f"S5 {name}")
            leaf = None if field is None else read_smc_reset_ctrl_bit(dut, f"{field}_val", idx)
            got.append((name, rb_ok, slices, leaf, ports))
            want.append((name, True, hier_expect(port), None if field is None else 0, (0, 1)))
            self.logger.info(
                "S5 %s port=%d bit=%d readback_ok=%s slices=%s leaf=%s ports=%s",
                name,
                port,
                ic_reset_control_bit(port),
                rb_ok,
                slices,
                leaf,
                ports,
            )
        rb_ok, slices, ports = await self._chain(jtag, dut, D, "S5 restore")
        got.append(("restore", rb_ok, slices, None, ports))
        want.append(("restore", True, hier_expect(None), None, (0, 1)))
        sb.expect_eq(
            "ten named ports at the TDR positions the integrator order rules give",
            got,
            want,
            evidence="ICLAY_IC_NAMED",
        )
        self._step("S5")

        # S6 ICLAY_IC_IMG
        img12 = img_ctrl0(PORT_COLD) & ~1
        assert img12 == D & ~1 & ~(1 << 26)
        rb0, _, _ = await self._chain(jtag, dut, img12, "S6 pre-POR write")
        rb1, pre_slices1, pre_ports1 = await self._chain(jtag, dut, img12, "S6 pre-POR confirm")
        await self._power_on_reset(jtag, dut)
        self.cur = D
        por_ok, por_slices, por_ports = await self._chain(jtag, dut, D, "S6 post-POR read")
        await self._check_idcode(jtag, "S6 POR")
        rb2, _, _ = await self._chain(jtag, dut, img12, "S6 pre-TRST write")
        rb3, pre_slices3, pre_ports3 = await self._chain(jtag, dut, img12, "S6 pre-TRST confirm")
        await jtag.assert_trst(tck_cycles=TRST_CYCLES, tms=1)
        await jtag.release_trst()
        await self._wait_tap_ref(dut, OcahJtagState.TEST_LOGIC_RESET, "s6_trst_tlr")
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        self.cur = D
        trst_ok, trst_slices, trst_ports = await self._chain(jtag, dut, D, "S6 post-TRST read")
        self.logger.info(
            "S6 pre-state readbacks=%s post-POR ok=%s slices=%s ports=%s post-TRST ok=%s "
            "slices=%s ports=%s",
            (rb0, rb1, rb2, rb3),
            por_ok,
            por_slices,
            por_ports,
            trst_ok,
            trst_slices,
            trst_ports,
        )
        sb.expect_eq(
            "pre-state non-default, then all 155 bits read 1 after power-on reset and TRST_n",
            (
                rb0,
                rb1,
                rb2,
                rb3,
                pre_slices1,
                pre_ports1,
                pre_slices3,
                pre_ports3,
                por_ok,
                por_slices,
                por_ports,
                trst_ok,
                trst_slices,
                trst_ports,
            ),
            (
                True,
                True,
                True,
                True,
                hier_expect(PORT_COLD),
                (0, 1),
                hier_expect(PORT_COLD),
                (0, 1),
                True,
                hier_expect(None),
                (0, 1),
                True,
                hier_expect(None),
                (0, 1),
            ),
            evidence="ICLAY_IC_IMG",
        )
        self._step("S6")

        # S7 ICLAY_IC_RECAP
        img10 = img_ctrl0(PORT_WARM)
        moved = [0]
        samples = [0]

        async def watch_ports() -> None:
            while True:
                await RisingEdge(dut.jtag_tck)
                samples[0] += 1
                ovrd, ctrl_n = dut.jtag_ic_reset_ext_ovrd.value, dut.jtag_ic_reset_ext_ctrl_n.value
                if not (ovrd.is_resolvable and ctrl_n.is_resolvable):
                    moved[0] += 1
                elif (int(ovrd), int(ctrl_n)) != (0, 1):
                    moved[0] += 1

        port_watcher = cocotb.start_soon(watch_ports())
        try:
            pre_ok, pre_slices, pre_ports = await self._chain(jtag, dut, img10, "S7 write")
            ok1, slices1, ports1 = await self._chain(jtag, dut, img10, "S7 read1")
            ok2, slices2, ports2 = await self._chain(jtag, dut, D, "S7 read2")
        finally:
            port_watcher.cancel()
        assert samples[0] > 0, "S7 port watcher took no samples"
        self.logger.info(
            "S7 compare is read1 == read2 == written image; ok=%s slices1=%s slices2=%s",
            (pre_ok, ok1, ok2),
            slices1,
            slices2,
        )
        self.logger.info("S7 port samples=%d moved=%d", samples[0], moved[0])
        sb.expect_eq(
            "recapture returns the written image and no output moves across the rewrite",
            (pre_ok, ok1, ok2, pre_slices, slices1, pre_ports, ports1, ports2, moved[0]),
            (
                True,
                True,
                True,
                hier_expect(PORT_WARM),
                hier_expect(PORT_WARM),
                (0, 1),
                (0, 1),
                (0, 1),
                0,
            ),
            evidence="ICLAY_IC_RECAP",
        )
        self._step("S7")

        # S8 ICLAY_CAPS_DEF
        caps = await self._watched(
            jtag, dut, "S8 JTAG_CAPS", DTP_JTAG_CAPS_LEN, lambda: jtag.read("JTAG_CAPS")
        )
        for name, lsb, width in CAPS_FIELDS:
            self.logger.info("S8 JTAG_CAPS.%s = %d", name, (caps >> lsb) & ((1 << width) - 1))
        int_ct = (caps >> 54) & 0x3F
        self.logger.info("S8 num_xtrig_int_ct observed %d, accepted {8, 10}", int_ct)
        sb.expect_eq(
            "JTAG_CAPS default configuration, num_xtrig_int_ct in {8, 10}",
            (caps & CAPS_MASK, int_ct in (8, 10)),
            (_caps_expected() & CAPS_MASK, True),
            evidence="ICLAY_CAPS_DEF",
        )
        self._step("S8")

        # S9 ICLAY_CAPS_RO
        ones = await self._watched(
            jtag,
            dut,
            "S9 ones",
            DTP_JTAG_CAPS_LEN,
            lambda: jtag.read("JTAG_CAPS", shift_value=(1 << DTP_JTAG_CAPS_LEN) - 1),
        )
        zeros = await self._watched(
            jtag,
            dut,
            "S9 zeros",
            DTP_JTAG_CAPS_LEN,
            lambda: jtag.read("JTAG_CAPS", shift_value=0),
        )
        mark1 = await self._marker_caps(jtag, dut, 1, "S9 marker1")
        mark0 = await self._marker_caps(jtag, dut, (1 << 61) - 2, "S9 marker0")
        low = (1 << DTP_JTAG_CAPS_LEN) - 1
        self.logger.info(
            "S9 shift-in ones=0x%x zeros=0x%x marker1=0x%x marker0=0x%x", ones, zeros, mark1, mark0
        )
        sb.expect_eq(
            "JTAG_CAPS ignores shifted-in bits and is exactly 60 bits",
            (ones, zeros, mark1 & low, mark1 >> 60, mark0 & low, mark0 >> 60),
            (caps, caps, caps, 1, caps, 0),
            evidence="ICLAY_CAPS_RO",
        )
        self._step("S9")

        # S10 CHK-TIMEOUT-PATHS
        final_ok, final_slices, final_ports = await self._chain(jtag, dut, D, "final verify")
        assert final_ok and final_slices == hier_expect(None) and final_ports == (0, 1)
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
        self.logger.info("IC_RESET scans: %d", self.scans)
        self.logger.info("CHK-NONVAC: PASS (ordered fence S1<S2<...<S9<PASS)")

    def _step(self, step_id: str) -> None:
        self.steps.append(step_id)
        self.logger.info("STEP %s done", step_id)

    def _record(self, label: str, bound: int, last: str) -> None:
        self.timeout_paths.append(f"{label}: bound={bound} ok last={last}")

    async def _chain(self, jtag, dut, image: int, where: str):
        """Read IC_RESET leaving `image`; return (readback == previous image, slices, ports)."""
        self.scans += 1
        readback = await self._watched(
            jtag,
            dut,
            where,
            SMU_IC_RESET_LEN,
            lambda: jtag.read("IC_RESET", shift_value=image),
        )
        ok = readback == self.cur
        if not ok:
            self.logger.info("%s readback 0x%x expected 0x%x", where, readback, self.cur)
        self.cur = image
        await ClockCycles(dut.clk_smu_i, SAMPLE_AFTER_UPDATE_SMU_CYCLES)
        return ok, _slices(dut), _ports(dut)

    async def _marker_ic_reset(self, jtag, dut) -> int:
        """163-bit scan, a 0 first then ones; returns the TDO stream."""
        self.scans += 1

        async def op() -> int:
            await jtag.shift_ir(DTP_IR_IC_RESET, width=DTP_IR_WIDTH, back_to_rti=False)
            return await jtag.shift_dr((1 << MARKER_LEN) - 2, MARKER_LEN, back_to_rti=True)

        return await self._watched(jtag, dut, "S2 marker", MARKER_LEN, op)

    async def _marker_caps(self, jtag, dut, value: int, where: str) -> int:
        async def op() -> int:
            await jtag.shift_ir(DTP_IR_JTAG_CAPS, width=DTP_IR_WIDTH, back_to_rti=False)
            return await jtag.shift_dr(value, DTP_JTAG_CAPS_LEN + 1, back_to_rti=True)

        return await self._watched(jtag, dut, where, DTP_JTAG_CAPS_LEN + 1, op)

    async def _watched(self, jtag, dut, where: str, min_dr: int, op) -> int:
        """Run a scan; fail on X/Z TDO while driven or on fewer than `min_dr` Shift-DR bits."""
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
            result = await op()
        finally:
            watcher.cancel()
        require_jtag_tdo_resolved(where)
        if bad:
            raise AssertionError(f"X/Z on TDO during {where}: {bad[:8]}")
        if dr_driven[0] < min_dr:
            raise AssertionError(f"{where}: {dr_driven[0]} driven Shift-DR TDO bits, need {min_dr}")
        return int(result)

    async def _check_idcode(self, jtag, where: str) -> None:
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(
                f"{where} IDCODE got=0x{idcode:08x} expect=0x{DTP_DEFAULT_IDCODE:08x}"
            )

    async def _power_on_reset(self, jtag, dut) -> None:
        assert _sample(dut.jtag_trst, "jtag_trst") == 1, "S6 requires TRST_n released"
        dut.powergood_i.value = 0
        await self._wait_tap_ref(dut, OcahJtagState.TEST_LOGIC_RESET, "s6_por_tlr")
        dut.powergood_i.value = 1
        await self._wait_high(dut, dut.obs_powergood_stable_o, dut.clk_ref_i, "s6_pg_stable")
        await self._wait_high(dut, dut.rst_cold_n_o, dut.clk_ref_i, "s6_cold_n")
        await self._wait_high(dut, dut.rst_primary_smc_clk_n_o, dut.clk_smu_i, "s6_smc_n")
        jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)

    async def _confirm_state(self, jtag, expect: OcahJtagState, label: str) -> None:
        last = None
        for _ in range(BOUND_TCK):
            last = _sample(cocotb.top.jtag_ptap_state, "jtag_ptap_state")
            if last == int(expect):
                self._record(label, BOUND_TCK, f"0x{last:x}")
                return
            await jtag.step_tms(0)
        self.timeout_paths.append(f"{label}: bound={BOUND_TCK} EXPIRED last=0x{last:x}")
        raise AssertionError(
            f"TIMEOUT {label}: bound={BOUND_TCK} last_state=0x{last:x} expect={expect.name}"
        )

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

    async def _wait_high(self, dut, signal, clk, label: str) -> None:
        last = None
        for _ in range(BOUND_REF):
            await RisingEdge(clk)
            last = signal.value
            if last.is_resolvable and int(last) == 1:
                self._record(label, BOUND_REF, "1")
                return
        self.timeout_paths.append(f"{label}: bound={BOUND_REF} EXPIRED last={last}")
        raise AssertionError(f"TIMEOUT {label}: bound={BOUND_REF} last={last}")
