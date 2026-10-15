// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// SEP VCS coverage exclusions -- condition and branch terms fixed by RTL ties
// and SEP elaboration parameters.
// Format Version: 2
// ExclMode: default
//
// Scope: the cocotb VCS elaboration of sep_uvm_top, target `default`, TT-owned
// modules only. Third-party modules are a scope (.hier) decision and are not
// here.
//
// What this file waives, and nothing else:
//   - PeakRDL regblocks whose cpuif hardwires cpuif_req_stall_rd/wr to '0: the
//     condition vectors that need a stall, and the stall-else arms of the
//     AXI4-Lite request dispatch. Blocks whose stall follows external_pending
//     (efuse_mmr_reg, entropy_source_reg, km_kpv_reg) are NOT listed.
//   - Regblocks that decode no error: the pslverr vectors with a 1 operand
//     (APB), and the error-response lines and branches of sep_cpu_ctrl_reg
//     and entropy_source_reg (AXI-Lite).
//   - Regblock load_next nets that the generator assigns '1 in both arms: the
//     implicit else of the load_next branch (sep_cpu_ctrl_reg,
//     filter_ctrl_reg).
//   - KM CPU virtual-ROM decode, tied off without the simulation-only define,
//     and the KM ROM base compare against RomBase = 0.
//   - Elaboration-only constant functions (entropy_generator_complex, KM xbar).
//   - The else arms of integrity-generation, ACK_ZERO_STROBE_WRITE and
//     HAS_LC_STATE parameters that SEP fixes.
//   - Literal input ties inside SEP: entropy_source observe and entropy FIFO
//     clr/churn inputs, the pool EDN endpoint cancel, the outbound filter
//     skip, the SPI axi_lite_to_tlul err_clr, output_remap address bit 3, and
//     the VeeR IFU write address.
//   - Constant efuse values: the sw_lock bits [1:0] from the constant field
//     map, and the security-disable rev cell high source.
//
// Honesty rules:
//   1. Every entry is forced by RTL or by a SEP elaboration parameter cited in
//      its ANNOTATION. A term that stimulus, a CSR value, an error response, a
//      fault or a plusarg can reach stays in the denominator as a test gap.
//   2. Entries are copied from `urg -dump full_exclusions` on the merged VDB,
//      never typed by hand, and the file is checked with -excl_strict so it
//      cannot waive an object that any leaf covered.
//==================================================

CHECKSUM: "2662093143 1233793020"
MODULE: abr_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv:221-222 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 160 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 160 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 161 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 162 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 162 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 163 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 164 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 164 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "2662093143 2570161049"
MODULE: abr_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv:221-222 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "2825384411 3994493934"
MODULE: aes_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/aes_wrapper_key_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 47 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 47 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 48 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 49 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 49 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 50 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 51 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 51 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "2825384411 1358904238"
MODULE: aes_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/aes_wrapper_key_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "765096654 3808596618"
MODULE: alias_remap_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/axi_alias_remap/regs/gen/sv/alias_remap_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 34 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 34 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 35 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 36 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 36 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 37 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 38 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 38 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "765096654 1297930971"
MODULE: alias_remap_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/axi_alias_remap/regs/gen/sv/alias_remap_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "937729671 1625737755"
MODULE: efuse_interface_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/efuse/regs/gen/sv/efuse_interface_ctrl_reg.sv:83-84 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 74 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 74 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 75 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 76 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 76 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 77 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 78 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 78 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "775763348 1712681443"
MODULE: efuse_shim_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/efuse/dv/models/regs/gen/sv/efuse_shim_ctrl_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 21 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 21 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 22 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 23 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 23 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 24 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 25 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 25 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "775763348 2181345026"
MODULE: efuse_shim_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/efuse/dv/models/regs/gen/sv/efuse_shim_ctrl_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "1620533576 2271730998"
MODULE: filter_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/axi_filter/regs/gen/sv/filter_ctrl_reg.sv:221-222 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 53 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 53 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 54 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 55 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 55 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 56 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 57 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 57 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "1620533576 363877172"
MODULE: filter_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/axi_filter/regs/gen/sv/filter_ctrl_reg.sv:221-222 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "1498279216 3994493934"
MODULE: hmac_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/hmac_wrapper_key_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 47 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 47 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 48 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 49 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 49 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 50 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 51 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 51 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "1498279216 1358904238"
MODULE: hmac_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/hmac_wrapper_key_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "1014206092 3994493934"
MODULE: kmac_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/kmac_wrapper_key_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 47 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 47 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 48 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 49 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 49 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 50 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 51 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 51 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "1014206092 1358904238"
MODULE: kmac_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/kmac_wrapper_key_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "3447392668 3746136994"
MODULE: km_csr_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/km_csr_reg.sv:221-222 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 1301 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 1301 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 1302 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 1303 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 1303 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 1304 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 1305 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 1305 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "3447392668 4254605598"
MODULE: km_csr_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/km_csr_reg.sv:221-222 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "1463142815 1508870659"
MODULE: km_drbg_sampler_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/km_drbg_sampler_reg.sv:221-222 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 64 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 64 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 65 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 66 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 66 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 67 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 68 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 68 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "1463142815 2291590634"
MODULE: km_drbg_sampler_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/km_drbg_sampler_reg.sv:221-222 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "661860948 1654758731"
MODULE: km_mailbox_km_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/km_mailbox_km_reg.sv:221-222 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 133 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 133 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 134 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 135 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 135 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 136 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 137 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 137 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "661860948 148191721"
MODULE: km_mailbox_km_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/km_mailbox_km_reg.sv:221-222 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "2772866781 624218258"
MODULE: km_mailbox_sep_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/km_mailbox_sep_reg.sv:221-222 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 133 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 133 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 134 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 135 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 135 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 136 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 137 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 137 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "2772866781 558970297"
MODULE: km_mailbox_sep_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/km_mailbox_sep_reg.sv:221-222 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "3313930772 1863524742"
MODULE: otbn_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/key_manager/regs/gen/sv/otbn_wrapper_key_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 55 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 55 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 56 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 57 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 57 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 58 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 59 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 59 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "3313930772 1675308283"
MODULE: otbn_wrapper_key_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/key_manager/regs/gen/sv/otbn_wrapper_key_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "2368045406 2525155830"
MODULE: output_remap_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 25 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 25 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 26 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 27 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 27 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 28 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 29 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 29 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "2368045406 1795492639"
MODULE: output_remap_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "2905179362 2615609264"
MODULE: sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:221-222 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 226 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 226 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 227 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 228 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 228 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 229 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 230 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 230 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "2905179362 3747101343"
MODULE: sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:221-222 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "760587158 3810113182"
MODULE: sep_lifecycle_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/sys/sep/regs/gen/sv/blocks/sep_lifecycle_ctrl_reg.sv:221-222 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 40 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 40 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 41 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 42 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 42 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 43 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 44 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 44 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "760587158 718520331"
MODULE: sep_lifecycle_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/sys/sep/regs/gen/sv/blocks/sep_lifecycle_ctrl_reg.sv:221-222 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "3743219407 3214460824"
MODULE: sep_reset_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/sys/sep/regs/gen/sv/blocks/sep_reset_ctrl_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 48 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 48 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 49 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 50 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 50 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 51 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 52 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 52 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "3743219407 2121730135"
MODULE: sep_reset_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/sys/sep/regs/gen/sv/blocks/sep_reset_ctrl_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "2477850130 1989962094"
MODULE: sep_scratch_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-COND: hw/sys/sep/regs/gen/sv/blocks/sep_scratch_reg.sv:220-221 assigns cpuif_req_stall_rd and cpuif_req_stall_wr to constant '0 (generator comment: read and write latencies are balanced, stalls not required). A term that needs a stall to be 1, or a !(..stall..) term to be 0, cannot occur in any elaboration of this block. NOT waived: the cpuif_req, cpuif_req_is_wr and response-path terms, which move with bus traffic."
Condition 25 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (2 "101")
Condition 25 "1986659825" "(cpuif_req & ( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) & ( ! (cpuif_req_is_wr & cpuif_req_stall_wr) )) 1 -1" (3 "110")
Condition 26 "2444199068" "( ! (((!cpuif_req_is_wr)) & cpuif_req_stall_rd) ) 1 -1" (2 "1")
Condition 27 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (1 "01")
Condition 27 "1170080477" "(((!cpuif_req_is_wr)) & cpuif_req_stall_rd) 1 -1" (3 "11")
Condition 28 "333285110" "( ! (cpuif_req_is_wr & cpuif_req_stall_wr) ) 1 -1" (2 "1")
Condition 29 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (1 "01")
Condition 29 "3073733329" "(cpuif_req_is_wr & cpuif_req_stall_wr) 1 -1" (3 "11")

