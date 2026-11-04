// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mirror sensed fuse bits in a shadow file and serve the MAP APB window under lock controls.
//
// After reset it issues one fuse READ command of SENSE_WORDS words, or with ISSUE_SENSE clear
// observes a READ another instance issues on the same response stream. It stores responses
// LOAD_WORD_OFFSET onwards into the shadow file, then serves APB reads/writes through the
// access control.
// CLASS1_SHADOW_RANGES places words in separately named storage for scan exclusion;
// SECRET_SHADOW_RANGES selects the words that secure_tm_i zeroes on the hardware output.
// TOKEN_MATCH_CODE and the RMA token match inputs gate lifecycle-state transitions.
// fuse_sense_done_o marks initial sense complete for token processing;
// locked_field_access_interrupt_o reports locked-field APB hits.

`include "prim_assert.sv"
`include "ocah_assert.svh"
`include "ocah_registers.svh"

module efuse_shadow_regs
#(
    parameter int unsigned FUSE_MAP_REG_MAP_BASE_ADDR = 32'h0,  // Base address of the MAP window;
                                                                // not used in this module, which
                                                                // decodes window offsets.

    parameter int unsigned SHADOW_REG_BITS = 24576,  // Shadow register file size in bits.
    parameter int unsigned SHADOW_REG_BYTES = SHADOW_REG_BITS / 8,  // Shadow register file size in bytes.
    parameter int unsigned SHADOW_REG_WORD_WIDTH = 32,  // Shadow word width in bits.
    parameter int unsigned EFUSE_FIELDS = 1,  // eFuse field-map entry count.
    parameter int unsigned REG_ADDR_WIDTH = 12,  // Width of the MAP window byte offset on
                                                 // apb_req_paddr_i.

    parameter bit HAS_LC_STATE = 1'b0,  // Set for SEP: keeps the lifecycle state, differentially
                                        // encoded, in shadow word ShadowIdxLcState and applies
                                        // token-gated lifecycle transitions; clear for SMC.
    parameter efuse_pkg::shadow_word_range_map_t CLASS1_SHADOW_RANGES = '0,  // Class-1 shadow word ranges, stored in
                                                                             // the separately named *_n0_scan array;
                                                                             // the lifecycle-state word is always
                                                                             // written there, so it must be covered
                                                                             // when HAS_LC_STATE is set.
    parameter efuse_pkg::shadow_word_range_map_t SECRET_SHADOW_RANGES = '0,  // Secret shadow ranges masked under secure_tm.

    parameter int unsigned SENSE_WORDS = SHADOW_REG_BITS / SHADOW_REG_WORD_WIDTH,  // Words in the sense READ; all
                                                                                   // are counted before sensing
                                                                                   // completes.
    parameter int unsigned LOAD_WORD_OFFSET = 0,  // Sense response index stored in shadow word 0; must be 0
                                                  // when HAS_LC_STATE is set.
    parameter bit ISSUE_SENSE = 1'b1,  // Set to issue the sense READ on fuse_command_req_o; clear to
                                       // leave it idle and count a READ issued elsewhere.
    parameter int unsigned LOCK_VECTOR_BITS = 2 * (EFUSE_FIELDS - 1),  // Hardware lock bits applied to the
                                                                       // field map.
    parameter bit EXT_LOCKS = 1'b0,  // Set to take the hardware lock bits from ext_locks_i; clear to
                                     // take them from the leading shadow words.
    parameter string PRELOAD_PLUSARG =  // Plusarg naming the simulation preload file.
        HAS_LC_STATE ? "sep_shadow_reg_preload" : "smc_shadow_reg_preload",

    parameter logic [5:0] TOKEN_MATCH_CODE = 6'b010101,  // Token-match code that permits the RMA
                                                         // lifecycle-state transitions.

    parameter type efuse_apb_resp_t = logic,  // eFuse APB response type.

    parameter type efuse_addr_t = logic,  // Fuse bit-address type.
    parameter type efuse_data_t = logic,  // Fuse data-word type.
    parameter type efuse_word_counter_t = logic,  // Fuse access-length counter type.
    parameter type fuse_command_req_t = logic,  // Fuse-command request type.
    parameter type fuse_command_resp_t = logic,  // Fuse-command response type.

    parameter type efuse_map_t = logic,  // Shadow eFuse map type.

    localparam int unsigned LcStateWidth = efuse_pkg::LcStateRawWidth,  // Lifecycle-state field width; fixed by the encoding in efuse_pkg.

    localparam int unsigned NumShadowWords = SHADOW_REG_BITS / SHADOW_REG_WORD_WIDTH,  // Shadow file word count.
    localparam int unsigned ShadowEfuseWidth =  // Shadow word index width.
        NumShadowWords > 1 ? $clog2(NumShadowWords) : 1
) (

    input  logic                                clk_i,  // System clock.
    input  logic                                rst_ni,  // Active-low asynchronous reset; its
                                                         // release starts fuse sensing.
    input  logic                                security_disable_i,  // Security disable, active-high; stops loading
                                                                     // from the fuses and opens APB access to the
                                                                     // shadow file before sensing completes.
    input  logic                                secure_tm_i,  // Secure test mode, active-high;
                                                              // zeroes the secret words on
                                                              // shadow_efuse_o and adds the
                                                              // secure-test-mode lock to write
                                                              // checks.

    input  efuse_pkg::rule_t [EFUSE_FIELDS-1:0] efuse_field_map_i,  // Per-field byte ranges, lock indices, and
                                                                    // software lock bits for the access control.

    input  logic [REG_ADDR_WIDTH-1:0]           apb_req_paddr_i,  // Byte offset within the MAP
                                                                  // window.
    input  logic                                apb_req_psel_i,  // APB select for the MAP window.
    input  logic                                apb_req_penable_i,  // APB access phase.
    input  logic                                apb_req_pwrite_i,  // APB transfer direction, high
                                                                   // for a write.
    input  logic [31:0]                         apb_req_pwdata_i,  // Write data; set-only fields OR
                                                                   // it into the stored bits.
    input  logic [3:0]                          apb_req_pstrb_i,  // Byte lane enables for the
                                                                  // write.

    output efuse_apb_resp_t                     apb_resp_o,  // APB response; errors with 0xBADCAB1E
                                                             // before fuse sensing completes or
                                                             // beyond the shadow file, and returns
                                                             // 0xBADCAB1E without an error for a
                                                             // locked access.

    output logic                                fuse_sense_done_o,  // Set once the sense read has returned a
                                                                    // response for every shadow word, errored or
                                                                    // not; held until reset.
    output efuse_map_t                          shadow_efuse_o,  // Shadow eFuse map, with the
                                                                 // secret words zeroed while secure
                                                                 // test mode is active.
    input  logic [5:0]                          rma_chiplet_token_match_i,  // RMA chiplet token-match code; a match
                                                                            // permits setting lifecycle-state bit 2
                                                                            // once bit 1 is set.
    input  logic [5:0]                          rma_sip_token_match_i,  // RMA SiP token-match code; a match permits
                                                                        // setting lifecycle-state bit 1.

    output fuse_command_req_t                   fuse_command_req_o,  // Registered sense command: one READ of
                                                                     // SENSE_WORDS words from bit address 0; valid
                                                                     // stays high once issued. Idle when
                                                                     // ISSUE_SENSE is clear.
    input  fuse_command_resp_t                  fuse_command_resp_i,  // Streamed sense responses; each valid response
                                                                      // advances the sense index, and one without an
                                                                      // error status is stored in its shadow word.

    input  logic [LOCK_VECTOR_BITS-1:0]         ext_locks_i,  // Hardware lock bits used when EXT_LOCKS is
                                                              // set: write lock at 2n, read lock at 2n+1.
    output logic [LOCK_VECTOR_BITS-1:0]         lock_vector_o,  // Hardware lock bits applied to the field
                                                                // map, from the unmasked shadow file.

    output logic                                is_write_locked_o,  // High while an APB write is blocked by a lock.
    output logic                                is_write_setup_only_o,  // High when the APB address falls in a
                                                                        // set-only field.
    output logic                                is_lc_state_access_o,  // High when the APB address falls in the
                                                                       // lifecycle-state field.
    output logic                                is_read_locked_o,  // High when the APB address
                                                                   // falls in a read-locked field.

    output logic                                locked_field_access_interrupt_o  // High during an APB access to the
                                                                                 // MAP window that a lock blocks.
);

  localparam fuse_command_req_t FuseCommandReqDefault = '0;
  localparam fuse_command_resp_t FuseCommandRespDefault = '0;

  typedef int unsigned shadow_word_idx_t;

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

  logic [LcStateWidth-1:0] lc_state_raw_d;
  logic [2*LcStateWidth-1:0] lc_state_diff_d;

  logic sim_skip_fuse_sense;
  reg [31:0] shadow_reg_preload [0:NumShadowWords-1];

`ifdef EMULATION
  assign sim_skip_fuse_sense = 1'b0;
