# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cold boot release order of the power-good, cold and primary resets.

Contract SMU_SMC_BOOT_004, anchor smu_smc_cold_boot_release_order_test.
Spec: clk_rst.adoc Reset Architecture, Power-Good and Cold Reset, Primary and Warm Reset,
Reset Synchronization; port_table.adoc rst_cold_ni, powergood_i, rst_primary_*_no rows.

The stimulus is powergood_i, rst_cold_ni and jtag_trst only. Two samplers read the stable
power-good, the stable cold reset and the primary resets on every clk_ref_i and clk_smu_i edge.
Counts that the waived findings SF-008 and SF-009 leave open are logged and never compared.
SF-007/SF-009 observe-only legs per the supervisor record: the order between the exported stable
cold pin and the primary outputs is logged; the primary outputs are compared for holding 0 while
the cold reset is asserted and for releasing within the bounded wait.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.smu_tb_pins import cold_stable_reset, smc_primary_reset

PG_STABLE_MIN_EDGES = 32
COLD_EXT_MIN_EDGES = 255
COLD_LOW_EDGES_A = 600
COLD_LOW_EDGES_B = 600
COLD_RELEASE_WAIT_EDGES = 64
COLD_PULSE_EDGES = 64
WAIT_BOUND = 5000
SAMPLER_BOUND = 40000
TAP_RESET_PULSES = 16
SITE_NAMES = (
    "S1_assert",
    "S3_pg_stable_rise",
    "S4_cold_release",
    "S5_cold_release_after_reassert",
    "S5_smc_assert",
    "S5_ref_assert",
    "S6_smc_rise_A",
    "S6_ref_rise_A",
    "S6_smc_rise_B",
    "S6_ref_rise_B",
    "S6_smc_sampler",
    "S6_ref_sampler",
)


def _bit(sig, name: str) -> int:
    val = sig.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val) & 1


def _rises(values: list[int], start: int, stop: int) -> list[int]:
    return [k for k in range(max(start, 1), stop) if values[k - 1] == 0 and values[k] == 1]


