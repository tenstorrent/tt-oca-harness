// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//==================================================
// SEP VCS coverage exclusions -- crossbar and interconnect toggle bits that the
// RTL makes constant.
// Format Version: 2
// ExclMode: default
//
// Scope: the cocotb VCS elaboration of sep_uvm_top, target `default`, on top of
// the other cov/config/vcs exclusion files. Instances:
// sep_local_axi_xbar_wrapper and its sep_local_axi_xbar,
// sep_system_peripherals_xbar_wrapper and its sep_system_peripherals_xbar, and
// sep_crypto_axi_interconnect.
//
// Each block waives bits that cannot take a second value in any legal system:
//   * a direct copy of an IFU, debug or DMA port field that
//     sep_master_tie_exclusions.el waives;
//   * a cpu_tcm target field that the DMA (its only initiator) ties to 0;
//   * the DMA AxPROT, which the DMA TL-UL to AXI-Lite bridge ties to 0;
//   * the cpu_tcm response rlast, which the VeeR DMA slave ties to 1;
//   * the reset_ctrl read data bits [63:7], which its register block ties to 0;
//   * the mailbox response bit 0, which every mailbox response literal holds
//     at 0;
//   * the ext ID bit that axi_id_remap holds at 0, the tied test_i input, the
//     tied cpu_tcm response USER, and the OTBN AxCACHE bit that the
//     interconnect forces to 1.
//
// Three rules keep this file honest:
//   * A field that the SMN inbound port, an integrator-driven target, the no_cpu
//     bench force on the LSU port, or any free CPU/DMA field can reach is NOT
//     listed. Those holes are stimulus gaps.
//   * An address bit that only a decode-range argument holds constant is NOT
//     listed.
//   * A bit that any leaf toggles in either direction is NOT listed. No listed
//     bit toggles in the merged database that supplies the checksums, and
//     urg -excl_strict accepts the file.
//
// Checksums come from `urg -dump full_exclusions tgl` on the merged VDB.
//==================================================

