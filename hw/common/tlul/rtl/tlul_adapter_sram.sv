// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Adapt TL-UL device traffic onto an SRAM-like memory port.
//
// Translate Get/Put into req/we/addr/wdata/wmask transactions and track outstanding
// responses. Responses return in request order: a write responds once accepted, a read
// once rvalid_i returns its data, and a rejected request without an SRAM access.
//
// BaseAddr is intentionally omitted so multiple memory maps may be used in an SoC.
// Aliasing can happen if the TL-UL crossbar target size is bigger than the SRAM.
//
// At most one of ENABLE_DATA_INTG_GEN and ENABLE_DATA_INTG_PT may be enabled; there is no legal
// case where both are true. Both may be disabled when a non-security-critical memory has
// no stored integrity and an upstream entity already returns integrity. SRAM_DW must be a
// multiple of the TL width.
//
// The remaining parameters select optional features:
//
// - BYTE_ACCESS enables sub-word writes and results in read-modify-write for integrity
//   regeneration when ENABLE_DATA_INTG_PT is set and ERR_ON_WRITE is clear.
// - ERR_ON_WRITE and ERR_ON_READ automatically error disallowed accesses.
// - CMD_INTG_CHECK enables command and A-channel data integrity checking.
// - ENABLE_RSP_INTG_GEN and ENABLE_DATA_INTG_GEN generate response and data integrity.
// - ENABLE_DATA_INTG_PT passes write data integrity to the SRAM and returns the stored
//   integrity with read data.
// - SEC_FIFO_PTR uses redundant FIFO pointers.
// - ENABLE_READBACK reads back and checks written or read data.
// - DATA_XOR_ADDR removes an address XOR that the memory applied to read data, so a faulted
//   read address shows up as an integrity error; it takes effect only with ENABLE_DATA_INTG_PT.
// - SRAM_BUS_BANK_AW is the SRAM bank address width, used only when DATA_XOR_ADDR is set.

