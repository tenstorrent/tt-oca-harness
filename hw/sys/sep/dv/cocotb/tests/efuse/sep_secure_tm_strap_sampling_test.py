# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SECURE_TM clears at cold reset and samples the strap only at its sampling events.

Contract (``hw/sys/sep/doc/test_mode.adoc``, Entry and Exit;
``hw/sys/sep/doc/security_disable.adoc``, Reset Persistence;
``hw/sys/sep/doc/port_table.adoc``, ``secure_tm_req_i`` and ``secure_tm_o``):

* ``SECURE_TM`` clears when cold reset asserts.
* The strap ``secure_tm_req_i`` (bench pin ``test_en_strap_i``) is sampled at
  each fuse-sense completion and, with ``SEC_DIS`` asserted, once early after
  the cold-reset release. No other event samples it, and the sampled value is
  held until the next sampling event.

Legs, in this order: A (cold clear), B (four non-sampling events with
``secure_tm_o`` = 1 and the strap driven to 0 before the first event, so a
resample at an event reads 0), C (a strap change 1 to 0 and 0 to 1 after a capture), D0
(early-capture control, no match), E (late ``SEC_DIS``: the token arrives after
sensing with no later cold reset) and D (early capture with the match present,
strap 1, then strap 0). The ``SEC_DIS`` token is presented over the JTAG
AXI-Lite port ``j_axi`` with the token whose digest ``tb_top`` binds. A match
survives ``rst_ni`` (``security_disable.adoc``, Reset Persistence), so the
cold resets of leg D boot with the match present and no fuse sense runs.

``secure_tm_o``, ``sep_fuse_sense_done_o``, ``rst_ni`` and the strap are sampled
on every ``clk_i`` rising edge for the whole leaf.

Checkers:
  CHK-STM-CAPTURE  in leg D with the match present and the strap at 1,
                   ``secure_tm_o`` reads 1 with ``sep_fuse_sense_done_o`` low no
                   later than ``T_sense`` after the release, and keeps 1 after
                   the strap flips to 0. Control: in leg D0 (no match)
                   ``secure_tm_o`` reads 0 at the same cycle and follows the
                   strap only at sense completion.
  CHK-STM-RETAIN   in legs B, C and D ``secure_tm_o`` keeps its value on every
                   sample through every event and after every strap change. In
                   leg B the strap reads 0 and ``secure_tm_o`` holds 1 through
                   all four events, so a resample at an event changes it.
                   Control: leg A shows ``secure_tm_o`` = 1. The leg-B
                   ``wdt_rst_ni`` pulse reads ``sep_cpu_reset_n_o`` low, the
                   override pulse reads ``dbg_sep_reset_n_o`` low and, on the
                   full-CPU build, the ``dbg_rstb_i`` pulse reads
                   ``mpc_run_sync_probe_o`` low inside the pulse window, so
                   each graded event reaches the DUT. In both leg-D
                   boots ``lcc_security_disable_probe_o`` reads 1 on every
                   sample from the release to the end of the hold, so the
                   match is shown present (a lost match runs a sense that
                   ends past the leg-D windows, which the sense-done level
                   alone does not show).
  CHK-STM-CLEAR    with ``rst_ni`` low and the strap at 1, ``secure_tm_o`` reads 0
                   at the last ``clk_i`` edge before the release. Control: it
                   reads 1 before the reset.
  CHK-STM-LATE     in leg E, with no match at the boot, ``secure_tm_o`` stays 0
                   after the strap rises and the ``SEC_DIS`` token matches.
                   Control: leg D shows the early capture to 1.

``OBS-STM-CAPTURE0`` logs ``secure_tm_o`` of the strap-0 boot of leg D (the
cold-reset clear gives the same 0, so it is not graded as a capture). The
sampling at fuse-sense completion is a control here.

