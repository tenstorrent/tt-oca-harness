// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU lifecycle functional coverage: smu_lc_disable_vector_cg and
// smu_lc_sigint_cg of SMU_FCOV.adoc, the lifecycle image and disable-vector
// pair class a sense presents, the posture of the four gated debug paths the
// owner walks, and each bit and rail of the exported LC_STATE pair failing
// closed under the bench inject.
//
// The image is lc_state_o at the rise of sep_fuse_sense_done_o after a cold
// reset, {~raw, raw} of the lifecycle state encodings
// (lifecycle_controller.adoc, sep_efuse_map.rdl LC_STATE). The pair class is
// lcc_feat_ctrl_o at the same edge, the undemoted profile word of the image
// (lifecycle_controller.adoc, "Per-LC-state Feature Control Profile"), for
// the five TEST_DEV classes and the PROD every-bit class. The other four PROD
// classes present the same lc_state_o and lcc_feat_ctrl_o on every port, so
// their class is the file name of the +sep_shadow_reg_preload plusarg, read
// once at time 0; a run without that plusarg, or with another file, samples
// no PROD class but every-bit.
//
// A path's posture is the one the profile word read at the done rise
// states for it (lifecycle_controller.adoc, "DTP path feature gates"),
// counted at the gate's fall only when the activity seen since the image
// sample agrees: a
// STAP open with a host TMS edge and its TDO enable high, shut with
// neither; the SMC fabric bridge open when its AR, AW and B counters all
// moved, shut when none moved; the secure DFT SIB open when its select was
// high, shut when it never was. A shut posture also needs a PTAP
// TMS edge in the window, so a window with no path activity and no PTAP
// activity counts no posture and no image. The image and pair class read at the rise are
// counted at the same fall, only when all four observed postures equal the
// ones the profile word states; under a word whose four postures are shut,
// a window with PTAP activity and no path activity counts the image and
// the four shut postures.
//
// The pair inject is counted at the fall of lc_sigint_inject_i[0] when
// lc_sigint_err_o rose under the inject and the pair the SMC receives had
// the two rails of the selected bit equal and every other bit legal. The
// hold is the number of clk_smu_i edges with the gate and the inject both
// high.
//
// One passive module on clk_smu_i. Every port is a signal of the bench top.
// clk_smu_i runs at 800 MHz or 100 MHz and clk_ref_i, the clock the owner's
// STAP monitor samples on, at 100 MHz, so every level the STAP and SIB taps
// hold for a clk_ref_i period reaches a clk_smu_i edge. Samples are taken
// only while the owning leaf holds tb_fcov_gate high, never while rst_cold_ni
// is low, and an image only after a cold reset has been seen low.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch; the plusarg decode is assigned once in an initial
// block.

