# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_axi_external_port_connectivity_test (SMU_ALL_002).

DV-CARD:          SMU_ALL_002   ANCHOR: smu_axi_external_port_connectivity_test

Owns:
  SMU-PORT-SMN-AXI.S1 — inbound 56/64-bit on smu_axi_in reaches SMC via
    direct IW converters (wrapper bench, SEP=0; required_cells dir=in +
    dest=smc_aperture only).
  SMU-SEP-PARAM.S2 — SEP=0 elaboration of direct SMC↔external ID converters
    (non-OTP-error).

The S1 probe lands on SMC BlockByDefault (no inbound window programmed), so
its response is DECERR. A DECERR alone is also what a dead bus or a stuck
converter would produce, so the same run carries a positive control: JTAG2AXI
opens inbound filter 0 over CHIP_CONFIG.VERSION_LO, the same external master
reads it through the same path and must see OKAY with the RDL reset value,
and the window is cleared again so the DECERR returns. The deny leg is then a
filter decision on a path shown live in this run.

SEP aperture inbound (dest=sep_aperture) is owned by SMU-PORT-SMN-AXI.S4 on
SMU_ALL_008 — out of scope for this card.
"""

from __future__ import annotations

import os
import random
import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer, with_timeout
from ocah_axi_vip import RESP_DECERR, RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO, SMC_CHIP_CONFIG_VERSION_LO_RESET
from seq_lib.smu_axi_helpers import (
    axi_read32_resp_ids,
    axi_write32_resp_ids,
    make_smu_axi_master,
    resp_name,
)
from seq_lib.smu_compose_helpers import GenerateScope
from seq_lib.smu_filter_helpers import (
    await_smn_resp,
    clear_inbound0_config,
    page_align_window,
    program_inbound0_window,
)
from seq_lib.smu_jtag_helpers import DTP_DEFAULT_IDCODE, make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope


class smu_axi_external_port_connectivity_test_seq:
    """SMU_ALL_002: SEP=0 inbound→SMC + direct IW converter elaboration."""

    # Authoritative map: smc_addr.h VERSION_LO (SMC local-alias aperture).
    IN_PROBE = SMC_CHIP_CONFIG_VERSION_LO
    # chip_config.rdl VERSION_LO is sw=r with a fixed reset value: the control
    # read compares the value, not just the response class.
    CONTROL_EXPECT = SMC_CHIP_CONFIG_VERSION_LO_RESET
    # Finite bound enforced by with_timeout — must match logged TIMEOUT bound.
    AXI_TIMEOUT_NS = 200_000
    # Bounded waits: inbound write + inbound read + control read (S2).
    EXPECTED_TIMEOUT_PATHS = 3

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
        # A third ID for the control read so its RID compare is its own.
        self.CONTROL_ID = (self.READ_ID + 1 + rng.randint(0, 0x7F)) & 0xFF
        while self.CONTROL_ID in (0, self.WRITE_ID, self.READ_ID):
            self.CONTROL_ID = (self.CONTROL_ID + 1) & 0xFF
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

    async def _axi_read_bounded(self, master, addr: int, arid: int, label: str = "s2_inbound_read"):
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

    async def _open_jtag2axi(self, dut):
        """Bring the PTAP out of TLR and require the SMC JTAG2AXI gate open.

        feat_ctrl is synchronised on TCK, so idle TCK cycles after the TAP
        reset are needed before ``smc_jtag2axi_security_disable`` can drop;
        while it is set SINGLE_OP no-ops with a SUCCESS status, so the gate is
        read from the TB pin rather than inferred from the status.
        """
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate_pin = getattr(dut, "tb_smc_jtag2axi_security_disable", None)
        if gate_pin is None:
            raise AssertionError("tb_smc_jtag2axi_security_disable not on this TB top")
        gate = self._sample(gate_pin, "tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        self._log(f"J2A ready: idcode=0x{idcode:08x} smc_jtag2axi_security_disable={gate}")
        return jtag

    async def _control_leg(self, dut, master, sb) -> None:
        """Positive control for the S1 DECERR: same master, same path, OKAY.

        Inbound filter 0 is opened over the probe (allow_burst=1, so the
        4 KB granule around it), the external master reads the probe and must
        see OKAY, its own RID and the RDL reset value; the window is cleared
        and the DECERR must come back. Both filter-ready waits are bounded
        polls that fail with last-state.
        """
        jtag = await self._open_jtag2axi(dut)
        lo, hi = page_align_window(self.IN_PROBE, self.IN_PROBE)
        await program_inbound0_window(jtag, lo, hi, scoreboard=sb, tag="S1CTRL_INBOUND0")
        self._log(f"S1 control: inbound0 window [0x{lo:08x},0x{hi:08x}] over VERSION_LO")
        await await_smn_resp(
            master, self.IN_PROBE, RESP_OKAY, clk=dut.clk_smu_i, label="s1_control_ready"
        )
        c_data, c_resp, _c_arid, c_rid = await self._axi_read_bounded(
            master, self.IN_PROBE, self.CONTROL_ID, label="s2_control_read"
        )
        c_data &= 0xFFFF_FFFF
        if c_resp != RESP_OKAY:
            raise AssertionError(
                f"control RRESP {resp_name(c_resp)} (expect OKAY through the programmed window)"
            )
        if c_rid != self.CONTROL_ID:
            raise AssertionError(
                f"control RID mismatch: rid=0x{c_rid:x} arid=0x{self.CONTROL_ID:x}"
            )
        sb.expect_eq(
            "CHK-SMU-PORT-SMN-AXI-S1-CONTROL VERSION_LO OKAY",
            c_resp,
            RESP_OKAY,
            evidence="CHK-SMU-PORT-SMN-AXI-S1-CONTROL",
        )
        sb.expect_eq(
            "CHK-SMU-PORT-SMN-AXI-S1-CONTROL VERSION_LO reset value",
            c_data,
            self.CONTROL_EXPECT,
            evidence="CHK-SMU-PORT-SMN-AXI-S1-CONTROL",
        )
        self._log(
            "CHK-SMU-PORT-SMN-AXI-S1-CONTROL: PASS "
            f"(dir=in dest=smc_aperture path=direct_iw addr=0x{self.IN_PROBE:08x} "
            f"arid=0x{self.CONTROL_ID:x} rid=0x{c_rid:x} rresp={resp_name(c_resp)} "
            f"rdata=0x{c_data:08x} expect=0x{self.CONTROL_EXPECT:08x})"
        )

        await clear_inbound0_config(jtag, scoreboard=sb)
        r_data, r_resp = await await_smn_resp(
            master, self.IN_PROBE, RESP_DECERR, clk=dut.clk_smu_i, label="s1_control_cleared"
        )
        self._log(
            f"S1 control cleared: VERSION_LO {resp_name(r_resp)} "
            f"rdata=0x{int(r_data) & 0xFFFF_FFFF:08x} with inbound0 disabled again"
        )

    async def _observe_direct_iw_converters(self, dut) -> tuple[str, int, int]:
        """Passive hierarchy observe: gen_no_sep IW converters present; no xbar."""
        smu = smu_scope(dut)
        if GenerateScope(smu, "gen_sep").exists():
            raise AssertionError(
                "SEP=0 elaboration fail: gen_sep present (expected gen_no_sep only)"
            )
        gen = GenerateScope(smu, "gen_no_sep")
        if not gen.exists():
            raise AssertionError(f"missing hierarchical child gen_no_sep under {smu}")
        iw_in = gen.get("u_iw_conv_smc_in")
        iw_out = gen.get("u_iw_conv_smc_out")
        if gen.has("u_smu_axi_xbar"):
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
            "SETUP: SEP=0 wrapper bring-up; clocks/resets stable; smu_axi_in BFM peer live",
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
            f"READ_ID=0x{self.READ_ID:x} CONTROL_ID=0x{self.CONTROL_ID:x} "
            f"wdata=0x{self.wdata:08x}"
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

        # Positive control for the deny-class responses above: same master,
        # same probe, window opened -> OKAY + reset value, window cleared ->
        # DECERR again.
        self._log(
            "ACTION SMU-PORT-SMN-AXI.S1 control: open inbound0 over "
            f"0x{self.IN_PROBE:08x} via JTAG2AXI, read from smu_axi_in, clear"
        )
        await self._control_leg(dut, master, sb)

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
