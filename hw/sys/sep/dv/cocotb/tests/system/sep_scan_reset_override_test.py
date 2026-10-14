# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scan reset replaces the SEP reset nets only while test_en_i is high.

RAND-REP, no_cpu on ``lsu_stub_all_live`` with real fuse sense, VCS only (the
release phase is sub-cycle and the nets can hold X). The seed draws the low
width ``w`` of ``scan_rst_ni`` (4 to 64 ``clk_i`` cycles; the floor is an
environment choice) and its release ``phase`` (10 to 90 percent of the
``clk_i`` period after a ``clk_i`` rising edge). The cells, their order and the
strap values are the same on every seed.

Contract (``hw/sys/sep/doc/port_table.adoc``, ``test_en_i``, ``scan_rst_ni``,
``secure_tm_req_i``; ``hw/sys/sep/doc/reset_controller.adoc``, SEP Reset
Controller; ``hw/sys/sep/doc/clk_rst.adoc``, Reset Architecture;
``hw/sys/sep/doc/test_mode.adoc``, Entry and Exit):

* While ``test_en_i`` is high, ``scan_rst_ni`` replaces the 11 nets
  ``sep_reset_n``, ``sep_cpu_reset_n``, ``ip_rst_n[6:1]``, ``aon_rst_n`` and
  ``km_cond_rst[1:0]``. ``sep_reset_n`` and ``aon_rst_n`` rise before the next
  edge of their own clock after the ``scan_rst_ni`` rise (the synchronizer is
  not in the path). With ``test_en_i`` low, ``scan_rst_ni`` has no effect.
* ``test_en_i`` and ``secure_tm_req_i`` are separate ports: ``secure_tm_o``
  does not follow ``test_en_i``.

``clk_wdt_i`` runs at 8 ``clk_i`` periods with a fixed phase of 5 percent of a
``clk_i`` period after a ``clk_i`` rising edge, so a ``clk_wdt_i`` edge never
falls on a ``clk_i`` edge or on the drawn release point. The hold interval H
(32 ``clk_i`` cycles, at least two ``clk_wdt_i`` periods) is a test parameter.

Checkers:
  CHK-SCAN-IDLE     test_en_i=0: the 11 nets stay high on every clk_i edge from
                    the scan_rst_ni fall to the end of the hold after its rise.
  CHK-SCAN-REPLACE  test_en_i=1: the 11 nets are low on every clk_i edge
                    while scan_rst_ni is low and high with scan_rst_ni=1;
                    sep_reset_n and aon_rst_n rise before the next clk_i and
                    clk_wdt_i edge. Other rise offsets: OBS-SCAN-OFFSET.
  CHK-STRAP-INDEP   secure_tm_o does not move across the test_en_i toggles, at
                    strap 1 and at strap 0.

Blocked (open specification question): the specification does not name the
test inputs that ``test_en_i`` must reach, and the design ties some clock-gater
and AXI cell test inputs to 0. No test pin is graded. A read-only hierarchy walk
collects a pin population from the DUT itself, so it is not a golden set. The
leaf logs ``OBS-TEST-EN-PINS`` (the walk totals, the count of pins that follow
``test_en_i`` and the path of every pin that does not) and ``OBS-STRAP-PINS``
(the walked pins that move across the strap toggles).