CHECKSUM: "3529663893 1660934675"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_local_axi_xbar_wrapper.u_sep_local_axi_xbar
ANNOTATION: "SEP-XBAR-INPUT-COPY: xbar_slv_req[0], [2] and [3] are direct copies of the IFU, debug and DMA initiator ports (hw/sys/sep/rtl/crossbars/sep_local_axi_xbar.sv:215-227). Each listed field is the same tied field that sep_master_tie_exclusions.el waives on the port (IFU el2_ifu_mem_ctl.sv:1074-1101, debug el2_dbg.sv:738-774, DMA axi_lite_to_axi.sv:39-67 and sep_dma_wrap.sv:283-284, AxUSER/AWATOP sep_cpu.sv:493-505). NOT waived: every xbar_slv_req[1] (LSU) field, because the no_cpu bench force on u_sep_cpu.lsu_axi_req moves the LSU ties; xbar_slv_req[4] (ext, integrator-driven); and every field the base file leaves graded. aw.addr bit 28 stays graded on xbar_slv_req[0] after the IFU window remap: axi_window_remap (hw/ip/axi_window_remap/rtl/axi_window_remap.sv:37-53) moves a raw address of 0 to 0x1000_0000 when SEP_LOCAL_BASE_ADDR[31:0] is 0, and that CSR is software-writable (sep_cpu_ctrl.rdl:184-191)."
Toggle xbar_slv_req[0].ar.size "logic xbar_slv_req[0].ar.size[2:0]"
Toggle xbar_slv_req[0].ar.prot "logic xbar_slv_req[0].ar.prot[2:0]"
Toggle xbar_slv_req[0].ar.cache "logic xbar_slv_req[0].ar.cache[3:0]"
Toggle xbar_slv_req[0].ar.len "logic xbar_slv_req[0].ar.len[7:0]"
Toggle xbar_slv_req[0].ar.burst "logic xbar_slv_req[0].ar.burst[1:0]"
Toggle xbar_slv_req[0].ar.qos "logic xbar_slv_req[0].ar.qos[3:0]"
Toggle xbar_slv_req[0].ar.lock "logic xbar_slv_req[0].ar.lock"
Toggle xbar_slv_req[0].ar.user "logic xbar_slv_req[0].ar.user[11:0]"
Toggle xbar_slv_req[0].aw_valid "logic xbar_slv_req[0].aw_valid"
Toggle xbar_slv_req[0].aw.id "logic xbar_slv_req[0].aw.id[2:0]"
Toggle xbar_slv_req[0].aw.addr [0] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [1] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [2] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [3] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [4] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [5] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [6] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [7] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [8] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [9] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [10] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [11] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [12] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [13] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [14] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [15] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [16] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [17] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [18] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [19] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [20] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [21] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [22] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [23] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [24] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [25] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [26] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [27] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [29] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [30] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.addr [31] "logic xbar_slv_req[0].aw.addr[31:0]"
Toggle xbar_slv_req[0].aw.len "logic xbar_slv_req[0].aw.len[7:0]"
Toggle xbar_slv_req[0].aw.size "logic xbar_slv_req[0].aw.size[2:0]"
Toggle xbar_slv_req[0].aw.burst "logic xbar_slv_req[0].aw.burst[1:0]"
Toggle xbar_slv_req[0].aw.lock "logic xbar_slv_req[0].aw.lock"
Toggle xbar_slv_req[0].aw.cache "logic xbar_slv_req[0].aw.cache[3:0]"
Toggle xbar_slv_req[0].aw.prot "logic xbar_slv_req[0].aw.prot[2:0]"
Toggle xbar_slv_req[0].aw.qos "logic xbar_slv_req[0].aw.qos[3:0]"
Toggle xbar_slv_req[0].aw.region "logic xbar_slv_req[0].aw.region[3:0]"
Toggle xbar_slv_req[0].aw.atop "logic xbar_slv_req[0].aw.atop[5:0]"
Toggle xbar_slv_req[0].aw.user "logic xbar_slv_req[0].aw.user[11:0]"
Toggle xbar_slv_req[0].w_valid "logic xbar_slv_req[0].w_valid"
Toggle xbar_slv_req[0].w.data "logic xbar_slv_req[0].w.data[63:0]"
Toggle xbar_slv_req[0].w.strb "logic xbar_slv_req[0].w.strb[7:0]"
Toggle xbar_slv_req[0].w.last "logic xbar_slv_req[0].w.last"
Toggle xbar_slv_req[0].w.user "logic xbar_slv_req[0].w.user[11:0]"
Toggle xbar_slv_req[0].b_ready "logic xbar_slv_req[0].b_ready"
Toggle xbar_slv_req[2].aw.id "logic xbar_slv_req[2].aw.id[2:0]"
Toggle xbar_slv_req[2].aw.prot "logic xbar_slv_req[2].aw.prot[2:0]"
Toggle xbar_slv_req[2].aw.cache "logic xbar_slv_req[2].aw.cache[3:0]"
Toggle xbar_slv_req[2].aw.len "logic xbar_slv_req[2].aw.len[7:0]"
Toggle xbar_slv_req[2].aw.burst "logic xbar_slv_req[2].aw.burst[1:0]"
Toggle xbar_slv_req[2].aw.qos "logic xbar_slv_req[2].aw.qos[3:0]"
Toggle xbar_slv_req[2].aw.lock "logic xbar_slv_req[2].aw.lock"
Toggle xbar_slv_req[2].aw.user "logic xbar_slv_req[2].aw.user[11:0]"
Toggle xbar_slv_req[2].aw.atop "logic xbar_slv_req[2].aw.atop[5:0]"
Toggle xbar_slv_req[2].ar.id "logic xbar_slv_req[2].ar.id[2:0]"
Toggle xbar_slv_req[2].ar.prot "logic xbar_slv_req[2].ar.prot[2:0]"
Toggle xbar_slv_req[2].ar.cache "logic xbar_slv_req[2].ar.cache[3:0]"
Toggle xbar_slv_req[2].ar.len "logic xbar_slv_req[2].ar.len[7:0]"
Toggle xbar_slv_req[2].ar.burst "logic xbar_slv_req[2].ar.burst[1:0]"
Toggle xbar_slv_req[2].ar.qos "logic xbar_slv_req[2].ar.qos[3:0]"
Toggle xbar_slv_req[2].ar.lock "logic xbar_slv_req[2].ar.lock"
Toggle xbar_slv_req[2].ar.user "logic xbar_slv_req[2].ar.user[11:0]"
Toggle xbar_slv_req[2].w.last "logic xbar_slv_req[2].w.last"
Toggle xbar_slv_req[2].w.user "logic xbar_slv_req[2].w.user[11:0]"
Toggle xbar_slv_req[2].b_ready "logic xbar_slv_req[2].b_ready"
Toggle xbar_slv_req[2].r_ready "logic xbar_slv_req[2].r_ready"
Toggle xbar_slv_req[3].aw.id "logic xbar_slv_req[3].aw.id[2:0]"
Toggle xbar_slv_req[3].aw.len "logic xbar_slv_req[3].aw.len[7:0]"
Toggle xbar_slv_req[3].aw.burst "logic xbar_slv_req[3].aw.burst[1:0]"
Toggle xbar_slv_req[3].aw.lock "logic xbar_slv_req[3].aw.lock"
Toggle xbar_slv_req[3].aw.cache "logic xbar_slv_req[3].aw.cache[3:0]"
Toggle xbar_slv_req[3].aw.qos "logic xbar_slv_req[3].aw.qos[3:0]"
Toggle xbar_slv_req[3].aw.region "logic xbar_slv_req[3].aw.region[3:0]"
Toggle xbar_slv_req[3].aw.atop "logic xbar_slv_req[3].aw.atop[5:0]"
Toggle xbar_slv_req[3].aw.user "logic xbar_slv_req[3].aw.user[11:0]"
Toggle xbar_slv_req[3].ar.id "logic xbar_slv_req[3].ar.id[2:0]"
Toggle xbar_slv_req[3].ar.len "logic xbar_slv_req[3].ar.len[7:0]"
Toggle xbar_slv_req[3].ar.burst "logic xbar_slv_req[3].ar.burst[1:0]"
Toggle xbar_slv_req[3].ar.lock "logic xbar_slv_req[3].ar.lock"
Toggle xbar_slv_req[3].ar.cache "logic xbar_slv_req[3].ar.cache[3:0]"
Toggle xbar_slv_req[3].ar.qos "logic xbar_slv_req[3].ar.qos[3:0]"
Toggle xbar_slv_req[3].ar.region "logic xbar_slv_req[3].ar.region[3:0]"
Toggle xbar_slv_req[3].ar.user "logic xbar_slv_req[3].ar.user[11:0]"
Toggle xbar_slv_req[3].w.user "logic xbar_slv_req[3].w.user[11:0]"
ANNOTATION: "SEP-XBAR-TEST-TIED: sep_local_axi_xbar_wrapper.sv:205 drives test_i with 1'b0; no other driver exists."
Toggle test_i "logic test_i"
ANNOTATION: "SEP-XBAR-EXT-ID-ADDR: the ext initiator is the sep_system_peripherals forward path only (sep.sv:432). Its ID passes axi_id_remap with 4 table entries, which drives mst aw/ar id as {1'b0, 2-bit index} (vendor/pulp-platform/axi/upstream/src/axi_id_remap.sv:198-200; MAX_INFLIGHT_IDS=4 at hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_peripherals.sv:694), so id[2] is constant 0. NOT waived: id[1:0], every address bit (a decode-range argument only), and every other field, which the SMN inbound port drives."
Toggle ext_req_i.aw.id [2] "logic ext_req_i.aw.id[2:0]"
Toggle ext_req_i.ar.id [2] "logic ext_req_i.ar.id[2:0]"
Toggle xbar_slv_req[4].aw.id [2] "logic xbar_slv_req[4].aw.id[2:0]"
Toggle xbar_slv_req[4].ar.id [2] "logic xbar_slv_req[4].ar.id[2:0]"
ANNOTATION: "SEP-XBAR-TARGET-TIED: the cpu_tcm target port (target 0) carries only DMA beats, because Connectivity (sep_local_axi_xbar_pkg.sv:140-146) connects no other initiator to it. The axi_mux spill registers reset to 0 and load only on a valid handshake (vendor/pulp-platform/common_cells/upstream/src/spill_register_flushable.sv:45-47,78; LatencyMode CUT_ALL_PORTS at sep_local_axi_xbar_pkg.sv:126), and unconnected mux inputs are tied to 0 (axi_xbar_unmuxed.sv:241). axi_mux prepends the 3-bit initiator index above the 3-bit initiator ID (axi_id_prepend.sv:92-93). Each listed field is 0 in every DMA beat: qos, lock, len, burst, region, AWATOP, id[2:0], AxUSER and WUSER from axi_lite_to_axi.sv:39-67, cache from sep_dma_wrap.sv:283-284, and the DMA upsizer (sep_dma_wrap.sv:306) passes them unchanged. NOT waived: id[5:3] (the initiator index), every address bit (a decode-range argument only), prot and size, and every field on targets 1-9, which LSU fields moved by the no_cpu bench force, ext (integrator-driven) or free CPU/DMA fields reach."
Toggle cpu_tcm_req_o.ar.qos "logic cpu_tcm_req_o.ar.qos[3:0]"
Toggle xbar_mst_req[0].ar.qos "logic xbar_mst_req[0].ar.qos[3:0]"
Toggle cpu_tcm_req_o.ar.user "logic cpu_tcm_req_o.ar.user[11:0]"
Toggle xbar_mst_req[0].ar.user "logic xbar_mst_req[0].ar.user[11:0]"
Toggle cpu_tcm_req_o.ar.lock "logic cpu_tcm_req_o.ar.lock"
Toggle xbar_mst_req[0].ar.lock "logic xbar_mst_req[0].ar.lock"
Toggle cpu_tcm_req_o.ar.len "logic cpu_tcm_req_o.ar.len[7:0]"
Toggle xbar_mst_req[0].ar.len "logic xbar_mst_req[0].ar.len[7:0]"
Toggle cpu_tcm_req_o.ar.burst "logic cpu_tcm_req_o.ar.burst[1:0]"
Toggle xbar_mst_req[0].ar.burst "logic xbar_mst_req[0].ar.burst[1:0]"
Toggle cpu_tcm_req_o.ar.region "logic cpu_tcm_req_o.ar.region[3:0]"
Toggle xbar_mst_req[0].ar.region "logic xbar_mst_req[0].ar.region[3:0]"
Toggle cpu_tcm_req_o.ar.cache "logic cpu_tcm_req_o.ar.cache[3:0]"
Toggle xbar_mst_req[0].ar.cache "logic xbar_mst_req[0].ar.cache[3:0]"
Toggle cpu_tcm_req_o.ar.id [2:0] "logic cpu_tcm_req_o.ar.id[5:0]"
Toggle xbar_mst_req[0].ar.id [2:0] "logic xbar_mst_req[0].ar.id[5:0]"
Toggle cpu_tcm_req_o.aw.qos "logic cpu_tcm_req_o.aw.qos[3:0]"
Toggle xbar_mst_req[0].aw.qos "logic xbar_mst_req[0].aw.qos[3:0]"
Toggle cpu_tcm_req_o.aw.user "logic cpu_tcm_req_o.aw.user[11:0]"
Toggle xbar_mst_req[0].aw.user "logic xbar_mst_req[0].aw.user[11:0]"
Toggle cpu_tcm_req_o.aw.lock "logic cpu_tcm_req_o.aw.lock"
Toggle xbar_mst_req[0].aw.lock "logic xbar_mst_req[0].aw.lock"
Toggle cpu_tcm_req_o.aw.atop "logic cpu_tcm_req_o.aw.atop[5:0]"
Toggle xbar_mst_req[0].aw.atop "logic xbar_mst_req[0].aw.atop[5:0]"
Toggle cpu_tcm_req_o.aw.len "logic cpu_tcm_req_o.aw.len[7:0]"
Toggle xbar_mst_req[0].aw.len "logic xbar_mst_req[0].aw.len[7:0]"
Toggle cpu_tcm_req_o.aw.burst "logic cpu_tcm_req_o.aw.burst[1:0]"
Toggle xbar_mst_req[0].aw.burst "logic xbar_mst_req[0].aw.burst[1:0]"
Toggle cpu_tcm_req_o.aw.region "logic cpu_tcm_req_o.aw.region[3:0]"
Toggle xbar_mst_req[0].aw.region "logic xbar_mst_req[0].aw.region[3:0]"
Toggle cpu_tcm_req_o.aw.cache "logic cpu_tcm_req_o.aw.cache[3:0]"
Toggle xbar_mst_req[0].aw.cache "logic xbar_mst_req[0].aw.cache[3:0]"
Toggle cpu_tcm_req_o.aw.id [2:0] "logic cpu_tcm_req_o.aw.id[5:0]"
Toggle xbar_mst_req[0].aw.id [2:0] "logic xbar_mst_req[0].aw.id[5:0]"
Toggle cpu_tcm_req_o.w.user "logic cpu_tcm_req_o.w.user[11:0]"
Toggle xbar_mst_req[0].w.user "logic xbar_mst_req[0].w.user[11:0]"
ANNOTATION: "SEP-XBAR-TCM-RESP-USER-TIED: the cpu_tcm target is the VeeR DMA slave port of u_sep_cpu (hw/sys/sep/rtl/sep.sv:437,710), and sep_cpu.sv:511-512 drive its B and R USER to SEP_SOURCE_ID, 4'b1111 zero-extended to 12 bits (sep_pkg.sv:489), from time 0. NOT waived: response user on every other target and on the initiator side, which integrator-driven targets (sep_system_peripherals, sep_external) can move."
Toggle cpu_tcm_resp_i.r.user "logic cpu_tcm_resp_i.r.user[11:0]"
Toggle cpu_tcm_resp_i.b.user "logic cpu_tcm_resp_i.b.user[11:0]"
Toggle xbar_mst_resp[0].r.user "logic xbar_mst_resp[0].r.user[11:0]"
Toggle xbar_mst_resp[0].b.user "logic xbar_mst_resp[0].b.user[11:0]"