CHECKSUM: "2477850130 3516621464"
MODULE: sep_scratch_reg
ANNOTATION: "SEP-REGBLOCK-A1-STALL-BRANCH: hw/sys/sep/regs/gen/sv/blocks/sep_scratch_reg.sv:220-221 assigns cpuif_req_stall_rd/wr to constant '0, so the implicit else of each 'if(!cpuif_req_stall_*) axil_*_accept' in the AXI4-Lite request dispatch is unreachable. NOT waived: the axil_n_in_flight>=2 arm (response back-pressure) and the read/write arbitration arms, which a test can reach."
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (1) "(axil_n_in_flight < 2'd2) 1,1,0,-,-,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (3) "(axil_n_in_flight < 2'd2) 1,0,-,1,0,-,-"
Branch 1 "1722014690" "(axil_n_in_flight < 2'd2)" (5) "(axil_n_in_flight < 2'd2) 1,0,-,0,-,1,0"

CHECKSUM: "937729671 1625737755"
MODULE: efuse_interface_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-APB-NOERR: hw/ip/efuse/regs/gen/sv/efuse_interface_ctrl_reg.sv:78 (s_apb_pslverr), :633 cpuif_wr_err=0, :688 readback_err=0, :693 cpuif_rd_err=readback_err; the block sets is_valid_addr/is_valid_rw to '1 (no address or RW check), so both operands of cpuif_rd_err | cpuif_wr_err are constant 0 and the vectors with a 1 operand cannot occur."
Condition 73 "2060249598" "(cpuif_rd_err | cpuif_wr_err) 1 -1" (2 "01")
Condition 73 "2060249598" "(cpuif_rd_err | cpuif_wr_err) 1 -1" (3 "10")

CHECKSUM: "3827308321 2896595"
MODULE: efuse_mmr_reg
ANNOTATION: "SEP-REGBLOCK-A2-APB-NOERR: hw/ip/efuse/regs/gen/sv/efuse_mmr_reg.sv:78 (s_apb_pslverr), :320 cpuif_wr_err=0, :394 readback_err=0, :400 cpuif_rd_err=readback_err; the block sets is_valid_addr/is_valid_rw to '1 (no address or RW check), so both operands of cpuif_rd_err | cpuif_wr_err are constant 0 and the vectors with a 1 operand cannot occur."
Condition 32 "2060249598" "(cpuif_rd_err | cpuif_wr_err) 1 -1" (2 "01")
Condition 32 "2060249598" "(cpuif_rd_err | cpuif_wr_err) 1 -1" (3 "10")

CHECKSUM: "2137400323 2929689567"
MODULE: picorv32_wrapper
ANNOTATION: "KM-VROM-NOT-DECODED: without the simulation-only OCAH_KM_VROM define (not set by SEP DV, and rejected with $error under SYNTHESIS/EMULATION, hw/ip/key_manager/rtl/picorv32_wrapper.sv:323-339) hw/ip/key_manager/rtl/picorv32_wrapper.sv:344-345 tie is_vrom_addr and is_la_vrom_addr to 1'b0 and hw/ip/key_manager/rtl/picorv32_wrapper.sv:597 ties vrom_mem_ready to 1'b0. A term that needs one of these to be 1 (or !is_vrom_addr to be 0) cannot occur. NOT waived: the ROM, SRAM and peripheral decode terms."
Condition 8 "1556179153" "(((!is_rom_addr)) && ((!is_sram_addr)) && ((!is_vrom_addr))) 1 -1" (3 "110")
Condition 13 "2944619600" "((is_rom_addr && ((!rom_lockout_q))) || is_vrom_addr || sram_exec_allowed) 1 -1" (3 "010")
Condition 19 "2818024303" "(mem_valid && is_vrom_addr) 1 -1" (1 "01")
Condition 19 "2818024303" "(mem_valid && is_vrom_addr) 1 -1" (3 "11")
Condition 20 "908866964" "(mem_la_read && is_la_vrom_addr) 1 -1" (1 "01")
Condition 20 "908866964" "(mem_la_read && is_la_vrom_addr) 1 -1" (3 "11")
Condition 21 "1507716808" "((is_rom_addr && (rom_mem_ready || rom_read_blocked)) || (is_sram_addr && sram_mem_ready) || (is_vrom_addr && vrom_mem_ready) || (is_periph_addr && axi_adapter_mem_ready)) 1 -1" (3 "0010")
Condition 25 "4290863148" "(is_vrom_addr && vrom_mem_ready) 1 -1" (1 "01")
Condition 25 "4290863148" "(is_vrom_addr && vrom_mem_ready) 1 -1" (2 "10")
Condition 25 "4290863148" "(is_vrom_addr && vrom_mem_ready) 1 -1" (3 "11")

CHECKSUM: "2137400323 801391891"
MODULE: picorv32_wrapper
ANNOTATION: "KM-VROM-NOT-DECODED: hw/ip/key_manager/rtl/picorv32_wrapper.sv:344-345 tie is_vrom_addr to 1'b0 without OCAH_KM_VROM, so the is_vrom_addr arm of the read-data select register (hw/ip/key_manager/rtl/picorv32_wrapper.sv:494), of the combinational select (hw/ip/key_manager/rtl/picorv32_wrapper.sv:508) and the MEM_RDATA_SEL_VROM arm of the read mux (hw/ip/key_manager/rtl/picorv32_wrapper.sv:527) cannot be taken."
Branch 2 "545521854" "(!rst_ni)" (3) "(!rst_ni) 0,1,0,0,1"
Branch 3 "952348547" "current_read_complete" (2) "current_read_complete 1,0,0,1"
Branch 4 "2625712567" "mem_rdata_sel" (2) "mem_rdata_sel MEM_RDATA_SEL_VROM "

CHECKSUM: "3423857386 4188862500"
MODULE: entropy_generator_complex
ANNOTATION: "ENTROPY-GEN-ELAB-ONLY-FUNC: get_total_length/get_tapped_length (hw/ip/entropy_source/rtl/entropy_generator_complex.sv:148-182) are called only in the parameter override list of the generate loop (hw/ip/entropy_source/rtl/entropy_generator_complex.sv:275-276), so they are evaluated at elaboration and never execute at run time; no arm can be hit by any stimulus."
Branch 0 "844865755" "idx" (0) "idx 0 "
Branch 0 "844865755" "idx" (1) "idx 1 "
Branch 0 "844865755" "idx" (2) "idx 2 "
Branch 0 "844865755" "idx" (3) "idx 3 "
Branch 0 "844865755" "idx" (4) "idx 4 "
Branch 0 "844865755" "idx" (5) "idx 5 "
Branch 0 "844865755" "idx" (6) "idx 6 "
Branch 0 "844865755" "idx" (7) "idx 7 "
Branch 0 "844865755" "idx" (8) "idx 8 "
Branch 0 "844865755" "idx" (9) "idx 9 "
Branch 0 "844865755" "idx" (10) "idx 10 "
Branch 0 "844865755" "idx" (11) "idx 11 "
Branch 0 "844865755" "idx" (12) "idx default"
Branch 1 "844865755" "idx" (0) "idx 0 "
Branch 1 "844865755" "idx" (1) "idx 1 "
Branch 1 "844865755" "idx" (2) "idx 2 "
Branch 1 "844865755" "idx" (3) "idx 3 "
Branch 1 "844865755" "idx" (4) "idx 4 "
Branch 1 "844865755" "idx" (5) "idx 5 "
Branch 1 "844865755" "idx" (6) "idx 6 "
Branch 1 "844865755" "idx" (7) "idx 7 "
Branch 1 "844865755" "idx" (8) "idx 8 "
Branch 1 "844865755" "idx" (9) "idx 9 "
Branch 1 "844865755" "idx" (10) "idx 10 "
Branch 1 "844865755" "idx" (11) "idx 11 "
Branch 1 "844865755" "idx" (12) "idx default"

CHECKSUM: "2097437693 2178003635"
MODULE: axi_lite_to_tlul
ANNOTATION: "AXI2TLUL-INTG-GEN-PARAM: ENABLE_CMD_INTG_GEN and ENABLE_DATA_INTG_GEN default to 1 (hw/common/axi/axi_lite_to_tlul.sv:28-29); every SEP instance keeps the default or passes 1 (hw/sys/sep/rtl/sep_dma_wrap.sv:234-235 from hw/sys/sep/rtl/sep.sv:1202 ENABLE_DATA_INTG_GEN=1), so the else arms at :251/:267 are elaboration-dead."
Branch 3 "1189517418" "ENABLE_CMD_INTG_GEN" (1) "ENABLE_CMD_INTG_GEN 0"
Branch 4 "2160096988" "ENABLE_DATA_INTG_GEN" (1) "ENABLE_DATA_INTG_GEN 0"

CHECKSUM: "2470472206 1300994536"
MODULE: tlul_to_axi_lite
ANNOTATION: "TLUL2AXI-INTG-GEN-PARAM: the only SEP instance (hw/sys/sep/rtl/sep_dma_wrap.sv:259-260) passes ENABLE_DATA_INTG_GEN, set to 1 at hw/sys/sep/rtl/sep.sv:1202, to ENABLE_RSP_INTG_GEN and ENABLE_DATA_INTG_GEN, so the else arms at hw/common/axi/tlul_to_axi_lite.sv:281/:296 are elaboration-dead."
Branch 4 "3993283767" "ENABLE_RSP_INTG_GEN" (1) "ENABLE_RSP_INTG_GEN 0"
Branch 5 "2160096988" "ENABLE_DATA_INTG_GEN" (1) "ENABLE_DATA_INTG_GEN 0"

CHECKSUM: "486751003 1618864423"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_guard
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:368 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (efuse_interface_controller.sv:722), efuse_guard (efuse_interface_controller.sv:814) and on to efuse_shadow_reg_access_control (efuse_shadow_regs.sv:286). The HAS_LC_STATE=0 arms of efuse_guard at lines 102, 110 belong to the SMC elaboration and are dead here."
Branch 0 "4169860434" "HAS_LC_STATE" (3) "HAS_LC_STATE 0,-,-"
Branch 1 "4285556711" "HAS_LC_STATE" (4) "HAS_LC_STATE 0,-,-"

CHECKSUM: "3937190293 4074944007"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:368 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (efuse_interface_controller.sv:722), efuse_guard (efuse_interface_controller.sv:814) and on to efuse_shadow_reg_access_control (efuse_shadow_regs.sv:286). The HAS_LC_STATE=0 arms of efuse_interface_controller at lines 273, 291, 403 belong to the SMC elaboration and are dead here."
Branch 0 "3458527583" "HAS_LC_STATE" (2) "HAS_LC_STATE 0,-,1"
Branch 0 "3458527583" "HAS_LC_STATE" (3) "HAS_LC_STATE 0,-,0"
Branch 1 "221850953" "HAS_LC_STATE" (2) "HAS_LC_STATE 0,-,1"
Branch 1 "221850953" "HAS_LC_STATE" (3) "HAS_LC_STATE 0,-,0"
Branch 2 "1075115012" "HAS_LC_STATE" (4) "HAS_LC_STATE 0,-,-,-,1,-"
Branch 2 "1075115012" "HAS_LC_STATE" (5) "HAS_LC_STATE 0,-,-,-,0,1"
Branch 2 "1075115012" "HAS_LC_STATE" (6) "HAS_LC_STATE 0,-,-,-,0,0"

CHECKSUM: "3804881079 3321935136"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs.u_efuse_shadow_reg_access_control
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:368 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (efuse_interface_controller.sv:722), efuse_guard (efuse_interface_controller.sv:814) and on to efuse_shadow_reg_access_control (efuse_shadow_regs.sv:286). The HAS_LC_STATE=0 arms of efuse_shadow_reg_access_control at lines 146 belong to the SMC elaboration and are dead here."
Branch 1 "465878905" "HAS_LC_STATE" (4) "HAS_LC_STATE 0,-,-"

CHECKSUM: "1922851758 222844965"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:368 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (efuse_interface_controller.sv:722), efuse_guard (efuse_interface_controller.sv:814) and on to efuse_shadow_reg_access_control (efuse_shadow_regs.sv:286). The HAS_LC_STATE=0 arms of efuse_shadow_regs at lines 218, 336 belong to the SMC elaboration and are dead here."
Branch 2 "3908413232" "HAS_LC_STATE" (2) "HAS_LC_STATE 0,-,1"
Branch 2 "3908413232" "HAS_LC_STATE" (3) "HAS_LC_STATE 0,-,0"
Branch 4 "379866125" "HAS_LC_STATE" (14) "HAS_LC_STATE 0,-,-,-,-,-,-,-,-,-,-,-,-"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_aes_wrapper_s3c_scan.u_aes_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/sys/sep/rtl/aes_wrapper.sv:60-67), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Block 12 "2970101142" "req_error_d = 1'b0;"

