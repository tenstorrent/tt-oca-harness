// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// SEP VCS coverage exclusions -- PeakRDL regblock literal ties and the
// response ports that carry them.
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
// Other literal ties in generated regblocks:
//   - sep_cpu_ctrl_reg load_next nets that the generator assigns '1 in both
//     arms.
//   - A reserved field that the generator assigns 1'h0 (sep_cpu_ctrl_reg
//     SEP_NMI_VEC.rsvd).
//   - sep_scratch_reg address bits [2:0] and data bits [63:32], which its
//     cpuif builds from literal zeros.
//
// Two non-regblock entries carry an A2 response one level up:
//   - efuse_token_processing apb_resp_o.pslverr, which is efuse_mmr_reg
//     s_apb_pslverr.
//   - The fuse_bank_ctrl_resp_o B/R resp outputs of the efuse_interface_shim
//     instance, which come from efuse_shim_ctrl_reg. Only the shim outputs are
//     listed. The copies of this response inside u_sep come in through an
//     integrator input port, so they stay graded.
//
// SEP returns SLVERR from the fabric -- the AXI-Lite demux default slave
// (the sep_pkg::ERR_SLV leg, u_err_slv in sep_system_csr.sv), the axi_filter
// datapath and the xbar decode error slave -- and sep_axi_map_refuse_test
// grades those. This file does not waive them.
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


CHECKSUM: "1620533576 2326277839"
MODULE: filter_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR: hw/ip/axi_filter/regs/gen/sv/filter_ctrl_reg.sv:596,630 assign cpuif_wr_err and readback_err the literal '0, so axil_resp_buffer_err stores only 0 and the SLVERR arm at hw/ip/axi_filter/regs/gen/sv/filter_ctrl_reg.sv:210-211 cannot execute. NOT waived: the OKAY arm and the rest of the response path."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "1620533576 363877172"
MODULE: filter_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR: hw/ip/axi_filter/regs/gen/sv/filter_ctrl_reg.sv:596,630 assign cpuif_wr_err and readback_err the literal '0, so axil_resp_buffer_err stores only 0 and the SLVERR arm at hw/ip/axi_filter/regs/gen/sv/filter_ctrl_reg.sv:210-211 cannot execute. NOT waived: the OKAY arm (axil_resp_buffer_err = 0)."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "2368045406 3094551340"
MODULE: output_remap_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR: hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:343,364 assign cpuif_wr_err and readback_err the literal '0, so axil_resp_buffer_err stores only 0 and the SLVERR arm at hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:209-210 cannot execute. NOT waived: the OKAY arm and the rest of the response path."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "2368045406 1795492639"
MODULE: output_remap_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR: hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:343,364 assign cpuif_wr_err and readback_err the literal '0, so axil_resp_buffer_err stores only 0 and the SLVERR arm at hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:209-210 cannot execute. NOT waived: the OKAY arm (axil_resp_buffer_err = 0)."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "765096654 3811330331"
MODULE: alias_remap_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR: hw/ip/axi_alias_remap/regs/gen/sv/alias_remap_reg.sv:445,473 assign cpuif_wr_err and readback_err the literal '0, so axil_resp_buffer_err stores only 0 and the SLVERR arm at hw/ip/axi_alias_remap/regs/gen/sv/alias_remap_reg.sv:209-210 cannot execute. NOT waived: the OKAY arm and the rest of the response path."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "765096654 1297930971"
MODULE: alias_remap_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR: hw/ip/axi_alias_remap/regs/gen/sv/alias_remap_reg.sv:445,473 assign cpuif_wr_err and readback_err the literal '0, so axil_resp_buffer_err stores only 0 and the SLVERR arm at hw/ip/axi_alias_remap/regs/gen/sv/alias_remap_reg.sv:209-210 cannot execute. NOT waived: the OKAY arm (axil_resp_buffer_err = 0)."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "2905179362 2073096279"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_csr.u_sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-LOADNEXT-CONST: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:1021/1024, :1324/1327, :1350/1353, :1376/1379, :1402/1405, :1428/1431, :1454/1457, :1480/1483 and :1506/1509 assign load_next_c = '1 in both arms, so these load_next nets hold 1. NOT waived: the next and value nets of these fields, and load_next of every field whose arms differ."
Toggle field_combo.PERIPH_BUS_ERR_CLEAR.wdt.load_next "logic field_combo.PERIPH_BUS_ERR_CLEAR.wdt.load_next"
Toggle field_combo.PERIPH_BUS_ERR_CLEAR.edn.load_next "logic field_combo.PERIPH_BUS_ERR_CLEAR.edn.load_next"
Toggle field_combo.PERIPH_BUS_ERR_CLEAR.csrng.load_next "logic field_combo.PERIPH_BUS_ERR_CLEAR.csrng.load_next"
Toggle field_combo.PERIPH_BUS_ERR_CLEAR.otbn.load_next "logic field_combo.PERIPH_BUS_ERR_CLEAR.otbn.load_next"
Toggle field_combo.PERIPH_BUS_ERR_CLEAR.kmac.load_next "logic field_combo.PERIPH_BUS_ERR_CLEAR.kmac.load_next"
Toggle field_combo.PERIPH_BUS_ERR_CLEAR.hmac.load_next "logic field_combo.PERIPH_BUS_ERR_CLEAR.hmac.load_next"
Toggle field_combo.PERIPH_BUS_ERR_CLEAR.aes.load_next "logic field_combo.PERIPH_BUS_ERR_CLEAR.aes.load_next"
Toggle field_combo.DMA_BUS_ERR_CLEAR.clr.load_next "logic field_combo.DMA_BUS_ERR_CLEAR.clr.load_next"
Toggle field_combo.TIMEOUT_CLEAR.reserved.load_next "logic field_combo.TIMEOUT_CLEAR.reserved.load_next"

