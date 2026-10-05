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
//   - APB regblocks that decode no error: the pslverr vectors with a 1 operand.
//   - KM CPU virtual-ROM decode, tied off without the simulation-only define.
//   - Elaboration-only constant functions, and
//     the else arms of integrity-generation and HAS_LC_STATE parameters that SEP
//     fixes.
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
ANNOTATION: "AXI2TLUL-INTG-GEN-PARAM: ENABLE_CMD_INTG_GEN and ENABLE_DATA_INTG_GEN default to 1 (hw/common/axi/axi_lite_to_tlul.sv:28-29); every SEP instance keeps the default or passes 1 (hw/sys/sep/rtl/sep_dma_wrap.sv:234-235 from hw/sys/sep/rtl/sep.sv:1187 ENABLE_DATA_INTG_GEN=1), so the else arms at :251/:267 are elaboration-dead."
Branch 3 "1189517418" "ENABLE_CMD_INTG_GEN" (1) "ENABLE_CMD_INTG_GEN 0"
Branch 4 "2160096988" "ENABLE_DATA_INTG_GEN" (1) "ENABLE_DATA_INTG_GEN 0"

CHECKSUM: "2470472206 1300994536"
MODULE: tlul_to_axi_lite
ANNOTATION: "TLUL2AXI-INTG-GEN-PARAM: the only SEP instance (hw/sys/sep/rtl/sep_dma_wrap.sv:259-260) passes ENABLE_DATA_INTG_GEN, set to 1 at sep.sv:1187, to ENABLE_RSP_INTG_GEN and ENABLE_DATA_INTG_GEN, so the else arms at hw/common/axi/tlul_to_axi_lite.sv:281/:296 are elaboration-dead."
Branch 4 "3993283767" "ENABLE_RSP_INTG_GEN" (1) "ENABLE_RSP_INTG_GEN 0"
Branch 5 "2160096988" "ENABLE_DATA_INTG_GEN" (1) "ENABLE_DATA_INTG_GEN 0"

CHECKSUM: "486751003 1618864423"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_guard
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:364 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (:722), efuse_guard (:814) and on to efuse_shadow_reg_access_control (efuse_shadow_regs.sv:286). The HAS_LC_STATE=0 arms of efuse_guard at lines 102, 110 belong to the SMC elaboration and are dead here."
Branch 0 "4169860434" "HAS_LC_STATE" (3) "HAS_LC_STATE 0,-,-"
Branch 1 "4285556711" "HAS_LC_STATE" (4) "HAS_LC_STATE 0,-,-"

CHECKSUM: "3937190293 4074944007"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:364 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (:722), efuse_guard (:814) and on to efuse_shadow_reg_access_control (efuse_shadow_regs.sv:286). The HAS_LC_STATE=0 arms of efuse_interface_controller at lines 273, 291, 403 belong to the SMC elaboration and are dead here."
Branch 0 "3458527583" "HAS_LC_STATE" (2) "HAS_LC_STATE 0,-,1"
Branch 0 "3458527583" "HAS_LC_STATE" (3) "HAS_LC_STATE 0,-,0"
Branch 1 "221850953" "HAS_LC_STATE" (2) "HAS_LC_STATE 0,-,1"
Branch 1 "221850953" "HAS_LC_STATE" (3) "HAS_LC_STATE 0,-,0"
Branch 2 "1075115012" "HAS_LC_STATE" (4) "HAS_LC_STATE 0,-,-,-,1,-"
Branch 2 "1075115012" "HAS_LC_STATE" (5) "HAS_LC_STATE 0,-,-,-,0,1"
Branch 2 "1075115012" "HAS_LC_STATE" (6) "HAS_LC_STATE 0,-,-,-,0,0"

CHECKSUM: "3804881079 3321935136"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs.u_efuse_shadow_reg_access_control
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:364 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (:722), efuse_guard (:814) and on to efuse_shadow_reg_access_control (efuse_shadow_regs.sv:286). The HAS_LC_STATE=0 arms of efuse_shadow_reg_access_control at lines 146 belong to the SMC elaboration and are dead here."
Branch 1 "465878905" "HAS_LC_STATE" (4) "HAS_LC_STATE 0,-,-"

CHECKSUM: "1922851758 222844965"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs
ANNOTATION: "SEP-HAS-LC-STATE: hw/sys/sep/rtl/efuse/sep_efuse_wrapper.sv:364 sets HAS_LC_STATE=1 on efuse_interface_controller, which passes it to efuse_shadow_regs (:722), efuse_guard (:814) and on to efuse_shadow_reg_access_control (efuse_shadow_regs.sv:286). The HAS_LC_STATE=0 arms of efuse_shadow_regs at lines 218, 336 belong to the SMC elaboration and are dead here."
Branch 2 "3908413232" "HAS_LC_STATE" (2) "HAS_LC_STATE 0,-,1"
Branch 2 "3908413232" "HAS_LC_STATE" (3) "HAS_LC_STATE 0,-,0"
Branch 4 "379866125" "HAS_LC_STATE" (14) "HAS_LC_STATE 0,-,-,-,-,-,-,-,-,-,-,-,-"