CHECKSUM: "2906880031 2178003635"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_aes_wrapper_s3c_scan.u_aes_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/sys/sep/rtl/aes_wrapper.sv:60-67), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Branch 2 "3464338896" "state_q" (1) "state_q IDLE ,0,1,1,-,-,-,-,-,-,-,-,-"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_hmac_wrapper_s3c_scan.u_hmac_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/sys/sep/rtl/hmac_wrapper.sv:83-90), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Block 12 "2970101142" "req_error_d = 1'b0;"

CHECKSUM: "2906880031 2178003635"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_hmac_wrapper_s3c_scan.u_hmac_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/sys/sep/rtl/hmac_wrapper.sv:83-90), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Branch 2 "3464338896" "state_q" (1) "state_q IDLE ,0,1,1,-,-,-,-,-,-,-,-,-"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_kmac_wrapper_s3c_scan.u_kmac_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/sys/sep/rtl/kmac_wrapper.sv:93-100), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Block 12 "2970101142" "req_error_d = 1'b0;"

CHECKSUM: "2906880031 2178003635"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_kmac_wrapper_s3c_scan.u_kmac_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/sys/sep/rtl/kmac_wrapper.sv:93-100), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Branch 2 "3464338896" "state_q" (1) "state_q IDLE ,0,1,1,-,-,-,-,-,-,-,-,-"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/sys/sep/rtl/sep_crypto_otbn_wrapper.sv:73-80), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Block 12 "2970101142" "req_error_d = 1'b0;"