CHECKSUM: "2905179362 2073096279"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_csr.u_sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-NMIVEC-RSVD: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:1200 assigns hwif_out.SEP_NMI_VEC.rsvd.value = 1'h0. NOT waived: hwif_out.SEP_NMI_VEC.nmi_vec.value and the SEP_NMI_VEC field storage."
Toggle hwif_out.SEP_NMI_VEC.rsvd.value "logic hwif_out.SEP_NMI_VEC.rsvd.value"

CHECKSUM: "2905179362 2073096279"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_csr.u_sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-LOADNEXT-CONST: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:718 and :721 assign load_next_c = '1 in both arms, so REFERENCE_COUNTER load_next holds 1. NOT waived: REFERENCE_COUNTER next and value, which the hardware counter moves."
Toggle field_combo.REFERENCE_COUNTER.rc.load_next "logic field_combo.REFERENCE_COUNTER.rc.load_next"

CHECKSUM: "3743219407 1334731715"
MODULE: sep_reset_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/sys/sep/regs/gen/sv/blocks/sep_reset_ctrl_reg.sv:487 sets cpuif_wr_err to '0 and :513 sets readback_err to '0; these are the only loads of axil_resp_buffer_err (:166,176,181), so the 'if(axil_resp_buffer_err[...])' arm at :208 that drives SLVERR is unreachable. NOT waived: the OKAY arm and the response handshake."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "3743219407 2121730135"
MODULE: sep_reset_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/sys/sep/regs/gen/sv/blocks/sep_reset_ctrl_reg.sv:487 sets cpuif_wr_err to '0 and :513 sets readback_err to '0; these are the only loads of axil_resp_buffer_err (:166,176,181), so the 'if(axil_resp_buffer_err[...])' arm at :208 that drives SLVERR is unreachable. NOT waived: the OKAY arm and the response handshake."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "2905179362 847969879"
MODULE: sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:1530 sets cpuif_wr_err to '0 and :1652 sets readback_err to '0; these are the only loads of axil_resp_buffer_err (:167,177,182), so the 'if(axil_resp_buffer_err[...])' arm at :209 that drives SLVERR is unreachable. NOT waived: the OKAY arm and the response handshake."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "2905179362 3747101343"
MODULE: sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:1530 sets cpuif_wr_err to '0 and :1652 sets readback_err to '0; these are the only loads of axil_resp_buffer_err (:167,177,182), so the 'if(axil_resp_buffer_err[...])' arm at :209 that drives SLVERR is unreachable. NOT waived: the OKAY arm and the response handshake."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "2477850130 3748922694"
MODULE: sep_scratch_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/sys/sep/regs/gen/sv/blocks/sep_scratch_reg.sv:311 sets cpuif_wr_err to '0 and :333 sets readback_err to '0; these are the only loads of axil_resp_buffer_err (:166,176,181), so the 'if(axil_resp_buffer_err[...])' arm at :208 that drives SLVERR is unreachable. NOT waived: the OKAY arm and the response handshake."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "2477850130 3516621464"
MODULE: sep_scratch_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/sys/sep/regs/gen/sv/blocks/sep_scratch_reg.sv:311 sets cpuif_wr_err to '0 and :333 sets readback_err to '0; these are the only loads of axil_resp_buffer_err (:166,176,181), so the 'if(axil_resp_buffer_err[...])' arm at :208 that drives SLVERR is unreachable. NOT waived: the OKAY arm and the response handshake."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "2477850130 325599202"
MODULE: sep_scratch_reg
ANNOTATION: "SEP-REGBLOCK-SCRATCH-WIDTH: hw/sys/sep/regs/gen/sv/blocks/sep_scratch_reg.sv:137,142,147 build cpuif_addr as {axil_*addr[5:3],3'b0}, so cpuif_addr, decoded_addr and rd_mux_addr bits [2:0] hold 0; :325-328 load only readback_data[31:0], :337 copies it to cpuif_rd_data, and the response buffer (load at :177, reset '0 at :167) is the only source of s_axil_rdata (:207), so bits [63:32] hold 0. NOT waived: cpuif_addr[5:3] and data bits [31:0]."
Toggle s_axil_rdata [63:32] "logic s_axil_rdata[63:0]"
Toggle cpuif_addr [2:0] "logic cpuif_addr[5:0]"
Toggle cpuif_rd_data [63:32] "logic cpuif_rd_data[63:0]"
Toggle decoded_addr [2:0] "logic decoded_addr[5:0]"
Toggle rd_mux_addr [2:0] "logic rd_mux_addr[5:0]"
Toggle readback_data [63:32] "logic readback_data[63:0]"

