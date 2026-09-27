# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP LCC sep_debug -> inbound-filter gating test (OSS).

OSS port of the reference UVM ``sep_lcc_uvm_inbound_filter_gating_test``.
Proves that ``feat_ctrl.sep_debug`` gates the SEP inbound filter:
external AXI is BLOCKED in PROD (sep_debug=0, filter active) and ALLOWED in
PROD_DBG_1 (sep_debug=1, filter skipped). Datapath
(``sep.sv``: ``inbound_filter_skip_i = feat_ctrl.sep_debug``):

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
    the distinctive golden value 0xf000f000_f000f003 (proves the external path
    actually reached the LCC, not merely returned OKAY/all-ones).
  * CHK-IDENTITY   external access follows sep_debug: blocked@0, allowed@1 -- the
    frontdoor (FEAT_CTRL[0]) identity with the filter skip.
  * CHK-NONVAC     both block and allow outcomes observed (the A->B transition is
    real, not a single stuck state).

FEAT_CTRL is read frontdoor against the 64-bit lifecycle golden. A blocked
external read must return DECERR; an allowed external read must return the
LCC's distinctive FEAT_CTRL value. sep_debug is driven deterministically
between probes.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_lcc_golden import (
    DBG1_MASK,
    DBG2_MASK,
    LC_PROD,
    feat_ctrl_expected,
    lc_state_name,
)
from sep_base_test import sep_base_test
from seq_lib.sep_lcc_inbound_filter_gating_seq import (
    LCC_FEAT_CTRL,
    RESP_DECERR,
    SepExtAxiProbeSeq,
    SepLccDemoteSeq,
    SepLccFeatCtrlCheckSeq,
)

_MAX_SENSE_CYCLES = 20_000