CHECKSUM: "366726899 3902493086"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_local_axi_xbar_wrapper
ANNOTATION: "SEP-XBAR-EXT-ID-ADDR: the ext initiator is the sep_system_peripherals forward path only (sep.sv:432). Its ID passes axi_id_remap with 4 table entries, which drives mst aw/ar id as {1'b0, 2-bit index} (vendor/pulp-platform/axi/upstream/src/axi_id_remap.sv:198-200; MAX_INFLIGHT_IDS=4 at hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_peripherals.sv:694), so id[2] is constant 0. NOT waived: id[1:0], every address bit (a decode-range argument only), and every other field, which the SMN inbound port drives."
Toggle ext_axi_req_i.aw.id [2] "logic ext_axi_req_i.aw.id[2:0]"
Toggle ext_axi_req_i.ar.id [2] "logic ext_axi_req_i.ar.id[2:0]"
Toggle ext_req.aw.id [2] "logic ext_req.aw.id[2:0]"
Toggle ext_req.ar.id [2] "logic ext_req.ar.id[2:0]"
ANNOTATION: "SEP-XBAR-TARGET-TIED: the cpu_tcm target port (target 0) carries only DMA beats, because Connectivity (sep_local_axi_xbar_pkg.sv:140-146) connects no other initiator to it. The axi_mux spill registers reset to 0 and load only on a valid handshake (vendor/pulp-platform/common_cells/upstream/src/spill_register_flushable.sv:45-47,78; LatencyMode CUT_ALL_PORTS at sep_local_axi_xbar_pkg.sv:126), and unconnected mux inputs are tied to 0 (axi_xbar_unmuxed.sv:241). axi_mux prepends the 3-bit initiator index above the 3-bit initiator ID (axi_id_prepend.sv:92-93). Each listed field is 0 in every DMA beat: qos, lock, len, burst, region, AWATOP, id[2:0], AxUSER and WUSER from axi_lite_to_axi.sv:39-67, cache from sep_dma_wrap.sv:283-284, and the DMA upsizer (sep_dma_wrap.sv:306) passes them unchanged. NOT waived: id[5:3] (the initiator index), every address bit (a decode-range argument only), prot and size, and every field on targets 1-9, which LSU fields moved by the no_cpu bench force, ext (integrator-driven) or free CPU/DMA fields reach."
Toggle cpu_tcm_axi_req_o.ar.qos "logic cpu_tcm_axi_req_o.ar.qos[3:0]"
Toggle cpu_tcm_req.ar.qos "logic cpu_tcm_req.ar.qos[3:0]"
Toggle cpu_tcm_axi_req_o.ar.user "logic cpu_tcm_axi_req_o.ar.user[11:0]"
Toggle cpu_tcm_req.ar.user "logic cpu_tcm_req.ar.user[11:0]"
Toggle cpu_tcm_axi_req_o.ar.lock "logic cpu_tcm_axi_req_o.ar.lock"
Toggle cpu_tcm_req.ar.lock "logic cpu_tcm_req.ar.lock"
Toggle cpu_tcm_axi_req_o.ar.len "logic cpu_tcm_axi_req_o.ar.len[7:0]"
Toggle cpu_tcm_req.ar.len "logic cpu_tcm_req.ar.len[7:0]"
Toggle cpu_tcm_axi_req_o.ar.burst "logic cpu_tcm_axi_req_o.ar.burst[1:0]"
Toggle cpu_tcm_req.ar.burst "logic cpu_tcm_req.ar.burst[1:0]"
Toggle cpu_tcm_axi_req_o.ar.region "logic cpu_tcm_axi_req_o.ar.region[3:0]"
Toggle cpu_tcm_req.ar.region "logic cpu_tcm_req.ar.region[3:0]"
Toggle cpu_tcm_axi_req_o.ar.cache "logic cpu_tcm_axi_req_o.ar.cache[3:0]"
Toggle cpu_tcm_req.ar.cache "logic cpu_tcm_req.ar.cache[3:0]"
Toggle cpu_tcm_axi_req_o.ar.id [2:0] "logic cpu_tcm_axi_req_o.ar.id[5:0]"
Toggle cpu_tcm_req.ar.id [2:0] "logic cpu_tcm_req.ar.id[5:0]"
Toggle cpu_tcm_axi_req_o.aw.qos "logic cpu_tcm_axi_req_o.aw.qos[3:0]"
Toggle cpu_tcm_req.aw.qos "logic cpu_tcm_req.aw.qos[3:0]"
Toggle cpu_tcm_axi_req_o.aw.user "logic cpu_tcm_axi_req_o.aw.user[11:0]"
Toggle cpu_tcm_req.aw.user "logic cpu_tcm_req.aw.user[11:0]"
Toggle cpu_tcm_axi_req_o.aw.lock "logic cpu_tcm_axi_req_o.aw.lock"
Toggle cpu_tcm_req.aw.lock "logic cpu_tcm_req.aw.lock"
Toggle cpu_tcm_axi_req_o.aw.atop "logic cpu_tcm_axi_req_o.aw.atop[5:0]"
Toggle cpu_tcm_req.aw.atop "logic cpu_tcm_req.aw.atop[5:0]"
Toggle cpu_tcm_axi_req_o.aw.len "logic cpu_tcm_axi_req_o.aw.len[7:0]"
Toggle cpu_tcm_req.aw.len "logic cpu_tcm_req.aw.len[7:0]"
Toggle cpu_tcm_axi_req_o.aw.burst "logic cpu_tcm_axi_req_o.aw.burst[1:0]"
Toggle cpu_tcm_req.aw.burst "logic cpu_tcm_req.aw.burst[1:0]"
Toggle cpu_tcm_axi_req_o.aw.region "logic cpu_tcm_axi_req_o.aw.region[3:0]"
Toggle cpu_tcm_req.aw.region "logic cpu_tcm_req.aw.region[3:0]"
Toggle cpu_tcm_axi_req_o.aw.cache "logic cpu_tcm_axi_req_o.aw.cache[3:0]"
Toggle cpu_tcm_req.aw.cache "logic cpu_tcm_req.aw.cache[3:0]"
Toggle cpu_tcm_axi_req_o.aw.id [2:0] "logic cpu_tcm_axi_req_o.aw.id[5:0]"
Toggle cpu_tcm_req.aw.id [2:0] "logic cpu_tcm_req.aw.id[5:0]"
Toggle cpu_tcm_axi_req_o.w.user "logic cpu_tcm_axi_req_o.w.user[11:0]"
Toggle cpu_tcm_req.w.user "logic cpu_tcm_req.w.user[11:0]"
ANNOTATION: "SEP-XBAR-TCM-RESP-USER-TIED: the cpu_tcm target is the VeeR DMA slave port of u_sep_cpu (hw/sys/sep/rtl/sep.sv:437,710), and sep_cpu.sv:511-512 drive its B and R USER to SEP_SOURCE_ID, 4'b1111 zero-extended to 12 bits (sep_pkg.sv:489), from time 0. NOT waived: response user on every other target and on the initiator side, which integrator-driven targets (sep_system_peripherals, sep_external) can move."
Toggle cpu_tcm_axi_resp_i.r.user "logic cpu_tcm_axi_resp_i.r.user[11:0]"
Toggle cpu_tcm_axi_resp_i.b.user "logic cpu_tcm_axi_resp_i.b.user[11:0]"
Toggle cpu_tcm_resp.r.user "logic cpu_tcm_resp.r.user[11:0]"
Toggle cpu_tcm_resp.b.user "logic cpu_tcm_resp.b.user[11:0]"

