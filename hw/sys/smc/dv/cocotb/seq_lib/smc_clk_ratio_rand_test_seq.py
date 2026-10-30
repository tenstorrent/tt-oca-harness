# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN register traffic under a seed-drawn clk_ref_i / clk_smc_i / clk_periph_i triple.

Spec sources: hw/sys/smc/doc/clk_rst.adoc (Clock Architecture, Peripheral Timing
Requirements), the generated register map (smc_reg reset words).

The leaf draws the three periods in build_phase and the bench drives them. The sequence
measures each clock against the drawn period, counts the SMC and peripheral edges across
one ratio-collector window of reference edges, then reads generated reset words on both
sides of the peripheral clock-domain crossing and writes distinct patterns to every UART
scratch register and every I2C target address before any is read back.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import GLOBAL_BASE_RESET, reg_field_encode
from .smc_clk_ratio_test_seq import (
    _I2C_H,
    _UART_SCR_PATTERNS,
    AVS_CFG_0,
    AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT,
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    GLOBAL_BASE,
    I2C_NUM,
    I2C_TARGET_ID_REG_DEFAULT,
    RATIO_WINDOW_EDGES,
    RELATION_WINDOW_REF_EDGES,
    UART_16550_MAIN_LSR_REG_DEFAULT,
    UART_16550_MAIN_SCR_REG_DEFAULT,
    UART_NUM,
    WDT0_CMP,
    WDT_CMP_REG_DEFAULT,
    _i2c_target_id,
    _uart,
    relation_class,
    smc_clk_ratio_test_seq,
)

# Period grid and bounds of the draw, in ps. The 250 ps grid keeps every period an even
# number of ps and exact as a float number of ns.
PERIOD_GRID_PS = 250
PERIOD_BOUNDS_PS = {
    "ref": (4_000, 12_000),
    "smc": (1_250, 12_000),
    "periph": (3_000, 10_000),
}
# clk_rst.adoc, Peripheral Timing Requirements: clk_periph_i at 100 MHz or faster.
PERIPH_SPEC_MAX_PERIOD_PS = 10_000
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000

# Step 1 (the check of the draw) and step 6 (the count compares and the fence) take no
# simulation time and are not stamped; the step 1 line is printed after the S2 stamp.
_STEPS = ("S2", "S3", "S4", "S5")
_CHECKERS = (
    ("CHK-CKR-DRAW-LEGAL", "S2"),
    ("CHK-CKR-PERIODS", "S3"),
    ("CHK-CKR-RESET-WORDS", "S4"),
    ("CHK-CKR-COPATTERN", "S5"),
)


