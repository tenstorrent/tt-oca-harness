// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// DMA buffered log bytes to a UART under AXI-Lite CSR control.
//
// The log region is split into NumLogEntries equal slots. Each non-zero LOG_CTRL LOG_LEN
// requests a transfer from its slot; an arbiter tree serves one entry at a time, and
// LOG_LEN clears when that transfer completes.
// log_fetch_axil reads log words from the slot; log_write_axil writes them to
// LOG_WRITE_ADDR.
// uart_tx_ready_i paces the writes; irq_o signals fetch or write errors; FIFO_DEPTH
// sizes the read-data FIFO.

module log_engine
  import log_engine_pkg::*;
#(
  parameter int unsigned FIFO_DEPTH = 4  // Entries in the read-data FIFO between log fetch and UART
                                         // write.
) (
  input  logic                 clk_i,   // System clock, rising-edge triggered.
  input  logic                 rst_ni,  // Active-low reset. Assert asynchronously; deassert
                                        // synchronously to clk_i. Resets the registers, state
                                        // machines, counters and the FIFO.

  input  csr_axil_req_t        csr_axil_req_i,  // Csr AXI-Lite req (AXI4-Lite Register Interface).
  output csr_axil_resp_t       csr_axil_resp_o,  // Csr AXI-Lite resp.

  output log_fetch_axil_req_t  log_fetch_axil_req_o,  // Log fetch AXI-Lite req (AXI4-Lite Log Fetch
                                                      // Interface).
  input  log_fetch_axil_resp_t log_fetch_axil_resp_i,  // Log fetch AXI-Lite resp.

  output log_write_axil_req_t  log_write_axil_req_o,  // Log write AXI-Lite req (AXI4-Lite Log Write
                                                      // Interface).
  input  log_write_axil_resp_t log_write_axil_resp_i,  // Log write AXI-Lite resp.

  input  logic                 uart_tx_ready_i,  // Uart tx ready, active-high (DMA Interface). The
                                                 // engine writes a log word only while it is high,
                                                 // so the UART TX FIFO never overflows.

  output logic                 irq_o    // Interrupt request, active-high. High while any
                                        // INTR_STATUS bit enabled in INTR_ENABLE is set.
);

  `include "prim_assert.sv"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  // Log Engine configuration
  logic             log_engine_en;
  log_region_size_t log_region_size;
  log_fetch_addr_t  log_region_addr;
  log_write_addr_t  log_write_addr;
  log_len_t         log_lens       [NumLogEntries];   // Used unpacked array to fit structure of
                                                      // u_arbiter_tree.data_i

  // Current log entry
  log_len_t         log_len;
  log_index_t       log_index;
  logic             log_pending;
  logic             log_write_done;
  logic log_fetch_err, log_write_err;
  logic log_fetch_mem_resp_error, log_write_mem_resp_error;

  // RDATA FIFO
  logic rdata_fifo_wr_ready, rdata_fifo_wr_valid;
  logic rdata_fifo_rd_ready, rdata_fifo_rd_valid;
  log_word_t        rdata_fifo_rd_data;


  //////////////////////
  // Arbitation Logic //
  //////////////////////

  logic [NumLogEntries-1:0] log_reqs;

  always_comb begin
    for (int i = 0; i < NumLogEntries; i++) begin
      log_reqs[i] = log_lens[i] != log_len_t'(0);
    end
  end

  logic [NumLogEntries-1:0] arb_gnt;

  prim_arbiter_tree #(
    .N          (NumLogEntries),
    .DW         (LogLenWidth),
    .EnDataPort (1'b1)
  ) u_arbiter_tree (
    .clk_i,
    .rst_ni,
    .req_chk_i  (1'b1),
    .req_i      (log_reqs),
    .data_i     (log_lens),
    .gnt_o      (arb_gnt),
    .idx_o      (log_index),
    .valid_o    (log_pending),
    .data_o     (log_len),
    .ready_i    (log_write_done)
  );

  // Tie off unused signal to satisfy lint
  logic unused_arb_gnt;
  assign unused_arb_gnt = ^arb_gnt;

  /////////////////////
  // Log Fetch Logic //
  /////////////////////

  logic log_fetch_mem_req, log_fetch_mem_req_q, log_fetch_mem_wr_en;
  log_fetch_addr_t log_fetch_mem_addr, log_fetch_mem_addr_q;
  log_fetch_data_t      log_fetch_mem_wr_data;
  log_fetch_strb_t      log_fetch_mem_wr_byte_en;

  logic                 log_fetch_mem_grant;      // ARREADY
  log_fetch_data_t      log_fetch_mem_rd_data;
  logic                 log_fetch_mem_resp_valid; // RVALID

  log_fetch_axil_req_t  log_fetch_axil_req;
  log_fetch_axil_resp_t log_fetch_axil_resp;

  assign log_fetch_axil_req_o = log_fetch_axil_req;
  assign log_fetch_axil_resp = log_fetch_axil_resp_i;

  // add flop stage to cut timing after large combinational path in arb tree
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      log_fetch_mem_req_q <= 1'b0;
      log_fetch_mem_addr_q <= '0;
    end else begin
      log_fetch_mem_req_q <= log_fetch_mem_req;
      log_fetch_mem_addr_q <= log_fetch_mem_addr;
    end
  end

  axi_lite_from_mem #(
    .MemAddrWidth    (LogFetchAddrWidth),
    .AxiAddrWidth    (LogFetchAddrWidth),
    .DataWidth       (LogFetchDataWidth),
    .MaxRequests     (1),
    .AxiProt         (3'h2), // {data access, non-secure, unprivileged}
    .axi_req_t       (log_fetch_axil_req_t),
    .axi_rsp_t       (log_fetch_axil_resp_t)
  ) u_axil_lite_from_log_fetch_fsm (
    .clk_i,
    .rst_ni,

    .mem_req_i       (log_fetch_mem_req_q),
    .mem_addr_i      (log_fetch_mem_addr_q),
    .mem_we_i        (log_fetch_mem_wr_en),
    .mem_wdata_i     (log_fetch_mem_wr_data),
    .mem_be_i        (log_fetch_mem_wr_byte_en),
    .mem_gnt_o       (log_fetch_mem_grant),

    .mem_rsp_valid_o (log_fetch_mem_resp_valid),
    .mem_rsp_rdata_o (log_fetch_mem_rd_data),
    .mem_rsp_error_o (log_fetch_mem_resp_error),

    .axi_req_o       (log_fetch_axil_req),
    .axi_rsp_i       (log_fetch_axil_resp)
  );

  log_region_size_t       supported_log_region_size;
  log_len_t               max_log_len;
  log_len_t               max_transfer_len;
  log_len_t               effective_log_len;
  log_fetch_addr_t        log_word_addr;

  logic log_fetch_done_status, log_fetch_done_status_next;
  log_words_fetched_cnt_t log_words_fetched_cnt, log_words_fetched_cnt_next;
  log_len_t next_log_bytes_fetched;
  log_fetch_fsm_state_e log_fetch_fsm_state, log_fetch_fsm_state_next;

  assign next_log_bytes_fetched =
      log_len_t'(log_words_fetched_cnt + log_words_fetched_cnt_t'(1)) *
      log_len_t'(LogWordSize);

  always_comb begin
    log_fetch_mem_req        = 1'b0;
    log_fetch_mem_wr_en      = 1'b0;                 // No writes
    log_fetch_mem_addr       = log_word_addr;
    log_fetch_mem_wr_data    = log_fetch_data_t'(0); // No writes
    log_fetch_mem_wr_byte_en = log_fetch_strb_t'(0); // No writes
    rdata_fifo_wr_valid = 1'b0;

    log_fetch_done_status_next = log_fetch_done_status;
    log_words_fetched_cnt_next = log_words_fetched_cnt;
    log_fetch_fsm_state_next   = log_fetch_fsm_state;

    if (log_engine_en) begin
      unique case (log_fetch_fsm_state)
        ST_LOG_FETCH_IDLE: begin
          if (log_pending && effective_log_len != log_len_t'(0) && !log_fetch_done_status) begin
            log_fetch_fsm_state_next = ST_LOG_FETCH_REQ;
          end else begin
            if (log_write_done) begin
              log_fetch_done_status_next = 1'b0;
            end

            log_fetch_fsm_state_next = ST_LOG_FETCH_IDLE;
          end
        end
        ST_LOG_FETCH_REQ: begin
          if (rdata_fifo_wr_ready) begin
            log_fetch_mem_wr_en = 1'b0;

            if (log_fetch_mem_grant) begin
              log_fetch_mem_req = 1'b0;
              log_fetch_fsm_state_next = ST_LOG_FETCH_WAIT;
            end else begin
              log_fetch_mem_req = 1'b1;
              log_fetch_fsm_state_next = ST_LOG_FETCH_REQ;
            end
          end else begin
            log_fetch_fsm_state_next = ST_LOG_FETCH_REQ;
          end
        end
        ST_LOG_FETCH_WAIT: begin
          if (log_fetch_mem_resp_valid) begin
            rdata_fifo_wr_valid = 1'b1;

            if (next_log_bytes_fetched >= effective_log_len) begin
              log_fetch_done_status_next = 1'b1;
              log_words_fetched_cnt_next = log_words_fetched_cnt_t'(0);
              log_fetch_fsm_state_next   = ST_LOG_FETCH_IDLE;
            end else begin
              log_words_fetched_cnt_next = log_words_fetched_cnt +
                                                         log_words_fetched_cnt_t'(1);
              log_fetch_fsm_state_next   = ST_LOG_FETCH_REQ;
            end
          end else begin
            log_fetch_fsm_state_next = ST_LOG_FETCH_WAIT;
          end
        end
        default: begin
          log_fetch_done_status_next = 1'b0;
          log_words_fetched_cnt_next = log_words_fetched_cnt_t'(0);
          log_fetch_fsm_state_next   = ST_LOG_FETCH_IDLE;
        end
      endcase
    end else begin
      log_fetch_done_status_next = 1'b0;
      log_words_fetched_cnt_next = log_words_fetched_cnt_t'(0);
      log_fetch_fsm_state_next   = ST_LOG_FETCH_IDLE;
    end
  end

  // Valid programming is at most MaxLogRegionSize and aligned so every
  // slot contains complete fetch beats. The clamp and beat floor make invalid
  // programming safe without allowing a fetch to cross a slot boundary.
  assign supported_log_region_size =
      log_region_size > log_region_size_t'(MaxLogRegionSize) ?
      log_region_size_t'(MaxLogRegionSize) : log_region_size;
  assign max_log_len = log_len_t'(
      supported_log_region_size / log_region_size_t'(NumLogEntries)
  );
  assign max_transfer_len = log_word_floor(max_log_len);
  assign effective_log_len =
      log_len > max_transfer_len ? max_transfer_len : log_len;
  assign log_word_addr =
      log_region_addr +
      log_fetch_addr_t'(max_log_len) * log_fetch_addr_t'(log_index) +
      log_fetch_addr_t'(log_words_fetched_cnt) * log_fetch_addr_t'(LogWordSize);

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      log_fetch_done_status <= 1'b0;
      log_words_fetched_cnt <= log_words_fetched_cnt_t'(0);
      log_fetch_fsm_state   <= ST_LOG_FETCH_IDLE;
    end else begin
      log_fetch_done_status <= log_fetch_done_status_next;
      log_words_fetched_cnt <= log_words_fetched_cnt_next;
      log_fetch_fsm_state   <= log_fetch_fsm_state_next;
    end
  end


  ////////////////
  // RDATA FIFO //
  ////////////////

  prim_fifo_sync #(
    .Width             (LogFetchDataWidth),
    .Pass              (1'b1),
    .Depth             (FIFO_DEPTH),
    .OutputZeroIfEmpty (1'b1),
    .NeverClears       (1'b0),
    .Secure            (1'b0)
  ) u_rdata_fifo (
    .clk_i,
    .rst_ni,
    .clr_i             (!log_engine_en),
    .wvalid_i          (rdata_fifo_wr_valid),
    .wready_o          (rdata_fifo_wr_ready),
    .wdata_i           (log_fetch_mem_rd_data),
    .rvalid_o          (rdata_fifo_rd_valid),
    .rready_i          (rdata_fifo_rd_ready),
    .rdata_o           (rdata_fifo_rd_data),
    .full_o            (/* UNUSED */),
    .depth_o           (/* UNUSED */),
    .err_o             (/* UNUSED */)
  );


  /////////////////////
  // Log Write Logic //
  /////////////////////

  logic log_write_mem_req, log_write_mem_wr_en;
  log_write_addr_t log_write_mem_addr;
  log_write_data_t log_write_mem_wr_data;
  log_write_strb_t log_write_mem_wr_byte_en;

  logic            log_write_mem_grant;      // ARREADY
  log_write_data_t log_write_mem_rd_data;
  logic            log_write_mem_resp_valid; // RVALID

  log_write_axil_req_t  log_write_axil_req;
  log_write_axil_resp_t log_write_axil_resp;

  assign log_write_axil_req_o = log_write_axil_req;
  assign log_write_axil_resp = log_write_axil_resp_i;

  axi_lite_from_mem #(
    .MemAddrWidth    (LogWriteAddrWidth),
    .AxiAddrWidth    (LogWriteAddrWidth),
    .DataWidth       (LogWriteDataWidth),
    .MaxRequests     (1),
    .AxiProt         (3'h2), // {data access, non-secure, unprivileged}
    .axi_req_t       (log_write_axil_req_t),
    .axi_rsp_t       (log_write_axil_resp_t)
  ) u_axi_lite_from_log_write_fsm (
    .clk_i,
    .rst_ni,

    .mem_req_i       (log_write_mem_req),
    .mem_addr_i      (log_write_mem_addr),
    .mem_we_i        (log_write_mem_wr_en),
    .mem_wdata_i     (log_write_mem_wr_data),
    .mem_be_i        (log_write_mem_wr_byte_en),
    .mem_gnt_o       (log_write_mem_grant),

    .mem_rsp_valid_o (log_write_mem_resp_valid),
    .mem_rsp_rdata_o (log_write_mem_rd_data),
    .mem_rsp_error_o (log_write_mem_resp_error),

    .axi_req_o       (log_write_axil_req),
    .axi_rsp_i       (log_write_axil_resp)
  );

  log_word_byte_ptr_t byte_ptr;

  log_bytes_written_cnt_t log_bytes_written_cnt, log_bytes_written_cnt_next;
  log_write_fsm_state_e log_write_fsm_state, log_write_fsm_state_next;

  always_comb begin
    // Log write request
    log_write_mem_req        = 1'b0;
    log_write_mem_wr_en      = 1'b0;
    log_write_mem_addr       = log_write_addr;
    log_write_mem_wr_data    = log_write_data_t'(rdata_fifo_rd_data[byte_ptr]);
    log_write_mem_wr_byte_en = log_write_strb_t'('1);
    // RDATA FIFO control
    rdata_fifo_rd_ready = 1'b0;
    // Status
    log_write_done = 1'b0;

    // Counters
    log_bytes_written_cnt_next = log_bytes_written_cnt;
    // FSM State
    log_write_fsm_state_next = log_write_fsm_state;

    if (log_engine_en) begin
      unique case (log_write_fsm_state)
        ST_LOG_WRITE_IDLE: begin
          if (log_pending && effective_log_len == log_len_t'(0)) begin
            log_write_done = 1'b1;
            log_write_fsm_state_next = ST_LOG_WRITE_IDLE;
          end else if (rdata_fifo_rd_valid) begin
            log_write_fsm_state_next = ST_LOG_WRITE_REQ;
          end else begin
            log_write_fsm_state_next = ST_LOG_WRITE_IDLE;
          end
        end
        ST_LOG_WRITE_REQ: begin
          if (rdata_fifo_rd_valid && uart_tx_ready_i) begin
            log_write_mem_req   = 1'b1;
            log_write_mem_wr_en = 1'b1;

            if (log_write_mem_grant) begin
              log_write_fsm_state_next = ST_LOG_WRITE_WAIT;
            end else begin
              log_write_fsm_state_next = ST_LOG_WRITE_REQ;
            end
          end else begin
            log_write_fsm_state_next = ST_LOG_WRITE_REQ;
          end
        end
        ST_LOG_WRITE_WAIT: begin
          if (log_write_mem_resp_valid) begin
            if (log_bytes_written_cnt == effective_log_len - log_len_t'(1)) begin  // Write done
              rdata_fifo_rd_ready = 1'b1; // Read the last byte
              log_write_done      = 1'b1;

              log_bytes_written_cnt_next = log_bytes_written_cnt_t'(0);
              log_write_fsm_state_next   = ST_LOG_WRITE_IDLE;
            end else begin  // Log write not done
              rdata_fifo_rd_ready =
                                byte_ptr == log_word_byte_ptr_t'(LogWordSize - 1);

              log_bytes_written_cnt_next = log_bytes_written_cnt +
                                                         log_bytes_written_cnt_t'(1);
              log_write_fsm_state_next   = ST_LOG_WRITE_REQ;
            end
          end else begin
            log_write_fsm_state_next = ST_LOG_WRITE_WAIT;
          end
        end
        default: begin
          log_bytes_written_cnt_next = log_bytes_written_cnt_t'(0);
          log_write_fsm_state_next   = ST_LOG_WRITE_IDLE;
        end
      endcase
    end else begin
      log_bytes_written_cnt_next = log_bytes_written_cnt_t'(0);
      log_write_fsm_state_next   = ST_LOG_WRITE_IDLE;
    end
  end

  assign byte_ptr = log_word_byte_ptr_t'(log_bytes_written_cnt);

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      log_bytes_written_cnt <= log_bytes_written_cnt_t'(0);
      log_write_fsm_state   <= ST_LOG_WRITE_IDLE;
    end else begin
      log_bytes_written_cnt <= log_bytes_written_cnt_next;
      log_write_fsm_state   <= log_write_fsm_state_next;
    end
  end


  //////////
  // CSRs //
  //////////

  log_engine_reg_pkg::log_engine__in_t  reg_in;
  log_engine_reg_pkg::log_engine__out_t reg_out;

  log_engine_reg u_log_engine_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (csr_axil_resp_o.aw_ready),
    .s_axil_awvalid (csr_axil_req_i.aw_valid),
    .s_axil_awaddr  (csr_axil_req_i.aw.addr),
    .s_axil_awprot  (csr_axil_req_i.aw.prot),
    .s_axil_wready  (csr_axil_resp_o.w_ready),
    .s_axil_wvalid  (csr_axil_req_i.w_valid),
    .s_axil_wdata   (csr_axil_req_i.w.data),
    .s_axil_wstrb   (csr_axil_req_i.w.strb),
    .s_axil_bready  (csr_axil_req_i.b_ready),
    .s_axil_bvalid  (csr_axil_resp_o.b_valid),
    .s_axil_bresp   (csr_axil_resp_o.b.resp),
    .s_axil_arready (csr_axil_resp_o.ar_ready),
    .s_axil_arvalid (csr_axil_req_i.ar_valid),
    .s_axil_araddr  (csr_axil_req_i.ar.addr),
    .s_axil_arprot  (csr_axil_req_i.ar.prot),
    .s_axil_rready  (csr_axil_req_i.r_ready),
    .s_axil_rvalid  (csr_axil_resp_o.r_valid),
    .s_axil_rdata   (csr_axil_resp_o.r.data),
    .s_axil_rresp   (csr_axil_resp_o.r.resp),

    .hwif_in        (reg_in),
    .hwif_out       (reg_out)
  );

  // CTRL Register
  assign log_engine_en = reg_out.CTRL.EN.value;

  // LOG_REGION_SIZE Register
  assign log_region_size = reg_out.LOG_REGION_SIZE.LOG_REGION_SIZE.value;

  // The fetch fabric carries 56-bit addresses. CSR bits [63:56] are reserved-zero.
  assign log_region_addr = log_fetch_addr_t'({
    reg_out.LOG_REGION_ADDR.LOG_REGION_ADDR_HI.value,
    reg_out.LOG_REGION_ADDR.LOG_REGION_ADDR_LO.value
  });
  assign reg_in.LOG_REGION_ADDR.RESERVED.next = '0;

  // LOG_WRITE_ADDR Register
  assign log_write_addr = reg_out.LOG_WRITE_ADDR.LOG_WRITE_ADDR.value;

  // Interrupt Registers
  assign log_fetch_err = log_fetch_mem_resp_valid && log_fetch_mem_resp_error;
  assign log_write_err = log_write_mem_resp_valid && log_write_mem_resp_error;

  // The status bits latch whether or not the interrupt is enabled
  // Clear only on W1C; INTR_ENABLE masks the output
  assign reg_in.INTR_STATUS.LOG_FETCH_ERR.next =
        log_fetch_err || reg_out.INTR_TEST.LOG_FETCH_ERR.value;
  assign reg_in.INTR_STATUS.LOG_WRITE_ERR.next =
        log_write_err || reg_out.INTR_TEST.LOG_WRITE_ERR.value;

  assign irq_o =
        (reg_out.INTR_STATUS.LOG_FETCH_ERR.value && reg_out.INTR_ENABLE.LOG_FETCH_ERR.value) ||
        (reg_out.INTR_STATUS.LOG_WRITE_ERR.value && reg_out.INTR_ENABLE.LOG_WRITE_ERR.value);

  // LOG_CTRL Registers
  always_comb begin
    for (int i = 0; i < NumLogEntries; i++) begin
      log_lens[i] = reg_out.LOG_CTRL[i].LOG_LEN.value;
      if (log_index == log_index_t'(i)) begin
        reg_in.LOG_CTRL[i].LOG_LEN.hwclr = log_write_done;
      end else begin
        reg_in.LOG_CTRL[i].LOG_LEN.hwclr = 1'b0;
      end
    end
  end


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_INIT(paramCheckNumLogEntries, NumLogEntries > 0)
  `OCAH_OT_ASSERT_INIT(LogLenMaximumRepresentable_A, $bits(log_len_t)
                       == 16 && log_len_t'(MaxLogLen) == 16'h8000)
  `OCAH_OT_ASSERT_INIT(NonAlignedSlotRoundsDown_A, log_word_floor(log_len_t'(LogWordSize + 7)
                       ) == log_len_t'(LogWordSize))
  `OCAH_OT_ASSERT_INIT(LogRegionAlignmentValid_A, LogRegionAlignment == 128)

  `OCAH_OT_ASSERT(SupportedLogRegionWithinMaximum_A,
                  supported_log_region_size <= log_region_size_t'(MaxLogRegionSize))
  `OCAH_OT_ASSERT(
      SupportedLogRegionExactMin_A,
      supported_log_region_size == (log_region_size > log_region_size_t'(MaxLogRegionSize) ? log_region_size_t'(MaxLogRegionSize) : log_region_size))
  `OCAH_OT_ASSERT(
      OversizeLogRegionClamped_A,
      log_region_size > log_region_size_t'(MaxLogRegionSize) |-> supported_log_region_size == log_region_size_t'(MaxLogRegionSize))
  `OCAH_OT_ASSERT(
      MaxLogLenExactFloor_A,
      max_log_len == log_len_t'(supported_log_region_size / log_region_size_t'(NumLogEntries)))
  `OCAH_OT_ASSERT(MaxTransferLenExactFloor_A, max_transfer_len == log_word_floor(max_log_len))
  `OCAH_OT_ASSERT(MaxTransferRemainderBelowBeat_A,
                  max_log_len - max_transfer_len < log_len_t'(LogWordSize))
  `OCAH_OT_ASSERT(
      MisalignedLogRegionRounded_A,
      log_region_size % log_region_size_t'(LogRegionAlignment) != log_region_size_t'(0) |-> max_transfer_len <= max_log_len)
  `OCAH_OT_ASSERT(TransferCapacityBeatAligned_A,
                  max_transfer_len % log_len_t'(LogWordSize) == log_len_t'(0))
  `OCAH_OT_ASSERT(EffectiveLogLenWithinSlot_A, effective_log_len <= max_transfer_len)
  `OCAH_OT_ASSERT(EffectiveLogLenExactMin_A,
                  effective_log_len == (log_len > max_transfer_len ? max_transfer_len : log_len))
  `OCAH_OT_ASSERT(FetchResponseWithinSlot_A,
                  log_fetch_mem_resp_valid |-> next_log_bytes_fetched <= max_transfer_len)
  `OCAH_OT_ASSERT(FetchWordCounterWithinMaximum_A,
                  log_words_fetched_cnt < log_words_fetched_cnt_t'(MaxLogLen / LogWordSize))
  `OCAH_OT_ASSERT_INIT(LogRegionAddrWidth_A, 32 + $bits
                       (reg_out.LOG_REGION_ADDR.LOG_REGION_ADDR_HI.value) == $bits(log_fetch_addr_t
                                                                                      ))

  `OCAH_OT_ASSERT_KNOWN(CsrAxilRespKnownO_A, csr_axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(LogFetchAxilReqKnownO_A, log_fetch_axil_req_o)
  `OCAH_OT_ASSERT_KNOWN(LogWriteAxilReqKnownO_A, log_write_axil_req_o)
  `OCAH_OT_ASSERT_KNOWN(IrqKnownO_A, irq_o)

endmodule