CHECKSUM: "2309898495 127789342"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_crypto.u_sep_crypto_axi_interconnect
ANNOTATION: "SEP-CRYPTO-OTBN-CACHE-FORCED: sep_crypto_axi_interconnect.sv:337-344 ORs axi_pkg::CACHE_MODIFIABLE (4'b0010) into the OTBN AxCACHE, so bit 1 is constant 1. NOT waived: cache bits 0, 2 and 3."
Toggle otbn_axi_req_cache_forced.aw.cache [1] "logic otbn_axi_req_cache_forced.aw.cache[3:0]"
Toggle otbn_axi_req_cache_forced.ar.cache [1] "logic otbn_axi_req_cache_forced.ar.cache[3:0]"

CHECKSUM: "366726899 3902493086"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_local_axi_xbar_wrapper
ANNOTATION: "SEP-XBAR-DMA-PROT-TCM-RLAST: hw/common/axi/tlul_to_axi_lite.sv:156 zeroes axi_lite_req_o and never sets prot; vendor/pulp-platform/axi/upstream/src/axi_lite_to_axi.sv:42,59, the upsizer and the window remap copy it, so DMA AxPROT is 0. vendor/chipsalliance/Cores-VeeR-EL2/upstream/design/el2_dma_ctrl.sv:492 assigns dma_axi_rlast = 1'b1, wired through hw/sys/sep/rtl/sep_cpu.sv:431 and hw/sys/sep/rtl/crossbars/sep_local_axi_xbar.sv:280. NOT waived: the cpu_tcm target request fields and response IDs, which depend on crossbar routing."
Toggle dma_axi_req_i.ar.prot "logic dma_axi_req_i.ar.prot[2:0]"
Toggle dma_axi_req_i.aw.prot "logic dma_axi_req_i.aw.prot[2:0]"
Toggle dma_req.ar.prot "logic dma_req.ar.prot[2:0]"
Toggle dma_req.aw.prot "logic dma_req.aw.prot[2:0]"
Toggle cpu_tcm_axi_resp_i.r.last "logic cpu_tcm_axi_resp_i.r.last"
Toggle cpu_tcm_resp.r.last "logic cpu_tcm_resp.r.last"