CHECKSUM: "760587158 1635514154"
MODULE: sep_lifecycle_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/sys/sep/regs/gen/sv/blocks/sep_lifecycle_ctrl_reg.sv:167, :177, :182 load axil_resp_buffer_err only from cpuif_rd_err/cpuif_wr_err, which are literal 0 (:466, :496, :501), so the error-response statements at :210-211 never execute. NOT waived: the OKAY response statements at :213-214."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "760587158 718520331"
MODULE: sep_lifecycle_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/sys/sep/regs/gen/sv/blocks/sep_lifecycle_ctrl_reg.sv:167, :177, :182 load axil_resp_buffer_err only from cpuif_rd_err/cpuif_wr_err, which are literal 0 (:466, :496, :501), so the true arm of the branch at :209 never executes. NOT waived: the false (OKAY) arm of that branch."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "775763348 326083122"
MODULE: efuse_shim_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/ip/efuse/dv/models/regs/gen/sv/efuse_shim_ctrl_reg.sv:166, :176, :181 load axil_resp_buffer_err only from cpuif_rd_err/cpuif_wr_err, which are literal 0 (:307, :327, :332), so the error-response statements at :209-210 never execute. NOT waived: the OKAY response statements at :212-213."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "775763348 2181345026"
MODULE: efuse_shim_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-RESP: hw/ip/efuse/dv/models/regs/gen/sv/efuse_shim_ctrl_reg.sv:166, :176, :181 load axil_resp_buffer_err only from cpuif_rd_err/cpuif_wr_err, which are literal 0 (:307, :327, :332), so the true arm of the branch at :208 never executes. NOT waived: the false (OKAY) arm of that branch."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "1800326492 1617644716"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
ANNOTATION: "SEP-REGBLOCK-A2-APB-NOERR: hw/ip/efuse/rtl/efuse_token_processing.sv:136 drives apb_resp_o.pslverr from efuse_mmr_reg s_apb_pslverr = cpuif_rd_err | cpuif_wr_err (hw/ip/efuse/regs/gen/sv/efuse_mmr_reg.sv:78), and both are literal 0 (:320, :394, :400). NOT waived: apb_resp_o.pready and apb_resp_o.prdata."
Toggle apb_resp_o.pslverr "logic apb_resp_o.pslverr"

CHECKSUM: "1712882665 601168459"
INSTANCE: sep_uvm_top.u_dut.u_sep_ip_integration.u_efuse_interface_shim
ANNOTATION: "SEP-EFUSE-SHIM-RESP-OKAY: hw/ip/efuse/rtl/efuse_interface_shim.sv:92, :100 take the B/R resp from efuse_shim_ctrl_reg s_axil_bresp/s_axil_rresp, which is 2'b00 unless the constant-0 axil_resp_buffer_err selects 2'b10 (hw/ip/efuse/dv/models/regs/gen/sv/efuse_shim_ctrl_reg.sv:208-214). The literal assigns are inside the shim and its regblock, so the excluded bits are the shim outputs only. NOT waived: the B/R valid, id and R data of fuse_bank_ctrl_resp_o, and the copies of this response inside u_sep, which come in through an integrator input port."
Toggle fuse_bank_ctrl_resp_o.b.resp "logic fuse_bank_ctrl_resp_o.b.resp[1:0]"
Toggle fuse_bank_ctrl_resp_o.r.resp "logic fuse_bank_ctrl_resp_o.r.resp[1:0]"
