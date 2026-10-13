# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SEP reset releases on a clk_i edge, the watchdog timer-domain reset on a clk_wdt_i edge, and a cold reset clears the armed watchdog controls.

Contract (``hw/sys/sep/doc/reset_controller.adoc``, SEP Reset Controller:
``sep_reset_no`` releases synchronously to ``clk_i``;
``hw/sys/sep/doc/watchdog.adoc``, Clock, Reset, and Debug Behavior and
``hw/sys/sep/doc/clk_rst.adoc``, Reset Architecture: the watchdog timer-domain
reset releases synchronized to ``clk_wdt_i``;
``vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/gen/adoc/aon_timer.adoc``,
Reset column of ``WDOG_CTRL``, ``WKUP_CTRL`` and ``INTR_STATE``).

``clk_wdt_i`` runs at eight ``clk_i`` periods from a drawn start phase. Each leaf
runs two ``rst_ni`` passes. The control pass (graded window closed) asserts
``rst_ni`` at a drawn phase and releases it 10 percent of a ``clk_i`` period
after a ``clk_i`` rising edge. The graded pass asserts and releases ``rst_ni``
inside a drawn third of the ``clk_i`` period, with the release placed in the
``clk_i`` cycle that puts it inside the same third of the ``clk_wdt_i`` period.
Each pass first arms seven watchdog and wakeup registers to non-default values.

Checkers:
  CHK-ARM           each armed register reads back its armed value, which
                    differs from its RDL reset value on the field bits.
  CHK-RST-SYNC      the ``dbg_sep_reset_n_o`` tap rises after the ``rst_ni``
                    release, within 1 ps of a ``clk_i`` rising edge.
  CHK-AON-REL       the ``aon_rst_n_probe_o`` tap is low at the end of the
                    ``rst_ni`` low window and rises after the release, within
                    1 ps of a ``clk_wdt_i`` rising edge.
  CHK-COLD-DEFAULT  after the cold reset ``WDOG_CTRL``, ``WKUP_CTRL`` and
                    ``INTR_STATE`` read their reset value 0 on the RDL field bits.

Controls and observations: ``CTL-COLD-WDT`` logs ``WDOG_REGWEN``, the two
watchdog thresholds and ``WKUP_THOLD_HI`` after the reset (graded by
``sep_timer_clock_contract_test``). ``OBS-RST-ASSERT`` logs the delay from the
``rst_ni`` fall to the ``sep_reset_n`` fall; the specification gives no
assertion timing, so it is not graded.