CHECKSUM: "2906880031 2178003635"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/sys/sep/rtl/sep_crypto_otbn_wrapper.sv:73-80), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Branch 2 "3464338896" "state_q" (1) "state_q IDLE ,0,1,1,-,-,-,-,-,-,-,-,-"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_csrng_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/ip/drbg/rtl/drbg.sv:236-241), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Block 12 "2970101142" "req_error_d = 1'b0;"

CHECKSUM: "2906880031 2178003635"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_csrng_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/ip/drbg/rtl/drbg.sv:236-241), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Branch 2 "3464338896" "state_q" (1) "state_q IDLE ,0,1,1,-,-,-,-,-,-,-,-,-"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_edn_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/ip/drbg/rtl/drbg.sv:269-274), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Block 12 "2970101142" "req_error_d = 1'b0;"

CHECKSUM: "2906880031 2178003635"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_edn_axi_lite_to_tlul
ANNOTATION: "SEP-A2T-ACKZERO-OFF: this instance keeps ACK_ZERO_STROBE_WRITE at its default 0 (hw/common/axi/axi_lite_to_tlul.sv:30; hw/ip/drbg/rtl/drbg.sv:269-274), so the zero-strobe early-OKAY path at hw/common/axi/axi_lite_to_tlul.sv:158-162 is dead by parameter: its statements and its IDLE branch arm cannot occur. NOT waived: the TL_PUT_REQ write path, the PUT_PARTIAL_DATA path and every other IDLE arm."
Branch 2 "3464338896" "state_q" (1) "state_q IDLE ,0,1,1,-,-,-,-,-,-,-,-,-"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_aes_wrapper_s3c_scan.u_aes_axi_lite_to_tlul
ANNOTATION: "SEP-INTG-GEN-ON: ENABLE_CMD_INTG_GEN and ENABLE_DATA_INTG_GEN keep their default 1 for this instance (hw/common/axi/axi_lite_to_tlul.sv:28-29; hw/sys/sep/rtl/aes_wrapper.sv:60-67), so the else arms at hw/common/axi/axi_lite_to_tlul.sv:263,273 that drive the all-ones integrity placeholder are dead by parameter. NOT waived: the generate-on arms at :255,:270."
Block 39 "915842203" "cmd_intg = {tlul_pkg::H2D_CMD_INTG_WIDTH {1'b1}};"
Block 42 "2397383519" "data_intg = {tlul_pkg::DATA_INTG_WIDTH {1'b1}};"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_hmac_wrapper_s3c_scan.u_hmac_axi_lite_to_tlul
ANNOTATION: "SEP-INTG-GEN-ON: ENABLE_CMD_INTG_GEN and ENABLE_DATA_INTG_GEN keep their default 1 for this instance (hw/common/axi/axi_lite_to_tlul.sv:28-29; hw/sys/sep/rtl/hmac_wrapper.sv:83-90), so the else arms at hw/common/axi/axi_lite_to_tlul.sv:263,273 that drive the all-ones integrity placeholder are dead by parameter. NOT waived: the generate-on arms at :255,:270."
Block 39 "915842203" "cmd_intg = {tlul_pkg::H2D_CMD_INTG_WIDTH {1'b1}};"
Block 42 "2397383519" "data_intg = {tlul_pkg::DATA_INTG_WIDTH {1'b1}};"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_kmac_wrapper_s3c_scan.u_kmac_axi_lite_to_tlul
ANNOTATION: "SEP-INTG-GEN-ON: ENABLE_CMD_INTG_GEN and ENABLE_DATA_INTG_GEN keep their default 1 for this instance (hw/common/axi/axi_lite_to_tlul.sv:28-29; hw/sys/sep/rtl/kmac_wrapper.sv:93-100), so the else arms at hw/common/axi/axi_lite_to_tlul.sv:263,273 that drive the all-ones integrity placeholder are dead by parameter. NOT waived: the generate-on arms at :255,:270."
Block 39 "915842203" "cmd_intg = {tlul_pkg::H2D_CMD_INTG_WIDTH {1'b1}};"
Block 42 "2397383519" "data_intg = {tlul_pkg::DATA_INTG_WIDTH {1'b1}};"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_axi_lite_to_tlul
ANNOTATION: "SEP-INTG-GEN-ON: ENABLE_CMD_INTG_GEN and ENABLE_DATA_INTG_GEN keep their default 1 for this instance (hw/common/axi/axi_lite_to_tlul.sv:28-29; hw/sys/sep/rtl/sep_crypto_otbn_wrapper.sv:73-80), so the else arms at hw/common/axi/axi_lite_to_tlul.sv:263,273 that drive the all-ones integrity placeholder are dead by parameter. NOT waived: the generate-on arms at :255,:270."
Block 39 "915842203" "cmd_intg = {tlul_pkg::H2D_CMD_INTG_WIDTH {1'b1}};"
Block 42 "2397383519" "data_intg = {tlul_pkg::DATA_INTG_WIDTH {1'b1}};"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_csrng_axi_lite_to_tlul
ANNOTATION: "SEP-INTG-GEN-ON: ENABLE_CMD_INTG_GEN and ENABLE_DATA_INTG_GEN keep their default 1 for this instance (hw/common/axi/axi_lite_to_tlul.sv:28-29; hw/ip/drbg/rtl/drbg.sv:236-241), so the else arms at hw/common/axi/axi_lite_to_tlul.sv:263,273 that drive the all-ones integrity placeholder are dead by parameter. NOT waived: the generate-on arms at :255,:270."
Block 39 "915842203" "cmd_intg = {tlul_pkg::H2D_CMD_INTG_WIDTH {1'b1}};"
Block 42 "2397383519" "data_intg = {tlul_pkg::DATA_INTG_WIDTH {1'b1}};"

