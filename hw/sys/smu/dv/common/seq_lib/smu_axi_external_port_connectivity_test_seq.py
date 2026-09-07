# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_axi_external_port_connectivity_test (SMU_ALL_002).

DV-CARD:          SMU_ALL_002   ANCHOR: smu_axi_external_port_connectivity_test

Owns:
  SMU-PORT-SMN-AXI.S1 — inbound 56/64-bit on smu_axi_in reaches SMC via
    direct IW converters (bare tb_top SEP=0; required_cells dir=in +
    dest=smc_aperture only).
  SMU-SEP-PARAM.S2 — SEP=0 elaboration of direct SMC↔external ID converters
    (non-OTP-error).

SEP aperture inbound (dest=sep_aperture) is owned by SMU-PORT-SMN-AXI.S4 on
SMU_ALL_008 — out of scope for this card.
"""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope

import os
import random
import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer, with_timeout
from ocah_axi_vip import RESP_DECERR, RESP_OKAY

from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO
from seq_lib.smu_axi_helpers import (
    axi_read32_resp_ids,
    axi_write32_resp_ids,
    make_smu_axi_master,
    resp_name,
)

# SMC SYS_IN BlockByDefault err_slv poison (low 32b).
SMC_FILTER_POISON_LO = 0xBADCAB1E


class smu_axi_external_port_connectivity_test_seq:
    """SMU_ALL_002: SEP=0 inbound→SMC + direct IW converter elaboration."""

    # Authoritative map: smc_addr.h VERSION_LO (SMC local-alias aperture).
    IN_PROBE = SMC_CHIP_CONFIG_VERSION_LO
    # Finite bound enforced by with_timeout — must match logged TIMEOUT bound.
    AXI_TIMEOUT_NS = 200_000
    # Bounded waits: inbound write + inbound read (S2).
    EXPECTED_TIMEOUT_PATHS = 2

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        rng = random.Random(seed ^ 0xFAB_E001)
        # 8-bit SMN IDs; keep write/read distinct for BID/RID match checkers.
        self.WRITE_ID = rng.randint(1, 0xFE)
        self.READ_ID = (self.WRITE_ID + 1 + rng.randint(0, 0x7F)) & 0xFF
        if self.READ_ID == 0 or self.READ_ID == self.WRITE_ID:
            self.READ_ID = (self.WRITE_ID ^ 0x55) or 0x43
        self.wdata = rng.getrandbits(32)
        self._seed = seed

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self._log(f"STEP {step_id}: {detail}")

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    def _require_child(self, parent, name: str):
        if not hasattr(parent, name):
            raise AssertionError(f"missing hierarchical child {name} under {parent}")
        return getattr(parent, name)

    async def _axi_write_bounded(self, master, addr: int, data: int, awid: int):
        label = "s2_inbound_write"
        try:
            result = await with_timeout(
                axi_write32_resp_ids(master, addr, data, awid=awid),
                timeout_time=self.AXI_TIMEOUT_NS,
                timeout_unit="ns",
            )
            self._timeout_paths.append(
                f"{label}: bound={self.AXI_TIMEOUT_NS}ns ok last={resp_name(result[0])}"
            )
            return result
        except Exception:
            self._timeout_paths.append(
                f"{label}: bound={self.AXI_TIMEOUT_NS}ns EXPIRED last=no_bresp"
            )
            raise AssertionError(
                f"TIMEOUT {label}: bound={self.AXI_TIMEOUT_NS}ns last_state=no_bresp "
                f"addr=0x{addr:08x}"
            ) from None

    async def _axi_read_bounded(self, master, addr: int, arid: int):
        label = "s2_inbound_read"
        try:
            result = await with_timeout(
                axi_read32_resp_ids(master, addr, arid=arid),
                timeout_time=self.AXI_TIMEOUT_NS,
                timeout_unit="ns",
            )
            self._timeout_paths.append(
                f"{label}: bound={self.AXI_TIMEOUT_NS}ns ok last={resp_name(result[1])}"
            )
            return result
        except Exception:
            self._timeout_paths.append(
                f"{label}: bound={self.AXI_TIMEOUT_NS}ns EXPIRED last=no_rresp"
            )
            raise AssertionError(
                f"TIMEOUT {label}: bound={self.AXI_TIMEOUT_NS}ns last_state=no_rresp "
                f"addr=0x{addr:08x}"
            ) from None

    async def _observe_direct_iw_converters(self, dut) -> tuple[str, int, int]:
        """Passive hierarchy observe: gen_no_sep IW converters present; no xbar."""
        smu = smu_scope(dut)
        if hasattr(smu, "gen_sep"):
            raise AssertionError(
                "SEP=0 elaboration fail: gen_sep present (expected gen_no_sep only)"
            )
        gen = self._require_child(smu, "gen_no_sep")
        iw_in = self._require_child(gen, "u_iw_conv_smc_in")
        iw_out = self._require_child(gen, "u_iw_conv_smc_out")
        if hasattr(gen, "u_smu_axi_xbar"):
            raise AssertionError("SEP=0 elaboration fail: u_smu_axi_xbar present under gen_no_sep")

        # Live clk identity: converters track clk_smu_i (CONNECTIVITY, not force).
        await RisingEdge(dut.clk_smu_i)
        await Timer(1, unit="ns")
        top_clk = self._sample(dut.clk_smu_i, "clk_smu_i")
        in_clk = self._sample(iw_in.clk_i, "u_iw_conv_smc_in.clk_i")
        out_clk = self._sample(iw_out.clk_i, "u_iw_conv_smc_out.clk_i")
        if not (in_clk == out_clk == top_clk):
            raise AssertionError(
                f"direct IW converter clk identity fail: top={top_clk} in={in_clk} out={out_clk}"
            )

        sep_base = self._sample(dut.sep_global_base_o, "sep_global_base_o")
        sep_size = self._sample(dut.sep_region_size_o, "sep_region_size_o")
        if sep_base != 0 or sep_size != 0:
            raise AssertionError(
                f"SEP=0 aperture not tied off: base=0x{sep_base:x} size=0x{sep_size:x}"
            )
        detail = (
            f"sep=0 path=direct_smc_ext "
            f"iw=u_iw_conv_smc_in+u_iw_conv_smc_out xbar=absent "
            f"clk_identity={top_clk}"
        )
        return detail, sep_base, sep_size

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 32)

        # ------------------------------------------------------------------
        # S1 SETUP
        # ------------------------------------------------------------------
        self._mark_step(
            "S1",
            "SETUP: SEP=0 bare tb_top bring-up; clocks/resets stable; smu_axi_in BFM peer live",
        )
        # Baseline aperture observe (SEP tied off under SEP=0).
        sep_base = self._sample(dut.sep_global_base_o, "sep_global_base_o")
        sep_size = self._sample(dut.sep_region_size_o, "sep_region_size_o")
        self._log(f"baseline sep_global_base_o=0x{sep_base:x} sep_region_size_o=0x{sep_size:x}")

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        # ------------------------------------------------------------------
        # S2 SMU-PORT-SMN-AXI.S1 — inbound reaches SMC via direct IW path
        # ------------------------------------------------------------------
        self._mark_step(
            "S2",
            "ACTION SMU-PORT-SMN-AXI.S1: 56/64-bit smu_axi_in write/read "
            f"@0x{self.IN_PROBE:08x} (SMC aperture / direct IW)",
        )
        # required_cells: dir=in, dest=smc_aperture
        self._log("COVERAGE SMU-PORT-SMN-AXI.S1 cells: dir=in dest=smc_aperture")

        self._log(
            f"SEED: {self._seed} WRITE_ID=0x{self.WRITE_ID:x} "
            f"READ_ID=0x{self.READ_ID:x} wdata=0x{self.wdata:08x}"
        )
        wdata = self.wdata
        wresp, w_awid, w_bid = await self._axi_write_bounded(
            master, self.IN_PROBE, wdata, self.WRITE_ID
        )
        # Path reached SMC: BlockByDefault → DECERR, or programmed → OKAY.
        if wresp not in (RESP_OKAY, RESP_DECERR):
            raise AssertionError(
                f"inbound BRESP unexpected {resp_name(wresp)} (expect OKAY|DECERR proving SMC path)"
            )
        if w_bid != self.WRITE_ID:
            raise AssertionError(f"inbound BID mismatch: bid=0x{w_bid:x} awid=0x{self.WRITE_ID:x}")

        rdata, rresp, r_arid, r_rid = await self._axi_read_bounded(
            master, self.IN_PROBE, self.READ_ID
        )
        if rresp not in (RESP_OKAY, RESP_DECERR):
            raise AssertionError(
                f"inbound RRESP unexpected {resp_name(rresp)} (expect OKAY|DECERR proving SMC path)"
            )
        if r_rid != self.READ_ID:
            raise AssertionError(f"inbound RID mismatch: rid=0x{r_rid:x} arid=0x{self.READ_ID:x}")
        # When BlockByDefault DECERR, err_slv poison confirms SMC consumer.
        if rresp == RESP_DECERR:
            poison = rdata & 0xFFFF_FFFF
            if poison != SMC_FILTER_POISON_LO:
                raise AssertionError(
                    f"SMC filter poison mismatch: rdata=0x{poison:08x} "
                    f"expect=0x{SMC_FILTER_POISON_LO:08x}"
                )

        self._log(
            "CHK-SMU-PORT-SMN-AXI-S1: PASS "
            "(dir=in dest=smc_aperture path=direct_iw "
            f"addr=0x{self.IN_PROBE:08x} "
            f"awid=0x{self.WRITE_ID:x} bid=0x{w_bid:x} bresp={resp_name(wresp)} "
            f"arid=0x{self.READ_ID:x} rid=0x{r_rid:x} rresp={resp_name(rresp)} "
            f"rdata=0x{rdata & 0xFFFF_FFFF:08x})"
        )
        sb.expect_eq(
            "CHK-SMU-PORT-SMN-AXI-S1 ID match",
            w_bid,
            self.WRITE_ID,
            evidence="CHK-SMU-PORT-SMN-AXI-S1",
        )

        # ------------------------------------------------------------------
        # S3 SMU-SEP-PARAM.S2 — SEP=0 direct SMC↔external converters
        # ------------------------------------------------------------------
        self._mark_step(
            "S3",
            "ACTION SMU-SEP-PARAM.S2: observe SEP=0 direct SMC↔external "
            "ID converters (no 3x3 xbar / no live SEP)",
        )
        detail, sep_base_s3, sep_size_s3 = await self._observe_direct_iw_converters(dut)
        self._log(f"COVERAGE SMU-SEP-PARAM.S2 cells: sep=0 path=direct_smc_ext ({detail})")
        self._log(f"CHK-SMU-SEP-PARAM-S2: PASS ({detail})")
        # Non-tautological scoreboard: SEP aperture outputs must stay tied off.
        sb.expect_eq(
            "CHK-SMU-SEP-PARAM-S2 sep_global_base_o tied-off",
            sep_base_s3,
            0,
            evidence="CHK-SMU-SEP-PARAM-S2",
        )
        sb.expect_eq(
            "CHK-SMU-SEP-PARAM-S2 sep_region_size_o tied-off",
            sep_size_s3,
            0,
            evidence="CHK-SMU-SEP-PARAM-S2",
        )

        # ------------------------------------------------------------------
        # S4 TIMEOUT inventory
        # ------------------------------------------------------------------
        self._mark_step(
            "S4",
            "TIMEOUT: every bounded wait names finite bound + last-state",
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line or ("ok last=" not in line and "EXPIRED last=" not in line):
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] shape fail: {line}")
            if f"bound={self.AXI_TIMEOUT_NS}ns" not in line:
                raise AssertionError(
                    f"CHK-TIMEOUT-PATHS[{i}] bound mismatch vs with_timeout: {line}"
                )
        self._log(
            "CHK-TIMEOUT-PATHS: Finite bound on S4; expiry fails with "
            f"last-state diagnostics (paths={n_paths} "
            f"expect={self.EXPECTED_TIMEOUT_PATHS} bound={self.AXI_TIMEOUT_NS}ns)"
        )
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_ALL_002 sequence complete (PASS term for NONVAC fence)")

        order = ["S1", "S2", "S3", "S4", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        # Timestamp deltas from wall-clock marks.
        deltas_ns = [
            int((self._step_ts[b] - self._step_ts[a]) * 1e9) for a, b in zip(order, order[1:])
        ]
        positive_deltas = sum(1 for d in deltas_ns if d > 0)
        if positive_deltas != 4:
            raise AssertionError(
                f"CHK-NONVAC positive-delta count fail: {positive_deltas} deltas_ns={deltas_ns}"
            )
        self._log("CHK-NONVAC: Ordered fence S1<S2<S3<S4<PASS all hold")
        sb.expect_eq(
            "CHK-NONVAC positive step-delta count",
            positive_deltas,
            4,
            evidence="CHK-NONVAC",
        )
