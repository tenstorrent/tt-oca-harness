# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The RMA_SIP raw 4'b0011 LC_STATE pair reaches every SMU observation point as 0xC3.

Spec: hw/sys/sep/doc/otp_fuse_controller.adoc:216-224,
hw/sys/sep/doc/lifecycle_controller.adoc:98-148, hw/sys/smu/doc/port_table.adoc:131 (lc_state_o).

The exported word is ``{~raw[3:0], raw[3:0]}``; RMA_SIP raw 4'b0011 gives 0xC3. The shadow image
named by ``+sep_shadow_reg_preload`` is the only stimulus.

S1, setup: the shadow image is the RMA_SIP one; the SMC's LC_STATE input reaches 0xC3 and
    lcc_dbg_disable_o is then unchanged for 16 cycles.
S2, export: lc_state_o, obs_sep_lc_state_o and smc_lc_state_in_o sampled on one clk_smu_i
    edge each equal 0xC3; lc_sigint_err_o is logged.
S3, timeout: every bounded wait reports its bound and last observed state.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

#: hw/sys/sep/doc/lifecycle_controller.adoc:98-148, RMA_SIP raw 4'b0011 -> {~raw, raw}.
LC_RMA_SIP_1_WORD = 0xC3

PRELOAD_IMAGE = "sep_efuse_shadow_lc_rma_sip_1.preload"
LC_SETTLE_BOUND_CYCLES = 60000
DBG_SETTLE_BOUND_CYCLES = 4096
DBG_STABLE_CYCLES = 16
CONTRACT_WAIT_LABELS = ["lc_settle", "dbg_settle"]


class smu_lc_rma_sip_1_export_test_seq:
    """RMA_SIP LC_STATE export observed at the wrapper, the SEP and the SMC input."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.step_ts: dict[str, float] = {}
        self.sites: list[dict] = []

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _rd(self, name: str, *, allow_xz: bool = False) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on the wrapper tb top")
        return self.test.read_int(pin, name, allow_xz=allow_xz)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _site(self, label: str, bound: int) -> dict:
        rec = {"label": label, "bound": bound, "cycles": 0, "last": "none", "met": False}
        self.sites.append(rec)
        return rec

    async def _lc_settle(self) -> None:
        rec = self._site("lc_settle", LC_SETTLE_BOUND_CYCLES)
        clk = self.dut.clk_smu_i
        for cycle in range(rec["bound"]):
            await RisingEdge(clk)
            word = self._rd("smc_lc_state_in_o", allow_xz=True)
            rec["cycles"] = cycle + 1
            rec["last"] = f"smc_lc_state_in=0x{word:02x}"
            if word == LC_RMA_SIP_1_WORD:
                rec["met"] = True
                self._log(f"CELL lc_settle cycles={rec['cycles']} smc_lc_state_in=0x{word:02x}")
                return
        raise AssertionError(f"lc_settle expired after {rec['bound']} cycles, last {rec['last']}")

    async def _dbg_settle(self) -> None:
        rec = self._site("dbg_settle", DBG_SETTLE_BOUND_CYCLES)
        clk = self.dut.clk_smu_i
        prev = None
        stable = 0
        for cycle in range(rec["bound"]):
            await RisingEdge(clk)
            word = self._rd("lcc_dbg_disable_o")
            rec["cycles"] = cycle + 1
            rec["last"] = f"lcc_dbg_disable=0x{word:04x}"
            stable = stable + 1 if word == prev else 0
            prev = word
            if stable >= DBG_STABLE_CYCLES:
                rec["met"] = True
                self._log(f"CELL dbg_settle cycles={rec['cycles']} lcc_dbg_disable=0x{word:04x}")
                return
        raise AssertionError(f"dbg_settle expired after {rec['bound']} cycles, last {rec['last']}")

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        clk = dut.clk_smu_i

        self._mark("S1", "SETUP: RMA_SIP shadow image, lc_settle then dbg_settle")
        preload = str(cocotb.plusargs.get("sep_shadow_reg_preload", ""))
        assert preload.endswith(PRELOAD_IMAGE), f"wrong shadow image: {preload!r}"
        assert "lc_sigint_inject" not in cocotb.plusargs, "+lc_sigint_inject must be absent"
        await self._lc_settle()
        await self._dbg_settle()

        self._mark("S2", "sample the three LC_STATE observation points on one edge")
        await RisingEdge(clk)
        lc_o = self._rd("lc_state_o")
        obs = self._rd("obs_sep_lc_state_o")
        smc_in = self._rd("smc_lc_state_in_o")
        sigint = self._rd("lc_sigint_err_o")
        self._log(
            f"CELL lc_export lc_state_o=0x{lc_o:02x} obs_sep=0x{obs:02x} "
            f"smc_in=0x{smc_in:02x} lc_sigint_err={sigint}"
        )
        sb.expect_eq(
            "CHK-LCG-RMASIP1-LC-EXPORT",
            (lc_o, obs, smc_in),
            (0xC3, 0xC3, 0xC3),
            evidence="CHK-LCG-RMASIP1-LC-EXPORT",
        )
        self._log(
            f"CHK-LCG-RMASIP1-LC-EXPORT: lc_state_o=0x{lc_o:02x} obs_sep_lc_state_o=0x{obs:02x} "
            f"smc_lc_state_in_o=0x{smc_in:02x} expected=0xC3"
        )
        self._log(f"CHK-LCG-RMASIP1-LC-EXPORT: lc_sigint_err_o={sigint}")

        self._mark("S3", "TIMEOUT: bounded waits and last state")
        await RisingEdge(clk)
        self._log(f"CELL lc_export_hold lc_state_o=0x{self._rd('lc_state_o'):02x}")
        for rec in self.sites:
            rec["expired"] = int(rec["cycles"] >= rec["bound"] or not rec["met"])
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['label']}: bound={rec['bound']} cycles={rec['cycles']} "
                f"{state} last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        labels = sorted(rec["label"] for rec in self.sites)
        well_formed = all(0 < rec["bound"] < 10**9 and rec["last"] for rec in self.sites)
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} labels={labels} expired={expired} "
            f"well_formed={well_formed}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "each wait label recorded exactly once",
            labels,
            sorted(CONTRACT_WAIT_LABELS),
            evidence="CHK-TIMEOUT-PATHS",
        )
        sb.expect_eq(
            "site bounds finite and positive, last state non-empty",
            well_formed,
            True,
            evidence="CHK-TIMEOUT-PATHS",
        )

        await RisingEdge(clk)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = ["S1", "S2", "S3", "PASS"]
        deltas = [self.step_ts[b] - self.step_ts[a] for a, b in zip(order, order[1:])]
        stamps = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
        self._log(f"CHK-NONVAC: ordered fence S1<S2<S3<PASS {stamps}")
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            all(d > 0 for d in deltas),
            True,
            evidence="CHK-NONVAC",
        )