The graded window (owner code of this test) is open from the first test_en_i
toggle to the end of leg B, and closed for the rst_ni pulse of the strap-0 boot
and for the Key Manager release.
"""

from __future__ import annotations

import re

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.sep_edge_timer import SepEdgeTimer, SepPinEdgeCounter
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = "sep_scan_reset_override_test"

# The 11 replaced nets and their tb_top taps (bit 0 of km_cond_rst_probe_o is
# rst_warm_sync_n, bit 1 rst_cold_aasd_n).
NETS: tuple[tuple[str, str, int | None], ...] = (
    ("sep_reset_n", "dbg_sep_reset_n_o", None),
    ("sep_cpu_reset_n", "sep_cpu_reset_n_o", None),
    ("ip_rst_n[1]", "otbn_gated_rst_n_probe_o", None),
    ("ip_rst_n[2]", "aes_gated_rst_n_probe_o", None),
    ("ip_rst_n[3]", "hmac_gated_rst_n_probe_o", None),
    ("ip_rst_n[4]", "kmac_gated_rst_n_probe_o", None),
    ("ip_rst_n[5]", "trng_gated_rst_n_probe_o", None),
    ("ip_rst_n[6]", "abr_gated_rst_n_probe_o", None),
    ("aon_rst_n", "aon_rst_n_probe_o", None),
    ("km_cond_rst[0]", "km_cond_rst_probe_o", 0),
    ("km_cond_rst[1]", "km_cond_rst_probe_o", 1),
)
N_NETS = len(NETS)

H = 32  # hold interval in clk_i cycles (at least two clk_wdt_i periods)
P_W = 8  # clk_wdt_i period in clk_i periods
WDT_PHASE_PCT = 5  # clk_wdt_i rising edge, percent of a clk_i period after clk_i
PIN_BOUND = 16  # clk_i cycles for every pin to follow test_en_i
TAP_BOUND = 2_000  # clk_i cycles for a reset tap to read 1
SENSE_BOUND = 40_000  # clk_i cycles for real fuse sense
RST_PULSE = 20  # clk_i cycles of the rst_ni pulse of the strap-0 boot

# Pin classes of the walk: (class, definition-name pattern, test port).
PIN_CLASSES = (
    ("clock_gater", re.compile(r"clock_gat|clk_gat", re.I), "test_en_i"),
    ("axi_cell", re.compile(r"^axi_|^axi$", re.I), "test_i"),
)


class _Cfg:
    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.w = rng.randrange(4, 65)
        self.phase = rng.randrange(10, 91)


@pyuvm.test()
class sep_scan_reset_override_test(sep_base_test):
    """scan_rst_ni replaces the SEP reset nets only while test_en_i is high."""

    required_evidence = (
        "CHK-SCAN-IDLE",
        "CHK-SCAN-REPLACE",
        "CHK-STRAP-INDEP",
    )

    # -- taps -------------------------------------------------------------------

    def _net(self, i: int) -> int:
        _name, port, bit = NETS[i]
        sig = getattr(cocotb.top, port)
        if bit is None:
            return self.rd(sig)
        return (self.rd(sig, 1 << bit) >> bit) & 1

    def _nets(self) -> list[int]:
        return [self._net(i) for i in range(N_NETS)]

    async def _wait_tap(self, port: str, bound: int) -> int:
        sig = getattr(cocotb.top, port)
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd(sig, allow_unknown=True):
                await RisingEdge(cocotb.top.clk_i)
                return n
        raise AssertionError(f"{port} did not read 1 within {bound} clk_i cycles")

    # -- hierarchy walk -----------------------------------------------------------

    def _walk(self) -> dict[str, list[tuple[str, object]]]:
        """Read-only walk of the SEP hierarchy for the test pins of each class."""
        from cocotb.handle import HierarchyArrayObject, HierarchyObject

        found: dict[str, list[tuple[str, object]]] = {c: [] for c, _p, _n in PIN_CLASSES}
        scopes = 0

        def visit(h, path: str) -> None:
            nonlocal scopes
            scopes += 1
            try:
                defn = h._def_name or ""
            except Exception:  # noqa: BLE001 - a scope without a definition name
                defn = ""
            for cls, pat, port in PIN_CLASSES:
                if defn and pat.search(defn):
                    pin = getattr(h, port, None) if hasattr(h, port) else None
                    if pin is not None:
                        found[cls].append((f"{path}.{port} ({defn})", pin))
            try:
                children = list(h)
            except Exception:  # noqa: BLE001 - a scope the simulator cannot iterate
                return
            for child in children:
                name = getattr(child, "_name", "?")
                if isinstance(child, HierarchyArrayObject):
                    for sub in child:
                        visit(sub, f"{path}.{getattr(sub, '_name', name)}")
                elif isinstance(child, HierarchyObject):
                    visit(child, f"{path}.{name}")

        visit(cocotb.top.u_dut.u_sep, "u_dut.u_sep")
        self.logger.info(
            "TEST-EN-WALK LOG: scopes=%d %s",
            scopes,
            " ".join(f"{c}={len(v)}" for c, v in found.items()),
        )
        for cls, pins in found.items():
            for path, _pin in pins:
                self.logger.info("TEST-EN-PIN LOG: class=%s pin=%s", cls, path)
        return found

    def _pins(self) -> list[tuple[str, int]]:
        return [(p, self.rd(sig)) for pins in self.walk.values() for p, sig in pins]

    async def _set_test_en(self, v: int) -> None:
        """Drive test_en_i, wait up to PIN_BOUND cycles for every walked pin to
        equal it, and record the pins that do not (OBS-TEST-EN-PINS)."""
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = v
        for _ in range(PIN_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            bad = [p for p, x in self._pins() if x != v]
            if not bad:
                break
        self.pin_stuck.update(bad)
        await RisingEdge(dut.clk_i)

    async def _toggle_test_en(self, strap: int) -> None:
        """test_en_i 0, 1, 0, each held H cycles; secure_tm_o sampled every edge."""
        dut = cocotb.top
        tm0 = self.tm_expect
        moved = []
        seen = {"n": 0, "last": 0}

        async def _watch(stop: dict) -> None:
            while not stop["v"]:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                tm = self.rd(dut.secure_tm_o)
                seen["n"] += 1
                seen["last"] = int(get_sim_time("ps"))
                if tm != tm0:
                    moved.append((seen["last"], tm))

        stop = {"v": False}
        task = cocotb.start_soon(_watch(stop))
        for v in (0, 1, 0):
            await self._set_test_en(v)
            await ClockCycles(dut.clk_i, H)
            self.test_en_toggles += 1
        t_end = int(get_sim_time("ps"))
        stop["v"] = True
        await task
        assert seen["n"] and seen["last"] >= t_end, (
            f"CHK-STRAP-INDEP FAIL: secure_tm_o watcher did not sample through the toggles "
            f"(samples={seen['n']} last={seen['last']} ps end={t_end} ps)"
        )
        assert not moved, (
            f"CHK-STRAP-INDEP FAIL: secure_tm_o moved from {tm0} across the test_en_i toggles "
            f"(strap={strap}): {moved[:4]}"
        )
        self.logger.info(
            "STRAP-INDEP LOG: strap=%d secure_tm_o=%d unchanged across test_en_i 0,1,0", strap, tm0
        )

    # -- scan pulse -------------------------------------------------------------------

    async def _scan_pulse(self, test_en: int, chk: str) -> dict:
        """scan_rst_ni low for w cycles, released at the drawn phase; nets sampled
        on every clk_i rising edge to the end of the hold after the rise."""
        dut = cocotb.top
        cfg = self.tcfg
        period_ps = self.sys_ps
        samples: list[tuple[int, list[int]]] = []
        stop = {"v": False}

        async def _sample() -> None:
            while not stop["v"]:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                samples.append((int(get_sim_time("ps")), self._nets()))

        timers = [SepEdgeTimer(getattr(dut, port), name=name).start() for name, port, _b in NETS]
        task = cocotb.start_soon(_sample())
        await RisingEdge(dut.clk_i)
        await Timer(cfg.phase * period_ps // 100, units="ps")
        dut.scan_rst_ni_i.value = 0
        t_fall = int(get_sim_time("ps"))
        for _ in range(cfg.w):
            await RisingEdge(dut.clk_i)
        await ReadOnly()
        last_edge = int(get_sim_time("ps"))
        before_release = self._nets()
        await Timer(cfg.phase * period_ps // 100, units="ps")
        dut.scan_rst_ni_i.value = 1
        t_rise = int(get_sim_time("ps"))
        await ClockCycles(dut.clk_i, H)
        await ReadOnly()
        t_end = int(get_sim_time("ps"))
        stop["v"] = True
        await task
        assert samples and samples[-1][0] >= t_end, (
            f"{chk} FAIL: net sampler did not sample through the hold (end={t_end} ps)"
        )
        for t in timers:
            await t.stop()
        rises = {}
        for (name, _p, bit), t in zip(NETS, timers):
            r = t.rises(t_rise, until_ps=t_end, bit=bit or 0)
            rises[name] = r[0] if r else None
        return {
            "samples": [s for s in samples if s[0] >= t_fall],
            "t_fall": t_fall,
            "t_rise": t_rise,
            "last_edge": last_edge,
            "before_release": before_release,
            "rises": rises,
            "test_en": test_en,
        }

    # -- leaf -----------------------------------------------------------------------

    async def _boot(self) -> None:
        """Bring-up with the strap at 1 stable from before the rst_ni release."""
        dut = cocotb.top
        self.drive_idle_defaults(dut, cpu_run=False)
        dut.test_en_i.value = 0
        dut.scan_rst_ni_i.value = 1
        dut.test_en_strap_i.value = 1
        await self.assert_cold_reset(dut)
        self.start_clocks(dut)
        await ClockCycles(dut.clk_i, 20)
        dut.rst_ni.value = 1
        await ClockCycles(dut.clk_i, 2)
        self.cfg.reset_done.set()

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.tcfg = cfg = _Cfg(seed)
        self.logger.info("DRAW w=%d phase=%d", cfg.w, cfg.phase)
        self.sys_ps = int(round(self.cfg.sys_clk_period_ns * 1000))
        self.logger.info(
            "SCAN env: H=%d P_w=%d wdt_phase_pct=%d pin_bound=%d tap_bound=%d sense_bound=%d",
            H,
            P_W,
            WDT_PHASE_PCT,
            PIN_BOUND,
            TAP_BOUND,
            SENSE_BOUND,
        )
        dut = cocotb.top
        self.cfg.wdt_clk_period_ns = P_W * self.cfg.sys_clk_period_ns
        self.clock_phases_ps = {"clk_wdt_i": WDT_PHASE_PCT * self.sys_ps // 100}
        self.pins_clk = SepPinEdgeCounter(("clk_i", "clk_wdt_i"), keep=1 << 14).start()
        self.test_en_toggles = 0
        self.strap_toggles = 0
        self.pin_stuck: set[str] = set()

        # Step 2: boot with real fuse sense and the strap at 1.
        self.write_efuse_image(self.select_efuse_image())
        await self._boot()
        await self.wait_fuse_sense(max_cycles=SENSE_BOUND)
        for port in ("dbg_sep_reset_n_o", "sep_cpu_reset_n_o"):
            await self._wait_tap(port, TAP_BOUND)
        await self._wait_tap("secure_tm_o", TAP_BOUND)
        self.tm_expect = 1
        self.logger.info("CTL-STRAP-INDEP: strap=1 secure_tm_o=1 after sensing")

        # Step 3: hierarchy walk.
        self.walk = self._walk()
        for cls, pins in self.walk.items():
            self.logger.info("OBS-TEST-EN-WALK: class=%s pins=%d", cls, len(pins))

        # Step 4: test_en_i toggles with the strap at 1.
        open_graded_window(TEST, self.logger)
        await self._toggle_test_en(strap=1)

        # Step 5: strap toggles with test_en_i = 0. Every walked pin is compared with
        # its own value before the toggles (OBS-STRAP-PINS).
        following = [p for p, _x in self._pins() if p not in self.pin_stuck]
        await ReadOnly()
        before = dict(self._pins())
        await RisingEdge(dut.clk_i)
        moved = []
        for v in (0, 1):
            await RisingEdge(dut.clk_i)
            dut.test_en_strap_i.value = v
            self.strap_toggles += 1
            for _ in range(H):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                moved += [(p, x) for p, x in self._pins() if x != before[p]]
        await RisingEdge(dut.clk_i)
        for p in sorted({p for p, _x in moved}):
            self.logger.info("OBS-STRAP-PINS: moved=%s", p)
        self.logger.info(
            "OBS-STRAP-PINS: strap toggles 1,0,1 with test_en_i=0: pins=%d follow_test_en_i=%d "
            "moved=%d",
            len(before),
            len(following),
            len({p for p, _x in moved}),
        )

        # Step 6: strap at 0, rst_ni pulse (not graded), toggles again.
        close_graded_window(self.logger)
        dut.test_en_strap_i.value = 0
        await self.pulse_rst_ni(
            hold_cycles=RST_PULSE, release_bound=TAP_BOUND, max_sense_cycles=SENSE_BOUND
        )
        for port in ("dbg_sep_reset_n_o", "sep_cpu_reset_n_o"):
            await self._wait_tap(port, TAP_BOUND)
        await ReadOnly()
        tm = self.rd(dut.secure_tm_o)
        assert tm == 0, f"CHK-STRAP-INDEP FAIL: secure_tm_o={tm} after sensing with the strap at 0"
        await RisingEdge(dut.clk_i)
        self.tm_expect = 0
        self.logger.info("CTL-STRAP-INDEP: strap=0 secure_tm_o=0 after sensing")
        open_graded_window(TEST, self.logger)
        await self._toggle_test_en(strap=0)
        npins = len(self._pins())
        for path in sorted(self.pin_stuck):
            self.logger.info("OBS-TEST-EN-PINS: not_following=%s", path)
        self.logger.info(
            "OBS-TEST-EN-PINS: pins=%d clock_gater=%d axi_cell=%d follow_test_en_i=%d "
            "not_following=%d (test_en_i toggled at strap 1 and 0)",
            npins,
            len(self.walk["clock_gater"]),
            len(self.walk["axi_cell"]),
            npins - len(self.pin_stuck),
            len(self.pin_stuck),
        )
        self.logger.info(
            "CHK-STRAP-INDEP PASS: secure_tm_o=1 unchanged across %d test_en_i toggles at strap=1 "
            "and secure_tm_o=0 unchanged across %d at strap=0",
            3,
            3,
        )

        # Step 7: release the Key Manager (set-up, window closed).
        close_graded_window(self.logger)
        swrst = SepSwReset(self)
        swrst.value = await swrst.read_back()
        await swrst.release("km")
        for _ in range(TAP_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.km_cond_rst_probe_o) == 0x3:
                break
        assert self.rd(dut.km_cond_rst_probe_o) == 0x3, (
            "km_cond_rst taps did not both read 1 after the Key Manager release"
        )
        base = self._nets()
        assert all(base), (
            f"precondition FAIL: nets before the scan pulses {dict(zip([n[0] for n in NETS], base))}"
        )
        await RisingEdge(dut.clk_i)
        self.logger.info("SCAN-BASELINE LOG: nets_high=%d/%d", sum(base), N_NETS)

        # Step 8: control A, test_en_i = 0.
        open_graded_window(TEST, self.logger)
        a = await self._scan_pulse(0, "CHK-SCAN-IDLE")
        low = [(t, [NETS[i][0] for i, v in enumerate(vals) if v != 1]) for t, vals in a["samples"]]
        low = [x for x in low if x[1]]
        assert not low and a["samples"], (
            f"CHK-SCAN-IDLE FAIL: net(s) low with test_en_i=0 (samples={len(a['samples'])}): "
            f"{low[:4]}"
        )
        self.logger.info(
            "CHK-SCAN-IDLE PASS: scan_rst_ni low %d cycles test_en_i=0 nets_high=%d/%d samples=%d",
            cfg.w,
            N_NETS,
            N_NETS,
            len(a["samples"]),
        )

        # Step 9: leg B, test_en_i = 1.
        await RisingEdge(dut.clk_i)
        dut.test_en_i.value = 1
        hold = []
        for _ in range(H):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            hold.append(self._nets())
        bad = [v for v in hold if not all(v)]
        assert not bad, f"CHK-SCAN-REPLACE FAIL: a net low with scan_rst_ni=1 test_en_i=1: {bad[0]}"
        await RisingEdge(dut.clk_i)
        b = await self._scan_pulse(1, "CHK-SCAN-REPLACE")
        close_graded_window(self.logger)
        names = [n[0] for n in NETS]
        # Every clk_i edge from the scan_rst_ni fall to the last edge before the release.
        during = [(t, vals) for t, vals in b["samples"] if b["t_fall"] < t <= b["last_edge"]]
        high = [(t, [names[i] for i, v in enumerate(vals) if v != 0]) for t, vals in during]
        high = [x for x in high if x[1]]
        assert len(during) == cfg.w and not high, (
            f"CHK-SCAN-REPLACE FAIL: net(s) not low with scan_rst_ni=0 test_en_i=1 "
            f"(edges={len(during)} expected={cfg.w}): {high[:4]}"
        )
        not_low = [names[i] for i, v in enumerate(b["before_release"]) if v != 0]
        assert not not_low, (
            f"CHK-SCAN-REPLACE FAIL: net(s) not low on the last clk_i edge before the release "
            f"(t={b['last_edge']} ps): {not_low}"
        )
        after = [(t, vals) for t, vals in b["samples"] if t > b["t_rise"]]
        bad = [(t, [names[i] for i, v in enumerate(vals) if v != 1]) for t, vals in after]
        bad = [x for x in bad if x[1]]
        assert after and not bad, (
            f"CHK-SCAN-REPLACE FAIL: net(s) not high with scan_rst_ni=1 test_en_i=1 after the "
            f"release: {bad[:4]}"
        )
        t_rise = b["t_rise"]
        clk_e = [t for t in self.pins_clk.edge_times("clk_i") if t > t_rise]
        wdt_e = [t for t in self.pins_clk.edge_times("clk_wdt_i") if t > t_rise]
        assert clk_e and wdt_e, "CHK-SCAN-REPLACE FAIL: no clock edge recorded after the release"
        nclk, nwdt = clk_e[0], wdt_e[0]
        r_sep, r_aon = b["rises"]["sep_reset_n"], b["rises"]["aon_rst_n"]
        line = (
            f"nets_low={N_NETS - len(not_low)}/{N_NETS} low_edges={len(during)}; scan_rst_ni rose t={t_rise} "
            f"sep_reset_n rose t={r_sep} next_clk_i_edge t={nclk} aon_rst_n rose t={r_aon} "
            f"next_clk_wdt_i_edge t={nwdt}"
        )
        assert r_sep is not None and r_sep < nclk, f"CHK-SCAN-REPLACE FAIL: {line}"
        assert r_aon is not None and r_aon < nwdt, f"CHK-SCAN-REPLACE FAIL: {line}"
        for name in names:
            if name in ("sep_reset_n", "aon_rst_n"):
                continue
            r = b["rises"][name]
            self.logger.info(
                "OBS-SCAN-OFFSET: net=%s rise_t=%s offset_ps=%s",
                name,
                r,
                None if r is None else r - t_rise,
            )
        self.logger.info("CHK-SCAN-REPLACE PASS: %s", line)
        self.result_pass(TEST, seed, 3)
