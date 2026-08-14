// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Efuse Shadow Regs
//
//-----------------------------------------------------------------------------

`include "prim_assert.sv"

module efuse_shadow_regs
#(
    parameter int unsigned FUSE_MAP_REG_MAP_BASE_ADDR = 32'h0,

    parameter int unsigned SHADOW_REG_BITS = 24576,
    parameter int unsigned SHADOW_REG_BYTES = SHADOW_REG_BITS / 8,
    parameter int unsigned SHADOW_REG_WORD_WIDTH = 32,
    parameter int unsigned EFUSE_FIELDS = 1,
    parameter int unsigned REG_ADDR_WIDTH = 12,

    parameter bit HAS_LC_STATE = 1'b0,
    parameter efuse_pkg::shadow_word_range_map_t CLASS1_SHADOW_RANGES = '0,
    // Class 1a device secrets, masked on the hardware output under secure_tm.
    parameter efuse_pkg::shadow_word_range_map_t SECRET_SHADOW_RANGES = '0,

    parameter logic [5:0] TOKEN_MATCH_CODE = 6'b010101,

    parameter type addr_t = logic,
    parameter type data_t = logic,
    parameter type efuse_apb_req_t  = logic,
    parameter type efuse_apb_resp_t = logic,

    parameter type efuse_addr_t = logic,
    parameter type efuse_data_t = logic,
    parameter type efuse_word_counter_t = logic,
    parameter type fuse_command_req_t = logic,
    parameter type fuse_command_resp_t = logic,

    parameter type efuse_map_t = logic,

    parameter int unsigned LC_STATE_WIDTH = 4,

    localparam int unsigned NumShadowWords = SHADOW_REG_BITS / SHADOW_REG_WORD_WIDTH,
    localparam int unsigned ShadowEfuseWidth = $clog2(NumShadowWords)
) (

    input  logic                                clk_i,
    input  logic                                rst_ni,
    input  logic                                test_en_i,
    input  logic                                security_disable_i,
    input  logic                                secure_tm_i,

    input  efuse_pkg::rule_t [EFUSE_FIELDS-1:0] efuse_field_map_i,

    // APB Register Interface
    input  logic [REG_ADDR_WIDTH-1:0]           apb_req_paddr_i,
    input  logic [2:0]                          apb_req_pprot_i,
    input  logic                                apb_req_psel_i,
    input  logic                                apb_req_penable_i,
    input  logic                                apb_req_pwrite_i,
    input  logic [31:0]                         apb_req_pwdata_i,
    input  logic [3:0]                          apb_req_pstrb_i,

    output efuse_apb_resp_t                     apb_resp_o,

    output logic                                fuse_sense_done_o,
    output efuse_map_t                          shadow_efuse_o,
    input  logic [5:0]                          rma_chiplet_token_match_i,
    input  logic [5:0]                          rma_sip_token_match_i,

    // PROD_DBG isolation: when asserted with LC_STATE==PROD, block all transitions
    input  logic                                prod_dbg_active_i,

    // Fuse Command Interface - custom interface for SHIM state machine
    output fuse_command_req_t                   fuse_command_req,  // {address, write data, access length, command, valid}
    input  fuse_command_resp_t                  fuse_command_resp, // {read data, command status, valid}

    // Debug ports
    output logic                                is_write_locked_o,
    output logic                                is_write_setup_only_o,
    output logic                                is_lc_state_access_o,
    output logic                                is_read_locked_o,

    // Locked Field Access Interrupt
    output logic                                locked_field_access_interrupt_o
);

  localparam fuse_command_req_t FUSE_COMMAND_REQ_DEFAULT = '0;
  localparam fuse_command_resp_t FUSE_COMMAND_RESP_DEFAULT = '0;

  // Keep Class 1 shadow words in a separately named storage array so the
  // synthesis scan-exclusion flow can identify only those flops. The regular
  // shadow array contains the remaining Class 3 fuse-map words.
  // A packed array cannot have zero elements. The one-word SMC fallback is
  // never read or written and is removed during elaboration/synthesis.
  localparam int unsigned ActualNumClass1ShadowWords =
      efuse_pkg::shadow_range_map_word_count(CLASS1_SHADOW_RANGES);
  localparam int unsigned NumClass1ShadowWords =
      (ActualNumClass1ShadowWords > 0) &&
      (ActualNumClass1ShadowWords <= NumShadowWords) ? ActualNumClass1ShadowWords : 1;
  localparam int unsigned NumNormalShadowWords =
      ActualNumClass1ShadowWords < NumShadowWords ?
      NumShadowWords - ActualNumClass1ShadowWords : 1;

  logic [NumNormalShadowWords-1:0][SHADOW_REG_WORD_WIDTH-1:0] shadow_efuse_values;
  logic [NumClass1ShadowWords-1:0][SHADOW_REG_WORD_WIDTH-1:0] shadow_efuse_values_n0_scan;
  efuse_map_t shadow_efuse;
  efuse_map_t shadow_efuse_masked;

  // Reconstruct the public union view from the two storage arrays. Only the
  // selected Class 1 words come from the *_n0_scan array.
  always_comb begin
    for (int i = 0; i < NumShadowWords; i++) begin
      if (efuse_pkg::shadow_range_map_contains_word(CLASS1_SHADOW_RANGES, i)) begin
        shadow_efuse.values[i] =
            shadow_efuse_values_n0_scan[
                efuse_pkg::class1_shadow_storage_idx(CLASS1_SHADOW_RANGES, i)];
      end else begin
        shadow_efuse.values[i] =
            shadow_efuse_values[
                efuse_pkg::normal_shadow_storage_idx(CLASS1_SHADOW_RANGES, i)];
      end
    end
  end

  // The hardware output to the rest of the design observes the masked view, so no
  // Class 1a secret reaches a downstream consumer in secure test. Register reads
  // keep using the unmasked view and stay governed by the normal access controls.
  // Write merges, lock checks and LC state logic also use the unmasked view so a
  // write under secure_tm cannot clear stored bits.
  always_comb begin
    shadow_efuse_masked = shadow_efuse;
    if (secure_tm_i) begin
      for (int i = 0; i < NumShadowWords; i++) begin
        if (efuse_pkg::shadow_range_map_contains_word(SECRET_SHADOW_RANGES, i)) begin
          shadow_efuse_masked.values[i] = '0;
        end
      end
    end
  end

  logic chiplet_state_change_completed_n0_scan;
  logic sop_state_change_completed_n0_scan;

  logic [LC_STATE_WIDTH-1:0] lc_state_raw_d;
  logic [2*LC_STATE_WIDTH-1:0] lc_state_diff_d;

  logic sim_skip_fuse_sense;
  reg [31:0] shadow_reg_preload [0:NumShadowWords-1];

`ifdef SIM
  initial begin
    sim_skip_fuse_sense = 1'b0;

    if ($test$plusargs("skip_fuse_sense")) begin
      $display("[INFO] Skipping fuse sense");
      sim_skip_fuse_sense = 1'b1;
    end else begin
      $display("[INFO] Not skipping fuse sense - cannot find +skip_fuse_sense plusarg");
      sim_skip_fuse_sense = 1'b0;
    end
  end