CHECKSUM: "3529663893 1660934675"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_local_axi_xbar_wrapper.u_sep_local_axi_xbar
ANNOTATION: "SEP-XBAR-DMA-PROT-TCM-RLAST: hw/common/axi/tlul_to_axi_lite.sv:156 zeroes axi_lite_req_o and never sets prot; vendor/pulp-platform/axi/upstream/src/axi_lite_to_axi.sv:42,59, the upsizer and the window remap copy it, so DMA AxPROT is 0. vendor/chipsalliance/Cores-VeeR-EL2/upstream/design/el2_dma_ctrl.sv:492 assigns dma_axi_rlast = 1'b1, wired through hw/sys/sep/rtl/sep_cpu.sv:431 and hw/sys/sep/rtl/crossbars/sep_local_axi_xbar.sv:280. NOT waived: the cpu_tcm target request fields and response IDs."
Toggle dma_req_i.ar.prot "logic dma_req_i.ar.prot[2:0]"
Toggle dma_req_i.aw.prot "logic dma_req_i.aw.prot[2:0]"
Toggle xbar_slv_req[3].ar.prot "logic xbar_slv_req[3].ar.prot[2:0]"
Toggle xbar_slv_req[3].aw.prot "logic xbar_slv_req[3].aw.prot[2:0]"
Toggle cpu_tcm_resp_i.r.last "logic cpu_tcm_resp_i.r.last"
Toggle xbar_mst_resp[0].r.last "logic xbar_mst_resp[0].r.last"

