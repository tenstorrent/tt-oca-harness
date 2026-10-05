// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// SEP VCS coverage exclusions -- PeakRDL regblock structural ties.
// Format Version: 2
// ExclMode: default
//
// Scope: the cocotb VCS elaboration of sep_uvm_top, target `default`.
// Do not merge a `rom_boot` target run against this file.
//
// A1 NO-STALL applies only to a regblock whose generated cpuif hardwires
// cpuif_req_stall_rd/cpuif_req_stall_wr to '0 ("Read & write latencies are
// balanced. Stalls not required", e.g. sep_scratch_reg.sv). A1 IS NOT APPLIED
// to a block with external registers, where the generator drives stall from
// external_pending (efuse_mmr_reg.sv, entropy_source_reg.sv, km_kpv_reg.sv):
// there the stall moves.
//
// A2 NO-ERROR applies ONLY to the register spaces that decode no error. Their
// decode always_comb sets is_valid_addr='1 and is_valid_rw='1 with the
// generator's own comments "No valid address check" / "No valid RW check",
// then decoded_err='0, cpuif_wr_err='0, readback_err='0 and
// cpuif_rd_err=readback_err (e.g. sep_scratch_reg.sv). With the response
// buffer never loading a 1, s_axil_bresp/s_axil_rresp hold 2'b00 OKAY.
//
// The same A2 reasoning holds for an APB cpuif: s_apb_pslverr is
// cpuif_rd_err | cpuif_wr_err (efuse_interface_ctrl_reg.sv), so it holds 0.
// A block whose cpuif is an interface port (entropy_source_reg, axi4lite_intf)
// gets A2 on its internal error nets only; the interface bresp/rresp are not
// listed.
//
// A2 does not hold for the *_wrapper_key_reg blocks or the KM
// km_csr/km_drbg_sampler/km_mailbox_* blocks. Those blocks decode errors:
//   decoded_err = (~is_valid_addr | (is_valid_addr & ~is_valid_rw)) & decoded_req
//   and cpuif_wr_err / readback_err follow decoded_err
//   (e.g. aes_wrapper_key_reg.sv, abr_wrapper_key_reg.sv)
// Their SLVERR is reachable by an out-of-window or wrong-direction access on
// the KM private key bus, so they are not listed.
//
// SEP returns SLVERR from the fabric -- the AXI-Lite demux default slave
// (the sep_pkg::ERR_SLV leg, u_err_slv in sep_system_csr.sv), the axi_filter
// datapath and the xbar decode error slave -- and sep_axi_map_refuse_test
// grades those. This file waives the bresp/rresp OUTPUT OF A LEAF REGBLOCK
// only, which is a different signal.
//==================================================


CHECKSUM: "3714861442 325599202"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the AXI-Lite response holds 2-bit-zero OKAY."
MODULE: sep_scratch_reg
Toggle s_axil_bresp "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp "logic s_axil_rresp[1:0]"
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "602191063 2073096279"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the AXI-Lite response holds 2-bit-zero OKAY."
MODULE: sep_cpu_ctrl_reg
Toggle s_axil_bresp "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp "logic s_axil_rresp[1:0]"
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "3746075860 3442232018"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the AXI-Lite response holds 2-bit-zero OKAY."
MODULE: sep_reset_ctrl_reg
Toggle s_axil_bresp "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp "logic s_axil_rresp[1:0]"
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "1089600213 3277739977"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the AXI-Lite response holds 2-bit-zero OKAY."
MODULE: alias_remap_reg
Toggle s_axil_bresp "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp "logic s_axil_rresp[1:0]"
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "1931972926 336826070"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the AXI-Lite response holds 2-bit-zero OKAY."
MODULE: output_remap_reg
Toggle s_axil_bresp "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp "logic s_axil_rresp[1:0]"
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "2526737544 534567824"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the AXI-Lite response holds 2-bit-zero OKAY."
MODULE: filter_ctrl_reg
Toggle s_axil_bresp "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp "logic s_axil_rresp[1:0]"
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "1174471060 2756314957"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the AXI-Lite response holds 2-bit-zero OKAY."
MODULE: sep_lifecycle_ctrl_reg
Toggle s_axil_bresp "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp "logic s_axil_rresp[1:0]"
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "2125860950 1425039785"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: aes_wrapper_key_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

CHECKSUM: "536375817 2110593416"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: otbn_wrapper_key_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

CHECKSUM: "2468595266 1425039785"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: hmac_wrapper_key_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

CHECKSUM: "2634068924 1425039785"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: kmac_wrapper_key_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

CHECKSUM: "1094917889 2179785762"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: abr_wrapper_key_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

CHECKSUM: "937729671 786261837"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the APB s_apb_pslverr (cpuif_rd_err | cpuif_wr_err) holds 0."
MODULE: efuse_interface_ctrl_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"
Toggle s_apb_pslverr "logic s_apb_pslverr"

CHECKSUM: "775763348 3636628729"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the AXI-Lite response holds 2-bit-zero OKAY."
MODULE: efuse_shim_ctrl_reg
Toggle s_axil_bresp "logic s_axil_bresp[1:0]"
Toggle s_axil_rresp "logic s_axil_rresp[1:0]"
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "3827308321 220422702"
ANNOTATION: "A1 is NOT claimed: this block has external registers and drives stall from external_pending. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low and the APB s_apb_pslverr (cpuif_rd_err | cpuif_wr_err) holds 0."
MODULE: efuse_mmr_reg
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"
Toggle s_apb_pslverr "logic s_apb_pslverr"

CHECKSUM: "3063145569 4245126038"
ANNOTATION: "A1 is NOT claimed: this block has external registers and drives stall from external_pending. SEP-REGBLOCK-A2-NOERROR: this register space decodes no error condition (is_valid_addr and is_valid_rw are constant 1, decoded_err is zero), so cpuif_rd_err/cpuif_wr_err/readback_err stay low. Its response leaves through the axi4lite_intf port, which is not listed."
MODULE: entropy_source_reg
Toggle cpuif_rd_err "logic cpuif_rd_err"
Toggle cpuif_wr_err "logic cpuif_wr_err"
Toggle decoded_err "logic decoded_err"
Toggle readback_err "logic readback_err"

CHECKSUM: "3447392668 4110010268"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: km_csr_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

CHECKSUM: "1463142815 47713360"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: km_drbg_sampler_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

CHECKSUM: "661860948 937785337"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: km_mailbox_km_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

CHECKSUM: "2772866781 740540854"
ANNOTATION: "SEP-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif hardwires cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so neither net presents a second value for any access this slave can see. A2 is NOT claimed here: this block decodes real errors and its SLVERR path is reachable."
MODULE: km_mailbox_sep_reg
Toggle cpuif_req_stall_wr "logic cpuif_req_stall_wr"
Toggle cpuif_req_stall_rd "logic cpuif_req_stall_rd"