Environment choices (not from the specification): the 1 ps edge allowance
covers the simulator resolution; the ``sep_reset_n`` release wait is
``_SEP_BOUND`` ``clk_i`` cycles and the ``aon_rst_n`` wait ``_AON_BOUND``
``clk_wdt_i`` periods; the reset width floor is 8 ``clk_i`` cycles.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense`` with
``ext_boot_seq_done_i`` at 1, so ``rst_ni`` is the only open term. VCS only:
the sub-cycle phases need a four-state, event-ordered simulator. RANDCFG.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.sep_edge_timer import (
    SepEdgeTimer,
    SepPinEdgeCounter,
    nearest_edge_offset_ps,
    phase_pct,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import WDT_TIMER
from seq_lib.sep_wdt_aon_seq import (
    INTR_STATE,
    INTR_TEST,
    WDOG_BARK_THOLD,
    WDOG_BITE_THOLD,
    WDOG_CTRL,
    WDOG_ENABLE,
    WDOG_REGWEN,
    WKUP_CTRL,
    WKUP_ENABLE,
    WKUP_PRESCALER_SHIFT,
    WKUP_THOLD_HI,
    SepWdtAon,
)

TEST = "sep_cold_reset_phase_test"

_WDT_RATIO = 8
_EDGE_ALLOWANCE_PS = 1
_SEP_BOUND = 64
_AON_BOUND = 64
# Thirds of a period in percent (each away from the edge).
_THIRDS = {1: (10, 33), 2: (33, 67), 3: (67, 90)}
_CTL_RELEASE_PCT = 10
# The clk_wdt_i start phase is a whole number of 125 ps steps. The bench clock
# start takes the delay in ns, and a multiple of 0.125 ns is exact in binary,
# so the delay is a whole step count at 1 ps and at 1 fs simulator precision.
_WDT_PHASE_STEP_PS = 125

_BARK = 0x0FFF_0000
_BITE = 0x0FFF_1000
_WKUP_HI = 0x0FFF_0000
_WKUP_PRESCALER = 5
_INTR_BARK_TEST = WDT_TIMER.field_mask("INTR_TEST", "wdog_timer_bark")
_INTR_BARK_STATE = WDT_TIMER.field_mask("INTR_STATE", "wdog_timer_bark")

# Arm order of the contract: (name, address, value written, armed readback).
_ARM = (
    ("WDOG_BARK_THOLD", WDOG_BARK_THOLD, _BARK, _BARK),
    ("WDOG_BITE_THOLD", WDOG_BITE_THOLD, _BITE, _BITE),
    ("WKUP_THOLD_HI", WKUP_THOLD_HI, _WKUP_HI, _WKUP_HI),
    (
        "WKUP_CTRL",
        WKUP_CTRL,
        WKUP_ENABLE | (_WKUP_PRESCALER << WKUP_PRESCALER_SHIFT),
        WKUP_ENABLE | (_WKUP_PRESCALER << WKUP_PRESCALER_SHIFT),
    ),
    ("WDOG_CTRL", WDOG_CTRL, WDOG_ENABLE, WDOG_ENABLE),
    ("INTR_STATE", INTR_TEST, _INTR_BARK_TEST, _INTR_BARK_STATE),
    ("WDOG_REGWEN", WDOG_REGWEN, 0, 0),
)
_ADDR = {
    "WDOG_BARK_THOLD": WDOG_BARK_THOLD,
    "WDOG_BITE_THOLD": WDOG_BITE_THOLD,
    "WKUP_THOLD_HI": WKUP_THOLD_HI,
    "WKUP_CTRL": WKUP_CTRL,
    "WDOG_CTRL": WDOG_CTRL,
    "INTR_STATE": INTR_STATE,
    "WDOG_REGWEN": WDOG_REGWEN,
}
# Graded by this leaf: the aon_timer.adoc Reset column gives 0 for each.
_COLD_GRADED = ("WDOG_CTRL", "WKUP_CTRL", "INTR_STATE")
_COLD_LOGGED = ("WDOG_REGWEN", "WDOG_BARK_THOLD", "WDOG_BITE_THOLD", "WKUP_THOLD_HI")
_SPEC_COLD_VALUE = 0


def _now_ps() -> int:
    return int(get_sim_time("ps"))


@pyuvm.test()
class sep_cold_reset_phase_test(sep_base_test):
    """sep_reset_n releases on clk_i, aon_rst_n on clk_wdt_i; cold reset clears the AON controls."""

    required_evidence = ("CHK-ARM", "CHK-RST-SYNC", "CHK-AON-REL", "CHK-COLD-DEFAULT")

    def _draw(self, rng: SepSeededRng) -> None:
        p = self.p_ps
        log = self.logger

        def in_third(j: int, period: int) -> int:
            lo, hi = _THIRDS[j]
            return rng.randrange(lo * period // 100 + 1, hi * period // 100)

        self.third = rng.randrange(1, 4)
        log.info("DRAW third=%d (%d-%d %% of the period)", self.third, *_THIRDS[self.third])
        self.wc = {"ctl": rng.randrange(8, 65), "graded": rng.randrange(8, 65)}
        log.info("DRAW Wc ctl=%d graded=%d clk_i cycles", self.wc["ctl"], self.wc["graded"])
        self.pa = {"ctl": rng.randrange(10 * p // 100, 90 * p // 100 + 1)}
        log.info("DRAW pa_0=%d ps (%.1f %%)", self.pa["ctl"], phase_pct(self.pa["ctl"], p))
        self.pa["graded"] = in_third(self.third, p)
        self.pr_graded = in_third(self.third, p)
        log.info(
            "DRAW pa_j=%d ps (%.1f %%) pr_j=%d ps (%.1f %%)",
            self.pa["graded"],
            phase_pct(self.pa["graded"], p),
            self.pr_graded,
            phase_pct(self.pr_graded, p),
        )
        self.wdt_phase = rng.randrange(0, self.pw_ps // _WDT_PHASE_STEP_PS) * _WDT_PHASE_STEP_PS
        log.info(
            "DRAW clk_wdt_i start phase=%d ps (period %d ps)",
            self.wdt_phase,
            self.pw_ps,
        )

    async def _wait_level(self, sig, want: int, clk, bound: int, label: str) -> None:
        for _ in range(bound):
            await RisingEdge(clk)
            await ReadOnly()
            if self.rd(sig, allow_unknown=True) == want and sig.value.is_resolvable:
                await RisingEdge(cocotb.top.clk_i)
                return
        raise AssertionError(f"{label}: {sig._name} did not read {want} within {bound} cycles")

    async def _arm(self, pass_name: str) -> dict[str, int]:
        armed = {}
        for name, addr, value, _exp in _ARM:
            await self.wdt.write(addr, value)
        for name, _addr, _value, exp in _ARM:
            got = await self.wdt.read(_ADDR[name])
            mask = WDT_TIMER.mask32(name)
            default = WDT_TIMER.reset32(name)
            fc = field_compare(got, exp, mask)
            assert (exp & mask) != (default & mask), (
                f"CHK-ARM FAIL: test error, armed value of {name} equals its RDL default"
            )
            assert fc.ok, (
                f"CHK-ARM FAIL: pass={pass_name} {name} {fc.fields()} default=0x{default:x}"
            )
            armed[name] = got & mask
            self.logger.info(
                "CHK-ARM PASS: pass=%s %s=0x%x default=0x%x field_mask=0x%x rsvd=0x%x",
                pass_name,
                name,
                got & mask,
                default & mask,
                mask,
                fc.rsvd,
            )
        return armed

    def _release_cycle(self, t_edge: int, pr: int) -> int:
        """clk_i edges after ``t_edge`` that put ``t_edge + n P + pr`` in third j of clk_wdt_i."""
        lo, hi = _THIRDS[self.third]
        wdt = self.edges.edge_times("clk_wdt_i")
        t_w = wdt[-1]
        for n in range(1, 4 * _WDT_RATIO):
            t_rel = t_edge + n * self.p_ps + pr
            ph = (t_rel - t_w) % self.pw_ps
            if lo * self.pw_ps < 100 * ph < hi * self.pw_ps:
                return n
        raise AssertionError("test error: no clk_i cycle places the release in the drawn third")

    async def _pass(self, pass_name: str) -> None:
        dut = cocotb.top
        clk = dut.clk_i
        p = self.p_ps
        armed = await self._arm(pass_name)

        # Assert.
        await RisingEdge(clk)
        await Timer(self.pa[pass_name], units="ps")
        sep_before = self.rd(dut.dbg_sep_reset_n_o)
        assert sep_before == 1, f"pass={pass_name}: sep_reset_n tap not 1 before the assert"
        dut.rst_ni.value = 0
        t_fall = _now_ps()
        for _ in range(self.wc[pass_name]):
            await RisingEdge(clk)
        hold_end_aon = self.rd(dut.aon_rst_n_probe_o, allow_unknown=True)
        sep_falls = self.sep_t.falls(t_fall)
        assert sep_falls, (
            f"pass={pass_name}: sep_reset_n tap did not fall within the {self.wc[pass_name]}-cycle "
            "rst_ni low window"
        )
        clk_between = sum(1 for t in self.edges.edge_times("clk_i") if t_fall < t <= sep_falls[0])
        self.logger.info(
            "OBS-RST-ASSERT: pass=%s third=%s rst_ni fell t=%d sep_reset_n fell t=%d delta=%d "
            "clk_edges_between=%d",
            pass_name,
            self.third if pass_name == "graded" else "-",
            t_fall,
            sep_falls[0],
            sep_falls[0] - t_fall,
            clk_between,
        )

        # Release.
        await RisingEdge(clk)
        t_edge = _now_ps()
        if pass_name == "ctl":
            pr = _CTL_RELEASE_PCT * p // 100
            n = 0
        else:
            pr = self.pr_graded
            n = self._release_cycle(t_edge, pr)
            for _ in range(n):
                await RisingEdge(clk)
        await Timer(pr, units="ps")
        dut.rst_ni.value = 1
        t_rel = _now_ps()
        wdt_edges = self.edges.edge_times("clk_wdt_i")
        wdt_ph = (t_rel - wdt_edges[-1]) % self.pw_ps
        self.logger.info(
            "PLACE pass=%s release t=%d clk_i phase=%d ps (%.1f %%) after %d cycles; "
            "clk_wdt_i phase=%d ps (%.1f %%)",
            pass_name,
            t_rel,
            pr,
            phase_pct(pr, p),
            n,
            wdt_ph,
            phase_pct(wdt_ph, self.pw_ps),
        )
        if pass_name == "graded":
            lo, hi = _THIRDS[self.third]
            assert lo * self.pw_ps < 100 * wdt_ph < hi * self.pw_ps, (
                f"test error: graded release clk_wdt_i phase {wdt_ph} ps not in third {self.third}"
            )

        await self._wait_level(dut.dbg_sep_reset_n_o, 1, clk, _SEP_BOUND, "sep_reset_n release")
        sep_rise = [t for t in self.sep_t.rises(t_rel)]
        assert sep_rise, f"CHK-RST-SYNC FAIL: pass={pass_name} no sep_reset_n rise after release"
        t_sr = sep_rise[0]
        off = nearest_edge_offset_ps(t_sr, self.edges.edge_times("clk_i"))
        assert t_sr > t_rel and off is not None and abs(off) <= _EDGE_ALLOWANCE_PS, (
            f"CHK-RST-SYNC FAIL: pass={pass_name} rst_ni rose t={t_rel} sep_reset_n rose t={t_sr} "
            f"offset_to_clk_edge={off} ps (allowance {_EDGE_ALLOWANCE_PS} ps)"
        )
        self.logger.info(
            "CHK-RST-SYNC PASS: pass=%s rst_ni rose t=%d phase=%.1f sep_reset_n rose t=%d "
            "offset_to_clk_edge=%d allowance=%d",
            pass_name,
            t_rel,
            phase_pct(pr, p),
            t_sr,
            off,
            _EDGE_ALLOWANCE_PS,
        )

        try:
            await self._wait_level(
                dut.aon_rst_n_probe_o, 1, dut.clk_wdt_i, _AON_BOUND, "aon_rst_n release"
            )
        except AssertionError as exc:
            raise AssertionError(f"CHK-AON-REL FAIL: pass={pass_name} {exc}") from None
        assert hold_end_aon == 0 and self.aon_t.value_at(t_rel - 1) == 0, (
            f"CHK-AON-REL FAIL: pass={pass_name} aon_rst_n not low in the rst_ni low window "
            f"(hold end={hold_end_aon}, at release={self.aon_t.value_at(t_rel - 1)})"
        )
        aon_rise = self.aon_t.rises(t_rel)
        assert aon_rise, f"CHK-AON-REL FAIL: pass={pass_name} no aon_rst_n rise after release"
        t_ar = aon_rise[0]
        woff = nearest_edge_offset_ps(t_ar, self.edges.edge_times("clk_wdt_i"))
        assert t_ar > t_rel and woff is not None and abs(woff) <= _EDGE_ALLOWANCE_PS, (
            f"CHK-AON-REL FAIL: pass={pass_name} aon_rst_n rose t={t_ar} "
            f"offset_to_clk_wdt_edge={woff} ps (allowance {_EDGE_ALLOWANCE_PS} ps)"
        )
        self.logger.info(
            "CHK-AON-REL PASS: pass=%s aon_rst_n rose t=%d offset_to_clk_wdt_edge=%d "
            "wdt_phase=%d low_at_release=1 rst_ni rose t=%d",
            pass_name,
            t_ar,
            woff,
            wdt_ph,
            t_rel,
        )

        await self.wait_fuse_sense(max_cycles=_SEP_BOUND)
        got = {name: await self.wdt.read(_ADDR[name]) for name in _COLD_GRADED + _COLD_LOGGED}
        for name in _COLD_GRADED:
            exp = WDT_TIMER.reset32(name)
            assert exp == _SPEC_COLD_VALUE, (
                f"test error: RDL reset of {name} is 0x{exp:x}, the aon_timer Reset column gives 0"
            )
            mask = WDT_TIMER.mask32(name)
            fc = field_compare(got[name], exp, mask)
            assert fc.ok, (
                f"CHK-COLD-DEFAULT FAIL: pass={pass_name} {name} {fc.fields()} "
                f"armed=0x{armed[name]:x}"
            )
            self.logger.info(
                "CHK-COLD-DEFAULT PASS: pass=%s %s=0x%x armed=0x%x field_mask=0x%x rsvd=0x%x",
                pass_name,
                name,
                got[name] & mask,
                armed[name],
                mask,
                fc.rsvd,
            )
        self.logger.info(
            "CTL-COLD-WDT: pass=%s regwen=0x%x bark=0x%x bite=0x%x wkup_hi=0x%x",
            pass_name,
            got["WDOG_REGWEN"],
            got["WDOG_BARK_THOLD"],
            got["WDOG_BITE_THOLD"],
            got["WKUP_THOLD_HI"],
        )

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        dut = cocotb.top
        self.p_ps = round(self.cfg.sys_clk_period_ns * 1000)
        self.pw_ps = _WDT_RATIO * self.p_ps
        rng = SepSeededRng(seed)
        self._draw(rng)
        close_graded_window()
        self.cfg.wdt_clk_period_ns = self.pw_ps / 1000
        self.clock_phases_ps = {"clk_wdt_i": self.wdt_phase}
        self.edges = SepPinEdgeCounter(("clk_i", "clk_wdt_i")).start()
        self.sep_t = SepEdgeTimer(dut.dbg_sep_reset_n_o, name="sep_reset_n").start()
        self.aon_t = SepEdgeTimer(dut.aon_rst_n_probe_o, name="aon_rst_n").start()
        self.wdt = SepWdtAon(self)
        await self.bring_up_no_cpu()
        await self._wait_level(dut.dbg_sep_reset_n_o, 1, dut.clk_i, _SEP_BOUND, "bring-up")
        await self._wait_level(
            dut.aon_rst_n_probe_o, 1, dut.clk_wdt_i, _AON_BOUND, "bring-up aon_rst_n"
        )
        measured = self.edges.period_ps("clk_wdt_i")
        assert measured == self.pw_ps, (
            f"test error: clk_wdt_i period {measured} ps, expected {self.pw_ps} ps"
        )
        self.logger.info(
            "CFG clk_i=%d ps clk_wdt_i=%d ps (ratio %d) start phase=%d ps",
            self.p_ps,
            self.pw_ps,
            _WDT_RATIO,
            self.wdt_phase,
        )

        await self._pass("ctl")
        open_graded_window(TEST, self.logger)
        await self._pass("graded")
        close_graded_window(self.logger)
        self.logger.info(
            "RESULT %s seed=%d PASS checks=%d", TEST, seed, len(self.required_evidence)
        )