Environment choices (not from the specification): the hold H, the reset width,
the event pulse widths and the wait bounds below. The image is a PROD image
with the disable vectors of the real-sense eFuse tests; in PROD the JTAG port
reaches the token block.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense,
``+sep_edn_jtag_reset_waive`` for the ``sep_reset_n`` override pulse of leg B.
Verilator and VCS; the ``dbg_rstb_i`` event of leg B runs on VCS only. On the
CPU stub build no approved probe shows its reach, so it runs ungraded
(``OBS-STM-DBG-REACH``). The full-CPU entry (``--target default``,
``+sep_require_full_cpu``) grades it: with ``mpc_reset_run_req`` at 1 the
``mpc_run_sync_probe_o`` tap reads 0 inside the pulse. RAND-REP:
the seed draws ``c`` (8 to 200) and the order of the leg B events.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_lcc_golden import LC_PROD
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_MMR, sym
from seq_lib.sep_efuse_rma_token_seq import TOKEN_ERROR, TOKEN_MATCH, TOKEN_MISMATCH
from seq_lib.sep_sw_reset_seq import SW_RESET_N_RESET_DEFAULT, SepSwReset

TEST = "sep_secure_tm_strap_sampling_test"

_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
# The token whose SHA-256 digest tb_top binds as SEP_SEC_DISABLE_TOKEN (32 zero bytes).
_SEC_DIS_TOKEN = 0
_SEC_DIS_TOKEN_I = tuple(sym(f"EFUSE_MMR_SEC_DISABLE_TOKEN_I_{i}__REG_ADDR") for i in range(8))
_TOKEN_EOP = sym("EFUSE_MMR_TOKEN_EOP_REG_ADDR")
_EOP_SEC_DIS = EFUSE_MMR.field_mask("TOKEN_EOP", "secure_disable_token_go")
_SEC_DIS_MATCH = sym("EFUSE_MMR_SEC_DISABLE_TOKEN_MATCH_REG_ADDR")
_MATCH_MASK = EFUSE_MMR.field_mask("TOKEN_MATCH", "token_match_status")
_MATCH_LSB = EFUSE_MMR.field_lsb("TOKEN_MATCH", "token_match_status")

_HOLD = 256
_RST_LOW = 20
_PULSE = 16
_OVRD_CYCLES = 32
_SENSE_BOUND = 20_000
_STM_BOUND = 16
_TAP_BOUND = 256
_SYNC_BOUND = 16
_HMAC_BOUND = 4_096
_TOKEN_POLLS = 200

_EVENTS = ("wdt_rst_ni", "dbg_rstb_i", "sw_reset_n", "sep_reset_n_ovrd")


def _bit(sig) -> int | None:
    v = sig.value
    if not v.is_resolvable:
        return None
    return int(v) & 1