`include "ocah_fcov_macros.svh"

module smu_lifecycle_fcov (
  input wire clk_smu_i,  // SMU fabric clock that samples every point.
  input wire rst_cold_ni,  // Cold reset, active low; every point is disabled while it is low.
  input wire fcov_gate_i,  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire [7:0] lc_state_i,  // Exported LC_STATE pair at the SMU boundary.
  input wire [63:0] lcc_feat_ctrl_i,  // Feature-control word, 1 = enabled.
  input wire sep_fuse_sense_done_i,  // SEP fuse-sense completion; its rise samples the image.
  input wire [31:0] dbg_ar_count_i,  // DTP-to-SMC debug AXI read address handshakes.
  input wire [31:0] dbg_aw_count_i,  // DTP-to-SMC debug AXI write address handshakes.
  input wire [31:0] dbg_b_count_i,  // DTP-to-SMC debug AXI write response handshakes.
  input wire ptap_tms_i,  // Primary TAP TMS pin of the bench.
  input wire stap_io_tms_i,  // I/O STAP host TMS as the DTP drives it.
  input wire stap_io_tdo_oen_i,  // I/O STAP host TDO output enable.
  input wire stap_sep_tms_i,  // SEP debug STAP host TMS as the DTP drives it.
  input wire stap_sep_tdo_oen_i,  // SEP debug STAP host TDO output enable from the DTP.
  input wire dft_secure_select_i,  // Secure DFT iJTAG SIB host select.
  input wire [3:0] lc_sigint_inject_i,  // Bench LC_STATE pair inject: arm, bit, rail.
  input wire [7:0] smc_lc_state_in_i,  // LC_STATE pair as the SMC eFuse wrapper receives it.
  input wire lc_sigint_err_i  // Lifecycle signal-integrity error at the SMU boundary.
);

  import smu_fcov_sep_csr_pkg::SEP_EFUSE_MAP_LC_DISABLE_SEP_DEBUG_SHIFT;
  import smu_fcov_sep_csr_pkg::SEP_EFUSE_MAP_LC_DISABLE_CHIPLET_DBG_SHIFT;
  import smu_fcov_sep_csr_pkg::SEP_EFUSE_MAP_LC_DISABLE_SIP_DEBUG_SHIFT;
  import smu_fcov_sep_csr_pkg::SEP_EFUSE_MAP_LC_DISABLE_FUNC_RESERVED_MASK;

  // lc_state_o after sensing, {~raw[3:0], raw[3:0]} (sep_efuse_map.adoc,
  // LC_STATE) of the raw encodings TEST_DEV 4'b0000 and PROD 4'b0001
  // (lifecycle_controller.adoc, SEP lifecycle state encodings).
  localparam logic [7:0] LcTestDev = 8'hF0;
  localparam logic [7:0] LcProd = 8'hE1;

  // LC_DISABLE bits the DTP path gates read and the Function group
  // (sep_efuse_map.rdl, LC_DISABLE; lifecycle_controller.adoc, "DTP access
  // cases").
  localparam int unsigned SepDbgBit = SEP_EFUSE_MAP_LC_DISABLE_SEP_DEBUG_SHIFT;
  localparam int unsigned ChipletDbgBit = SEP_EFUSE_MAP_LC_DISABLE_CHIPLET_DBG_SHIFT;
  localparam int unsigned SipDbgBit = SEP_EFUSE_MAP_LC_DISABLE_SIP_DEBUG_SHIFT;
  localparam logic [63:0] FeatProdFunc = SEP_EFUSE_MAP_LC_DISABLE_FUNC_RESERVED_MASK;

  // Profile words of the preload set (lifecycle_controller.adoc, "Per-LC-state
  // Feature Control Profile", SEC_DIS 0, no demotion): TEST_DEV gives
  // ~(SIP_DIS | SYS_DIS) on every bit, PROD the Function group only. The
  // SIP_DIS files set SEP_DBG and the SYS_DIS files CHIPLET_DBG.
  localparam logic [63:0] FeatAll = '1;
  localparam logic [63:0] FeatTdSip = ~(64'h1 << SepDbgBit);
  localparam logic [63:0] FeatTdSys = ~(64'h1 << ChipletDbgBit);
  localparam logic [63:0] FeatTdBoth = FeatTdSip & FeatTdSys;
  localparam logic [63:0] FeatNone = 64'h0;

  // Pair class: no bit, one SIP_DIS bit, one SYS_DIS bit, one in each, every
  // bit. NoCls lists no bin.
  localparam logic [2:0] ClsNone = 3'd0;
  localparam logic [2:0] ClsSip = 3'd1;
  localparam logic [2:0] ClsSys = 3'd2;
  localparam logic [2:0] ClsBoth = 3'd3;
  localparam logic [2:0] ClsAll = 3'd4;
  localparam logic [2:0] NoCls = 3'd7;

  // Walked paths, in the order of the cp_posture tuple.
  localparam logic [1:0] PathIoStap = 2'd0;
  localparam logic [1:0] PathSmcFabric = 2'd1;
  localparam logic [1:0] PathSepStap = 2'd2;
  localparam logic [1:0] PathSecureSib = 2'd3;

  // The hold the owner draws is 0 to 4095 clk_smu_i cycles.
  localparam logic [12:0] HoldSat = 13'd4096;
  localparam logic [12:0] HoldLongMin = 13'd2048;

  wire in_reset = (rst_cold_ni !== 1'b1);
  wire gate_on = (fcov_gate_i === 1'b1);

  // ------------------------------------------------------------------
  // The +sep_shadow_reg_preload file name, read once at time 0.
  // ------------------------------------------------------------------
  function automatic string base_name(input string path);
    for (int i = path.len() - 1; i >= 0; i--) begin
      if (path.getc(i) == "/") return path.substr(i + 1, path.len() - 1);
    end
    return path;
  endfunction

  // The PROD files whose pair no port tells apart.
  function automatic logic [2:0] prod_file_class(input string name);
    if (name == "sep_efuse_shadow_lc_prod.preload") return ClsNone;
    if (name == "sep_efuse_shadow_lc_prod_sip_dis_sep_dbg.preload") return ClsSip;
    if (name == "sep_efuse_shadow_lc_prod_sys_dis_chiplet_dbg.preload") return ClsSys;
    if (name == "sep_efuse_shadow_lc_prod_sip_dis_sep_dbg_sys_dis_chiplet_dbg.preload") begin
      return ClsBoth;
    end
    return NoCls;
  endfunction

  logic [2:0] prod_file_cls_q;
  initial begin : prod_file_decode
    string path;
    prod_file_cls_q = NoCls;
    if ($value$plusargs("sep_shadow_reg_preload=%s", path)) begin
      prod_file_cls_q = prod_file_class(base_name(path));
    end
  end

  // {image, class} of a sensed lc_state_o and lcc_feat_ctrl_o; NoCls when
  // the pair matches no row.
  function automatic logic [3:0] image_pair(input logic [7:0] lc, input logic [63:0] feat,
                                            input logic [2:0] prod_file_cls);
    if (lc == LcTestDev) begin
      if (feat == FeatAll) return {1'b0, ClsNone};
      if (feat == FeatTdSip) return {1'b0, ClsSip};
      if (feat == FeatTdSys) return {1'b0, ClsSys};
      if (feat == FeatTdBoth) return {1'b0, ClsBoth};
      if (feat == FeatNone) return {1'b0, ClsAll};
    end else if (lc == LcProd) begin
      if (feat == FeatNone) return {1'b1, ClsAll};
      if (feat == FeatProdFunc) return {1'b1, prod_file_cls};
    end
    return {1'b0, NoCls};
  endfunction

  // Path posture the profile word states: I/O STAP iff SIP_DBG, the SMC
  // fabric bridge iff SIP_DBG and CHIPLET_DBG, the SEP debug STAP and the
  // secure SIB iff SIP_DBG, CHIPLET_DBG and SEP_DBG.
  function automatic logic stated_open(input logic [63:0] feat, input logic [1:0] path);
    if (path == PathIoStap) return feat[SipDbgBit];
    if (path == PathSmcFabric) return feat[SipDbgBit] && feat[ChipletDbgBit];
    return feat[SipDbgBit] && feat[ChipletDbgBit] && feat[SepDbgBit];
  endfunction

  // ------------------------------------------------------------------
  // smu_lc_disable_vector_cg and smu_lc_sigint_cg (SMU_FCOV.adoc).
  // ------------------------------------------------------------------
  // cp_image_pair is {image, class}, image 0 TEST_DEV and 1 PROD, read at
  // the done rise and counted at the gate's fall when all four paths agree;
  // a posture sample hands it NoCls. cp_posture is {posture sample, path, open},
  // the posture the profile word read at the done rise states; an image
  // sample hands it posture sample 0.
  covergroup smu_lc_disable_vector_cg with function sample (
      logic img, logic [2:0] cls, logic pv, logic [1:0] path, logic open
  );
    option.per_instance = 1;
    cp_image_pair: coverpoint {
      img, cls
    } {
      bins test_dev_no_bit = {4'b0_000};
      bins test_dev_sip_dis = {4'b0_001};
      bins test_dev_sys_dis = {4'b0_010};
      bins test_dev_sip_sys_dis = {4'b0_011};
      bins test_dev_dis_all = {4'b0_100};
      bins prod_no_bit = {4'b1_000};
      bins prod_sip_dis = {4'b1_001};
      bins prod_sys_dis = {4'b1_010};
      bins prod_sip_sys_dis = {4'b1_011};
      bins prod_dis_all = {4'b1_100};
    }
    cp_posture: coverpoint {
      pv, path, open
    } {
      bins io_stap_shut = {4'b1_00_0};
      bins io_stap_open = {4'b1_00_1};
      bins smc_fabric_shut = {4'b1_01_0};
      bins smc_fabric_open = {4'b1_01_1};
      bins sep_stap_shut = {4'b1_10_0};
      bins sep_stap_open = {4'b1_10_1};
      bins dft_secure_sib_shut = {4'b1_11_0};
      bins dft_secure_sib_open = {4'b1_11_1};
    }
  endgroup

  // cp_bit_rail is {sample, LC_STATE bit, p rail}; cp_hold is the hold class,
  // 0, 1 to 2047 and 2048 to 4095 clk_smu_i cycles. A hold above 4095 is
  // class 3, which lists no bin.
  covergroup smu_lc_sigint_cg with function sample (
      logic bv, logic [1:0] lc_bit, logic p_rail, logic [1:0] hold_cls
  );
    option.per_instance = 1;
    cp_bit_rail: coverpoint {
      bv, lc_bit, p_rail
    } {
      bins bit0_n = {4'b1_00_0};
      bins bit0_p = {4'b1_00_1};
      bins bit1_n = {4'b1_01_0};
      bins bit1_p = {4'b1_01_1};
      bins bit2_n = {4'b1_10_0};
      bins bit2_p = {4'b1_10_1};
      bins bit3_n = {4'b1_11_0};
      bins bit3_p = {4'b1_11_1};
    }
    cp_hold: coverpoint hold_cls {
      bins zero = {2'd0}; bins short_1_2047 = {2'd1}; bins long_2048_4095 = {2'd2};
    }
  endgroup

  smu_lc_disable_vector_cg u_cg_lc_disable_vector = new();
  smu_lc_sigint_cg u_cg_lc_sigint = new();

  // ------------------------------------------------------------------
  // Image sample and the walk window it opens.
  // ------------------------------------------------------------------
  logic gate_q, done_q, cold_low_seen_q, window_q;
  logic img_q;
  logic [2:0] cls_q;
  logic [63:0] feat_q;
  logic ptap_tms_q, io_tms_q, sep_tms_q;
  logic ptap_moved_q, io_moved_q, io_oen_q, sep_moved_q, sep_oen_q;
  logic sib_sel_q;
  logic [31:0] ar0_q, aw0_q, b0_q;

  wire gate_fell = !gate_on && (gate_q === 1'b1);
  wire done_rose = (sep_fuse_sense_done_i === 1'b1) && (done_q === 1'b0);
  wire sense_known = !$isunknown({lc_state_i, lcc_feat_ctrl_i});
  wire [3:0] image_cell = image_pair(lc_state_i, lcc_feat_ctrl_i, prod_file_cls_q);
  wire image_e = gate_on && cold_low_seen_q && done_rose && sense_known
      && (image_cell[2:0] != NoCls);
  wire in_window = gate_on && window_q;
  wire ptap_moved = (ptap_tms_i ^ ptap_tms_q) === 1'b1;
  wire io_moved = (stap_io_tms_i ^ io_tms_q) === 1'b1;
  wire sep_moved = (stap_sep_tms_i ^ sep_tms_q) === 1'b1;

  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      gate_q <= 1'b0;
      done_q <= 1'b1;
      cold_low_seen_q <= 1'b1;
      window_q <= 1'b0;
      img_q <= 1'b0;
      cls_q <= NoCls;
      feat_q <= '0;
      ptap_tms_q <= 1'b0;
      io_tms_q <= 1'b0;
      sep_tms_q <= 1'b0;
      ptap_moved_q <= 1'b0;
      io_moved_q <= 1'b0;
      io_oen_q <= 1'b0;
      sep_moved_q <= 1'b0;
      sep_oen_q <= 1'b0;
      sib_sel_q <= 1'b0;
      ar0_q <= '0;
      aw0_q <= '0;
      b0_q <= '0;
    end else begin
      gate_q <= gate_on;
      done_q <= sep_fuse_sense_done_i;
      ptap_tms_q <= ptap_tms_i;
      io_tms_q <= stap_io_tms_i;
      sep_tms_q <= stap_sep_tms_i;
      if (image_e) begin
        window_q <= 1'b1;
        img_q <= image_cell[3];
        cls_q <= image_cell[2:0];
        feat_q <= lcc_feat_ctrl_i;
        ptap_moved_q <= 1'b0;
        io_moved_q <= 1'b0;
        io_oen_q <= 1'b0;
        sep_moved_q <= 1'b0;
        sep_oen_q <= 1'b0;
        sib_sel_q <= 1'b0;
        ar0_q <= dbg_ar_count_i;
        aw0_q <= dbg_aw_count_i;
        b0_q <= dbg_b_count_i;
      end else if (gate_fell) begin
        window_q <= 1'b0;
      end else if (in_window) begin
        if (ptap_moved) ptap_moved_q <= 1'b1;
        if (io_moved) io_moved_q <= 1'b1;
        if (stap_io_tdo_oen_i === 1'b1) io_oen_q <= 1'b1;
        if (sep_moved) sep_moved_q <= 1'b1;
        if (stap_sep_tdo_oen_i === 1'b1) sep_oen_q <= 1'b1;
        if (dft_secure_select_i === 1'b1) sib_sel_q <= 1'b1;
      end
    end
  end

  // Observed posture of each path over the window: 2'b01 shut, 2'b11 open,
  // 2'b00 neither.
  wire fab_known = !$isunknown({dbg_ar_count_i, dbg_aw_count_i, dbg_b_count_i});
  wire fab_open = fab_known && (dbg_ar_count_i != ar0_q) && (dbg_aw_count_i != aw0_q)
      && (dbg_b_count_i != b0_q);
  wire fab_shut = fab_known && (dbg_ar_count_i == ar0_q) && (dbg_aw_count_i == aw0_q)
      && (dbg_b_count_i == b0_q);
  wire [1:0] obs_io = (io_moved_q && io_oen_q) ? 2'b11
      : (!io_moved_q && !io_oen_q && ptap_moved_q) ? 2'b01 : 2'b00;
  wire [1:0] obs_fabric = fab_open ? 2'b11 : (fab_shut && ptap_moved_q) ? 2'b01 : 2'b00;
  wire [1:0] obs_sep = (sep_moved_q && sep_oen_q) ? 2'b11
      : (!sep_moved_q && !sep_oen_q && ptap_moved_q) ? 2'b01 : 2'b00;
  wire [1:0] obs_sib = sib_sel_q ? 2'b11 : ptap_moved_q ? 2'b01 : 2'b00;
  wire posture_e = gate_fell && window_q;

  // A path agrees when its posture is observed and is the one the profile
  // word read at the done rise states.
  wire io_agrees = obs_io[0] && (obs_io[1] == stated_open(feat_q, PathIoStap));
  wire fab_agrees = obs_fabric[0]
      && (obs_fabric[1] == stated_open(feat_q, PathSmcFabric));
  wire sep_agrees = obs_sep[0] && (obs_sep[1] == stated_open(feat_q, PathSepStap));
  wire sib_agrees = obs_sib[0] && (obs_sib[1] == stated_open(feat_q, PathSecureSib));
  wire walk_agrees = io_agrees && fab_agrees && sep_agrees && sib_agrees;

  task automatic sample_posture(input logic [1:0] path, input logic agrees, input logic open);
    if (agrees) u_cg_lc_disable_vector.sample(1'b0, NoCls, 1'b1, path, open);
  endtask

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset) begin
      if (posture_e) begin
        if (walk_agrees) u_cg_lc_disable_vector.sample(img_q, cls_q, 1'b0, 2'd0, 1'b0);
        sample_posture(PathIoStap, io_agrees, obs_io[1]);
        sample_posture(PathSmcFabric, fab_agrees, obs_fabric[1]);
        sample_posture(PathSepStap, sep_agrees, obs_sep[1]);
        sample_posture(PathSecureSib, sib_agrees, obs_sib[1]);
      end
    end
  end

  // ------------------------------------------------------------------
  // LC_STATE pair inject: the bit and rail, the error, the broken pair and
  // the hold, from the rise of lc_sigint_inject_i[0] to its fall.
  // ------------------------------------------------------------------
  // The selected bit's two rails are equal and every other bit's differ.
  function automatic logic one_broken_bit(input logic [7:0] pair, input logic [1:0] b);
    logic [3:0] equal;
    equal = ~(pair[7:4] ^ pair[3:0]);
    return !$isunknown(pair) && (equal == 4'(1 << b));
  endfunction

  function automatic logic [1:0] hold_class(input logic [12:0] hold);
    if (hold == '0) return 2'd0;
    if (hold < HoldLongMin) return 2'd1;
    if (hold < HoldSat) return 2'd2;
    return 2'd3;
  endfunction

  logic inj_q, err_seen_q, broken_q, inj_p_q;
  logic [1:0] inj_bit_q;
  logic [12:0] hold_cnt_q;

  wire inj_on = (lc_sigint_inject_i[0] === 1'b1);
  wire inj_rose = inj_on && !inj_q;
  wire inj_fell = (lc_sigint_inject_i[0] === 1'b0) && inj_q;
  wire err_on = (lc_sigint_err_i === 1'b1);
  wire broken_on = one_broken_bit(smc_lc_state_in_i, lc_sigint_inject_i[2:1]);
  wire hold_edge = gate_on && inj_on;

  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      inj_q <= 1'b0;
      err_seen_q <= 1'b0;
      broken_q <= 1'b0;
      inj_p_q <= 1'b0;
      inj_bit_q <= '0;
      hold_cnt_q <= '0;
    end else begin
      inj_q <= inj_on;
      if (inj_rose) begin
        inj_bit_q <= lc_sigint_inject_i[2:1];
        inj_p_q <= lc_sigint_inject_i[3];
        err_seen_q <= err_on;
        broken_q <= broken_on;
        hold_cnt_q <= {12'd0, hold_edge};
      end else if (inj_on) begin
        inj_bit_q <= lc_sigint_inject_i[2:1];
        inj_p_q <= lc_sigint_inject_i[3];
        if (err_on) err_seen_q <= 1'b1;
        if (broken_on) broken_q <= 1'b1;
        if (hold_edge && (hold_cnt_q != HoldSat)) hold_cnt_q <= hold_cnt_q + 13'd1;
      end
    end
  end

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset && gate_on && inj_fell && err_seen_q && broken_q) begin
      u_cg_lc_sigint.sample(1'b1, inj_bit_q, inj_p_q, hold_class(hold_cnt_q));
    end
  end

endmodule : smu_lifecycle_fcov