# Distinct non-zero disable vectors so the decoded FEAT_CTRL is a non-trivial
# value in BOTH states (guards the golden checks against a vacuous all-zero pass).
# DBG_1 bits 0 (sep_debug) and 1 (chiplet_dbg) are LEFT ENABLED in both
# vectors. Under the per-group decode a PROD demotion only relaxes its debug group to
# honour SIP_DIS|SYS_DIS; it does not force the group open. A vector that
# disables sep_debug would make this test's own property unreachable: DEMOTE_1 would
# be honoured correctly and sep_debug would still read 0. Every other DIS bit stays
# set, so the value remains distinctive rather than all-ones.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0C
_SYS_DIS = 0x00FF_00FF_00FF_00FC


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
        # Every scoreboard judgment from here on backs the closing PASS line.
        scenario_mark = self.sb_mark()
        self.logger.info(
            "sensed OTP LC_STATE=%s; SIP_DIS=0x%016x SYS_DIS=0x%016x",
            lc_state_name(image.lc_raw()),
            _SIP_DIS,
            _SYS_DIS,
        )

        # security_disable read from the DUT, not assumed. It asserts only after a
        # SEC_DIS token match, which this no-token PROD flow never performs, so the
        # expected value is 0 -- but "expected 0" and "observed 0" are different
        # claims, and the probe makes it the second one. The exact 64-bit golden
        # compare below remains the safety net either way.
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1

        # ---- PROD: sep_debug=0, inbound filter active -> external blocked ----
        feat_prod = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=sec_dis)
        ctl_prod = SepLccFeatCtrlCheckSeq(feat_prod)
        mark = self.sb_mark()
        await self.start_seq(ctl_prod)
        self.assert_sb_judged(mark, "CHK-PROD-FEAT")
        assert ctl_prod.feat_ctrl == feat_prod, (
            f"CHK-PROD-FEAT FAIL: FEAT_CTRL=0x{ctl_prod.feat_ctrl:016x} != golden 0x{feat_prod:016x}"
        )
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
        # NOT a timeout (which would be a wedge) and NOT SLVERR. A timeout raises
        # in the driver and fails the test.
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
            LCC_FEAT_CTRL,
            probe_prod.resp_code,
        )

        # ---- CHK-DEMOTE-INDEP: DEMOTE_2 alone must open DBG_2 and NOT DBG_1 ----
        #
        # DEMOTE_1 and DEMOTE_2 are independent and act only on their own debug
        # group: DEMOTE_1 on DBG_1 [23:0], DEMOTE_2 on DBG_2 [47:24].
        # DEMOTE_2 is driven FIRST: the demote field is `onwrite=woset`
        # (sep_lifecycle_ctrl.rdl:27), so it cannot be cleared once set. Driving
        # DEMOTE_2 while DEMOTE_1 is still 0 is the only order in which this DUT
        # can show one group opening without the other. sep_debug is bit 0, inside
        # DBG_1, so it must still read 0 here -- and the external port must still
        # be blocked, which is a second, independent consequence of the same
        # property.
        demote2 = SepLccDemoteSeq(group=2)
        mark = self.sb_mark()
        await self.start_seq(demote2)
        self.assert_sb_judged(mark, "CHK-DEMOTE-INDEP DEMOTE_2 readback")
        assert demote2.demote == 1, f"DEMOTE_2.demote read back {demote2.demote}, expected 1"

        feat_d2 = feat_ctrl_expected(
            LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, demote_2=1, sec_dis=sec_dis
        )
        ctl_d2 = SepLccFeatCtrlCheckSeq(feat_d2)
        mark = self.sb_mark()
        await self.start_seq(ctl_d2)
        self.assert_sb_judged(mark, "CHK-DEMOTE-INDEP")
        assert ctl_d2.sep_debug == 0, (
            f"DEMOTE_2 alone must NOT open sep_debug (a DBG_1 bit), got "
            f"{ctl_d2.sep_debug} (FEAT_CTRL=0x{ctl_d2.feat_ctrl:016x}) -- the two demote "
            f"registers are not independent"
        )
        assert (ctl_d2.feat_ctrl & DBG1_MASK) == 0, (
            f"DEMOTE_2 alone opened DBG_1 bits [23:0]=0x{ctl_d2.feat_ctrl & DBG1_MASK:06x}, "
            f"expected 0 -- demotion is not per-group"
        )
        assert ctl_d2.feat_ctrl & DBG2_MASK, (
            f"DEMOTE_2 did not open any DBG_2 bit [47:24]=0x"
            f"{(ctl_d2.feat_ctrl & DBG2_MASK) >> 24:06x} -- the write had no effect"
        )
        self.logger.info(
            "CHK-DEMOTE-INDEP PASS: DEMOTE_2 alone opened DBG_2 and left DBG_1 closed "
            "(sep_debug=0), so the two demote registers act per-group"
        )

        probe_d2 = SepExtAxiProbeSeq(LCC_FEAT_CTRL)
        await self.start_ext_seq(probe_d2)
        assert probe_d2.resp_code == RESP_DECERR, (
            f"DEMOTE_2 alone must leave the inbound filter active (sep_debug=0), but the "
            f"external probe returned resp={probe_d2.resp_code}"
        )
        self.logger.info(
            "CHK-DEMOTE-INDEP PASS: external AXI still DECERR under DEMOTE_2 alone "
            "(filter follows DBG_1, not DBG_2)"
        )

        # ---- flip PROD -> PROD_DBG_1 via DEMOTE_1 ----
        demote = SepLccDemoteSeq(group=1)
        mark = self.sb_mark()
        await self.start_seq(demote)
        self.assert_sb_judged(mark, "CHK-DEMOTE")
        assert demote.demote == 1, f"DEMOTE_1.demote read back {demote.demote}, expected 1"
        self.logger.info("CHK-DEMOTE PASS: DEMOTE_1.demote write -> read-back == 1")

        # ---- PROD_DBG_1: sep_debug=1, inbound filter skipped -> external allowed ----
        # demote_2 stays 1: the field is write-once-set, so the golden must carry both.
        feat_dbg = feat_ctrl_expected(
            LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=1, demote_2=1, sec_dis=sec_dis
        )
        ctl_dbg = SepLccFeatCtrlCheckSeq(feat_dbg)
        mark = self.sb_mark()
        await self.start_seq(ctl_dbg)
        self.assert_sb_judged(mark, "CHK-DBG-FEAT")
        assert ctl_dbg.feat_ctrl == feat_dbg, (
            f"CHK-DBG-FEAT FAIL: FEAT_CTRL=0x{ctl_dbg.feat_ctrl:016x} != golden 0x{feat_dbg:016x}"
        )
        assert ctl_dbg.sep_debug == 1, (
            f"PROD_DBG_1 sep_debug must be 1, got {ctl_dbg.sep_debug} "
            f"(FEAT_CTRL=0x{ctl_dbg.feat_ctrl:016x})"
        )
        self.logger.info(
            "CHK-DBG-FEAT PASS: FEAT_CTRL=0x%016x == golden, sep_debug=1",
            ctl_dbg.feat_ctrl,
        )

        # Read BOTH FEAT_CTRL halves over the external master. The DISTINCTIVE half is
        # the LO word: demotion acts only on DBG_1, so the hi (Function) word is
        # identical in PROD and PROD_DBG_1 and cannot distinguish them. The lo word
        # is ~(SIP_DIS|SYS_DIS) over both debug groups = 0xf000f003 -- neither all-ones
        # nor zero, so a dummy responder or any unrelated OKAY slave fails it, and
        # matching it proves the external read actually reached the LCC FEAT_CTRL
        # register. The hi word carries DBG_2 [47:24] as well as Function.
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
            "(lo word 0x%08x is distinctive -> external read reached the LCC)",
            probe_hi.rdata,
            probe_lo.rdata,
            exp_lo,
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
        self.logger.info("CHK-NONVAC PASS: PROD blocked + PROD_DBG_1 allowed both observed")
        self.assert_sb_judged(scenario_mark, "SEP LCC inbound-filter-gating")
        self.logger.info("SEP LCC inbound-filter-gating test PASS")
