# SPDX-License-Identifier: Apache-2.0
"""SEP LCC sep_debug -> inbound-filter gating test (OSS).

OSS port of the reference UVM ``sep_lcc_uvm_inbound_filter_gating_test`` (TEST 3.7,
reference suite). Proves that ``feat_ctrl.sep_debug`` gates the SEP inbound filter:
external AXI is BLOCKED in PROD (sep_debug=0, filter active) and ALLOWED in
PROD_DBG_1 (sep_debug=1, filter skipped). Datapath
(``sep.sv``: ``inbound_filter_skip_i = feat_ctrl_o.sep_debug``):

    eFuse OTP (LC_STATE=PROD) --sense--> LCC --feat_ctrl[0]=sep_debug-->
        u_inbound_filter.filter_skip_i --gates--> smn_inbound external AXI

Run mode: ``no_cpu`` with REAL fuse sense (no ``+skip_fuse_sense``). A custom OTP
image with LC_STATE constrained to PROD (random elsewhere, distinct non-zero
SIP_DIS/SYS_DIS so feat_ctrl is non-vacuous) is sensed into the LCC. PROD ->
PROD_DBG_1 is then a single DEMOTE_1 frontdoor CSR write (DEMOTE_LOCK_1=0 at
reset) -- no firmware needed, so the whole flow is CPU-held-off.

Two masters (both real DUT ports, no backdoor):
  * CONTROL = CPU-LSU (``s_axi``, no inbound filter): reads FEAT_CTRL (exact 64-bit
    golden value-check via the scoreboard) and writes DEMOTE_1.
  * EXTERNAL = SMN-inbound (``m_axi``): the filtered path; the probe at FEAT_CTRL
    is blocked (PROD) / allowed (PROD_DBG_1). The OSS analog of the reference suite's
    ``ext_axi_sqr`` (``axi_system[0].master[0]``).

Checkers (each logs positive evidence):
  * CHK-PROD-FEAT  FEAT_CTRL == golden(PROD), sep_debug==0 (scoreboard value-check).
  * CHK-PROD-BLOCK external probe blocked with the specific DECERR response
    (resp=3); a timeout is a wedge and fails the test.
  * CHK-DEMOTE     DEMOTE_1.demote write -> read-back == 1.
  * CHK-DBG-FEAT   FEAT_CTRL == golden(PROD_DBG_1), sep_debug==1 (scoreboard).
  * CHK-DBG-ALLOW  external probe reads BOTH FEAT_CTRL halves OKAY and returns
    the distinctive golden value 0xf0f00000_ffffffff (proves the external path
    actually reached the LCC, not merely returned OKAY/all-ones).
  * CHK-IDENTITY   external access follows sep_debug: blocked@0, allowed@1 -- the
    frontdoor (FEAT_CTRL[0]) replacement for the reference suite's backdoor filter_skip read.
  * CHK-NONVAC     both block and allow outcomes observed (the A->B transition is
    real, not a single stuck state).

Stronger than reference suite: reference suite reads ``filter_skip_i`` by backdoor ``uvm_hdl_read`` and
checks only ``feat_ctrl[0]``; the OSS port reads FEAT_CTRL frontdoor with an exact
64-bit golden value-check, requires the blocked external read to return DECERR,
and proves the allowed external read returns the LCC's distinctive FEAT_CTRL high
word. Scope delta: none functional. The reference suite async-flip ambiguity guard (firmware
advances LC mid-probe) is unnecessary here -- sep_debug is driven deterministically
between probes in the no_cpu flow.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from env.sep_lcc_golden import LC_PROD, feat_ctrl_expected, lc_state_name
from seq_lib.sep_lcc_inbound_filter_gating_seq import (
    LCC_FEAT_CTRL,
    RESP_DECERR,
    SepLccDemote1Seq,
    SepLccFeatCtrlCheckSeq,
    SepExtAxiProbeSeq,
)

_MAX_SENSE_CYCLES = 20_000

# Distinct non-zero disable vectors so the decoded FEAT_CTRL is a non-trivial
# value in BOTH states (guards the golden checks against a vacuous all-zero pass).
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF


@pyuvm.test()
class sep_lcc_uvm_inbound_filter_gating_test(sep_base_test):
    """sep_debug gates the SEP inbound filter: external AXI blocked/allowed."""

    async def run_scenario(self) -> None:
        # Real-sense a PROD OTP image (random elsewhere, pinned disable vectors).
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        assert image.lc_raw() == LC_PROD, "test bug: image LC_STATE is not PROD"
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        self.logger.info(
            "sensed OTP LC_STATE=%s; SIP_DIS=0x%016x SYS_DIS=0x%016x",
            lc_state_name(image.lc_raw()), _SIP_DIS, _SYS_DIS,
        )

        # security_disable (the LCC SEC_DIS override that forces feat_ctrl all-1s)
        # is 0 by construction: it asserts only after a SEC_DIS token match, which
        # this no-token PROD flow never performs. The exact 64-bit golden compare
        # below is the safety net -- if it were actually 1, FEAT_CTRL would read
        # all-1s and the PROD check (expecting sep_debug=0) would fail.
        sec_dis = 0

        # ---- PROD: sep_debug=0, inbound filter active -> external blocked ----
        feat_prod = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=sec_dis)
        ctl_prod = SepLccFeatCtrlCheckSeq(feat_prod)
        await self.start_seq(ctl_prod)
        assert ctl_prod.sep_debug == 0, (
            f"PROD sep_debug must be 0, got {ctl_prod.sep_debug} "
            f"(FEAT_CTRL=0x{ctl_prod.feat_ctrl:016x})"
        )
        self.logger.info(
            "CHK-PROD-FEAT PASS: FEAT_CTRL=0x%016x == golden, sep_debug=0",
            ctl_prod.feat_ctrl,
        )

        # allow_timeout=False: a blocked access must return the SPECIFIC DECERR
        # the inbound filter's axi_err_slv emits (axi_filter_wrap.sv RESP_DECERR),
        # NOT a timeout (which would be a wedge) and NOT SLVERR. A timeout now
        # raises in the driver and fails the test.
        probe_prod = SepExtAxiProbeSeq(LCC_FEAT_CTRL)
        await self.start_ext_seq(probe_prod)
        assert not probe_prod.resp_ok, (
            f"PROD: external AXI must be BLOCKED but got OKAY rdata=0x{probe_prod.rdata:08x}"
        )
        assert probe_prod.resp_code == RESP_DECERR, (
            f"PROD: external AXI must be blocked with DECERR (resp={RESP_DECERR}), "
            f"got resp={probe_prod.resp_code} (timed_out={probe_prod.timed_out})"
        )
        self.logger.info(
            "CHK-PROD-BLOCK PASS: external AXI @0x%08x blocked with DECERR (resp=%d)",
            LCC_FEAT_CTRL, probe_prod.resp_code,
        )

        # ---- flip PROD -> PROD_DBG_1 via DEMOTE_1 ----
        demote = SepLccDemote1Seq()
        await self.start_seq(demote)
        assert demote.demote == 1, f"DEMOTE_1.demote read back {demote.demote}, expected 1"
        self.logger.info("CHK-DEMOTE PASS: DEMOTE_1.demote write -> read-back == 1")

        # ---- PROD_DBG_1: sep_debug=1, inbound filter skipped -> external allowed ----
        feat_dbg = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=1, sec_dis=sec_dis)
        ctl_dbg = SepLccFeatCtrlCheckSeq(feat_dbg)
        await self.start_seq(ctl_dbg)
        assert ctl_dbg.sep_debug == 1, (
            f"PROD_DBG_1 sep_debug must be 1, got {ctl_dbg.sep_debug} "
            f"(FEAT_CTRL=0x{ctl_dbg.feat_ctrl:016x})"
        )
        self.logger.info(
            "CHK-DBG-FEAT PASS: FEAT_CTRL=0x%016x == golden, sep_debug=1",
            ctl_dbg.feat_ctrl,
        )

        # Read BOTH FEAT_CTRL halves over the external master. The lo word is
        # 0xffffffff (all debug bits) -- proves OKAY but is not distinctive. The
        # hi word (~SIP_DIS & FUNC_MASK = 0xf0f00000 here) is a DISTINCTIVE value:
        # a dummy responder returning all-ones (or any unrelated OKAY slave) would
        # fail it, so matching it proves the external read actually reached the
        # LCC FEAT_CTRL register.
        exp_lo = feat_dbg & 0xFFFF_FFFF
        exp_hi = (feat_dbg >> 32) & 0xFFFF_FFFF
        probe_lo = SepExtAxiProbeSeq(LCC_FEAT_CTRL)
        await self.start_ext_seq(probe_lo)
        probe_hi = SepExtAxiProbeSeq(LCC_FEAT_CTRL + 4)
        await self.start_ext_seq(probe_hi)
        assert probe_lo.resp_ok and probe_hi.resp_ok, (
            "PROD_DBG_1: external AXI must be ALLOWED but was blocked "
            f"(lo resp={probe_lo.resp_code} timed_out={probe_lo.timed_out}; "
            f"hi resp={probe_hi.resp_code} timed_out={probe_hi.timed_out})"
        )
        assert probe_lo.rdata == exp_lo and probe_hi.rdata == exp_hi, (
            f"PROD_DBG_1 external FEAT_CTRL read=0x{probe_hi.rdata:08x}_{probe_lo.rdata:08x} "
            f"!= control/golden 0x{exp_hi:08x}_{exp_lo:08x} (external path did not reach the LCC)"
        )
        self.logger.info(
            "CHK-DBG-ALLOW PASS: external AXI OKAY, FEAT_CTRL=0x%08x_%08x == golden "
            "(hi word 0x%08x is distinctive -> external read reached the LCC)",
            probe_hi.rdata, probe_lo.rdata, exp_hi,
        )

        # ---- filter_skip_i identity + non-vacuity ----
        assert (not probe_prod.resp_ok) and probe_lo.resp_ok, (
            "CHK-NONVAC: did not observe BOTH a blocked (PROD, DECERR) and an "
            "allowed (PROD_DBG_1, OKAY) external access"
        )
        self.logger.info(
            # Do not name filter_skip_i here: nothing in this test samples that
            # signal. The evidence is the external access flipping from DECERR to
            # OKAY across the sep_debug change, which is a behavioural claim.
            "CHK-IDENTITY PASS: external inbound access follows feat_ctrl.sep_debug "
            "(blocked@sep_debug=0 -> allowed@sep_debug=1)"
        )
        self.logger.info(
            "CHK-NONVAC PASS: PROD blocked + PROD_DBG_1 allowed both observed"
        )
        self.logger.info("SEP LCC inbound-filter-gating test PASS (TEST 3.7)")