CHECKSUM: "2906880031 3354473903"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_drbg_s3c_scan.u_edn_axi_lite_to_tlul
ANNOTATION: "SEP-INTG-GEN-ON: ENABLE_CMD_INTG_GEN and ENABLE_DATA_INTG_GEN keep their default 1 for this instance (hw/common/axi/axi_lite_to_tlul.sv:28-29; hw/ip/drbg/rtl/drbg.sv:269-274), so the else arms at hw/common/axi/axi_lite_to_tlul.sv:263,273 that drive the all-ones integrity placeholder are dead by parameter. NOT waived: the generate-on arms at :255,:270."
Block 39 "915842203" "cmd_intg = {tlul_pkg::H2D_CMD_INTG_WIDTH {1'b1}};"
Block 42 "2397383519" "data_intg = {tlul_pkg::DATA_INTG_WIDTH {1'b1}};"

CHECKSUM: "3423857386 1328081594"
MODULE: entropy_generator_complex
ANNOTATION: "ENTROPY-GEN-ELAB-ONLY-FUNC: get_total_length and get_tapped_length (hw/ip/entropy_source/rtl/entropy_generator_complex.sv:148-182) are called only in the parameter override list of the generate loop (hw/ip/entropy_source/rtl/entropy_generator_complex.sv:275-276), so they run only at elaboration and no statement in them executes at run time. NOT waived: every other line of entropy_generator_complex."
Block 1 "2710796142" "case (idx)"
Block 2 "195841642" "return TotalLength0;"
Block 3 "2656002457" "return TotalLength1;"
Block 4 "11027621" "return TotalLength2;"
Block 5 "2504747862" "return TotalLength3;"
Block 6 "1953196368" "return TotalLength4;"
Block 7 "3783804579" "return TotalLength5;"
Block 8 "2138006431" "return TotalLength6;"
Block 9 "3935063148" "return TotalLength7;"
Block 10 "3170355988" "return TotalLength8;"
Block 11 "689235175" "return TotalLength9;"
Block 12 "2703422086" "return TotalLength10;"
Block 13 "885120373" "return TotalLength11;"
Block 14 "1203358040" "return 29;"
Block 15 "2710796142" "case (idx)"
Block 16 "2345854153" "return TappedLength0;"
Block 17 "506579770" "return TappedLength1;"
Block 18 "2161569286" "return TappedLength2;"
Block 19 "355844597" "return TappedLength3;"
Block 20 "4095067123" "return TappedLength4;"
Block 21 "1643572224" "return TappedLength5;"
Block 22 "4279355708" "return TappedLength6;"
Block 23 "1794303695" "return TappedLength7;"
Block 24 "1015636407" "return TappedLength8;"
Block 25 "2842316356" "return TappedLength9;"
Block 26 "2609245752" "return TappedLength10;"
Block 27 "241615307" "return TappedLength11;"
Block 28 "1320563001" "return 19;"

CHECKSUM: "3661006289 3087401473"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan.u_biw_obs_fifo
ANNOTATION: "SEP-ESRC-FIFO-INPUT-TIE: entropy_source ties clr_i to 1'b0 (hw/ip/entropy_source/rtl/entropy_source.sv:460) and entropy_churn_enable_i to 1'b0 (hw/ip/entropy_source/rtl/entropy_source.sv:462) on this entropy_fifo instance, so the condition rows that need a 1 on a tied input and the churn true arm cannot occur. NOT waived: the push, pop, full, empty and counter-error terms, and churn_addr/churn_entry/churn_data."
Condition 1 "3834167469" "(push_i & ((~full_prim)) & ((~counter_err)) & ((~clr_i))) 1 -1" (4 "1110")
Condition 2 "750180934" "(pop_i & ((~empty_prim)) & ((~counter_err)) & ((~clr_i))) 1 -1" (4 "1110")
Condition 3 "3059300984" "(push_i & full_prim & ((~clr_i))) 1 -1" (3 "110")
Condition 4 "1666963403" "(pop_i & empty_prim & ((~clr_i))) 1 -1" (3 "110")
Condition 5 "3888848529" "(entropy_churn_enable_i ? ((wdata_i ^ churn_data)) : wdata_i) 1 -1" (2 "1")

CHECKSUM: "3661006289 3240782908"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan.u_biw_obs_fifo
ANNOTATION: "SEP-ESRC-FIFO-INPUT-TIE: entropy_source ties clr_i to 1'b0 (hw/ip/entropy_source/rtl/entropy_source.sv:460) and entropy_churn_enable_i to 1'b0 (hw/ip/entropy_source/rtl/entropy_source.sv:462) on this entropy_fifo instance, so the condition rows that need a 1 on a tied input and the churn true arm cannot occur. NOT waived: the push, pop, full, empty and counter-error terms, and churn_addr/churn_entry/churn_data."
Branch 0 "651385209" "entropy_churn_enable_i" (0) "entropy_churn_enable_i 1"

CHECKSUM: "3661006289 3087401473"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan.u_noise_obs_fifo
ANNOTATION: "SEP-ESRC-FIFO-INPUT-TIE: entropy_source ties entropy_churn_enable_i to 1'b0 (hw/ip/entropy_source/rtl/entropy_source.sv:589) on this entropy_fifo instance, so the condition rows that need a 1 on a tied input and the churn true arm cannot occur. NOT waived: clr_i and its flush condition rows, which follow noise_obs_flush; the push, pop, full, empty and counter-error terms, and churn_addr/churn_entry/churn_data."
Condition 5 "3888848529" "(entropy_churn_enable_i ? ((wdata_i ^ churn_data)) : wdata_i) 1 -1" (2 "1")

CHECKSUM: "3661006289 3240782908"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan.u_noise_obs_fifo
ANNOTATION: "SEP-ESRC-FIFO-INPUT-TIE: entropy_source ties entropy_churn_enable_i to 1'b0 (hw/ip/entropy_source/rtl/entropy_source.sv:589) on this entropy_fifo instance, so the condition rows that need a 1 on a tied input and the churn true arm cannot occur. NOT waived: clr_i and its flush condition rows, which follow noise_obs_flush; the push, pop, full, empty and counter-error terms, and churn_addr/churn_entry/churn_data."
Branch 0 "651385209" "entropy_churn_enable_i" (0) "entropy_churn_enable_i 1"