CHECKSUM: "366726899 3902493086"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_local_axi_xbar_wrapper
ANNOTATION: "SEP-XBAR-RSTCTL-RDATA-WIDTH: hw/sys/sep/regs/gen/sv/blocks/sep_reset_ctrl_reg.sv:500-510 set readback bits [6:0] only, and vendor/pulp-platform/axi/upstream/src/axi_to_axi_lite.sv:166 and vendor/pulp-platform/axi/upstream/src/axi_atop_filter.sv:260,287 pass that data or '0, so read data [63:7] is 0. NOT waived: read data [6:0], which the SW_RESET_N fields drive."
Toggle sep_reset_ctrl_axi_resp_i.r.data [63:7] "logic sep_reset_ctrl_axi_resp_i.r.data[63:0]"
Toggle sep_reset_ctrl_resp.r.data [63:7] "logic sep_reset_ctrl_resp.r.data[63:0]"

CHECKSUM: "3529663893 1660934675"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_local_axi_xbar_wrapper.u_sep_local_axi_xbar
ANNOTATION: "SEP-XBAR-RSTCTL-RDATA-WIDTH: hw/sys/sep/regs/gen/sv/blocks/sep_reset_ctrl_reg.sv:500-510 set readback bits [6:0] only, and vendor/pulp-platform/axi/upstream/src/axi_to_axi_lite.sv:166 and vendor/pulp-platform/axi/upstream/src/axi_atop_filter.sv:260,287 pass that data or '0, so read data [63:7] is 0. NOT waived: read data [6:0]."
Toggle sep_reset_ctrl_resp_i.r.data [63:7] "logic sep_reset_ctrl_resp_i.r.data[63:0]"