class smu_smc_cold_boot_release_order_test_seq:
    """Leaf-driven cold boots observed on the boundary reset pins."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.step_ts: dict[str, float] = {}
        self.sites = {
            name: {"bound": 0, "count": 0, "last": "none", "expired": 0} for name in SITE_NAMES
        }
        self.stop = False
        self.smc = {"prim": [], "cold": []}
        self.ref = {"prim": [], "cold": [], "pg": []}

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, text: str) -> None:
        self._log(f"CELL {name} {text}")

    def _pins(self) -> dict[str, int]:
        dut = self.dut
        return {
            "pg": _bit(dut.obs_powergood_stable_o, "obs_powergood_stable_o"),
            "cold": _bit(cold_stable_reset(dut), "rst_cold_stable_ref_clk_no"),
            "smc": _bit(smc_primary_reset(dut), "rst_primary_smc_clk_n_o"),
            "ref": _bit(dut.rst_primary_ref_clk_no, "rst_primary_ref_clk_no"),
        }

    async def _sampler(self, site: str, clk, rec: dict, prim_sig, prim_name: str) -> None:
        r = self.sites[site]
        r["bound"] = SAMPLER_BOUND
        for n in range(SAMPLER_BOUND):
            await RisingEdge(clk)
            rec["prim"].append(_bit(prim_sig, prim_name))
            rec["cold"].append(_bit(cold_stable_reset(self.dut), "rst_cold_stable_ref_clk_no"))
            if "pg" in rec:
                rec["pg"].append(_bit(self.dut.obs_powergood_stable_o, "obs_powergood_stable_o"))
            r["count"] = n + 1
            r["last"] = f"prim={rec['prim'][-1]} cold={rec['cold'][-1]}"
            if self.stop:
                return
        r["expired"] = 1
        raise AssertionError(f"TIMEOUT {site}: still running after {SAMPLER_BOUND} edges")

    async def _wait(self, site: str, cond, bound: int = WAIT_BOUND) -> int:
        """Edges of clk_ref_i until cond() holds, with the site's bound and last state."""
        r = self.sites[site]
        r["bound"] = bound
        for n in range(bound):
            await RisingEdge(self.dut.clk_ref_i)
            pins = self._pins()
            r["count"] = n + 1
            r["last"] = " ".join(f"{k}={v}" for k, v in pins.items())
            if cond(pins):
                return n + 1
        r["expired"] = 1
        raise AssertionError(f"TIMEOUT {site}: bound {bound} clk_ref, last {r['last']}")

    async def _wait_rises(self, site: str, rec: dict, start: int) -> int:
        """Edges of clk_ref_i until the sampler has recorded a primary rise at or after start."""
        r = self.sites[site]
        r["bound"] = WAIT_BOUND
        for n in range(WAIT_BOUND):
            seen = _rises(rec["prim"], start, len(rec["prim"]))
            r["count"] = n + 1
            r["last"] = f"prim={rec['prim'][-1] if rec['prim'] else 'none'} rises={len(seen)}"
            if seen:
                return n + 1
            await RisingEdge(self.dut.clk_ref_i)
        r["expired"] = 1
        raise AssertionError(f"TIMEOUT {site}: bound {WAIT_BOUND} clk_ref, last {r['last']}")

    def _first_zero(self, site: str, rec: dict, start: int, stop: int) -> int:
        """Index of the first sample at or after start where the primary output reads 0."""
        r = self.sites[site]
        r["bound"] = WAIT_BOUND
        for n in range(min(WAIT_BOUND, stop - start)):
            r["count"] = n + 1
            r["last"] = f"prim={rec['prim'][start + n]}"
            if rec["prim"][start + n] == 0:
                return start + n
        r["expired"] = 1
        raise AssertionError(f"TIMEOUT {site}: bound {WAIT_BOUND}, last {r['last']}")

    async def _hold_low_window(self, edges: int, state: dict) -> None:
        """Hold rst_cold_ni low; the stable cold reset may not rise once it has read 0."""
        for _ in range(edges):
            await RisingEdge(self.dut.clk_ref_i)
            cold = self._pins()["cold"]
            if cold == 0:
                state["seen0"] = True
            elif state["seen0"]:
                state["viol"] += 1
            if not state["seen0"]:
                state["pre_edges"] += 1

    def _window(self, rec: dict, start: int, stop: int, label: str) -> dict:
        """Rise and post-rise checks of one sampler over one boot window."""
        prim_r = _rises(rec["prim"], start, stop)
        cold_r = _rises(rec["cold"], start, stop)
        after = 0
        if prim_r:
            after = sum(1 for v in rec["prim"][prim_r[-1] + 1 : stop] if v == 0)
        return {"prim_rises": prim_r, "cold_rises": cold_r, "post_rise_zero": after, "label": label}

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        ref_clk = dut.clk_ref_i

        # S1: leaf-driven cold boot start and samplers.
        self._mark("S1", "power-good and cold reset low, samplers armed")
        handle = cold_stable_reset(dut)
        self._cell("cold_pin", f"handle={getattr(handle, '_name', handle)}")
        smc_task = cocotb.start_soon(
            self._sampler(
                "S6_smc_sampler",
                dut.clk_smu_i,
                self.smc,
                smc_primary_reset(dut),
                "rst_primary_smc_clk_n_o",
            )
        )
        ref_task = cocotb.start_soon(
            self._sampler(
                "S6_ref_sampler",
                ref_clk,
                self.ref,
                dut.rst_primary_ref_clk_no,
                "rst_primary_ref_clk_no",
            )
        )
        a_hold_start = (len(self.smc["prim"]), len(self.ref["prim"]))
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        s1_state = {"seen": False, "viol": 0}

        def _s1_cond(pins: dict[str, int]) -> bool:
            if pins["cold"] == 0:
                s1_state["seen"] = True
            elif s1_state["seen"]:
                s1_state["viol"] += 1
            return not any(pins.values())

        n1 = await self._wait("S1_assert", _s1_cond)
        self._log(f"CHK-BOOT-COLD-HELD: s1_assert_edges={n1}")

        # S2: cold input high while power-good is low.
        self._mark("S2", "rst_cold_ni high with powergood_i low")
        dut.rst_cold_ni.value = 1
        pg_nonzero = 0
        cold_nonzero_a = s1_state["viol"]
        cold_nonzero_s2 = 0
        for _ in range(COLD_LOW_EDGES_A):
            await RisingEdge(ref_clk)
            pins = self._pins()
            pg_nonzero += pins["pg"]
            cold_nonzero_s2 += pins["cold"]
        self._cell(
            "cold_rise_while_powergood_low",
            f"obs_powergood_stable_o_nonzero={pg_nonzero} "
            f"rst_cold_stable_ref_clk_no_nonzero={cold_nonzero_s2} count={COLD_LOW_EDGES_A}",
        )
        sb.expect_eq(
            "stable power-good and stable cold reset stay 0 with power-good low",
            (pg_nonzero, cold_nonzero_s2),
            (0, 0),
            evidence="BOOT_PG_HOLD",
        )

        # S3: power-good rise to the stable power-good rise.
        self._mark("S3", "powergood_i rise, count to obs_powergood_stable_o")
        a_hold_end = (len(self.smc["prim"]), len(self.ref["prim"]))
        dut.powergood_i.value = 1
        dut.jtag_trst.value = 1
        tap_task = cocotb.start_soon(self.test.jtag_tap_reset(TAP_RESET_PULSES))
        cold_first: dict[str, int | None] = {"n": None}
        edge_no = {"n": 0}

        def _s3_cond(pins: dict[str, int]) -> bool:
            edge_no["n"] += 1
            if pins["cold"] == 1 and cold_first["n"] is None:
                cold_first["n"] = edge_no["n"]
            return pins["pg"] == 1

        n3 = await self._wait("S3_pg_stable_rise", _s3_cond)
        self._log(f"CHK-BOOT-PG-STRETCH: pg_rise_to_stable_edges={n3}")
        self._cell("powergood_rise_to_stable_rise_latency", f"obs_powergood_stable_o=1 count={n3}")

        # S4: later input rise to the stable cold release.
        self._mark("S4", "count from the later of powergood_i and rst_cold_ni rise to cold release")
        if cold_first["n"] is not None:
            n4 = cold_first["n"]
        else:
            n4 = n3 + await self._wait("S4_cold_release", lambda p: p["cold"] == 1)
        if cold_first["n"] is not None:
            self.sites["S4_cold_release"].update(
                bound=WAIT_BOUND, count=n4, last=f"cold=1 edges={n4}"
            )
        self._log(f"CHK-BOOT-COLD-EXT: later_rise_to_cold_stable_edges={n4}")
        self._cell("release_extension_255", f"rst_cold_stable_ref_clk_no=1 count={n4}")
        sb.expect_eq(
            "stable cold reset is 0 for the first 255 clk_ref after the later rise",
            n4 >= COLD_EXT_MIN_EDGES,
            True,
            evidence="BOOT_COLD_EXT",
        )
        await tap_task

        # S6 boot A: primary rises behind the stable cold rise.
        self._log("boot A primary reset rises")
        await self._wait_rises("S6_smc_rise_A", self.smc, 0)
        await self._wait_rises("S6_ref_rise_A", self.ref, 0)
        end_a_smc = len(self.smc["prim"])
        end_a_ref = len(self.ref["prim"])
        pg_rises_a = len(_rises(self.ref["pg"], 0, end_a_ref))
        sb.expect_eq(
            "stable power-good is 0 for the first 32 clk_ref and rises exactly once",
            (n3 >= PG_STABLE_MIN_EDGES, pg_rises_a),
            (True, 1),
            evidence="BOOT_PG_STRETCH",
        )

        # S5 boot B: cold input low, release, second pulse inside the extension.
        self._mark("S5", "boot B cold input low 600, release, 64-edge pulse, release")
        start_b_smc = end_a_smc
        start_b_ref = end_a_ref
        held = {"seen0": False, "viol": 0, "pre_edges": 0}
        dut.rst_cold_ni.value = 0
        b_fall = (len(self.smc["prim"]), len(self.ref["prim"]))
        await self._hold_low_window(COLD_LOW_EDGES_B, held)
        b_hold_end = (len(self.smc["prim"]), len(self.ref["prim"]))
        b_hold_start = (
            self._first_zero("S5_smc_assert", self.smc, b_fall[0], b_hold_end[0]),
            self._first_zero("S5_ref_assert", self.ref, b_fall[1], b_hold_end[1]),
        )
        dut.rst_cold_ni.value = 1
        ext_nonzero = 0
        for _ in range(COLD_RELEASE_WAIT_EDGES):
            await RisingEdge(ref_clk)
            ext_nonzero += self._pins()["cold"]
        dut.rst_cold_ni.value = 0
        viol_before_pulse = held["viol"]
        await self._hold_low_window(COLD_PULSE_EDGES, held)
        pulse_viol = held["viol"] - viol_before_pulse + ext_nonzero
        dut.rst_cold_ni.value = 1
        n5 = await self._wait("S5_cold_release_after_reassert", lambda p: p["cold"] == 1)
        first_release_to_rise = COLD_RELEASE_WAIT_EDGES + COLD_PULSE_EDGES + n5
        self._log(
            f"CHK-BOOT-COLD-REASSERT: first_release_to_rise={first_release_to_rise} "
            f"later_release_to_rise={n5} pulse_edges={COLD_PULSE_EDGES} "
            f"restarted={n5 >= COLD_EXT_MIN_EDGES}"
        )
        self._log(
            f"CHK-BOOT-COLD-HELD: cold_assert_after_low_edges={held['pre_edges']} "
            f"nonzero_in_extension={ext_nonzero}"
        )
        self._cell(
            "cold_held_while_input_low",
            f"rst_cold_stable_ref_clk_no_viol_a={cold_nonzero_a + cold_nonzero_s2} "
            f"viol_b={held['viol']} ext_nonzero={ext_nonzero} "
            f"count={COLD_LOW_EDGES_B + COLD_PULSE_EDGES}",
        )
        sb.expect_eq(
            "stable cold reset stays 0 for as long as rst_cold_ni is low",
            (cold_nonzero_a + cold_nonzero_s2, held["viol"], ext_nonzero, held["seen0"]),
            (0, 0, 0, True),
            evidence="BOOT_COLD_HELD",
        )
        self._cell("reassert_during_extension", f"rst_cold_stable_ref_clk_no=1 count={n5}")
        sb.expect_eq(
            "stable cold reset holds 0 while the input is low and rises within the bound",
            (pulse_viol, n5 <= WAIT_BOUND, n5 >= COLD_EXT_MIN_EDGES),
            (0, True, True),
            evidence="BOOT_COLD_REASSERT",
        )

        # S6 boot B.
        self._mark("S6", "boot B primary reset rises")
        await self._wait_rises("S6_smc_rise_B", self.smc, start_b_smc)
        await self._wait_rises("S6_ref_rise_B", self.ref, start_b_ref)

        # S7: close the samplers and evaluate order and edges.
        self._mark("S7", "primary reset order and destination-clock edges")
        self.stop = True
        await smc_task
        await ref_task
        end_smc = len(self.smc["prim"])
        end_ref = len(self.ref["prim"])
        wins = {
            ("A", "smc"): self._window(self.smc, 0, end_a_smc, "A smc"),
            ("A", "ref"): self._window(self.ref, 0, end_a_ref, "A ref"),
            ("B", "smc"): self._window(self.smc, start_b_smc, end_smc, "B smc"),
            ("B", "ref"): self._window(self.ref, start_b_ref, end_ref, "B ref"),
        }
        for idx, (rec, name, token, cell, wkey) in enumerate(
            (
                (
                    self.smc,
                    "rst_primary_smc_clk_n_o",
                    "BOOT_PRIM_SMC_ORDER",
                    "smc_clk_primary_not_before_cold",
                    "smc",
                ),
                (
                    self.ref,
                    "rst_primary_ref_clk_no",
                    "BOOT_PRIM_REF_ORDER",
                    "ref_clk_primary_not_before_cold",
                    "ref",
                ),
            )
        ):
            early = sum(1 for p, c in zip(rec["prim"], rec["cold"]) if p == 1 and c == 0)
            runs = []
            for k, (p, c) in enumerate(zip(rec["prim"], rec["cold"])):
                if p == 1 and c == 0:
                    if runs and runs[-1][1] == k - 1:
                        runs[-1][1] = k
                    else:
                        runs.append([k, k])
            lead = {
                boot: (
                    wins[(boot, wkey)]["cold_rises"][-1] - wins[(boot, wkey)]["prim_rises"][-1]
                    if wins[(boot, wkey)]["cold_rises"] and wins[(boot, wkey)]["prim_rises"]
                    else None
                )
                for boot in ("A", "B")
            }
            self._log(
                f"CHK-{token.replace('_', '-')}: prim1_cold0_samples={early} runs={runs} "
                f"lead_clk_{wkey}={lead} samples={len(rec['prim'])} "
                "(SF-007/SF-009 observe-only)"
            )
            a0, a1 = a_hold_start[idx], a_hold_end[idx]
            b0, b1 = b_hold_start[idx], b_hold_end[idx]
            first_cold0 = next((k for k in range(b_fall[idx], b1) if rec["cold"][k] == 0), None)
            self._log(
                f"CHK-{token.replace('_', '-')}: assert_latency_edges={b0 - b_fall[idx]} "
                f"vs_exported_pin={None if first_cold0 is None else b0 - first_cold0} "
                "(SF-009 observe-only)"
            )
            hold_viol = sum(rec["prim"][a0:a1]) + sum(rec["prim"][b0:b1])
            viol_idx = [k for k in range(a0, a1) if rec["prim"][k]] + [
                k for k in range(b0, b1) if rec["prim"][k]
            ]
            self._log(f"CHK-{token.replace('_', '-')}: hold_violation_samples={viol_idx}")
            self._cell(
                cell,
                f"{name}=1_in_hold_windows count={hold_viol} windows=A[{a0},{a1}) B[{b0},{b1})",
            )
            sb.expect_eq(
                f"{name} reads 0 at every sample while the cold reset is asserted",
                hold_viol,
                0,
                evidence=token,
            )

        released = {}
        edge_obs = {}
        for key, w in wins.items():
            rec = self.smc if key[1] == "smc" else self.ref
            end = end_a_smc if key == ("A", "smc") else end_a_ref if key[0] == "A" else None
            last = rec["prim"][(end if end is not None else len(rec["prim"])) - 1]
            released[key] = bool(w["prim_rises"]) and last == 1
            edge_obs[key] = (len(w["prim_rises"]), w["post_rise_zero"])
            w["latency"] = (
                w["prim_rises"][-1] - w["cold_rises"][-1]
                if w["prim_rises"] and w["cold_rises"]
                else -1
            )
        for boot in ("A", "B"):
            sw, rw = wins[(boot, "smc")], wins[(boot, "ref")]
            self._log(
                f"CHK-BOOT-COLD-TO-PRIMARY: boot={boot} smc_rise={sw['prim_rises']} "
                f"smc_cold_rise={sw['cold_rises']} ref_rise={rw['prim_rises']} "
                f"ref_cold_rise={rw['cold_rises']} (SF-007/SF-009 observe-only)"
            )
        self._cell(
            "primary_after_stable_cold_both_domains",
            " ".join(f"{b}_{p}_released={released[(b, p)]}" for b, p in wins),
        )
        sb.expect_eq(
            "each primary reset rises within its bound and is 1 at the end of each boot",
            released,
            {key: True for key in wins},
            evidence="BOOT_COLD_TO_PRIMARY",
        )
        self._cell(
            "release_edge_on_dest_clk",
            " ".join(f"{b}_{p}=(rises,post_zero){edge_obs[(b, p)]}" for b, p in wins),
        )
        sb.expect_eq(
            "each primary reset has one release edge per boot and stays released",
            edge_obs,
            {key: (1, 0) for key in wins},
            evidence="BOOT_PRIM_EDGE",
        )
        for boot in ("A", "B"):
            self._log(
                f"CHK-BOOT-PRIM-EDGE: boot={boot} "
                f"smc_latency_dest_clks={wins[(boot, 'smc')]['latency']} "
                f"ref_latency_dest_clks={wins[(boot, 'ref')]['latency']}"
            )

        # S8: timeout records and ordered fence.
        self._mark("S8", "TIMEOUT: bounded waits and last state")
        lines = []
        for site, rec in self.sites.items():
            state = "EXPIRED" if rec["expired"] else "ok"
            lines.append(
                f"{site}: bound={rec['bound']} {state} count={rec['count']} last={rec['last']}"
            )
        for line in lines:
            self._log(f"TIMEOUT-PATH {line}")
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired}")
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq(
            "bounded wait sites named by the contract",
            sorted(self.sites),
            sorted(
                [
                    "S1_assert",
                    "S3_pg_stable_rise",
                    "S4_cold_release",
                    "S5_cold_release_after_reassert",
                    "S5_smc_assert",
                    "S5_ref_assert",
                    "S6_smc_rise_A",
                    "S6_ref_rise_A",
                    "S6_smc_rise_B",
                    "S6_ref_rise_B",
                    "S6_smc_sampler",
                    "S6_ref_sampler",
                ]
            ),
        )

        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<S6<S7<S8<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 9, evidence="CHK-NONVAC")
        dut.powergood_i.value = 1
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