CHECKSUM: "3661006289 3087401473"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan.u_entropy_fifo
ANNOTATION: "SEP-ESRC-FIFO-INPUT-TIE: entropy_source ties clr_i to 1'b0 (hw/ip/entropy_source/rtl/entropy_source.sv:414) on this entropy_fifo instance, so the condition rows that need a 1 on a tied input and the churn true arm cannot occur. NOT waived: entropy_churn_enable_i and the churn arm, which follow the FIFO_CTRL CSR; the push, pop, full, empty and counter-error terms, and churn_addr/churn_entry/churn_data."
Condition 1 "3834167469" "(push_i & ((~full_prim)) & ((~counter_err)) & ((~clr_i))) 1 -1" (4 "1110")
Condition 2 "750180934" "(pop_i & ((~empty_prim)) & ((~counter_err)) & ((~clr_i))) 1 -1" (4 "1110")
Condition 3 "3059300984" "(push_i & full_prim & ((~clr_i))) 1 -1" (3 "110")
Condition 4 "1666963403" "(pop_i & empty_prim & ((~clr_i))) 1 -1" (3 "110")

CHECKSUM: "560690602 2370236681"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan.u_entropy_source_reg
ANNOTATION: "SEP-ESRC-NOERR-RESP: entropy_source_reg sets cpuif_wr_err='0, readback_err='0 and cpuif_rd_err=readback_err, so axil_resp_buffer_err resets to 0 and loads only 0; the SLVERR arm never executes and BRESP/RRESP hold 2'b00. hw/ip/entropy_source/regs/gen/sv/entropy_source_reg.sv:158,168,173,200-205,3220,3511,3517. NOT waived: the OKAY arm, RDATA and the stall from external_pending."
Block 66 "4057615334" "s_axil.BRESP = 2'b10;"

CHECKSUM: "560690602 2636490419"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_trng.u_entropy_source_s3c_scan.u_entropy_source_reg
ANNOTATION: "SEP-ESRC-NOERR-RESP: entropy_source_reg sets cpuif_wr_err='0, readback_err='0 and cpuif_rd_err=readback_err, so axil_resp_buffer_err resets to 0 and loads only 0; the SLVERR arm never executes and BRESP/RRESP hold 2'b00. hw/ip/entropy_source/regs/gen/sv/entropy_source_reg.sv:158,168,173,200-205,3220,3511,3517. NOT waived: the OKAY arm, RDATA and the stall from external_pending."
Branch 8 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "3497888529 4220762321"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_axis_edn_pool_s3c_scan
ANNOTATION: "SEP-EDN-POOL-CANCEL-TIE: sep_crypto ties endpoint_cancel_i of the pool EDN adapter to '0, so the cancel input and the flush row with clear_i=0, endpoint_cancel_i=1 cannot occur. hw/sys/sep/rtl/sep_crypto.sv:1005; hw/ip/drbg/rtl/drbg_axis_edn_adapter.sv:166. NOT waived: clear_i and its flush row, and the crypto EDN adapter cancel input, which is live (hw/sys/sep/rtl/sep_crypto.sv:981)."
Condition 6 "4163802455" "(clear_i || endpoint_cancel_i[0]) 1 -1" (2 "01")

CHECKSUM: "1557237986 1319700504"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_outbound_filter
ANNOTATION: "SEP-OUTFILTER-SKIP-TIED: hw/sys/sep/rtl/sep.sv:1091 ties outbound_filter_skip_i to 1'b0 and hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_peripherals.sv:433 connects it to filter_skip_i, the only driver of that net. So filter_skip_i is 0 and the skip arm of the isolate_write/isolate_read ternaries (hw/ip/axi_filter/rtl/axi_filter_wrap.sv:224,234) cannot occur. NOT waived: the filter_skip_i = 0 vectors and the nested no-match/allow conditions, which filter traffic moves."
Condition 65 "1848364127" "(filter_skip_i ? 1'b0 : (no_write_filter_matches ? BLOCK_BY_DEFAULT : ((!allow_write[write_filter_hit_idx])))) 1 -1" (2 "1")
Condition 67 "2709885922" "(filter_skip_i ? 1'b0 : (no_read_filter_matches ? BLOCK_BY_DEFAULT : ((!allow_read[read_filter_hit_idx])))) 1 -1" (2 "1")

CHECKSUM: "1557237986 4093739576"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_outbound_filter
ANNOTATION: "SEP-OUTFILTER-SKIP-TIED: hw/sys/sep/rtl/sep.sv:1091 ties outbound_filter_skip_i to 1'b0 and hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_peripherals.sv:433 connects it to filter_skip_i, the only driver of that net. So the filter_skip_i = 1 arm of hw/ip/axi_filter/rtl/axi_filter_wrap.sv:224 and :234 is unreachable. NOT waived: the two filter_skip_i = 0 arms (no-match and hit), which filter traffic reaches."
Branch 0 "572651959" "filter_skip_i" (0) "filter_skip_i 1,-"
Branch 1 "2652501629" "filter_skip_i" (0) "filter_skip_i 1,-"

CHECKSUM: "1620533576 363877172"
MODULE: filter_ctrl_reg
ANNOTATION: "SEP-FILTERREG-LOADNEXT-CONST: hw/ip/axi_filter/regs/gen/sv/filter_ctrl_reg.sv:544-550 and :570-576 assign load_next_c = '1 in both the SW-write arm and the HW-write else arm, so START_ADDR and END_ADDR load_next is always 1. The load_next = 0 arm of the storage flop (:555-558, :581-584) is unreachable. NOT waived: the reset arm and the load arm, and the SW/HW write select at :544 and :570."
Branch 22 "1813063680" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 24 "3372078797" "(~arst_n)" (2) "(~arst_n) 0,0"

CHECKSUM: "2368045406 2525155830"
MODULE: output_remap_reg
ANNOTATION: "SEP-OUTREMAP-ADDR3-TIED: hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv:389,400,458,469 drive s_axil_awaddr/araddr of every output_remap_reg instance as {1'b0, addr[2:0]}, so address bit 3 is 0; hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:137,142,147 build cpuif_addr as {addr[3], 3'b0}, so cpuif_addr, decoded_addr and rd_mux_addr are 0 on every access. The (cpuif_addr == 0) term at hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:247 is never 0. NOT waived: the cpuif_req_masked = 0 vector and the (1 1) vector, which every access moves."
Condition 16 "4082264844" "(cpuif_req_masked & (cpuif_addr == 4'b0)) 1 -1" (2 "10")
Condition 17 "610652891" "(cpuif_addr == 4'b0) 1 -1" (1 "0")

CHECKSUM: "2368045406 1795492639"
MODULE: output_remap_reg
ANNOTATION: "SEP-OUTREMAP-ADDR3-TIED: hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv:389,400,458,469 drive s_axil_awaddr/araddr of every output_remap_reg instance as {1'b0, addr[2:0]}, so address bit 3 is 0; hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:137,142,147 build cpuif_addr as {addr[3], 3'b0}, so cpuif_addr, decoded_addr and rd_mux_addr are 0 on every access. The rd_mux_addr != 0 arm at hw/ip/output_remap/regs/gen/sv/output_remap_reg.sv:358 is unreachable. NOT waived: the rd_mux_addr == 0 arm."
Branch 9 "598101187" "(rd_mux_addr == 4'b0)" (1) "(rd_mux_addr == 4'b0) 0"