def draw_periods_ps(rng) -> dict[str, int]:
    """One period per clock, uniform on the grid inside its bounds."""
    drawn = {}
    for name, (lo, hi) in PERIOD_BOUNDS_PS.items():
        drawn[name] = PERIOD_GRID_PS * rng.randint(lo // PERIOD_GRID_PS, hi // PERIOD_GRID_PS)
    return drawn


def drawn_text(periods_ps: dict[str, int]) -> str:
    return "ref={}ps smc={}ps periph={}ps".format(
        periods_ps["ref"], periods_ps["smc"], periods_ps["periph"]
    )


class smc_clk_ratio_rand_test_seq(smc_clk_ratio_test_seq):
    """Confirm the drawn triple, then cross the peripheral clock domain under it."""

    def __init__(
        self,
        name: str = "smc_clk_ratio_rand_test_seq",
        *,
        periods_ps: dict[str, int],
    ) -> None:
        span = RELATION_WINDOW_REF_EDGES * periods_ps["ref"]
        predicted = tuple(
            relation_class(span // periods_ps[n], RELATION_WINDOW_REF_EDGES)
            for n in ("smc", "periph")
        )
        super().__init__(
            name,
            periods_ns=tuple(periods_ps[n] / 1000 for n in ("ref", "smc", "periph")),
            relations=predicted,
        )
        self.drawn_ps = dict(periods_ps)
        self.drawn = drawn_text(periods_ps)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.last_access = "none"

    def _mark(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _read_exact(self, label: str, addr: int, want: int, length: int = 4) -> int:
        self.last_access = f"read {label} @0x{addr:08x}"
        got = await self.csr_read(label, addr, expected=want, length=length)
        got &= (1 << (8 * length)) - 1
        assert got == want, (
            f"{label} @ 0x{addr:08x}: read 0x{got:x}, want 0x{want:x}; drawn={self.drawn}"
        )
        return got

    async def _write(self, label: str, addr: int, data: int) -> None:
        self.last_access = f"write {label} @0x{addr:08x}"
        await self.csr_write(label, addr, data)

    def _s1_legal(self) -> str:
        parts = []
        for name, (lo, hi) in PERIOD_BOUNDS_PS.items():
            ps = self.drawn_ps[name]
            assert lo <= ps <= hi, f"clk_{name}_i period {ps} ps outside [{lo}, {hi}]"
            assert ps % PERIOD_GRID_PS == 0, f"clk_{name}_i period {ps} ps off the grid"
            parts.append(f"clk_{name}_i {ps} ps in [{lo}, {hi}]")
        periph = self.drawn_ps["periph"]
        assert periph <= PERIPH_SPEC_MAX_PERIOD_PS, (
            f"clk_periph_i period {periph} ps above the {PERIPH_SPEC_MAX_PERIOD_PS} ps "
            f"(100 MHz) floor of clk_rst.adoc"
        )
        return (
            f"drawn={self.drawn}; {'; '.join(parts)}, each a multiple of {PERIOD_GRID_PS} ps; "
            f"clk_periph_i at or below {PERIPH_SPEC_MAX_PERIOD_PS} ps (100 MHz or faster)"
        )

    def _s3_periods(self) -> str:
        for name, ps in self.drawn_ps.items():
            got = self.periods_ps[name]
            assert got == ps, (
                f"clk_{name}_i measured {got} ps per cycle over {RATIO_WINDOW_EDGES} rising "
                f"edges; drawn {ps} ps (drawn={self.drawn})"
            )
        span_ps = RELATION_WINDOW_REF_EDGES * self.drawn_ps["ref"]
        parts = []
        for name in ("smc", "periph"):
            want = span_ps / self.drawn_ps[name]
            got = self.relation_edges[name]
            assert abs(got - want) <= 1, (
                f"clk_{name}_i made {got} rising edges across {RELATION_WINDOW_REF_EDGES} "
                f"clk_ref_i edges; the drawn periods give {want:g} (drawn={self.drawn})"
            )
            bucket = relation_class(got, RELATION_WINDOW_REF_EDGES)
            parts.append(f"clk_{name}_i {got} edges (want {want:g} +-1, cg_clk_ratio {bucket})")
        measured = " / ".join(f"{self.periods_ps[n]:g}" for n in ("ref", "smc", "periph"))
        return (
            f"drawn={self.drawn}; measured ref / smc / periph {measured} ps over "
            f"{RATIO_WINDOW_EDGES} edges each, equal to the drawn periods; across "
            f"{RELATION_WINDOW_REF_EDGES} clk_ref_i edges {'; '.join(parts)} (bucket printed, "
            f"graded by cg_clk_ratio); stimulus integrity, not a DUT property"
        )

    async def _s4_reset_words(self) -> str:
        words = [
            ("GLOBAL_BASE", GLOBAL_BASE, GLOBAL_BASE_RESET, 8),
            ("WDT0_CMP", WDT0_CMP, WDT_CMP_REG_DEFAULT, 4),
            ("AVS_CFG_0", AVS_CFG_0, AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT, 4),
        ] + [
            (f"UART{i}_LSR", _uart("LSR", i), UART_16550_MAIN_LSR_REG_DEFAULT, 4)
            for i in range(UART_NUM)
        ]
        parts = []
        for label, addr, want, length in words:
            got = await self._read_exact(label, addr, want, length)
            parts.append(f"{label}=0x{got:X}")
        return (
            f"drawn={self.drawn}; {len(words)} generated reset words read OKAY and equal: "
            + ", ".join(parts)
        )

    async def _s5_copattern(self) -> str:
        entries = [
            (
                f"UART{i}_SCR",
                _uart("SCR", i),
                _UART_SCR_PATTERNS[i],
                UART_16550_MAIN_SCR_REG_DEFAULT,
            )
            for i in range(UART_NUM)
        ] + [
            (
                f"I2C{i}_TARGET_ID",
                _i2c_target_id(i),
                reg_field_encode(_I2C_H, "I2C", "TARGET_ID", address0=0x31 + i, mask0=0x7F),
                I2C_TARGET_ID_REG_DEFAULT,
            )
            for i in range(I2C_NUM)
        ]
        assert len({e[1] for e in entries}) == len(entries), "addresses not distinct"
        assert len({e[2] for e in entries}) == len(entries), "patterns not distinct"
        for label, addr, pattern, _ in entries:
            await self._write(f"{label}_PATTERN", addr, pattern)
        reads = []
        for label, addr, pattern, _ in entries:
            got = await self._read_exact(f"{label}_PATTERN_RB", addr, pattern)
            reads.append(f"{label}=0x{got:X}")
        for label, addr, _, restore in entries:
            await self._write(f"{label}_RESTORE", addr, restore)
        for label, addr, _, restore in entries:
            await self._read_exact(f"{label}_RESTORE_RB", addr, restore)
        return (
            f"drawn={self.drawn}; {len(entries)} patterns written before any read back, each "
            f"read back its own pattern ({', '.join(reads)}); after the restore every "
            f"register read its generated reset word"
        )

    async def body(self) -> None:
        cocotb.log.info("CKR draw in use: drawn=%s", self.drawn)
        text = self._s1_legal()

        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        self._mark("S2")
        cocotb.log.info("BRINGUP_DONE under drawn=%s", self.drawn)
        self._chk("CHK-CKR-DRAW-LEGAL", text)

        await self._measure_periods()
        await self._count_relation()
        text = self._s3_periods()
        self._mark("S3")
        self._chk("CHK-CKR-PERIODS", text)

        self.value_checks_before = self.env.scoreboard.sys_axi_value_checks_seen
        text = await self._s4_reset_words()
        self._mark("S4")
        self._chk("CHK-CKR-RESET-WORDS", text)

        text = await self._s5_copattern()
        self._mark("S5")
        self._chk("CHK-CKR-COPATTERN", text)

        self.value_checks = self.env.scoreboard.sys_axi_value_checks_seen - self.value_checks_before
        assert self.value_checks == EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {self.value_checks} exact compares, expected "
            f"{EXPECTED_VALUE_CHECKS}"
        )
        self.assert_all_reachable(EXPECTED_ACCESSES, "CLK_RATIO_RAND")

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 2 bounded waits: wait_fuse_sense_done sub-waits each bounded "
            "%d clk_smc_i rises; %d SEP_IN accesses each bounded by the driver timeout %d ns "
            "(allow_timeout False), last %s; the period and edge-count windows are fixed "
            "edge counts (%d edges per clock, %d clk_ref_i edges); expiry raises AssertionError",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.accesses,
            self.cfg.axi_timeout_ns,
            self.last_access,
            RATIO_WINDOW_EDGES,
            RELATION_WINDOW_REF_EDGES + 2,
        )

    def nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses == EXPECTED_ACCESSES, f"{self.accesses} accesses"
        assert self.value_checks == EXPECTED_VALUE_CHECKS, f"{self.value_checks} compares"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP_DONE<PERIODS<RESET_WORDS<COPATTERN; "
            "checker lines %s; accesses %d == %d; scoreboard exact compares %d == %d; "
            "drawn=%s; stamps %s",
            ",".join(chk_ids),
            self.accesses,
            EXPECTED_ACCESSES,
            self.value_checks,
            EXPECTED_VALUE_CHECKS,
            self.drawn,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