`elsif SIMULATION
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
`ifdef SIMULATION
`ifndef EMULATION
  initial begin
    string preload_file;
    logic preload_plusarg_found;
    preload_plusarg_found = 1'b0;

    if ($test$plusargs("skip_fuse_sense") &&
        $value$plusargs({PRELOAD_PLUSARG, "=%s"}, preload_file)) begin
      $display("Loading shadow reg preload data from %s", preload_file);
      $readmemh(preload_file, shadow_reg_preload, 0, NumShadowWords-1);
      preload_plusarg_found = 1'b1;
    end
    if ($test$plusargs("skip_fuse_sense") && preload_plusarg_found == 1'b0) begin
        $display("[INFO] +skip_fuse_sense provided, but the required shadow register preload plusarg (+%s=filename) was NOT found.", PRELOAD_PLUSARG);

        $display("[INFO] Initializing shadow_reg_preload array to default pattern (32'h00000000) due to missing preload file.");
        for (int i = 0; i < NumShadowWords; i++) begin : preload_not_found
        if (HAS_LC_STATE && (i == efuse_pkg::ShadowIdxLcState)) begin : reset_lc_state
          shadow_reg_preload[i] = {{(32-2*LcStateWidth){1'b0}}, {LcStateWidth{1'b0}}, {LcStateWidth{1'b1}}};
        end else begin : smc_case
          shadow_reg_preload[i] = 32'h0;
        end
        end

    end
  end
`endif
`endif

  logic fuse_sense_done;
  logic write_locked;
  logic write_setup_only;
  logic is_lc_state_access;
  logic read_locked;

  // Extract the hardware lock vector from the unmasked shadow register.
  // Two bits per real field slot (write-lock at 2n, read-lock at 2n+1).
  // The lock meta-field uses the fixed sentinel idx '1 (all-ones = 6'h3F)
  // and is excluded from this vector; its slot always returns 0 (never hw-locked).
  // Taken from the unmasked shadow_efuse view so a Class-1a secure_tm mask cannot
  // clear lock bits and open a field for scanning.
  // Number of 32-bit shadow words that cover LOCK_VECTOR_BITS (ceiling divide).
  localparam int unsigned LockWords = (LOCK_VECTOR_BITS + 31) / 32;

  logic [LOCK_VECTOR_BITS-1:0] lock_vector;

  if (EXT_LOCKS) begin : gen_ext_lock_vector
    assign lock_vector = ext_locks_i;
  end else begin : gen_shadow_lock_vector
    logic [LockWords*32-1:0] lock_words_concat;

    always_comb begin
      for (int w = 0; w < int'(LockWords); w++) begin
        lock_words_concat[w*32 +: 32] = shadow_efuse.values[w];
      end
    end
    assign lock_vector = lock_words_concat[LOCK_VECTOR_BITS-1:0];
  end

  assign lock_vector_o = lock_vector;

  efuse_shadow_reg_access_control #(
      .EFUSE_ADDR_WIDTH (REG_ADDR_WIDTH),
      .EFUSE_FIELDS     (EFUSE_FIELDS),
      .HAS_LC_STATE     (HAS_LC_STATE),
      .efuse_addr_t     (efuse_addr_t),
      .LOCK_VECTOR_BITS (LOCK_VECTOR_BITS)
  ) u_efuse_shadow_reg_access_control (
      .secure_tm_i        (secure_tm_i),
      .efuse_field_map_i  (efuse_field_map_i),
      .locks_i            (lock_vector),
      .addr_i             (apb_req_paddr_i),
      .write_locked_o     (write_locked),
      .read_locked_o      (read_locked),
      .write_setup_only_o (write_setup_only),
      .lc_state_access_o  (is_lc_state_access)
  );

  ////////////////////////////////////////////////////////////////////////////
  // APB Access
  ////////////////////////////////////////////////////////////////////////////

  // An access phase to a locked field completes at once with 0xBADCAB1E and no error, and
  // touches no storage. Every other access phase is a shadow-register access, answered from
  // apb_resp_q.
  logic apb_access_phase;
  logic write_blocked;
  logic read_blocked;
  logic shadow_reg_access;

  assign apb_access_phase = apb_req_psel_i && apb_req_penable_i;
  assign write_blocked    = apb_access_phase && apb_req_pwrite_i && write_locked;
  assign read_blocked     = apb_access_phase && !apb_req_pwrite_i && read_locked;
  assign shadow_reg_access = apb_access_phase && !write_blocked && !read_blocked;

  assign locked_field_access_interrupt_o = write_blocked || read_blocked;

  efuse_apb_resp_t apb_resp_q;

  always_comb begin
    apb_resp_o.pready  = 1'b0;
    apb_resp_o.prdata  = efuse_data_t'(0);
    apb_resp_o.pslverr = 1'b0;
    if (write_blocked || read_blocked) begin
      apb_resp_o.pready = 1'b1;
      apb_resp_o.prdata = efuse_data_t'(32'hbadcab1e);
    end else if (shadow_reg_access) begin
      apb_resp_o = apb_resp_q;
    end
  end

  // The shadow file takes shadow-register accesses once it is loaded from the fuses, or from
  // the preload file in simulation, and at once when security_disable_i skips sensing.
  logic preloading;
  logic sensing;
  logic shadow_ready;

  assign preloading   = sim_skip_fuse_sense && !fuse_sense_done;
  assign sensing      = !preloading && !fuse_sense_done && !security_disable_i;
  assign shadow_ready = !preloading && !sensing;

  logic                        addr_out_of_range;
  logic [ShadowEfuseWidth-1:0] word_sel;
  logic                        word_is_class1;

  assign addr_out_of_range = efuse_addr_t'(apb_req_paddr_i) > efuse_addr_t'(SHADOW_REG_BYTES - 4);
  assign word_sel          = ShadowEfuseWidth'(apb_req_paddr_i >> 2);
  assign word_is_class1    = efuse_pkg::shadow_range_map_contains_word(
                                 CLASS1_SHADOW_RANGES, shadow_word_idx_t'(word_sel));

  // A write commits in the first cycle of its access phase; apb_resp_q.pready holds it off for
  // the rest of the phase.
  logic wr_commit;
  assign wr_commit = shadow_ready && shadow_reg_access && apb_req_pwrite_i && !addr_out_of_range &&
                     !apb_resp_q.pready;

  // The word a committed write leaves behind. Set-only fields OR the write data into the
  // stored bits. In a set-only lifecycle-state field, byte 0 takes the encoder output, which
  // applies the set-only rule and the token gates, and the upper bytes take the write data.
  logic set_only_write;
  logic lc_state_write;
  logic [SHADOW_REG_WORD_WIDTH-1:0] wr_word;

  assign set_only_write = write_setup_only && !is_lc_state_access;
  assign lc_state_write = write_setup_only && is_lc_state_access;

  always_comb begin
    wr_word = shadow_efuse.values[word_sel];
    for (int b = 0; b < 4; b++) begin
      if (apb_req_pstrb_i[b]) begin
        if (lc_state_write && (b == 0)) begin
          wr_word[2*LcStateWidth-1:0] = lc_state_diff_d;
        end else if (set_only_write) begin
          wr_word[b*8+:8] = wr_word[b*8+:8] | apb_req_pwdata_i[b*8+:8];
        end else begin
          wr_word[b*8+:8] = apb_req_pwdata_i[b*8+:8];
        end
      end
    end
  end

  // Shadow-register accesses error with 0xBADCAB1E until the shadow file is ready, and beyond
  // its last word.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      apb_resp_q <= '0;
    end else if (shadow_reg_access) begin
      apb_resp_q.pready <= 1'b1;
      if (!shadow_ready || addr_out_of_range) begin
        apb_resp_q.pslverr <= 1'b1;
        apb_resp_q.prdata  <= efuse_data_t'('hbadcab1e);
      end else begin
        apb_resp_q.pslverr <= 1'b0;
        apb_resp_q.prdata  <= apb_req_pwrite_i ? efuse_data_t'(0) : shadow_efuse.values[word_sel];
      end
    end else if (shadow_ready) begin
      apb_resp_q <= '0;
    end
  end

  efuse_word_counter_t current_word_num_q, current_word_num_d;
  efuse_word_counter_t words_received_q, words_received_d;
  fuse_command_req_t fuse_command_req_d;

  logic [LcStateWidth-1:0] lc_state_cur;
  logic [LcStateWidth-1:0] lc_state_candidate;

  // Shadow word the current sense response belongs to, if any.
  logic load_word_in_range;
  shadow_word_idx_t load_word_idx;

  // A response before LOAD_WORD_OFFSET wraps load_word_idx past NumShadowWords.
  assign load_word_idx = shadow_word_idx_t'(words_received_q) - LOAD_WORD_OFFSET;
  assign load_word_in_range = load_word_idx < NumShadowWords;

  // Combinationally compute the next raw LC_STATE value for each write path,
  // then feed it through the differential encoder so the always_ff can store
  // the full encoded value atomically.
  always_comb begin
      lc_state_raw_d = '0;
      lc_state_candidate = '0;
      lc_state_cur = '0;
      if (HAS_LC_STATE) begin
          lc_state_raw_d = shadow_efuse.values[efuse_pkg::ShadowIdxLcState][LcStateWidth-1:0];
          lc_state_candidate = shadow_efuse.values[efuse_pkg::ShadowIdxLcState][LcStateWidth-1:0];
          if (preloading) begin
              lc_state_raw_d = shadow_reg_preload[efuse_pkg::ShadowIdxLcState][LcStateWidth-1:0];
          end
          else if (sensing) begin
              if (fuse_command_resp_i.valid && !fuse_command_resp_i.status &&
                  load_word_in_range && load_word_idx == efuse_pkg::ShadowIdxLcState) begin
                  lc_state_raw_d = fuse_command_resp_i.data[LcStateWidth-1:0];
              end
          end else begin
              // A write may set any LC_STATE bit, giving a valid encoding or not, subject to the
              // token gates: bit 1 (RMA_SIP) needs a SIP token match, and bit 2 (RMA_CHIPLET)
              // needs a chiplet token match with bit 1 already set. An invalid encoding is
              // terminal.
              lc_state_cur = shadow_efuse.values[efuse_pkg::ShadowIdxLcState][LcStateWidth-1:0];

              if (efuse_pkg::is_invalid_lc_state(lc_state_cur)) begin
                  lc_state_raw_d = lc_state_cur;
              end
              // A shadow-register access holds off the transient RMA update; only a write to
              // byte 0 of a set-only lifecycle-state field changes the state.
              else if (shadow_reg_access) begin
                  if (apb_req_pwrite_i && lc_state_write && apb_req_pstrb_i[0]) begin
                      lc_state_candidate[0] = apb_req_pwdata_i[0] | lc_state_cur[0];
                      lc_state_candidate[1] = (rma_sip_token_match_i == TOKEN_MATCH_CODE)
                          ? (apb_req_pwdata_i[1] | lc_state_cur[1])
                          : lc_state_cur[1];
                      lc_state_candidate[2] = (lc_state_cur[1] &&
                                               (rma_chiplet_token_match_i == TOKEN_MATCH_CODE))
                          ? (apb_req_pwdata_i[2] | lc_state_cur[2])
                          : lc_state_cur[2];
                      lc_state_candidate[3] = apb_req_pwdata_i[3] | lc_state_cur[3];
                      lc_state_raw_d = lc_state_candidate;
                  end
              end else if (shadow_efuse.values[efuse_pkg::ShadowIdxTransientRmaEn][0] == 1'b1) begin
                  // Transient RMA applies the same token gates as the APB path.
                  if (rma_chiplet_token_match_i == TOKEN_MATCH_CODE && lc_state_cur[1]) begin
                      lc_state_raw_d[2] = 1'b1;
                  end else if (rma_chiplet_token_match_i == TOKEN_MATCH_CODE) begin
                      // A chiplet match without RMA_SIP established changes nothing.
                  end else if (rma_sip_token_match_i == TOKEN_MATCH_CODE) begin
                      lc_state_raw_d[1] = 1'b1;
                  end
              end
          end
      end
  end

  prim_diff_encode_multi #(.WIDTH(LcStateWidth)) u_lc_state_enc (
      .clk_i,
      .rst_ni,
      .data_i (lc_state_raw_d),
      .data_o (lc_state_diff_d)
  );

  // Fuse sense state machine
  typedef enum {
    ST_IDLE, ST_READ, ST_WAIT, ST_FINISHED
  } efuse_sense_state_e;

  efuse_sense_state_e efuse_sense_state_d, efuse_sense_state_q;

    always_comb begin
        efuse_sense_state_d = efuse_sense_state_q;
        words_received_d = words_received_q;
        current_word_num_d = current_word_num_q;
        fuse_command_req_d = fuse_command_req_o;

        unique case (efuse_sense_state_q)
            ST_IDLE: begin
                if (rst_ni) begin
                    efuse_sense_state_d = ST_READ;
                    words_received_d = '0;
                    current_word_num_d = '0;
                end
            end

            ST_READ: begin
                if (ISSUE_SENSE) begin
                    // .address is a bit address. current_word_num_q is always 0 here, so it is
                    // also bit 0 of word 0.
                    fuse_command_req_d.address = efuse_addr_t'(current_word_num_q);
                    fuse_command_req_d.access_length_words =
                        efuse_word_counter_t'(SENSE_WORDS);
                    fuse_command_req_d.valid = 1'b1;
                    fuse_command_req_d.command = efuse_pkg::FUSE_COMMAND_READ;
                end

                efuse_sense_state_d = ST_WAIT;
                words_received_d = '0;
            end

            ST_WAIT: begin

                if (fuse_command_resp_i.valid) begin
                    if (words_received_q >= efuse_word_counter_t'(SENSE_WORDS - 1)) begin
                        efuse_sense_state_d = ST_FINISHED;
                    end else begin
                        words_received_d = words_received_q + efuse_word_counter_t'(1);
                        current_word_num_d = current_word_num_q + efuse_word_counter_t'(1);
                    end
                end

            end

            ST_FINISHED: begin
                efuse_sense_state_d = ST_FINISHED;
            end

            // Default case to catch parasitic states
            default: begin
                efuse_sense_state_d = fuse_sense_done ? ST_FINISHED : ST_IDLE;
            end
        endcase
    end

    `OCAH_FF(efuse_sense_state_q, efuse_sense_state_d, ST_IDLE, clk_i, rst_ni)
    `OCAH_FF(current_word_num_q, current_word_num_d, '0, clk_i, rst_ni)
    `OCAH_FF(words_received_q, words_received_d, efuse_word_counter_t'(0), clk_i, rst_ni)
    `OCAH_FF(fuse_command_req_o, fuse_command_req_d, FuseCommandReqDefault, clk_i, rst_ni)

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      fuse_sense_done <= 1'b0;
    end else if (sim_skip_fuse_sense) begin
      fuse_sense_done <= 1'b1;
    end else if ((efuse_sense_state_q == ST_FINISHED) && !fuse_sense_done) begin
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
              (i == efuse_pkg::ShadowIdxLcState)) begin : reset_lc_state
            shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                CLASS1_SHADOW_RANGES, i)] <=
                efuse_data_t'({{LcStateWidth{1'b0}}, {LcStateWidth{1'b1}}});
          end else begin : reset_class1_shadow_reg
            shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                CLASS1_SHADOW_RANGES, i)] <= efuse_data_t'(0);
          end
        end else begin : reset_shadow_reg
          shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
              CLASS1_SHADOW_RANGES, i)] <= efuse_data_t'(0);
        end
      end

      chiplet_state_change_completed_n0_scan <= 1'b0;
      sop_state_change_completed_n0_scan <= 1'b0;

    end else begin
      /////////////////////////////////////////
      // preload shadow registers - simulating
      /////////////////////////////////////////
      if (preloading) begin : preload_shadow_regs
        for (int i = 0; i < NumShadowWords; i++) begin : preload_shadow_registers
          if (efuse_pkg::shadow_range_map_contains_word(CLASS1_SHADOW_RANGES, i)) begin
            if (HAS_LC_STATE && (i == efuse_pkg::ShadowIdxLcState)) begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES, i)] <=
                  {shadow_reg_preload[i][31:2*LcStateWidth], lc_state_diff_d};
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
      end
      ////////////////////////////////////////////////////////////////////
      // load shadow registers from streaming fuse sense command responses
      ////////////////////////////////////////////////////////////////////
      else if (sensing) begin : load_shadow_regs
        if (fuse_command_resp_i.valid && (fuse_command_resp_i.status == 1'b0)) begin
          // Store the data at the current word index (before incrementing words_received)
          if (load_word_in_range) begin
            if (HAS_LC_STATE && load_word_idx == efuse_pkg::ShadowIdxLcState) begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES, load_word_idx)] <=
                  {fuse_command_resp_i.data[31:2*LcStateWidth], lc_state_diff_d};
            end else begin
              if (efuse_pkg::shadow_range_map_contains_word(
                  CLASS1_SHADOW_RANGES, load_word_idx)) begin
                shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                    CLASS1_SHADOW_RANGES, load_word_idx)] <=
                    fuse_command_resp_i.data;
              end else begin
                shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
                    CLASS1_SHADOW_RANGES, load_word_idx)] <=
                    fuse_command_resp_i.data;
              end
            end
          end
        end
      end

      //////////////////////////////////////////////////////////////////////////////////
      // apb writes and transient rma en - regular operation
      //////////////////////////////////////////////////////////////////////////////////
      else if (wr_commit) begin : apb_write
        if (word_is_class1) begin
          shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
              CLASS1_SHADOW_RANGES, shadow_word_idx_t'(word_sel))] <= wr_word;
        end else begin
          shadow_efuse_values[efuse_pkg::normal_shadow_storage_idx(
              CLASS1_SHADOW_RANGES, shadow_word_idx_t'(word_sel))] <= wr_word;
        end
      end else if (!shadow_reg_access) begin : transient_rma_en
        if (HAS_LC_STATE) begin
          if (shadow_efuse.values[efuse_pkg::ShadowIdxTransientRmaEn][0] == 1'b1) begin
            priority if (rma_chiplet_token_match_i == TOKEN_MATCH_CODE &&
                         !chiplet_state_change_completed_n0_scan) begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES,
                  efuse_pkg::ShadowIdxLcState)][2*LcStateWidth-1:0] <= lc_state_diff_d;
              chiplet_state_change_completed_n0_scan <= 1'b1;
            end else if (rma_sip_token_match_i == TOKEN_MATCH_CODE &&
                         !sop_state_change_completed_n0_scan) begin
              shadow_efuse_values_n0_scan[efuse_pkg::class1_shadow_storage_idx(
                  CLASS1_SHADOW_RANGES,
                  efuse_pkg::ShadowIdxLcState)][2*LcStateWidth-1:0] <= lc_state_diff_d;
              sop_state_change_completed_n0_scan <= 1'b1;
            end
          end
        end else begin
          // No chiplet state change in the SMC instance.
          chiplet_state_change_completed_n0_scan <= 1'b1;
          sop_state_change_completed_n0_scan <= 1'b1;
        end
      end
    end
  end

  assign shadow_efuse_o = shadow_efuse_masked;
  assign fuse_sense_done_o = fuse_sense_done;

  // debug ports
  assign is_write_locked_o = write_blocked;
  assign is_write_setup_only_o = write_setup_only;
  assign is_lc_state_access_o = is_lc_state_access;
  assign is_read_locked_o = read_locked;

  `OCAH_ASSERT_STATIC(Class1ShadowRangesValid_A,
      efuse_pkg::shadow_range_map_is_valid(CLASS1_SHADOW_RANGES, NumShadowWords))
  `OCAH_ASSERT_STATIC(Class1ShadowCountFits_A,
      ActualNumClass1ShadowWords <= NumShadowWords)
  `OCAH_ASSERT_STATIC(SecretShadowRangesValid_A,
      efuse_pkg::shadow_range_map_is_valid(SECRET_SHADOW_RANGES, NumShadowWords))
  `OCAH_ASSERT_STATIC(SenseWordsFitWordCounter_A,
      $clog2(SENSE_WORDS + 1) <= $bits(efuse_word_counter_t))
  `OCAH_ASSERT_STATIC(ShadowWordsWithinSense_A,
      LOAD_WORD_OFFSET + NumShadowWords <= SENSE_WORDS)
  `OCAH_ASSERT_STATIC(LcStateNeedsZeroLoadOffset_A,
      !HAS_LC_STATE || (LOAD_WORD_OFFSET == 0))
  `OCAH_ASSERT_STATIC(LockWordsWithinShadow_A,
      EXT_LOCKS || (LockWords <= NumShadowWords))

  for (genvar i = 0; i < NumShadowWords; i++) begin : gen_secret_word_assert
    if (efuse_pkg::shadow_range_map_contains_word(SECRET_SHADOW_RANGES, i)) begin : gen_masked
      `OCAH_OT_ASSERT(SecureTmSecretWordZero_A,
          secure_tm_i |-> shadow_efuse_o.values[i] == '0, clk_i, !rst_ni)
    end
  end

endmodule : efuse_shadow_regs