CHECKSUM: "3560311852 126358546"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_peripherals_xbar_wrapper
ANNOTATION: "SEP-MBX-RESP-BIT0: vendor/pulp-platform/axi/upstream/src/axi_lite_mailbox.sv:319,322 and :370-419 assign only RESP_OKAY or RESP_SLVERR, and the mailbox unit has no error slave (hw/ip/axi_lite_mailbox_unit/rtl/axi_lite_mailbox_unit.sv:88-104), so response bit 0 is 0. NOT waived: response bit 1."
Toggle mailbox_resp_i.r.resp [0] "logic mailbox_resp_i.r.resp[1:0]"
Toggle mailbox_resp_i.b.resp [0] "logic mailbox_resp_i.b.resp[1:0]"
Toggle mailbox_resp.r.resp [0] "logic mailbox_resp.r.resp[1:0]"
Toggle mailbox_resp.b.resp [0] "logic mailbox_resp.b.resp[1:0]"

CHECKSUM: "1490650064 2890434499"
INSTANCE: sep_uvm_top.u_dut.u_sep.u_sep_system_peripherals.u_sep_system_peripherals_xbar_wrapper.u_sep_system_peripherals_xbar
ANNOTATION: "SEP-MBX-RESP-BIT0: vendor/pulp-platform/axi/upstream/src/axi_lite_mailbox.sv:319,322 and :370-419 assign only RESP_OKAY or RESP_SLVERR, and the mailbox unit has no error slave (hw/ip/axi_lite_mailbox_unit/rtl/axi_lite_mailbox_unit.sv:88-104), so response bit 0 is 0. NOT waived: response bit 1."
Toggle mailbox_resp_i.r.resp [0] "logic mailbox_resp_i.r.resp[1:0]"
Toggle mailbox_resp_i.b.resp [0] "logic mailbox_resp_i.b.resp[1:0]"
