// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap CPU control CSRs for the SMC cluster.
//
// Implements the cpu_ctrl registers behind an AXI-Lite port: core, uncore and debug reset
// control with a drain handshake and timeout, per-core reset vectors and reset pulses, a
// second watchdog stage, an eight-entry writeback PC history per core, the reference counter,
// mutexes, semaphores, scratch registers and SMC_ATTRIBUTES.
// In smc_cpu_wrapper it sits behind the front-port demux beside the L2 frontend.

module smc_cpu_ctrl_wrap #(
  parameter bit NO_ADDR_REMAP = 1'b1,   // Reported in SMC_ATTRIBUTES.no_output_remap; no other
                                        // effect in this module.
  parameter int unsigned NUM_CPU_CORES               = 4,  // Number of CPU cores this block drives
                                                           // resets, reset vectors and watchdog
                                                           // counters for; at most MaxCPUCores.

  localparam int unsigned MaxCPUCores                = 4  // Number of cores the cpu_ctrl register
                                                          // map provides per-core fields for; sizes
                                                          // the internal per-core arrays.
) (
  input  logic                                    clk_ref_i,  // Reference clock for the
                                                              // free-running REFERENCE_COUNTER
                                                              // counter.
  input  logic                                    clk_smc_i,  // SMC core clock for the CSR block,
                                                              // reset control and watchdog logic.
  input  logic                                    rst_warm_smc_clk_ni,  // Active-low warm reset in
                                                                        // the clk_smc_i domain;
                                                                        // while low, holds the core
                                                                        // and uncore resets
                                                                        // asserted and drives
                                                                        // core_reset_vector_o to
                                                                        // the default boot address
                                                                        // 0xC0040000.
  input  logic                                    rst_primary_ni,  // Active-low primary reset in
                                                                   // the clk_smc_i domain; resets
                                                                   // the CSR block, reference
                                                                   // counter, watchdog, PC history,
                                                                   // reset-control state, mutexes
                                                                   // and semaphores.

  input  logic                                    test_en_i,  // Scan test mode enable; not used in
                                                              // this module.
  input  logic                                    scan_rst_ni,  // Active-low scan reset; not used
                                                                // in this module.

  input  smc_pkg::smc_axil_32_64_req_t            axil_req_i,  // AXI-Lite request to the cpu_ctrl
                                                               // CSR block from the SMC front-port
                                                               // demux.
  output smc_pkg::smc_axil_32_64_resp_t           axil_resp_o,  // AXI-Lite response from the
                                                                // cpu_ctrl CSR block.

  input  logic [NUM_CPU_CORES-1:0][57:0]          wb_reg_pc_i,  // Per-core writeback program
                                                                // counter from the cluster, sampled
                                                                // on clk_smc_i into the eight-entry
                                                                // WB_PC_CORE history; a value equal
                                                                // to the newest entry is not added
                                                                // again.
  input  logic [NUM_CPU_CORES-1:0]                wb_pc_valid_i,  // Per-core qualifier for
                                                                  // wb_reg_pc_i; a new PC enters
                                                                  // the history only while this is
                                                                  // high.

  input  logic [NUM_CPU_CORES-1:0]                wdt_timeout_cluster_i,  // Per-core first-stage watchdog
                                                                          // timeout; while high, that core's
                                                                          // second-stage counter counts
                                                                          // down, and while low it reloads
                                                                          // from WDT_TIMEOUT.
  input  logic                                    chiplet_is_primary_i,  // High on the primary chiplet;
                                                                         // read back through
                                                                         // SMC_ATTRIBUTES.
  output logic                                    wdt_second_timeout_o,  // Registered second-stage watchdog
                                                                         // timeout; high while any core's
                                                                         // counter is zero.

  output logic [NUM_CPU_CORES-1:0]                core_reset_n_n0_scan_o,  // Active-low per-core reset from
                                                                           // RESET_CTRL or a reset pulse,
                                                                           // registered on clk_smc_i and low
                                                                           // while warm reset is asserted; a
                                                                           // software assertion waits for the
                                                                           // cluster to drain or, in timeout
                                                                           // mode, for the RESET_TIMEOUT
                                                                           // timeout.
  output logic [NUM_CPU_CORES-1:0][55:0]          core_reset_vector_o,  // Per-core boot address
                                                                        // from the RESET_VECTOR
                                                                        // registers; the default
                                                                        // boot address while warm
                                                                        // reset is asserted.
  output logic                                    cluster_uncore_reset_n_n0_scan_o,  // Active-low uncore reset from
                                                                                     // RESET_CTRL, registered on
                                                                                     // clk_smc_i and low while warm
                                                                                     // reset is asserted; a software
                                                                                     // assertion waits for the cluster
                                                                                     // to drain or, in timeout mode,
                                                                                     // for the RESET_TIMEOUT timeout.
  output logic                                    debug_reset_n_o,  // Active-low debug-module
                                                                    // reset, driven directly from
                                                                    // the RESET_CTRL debug reset
                                                                    // field, which resets to 0
                                                                    // (asserted); not held by the
                                                                    // drain handshake.

  output logic                                    isolate_req_o,  // Drain request to the cluster:
                                                                  // high while RESET_CTRL holds a
                                                                  // core or the uncore in reset,
                                                                  // or a core reset pulse is
                                                                  // pending or in flight.
  input  logic                                    drained_i,  // High once the cluster boundary
                                                              // has drained and isolated;
                                                              // releases a withheld software
                                                              // reset.

  output logic                                    isolate_flush_o  // Flush request to the cluster
                                                                   // AXI isolate modules, high
                                                                   // while the RESET_TIMEOUT
                                                                   // timeout forces a withheld
                                                                   // reset in timeout mode.
);

  localparam cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t DEFAULT_RESET_SETTINGS =
      smc_4core_cpu_pkg::DEFAULT_RESET_SETTINGS;

  ///////////////////////
  // Reference Counter //
  ///////////////////////

  localparam int unsigned RefCountWidth = 64;  // 64 bit ref counter
  logic [RefCountWidth-1:0] ref_count_sync, ref_count_from_reg;
  logic ref_count_wr_swacc;
  logic ref_count_wr_swacc_q;

  // Delay wr_swacc one cycle so the update value is sampled after the CSR field
  // has captured the SW write data
  always_ff @(posedge clk_smc_i or negedge rst_primary_ni) begin
    if (!rst_primary_ni) begin
      ref_count_wr_swacc_q <= 1'b0;
    end else begin
      ref_count_wr_swacc_q <= ref_count_wr_swacc;
    end
  end

  prim_refclk_count_w_cdc #(
    .REF_COUNT_WIDTH(RefCountWidth)
  ) u_refclk_counter (
    .refclk_i(clk_ref_i),
    .prst_ni(rst_primary_ni),
    .cnt_en_i(1'b1),
    .cnt_update_i(ref_count_wr_swacc_q),
    .cnt_update_value_i(ref_count_from_reg),
    .out_clk_i(clk_smc_i),
    .count_o(ref_count_sync)
  );

  //////////////////////
  // Core Reset Logic //
  //////////////////////

  logic [MaxCPUCores-1:0]       int_core_reset_n;
  logic [MaxCPUCores-1:0][55:0] int_core_reset_vector;

  always_comb begin
    for (int i = 0; i < NUM_CPU_CORES; i = i + 1) begin
      core_reset_vector_o[i] = rst_warm_smc_clk_ni ? int_core_reset_vector[i] : 56'hC0040000;
    end
  end

  logic reg_uncore_reset_n;

  // Drain-handshake gated software resets (assigns live in the Reset Control
  // Logic section below, where the pulse signals they reference are declared).
  logic [NUM_CPU_CORES-1:0] gated_core_reset_n;
  logic                     gated_uncore_reset_n;

  always_ff @(posedge clk_smc_i or negedge rst_warm_smc_clk_ni) begin
    // flop both to prevent glitches
    if (~rst_warm_smc_clk_ni) begin
      core_reset_n_n0_scan_o <= {(NUM_CPU_CORES){1'b0}};
      cluster_uncore_reset_n_n0_scan_o <= 1'b0;
    end else begin
      core_reset_n_n0_scan_o <= gated_core_reset_n;
      cluster_uncore_reset_n_n0_scan_o <= gated_uncore_reset_n;
    end
  end

  //////////////////
  // Writeback PC //
  //////////////////

  // wb_reg_pc_i is from the core domain, which can be async reset, being captured on clk_smc_i
  // RDC issue

  // requested by fw team, would like a chain of 8 pc values to be stored for debug
  localparam int unsigned NUM_PC_REGS = 8;
  logic [NUM_CPU_CORES-1:0][NUM_PC_REGS-1:0][58-1:0] wb_reg_pc_sr;
  always_ff @(posedge clk_smc_i) begin
    for (int c = 0; c < NUM_CPU_CORES; c = c + 1) begin
      if (~rst_primary_ni) begin
        wb_reg_pc_sr[c] <= {(NUM_PC_REGS * 58) {1'b0}};
      end else begin
        if ((wb_reg_pc_sr[c][0] != wb_reg_pc_i[c]) && wb_pc_valid_i[c]) begin
          wb_reg_pc_sr[c] <= {wb_reg_pc_sr[c][NUM_PC_REGS-2:0], wb_reg_pc_i[c]};
        end
      end
    end
  end

  logic [MaxCPUCores-1:0][NUM_PC_REGS-1:0][58-1:0] int_wb_reg_pc_sr;
  always_comb begin
    int_wb_reg_pc_sr[MaxCPUCores-1:0] = {(MaxCPUCores*NUM_PC_REGS*58){1'b0}};
    int_wb_reg_pc_sr[NUM_CPU_CORES-1:0] = wb_reg_pc_sr;
  end

  //////////////////////////
  // Watchdog Timer Logic //
  //////////////////////////

  // smc_cpu's watchdog timer is a single stage timer
  // -> Create a pseudo dual-staged WDT by adding another timeout stage
  //    Timing out the second stage will drive a separate output wire
  logic [31:0] max_count;
  logic [MaxCPUCores-1:0] count_reset;
  logic [MaxCPUCores-1:0][31:0] cycle_count;
  logic [MaxCPUCores-1:0] smc_wdt_timeout;

  logic [NUM_CPU_CORES-1:0] reset_wdt_count;

  assign reset_wdt_count = ~{(NUM_CPU_CORES){rst_primary_ni}} | count_reset[NUM_CPU_CORES-1:0] | ~wdt_timeout_cluster_i[NUM_CPU_CORES-1:0];

  // wdt_timeout_cluster_i is from the rst_uncore_ni domain, which can be async reset, being captured on clk_smc_i
  generate
    for (genvar i = 0; i < NUM_CPU_CORES; i = i + 1) begin : gen_core_cycle_count
      always_ff @(posedge clk_smc_i) begin
        if (reset_wdt_count[i]) begin
          cycle_count[i] <= max_count;
        end else begin
          if (wdt_timeout_cluster_i[i] && (cycle_count[i] != 32'h0)) begin
            cycle_count[i] <= cycle_count[i] - 32'd1;
          end
        end
      end
    end
  endgenerate

  always_comb begin
    smc_wdt_timeout = {(MaxCPUCores) {1'b0}};
    for (int i = 0; i < NUM_CPU_CORES; i = i + 1) begin
      if (cycle_count[i] == 32'h0) begin
        smc_wdt_timeout[i] = 1'b1;
      end
    end
  end

  always_ff @(posedge clk_smc_i) begin
    if (~rst_primary_ni) begin
      wdt_second_timeout_o <= 1'b0;
    end else begin
      wdt_second_timeout_o <= |smc_wdt_timeout;
    end
  end

  // Register interface
  cpu_ctrl_reg_pkg::cpu_ctrl__in_t hwif_in;
  cpu_ctrl_reg_pkg::cpu_ctrl__out_t hwif_out;

  //////////////////////
  // Scratch Register //
  //////////////////////

  // Unused by hardware, pulled out for debug
  logic [31:0] scratch_reg[16];

  assign scratch_reg[0] = hwif_out.SCRATCH[0].data.value;
  assign scratch_reg[1] = hwif_out.SCRATCH[1].data.value;
  assign scratch_reg[2] = hwif_out.SCRATCH[2].data.value;
  assign scratch_reg[3] = hwif_out.SCRATCH[3].data.value;
  assign scratch_reg[4] = hwif_out.SCRATCH[4].data.value;
  assign scratch_reg[5] = hwif_out.SCRATCH[5].data.value;
  assign scratch_reg[6] = hwif_out.SCRATCH[6].data.value;
  assign scratch_reg[7] = hwif_out.SCRATCH[7].data.value;
  assign scratch_reg[8] = hwif_out.SCRATCH[8].data.value;
  assign scratch_reg[9] = hwif_out.SCRATCH[9].data.value;
  assign scratch_reg[10] = hwif_out.SCRATCH[10].data.value;
  assign scratch_reg[11] = hwif_out.SCRATCH[11].data.value;
  assign scratch_reg[12] = hwif_out.SCRATCH[12].data.value;
  assign scratch_reg[13] = hwif_out.SCRATCH[13].data.value;
  assign scratch_reg[14] = hwif_out.SCRATCH[14].data.value;
  assign scratch_reg[15] = hwif_out.SCRATCH[15].data.value;

  ////////////////////////
  // Register Interface //
  ////////////////////////

  // External register interface
  logic      [63:0] external_wr_data;
  logic      [63:0] external_wr_bit_mask;
  logic             reset_ctrl_wr_en;
  logic      [63:0] reset_ctrl_rd_data;
  logic      [3:0]  mutex;
  logic [3:0] mutex_wr_swacc, mutex_rd_swacc;
  logic [3:0][15:0] sema;
  logic      [3:0]  sema_wr_en;

  // Pulse core reset signals
  logic      [15:0] pre_reset_pulse_wait;
  logic      [15:0] post_reset_pulse_wait;

  logic [NUM_CPU_CORES-1:0] core_resets_pulse_start ;
  logic [MaxCPUCores-1:0] core_reset_pulse_out      ;
  logic [MaxCPUCores-1:0] core_reset_pulse_done ;

  logic [31:0] test_ctrl;

  cpu_ctrl_reg u_cpu_ctrl_reg (
    .clk(clk_smc_i),
    .arst_n(rst_primary_ni),

    .s_axil_awready(axil_resp_o.aw_ready),
    .s_axil_awvalid(axil_req_i.aw_valid),
    .s_axil_awaddr(axil_req_i.aw.addr[cpu_ctrl_reg_pkg::CPU_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_awprot(axil_req_i.aw.prot),
    .s_axil_wready(axil_resp_o.w_ready),
    .s_axil_wvalid(axil_req_i.w_valid),
    .s_axil_wdata(axil_req_i.w.data),
    .s_axil_wstrb(axil_req_i.w.strb),
    .s_axil_bready(axil_req_i.b_ready),
    .s_axil_bvalid(axil_resp_o.b_valid),
    .s_axil_bresp(axil_resp_o.b.resp),
    .s_axil_arready(axil_resp_o.ar_ready),
    .s_axil_arvalid(axil_req_i.ar_valid),
    .s_axil_araddr(axil_req_i.ar.addr[cpu_ctrl_reg_pkg::CPU_CTRL_REG_MIN_ADDR_WIDTH-1:0]),
    .s_axil_arprot(axil_req_i.ar.prot),
    .s_axil_rready(axil_req_i.r_ready),
    .s_axil_rvalid(axil_resp_o.r_valid),
    .s_axil_rdata(axil_resp_o.r.data),
    .s_axil_rresp(axil_resp_o.r.resp),

    .hwif_in(hwif_in),
    .hwif_out(hwif_out)
  );

  assign hwif_in.CORE_RESET_PULSE_COUNT.core_resets_done.next = core_reset_pulse_done;
  assign hwif_in.REFERENCE_COUNTER.rc.next = ref_count_sync;

  // SMC_ATTRIBUTES.num_mailboxes is defined as 6 bits in the register header, so we need to cast to 6 bits for LHS = RHS
  assign hwif_in.SMC_ATTRIBUTES.num_mailboxes.next = 6'(smc_pkg::NUM_MAILBOXES);
  // SMC_ATTRIBUTES.mailbox_depth is defined as 4 bits in the register header, so we need to cast to 4 bits for LHS = RHS
  assign hwif_in.SMC_ATTRIBUTES.mailbox_depth.next = 4'(smc_pkg::MAILBOX_DEPTH);
  // SMC_ATTRIBUTES.num_cores is defined as 3 bits in the register header, so we need to cast to 3 bits for LHS = RHS
  assign hwif_in.SMC_ATTRIBUTES.num_cores.next     = 3'(NUM_CPU_CORES);
  // Report whether output remap is disabled
  assign hwif_in.SMC_ATTRIBUTES.no_output_remap.next = NO_ADDR_REMAP;
  // SMC_ATTRIBUTES.sram_size is defined as 6 bits in the register header, so we need to cast to 6 bits
  assign hwif_in.SMC_ATTRIBUTES.sram_size.next = chipyard_4core_mem_pkg::SRAM_SIZE;
  assign hwif_in.SMC_ATTRIBUTES.num_ext_interrupts.next = smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS;
  assign hwif_in.SMC_ATTRIBUTES.num_cpu_interrupts.next = smc_4core_cpu_pkg::NUM_CPU_INTERRUPTS;
  assign hwif_in.SMC_ATTRIBUTES.chiplet_is_primary.next = chiplet_is_primary_i;

  assign hwif_in.TEST_CTRL.data.next = test_ctrl;

  for (genvar i = 0; i < NUM_PC_REGS; i++) begin : gen_wb_pc
    assign hwif_in.WB_PC_CORE0[i].pc.next = int_wb_reg_pc_sr[0][i];
    assign hwif_in.WB_PC_CORE1[i].pc.next = int_wb_reg_pc_sr[1][i];
    assign hwif_in.WB_PC_CORE2[i].pc.next = int_wb_reg_pc_sr[2][i];
    assign hwif_in.WB_PC_CORE3[i].pc.next = int_wb_reg_pc_sr[3][i];
  end

  for (genvar i = 0; i < 4; i++) begin : gen_mutex
    assign hwif_in.MUTEX[i].mutex.next = mutex[i];
    assign mutex_wr_swacc[i] = hwif_out.MUTEX[i].mutex.wr_swacc;
    assign mutex_rd_swacc[i] = hwif_out.MUTEX[i].mutex.rd_swacc;
  end

  for (genvar i = 0; i < MaxCPUCores; i++) begin : gen_reset_vector
    if (i < NUM_CPU_CORES) begin : gen_used_reset_vector
      assign int_core_reset_vector[i] = hwif_out.RESET_VECTOR[i].vector.value;
    end else begin : gen_unused_reset_vector
      assign int_core_reset_vector[i] = 56'h0;
    end
  end

  assign pre_reset_pulse_wait = hwif_out.CORE_RESET_PULSE_COUNT.pre_reset_count.value;
  assign post_reset_pulse_wait = hwif_out.CORE_RESET_PULSE_COUNT.post_reset_count.value;


  assign ref_count_from_reg = hwif_out.REFERENCE_COUNTER.rc.value;
  assign ref_count_wr_swacc = hwif_out.REFERENCE_COUNTER.rc.wr_swacc;

  assign max_count = hwif_out.WDT_TIMEOUT.data.value;

  assign count_reset[0] = hwif_out.WDT_TIMEOUT_RESET.reset_cycle_count_0.value;
  assign count_reset[1] = hwif_out.WDT_TIMEOUT_RESET.reset_cycle_count_1.value;
  assign count_reset[2] = hwif_out.WDT_TIMEOUT_RESET.reset_cycle_count_2.value;
  assign count_reset[3] = hwif_out.WDT_TIMEOUT_RESET.reset_cycle_count_3.value;

  assign external_wr_data = hwif_out.RESET_CTRL.wr_data;
  assign external_wr_bit_mask = hwif_out.RESET_CTRL.wr_biten;

  assign reset_ctrl_wr_en = hwif_out.RESET_CTRL.req && hwif_out.RESET_CTRL.req_is_wr;
  assign hwif_in.RESET_CTRL.wr_ack = reset_ctrl_wr_en;
  assign hwif_in.RESET_CTRL.rd_ack = hwif_out.RESET_CTRL.req && !hwif_out.RESET_CTRL.req_is_wr;
  assign hwif_in.RESET_CTRL.rd_data = reset_ctrl_rd_data;

  for (genvar i = 0; i < 4; i++) begin : gen_sema
    assign sema_wr_en[i] = hwif_out.SEMA[i].req && hwif_out.SEMA[i].req_is_wr;
    assign hwif_in.SEMA[i].wr_ack = sema_wr_en[i];
    assign hwif_in.SEMA[i].rd_ack = hwif_out.SEMA[i].req && !hwif_out.SEMA[i].req_is_wr;
    assign hwif_in.SEMA[i].rd_data = {48'h0, sema[i]};
  end

  /////////////////////////
  // Reset Control Logic //
  /////////////////////////

  generate
    for (genvar i = 0; i < MaxCPUCores; i++) begin : gen_pulse
      if (i < NUM_CPU_CORES) begin : gen_pulse_core_resets
        prim_pulse_signal #(
          .COUNT_WIDTH(16),
          .IS_ACTIVE_HIGH(0)
        ) u_pulse_core_reset (
          .clk_i(clk_smc_i),
          .rst_ni(rst_primary_ni),

          .pulse_start_i(core_resets_pulse_start[i]),
          .pre_pulse_wait_i(pre_reset_pulse_wait),
          .post_pulse_wait_i(post_reset_pulse_wait),

          .pulse_in_i(int_core_reset_n[i]),
          .pulse_out_o(core_reset_pulse_out[i]),
          .pulse_done_o(core_reset_pulse_done[i])
        );
      end else begin : gen_tie_off_core_reset_and_done
        assign core_reset_pulse_out[i] = 1'b0;
        assign core_reset_pulse_done[i] = 1'b1;
      end
    end
  endgenerate


  // Software-reset drain handshake: one `withhold` holds off the software reset
  // (level, uncore, pulse) until the cluster reports drained_i.
  logic                     sw_reset_req;
  logic                     withhold;
  logic [NUM_CPU_CORES-1:0] pulse_start_req;
  logic [NUM_CPU_CORES-1:0] pulse_start_pending;

  logic        pending;
  logic        force_apply;
  logic        timeout_fired_q;
  logic        reset_applied;
  logic        reset_timeout;
  logic [15:0] timeout_value;
  logic        timeout_mode;
  logic [15:0] timeout_cnt;

  cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t reset_ctrl_reset_value;
  cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t reset_ctrl_wr_data;
  cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t reset_ctrl_reg_value_n0_scan;

  // Raw 1-cycle pulse-start request from the register write
  always_comb begin
    for (int core = 0; core < NUM_CPU_CORES; core++) begin
      // reset core if register at index "core" written high
      // pulse control starts at bit 4
      pulse_start_req[core] = reset_ctrl_wr_en & external_wr_bit_mask[core+4] & external_wr_data[core+4];
    end
  end

  // Drain request: a held level/uncore reset, a pending pulse start, or a pulse
  // in flight all keep the cluster isolated.
  assign sw_reset_req = ~(&reset_ctrl_reg_value_n0_scan[NUM_CPU_CORES-1:0]) // any core held in reset (register level)
                    | ~reg_uncore_reset_n
                    | (|pulse_start_pending)
                    | ~(&core_reset_pulse_done[NUM_CPU_CORES-1:0]);       // any pulse in flight

  assign isolate_req_o = sw_reset_req;

  assign timeout_value = hwif_out.RESET_TIMEOUT.timeout_value.value;
  assign timeout_mode  = hwif_out.RESET_TIMEOUT.timeout_mode.value;
  assign pending       = sw_reset_req & ~drained_i;
  assign force_apply   = sw_reset_req & timeout_fired_q & timeout_mode;
  assign withhold      = pending & ~force_apply;
  assign reset_applied = sw_reset_req & ~withhold;         // live status
  assign reset_timeout = sw_reset_req & timeout_fired_q;   // status for the active request

  // Flush the cluster AXI isolates when the timeout forces the reset; the
  // isolates latch it and self-clear at de-isolation.
  assign isolate_flush_o = force_apply;

  assign hwif_in.RESET_TIMEOUT.reset_applied.next = reset_applied;
  assign hwif_in.RESET_TIMEOUT.reset_timeout.next = reset_timeout;

  // Unified gate: hold off level, uncore, and the pulse start until drained.
  always_comb begin
    gated_uncore_reset_n = withhold ? 1'b1 : reg_uncore_reset_n;
    for (int core = 0; core < NUM_CPU_CORES; core++) begin
      gated_core_reset_n[core]      = withhold ? 1'b1 : int_core_reset_n[core];
      // The pulse module sees its start only once drained.
      core_resets_pulse_start[core] = pulse_start_pending[core] & ~withhold;
    end
  end

  // Capture each pulse-start strobe until its gated start launches the pulse
  // (a 1-cycle strobe would otherwise be lost while withholding).
  always_ff @(posedge clk_smc_i or negedge rst_primary_ni) begin
    if (~rst_primary_ni) begin
      pulse_start_pending <= '0;
    end else begin
      for (int core = 0; core < NUM_CPU_CORES; core++) begin
        if (pulse_start_req[core]) begin
          pulse_start_pending[core] <= 1'b1;
        end else if (core_resets_pulse_start[core]) begin
          pulse_start_pending[core] <= 1'b0;
        end
      end
    end
  end

  always_ff @(posedge clk_smc_i or negedge rst_primary_ni) begin
    if (~rst_primary_ni) begin
      timeout_cnt     <= 16'd0;
      timeout_fired_q <= 1'b0;
    end else if (~sw_reset_req) begin
      timeout_cnt     <= 16'd0;
      timeout_fired_q <= 1'b0;
    end else if (~pending) begin
      timeout_cnt <= 16'd0;
    end else if ((timeout_value != 16'd0) && ~timeout_fired_q) begin
      if (timeout_cnt >= timeout_value) begin
        timeout_fired_q <= 1'b1;
      end else begin
        timeout_cnt <= timeout_cnt + 16'd1;
      end
    end
  end

  logic [MaxCPUCores-1:0] core_reset_reg_n;

  assign core_reset_reg_n = {
    reset_ctrl_reg_value_n0_scan.core3_reset_n_n0_scan,
    reset_ctrl_reg_value_n0_scan.core2_reset_n_n0_scan,
    reset_ctrl_reg_value_n0_scan.core1_reset_n_n0_scan,
    reset_ctrl_reg_value_n0_scan.core0_reset_n_n0_scan
  };

  for (genvar i = 0; i < MaxCPUCores; i++) begin : gen_core_reset_mux
    prim_rst_mux2_hf_n u_core_reset_mux (
      .rst0_ni (core_reset_pulse_out[i]),
      .rst1_ni (core_reset_reg_n[i]),
      .sel_i   (core_reset_pulse_done[i]),
      .rst_no  (int_core_reset_n[i])
    );
  end

  assign reg_uncore_reset_n  = reset_ctrl_reg_value_n0_scan.uncore_reset_n_n0_scan;
  assign debug_reset_n_o = reset_ctrl_reg_value_n0_scan.debug_reset_n_n0_scan;

  assign reset_ctrl_reset_value = DEFAULT_RESET_SETTINGS;
  // never write the value for the pulse start bits
  assign reset_ctrl_wr_data = {((reset_ctrl_reg_value_n0_scan[$bits(cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t)-1:8] &
                    ~external_wr_bit_mask[$bits(cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t)-1:8]) |
                (external_wr_data[$bits(cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t)-1:8] &
                    external_wr_bit_mask[$bits(cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t)-1:8])),
            4'd0,
            ((reset_ctrl_reg_value_n0_scan[MaxCPUCores-1:0] &
                    ~external_wr_bit_mask[MaxCPUCores-1:0]) |
                (external_wr_data[MaxCPUCores-1:0] &
                    external_wr_bit_mask[MaxCPUCores-1:0]))
        };

  always_ff @(posedge clk_smc_i or negedge rst_primary_ni) begin
    if (~rst_primary_ni) begin
      reset_ctrl_reg_value_n0_scan <= reset_ctrl_reset_value;
    end else begin
      if (reset_ctrl_wr_en) begin
        reset_ctrl_reg_value_n0_scan <= reset_ctrl_wr_data;
      end
    end
  end

  assign reset_ctrl_rd_data = {
    {(64 - $bits(cpu_ctrl_reg_pkg::cpu_ctrl__RESET_CTRL__external__fields__out_t)) {1'b0}},
    reset_ctrl_reg_value_n0_scan
  };

  /////////////////////////////
  // Mutex & Semaphore Logic //
  /////////////////////////////

  // mutex lock
  // - if 1, it means it's available
  // - if 0, it means it's not available
  always_ff @(posedge clk_smc_i) begin
    if (~rst_primary_ni) begin
      for (int i = 0; i < 4; i++) begin
        mutex[i] <= 1'b1;
      end
    end else begin
      for (int i = 0; i < 4; i++) begin
        if (mutex_wr_swacc[i]) begin
          mutex[i] <= 1'b1;
        end else if (mutex_rd_swacc[i]) begin
          mutex[i] <= 1'b0;
        end
      end
    end
  end

  // semaphore
  always_ff @(posedge clk_smc_i) begin
    if (~rst_primary_ni) begin
      for (int i = 0; i < 4; i++) begin
        sema[i] <= 16'd0;
      end
    end else begin
      for (int i = 0; i < 4; i++) begin
        if (sema_wr_en[i]) begin
          sema[i] <= sema[i] + (external_wr_data[15:0] & external_wr_bit_mask[15:0]);
        end
      end
    end
  end

  //////////////////
  // Test Control //
  //////////////////

  // Tied off in RTL. A testbench can deposit onto this signal to hand test control
  // values to firmware, which reads them back through the TEST_CTRL register.
  assign test_ctrl = 32'h0;

endmodule
