// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// DTP VCS coverage waivers: points the bench reaches by no stimulus the DTP's
// interface contract allows, for the fact the ANNOTATION before each item
// states. A formal unreachability analysis cannot prove them, because they
// are DTP inputs or bench checkers, so they are not in dtp_unreachable.el.
// Format Version: 2
// ExclMode: default
//
// Each CHECKSUM pair is the one `urg -dump full_exclusions` reports for the
// scope; build a changed entry from that dump, never by hand.
//==================================================

CHECKSUM: "662344282 920999053"
INSTANCE: dtp_uvm_top.u_dut
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.b.id "logic axi_smc_dbg_resp_i.b.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.r.id "logic axi_smc_dbg_resp_i.r.id[1:0]"
ANNOTATION: "CT_Ack_out is output-only: the cross-trigger network holds every CT_Ack_out pad input enable low and reads the pad inputs only into its lint sink, so no DTP logic observes them."
Toggle xtrig_ctp_ack_out_din_i "logic xtrig_ctp_ack_out_din_i[15:0]"

CHECKSUM: "282421448 501317893"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.b.id "logic axi_smc_dbg_resp_i.b.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.r.id "logic axi_smc_dbg_resp_i.r.id[1:0]"

CHECKSUM: "4175005557 2956291194"
INSTANCE: dtp_uvm_top.u_dut.u_jtag_intf_unit.u_jtag_ptap
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with AWID 0, and an AXI subordinate returns the request's ID as BID, so BID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.b.id "logic axi_smc_dbg_resp_i.b.id[1:0]"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request with ARID 0, and an AXI subordinate returns the request's ID as RID, so RID stays 0 on a compliant fabric."
Toggle axi_smc_dbg_resp_i.r.id "logic axi_smc_dbg_resp_i.r.id[1:0]"

// An Assert entry applies only while its instance checksum matches the design,
// so a change to the checker drops these with a URG warning.
CHECKSUM: "3246710229"
INSTANCE: dtp_uvm_top.u_m_axi_sva
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the FIXED-burst length rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AW_LEN_FIXED_MAX16.OCAH_AXI_AW_LEN_FIXED_MAX16 "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the FIXED-burst length rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AR_LEN_FIXED_MAX16.OCAH_AXI_AR_LEN_FIXED_MAX16 "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the WRAP-burst length rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AW_LEN_WRAP_LEGAL.OCAH_AXI_AW_LEN_WRAP_LEGAL "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the WRAP-burst length rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AR_LEN_WRAP_LEGAL.OCAH_AXI_AR_LEN_WRAP_LEGAL "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the WRAP-burst alignment rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AW_WRAP_ALIGNED.OCAH_AXI_AW_WRAP_ALIGNED "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as an INCR burst, so the WRAP-burst alignment rule has no antecedent."
Assert gen_axi4_rules.gen_OCAH_AXI_AR_WRAP_ALIGNED.OCAH_AXI_AR_WRAP_ALIGNED "assertion"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as one beat, with AWLEN 0, so the multi-beat write cover cannot fire."
Assert gen_axi4_rules.OCAH_AXI_C_AW_MULTI_BEAT "cover property"
ANNOTATION: "The JTAG2AXI bridge issues every SMC fabric request as one beat, with ARLEN 0, so the multi-beat read cover cannot fire."
Assert gen_axi4_rules.OCAH_AXI_C_AR_MULTI_BEAT "cover property"