CHECKSUM: "2196427632 1402944094"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_cpu.u_ifu_local_alias_remap
ANNOTATION: "SEP-CPU-IFU-AW-ZERO: the VeeR IFU drives awaddr = '0 (vendor/chipsalliance/Cores-VeeR-EL2/upstream/design/ifu/el2_ifu_mem_ctl.sv:1087), and region_size_i is the literal 0x3000_0000 (hw/sys/sep/rtl/sep_cpu.sv:544, hw/sys/sep/rtl/sep_pkg.sv:485). With addr 0, addr >= base holds only for base 0, and then 0 < base + size holds (hw/ip/axi_window_remap/rtl/axi_window_remap.sv:37,42-43), so the (1 0) vector cannot occur. NOT waived: the (0 1) and (1 1) vectors, which SEP_LOCAL_BASE_ADDR moves."
Condition 1 "1033715818" "((slv_req_i.aw.addr >= local_alias_base_i) && ({1'b0, slv_req_i.aw.addr} < local_alias_end)) 1 -1" (2 "10")

CHECKSUM: "2905179362 847969879"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_csr.u_sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-LINE: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:313, :1530 and :1652,1657 assign decoded_err, cpuif_wr_err, cpuif_rd_err and readback_err to constant '0. axil_resp_buffer_err resets to 0 (:167) and loads only these constants (:174-182), so the SLVERR statements at :210-211 never execute. NOT waived: the OKAY statements at :213-214 and all other response-path lines."
Block 66 "3040295231" "s_axil_bresp = 2'b10;"

CHECKSUM: "2905179362 3747101343"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_csr.u_sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-A2-NOERROR-BRANCH: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:313, :1530 and :1652,1657 assign the decode, write and read error terms to constant '0, and axil_resp_buffer_err loads only these constants (:167, :174-182), so the true arm of 'if(axil_resp_buffer_err[...])' at :209 never executes. NOT waived: the false (OKAY) arm."
Branch 4 "2022485169" "axil_resp_buffer_err[axil_resp_rptr[0]]" (0) "axil_resp_buffer_err[axil_resp_rptr[0]] 1"

CHECKSUM: "2905179362 3747101343"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_csr.u_sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-LOADNEXT-CONST-BRANCH: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:1021/1024, :1324/1327, :1350/1353, :1376/1379, :1402/1405, :1428/1431, :1454/1457, :1480/1483 and :1506/1509 assign load_next_c = '1 in both arms of the SW-write test, so load_next is constant 1 for TIMEOUT_CLEAR, DMA_BUS_ERR_CLEAR and the seven PERIPH_BUS_ERR_CLEAR fields, and the implicit else of 'if(load_next)' at :1033, :1336, :1362, :1388, :1414, :1440, :1466, :1492 and :1518 never executes. NOT waived: the reset arm, the load arm, and both arms of the SW-write test."
Branch 34 "4266396544" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 60 "3588033518" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 62 "884099970" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 64 "3291265552" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 66 "278621705" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 68 "54238030" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 70 "2224839643" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 72 "553878654" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 74 "2747625622" "(~arst_n)" (2) "(~arst_n) 0,0"

CHECKSUM: "2905179362 3747101343"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_csr.u_sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-LOADNEXT-CONST-BRANCH: hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:718 and :721 assign load_next_c = '1 in both arms, so REFERENCE_COUNTER load_next is constant 1 and the implicit else of 'if(load_next)' at :730 never executes. NOT waived: the reset arm, the load arm, and both arms of the SW-write test at :716."
Branch 8 "2691458842" "(~arst_n)" (2) "(~arst_n) 0,0"

CHECKSUM: "2906880031 1967776477"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_io.u_sep_ot_spi_wrap.u_spi_axi_lite_to_tlul
ANNOTATION: "SEP-SPI-A2T-ERRCLR-TIED: hw/common/axi/axi_lite_to_tlul.sv:124 row 10 needs err_clr_i = 1, but hw/sys/sep/rtl/sep_ot_spi_wrap.sv:125 ties .err_clr_i to 1'b0. NOT waived: rows 01 and 11 of the same condition."
Condition 1 "3055253419" "(sticky_err_q & ((~err_clr_i))) 1 -1" (2 "10")

CHECKSUM: "2905179362 3747101343"
MODULE: sep_cpu_ctrl_reg
ANNOTATION: "SEP-REGBLOCK-LOADNEXT-BRANCH: in each of these field combos every path sets load_next_c to '1 (for example hw/sys/sep/regs/gen/sv/blocks/sep_cpu_ctrl_reg.sv:718,721 and :1021,1024 and :1324,1327), so the implicit else of 'if(field_combo.*.load_next)' in the storage flop at lines 730, 1033, 1336, 1362, 1388, 1414, 1440, 1466, 1492 and 1518 is unreachable. NOT waived: the reset arm and the load arm of each flop, and the load_next branches of fields that software alone loads."
Branch 8 "2691458842" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 34 "4266396544" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 60 "3588033518" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 62 "884099970" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 64 "3291265552" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 66 "278621705" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 68 "54238030" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 70 "2224839643" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 72 "553878654" "(~arst_n)" (2) "(~arst_n) 0,0"
Branch 74 "2747625622" "(~arst_n)" (2) "(~arst_n) 0,0"

CHECKSUM: "3937190293 1840328202"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:368 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (hw/ip/efuse/rtl/efuse_interface_controller.sv:722), efuse_guard (:814) and on to efuse_shadow_reg_access_control (hw/ip/efuse/rtl/efuse_shadow_regs.sv:286). The statements in the HAS_LC_STATE=0 arms at hw/ip/efuse/rtl/efuse_interface_controller.sv:280-284, :298-302 and :413-419 belong to the SMC elaboration and do not execute here. NOT waived: the HAS_LC_STATE=1 address-decode statements at :274-278, :292-296 and :404-412."
Block 5 "1977898423" "if ((axil_mux_req.aw.addr inside {[EFUSE_MAP_REG_MAP_BASE_ADDR:EfuseCtrlRegMapEndAddr]}))"
Block 6 "1893830314" "efuse_req_decode_select_aw = INTERFACE_SEL;"
Block 7 "1835296389" "efuse_req_decode_select_aw = SHIM_SEL;"
Block 12 "2676881816" "if ((axil_mux_req.ar.addr inside {[EFUSE_MAP_REG_MAP_BASE_ADDR:EfuseCtrlRegMapEndAddr]}))"
Block 13 "3347644321" "efuse_req_decode_select_ar = INTERFACE_SEL;"
Block 14 "1855215342" "efuse_req_decode_select_ar = SHIM_SEL;"
Block 23 "1518193479" "if ((apb_mux_req.paddr inside {[EFUSE_MAP_REG_MAP_BASE_ADDR:EfuseMapRegMapEndAddr]}))"
Block 24 "3333382630" "efuse_reg_select = SHADOW_REG_MAP;"
Block 25 "2891404597" "if ((apb_mux_req.paddr inside {[EFUSE_CTRL_REG_MAP_BASE_ADDR:EfuseCtrlRegMapEndAddr]}))"
Block 26 "357504973" "efuse_reg_select = EFUSE_CSR_REG_MAP;"
Block 27 "3360606802" "efuse_reg_select = ERR_DECODE;"