`else
  assign sim_skip_fuse_sense = 1'b0;
`endif
`ifdef SIM
  initial begin
    string sep_shadow_reg_preload;
    string smc_shadow_reg_preload;
    logic preload_plusarg_found;
    preload_plusarg_found = 1'b0;

     // preload shadow reg after a 10 time unit delay, can not wait until reset.
     if (HAS_LC_STATE) begin
          // Only load shadow reg preload when skip_fuse_sense is enabled.
          // This prevents a "default" preload path from affecting normal fuse-sense operation.
          if ($test$plusargs("skip_fuse_sense") &&
              $value$plusargs("sep_shadow_reg_preload=%s", sep_shadow_reg_preload)) begin
            $display("Loading SEP shadow reg preload data from %s", sep_shadow_reg_preload);
            $readmemh(sep_shadow_reg_preload, shadow_reg_preload, 0, NumShadowWords-1);
            preload_plusarg_found = 1'b1;
          end
     end else begin
          // Only load shadow reg preload if skip fuse sense is enabled
          if (sim_skip_fuse_sense == 1'b1 && $value$plusargs("smc_shadow_reg_preload=%s", smc_shadow_reg_preload)) begin
            $display("Loading SMC shadow reg preload data from %s", smc_shadow_reg_preload);
            $readmemh(smc_shadow_reg_preload, shadow_reg_preload, 0, NumShadowWords-1);
            preload_plusarg_found = 1'b1;
          end
    end
    if (sim_skip_fuse_sense == 1'b1 && preload_plusarg_found == 1'b0) begin
        // Construct the expected plusarg name string based on HAS_LC_STATE for the warning
        string expected_plusarg_name = HAS_LC_STATE ? "sep_shadow_reg_preload" : "smc_shadow_reg_preload";
        $display("[INFO] +skip_fuse_sense provided, but the required shadow register preload plusarg (+%s=filename) was NOT found.", expected_plusarg_name);

        $display("[INFO] Initializing shadow_reg_preload array to default pattern (32'h00000000) due to missing preload file.");
        for (int i = 0; i < NumShadowWords; i++) begin : preload_not_found
        if (HAS_LC_STATE && (i == efuse_pkg::SHADOW_IDX_LC_STATE)) begin : reset_lc_state
          shadow_reg_preload[i] = {{(32-2*LC_STATE_WIDTH){1'b0}}, {LC_STATE_WIDTH{1'b0}}, {LC_STATE_WIDTH{1'b1}}};
        end else begin : smc_case
          shadow_reg_preload[i] = 32'h0;
        end
        end

    end
  end
`endif

  logic fuse_sense_done;
  logic write_locked;
  logic write_setup_only;
  logic is_lc_state_access;
  logic read_locked;

  efuse_apb_req_t   apb_req_from_ac;
  efuse_apb_resp_t  apb_resp_from_ac;

  efuse_shadow_reg_access_control #(
      .EFUSE_ADDR_WIDTH(REG_ADDR_WIDTH),
      .EFUSE_FIELDS(EFUSE_FIELDS),
      .HAS_LC_STATE(HAS_LC_STATE),
      .efuse_map_t(efuse_map_t),

      .efuse_apb_req_t(efuse_apb_req_t),
      .efuse_apb_resp_t(efuse_apb_resp_t),

      .efuse_addr_t(efuse_addr_t),
      .efuse_data_t(efuse_data_t)
  ) efuse_shadow_reg_access_control (
      .clk_i(clk_i),
      .rst_ni(rst_ni),

      .secure_tm_i(secure_tm_i),

      .efuse_field_map_i(efuse_field_map_i),

      .apb_req_paddr_i         (apb_req_paddr_i),
      .apb_req_pprot_i         (apb_req_pprot_i),
      .apb_req_psel_i          (apb_req_psel_i),
      .apb_req_penable_i       (apb_req_penable_i),
      .apb_req_pwrite_i        (apb_req_pwrite_i),
      .apb_req_pwdata_i        (apb_req_pwdata_i),
      .apb_req_pstrb_i         (apb_req_pstrb_i),

      .apb_resp_o(apb_resp_o),

      .apb_req_from_ac_o(apb_req_from_ac),
      .apb_resp_from_ac_i(apb_resp_from_ac),

      .write_locked_o(write_locked),
      .write_setup_only_o(write_setup_only),
      .lc_state_access_o(is_lc_state_access),
      .read_locked_o(read_locked),

      .shadow_regs_i(shadow_efuse),

      .locked_field_access_interrupt_o(locked_field_access_interrupt_o)
  );

  efuse_word_counter_t current_word_num_q, current_word_num_d;
  efuse_word_counter_t words_received_q, words_received_d;
  fuse_command_req_t fuse_command_req_d;

  logic [LC_STATE_WIDTH-1:0] lc_state_cur;
  logic                      lc_state_is_prod;
  logic                      lc_state_is_prod_dbg;
  logic [LC_STATE_WIDTH-1:0] lc_state_candidate;
  logic [LC_STATE_WIDTH-1:0] lc_state_intended_dest;
  logic                      lc_state_write_allowed;

  // Combinationally compute the next raw LC_STATE value for each write path,
  // then feed it through the differential encoder so the always_ff can store
  // the full encoded value atomically.
  always_comb begin
      lc_state_raw_d = '0;
      lc_state_candidate = '0;
      lc_state_intended_dest = '0;
      lc_state_write_allowed = 1'b0;
      lc_state_cur = '0;
      lc_state_is_prod = 1'b0;
      lc_state_is_prod_dbg = 1'b0;
      if (HAS_LC_STATE) begin
          lc_state_raw_d = shadow_efuse.values[efuse_pkg::SHADOW_IDX_LC_STATE][LC_STATE_WIDTH-1:0];
          lc_state_candidate = shadow_efuse.values[efuse_pkg::SHADOW_IDX_LC_STATE][LC_STATE_WIDTH-1:0];
          if (sim_skip_fuse_sense && !fuse_sense_done) begin
              lc_state_raw_d = shadow_reg_preload[efuse_pkg::SHADOW_IDX_LC_STATE][LC_STATE_WIDTH-1:0];
          end else if (!fuse_sense_done && !security_disable_i) begin
              if (fuse_command_resp.valid && !fuse_command_resp.status &&
                  words_received_q < efuse_word_counter_t'(NumShadowWords) &&
                  words_received_q == efuse_word_counter_t'(efuse_pkg::SHADOW_IDX_LC_STATE)) begin
                  lc_state_raw_d = fuse_command_resp.data[LC_STATE_WIDTH-1:0];
              end else begin
                  // Keep default: lc_state_raw_d already set at line 225
              end
          end else begin
              // LC state transition enforcement:
              //   PROD_END, RMA_CHIPLET, and PROD_DBG are terminal — no W1S updates.
              //   From PROD, bit[2] and bit[3] are blocked (per-bit gating).
              //   bit[2] (RMA_CHIPLET) requires bit[1] (RMA_SIP) already established.
              lc_state_cur     = shadow_efuse.values[efuse_pkg::SHADOW_IDX_LC_STATE][LC_STATE_WIDTH-1:0];
              lc_state_is_prod = (lc_state_cur == efuse_pkg::LC_PROD);
              lc_state_is_prod_dbg = prod_dbg_active_i && lc_state_is_prod;

              if (lc_state_cur inside {efuse_pkg::LC_PROD_END,
                                       efuse_pkg::LC_RMA_CHIP_0,
                                       efuse_pkg::LC_RMA_CHIP_1}
                  || lc_state_is_prod_dbg) begin
                  lc_state_raw_d = lc_state_cur;
              end else if (apb_req_from_ac.psel) begin
                  if (apb_req_from_ac.pwrite && !write_locked &&
                      write_setup_only && is_lc_state_access && apb_req_from_ac.pstrb[0]) begin
                      // Pre-check: validate W1S intended destination atomically
                      // before applying per-bit token gating.
                      lc_state_intended_dest = lc_state_cur |
                          apb_req_from_ac.pwdata[LC_STATE_WIDTH-1:0];
                      lc_state_write_allowed =
                          efuse_pkg::is_valid_lc_state(lc_state_intended_dest);

                      if (lc_state_write_allowed) begin
                          lc_state_candidate[0] = apb_req_from_ac.pwdata[0] |
                                              shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][0];
                          lc_state_candidate[1] = (rma_sip_token_match_i == TOKEN_MATCH_CODE)
                              ? (apb_req_from_ac.pwdata[1] | shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][1])
                              : shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][1];
                          lc_state_candidate[2] = (lc_state_is_prod || !lc_state_cur[1])
                              ? shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][2]
                              : (rma_chiplet_token_match_i == TOKEN_MATCH_CODE)
                                  ? (apb_req_from_ac.pwdata[2] | shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][2])
                                  : shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][2];
                          lc_state_candidate[3] = lc_state_is_prod
                              ? shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][3]
                              : (apb_req_from_ac.pwdata[3] |
                                 shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][3]);
                          lc_state_raw_d = efuse_pkg::is_valid_lc_state(lc_state_candidate)
                              ? lc_state_candidate : lc_state_cur;
                      end
                  end
              end else if (shadow_efuse.values[efuse_pkg::SHADOW_IDX_TRANSIENT_RMA_EN][0] == 1'b1) begin
                  // Transient RMA: block CHIPLET token set unless RMA_SIP (bit[1]) already established
                  if (rma_chiplet_token_match_i == TOKEN_MATCH_CODE && !lc_state_is_prod && lc_state_cur[1]) begin
                      lc_state_raw_d[2] = 1'b1;
                  end else if (rma_chiplet_token_match_i == TOKEN_MATCH_CODE) begin
                      // CHIPLET matched but guard failed — block, don't fall through
                  end else if (rma_sip_token_match_i == TOKEN_MATCH_CODE) begin
                      lc_state_raw_d[1] = 1'b1;
                  end
                  // Reject if transient update would produce an invalid state (e.g. 0x0 -> 0x4).
                  if (!efuse_pkg::is_valid_lc_state(lc_state_raw_d)) begin
                      lc_state_raw_d = lc_state_cur;
                  end
              end
          end
      end
  end

  prim_diff_encode_multi #(.Width(LC_STATE_WIDTH)) u_lc_state_enc (
      .clk_i,
      .rst_ni,
      .data_i (lc_state_raw_d),
      .data_o (lc_state_diff_d)
  );

  // Read execution state machine
  typedef enum {
    StIdle, StRead, StWait, StFinished
  } efuse_sense_state_e;

  efuse_sense_state_e efuse_sense_state_d, efuse_sense_state_q;

    // Combinational decode of the state
    always_comb begin
        efuse_sense_state_d = efuse_sense_state_q;
        words_received_d = words_received_q;
        current_word_num_d = current_word_num_q;
        fuse_command_req_d = fuse_command_req;

        unique case (efuse_sense_state_q)
            StIdle: begin
                // Fuse sensing begins when reset is deasserted
                if (rst_ni) begin
                    efuse_sense_state_d = StRead;
                    words_received_d = '0;
                    current_word_num_d = '0;
                end
            end

            // StRead: Send the fuse command to read entire OTP
            StRead: begin
                // width-match the 9b word counter to the 13b bit-address field (clears W164b lint).
                // NOTE: value is 0 here; .address is a BIT address, so a nonzero word count would be wrong (see commit note re: word-vs-bit).
                fuse_command_req_d.address = efuse_addr_t'(current_word_num_q);
                fuse_command_req_d.access_length_words = NumShadowWords;
                fuse_command_req_d.valid = 1'b1;
                fuse_command_req_d.command = efuse_pkg::FUSE_COMMAND_READ;

                // Move to wait acknowledgment state
                efuse_sense_state_d = StWait;
                words_received_d = '0;
            end

            // StWait: Wait for remaining streaming responses and store data
            StWait: begin

                if (fuse_command_resp.valid) begin
                    // Check if we've received all expected words
                    if (words_received_q >= NumShadowWords - efuse_word_counter_t'(1)) begin
                        efuse_sense_state_d = StFinished;
                    end else begin
                        words_received_d = words_received_q + efuse_word_counter_t'(1);
                        current_word_num_d = current_word_num_q + efuse_word_counter_t'(1);
                    end
                    // Stay in wait state to receive more data
                end

                // Continue waiting for more responses
            end

            // StFinished: OTP sensing complete
            StFinished: begin
                // Stay in finished state
                efuse_sense_state_d = StFinished;
            end

            // Default case to catch parasitic states
            default: begin
                efuse_sense_state_d = fuse_sense_done ? StFinished : StIdle;
            end
        endcase
    end

    // Register the state
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            efuse_sense_state_q <= StIdle;
            current_word_num_q <= '0;
            words_received_q <= efuse_word_counter_t'(0);
            fuse_command_req <= FUSE_COMMAND_REQ_DEFAULT;

        end else begin
            efuse_sense_state_q <= efuse_sense_state_d;
            current_word_num_q <= current_word_num_d;
            words_received_q <= words_received_d;
            fuse_command_req <= fuse_command_req_d;
        end
    end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      fuse_sense_done <= 1'b0;
    end else if (sim_skip_fuse_sense) begin
      fuse_sense_done <= 1'b1;
    end else if ((efuse_sense_state_q == StFinished) && !fuse_sense_done) begin
      fuse_sense_done <= 1'b1;
`ifndef SIMULATION
      $display("[INFO] Fuse sense done");
`endif
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      for (int i = 0; i < NumShadowWords; i++) begin : reset_shadow_registers
        if (efuse_pkg::shadow_range_map_contains_word(
            CLASS1_SHADOW_RANGES, i)) begin : reset_class1_shadow_registers
          if (HAS_LC_STATE &&
              (i == efuse_pkg::SHADOW_IDX_LC_STATE)) begin : reset_lc_state
            shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                CLASS1_SHADOW_RANGES, i)] <=
                efuse_data_t'({{LC_STATE_WIDTH{1'b0}}, {LC_STATE_WIDTH{1'b1}}});
          end else begin : reset_class1_shadow_reg
            shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                CLASS1_SHADOW_RANGES, i)] <= efuse_data_t'(0);
          end
        end else begin : reset_shadow_reg
          shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
              CLASS1_SHADOW_RANGES, i)] <= efuse_data_t'(0);
        end
      end

      apb_resp_from_ac.pready <= 1'b0;
      apb_resp_from_ac.pslverr <= 1'b0;
      apb_resp_from_ac.prdata <= efuse_data_t'(0);
      chiplet_state_change_completed_n0_scan <= 1'b0;
      sop_state_change_completed_n0_scan <= 1'b0;

    end else begin
      /////////////////////////////////////////
      // preload shadow registers - simulating
      /////////////////////////////////////////
      if ((sim_skip_fuse_sense) && (!fuse_sense_done))begin : preload_shadow_regs
        for (int i = 0; i < NumShadowWords; i++) begin : preload_shadow_registers
          if (efuse_pkg::shadow_range_map_contains_word(CLASS1_SHADOW_RANGES, i)) begin
            if (HAS_LC_STATE && (i == efuse_pkg::SHADOW_IDX_LC_STATE)) begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES, i)] <=
                  {shadow_reg_preload[i][31:2*LC_STATE_WIDTH], lc_state_diff_d};
            end else begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES, i)] <= shadow_reg_preload[i];
            end
          end else begin
            shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
                CLASS1_SHADOW_RANGES, i)] <=
                shadow_reg_preload[i];
          end
        end
        // If there is a request to the shadow registers before fuse sense is done, return bad cable
        if (apb_req_from_ac.psel) begin
          apb_resp_from_ac.pslverr <= 1'b1;
          apb_resp_from_ac.pready  <= 1'b1;
          apb_resp_from_ac.prdata  <= efuse_data_t'('hbadcab1e);
        end
      end
      //////////////////////////////////////////////////////////////////////////////////
      // load shadow registers from streaming fuse command responses - regular operation
      //////////////////////////////////////////////////////////////////////////////////
      else if ((!fuse_sense_done)&&(!security_disable_i)) begin : load_shadow_regs
        if (fuse_command_resp.valid && (fuse_command_resp.status == 1'b0)) begin
          // Store the data at the current word index (before incrementing words_received)
          if (words_received_q < NumShadowWords) begin
            if (HAS_LC_STATE &&
                words_received_q ==
                    efuse_word_counter_t'(efuse_pkg::SHADOW_IDX_LC_STATE)) begin
              // ShadowEfuseWidth' cast narrows the 9b word-count to the 8b array index, conventional in this module (not entirely necessary as guarded < NumShadowWords above)
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES, ShadowEfuseWidth'(words_received_q))] <=
                  {fuse_command_resp.data[31:2*LC_STATE_WIDTH], lc_state_diff_d};
            end else begin
              if (efuse_pkg::shadow_range_map_contains_word(
                  CLASS1_SHADOW_RANGES, ShadowEfuseWidth'(words_received_q))) begin
                shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                    CLASS1_SHADOW_RANGES, ShadowEfuseWidth'(words_received_q))] <=
                    fuse_command_resp.data;
              end else begin
                shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
                    CLASS1_SHADOW_RANGES, ShadowEfuseWidth'(words_received_q))] <=
                    fuse_command_resp.data;
              end
            end
          end
        end

        // return error if a request to the shadow registers occur when sense is not complete
        if (apb_req_from_ac.psel) begin
          apb_resp_from_ac.pslverr <= 1'b1;
          apb_resp_from_ac.pready  <= 1'b1;
          apb_resp_from_ac.prdata  <= efuse_data_t'('hbadcab1e);
        end
      end

      //////////////////////////////////////////////////////////////////////////////////
      // apb access and transient rma en - regular operation
      //////////////////////////////////////////////////////////////////////////////////
      else begin : apb_access_and_transient_rma_en
        if (apb_req_from_ac.psel) begin
          // if address is out of range, return bad cable
          if (apb_req_from_ac.paddr > (SHADOW_REG_BYTES - efuse_addr_t'(4))) begin
            apb_resp_from_ac.pslverr <= 1'b1;
            apb_resp_from_ac.pready  <= 1'b1;
            apb_resp_from_ac.prdata  <= efuse_data_t'('hbadcab1e);
          end
          // else if it is a write -> we check if write locked or write_setup_only
          else if ((apb_req_from_ac.pwrite) && !(write_locked)) begin
            // setup only and NOT LC_STATE access
            if ((write_setup_only) && !(is_lc_state_access)) begin
              if (efuse_pkg::shadow_range_map_contains_word(
                  CLASS1_SHADOW_RANGES,
                  (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))) begin
                for (int b = 0; b < 4; b++) begin
                  if (apb_req_from_ac.pstrb[b] && !apb_resp_from_ac.pready) begin
                    shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                        CLASS1_SHADOW_RANGES,
                        (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))][b*8+:8] <=
                        apb_req_from_ac.pwdata[b*8+:8] |
                        shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][b*8+:8];
                  end
                end
              end else begin
                for (int b = 0; b < 4; b++) begin
                  if (apb_req_from_ac.pstrb[b] && !apb_resp_from_ac.pready) begin
                    shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
                        CLASS1_SHADOW_RANGES,
                        (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))][b*8+:8] <=
                        apb_req_from_ac.pwdata[b*8+:8] |
                        shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)][b*8+:8];
                  end
                end
              end
            // setup only and LC_STATE access
            // LC_STATE is the first nibble of the shadow register
            end else if ((write_setup_only) && (is_lc_state_access)) begin
              // LC_STATE byte 0: use the differentially encoded value from the encoder,
              // which applies set-only and token-gated logic on the raw [3:0] and produces
              // the complement in [7:4] via synthesis-protected anchor buffers.
              if (apb_req_from_ac.pstrb[0] && !apb_resp_from_ac.pready) begin
                if (efuse_pkg::shadow_range_map_contains_word(
                    CLASS1_SHADOW_RANGES,
                    (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))) begin
                  shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                      CLASS1_SHADOW_RANGES,
                      (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))
                  ][2*LC_STATE_WIDTH-1:0] <=
                      lc_state_diff_d;
                end else begin
                  shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
                      CLASS1_SHADOW_RANGES,
                      (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))
                  ][2*LC_STATE_WIDTH-1:0] <=
                      lc_state_diff_d;
                end
              end
              // Upper bytes: writable as before
              if (efuse_pkg::shadow_range_map_contains_word(
                  CLASS1_SHADOW_RANGES,
                  (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))) begin
                for (int b = 1; b < 4; b++) begin
                  if (apb_req_from_ac.pstrb[b] && !apb_resp_from_ac.pready) begin
                    shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                        CLASS1_SHADOW_RANGES,
                        (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))][b*8+:8] <=
                        apb_req_from_ac.pwdata[b*8+:8];
                  end
                end
              end else begin
                for (int b = 1; b < 4; b++) begin
                  if (apb_req_from_ac.pstrb[b] && !apb_resp_from_ac.pready) begin
                    shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
                        CLASS1_SHADOW_RANGES,
                        (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))][b*8+:8] <=
                        apb_req_from_ac.pwdata[b*8+:8];
                  end
                end
              end
            end else begin  // not setup only and NOT write locked, so it is writable
              if (efuse_pkg::shadow_range_map_contains_word(
                  CLASS1_SHADOW_RANGES,
                  (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))) begin
                for (int b = 0; b < 4; b++) begin
                  if (apb_req_from_ac.pstrb[b] && !apb_resp_from_ac.pready) begin
                    shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                        CLASS1_SHADOW_RANGES,
                        (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))][b*8+:8] <=
                        apb_req_from_ac.pwdata[b*8+:8];
                  end
                end
              end else begin
                for (int b = 0; b < 4; b++) begin
                  if (apb_req_from_ac.pstrb[b] && !apb_resp_from_ac.pready) begin
                    shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
                        CLASS1_SHADOW_RANGES,
                        (ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2))][b*8+:8] <=
                        apb_req_from_ac.pwdata[b*8+:8];
                  end
                end
              end
            end
            apb_resp_from_ac.pready  <= 1'b1;
            apb_resp_from_ac.pslverr <= 1'b0;
            apb_resp_from_ac.prdata  <= efuse_data_t'(0);
          end

          // if it is a read (read apb has already been filtered by access control)
          else if (!apb_req_from_ac.pwrite) begin
            apb_resp_from_ac.pready  <= 1'b1;
            apb_resp_from_ac.pslverr <= 1'b0;
            apb_resp_from_ac.prdata  <= shadow_efuse.values[(ShadowEfuseWidth)'(apb_req_from_ac.paddr>>2)];
          end
        // LC_STATE access
        end else if (HAS_LC_STATE) begin
          if (shadow_efuse.values[efuse_pkg::SHADOW_IDX_TRANSIENT_RMA_EN][0] == 1'b1) begin
            priority if (rma_chiplet_token_match_i == TOKEN_MATCH_CODE &&
                         !chiplet_state_change_completed_n0_scan) begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES,
                  efuse_pkg::SHADOW_IDX_LC_STATE)][2*LC_STATE_WIDTH-1:0] <= lc_state_diff_d;
              chiplet_state_change_completed_n0_scan <= 1'b1;
            end else if (rma_sip_token_match_i == TOKEN_MATCH_CODE &&
                         !sop_state_change_completed_n0_scan) begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES,
                  efuse_pkg::SHADOW_IDX_LC_STATE)][2*LC_STATE_WIDTH-1:0] <= lc_state_diff_d;
              sop_state_change_completed_n0_scan <= 1'b1;
            end else begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES,
                  efuse_pkg::SHADOW_IDX_LC_STATE)][2*LC_STATE_WIDTH-1:0] <=
                  shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                      CLASS1_SHADOW_RANGES,
                      efuse_pkg::SHADOW_IDX_LC_STATE)][2*LC_STATE_WIDTH-1:0];
            end
          end
          apb_resp_from_ac.pready  <= 1'b0;
          apb_resp_from_ac.pslverr <= 1'b0;
          apb_resp_from_ac.prdata  <= efuse_data_t'(0);
        end else begin
          // reset APB response channel in SMC case where HAS_LC_STATE=0
          apb_resp_from_ac.pready  <= 1'b0;
          apb_resp_from_ac.pslverr <= 1'b0;
          apb_resp_from_ac.prdata  <= efuse_data_t'(0);
          // No chiplet state change in the SMC instance.
          chiplet_state_change_completed_n0_scan <= 1'b1;
          sop_state_change_completed_n0_scan <= 1'b1;
        end
      end  // end of APB ACCESS_AND_TRANSIENT_RMA_EN condition
    end  // end of (NOT RESET condition)
  end  //end of always block

  assign shadow_efuse_o = shadow_efuse_masked;
  assign fuse_sense_done_o = fuse_sense_done;

  // debug ports
  assign is_write_locked_o = write_locked;
  assign is_write_setup_only_o = write_setup_only;
  assign is_lc_state_access_o = is_lc_state_access;
  assign is_read_locked_o = read_locked;

  `OCAH_OT_ASSERT_INIT(Class1ShadowRangesValid_A,
      efuse_pkg::shadow_range_map_is_valid(CLASS1_SHADOW_RANGES, NumShadowWords))
  `OCAH_OT_ASSERT_INIT(Class1ShadowCountFits_A,
      ActualNumClass1ShadowWords <= NumShadowWords)
  `OCAH_OT_ASSERT_INIT(SecretShadowRangesValid_A,
      efuse_pkg::shadow_range_map_is_valid(SECRET_SHADOW_RANGES, NumShadowWords))

  for (genvar i = 0; i < NumShadowWords; i++) begin : gen_secret_word_assert
    if (efuse_pkg::shadow_range_map_contains_word(SECRET_SHADOW_RANGES, i)) begin : gen_masked
      `OCAH_OT_ASSERT(SecureTmSecretWordZero_A,
          secure_tm_i |-> shadow_efuse_o.values[i] == '0, clk_i, !rst_ni)
    end
  end

endmodule : efuse_shadow_regs