module tlul_adapter_sram
  import tlul_pkg::*;

  `include "prim_assert.sv"
  import prim_mubi_pkg::mubi4_t;
#(
  parameter int SRAM_AW              = 12,  // SRAM word-address width.
  parameter int SRAM_DW              = 32,  // SRAM data width; must be a multiple of TL_DW.
  parameter int OUTSTANDING          = 1,   // Maximum outstanding SRAM transactions.
  parameter int SRAM_BUS_BANK_AW     = 12,  // SRAM bank address width; used when DATA_XOR_ADDR=1.
  parameter bit BYTE_ACCESS          = 1,   // Allow sub-word writes; may RMW if
                                            // ENABLE_DATA_INTG_PT.
  parameter bit ERR_ON_WRITE         = 0,   // Reject writes with a bus error.
  parameter bit ERR_ON_READ          = 0,   // Reject reads with a bus error.
  parameter bit CMD_INTG_CHECK       = 0,   // Check A-channel command and data integrity.
  parameter bit ENABLE_RSP_INTG_GEN  = 0,   // Generate D-channel response integrity.
  parameter bit ENABLE_DATA_INTG_GEN = 0,   // Generate D-channel data integrity.
  parameter bit ENABLE_DATA_INTG_PT  = 0,   // Pass data integrity through to the SRAM port.
  parameter bit SEC_FIFO_PTR         = 0,   // Use redundant pointers in all three FIFOs.
  parameter bit ENABLE_READBACK      = 0,   // Read back and check written or read data.
  parameter bit DATA_XOR_ADDR        = 0,   // XOR read data with the SRAM bank address.
  localparam int WidthMult           = SRAM_DW / top_pkg::TL_DW,  // TL beats packed per SRAM word.
  localparam int IntgWidth           = tlul_pkg::DATA_INTG_WIDTH * WidthMult,  // Integrity bits per SRAM word with PT.
  localparam int DataOutW            = ENABLE_DATA_INTG_PT ? SRAM_DW + IntgWidth : SRAM_DW  // Width of wdata_o, wmask_o and rdata_i.
) (
  input   clk_i,                             // System clock.
  input   rst_ni,                            // Active-low reset.

  input   tl_h2d_t          tl_i,            // TL-UL host-to-device request.
  output  tl_d2h_t          tl_o,            // TL-UL device-to-host response.

  input   mubi4_t en_ifetch_i,               // MuBi4True allows instruction-fetch Gets.

  output logic                  req_o,       // SRAM request valid.
  output mubi4_t                req_type_o,  // A_USER.INSTR_TYPE of the request.
  input                         gnt_i,       // SRAM grant.
  output logic                  we_o,        // SRAM write enable.
  output logic [SRAM_AW-1:0]    addr_o,      // SRAM word address.
  output logic [DataOutW-1:0]   wdata_o,     // SRAM write data (and optional integrity).
  output logic [DataOutW-1:0]   wmask_o,     // SRAM write mask (and optional integrity).
  output logic                  intg_error_o,// Integrity or FIFO pointer error; sticky.
  output logic [RSVD_WIDTH-1:0] user_rsvd_o, // Reserved user bits toward the SRAM side.
  input        [DataOutW-1:0]   rdata_i,     // SRAM read data (and optional integrity).
  input                         rvalid_i,    // SRAM read-data valid.
  input        [1:0]            rerror_i,    // [1] uncorrectable, sets D_ERROR; [0] unused.
  output logic                  compound_txn_in_progress_o,  // RMW write or readback request
                                                             // driven.
  input  mubi4_t                readback_en_i,               // MuBi4 readback enable; needs
                                                             // ENABLE_READBACK.
  output logic                  readback_error_o,            // Readback failure; sticky until
                                                             // reset.
  input  logic                  wr_collision_i,              // SRAM write collision; assertions
                                                             // only.
  input  logic                  write_pending_i              // SRAM write pending; assertions only.
);
  localparam int SramByte = SRAM_DW/8;
  localparam int DataBitWidth = prim_util_pkg::vbits(SramByte);
  localparam int WoffsetWidth = (SramByte == top_pkg::TL_DBW) ? 1 :
                                DataBitWidth - prim_util_pkg::vbits(top_pkg::TL_DBW);

  logic error_det; // Internal protocol error checker
  logic error_internal; // Internal protocol error checker
  logic wr_attr_error;
  logic instr_error;
  logic wr_vld_error;
  logic rd_vld_error;
  logic rsp_fifo_error;
  logic sramreqfifo_error;
  logic reqfifo_error;
  logic intg_error;
  logic tlul_error;
  logic readback_error;
  logic sram_byte_readback_error;

  // readback check
  logic readback_error_q;
  if (ENABLE_READBACK) begin : gen_cmd_readback_check
    assign readback_error = sram_byte_readback_error;
    // permanently latch readback error until reset
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        readback_error_q <= '0;
      end else if (readback_error) begin
        readback_error_q <= 1'b1;
      end
    end
  end else begin : gen_no_readback_check
    logic unused_sram_byte_readback_error;
    assign unused_sram_byte_readback_error = sram_byte_readback_error;
    assign readback_error = '0;
    assign readback_error_q = '0;
  end

  // readback error output is permanent and should be used for alert generation
  // or other downstream effects
  assign readback_error_o = readback_error | readback_error_q;

  // integrity check
  if (CMD_INTG_CHECK) begin : gen_cmd_intg_check
    tlul_cmd_intg_chk u_cmd_intg_chk (
      .tl_i(tl_i),
      .err_o (intg_error)
    );
  end else begin : gen_no_cmd_intg_check
    assign intg_error = '0;
  end

  // permanently latch integrity error until reset
  logic intg_error_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      intg_error_q <= '0;
    end else if (intg_error || rsp_fifo_error || sramreqfifo_error || reqfifo_error) begin
      intg_error_q <= 1'b1;
    end
  end

  // integrity error output is permanent and should be used for alert generation
  // or other downstream effects
  assign intg_error_o = intg_error | rsp_fifo_error | sramreqfifo_error |
      reqfifo_error | intg_error_q;

  // wr_attr_error is true if this is a PUT with an unsupported request size or mask. This is only
  // possible if BYTE_ACCESS is not allowed.
  assign wr_attr_error = (BYTE_ACCESS == 0) &&
                         (tl_i.a_opcode == PutFullData || tl_i.a_opcode == PutPartialData) &&
                         (tl_i.a_mask != '1 || tl_i.a_size != 2'h2);

  // An instruction type transaction is only valid if en_ifetch is enabled
  // If the instruction type is completely invalid, also considered an instruction error
  assign instr_error = prim_mubi_pkg::mubi4_test_invalid(tl_i.a_user.instr_type) |
                       (prim_mubi_pkg::mubi4_test_true_strict(tl_i.a_user.instr_type) &
                        prim_mubi_pkg::mubi4_test_false_loose(en_ifetch_i));

  if (ERR_ON_WRITE == 1) begin : gen_no_writes
    assign wr_vld_error = tl_i.a_opcode != Get;
  end else begin : gen_writes_allowed
    assign wr_vld_error = 1'b0;
  end

  if (ERR_ON_READ == 1) begin: gen_no_reads
    assign rd_vld_error = tl_i.a_opcode == Get;
  end else begin : gen_reads_allowed
    assign rd_vld_error = 1'b0;
  end

  // tlul protocol check
  tlul_err u_err (
    .clk_i,
    .rst_ni,
    .tl_i(tl_i),
    .err_o (tlul_error)
  );

  // error return is transactional and thus does not used the "latched" intg_err signal
  assign error_det = wr_attr_error | wr_vld_error | rd_vld_error | instr_error |
                     tlul_error    | intg_error;

  // from sram_byte to adapter logic
  tl_h2d_t tl_i_int;
  // from adapter logic to sram_byte
  tl_d2h_t tl_o_int;
  // from sram_byte to rsp_gen
  tl_d2h_t tl_out;

  // not all parts of tl_i_int are used
  logic unused_tl_i_int;
  assign unused_tl_i_int = ^tl_i_int;

  tlul_rsp_intg_gen #(
    .ENABLE_RSP_INTG_GEN(ENABLE_RSP_INTG_GEN),
    .ENABLE_DATA_INTG_GEN(ENABLE_DATA_INTG_GEN),
    .RSP_INTG_IN_IS_ZERO(1'b1)
  ) u_rsp_gen (
    .tl_i(tl_out),
    .tl_o
  );

  // byte handling for integrity
  tlul_sram_byte #(
    .ENABLE_INTG(BYTE_ACCESS & ENABLE_DATA_INTG_PT & !ERR_ON_WRITE),
    .OUTSTANDING(OUTSTANDING),
    .ENABLE_READBACK(ENABLE_READBACK)
  ) u_sram_byte (
    .clk_i,
    .rst_ni,
    .tl_i,
    .tl_o(tl_out),
    .tl_sram_o(tl_i_int),
    .tl_sram_i(tl_o_int),
    .error_i(error_det),
    .error_o(error_internal),
    .alert_o(sram_byte_readback_error),
    .compound_txn_in_progress_o,
    .readback_en_i,
    .wr_collision_i,
    .write_pending_i
  );

  typedef struct packed {
    logic [top_pkg::TL_DBW-1:0] mask ; // Byte mask within the TL-UL word
    logic [WoffsetWidth-1:0]    woffset ; // Offset of the TL-UL word within the SRAM word
  } sram_req_t ;

  typedef struct packed {
    logic [SRAM_BUS_BANK_AW-1:0] addr; // Address of the request going to the memory.
  } sram_req_addr_t ;

  typedef struct packed {
    logic                       is_read ;
    logic                       error ;
    prim_mubi_pkg::mubi4_t      instr_type;
    logic [top_pkg::TL_SZW-1:0] size ;
    logic [top_pkg::TL_AIW-1:0] source ;
  } req_t ;

  typedef struct packed {
    logic [top_pkg::TL_DW-1:0]  data ;
    logic [DATA_INTG_WIDTH-1:0] data_intg ;
    logic                       error ;
  } rsp_t ;

  localparam int SramReqWidth = $bits(sram_req_t);
  localparam int SramReqFifoWidth = SramReqWidth + (DATA_XOR_ADDR ? SRAM_BUS_BANK_AW : 0);
  localparam int ReqFifoWidth = $bits(req_t) ;
  localparam int RspFifoWidth = $bits(rsp_t) ;

  // FIFO signal in case OutStand is greater than 1
  // If request is latched, {write, source} is pushed to req fifo.
  // Req fifo is popped when D channel is acknowledged (v & r)
  // D channel valid is asserted if it is write request or rsp fifo not empty if read.
  logic reqfifo_wvalid, reqfifo_wready;
  logic reqfifo_rvalid, reqfifo_rready;
  req_t reqfifo_wdata,  reqfifo_rdata;

  logic sramreqfifo_wvalid, sramreqfifo_wready;
  logic sramreqfifo_rready;

  // An item in u_sramreqfifo is the request itself, together (if DATA_XOR_ADDR is nonzero) with
  // some bits of the request address. These values are in sram_req_*data and sram_addr_*data, which
  // get combined to fifo items in sramreqfifo_*data.
  sram_req_t                   sram_req_wdata, sram_req_rdata;
  logic [SRAM_BUS_BANK_AW-1:0] sram_addr_wdata, sram_addr_rdata;
  logic [SramReqFifoWidth-1:0] sramreqfifo_wdata, sramreqfifo_rdata;

  if (DATA_XOR_ADDR) begin : gen_combine_with_addr
    assign sramreqfifo_wdata = {sram_addr_wdata, sram_req_wdata};
    assign {sram_addr_rdata, sram_req_rdata} = sramreqfifo_rdata;
  end else begin : gen_combine_without_addr
    assign sramreqfifo_wdata = sram_req_wdata;
    assign sram_addr_rdata = '0;
    assign sram_req_rdata = sramreqfifo_rdata;
  end

  logic rspfifo_wvalid, rspfifo_wready;
  logic rspfifo_rvalid, rspfifo_rready;
  rsp_t rspfifo_wdata,  rspfifo_rdata;

  logic a_ack, d_ack, sram_ack;
  assign a_ack    = tl_i_int.a_valid & tl_o_int.a_ready ;
  assign d_ack    = tl_o_int.d_valid & tl_i_int.d_ready ;
  assign sram_ack = req_o        & gnt_i ;

  // Valid handling
  logic d_valid, d_error;
  always_comb begin
    d_valid = 1'b0;

    if (reqfifo_rvalid) begin
      if (reqfifo_rdata.error) begin
        // Return error response. Assume no request went out to SRAM
        d_valid = 1'b1;
      end else if (reqfifo_rdata.is_read) begin
        d_valid = rspfifo_rvalid;
      end else begin
        // Write without error
        d_valid = 1'b1;
      end
    end else begin
      d_valid = 1'b0;
    end
  end


  always_comb begin
    d_error = 1'b0;

    if (reqfifo_rvalid) begin
      if (reqfifo_rdata.is_read) begin
        d_error = rspfifo_rdata.error | reqfifo_rdata.error;
      end else begin
        d_error = reqfifo_rdata.error;
      end
    end else begin
      d_error = 1'b0;
    end
  end

  logic vld_rd_rsp;
  assign vld_rd_rsp = d_valid & rspfifo_rvalid & reqfifo_rdata.is_read;
  // If the response data is not valid, we set it to an illegal blanking value which is determined
  // by whether the current transaction is an instruction fetch or a regular read operation.
  logic [top_pkg::TL_DW-1:0] error_blanking_data;
  assign error_blanking_data = (prim_mubi_pkg::mubi4_test_true_strict(reqfifo_rdata.instr_type)) ?
                                 DATA_WHEN_INSTR_ERROR :
                                 DATA_WHEN_ERROR;

  // Since DATA_WHEN_INSTR_ERROR and DATA_WHEN_ERROR can be arbitrary parameters
  // we statically calculate the correct integrity values for these parameters here so that
  // they do not have to be supplied externally.
  logic [top_pkg::TL_DW-1:0] unused_instr, unused_data;
  logic [DATA_INTG_WIDTH-1:0] error_instr_integ, error_data_integ;
  tlul_data_integ_enc u_tlul_data_integ_enc_instr (
    .data_i(DATA_MAX_WIDTH'(DATA_WHEN_INSTR_ERROR)),
    .data_intg_o({error_instr_integ, unused_instr})
  );
  tlul_data_integ_enc u_tlul_data_integ_enc_data (
    .data_i(DATA_MAX_WIDTH'(DATA_WHEN_ERROR)),
    .data_intg_o({error_data_integ, unused_data})
  );

  logic [DATA_INTG_WIDTH-1:0] error_blanking_integ;
  assign error_blanking_integ = (prim_mubi_pkg::mubi4_test_true_strict(reqfifo_rdata.instr_type)) ?
                                 error_instr_integ :
                                 error_data_integ;

  logic [top_pkg::TL_DW-1:0] d_data;
  assign d_data = (vld_rd_rsp & ~d_error) ? rspfifo_rdata.data   // valid read
                                          : error_blanking_data; // write or TL-UL error

  // If this a write response with data fields set to 0, we have to set all ECC bits correctly
  // since we are using an inverted Hsiao code.
  logic [DATA_INTG_WIDTH-1:0] data_intg;
  assign data_intg = (reqfifo_rdata.error) ? error_blanking_integ    : // TL-UL error
                     (vld_rd_rsp)          ? rspfifo_rdata.data_intg : // valid read
                     prim_secded_pkg::SecdedInv3932ZeroEcc;            // valid write

  // When an error is seen on an incoming transaction it gets an immediate response without
  // performing an SRAM request. It may be the transaction receives a ready the first cycle it is
  // seen, but if not we force a ready the following cycle. This avoids factoring the error
  // calculation into the outgoing ready preventing a feedthrough path from the incoming tilelink
  // signals to the outgoing tilelink signals.
  logic missed_err_gnt_d, missed_err_gnt_q;

  // Track whether we've seen an incoming transaction with an error that didn't get a ready
  assign missed_err_gnt_d = error_internal & tl_i_int.a_valid & ~tl_o_int.a_ready;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      missed_err_gnt_q <= 1'b0;
    end else begin
      missed_err_gnt_q <= missed_err_gnt_d;
    end
  end

  assign tl_o_int = '{
      d_valid  : d_valid ,
      d_opcode : (d_valid && !reqfifo_rdata.is_read) ? AccessAck : AccessAckData,
      d_param  : '0,
      d_size   : (d_valid) ? reqfifo_rdata.size : '0,
      d_source : (d_valid) ? reqfifo_rdata.source : '0,
      d_sink   : 1'b0,
      d_data   : d_data,
      d_user   : '{default: '0, data_intg: data_intg},
      d_error  : d_valid && d_error,
      a_ready  : (gnt_i | missed_err_gnt_q) & reqfifo_wready & sramreqfifo_wready
  };

  // a_ready depends on the FIFO full condition and grant from SRAM (or SRAM arbiter)
  // assemble response, including read response, write response, and error for unsupported stuff

  // Output to SRAM:
  //    Generate request only when no internal error occurs. If error occurs, the request should be
  //    dropped and returned error response to the host. So, error to be pushed to reqfifo.
  //    In this case, it is assumed the request is granted (may cause ordering issue later?)
  assign req_o       = tl_i_int.a_valid & reqfifo_wready & ~error_internal;
  assign req_type_o  = tl_i_int.a_user.instr_type;
  assign we_o        = tl_i_int.a_valid & (tl_i_int.a_opcode inside {PutFullData, PutPartialData});
  assign addr_o      = (tl_i_int.a_valid) ? tl_i_int.a_address[DataBitWidth+:SRAM_AW] : '0;
  assign user_rsvd_o = (tl_i_int.a_valid) ? tl_i_int.a_user.rsvd : '0;

  // Support SRAMs wider than the TL-UL word width by mapping the parts of the
  // TL-UL address which are more fine-granular than the SRAM width to the
  // SRAM write mask.
  logic [WoffsetWidth-1:0] woffset;
  if (top_pkg::TL_DW != SRAM_DW) begin : gen_wordwidthadapt
    assign woffset = tl_i_int.a_address[DataBitWidth-1:prim_util_pkg::vbits(top_pkg::TL_DBW)];
  end else begin : gen_no_wordwidthadapt
    assign woffset = '0;
  end

  // The size of the data/wmask depends on whether passthrough integrity is enabled.
  // If passthrough integrity is enabled, the data is concatenated with the integrity passed through
  // the user bits.  Otherwise, it is the data only.
  localparam int DataWidth = ENABLE_DATA_INTG_PT ? top_pkg::TL_DW + DATA_INTG_WIDTH :
                                                   top_pkg::TL_DW;

  // Final combined wmask / wdata
  logic [WidthMult-1:0][DataWidth-1:0] wmask_combined;
  logic [WidthMult-1:0][DataWidth-1:0] wdata_combined;

  // Original tlul portion
  logic [WidthMult-1:0][top_pkg::TL_DW-1:0] wmask_int;
  logic [WidthMult-1:0][top_pkg::TL_DW-1:0] wdata_int;

  // Integrity portion
  logic [WidthMult-1:0][DATA_INTG_WIDTH-1:0] wmask_intg;
  logic [WidthMult-1:0][DATA_INTG_WIDTH-1:0] wdata_intg;

  always_comb begin
    wmask_int = '0;
    wdata_int = '0;

    if (tl_i_int.a_valid) begin
      for (int i = 0 ; i < top_pkg::TL_DW/8 ; i++) begin
        wmask_int[woffset][8*i +: 8] = {8{tl_i_int.a_mask[i]}};
        wdata_int[woffset][8*i +: 8] = (tl_i_int.a_mask[i] && we_o) ? tl_i_int.a_data[8*i+:8] : '0;
      end
    end
  end

  always_comb begin
    wmask_intg  = '0;
    wdata_intg  = '0;

    if (tl_i_int.a_valid) begin
      wmask_intg[woffset] = {DATA_INTG_WIDTH{1'b1}};
      wdata_intg[woffset] = tl_i_int.a_user.data_intg;
    end
  end

  for (genvar i = 0; i < WidthMult; i++) begin : gen_write_output
    if (ENABLE_DATA_INTG_PT) begin : gen_combined_output
      assign wmask_combined[i] = {wmask_intg[i], wmask_int[i]};
      assign wdata_combined[i] = {wdata_intg[i], wdata_int[i]};
    end else begin : gen_ft_output
      logic unused_w;
      assign wmask_combined[i] = wmask_int[i];
      assign wdata_combined[i] = wdata_int[i];
      assign unused_w = |wmask_intg & |wdata_intg;
    end
  end

  assign wmask_o = wmask_combined;
  assign wdata_o = wdata_combined;

  assign reqfifo_wvalid = a_ack ; // Push to FIFO only when granted
  assign reqfifo_wdata  = '{
    is_read: tl_i_int.a_opcode == Get,
    error:  error_internal,
    instr_type: tl_i_int.a_user.instr_type,
    size:   tl_i_int.a_size,
    source: tl_i_int.a_source
  }; // Store the request only. Doesn't have to store data
  assign reqfifo_rready = d_ack ;

  // push together with ReqFIFO, pop upon returning read
  assign sram_req_wdata = '{
    mask    : tl_i_int.a_mask,
    woffset : woffset
  };
  assign sramreqfifo_wvalid = sram_ack & ~we_o;
  assign sramreqfifo_rready = rspfifo_wvalid;

  assign rspfifo_wvalid = rvalid_i & reqfifo_rvalid;

  assign sram_addr_wdata = tl_i_int.a_address[DataBitWidth+:SRAM_BUS_BANK_AW];

  // Make sure only requested bytes are forwarded
  logic [WidthMult-1:0][DataWidth-1:0] rdata_reshaped;
  logic [DataWidth-1:0] rdata_tlword;

  // This just changes the array format so that the correct word can be selected by indexing.
  assign rdata_reshaped = rdata_i;

  if (ENABLE_DATA_INTG_PT) begin : gen_no_rmask
    always_comb begin
      // If the read mask is set to zero, all read data is zeroed out by the mask.
      // We have to set the ECC bits accordingly since we are using an inverted Hsiao code.
      rdata_tlword = prim_secded_pkg::SecdedInv3932ZeroWord;
      // Otherwise, if at least one mask bit is nonzero, we are passing through the integrity.
      // In that case we need to feed back the entire word since otherwise the integrity
      // will not calculate correctly.
      if (|sram_req_rdata.mask) begin
        // Select correct word.
        if (DATA_XOR_ADDR) begin : gen_data_xor_addr
          // When DATA_XOR_ADDR is enabled, on a read, the address is XORed with the data fetched
          // from the memory in the underlying memory controller (e.g., flash controller). At this
          // point, the address is again removed. If the address in the read transaction has been
          // modified, e.g., due to a fault, rdata now contains faulty data, which is detected by
          // the integrity mechanism.
          rdata_tlword = {
              rdata_reshaped[sram_req_rdata.woffset][DataWidth-1:top_pkg::TL_DW],
              rdata_reshaped[sram_req_rdata.woffset][top_pkg::TL_DW-1:0] ^
                  {{(top_pkg::TL_DW-SRAM_BUS_BANK_AW){1'b0}}, sram_addr_rdata}
          };
        end else begin: gen_no_data_xor_addr
          rdata_tlword = rdata_reshaped[sram_req_rdata.woffset];
        end
      end
    end
  end else begin : gen_rmask
    logic [DataWidth-1:0] rmask;
    always_comb begin
      rmask = '0;
      for (int i = 0 ; i < top_pkg::TL_DW/8 ; i++) begin
        rmask[8*i +: 8] = {8{sram_req_rdata.mask[i]}};
      end
    end
    // Select correct word and mask it.
    assign rdata_tlword = rdata_reshaped[sram_req_rdata.woffset] & rmask;
  end

  assign rspfifo_wdata  = '{
    data      : rdata_tlword[top_pkg::TL_DW-1:0],
    data_intg : ENABLE_DATA_INTG_PT ? rdata_tlword[DataWidth-1 -: DATA_INTG_WIDTH] : '0,
    error     : rerror_i[1] // Only care for Uncorrectable error
  };
  assign rspfifo_rready = reqfifo_rdata.is_read & ~reqfifo_rdata.error & reqfifo_rready;

  // This module only cares about uncorrectable errors.
  logic unused_rerror;
  assign unused_rerror = rerror_i[0];

  // FIFO instance: REQ, RSP

  // ReqFIFO is to store the Access type to match to the Response data.
  //    For instance, SRAM accepts the write request but doesn't return the
  //    acknowledge. In this case, it may be hard to determine when the D
  //    response for the write data should send out if reads/writes are
  //    interleaved. So, to make it in-order (even TL-UL allows out-of-order
  //    responses), storing the request is necessary. And if the read entry
  //    is write op, it is safe to return the response right away. If it is
  //    read request, then D response is waiting until read data arrives.
  prim_fifo_sync #(
    .Width       (ReqFifoWidth),
    .Pass        (1'b0),
    .Depth       (OUTSTANDING),
    .NeverClears (1'b1),
    .Secure      (SEC_FIFO_PTR)
  ) u_reqfifo (
    .clk_i,
    .rst_ni,
    .clr_i   (1'b0),
    .wvalid_i(reqfifo_wvalid),
    .wready_o(reqfifo_wready),
    .wdata_i (reqfifo_wdata),
    .rvalid_o(reqfifo_rvalid),
    .rready_i(reqfifo_rready),
    .rdata_o (reqfifo_rdata),
    .full_o  (),
    .depth_o (),
    .err_o   (reqfifo_error)
  );

  // sramreqfifo:
  //    While the ReqFIFO holds the request until it is sent back via TL-UL, the
  //    sramreqfifo only needs to hold the mask and word offset until the read
  //    data returns from memory.
  prim_fifo_sync #(
    .Width             (SramReqFifoWidth),
    .Pass              (1'b0),
    .Depth             (OUTSTANDING),
    .NeverClears       (1'b1),
    .Secure            (SEC_FIFO_PTR),
    .OutputZeroIfEmpty (1)
  ) u_sramreqfifo (
    .clk_i,
    .rst_ni,
    .clr_i   (1'b0),
    .wvalid_i(sramreqfifo_wvalid),
    .wready_o(sramreqfifo_wready),
    .wdata_i (sramreqfifo_wdata),
    .rvalid_o(),
    .rready_i(sramreqfifo_rready),
    .rdata_o (sramreqfifo_rdata),
    .full_o  (),
    .depth_o (),
    .err_o   (sramreqfifo_error)
  );

  if (!DATA_XOR_ADDR) begin : gen_no_data_xor_addr_fifo
    // If u_sramreqfifo doesn't contain any address data, nothing will be reading sram_addr_wdata or
    // sram_addr_rdata. Tie them off with an unused signal.
    logic unused_sram_addresses;
    assign unused_sram_addresses = ^{sram_addr_wdata, sram_addr_rdata};
  end

  // Rationale having #OUTSTANDING depth in response FIFO.
  //    In normal case, if the host or the crossbar accepts the response data,
  //    response FIFO isn't needed. But if in any case it has a chance to be
  //    back pressured, the response FIFO should store the returned data not to
  //    lose the data from the SRAM interface. Remember, SRAM interface doesn't
  //    have back-pressure signal such as read_ready.
  prim_fifo_sync #(
    .Width       (RspFifoWidth),
    .Pass        (1'b1),
    .Depth       (OUTSTANDING),
    .NeverClears (1'b1),
    .Secure      (SEC_FIFO_PTR)
  ) u_rspfifo (
    .clk_i,
    .rst_ni,
    .clr_i   (1'b0),
    .wvalid_i(rspfifo_wvalid),
    .wready_o(rspfifo_wready),
    .wdata_i (rspfifo_wdata),
    .rvalid_o(rspfifo_rvalid),
    .rready_i(rspfifo_rready),
    .rdata_o (rspfifo_rdata),
    .full_o  (),
    .depth_o (),
    .err_o   (rsp_fifo_error)
  );

  // below assertion fails when SRAM rvalid is asserted even though ReqFifo is empty
  `OCAH_OT_ASSERT(rvalidHighReqFifoEmpty, rvalid_i |-> reqfifo_rvalid)

  // below assertion fails when outstanding value is too small (SRAM rvalid is asserted
  // even though the RspFifo is full)
  `OCAH_OT_ASSERT(rvalidHighWhenRspFifoFull, rvalid_i |-> rspfifo_wready)

  // If both ERR_ON_WRITE and ERR_ON_READ are set, this block is useless
  `OCAH_OT_ASSERT_INIT(adapterNoReadOrWrite, (ERR_ON_WRITE & ERR_ON_READ) == 0)

  `OCAH_OT_ASSERT_INIT(SramDwHasByteGranularity_A, SRAM_DW % 8 == 0)
  `OCAH_OT_ASSERT_INIT(SramDwIsMultipleOfTlulWidth_A, SRAM_DW % top_pkg::TL_DW == 0)

  // These parameter options cannot both be true at the same time
  `OCAH_OT_ASSERT_INIT(DataIntgOptions_A, ~(ENABLE_DATA_INTG_GEN & ENABLE_DATA_INTG_PT))

  // Make sure that outputs are defined (a special case for tl_o is explained separately below)
  `OCAH_OT_ASSERT_KNOWN(ReqOutKnown_A,   req_o  )
  `OCAH_OT_ASSERT_KNOWN(WeOutKnown_A,    we_o   )
  `OCAH_OT_ASSERT_KNOWN(AddrOutKnown_A,  addr_o )
  `OCAH_OT_ASSERT_KNOWN(WdataOutKnown_A, wdata_o)
  `OCAH_OT_ASSERT_KNOWN(WmaskOutKnown_A, wmask_o)

  // We'd like to claim that the payload of the TL output is known, but this isn't necessarily true!
  // This block is just an adapter that converts from an SRAM interface to a TL interface. To make
  // the assertion true, we need to weaken it to say that that tl_o is only X if the SRAM supplied
  // that X.
  //
  // This is a bit tricky to track because SRAM responses get stored in u_rspfifo. Assuming that the
  // FIFO doesn't manufacture X's (an assertion in prim_fifo_sync), the only stage of the path
  // needed in this file is the following:
  `OCAH_OT_ASSERT_KNOWN(TlOutValidKnown_A, tl_o.d_valid)
  `OCAH_OT_ASSERT(TlOutKnownIfFifoKnown_A, !$isunknown(rspfifo_rdata) -> !$isunknown(tl_o))

  // The definition of d_valid leads to the assertion below.
  `OCAH_OT_ASSERT(DValidNeedsReqFifoRValid_A, d_valid -> reqfifo_rvalid)
endmodule