CHECKSUM: "486751003 420603909"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_guard
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:368 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (hw/ip/efuse/rtl/efuse_interface_controller.sv:722), efuse_guard (:814) and on to efuse_shadow_reg_access_control (hw/ip/efuse/rtl/efuse_shadow_regs.sv:286). The statement in the HAS_LC_STATE=0 arm at hw/ip/efuse/rtl/efuse_guard.sv:116-117 belongs to the SMC elaboration and does not execute here. NOT waived: the HAS_LC_STATE=1 lock statements at :112-113."
Block 10 "2670421632" "pro_read_intf_rm_lc_state_write_lock = efuse_guard.entry_write_locked(pro_read_intf_wr_index, shadow_regs_i);"

CHECKSUM: "171941408 446195242"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:368 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (hw/ip/efuse/rtl/efuse_interface_controller.sv:722), efuse_guard (:814) and on to efuse_shadow_reg_access_control (hw/ip/efuse/rtl/efuse_shadow_regs.sv:286). The statements in the HAS_LC_STATE=0 arms at hw/ip/efuse/rtl/efuse_shadow_regs.sv:229-232 (SMC preload) and :755-760 (SMC APB response reset) do not execute here. NOT waived: the SEP preload statement at :221-225 and the LC_STATE access arm at :728-752."
Block 18 "3048384116" "if (((sim_skip_fuse_sense == 1'b1) && $value$plusargs(\"smc_shadow_reg_preload=%s\", smc_shadow_reg_preload)))"
Block 155 "4129704973" "apb_resp_from_ac.pready <= 1'b0;"

CHECKSUM: "3595078827 3812065443"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs.u_efuse_shadow_reg_access_control
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:368 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (hw/ip/efuse/rtl/efuse_interface_controller.sv:722), efuse_guard (:814) and on to efuse_shadow_reg_access_control (hw/ip/efuse/rtl/efuse_shadow_regs.sv:286). The statement in the HAS_LC_STATE=0 arm at hw/ip/efuse/rtl/efuse_shadow_reg_access_control.sv:152-153 belongs to the SMC elaboration and does not execute here. NOT waived: the HAS_LC_STATE=1 lock statements at :148-149."
Block 8 "4131875210" "is_write_locked = efuse_shadow_reg_access_control.write_locked(field_index);"

CHECKSUM: "3595078827 2100095224"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs.u_efuse_shadow_reg_access_control
ANNOTATION: "SEP-EFUSE-SW-LOCK-CONST: sw_lock_bits comes only from find_efuse_sw_lock over the constant field map, or the default 0 (hw/ip/efuse/rtl/efuse_shadow_reg_access_control.sv:144, :251-260). All 42 map entries are WriteUnlock or WriteSetOnly with ReadUnlock (hw/sys/sep/rtl/efuse/sep_efuse_pkg.sv:525-990), so sw_lock_bits[1] and sw_lock_bits[0] are always 0. The excluded vectors at :161-162 need (sw_lock_bits[2:1] == 2'b11) or sw_lock_bits[0] to be 1. NOT waived: the is_write_locked, is_read_locked, sw_lock_bits[3] and secure_tm_i vectors."
Condition 15 "3957149935" "(is_write_locked | (sw_lock_bits[2:1] == 2'b11) | sw_lock_bits[3]) 1 -1" (3 "010")
Condition 16 "1024332690" "(sw_lock_bits[2:1] == 2'b11) 1 -1" (2 "1")
Condition 17 "57363498" "(is_write_locked | (sw_lock_bits[2:1] == 2'b11)) 1 -1" (2 "01")
Condition 18 "1432529323" "(sw_lock_bits[2:1] == 2'b11) 1 -1" (2 "1")
Condition 19 "2025791036" "(is_read_locked | sw_lock_bits[0]) 1 -1" (2 "01")

CHECKSUM: "1800326492 906278174"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
ANNOTATION: "SEP-SEC-DIS-REV-CELL-HIGH: hw/ip/efuse/rtl/efuse_token_processing.sv:322-329 feed in_i[0] from high[0] with src_high_i tied to 1'b1. prim_rev_cell drives hi_o from src_high_i and out_o from in_i (hw/common/ocah_prim/rtl/prim_rev_cell.sv), so tt_rev_d_out[0] is always 1 and the vector with tt_rev_d_out[0]=0 at :331 cannot occur. NOT waived: the vectors where sec_disable_token_match moves."
Condition 28 "3040491567" "(tt_rev_d_out[0] && (sec_disable_token_match == TOKEN_MATCH_CODE)) 1 -1" (1 "01")

CHECKSUM: "2110255361 1037641077"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_key_manager_s3c_scan.u_cpu
ANNOTATION: "SEP-KM-VROM-NOT-DECODED: without the simulation-only OCAH_KM_VROM define (hw/ip/key_manager/rtl/picorv32_wrapper.sv:323) the wrapper ties is_vrom_addr and is_la_vrom_addr to 1'b0 (hw/ip/key_manager/rtl/picorv32_wrapper.sv:344-345) and vrom_mem_ready and vrom_mem_rdata to 0 (:597-598); vrom_mem_valid and vrom_mem_la_read are gated by those decodes (:454,459). So the MEM_RDATA_SEL_VROM assignments at :495 and :509 and the vrom_mem_rdata read arm at :527 never execute. NOT waived: the ROM, SRAM and peripheral decode and their read-data arms."
Block 15 "2468130845" "mem_rdata_sel_q <= MEM_RDATA_SEL_VROM;"
Block 24 "1467059761" "mem_rdata_sel = MEM_RDATA_SEL_VROM;"
Block 30 "2685447353" "mem_rdata = vrom_mem_rdata;"

CHECKSUM: "2110255361 4240846735"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_key_manager_s3c_scan.u_cpu
ANNOTATION: "SEP-KM-ROMBASE-ZERO: RomBase is km_intf_pkg::RomBaseAddr = 32'h0 (hw/ip/key_manager/rtl/picorv32_wrapper.sv:145; hw/ip/key_manager/rtl/km_intf_pkg.sv:136), so the unsigned compares mem_addr >= RomBase (:312) and mem_la_addr >= RomBase (:318) are always true and row 01 cannot occur. NOT waived: the <= RomEnd term."
Condition 6 "2153538183" "((mem_addr >= RomBase) && (mem_addr <= RomEnd)) 1 -1" (1 "01")
Condition 9 "2824659452" "((mem_la_addr >= RomBase) && (mem_la_addr <= RomEnd)) 1 -1" (1 "01")

CHECKSUM: "483690867 2268580589"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_key_manager_s3c_scan.u_xbar
ANNOTATION: "SEP-KM-XBAR-ELAB-ONLY-FUNC: km_addr_map_aligned and km_addr_map_disjoint read only the elaborated localparams XbarCfg and AddrMap (hw/ip/key_manager/rtl/km_axi_lite_xbar.sv:111-171) and run only in the init assertions at :210-211, so the return 1'b0 statements at :190-192 and :203 never execute while those assertions pass. NOT waived: the loop, compare and return 1'b1 statements."
Block 3 "697137630" "return 1'b0;"
Block 6 "3483238939" "return 1'b0;"
Block 9 "2621016357" "return 1'b0;"
Block 15 "1275860279" "return 1'b0;"