@pyuvm.test()
class sep_secure_tm_strap_sampling_test(sep_base_test):
    """secure_tm_o clears at cold reset and samples the strap only at a sampling event."""

    required_evidence = (
        "CHK-STM-CAPTURE",
        "CHK-STM-RETAIN",
        "CHK-STM-CLEAR",
        "CHK-STM-LATE",
    )

    # -- sampler -------------------------------------------------------------

    async def _sampler(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.rec.append(
                {
                    "rst": _bit(dut.rst_ni),
                    "strap": _bit(dut.test_en_strap_i),
                    "stm": _bit(dut.secure_tm_o),
                    "done": _bit(dut.sep_fuse_sense_done_o),
                    "sep": _bit(dut.dbg_sep_reset_n_o),
                    "cpu": _bit(dut.sep_cpu_reset_n_o),
                    "mpc": _bit(dut.mpc_run_sync_probe_o),
                    "secdis": _bit(dut.lcc_security_disable_probe_o),
                }
            )

    def _now(self) -> int:
        """Sample index of the current clk_i edge (call right after a RisingEdge)."""
        return len(self.rec)

    async def _edge(self) -> int:
        await RisingEdge(cocotb.top.clk_i)
        return self._now()

    async def _until(self, idx: int) -> None:
        while self._now() < idx:
            await RisingEdge(cocotb.top.clk_i)

    async def _wait_sample(self, key: str, want: int, bound: int, label: str) -> int:
        """Wait until a sample shows ``key`` == ``want``; return its index."""
        start = self._now()
        while True:
            await RisingEdge(cocotb.top.clk_i)
            last = len(self.rec) - 1
            if last >= start and self.rec[last][key] == want:
                return last
            if self._now() - start > bound:
                raise AssertionError(f"{label}: {key} did not read {want} within {bound} cycles")

    def _window(self, a: int, b: int, key: str = "stm") -> list:
        return [self.rec[i][key] for i in range(a, b + 1)]

    # -- stimulus --------------------------------------------------------------

    async def _cold_reset(self, strap: int | None = None) -> tuple[int, int]:
        """Pulse rst_ni for _RST_LOW cycles. Returns (assert index, release index)."""
        dut = cocotb.top
        await self._edge()
        if strap is not None:
            dut.test_en_strap_i.value = strap
            await self._edge()
        dut.rst_ni.value = 0
        a = self._now()
        await self._until(a + _RST_LOW)
        dut.rst_ni.value = 1
        return a, self._now()

    async def _cold_boot(self, strap: int, label: str) -> tuple[int, int]:
        """Cold boot with a real sense. Returns (release index, sense index)."""
        _a, rel = await self._cold_reset(strap)
        sense = await self._wait_sample("done", 1, _SENSE_BOUND, f"{label} sense")
        await self._wait_sample("sep", 1, _TAP_BOUND, f"{label} sep_reset_n")
        await self._edge()
        self._check_efuse_shadow_after_sense()
        self.logger.info(
            "BOOT %s strap=%d release=%d sense_done=%d (T=%d)",
            label,
            strap,
            rel,
            sense,
            sense - rel,
        )
        return rel, sense

    async def _stm_after_sense(self, sense: int, want: int, label: str) -> int:
        idx = await self._wait_sample("stm", want, _STM_BOUND, f"{label} secure_tm_o")
        assert idx >= sense, f"{label}: secure_tm_o={want} before the sense rise"
        return idx

    async def _hold(self, cycles: int = _HOLD) -> int:
        await self._until(self._now() + cycles)
        return self._now()

    async def _ev_wdt(self) -> None:
        dut = cocotb.top
        await self._edge()
        dut.wdt_rst_ni_i.value = 0
        w0 = self._now()
        await self._until(w0 + _PULSE)
        dut.wdt_rst_ni_i.value = 1
        w1 = self._now()
        await self._wait_sample("cpu", 1, _TAP_BOUND, "sep_cpu_reset_n after the wdt pulse")
        # The event is a CPU reset only if the pulse reached sep_cpu_reset_n.
        low = sum(1 for i in range(w0, w1) if self.rec[i]["cpu"] == 0)
        assert low > 0, (
            f"CHK-STM-RETAIN FAIL: leg=B event=wdt_rst_ni: sep_cpu_reset_n_o never read 0 "
            f"in the pulse window (samples {w0}..{w1 - 1}), so the event did not happen"
        )
        self.logger.info(
            "LEG-B wdt_rst_ni pulse reached sep_cpu_reset_n: low on %d of samples %d..%d",
            low,
            w0,
            w1 - 1,
        )

    async def _ev_dbg(self) -> None:
        dut = cocotb.top
        if not self.full_cpu:
            await self._edge()
            dut.dbg_rstb_i.value = 0
            await self._until(self._now() + _PULSE)
            dut.dbg_rstb_i.value = 1
            self.logger.info(
                "OBS-STM-DBG-REACH: dbg_rstb_i low for %d cycles; reach not shown (the CPU "
                "stub build has no debug module or run-request synchronizer for a probe to read)",
                _PULSE,
            )
            return
        # Full-CPU build: dbg_rstb_i resets the run-request synchronizer. With
        # mpc_reset_run_req at 1 its output reads 1, so a 0 inside the pulse
        # shows that the pulse reached the debug reset domain. The core samples
        # mpc_reset_run_req only right after its own reset, which this event
        # does not assert; the request returns to 0 before the next event.
        await self._edge()
        dut.mpc_reset_run_req.value = 1
        r0 = await self._wait_sample("mpc", 1, _SYNC_BOUND, "control: mpc_run_sync rise")
        await self._edge()
        dut.dbg_rstb_i.value = 0
        d0 = self._now()
        await self._until(d0 + _PULSE)
        dut.dbg_rstb_i.value = 1
        d1 = self._now()
        f1 = await self._wait_sample(
            "mpc", 1, _SYNC_BOUND, "mpc_run_sync after the dbg_rstb_i pulse"
        )
        dut.mpc_reset_run_req.value = 0
        await self._wait_sample("mpc", 0, _SYNC_BOUND, "mpc_run_sync after the request drop")
        low = sum(1 for i in range(d0, d1) if self.rec[i]["mpc"] == 0)
        assert low > 0, (
            f"CHK-STM-RETAIN FAIL: leg=B event=dbg_rstb_i: mpc_run_sync_probe_o never read 0 "
            f"in the pulse window (samples {d0}..{d1 - 1}), so the event did not happen"
        )
        self.logger.info(
            "LEG-B dbg_rstb_i pulse reached the debug reset domain: mpc_run_sync low on %d of "
            "samples %d..%d control_high_at=%d high_again_at=%d",
            low,
            d0,
            d1 - 1,
            r0,
            f1,
        )

    async def _ev_swrst(self) -> None:
        dut = cocotb.top
        self.swrst.value = SW_RESET_N_RESET_DEFAULT
        await self.swrst.park("hmac")
        for _ in range(_HMAC_BOUND):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.hmac_gated_rst_n_probe_o) == 0:
                break
        else:
            raise AssertionError(f"ip_rst_n[3] did not fall within {_HMAC_BOUND} cycles")
        await self.swrst.release("hmac")
        for _ in range(_HMAC_BOUND):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.hmac_gated_rst_n_probe_o) == 1:
                break
        else:
            raise AssertionError(f"ip_rst_n[3] did not rise within {_HMAC_BOUND} cycles")

    async def _ev_ovrd(self) -> None:
        dut = cocotb.top
        await self._edge()
        dut.jtag_sep_reset_n_val_i.value = 0
        dut.jtag_sep_reset_n_ovrd_i.value = 1
        o0 = self._now()
        await self._until(o0 + _OVRD_CYCLES)
        dut.jtag_sep_reset_n_ovrd_i.value = 0
        o1 = self._now()
        await self._wait_sample("sep", 1, _TAP_BOUND, "sep_reset_n after the override")
        # The event is a sep_reset_n pulse only if the override reached it.
        low = sum(1 for i in range(o0, o1) if self.rec[i]["sep"] == 0)
        assert low > 0, (
            f"CHK-STM-RETAIN FAIL: leg=B event=sep_reset_n_ovrd: dbg_sep_reset_n_o never read 0 "
            f"in the override window (samples {o0}..{o1 - 1}), so the event did not happen"
        )
        self.logger.info(
            "LEG-B sep_reset_n override reached sep_reset_n: low on %d of samples %d..%d",
            low,
            o0,
            o1 - 1,
        )

    def _require_match(self, a: int, b: int, chk: str, label: str) -> None:
        """The SEC_DIS match is present on every sample a..b of a leg-D boot.

        ``lcc_security_disable_probe_o`` is the security-disable state the
        life-cycle controller receives. A boot whose match was lost runs a
        fuse sense that ends after ``T_sense``, past the leg-D windows, so the
        sense-done level alone cannot show the match; this read does.
        """
        vals = self._window(a, b, "secdis")
        assert all(v == 1 for v in vals), (
            f"{chk} FAIL: {label}: security_disable read 0 at samples "
            f"{[a + i for i, v in enumerate(vals) if v != 1][:8]} (match_present=0 at this boot)"
        )
        self.logger.info("LEG-D %s match_present=1 on samples %d..%d", label, a, b)

    async def _present_sec_dis(self, token: int = _SEC_DIS_TOKEN) -> int:
        """Present the SEC_DIS token over j_axi; return the settled match code."""
        for i, addr in enumerate(_SEC_DIS_TOKEN_I):
            resp, _ = await self.jtag_axil_op(
                write=True, addr=addr, wdata=(token >> (32 * i)) & 0xFFFF_FFFF
            )
            assert resp == 0, f"SEC_DIS token word {i} write over j_axi resp={resp}"
        resp, _ = await self.jtag_axil_op(write=True, addr=_TOKEN_EOP, wdata=_EOP_SEC_DIS)
        assert resp == 0, f"TOKEN_EOP write over j_axi resp={resp}"
        code = None
        for _ in range(_TOKEN_POLLS):
            resp, raw = await self.jtag_axil_op(write=False, addr=_SEC_DIS_MATCH)
            assert resp == 0, f"SEC_DISABLE_TOKEN_MATCH read over j_axi resp={resp}"
            code = (raw & _MATCH_MASK) >> _MATCH_LSB
            if code in (TOKEN_MATCH, TOKEN_MISMATCH, TOKEN_ERROR):
                return code
        raise AssertionError(f"SEC_DIS match status did not settle (last code={code})")

    # -- scenario --------------------------------------------------------------

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        rng = SepSeededRng(seed)
        c = rng.randrange(8, 201)
        self.logger.info("DRAW c=%d", c)
        order = list(_EVENTS)
        rng.shuffle(order)
        self.logger.info("DRAW event_order=%s", ",".join(order))
        vcs = "vcs" in str(getattr(cocotb, "SIM_NAME", "") or "").lower()
        self.full_cpu = self.full_cpu_build()
        # The full-CPU testlist entry passes +sep_require_full_cpu: there the
        # dbg_rstb_i event is graded, so a stub build fails the leaf.
        if "sep_require_full_cpu" in cocotb.plusargs and not self.full_cpu:
            raise AssertionError(
                "CTL-FULL-CPU FAIL: +sep_require_full_cpu and the build has the CPU stub"
            )
        events = [e for e in order if vcs or e != "dbg_rstb_i"]
        graded = [e for e in events if self.full_cpu or e != "dbg_rstb_i"]
        ungraded = "" if graded == events else " ungraded=dbg_rstb_i(stub: no load)"
        self.logger.info(
            "CFG H=%d rst_low=%d pulse=%d ovrd=%d full_cpu=%d events_run=%s%s%s",
            _HOLD,
            _RST_LOW,
            _PULSE,
            _OVRD_CYCLES,
            int(self.full_cpu),
            ",".join(events),
            "" if vcs else " (dbg_rstb_i runs on VCS only)",
            ungraded,
        )
        close_graded_window()
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        self.swrst = SepSwReset(self)
        self.rec: list[dict] = []
        retain: list[str] = []

        # Bring-up with the strap at 1: the first cold boot of leg A.
        self.drive_idle_defaults(dut, cpu_run=False)
        dut.test_en_strap_i.value = 1
        await self.assert_cold_reset(dut)
        self.start_clocks(dut)
        cocotb.start_soon(self._sampler())
        await self._until(_RST_LOW)
        dut.rst_ni.value = 1
        self.cfg.reset_done.set()
        sense = await self._wait_sample("done", 1, _SENSE_BOUND, "leg A sense")
        await self._wait_sample("sep", 1, _TAP_BOUND, "leg A sep_reset_n")
        await self._edge()
        self._check_efuse_shadow_after_sense()

        # Leg A: control of CHK-STM-CLEAR and CHK-STM-RETAIN.
        try:
            a_one = await self._stm_after_sense(sense, 1, "leg A")
        except AssertionError as exc:
            raise AssertionError(f"CHK-STM-CLEAR FAIL: control: {exc}") from None
        self.logger.info(
            "CTL-STM-LEGA: strap=1 secure_tm_o=1 at sample %d (sense %d)", a_one, sense
        )

        open_graded_window(TEST, self.logger)
        a, rel = await self._cold_reset()
        await self._edge()
        low = self._window(a, rel - 1)
        strap_low = self._window(a, rel - 1, "strap")
        assert all(s == 1 for s in strap_low), f"leg A: strap not 1 during the reset: {strap_low}"
        assert low[-1] == 0, (
            f"CHK-STM-CLEAR FAIL: strap=1 rst_ni low, secure_tm_o={low[-1]} at the last clk_i "
            f"edge (sample {rel - 1}) before the release"
        )
        self.logger.info(
            "CHK-STM-CLEAR PASS: rst_ni low -> secure_tm_o=0 at cycle %d strap=1 edges_low=%d "
            "ones_while_low=%d control_legA=1",
            rel - 1 - a,
            len(low),
            sum(1 for v in low if v == 1),
        )
        sense = await self._wait_sample("done", 1, _SENSE_BOUND, "leg A resense")
        await self._stm_after_sense(sense, 1, "leg A resense")
        await self._wait_sample("sep", 1, _TAP_BOUND, "leg A sep_reset_n")
        self._check_efuse_shadow_after_sense()

        # Leg B: non-sampling events with secure_tm_o = 1 and the strap at 0, so a
        # resample of the strap at any event reads 0.
        fl = await self._edge()
        dut.test_en_strap_i.value = 0
        await self._edge()
        b0 = await self._edge()
        run = {
            "wdt_rst_ni": self._ev_wdt,
            "dbg_rstb_i": self._ev_dbg,
            "sw_reset_n": self._ev_swrst,
            "sep_reset_n_ovrd": self._ev_ovrd,
        }
        for ev in events:
            if ev not in graded:
                # Stub build: dbg_rstb_i has no load, so the event is run with
                # the graded window closed and logged only.
                close_graded_window(self.logger)
                e0 = await self._edge()
                await run[ev]()
                e1 = await self._hold()
                vals = self._window(e0, e1 - 1)
                self.logger.info(
                    "OBS-STM-UNGRADED: event=%s samples=%d..%d secure_tm_o_ones=%d/%d",
                    ev,
                    e0,
                    e1 - 1,
                    sum(1 for v in vals if v == 1),
                    len(vals),
                )
                open_graded_window(TEST, self.logger)
                continue
            e0 = await self._edge()
            await run[ev]()
            e1 = await self._hold()
            vals = self._window(e0, e1 - 1)
            assert all(v == 1 for v in vals), (
                f"CHK-STM-RETAIN FAIL: leg=B event={ev} strap=0 secure_tm_o left 1 at samples "
                f"{[e0 + i for i, v in enumerate(vals) if v != 1][:8]}"
            )
            self.logger.info("LEG-B event=%s strap=0 samples=%d..%d secure_tm_o=1", ev, e0, e1 - 1)
        b1 = self._now() - 1
        strap_b = self._window(b0, b1, "strap")
        assert all(s == 0 for s in strap_b), "leg B: the strap did not stay at 0"
        whole = self._window(fl, b1)
        assert all(v == 1 for v in whole), (
            f"CHK-STM-RETAIN FAIL: leg=B strap=0 secure_tm_o left 1 at samples "
            f"{[fl + i for i, v in enumerate(whole) if v != 1][:8]}"
        )
        retain.append(
            f"leg=B events={','.join(graded)}{ungraded} strap=0 value=1 cycles={b1 - fl + 1}"
        )
        close_graded_window(self.logger)

        # Leg C, strap 1 -> 0.
        _rel, sense = await self._cold_boot(1, "leg C1")
        await self._stm_after_sense(sense, 1, "leg C1")
        open_graded_window(TEST, self.logger)
        await self._until(sense + c)
        dut.test_en_strap_i.value = 0
        f0 = self._now()
        f1 = await self._hold()
        vals = self._window(f0, f1 - 1)
        assert all(v == 1 for v in vals), (
            f"CHK-STM-RETAIN FAIL: leg=C strap 1->0 at sample {f0} (sense+{c}): secure_tm_o "
            f"left 1 at samples {[f0 + i for i, v in enumerate(vals) if v != 1][:8]}"
        )
        retain.append(f"leg=C events=strap_1to0@sense+{c} value=1 cycles={f1 - f0}")
        close_graded_window(self.logger)

        # Leg C, strap 0 -> 1.
        _rel, sense = await self._cold_boot(0, "leg C0")
        await self._until(sense + _STM_BOUND)
        assert self.rec[-1]["stm"] == 0, "leg C0: secure_tm_o is not 0 after a strap-0 sense"
        open_graded_window(TEST, self.logger)
        await self._until(sense + c)
        dut.test_en_strap_i.value = 1
        f0 = self._now()
        f1 = await self._hold()
        vals = self._window(f0, f1 - 1)
        assert all(v == 0 for v in vals), (
            f"CHK-STM-RETAIN FAIL: leg=C strap 0->1 at sample {f0} (sense+{c}): secure_tm_o "
            f"left 0 at samples {[f0 + i for i, v in enumerate(vals) if v != 0][:8]}"
        )
        retain.append(f"leg=C events=strap_0to1@sense+{c} value=0 cycles={f1 - f0}")
        close_graded_window(self.logger)

        # Leg D0: early-capture control, no match, strap 1.
        d0_rel, d0_sense = await self._cold_boot(1, "leg D0")
        d0_one = await self._stm_after_sense(d0_sense, 1, "leg D0")
        t_sense = d0_sense - d0_rel
        pre = self._window(d0_rel, d0_sense - 1)
        assert all(v == 0 for v in pre), (
            f"leg D0 control FAIL: secure_tm_o=1 before sense completion without a match at "
            f"samples {[d0_rel + i for i, v in enumerate(pre) if v != 0][:8]}"
        )
        self.logger.info(
            "CTL-STM-D0: match_present=0 strap=1 secure_tm_o=0 from release %d to sense %d, 1 at "
            "%d; T_sense=%d",
            d0_rel,
            d0_sense,
            d0_one,
            t_sense,
        )

        # Leg E: late SEC_DIS.
        _rel, sense = await self._cold_boot(0, "leg E")
        await self._until(sense + _STM_BOUND)
        assert self.rec[-1]["stm"] == 0, "leg E: secure_tm_o is not 0 after a strap-0 sense"
        self.logger.info("LEG-E match_present=0 (sense completed at sample %d)", sense)
        open_graded_window(TEST, self.logger)
        await self._edge()
        dut.test_en_strap_i.value = 1
        e0 = self._now()
        code = await self._present_sec_dis()
        sec_dis = self.rd(dut.lcc_security_disable_probe_o)
        assert code == TOKEN_MATCH and sec_dis == 1, (
            f"leg E precondition FAIL: SEC_DIS token code=0x{code:02x} security_disable={sec_dis}, "
            f"want MATCH 0x{TOKEN_MATCH:02x} and 1"
        )
        await self._edge()
        tok = self._now()
        e1 = await self._hold()
        late = self._window(e0, e1 - 1)
        assert all(v == 0 for v in late), (
            f"CHK-STM-LATE FAIL: match_present=0 strap=1 SEC_DIS late: secure_tm_o left 0 at "
            f"samples {[e0 + i for i, v in enumerate(late) if v != 0][:8]}"
        )
        self.logger.info("LEG-E strap rise %d token matched by %d hold end %d", e0, tok, e1)

        # Leg D, strap 1: early capture with the match present.
        _a, rel = await self._cold_reset()
        await self._until(rel + 2)
        self._require_match(rel, rel, "CHK-STM-CAPTURE", "strap=1 release")
        cap = None
        while self._now() <= rel + t_sense:
            await RisingEdge(dut.clk_i)
            last = len(self.rec) - 1
            if last >= rel and self.rec[last]["stm"] == 1:
                cap = next(i for i in range(rel, last + 1) if self.rec[i]["stm"] == 1)
                break
        assert cap is not None, (
            f"CHK-STM-CAPTURE FAIL: match_present=1 strap=1: secure_tm_o did not read 1 within "
            f"T_sense={t_sense} cycles of the release"
        )
        assert self.rec[cap]["done"] == 0, (
            f"CHK-STM-CAPTURE FAIL: secure_tm_o=1 at sample {cap} with sense_done=1; "
            "match_present=0 at this boot"
        )
        await self._until(cap + c)
        dut.test_en_strap_i.value = 0
        f0 = self._now()
        f1 = await self._hold()
        after = self._window(cap, f1 - 1)
        self._require_match(rel, f1 - 1, "CHK-STM-CAPTURE", "strap=1 window")
        done_d = self._window(rel, f1 - 1, "done")
        assert all(v == 0 for v in done_d), (
            "leg D precondition FAIL: sep_fuse_sense_done_o rose, so the token did not match "
            "(match_present=0 at this boot)"
        )
        assert all(v == 1 for v in after), (
            f"CHK-STM-CAPTURE FAIL: secure_tm_o left 1 after the capture at samples "
            f"{[cap + i for i, v in enumerate(after) if v != 1][:8]} (strap flip at {f0})"
        )
        d0_same = self.rec[d0_rel + (cap - rel)]["stm"]
        assert d0_same == 0, (
            f"CHK-STM-CAPTURE FAIL: control leg D0 read {d0_same} at the same cycle"
        )
        self.logger.info(
            "CHK-STM-CAPTURE PASS: leg=D match_present=1 strap=1 secure_tm_o=1 at release+%d "
            "sense_done=0 after_flip=1 control_D0=%d T_sense=%d flip=release+%d",
            cap - rel,
            d0_same,
            t_sense,
            f0 - rel,
        )
        retain.append(f"leg=D events=strap_1to0@capture+{c} value=1 cycles={f1 - f0}")

        # Leg D, strap 0 (retention leg).
        _a, rel = await self._cold_reset()
        await self._until(rel + c)
        obs = self.rec[-1]
        self.logger.info(
            "OBS-STM-CAPTURE0: match_present=1 strap=0 secure_tm_o=%s sense_done=%s at release+%d",
            obs["stm"],
            obs["done"],
            c - 1,
        )
        dut.test_en_strap_i.value = 1
        f0 = self._now()
        f1 = await self._hold()
        vals = self._window(f0, f1 - 1)
        self._require_match(rel, f1 - 1, "CHK-STM-RETAIN", "strap=0 window")
        done_d = self._window(rel, f1 - 1, "done")
        assert all(v == 0 for v in done_d), (
            "leg D strap 0 precondition FAIL: sep_fuse_sense_done_o rose (match_present=0)"
        )
        assert all(v == 0 for v in vals), (
            f"CHK-STM-RETAIN FAIL: leg=D strap 0->1 at release+{c}: secure_tm_o left 0 at samples "
            f"{[f0 + i for i, v in enumerate(vals) if v != 0][:8]}"
        )
        retain.append(f"leg=D events=strap_0to1@release+{c} value=0 cycles={f1 - f0}")
        close_graded_window(self.logger)

        # Evaluate the controls read at the end of the leaf.
        ones = sum(1 for r in self.rec if r["stm"] == 1)
        assert ones > 0, "CHK-STM-RETAIN FAIL: secure_tm_o never read 1 in the leaf"
        for line in retain:
            self.logger.info("CHK-STM-RETAIN PASS: %s control_legA=1", line)
        self.logger.info(
            "CHK-STM-LATE PASS: match_present=0 strap=1 SEC_DIS late secure_tm_o=0 cycles=%d "
            "control_legD=1",
            len(late),
        )
        self.result_pass(TEST, seed, len(self.required_evidence))
