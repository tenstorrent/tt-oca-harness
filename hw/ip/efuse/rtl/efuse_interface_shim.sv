// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Turn fuse-command requests into foundry APB accesses for an example fuse-bank model.
//
// Hosts SHIM CSRs on fuse_bank_ctrl_*.
// Sequences fuse_command_req_i onto efuse_model_otp_* APB, waiting the programmed bank init
// time before each command; debug_bus_o exposes shim state.
// The APB macro interface is foundry-specific in real integrations.

`include "ocah_registers.svh"

module efuse_interface_shim
#(
  parameter int unsigned SHADOW_REG_BITS = 24576,  // Fuse array size in bits; declared but not used
                                                   // in this module.
  parameter type addr_t = logic,        // Type of the byte address register for read commands.
  parameter type data_t = logic,        // Data type; declared but not used in this module.
  parameter type efuse_axil_req_t = logic,  // eFuse AXI-Lite request type.
  parameter type efuse_axil_resp_t = logic,  // eFuse AXI-Lite response type.
  parameter type efuse_apb_req_t = logic,  // eFuse APB request type.
  parameter type efuse_apb_resp_t = logic,  // eFuse APB response type.

  parameter type efuse_addr_byte_t = logic,  // Fuse byte-address type.
  parameter type efuse_data_t = logic,  // Fuse data-word type.
  parameter type efuse_word_counter_t = logic,  // Fuse access-length counter type.
  parameter type fuse_command_req_t = logic,  // Fuse-command request type.
  parameter type fuse_command_resp_t = logic,  // Fuse-command response type.

  localparam int unsigned CounterWidth = 32   // Width of the read and write bank init-time
                                              // counters.
) (
  input logic                      clk_i,  // System clock.
  input logic                      rst_ni,  // Active-low asynchronous reset.

  input  efuse_axil_req_t          fuse_bank_ctrl_req_i,  // AXI4-Lite request to the fuse bank
                                                          // control registers; only address bits
                                                          // [2:0] are decoded.
  output efuse_axil_resp_t         fuse_bank_ctrl_resp_o,  // AXI4-Lite response from the fuse bank
                                                           // control registers, which hold the bank
                                                           // init time.

  input  fuse_command_req_t        fuse_command_req_i,  // Filtered fuse command from the interface
                                                        // controller: read, program, or program
                                                        // with read-back.
  output fuse_command_resp_t       fuse_command_resp_o,  // Fuse command response, one valid pulse
                                                         // per word read or per program.

  output efuse_apb_req_t           efuse_model_otp_req_o,  // Registered APB request to the fuse
                                                           // bank model, byte addressed; a program
                                                           // writes one bit with one byte strobe.
  input  efuse_apb_resp_t          efuse_model_otp_resp_i,  // APB response from the fuse bank
                                                            // model.

  output logic [15:0]              debug_bus_o  // Shim status: {3'b0, write counter error, write
                                                // FSM state, 3'b0, read counter error, read FSM
                                                // state}.
);

  localparam fuse_command_resp_t FuseCommandRespDefault = '0;
  localparam fuse_command_req_t FuseCommandReqDefault = '0;
  localparam efuse_apb_req_t EfuseApbReqDefault = '0;
  localparam efuse_apb_resp_t EfuseApbRespDefault = '0;


  efuse_addr_byte_t efuse_addr_byte_address;
  logic [3:0] efuse_write_strob;
  logic [7:0] efuse_write_byte;
  efuse_data_t efuse_write_word;



  ///////////////////////////////////////////////////////////////
  // Fuse Bank Ctrl CSRs - foundry specific timing/config signals
  ///////////////////////////////////////////////////////////////

  efuse_shim_ctrl_reg_pkg::efuse_shim_ctrl__out_t fuse_bank_ctrl_hwif_out;

  efuse_shim_ctrl_reg u_efuse_shim_ctrl_reg (
    .clk    (clk_i),
    .arst_n (rst_ni),

    .s_axil_awready (fuse_bank_ctrl_resp_o.aw_ready),
    .s_axil_awvalid (fuse_bank_ctrl_req_i.aw_valid),
    .s_axil_awaddr (fuse_bank_ctrl_req_i.aw.addr[2:0]),
    .s_axil_awprot (fuse_bank_ctrl_req_i.aw.prot),
    .s_axil_wready (fuse_bank_ctrl_resp_o.w_ready),
    .s_axil_wvalid (fuse_bank_ctrl_req_i.w_valid),
    .s_axil_wdata (fuse_bank_ctrl_req_i.w.data),
    .s_axil_wstrb (fuse_bank_ctrl_req_i.w.strb),
    .s_axil_bready (fuse_bank_ctrl_req_i.b_ready),
    .s_axil_bvalid (fuse_bank_ctrl_resp_o.b_valid),
    .s_axil_bresp (fuse_bank_ctrl_resp_o.b.resp),
    .s_axil_arready (fuse_bank_ctrl_resp_o.ar_ready),
    .s_axil_arvalid (fuse_bank_ctrl_req_i.ar_valid),
    .s_axil_araddr (fuse_bank_ctrl_req_i.ar.addr[2:0]),
    .s_axil_arprot (fuse_bank_ctrl_req_i.ar.prot),
    .s_axil_rready (fuse_bank_ctrl_req_i.r_ready),
    .s_axil_rvalid (fuse_bank_ctrl_resp_o.r_valid),
    .s_axil_rdata (fuse_bank_ctrl_resp_o.r.data),
    .s_axil_rresp (fuse_bank_ctrl_resp_o.r.resp),

    .hwif_out      (fuse_bank_ctrl_hwif_out)
  );

  ////////////////////////////////////////
  // Read Fuse Bank Counter for Init Time
  ////////////////////////////////////////

  // Fuse Bank Ctrl CSRs - foundry specific timing/config signals
  logic [31:0] fuse_bank_init_cycles_r;
  assign fuse_bank_init_cycles_r = fuse_bank_ctrl_hwif_out.EFUSE_BANK_INIT_TIME.init_time.value;

  // Counter control signals for fuse bank init cycles
  logic fuse_bank_init_cycles_count_set_en_r;
  logic fuse_bank_init_cycles_count_commit_en_r;
  logic [31:0] fuse_bank_init_cycles_count_r;
  logic fuse_bank_init_cycles_counter_is_zero_r;
  logic fuse_bank_init_cycles_counter_err_r;

  // Counter for fuse bank init cycles
  prim_count #(
    .Width(CounterWidth),
    .ResetValue(CounterWidth'(32)), // 0x20 = 32
    .EnableAlertTriggerSVA(1'b0)
  ) u_prim_count_r (
    .clk_i                (clk_i),
    .rst_ni               (rst_ni),
    .clr_i                (1'b0),
    .set_i                (fuse_bank_init_cycles_count_set_en_r),    // This sets the primary counter to set_cnt_i
    .set_cnt_i            (fuse_bank_init_cycles_r),
    .incr_en_i            (1'b0),
    .decr_en_i            (1'b1),                                     // Decrement Always
    .step_i               (CounterWidth'(1)),                                     // Step size
    .commit_i             (fuse_bank_init_cycles_count_commit_en_r),  // Counter changes only take effect when `commit_i` is set
    .cnt_o                (fuse_bank_init_cycles_count_r),
    .cnt_after_commit_o   (),
    .err_o                (fuse_bank_init_cycles_counter_err_r)
  );

  assign fuse_bank_init_cycles_counter_is_zero_r = ~|fuse_bank_init_cycles_count_r;


  // State Machine signals
  efuse_word_counter_t outstanding_accesses_read_d, outstanding_accesses_read_q;

  efuse_apb_req_t apb_fuse_bank_req_read, apb_fuse_bank_req_read_flopped;
  efuse_apb_resp_t apb_fuse_bank_resp_r;
  fuse_command_resp_t fuse_command_resp_r;

  addr_t fuse_bank_address_read_q, fuse_bank_address_read_d;  // this type will change

  ///////////////////////
  // READ FUSE BANK FSM
  ///////////////////////

  typedef enum {
    ST_READ_IDLE,
    ST_READ_INIT,
    ST_READ_SETUP,
    ST_READ_ACCESS,
    ST_READ_WAIT,
    ST_READ_FINISH
  } efuse_read_state_e;

  efuse_read_state_e efuse_read_state_d, efuse_read_state_q;

  always_comb begin
    efuse_read_state_d = efuse_read_state_q;
    outstanding_accesses_read_d = outstanding_accesses_read_q;

    fuse_bank_address_read_d = fuse_bank_address_read_q;

    fuse_bank_init_cycles_count_set_en_r = 1'b1;
    fuse_bank_init_cycles_count_commit_en_r = 1'b0;

    fuse_command_resp_r = FuseCommandRespDefault;
    apb_fuse_bank_req_read = EfuseApbReqDefault;

    unique case (efuse_read_state_q)
      ST_READ_IDLE: begin
        if (fuse_command_req_i.valid && fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_READ) begin
          outstanding_accesses_read_d = fuse_command_req_i.access_length_words;
          fuse_bank_init_cycles_count_set_en_r = 1'b0;    // Allow counter to start counting
          fuse_bank_init_cycles_count_commit_en_r = 1'b1;

          fuse_bank_address_read_d = fuse_command_req_i.address >> 3; // >> 3 because we are reading by bytes for this model
          efuse_read_state_d = ST_READ_INIT;
        end
      end
      ST_READ_INIT: begin

        fuse_bank_init_cycles_count_set_en_r = 1'b0;
        fuse_bank_init_cycles_count_commit_en_r = 1'b1;

        if (fuse_bank_init_cycles_counter_is_zero_r) begin
          efuse_read_state_d = ST_READ_SETUP;

          fuse_bank_init_cycles_count_set_en_r = 1'b1;    // Set counter back to the initial value
          fuse_bank_init_cycles_count_commit_en_r = 1'b1; // Commit the counter change
        end
      end
      ST_READ_SETUP: begin

        // Generate bank read command, which is an APB request
        apb_fuse_bank_req_read.psel = 1'b1;
        apb_fuse_bank_req_read.penable = 1'b0;
        apb_fuse_bank_req_read.pwrite = 1'b0;
        apb_fuse_bank_req_read.paddr = fuse_bank_address_read_q;
        apb_fuse_bank_req_read.pwdata = '0;
        apb_fuse_bank_req_read.pstrb = '0;

        efuse_read_state_d = ST_READ_ACCESS;
      end
      ST_READ_ACCESS: begin
        apb_fuse_bank_req_read.psel = 1'b1;
        apb_fuse_bank_req_read.penable = 1'b1; // penable goes high after psel goes high
        apb_fuse_bank_req_read.pwrite = 1'b0;
        apb_fuse_bank_req_read.paddr = fuse_bank_address_read_q;
        apb_fuse_bank_req_read.pwdata = '0;
        apb_fuse_bank_req_read.pstrb = '0;

        outstanding_accesses_read_d = outstanding_accesses_read_q - efuse_word_counter_t'(1); // Decrement the number of outstanding accesses
        efuse_read_state_d = ST_READ_WAIT;
      end
      ST_READ_WAIT: begin
        // Wait for read to complete
        if (apb_fuse_bank_resp_r.pready) begin

          fuse_command_resp_r.data = apb_fuse_bank_resp_r.prdata;
          fuse_command_resp_r.status = apb_fuse_bank_resp_r.pslverr;
          fuse_command_resp_r.valid = 1'b1;

          apb_fuse_bank_req_read.psel = 1'b0;
          apb_fuse_bank_req_read.penable = 1'b0;

          // Check if there are more accesses to complete
          if (outstanding_accesses_read_q == efuse_word_counter_t'(0)) begin
            efuse_read_state_d = ST_READ_FINISH;
          end else begin
            fuse_bank_address_read_d = fuse_bank_address_read_q + 32'h4;
            efuse_read_state_d = ST_READ_SETUP;
          end
        end else begin
          // The values of PADDR, PSEL, PENABLE and PWRITE must remain unchanged while PREADY remains LOW.
          apb_fuse_bank_req_read.psel = 1'b1;
          apb_fuse_bank_req_read.penable = 1'b1;
          apb_fuse_bank_req_read.pwrite = 1'b0;
          apb_fuse_bank_req_read.paddr = fuse_bank_address_read_q;
          apb_fuse_bank_req_read.pwdata = '0;
          apb_fuse_bank_req_read.pstrb = '0;
        end
      end
      ST_READ_FINISH: begin
        efuse_read_state_d = ST_READ_IDLE;
      end
      default: efuse_read_state_d = ST_READ_IDLE;
    endcase
  end

  // Register the read state
  `OCAH_FF(efuse_read_state_q, efuse_read_state_d, ST_READ_IDLE, clk_i, rst_ni)
  `OCAH_FF(outstanding_accesses_read_q, outstanding_accesses_read_d, efuse_word_counter_t'(0),
           clk_i, rst_ni)
  `OCAH_FF(apb_fuse_bank_req_read_flopped, apb_fuse_bank_req_read, EfuseApbReqDefault, clk_i,
           rst_ni)
  `OCAH_FF(fuse_bank_address_read_q, fuse_bank_address_read_d, '0, clk_i, rst_ni)


  //////////////////////////
  // Write Fuse Bank Counter
  //////////////////////////

  // Fuse Bank Ctrl CSRs - foundry specific timing/config signals
  logic [CounterWidth-1:0] fuse_bank_init_cycles_w;
  assign fuse_bank_init_cycles_w = fuse_bank_ctrl_hwif_out.EFUSE_BANK_INIT_TIME.init_time.value;

  // Counter control signals for fuse bank init cycles
  logic fuse_bank_init_cycles_count_set_en_w;
  logic fuse_bank_init_cycles_count_commit_en_w;
  logic [CounterWidth-1:0] fuse_bank_init_cycles_count_w;
  logic fuse_bank_init_cycles_counter_is_zero_w;
  logic fuse_bank_init_cycles_counter_err_w;

  // Counter for fuse bank init cycles
  prim_count #(
    .Width(CounterWidth),
    .ResetValue(CounterWidth'(32)), // 0x20 = 32
    .EnableAlertTriggerSVA(1'b0)
  ) u_prim_count_w (
    .clk_i                (clk_i),
    .rst_ni               (rst_ni),
    .clr_i                (1'b0),
    .set_i                (fuse_bank_init_cycles_count_set_en_w),    // This sets the primary counter to set_cnt_i
    .set_cnt_i            (fuse_bank_init_cycles_w),
    .incr_en_i            (1'b0),
    .decr_en_i            (1'b1),                                    // Decrement Always
    .step_i               (CounterWidth'(1)),                        // Step size
    .commit_i             (fuse_bank_init_cycles_count_commit_en_w), // Counter changes only take effect when `commit_i` is set
    .cnt_o                (fuse_bank_init_cycles_count_w),
    .cnt_after_commit_o   (),
    .err_o                (fuse_bank_init_cycles_counter_err_w)
  );

  assign fuse_bank_init_cycles_counter_is_zero_w = ~|fuse_bank_init_cycles_count_w;

  // Generated macro requests WRITE
  efuse_apb_req_t apb_fuse_bank_req_write, apb_fuse_bank_req_write_flopped;
  efuse_apb_resp_t apb_fuse_bank_resp_w;
  fuse_command_resp_t fuse_command_resp_w;

  // Generated macro requests WRITE READBACK
  efuse_apb_req_t apb_fuse_bank_req_write_readback, apb_fuse_bank_req_write_readback_flopped;
  efuse_apb_resp_t apb_fuse_bank_resp_w_readback;

  // Signal to indicate if we are in the write or readback phase of the write command
  logic
      write_readback_phase_en,
      write_readback_phase_en_flopped; // 1'b1 when we are in the write readback phase, 1'b0 when we are in the write phase



  ///////////////////////
  // WRITE FUSE BANK FSM
  ///////////////////////

  typedef enum {
    ST_WRITE_IDLE,
    ST_WRITE_INIT,
    ST_WRITE_SETUP,
    ST_WRITE_ACCESS,
    ST_WRITE_WAIT,
    ST_WRITE_READ_BACK_SETUP,
    ST_WRITE_READ_BACK_ACCESS,
    ST_WRITE_READ_BACK_WAIT,
    ST_WRITE_FINISH
  } efuse_write_state_e;

  efuse_write_state_e efuse_write_state_d, efuse_write_state_q;

  always_comb begin
    efuse_write_state_d = efuse_write_state_q;
    fuse_bank_init_cycles_count_set_en_w = 1'b1;
    fuse_bank_init_cycles_count_commit_en_w = 1'b0;

    fuse_command_resp_w = FuseCommandRespDefault;
    apb_fuse_bank_req_write = EfuseApbReqDefault;
    apb_fuse_bank_req_write_readback = EfuseApbReqDefault;

    write_readback_phase_en = write_readback_phase_en_flopped;

    unique case (efuse_write_state_q)

      ST_WRITE_IDLE: begin
        if (fuse_command_req_i.valid && (fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_PROGRAM || fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_PROGRAM_READ_BACK)) begin
          fuse_bank_init_cycles_count_set_en_w = 1'b0;    // Allow counter to start counting
          fuse_bank_init_cycles_count_commit_en_w = 1'b1;
          efuse_write_state_d = ST_WRITE_INIT;
        end
      end
      ST_WRITE_INIT: begin
        fuse_bank_init_cycles_count_set_en_w = 1'b0;
        fuse_bank_init_cycles_count_commit_en_w = 1'b1;

        if (fuse_bank_init_cycles_counter_is_zero_w) begin
          efuse_write_state_d = ST_WRITE_SETUP;

          fuse_bank_init_cycles_count_set_en_w = 1'b1;    // Set counter back to the initial value
          fuse_bank_init_cycles_count_commit_en_w = 1'b1; // Commit the counter change
        end
      end
      ST_WRITE_SETUP: begin

        // Generate bank write command, which is an APB request
        apb_fuse_bank_req_write.psel = 1'b1;
        apb_fuse_bank_req_write.penable = 1'b0;
        apb_fuse_bank_req_write.pwrite = 1'b1;
        apb_fuse_bank_req_write.paddr = efuse_addr_byte_address;
        apb_fuse_bank_req_write.pwdata = efuse_write_word;
        apb_fuse_bank_req_write.pstrb = efuse_write_strob;

        efuse_write_state_d = ST_WRITE_ACCESS;
      end
      ST_WRITE_ACCESS: begin
        apb_fuse_bank_req_write.psel = 1'b1;
        apb_fuse_bank_req_write.penable = 1'b1; // penable goes high after psel goes high
        apb_fuse_bank_req_write.pwrite = 1'b1;
        apb_fuse_bank_req_write.paddr = efuse_addr_byte_address;
        apb_fuse_bank_req_write.pwdata = efuse_write_word;
        apb_fuse_bank_req_write.pstrb = efuse_write_strob;

        efuse_write_state_d = ST_WRITE_WAIT;
      end
      ST_WRITE_WAIT: begin
        if (apb_fuse_bank_resp_w.pready) begin

          apb_fuse_bank_req_write.psel = 1'b0;
          apb_fuse_bank_req_write.penable = 1'b0;

          if (fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_PROGRAM_READ_BACK) begin
            // Enable the write readback phase
            write_readback_phase_en = 1'b1;
            efuse_write_state_d = ST_WRITE_READ_BACK_SETUP;
          end else begin
            fuse_command_resp_w.data = '0;
            fuse_command_resp_w.status = apb_fuse_bank_resp_w.pslverr;
            fuse_command_resp_w.valid = 1'b1;
            // Disable the write readback phase, back to write idle
            write_readback_phase_en = 1'b0;
            efuse_write_state_d = ST_WRITE_FINISH;
          end

        end else begin
          apb_fuse_bank_req_write.psel = 1'b1;
          apb_fuse_bank_req_write.penable = 1'b1;
          apb_fuse_bank_req_write.pwrite = 1'b1;
          apb_fuse_bank_req_write.paddr = efuse_addr_byte_address;
          apb_fuse_bank_req_write.pwdata = efuse_write_word;
          apb_fuse_bank_req_write.pstrb = efuse_write_strob;
        end
      end
      // Commence a read sequence to read back the written data if command is write read back
      ST_WRITE_READ_BACK_SETUP: begin

        // Generate bank read command
        apb_fuse_bank_req_write_readback.psel = 1'b1;
        apb_fuse_bank_req_write_readback.penable = 1'b0;
        apb_fuse_bank_req_write_readback.pwrite = 1'b0;
        apb_fuse_bank_req_write_readback.paddr = efuse_addr_byte_address;
        apb_fuse_bank_req_write_readback.pwdata = '0;
        apb_fuse_bank_req_write_readback.pstrb = '0;

        efuse_write_state_d = ST_WRITE_READ_BACK_ACCESS;
      end
      ST_WRITE_READ_BACK_ACCESS: begin
        apb_fuse_bank_req_write_readback.psel = 1'b1;
        apb_fuse_bank_req_write_readback.penable = 1'b1; // penable goes high after psel goes high
        apb_fuse_bank_req_write_readback.pwrite = 1'b0;
        apb_fuse_bank_req_write_readback.paddr = efuse_addr_byte_address;
        apb_fuse_bank_req_write_readback.pwdata = '0;
        apb_fuse_bank_req_write_readback.pstrb = '0;

        efuse_write_state_d = ST_WRITE_READ_BACK_WAIT;
      end
      ST_WRITE_READ_BACK_WAIT: begin
        // Wait for read to complete
        if (apb_fuse_bank_resp_w_readback.pready) begin

          fuse_command_resp_w.data = apb_fuse_bank_resp_w_readback.prdata;

          // Return an error if the read back data doesn't have the bit set or if there is a pslverr
          if (apb_fuse_bank_resp_w_readback.pslverr || ((apb_fuse_bank_resp_w_readback.prdata & efuse_write_word) != efuse_write_word)) begin
            fuse_command_resp_w.status = 1'b1;
          end else begin
            fuse_command_resp_w.status = 1'b0;
          end

          fuse_command_resp_w.valid = 1'b1;

          apb_fuse_bank_req_write_readback.psel = 1'b0;
          apb_fuse_bank_req_write_readback.penable = 1'b0;

          efuse_write_state_d = ST_WRITE_FINISH;

        end else begin
          // The values of PADDR, PSEL, PENABLE and PWRITE must remain unchanged while PREADY remains LOW.
          apb_fuse_bank_req_write_readback.psel = 1'b1;
          apb_fuse_bank_req_write_readback.penable = 1'b1;
          apb_fuse_bank_req_write_readback.pwrite = 1'b0;
          apb_fuse_bank_req_write_readback.paddr = efuse_addr_byte_address;
          apb_fuse_bank_req_write_readback.pwdata = '0;
          apb_fuse_bank_req_write_readback.pstrb = '0;
        end
      end
      // End of write readback sequence

      ST_WRITE_FINISH: begin
        // Clear the write-readback phase set by ST_WRITE_WAIT's
        // PROGRAM_READ_BACK, so the demux routes the next program's
        // write request to the write path.
        write_readback_phase_en = 1'b0;
        efuse_write_state_d = ST_WRITE_IDLE;
      end

      default: efuse_write_state_d = ST_WRITE_IDLE;
    endcase
  end

  // Register the write state
  `OCAH_FF(efuse_write_state_q, efuse_write_state_d, ST_WRITE_IDLE, clk_i, rst_ni)
  `OCAH_FF(apb_fuse_bank_req_write_flopped, apb_fuse_bank_req_write, EfuseApbReqDefault, clk_i,
           rst_ni)
  `OCAH_FF(apb_fuse_bank_req_write_readback_flopped, apb_fuse_bank_req_write_readback,
           EfuseApbReqDefault, clk_i, rst_ni)
  `OCAH_FF(write_readback_phase_en_flopped, write_readback_phase_en, 1'b0, clk_i, rst_ni)

  ///////////////////////////////////////////////////////////////
  // Demux between read and write generated macro requests
  ///////////////////////////////////////////////////////////////

  // Multiplex read and write requests to single fuse model interface
  always_comb begin
    if (fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_READ) begin
      efuse_model_otp_req_o = apb_fuse_bank_req_read_flopped;
      apb_fuse_bank_resp_r = efuse_model_otp_resp_i;

      // Write and write readback responses are not used
      apb_fuse_bank_resp_w = EfuseApbRespDefault;
      apb_fuse_bank_resp_w_readback = EfuseApbRespDefault;

    end else if (fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_PROGRAM || fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_PROGRAM_READ_BACK) begin
      if (write_readback_phase_en_flopped) begin
        // Route the write readback request to the fuse model
        efuse_model_otp_req_o = apb_fuse_bank_req_write_readback_flopped;
        // Route the write readback response back to the command interface
        apb_fuse_bank_resp_w_readback = efuse_model_otp_resp_i;
        // Write response is not used
        apb_fuse_bank_resp_w = EfuseApbRespDefault;

      end else begin
        // Route the write request to the fuse model
        efuse_model_otp_req_o = apb_fuse_bank_req_write_flopped;
        // Route the write response back to the command interface
        apb_fuse_bank_resp_w = efuse_model_otp_resp_i;
        // Write readback response is not used
        apb_fuse_bank_resp_w_readback = EfuseApbRespDefault;

      end

      // Read back response is not used
      apb_fuse_bank_resp_r = EfuseApbRespDefault;

    end else begin
      efuse_model_otp_req_o = EfuseApbReqDefault;
      apb_fuse_bank_resp_r = EfuseApbRespDefault;
      apb_fuse_bank_resp_w = EfuseApbRespDefault;
      apb_fuse_bank_resp_w_readback = EfuseApbRespDefault;
    end
  end

  // Multiplex the command responses back to the command interface
  assign fuse_command_resp_o = (fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_READ)  ? fuse_command_resp_r :
                                 (fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_PROGRAM || fuse_command_req_i.command == efuse_pkg::FUSE_COMMAND_PROGRAM_READ_BACK) ? fuse_command_resp_w :
                                 FuseCommandRespDefault;


  // Calculate APB address for bank, must convert from bit to byte address
  logic [4:0] bit_in_word;
  logic [1:0] byte_in_word;

  always_comb begin
    efuse_addr_byte_address = fuse_command_req_i.address >> 3;

    bit_in_word = fuse_command_req_i.address % 32;

    efuse_write_word = 1 << bit_in_word;

    byte_in_word = fuse_command_req_i.address / 8;
    efuse_write_strob = 4'b0001 << byte_in_word;
  end

  // Debug bus, same layout as the internal shim:
  // {3'b0, write counter err, write FSM state, 3'b0, read counter err, read FSM state}
  assign debug_bus_o = {
    3'b0,
    fuse_bank_init_cycles_counter_err_w,
    4'(efuse_write_state_q),
    3'b0,
    fuse_bank_init_cycles_counter_err_r,
    4'(efuse_read_state_q)
  };

endmodule
