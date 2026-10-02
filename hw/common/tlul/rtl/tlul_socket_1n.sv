// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Steer one TL-UL host onto N device ports.
//
// Route each A-channel request to tl_d_o[dev_select_i] through optional host and
// per-device FIFOs; dev_select_i travels through the host FIFO with its request. Ports
// that are not selected see a_valid low, blanked a_data and deliberately bad integrity.
// Maximum N is 63.
//
// Stall switching to another device until all outstanding responses from other devices
// have returned: keep a counter of outstanding requests and wait until it is zero before
// switching.
//
// Return an error response from an internal tlul_err_resp when dev_select_i is outside
// 0..N-1. The instantiator may force an error with any illegal select; all ones is
// recommended for visibility. When EXPLICIT_ERRS is set, size dev_select_i as
// $clog2(N+1) bits so value N is always representable and can request that error.
//
// FIFO parameters:
//
// - H_REQ_PASS/H_RSP_PASS and D_REQ_PASS/D_RSP_PASS allow fall-through when the corresponding
//   FIFO is empty.
// - H_REQ_DEPTH/H_RSP_DEPTH and D_REQ_DEPTH/D_RSP_DEPTH set FIFO depths; the D* depths pack one
//   nibble per device.

module tlul_socket_1n #(
  parameter int unsigned  N             = 4,          // Number of device ports (max 63).
  parameter bit           H_REQ_PASS    = 1'b1,       // Host request FIFO fall-through.
  parameter bit           H_RSP_PASS    = 1'b1,       // Host response FIFO fall-through.
  parameter bit [N-1:0]   D_REQ_PASS    = {N{1'b1}},  // Per-device request FIFO fall-through.
  parameter bit [N-1:0]   D_RSP_PASS    = {N{1'b1}},  // Per-device response FIFO fall-through.
  parameter bit [3:0]     H_REQ_DEPTH   = 4'h1,       // Host request FIFO depth.
  parameter bit [3:0]     H_RSP_DEPTH   = 4'h1,       // Host response FIFO depth.
  parameter bit [N*4-1:0] D_REQ_DEPTH   = {N{4'h1}},  // Packed per-device request FIFO depths.
  parameter bit [N*4-1:0] D_RSP_DEPTH   = {N{4'h1}},  // Packed per-device response FIFO depths.
  parameter bit           EXPLICIT_ERRS = 1'b1,       // Widen select so N can request an error.

  localparam int unsigned NWD = $clog2(EXPLICIT_ERRS ? N+1 : N)  // Width of dev_select_i.
) (
  input                     clk_i,         // System clock.
  input                     rst_ni,        // Active-low reset.
  input  tlul_pkg::tl_h2d_t tl_h_i,        // Host-side TL-UL request.
  output tlul_pkg::tl_d2h_t tl_h_o,        // Host-side TL-UL response.
  output tlul_pkg::tl_h2d_t tl_d_o    [N], // Per-device TL-UL requests.
  input  tlul_pkg::tl_d2h_t tl_d_i    [N], // Per-device TL-UL responses.
  input  [NWD-1:0]          dev_select_i   // Device index; N and above return an error.
);
  `include "prim_assert.sv"

  `OCAH_OT_ASSERT_INIT(maxN, N < 64)

  // Since our steering is done after potential FIFOing, we need to
  // shove our device select bits into spare bits of reqfifo

  // instantiate the host fifo, create intermediate bus 't'

  // FIFO'd version of device select
  logic [NWD-1:0] dev_select_t;

  tlul_pkg::tl_h2d_t   tl_t_o;
  tlul_pkg::tl_d2h_t   tl_t_i;

  tlul_fifo_sync #(
    .REQ_PASS(H_REQ_PASS),
    .RSP_PASS(H_RSP_PASS),
    .REQ_DEPTH(H_REQ_DEPTH),
    .RSP_DEPTH(H_RSP_DEPTH),
    .SPARE_REQ_W(NWD)
  ) u_fifo_h (
    .clk_i,
    .rst_ni,
    .tl_h_i,
    .tl_h_o,
    .tl_d_o     (tl_t_o),
    .tl_d_i     (tl_t_i),
    .spare_req_i (dev_select_i),
    .spare_req_o (dev_select_t),
    .spare_rsp_i (1'b0),
    .spare_rsp_o ()
  );


  // We need to keep track of how many requests are outstanding,
  // and to which device. New requests are compared to this and
  // stall until that number is zero.
  localparam int MaxOutstanding = 2 ** top_pkg::TL_AIW;  // Up to 256 outstanding
  localparam int OutstandingW = $clog2(MaxOutstanding + 1);
  logic [OutstandingW-1:0] num_req_outstanding;
  logic [NWD-1:0]          dev_select_outstanding;
  logic                    hold_all_requests;
  logic accept_t_req, accept_t_rsp;

  assign  accept_t_req = tl_t_o.a_valid & tl_t_i.a_ready;
  assign  accept_t_rsp = tl_t_i.d_valid & tl_t_o.d_ready;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      num_req_outstanding <= '0;
      dev_select_outstanding <= '0;
    end else if (accept_t_req) begin
      if (!accept_t_rsp) begin
        num_req_outstanding <= num_req_outstanding + 1'b1;
      end
      dev_select_outstanding <= dev_select_t;
    end else if (accept_t_rsp) begin
      num_req_outstanding <= num_req_outstanding - 1'b1;
    end
  end

  `OCAH_OT_ASSERT(NotOverflowed_A,
                  accept_t_req && !accept_t_rsp -> num_req_outstanding <= MaxOutstanding)

  assign hold_all_requests = (num_req_outstanding != '0) & (dev_select_t != dev_select_outstanding);

  // Make N copies of 't' request side with modified reqvalid, call
  // them 'u[0]' .. 'u[n-1]'.

  tlul_pkg::tl_h2d_t   tl_u_o [N+1];
  tlul_pkg::tl_d2h_t   tl_u_i [N+1];

  // ensure that when a device is not selected, both command
  // data integrity can never match
  tlul_pkg::tl_a_user_t blanked_auser;
  assign blanked_auser = '{
          rsvd: tl_t_o.a_user.rsvd,
          instr_type: tl_t_o.a_user.instr_type,
          cmd_intg: tlul_pkg::get_bad_cmd_intg(tl_t_o),
          data_intg: tlul_pkg::get_bad_data_intg(tlul_pkg::BlankedAData)
      };

  // if a host is not selected, or if requests are held off, blank the bus
  for (genvar i = 0; i < N; i++) begin : gen_u_o
    logic dev_select;
    assign dev_select = dev_select_t == NWD'(i) & ~hold_all_requests;

    assign tl_u_o[i].a_valid   = tl_t_o.a_valid & dev_select;
    assign tl_u_o[i].a_opcode  = tl_t_o.a_opcode;
    assign tl_u_o[i].a_param   = tl_t_o.a_param;
    assign tl_u_o[i].a_size    = tl_t_o.a_size;
    assign tl_u_o[i].a_source  = tl_t_o.a_source;
    assign tl_u_o[i].a_address = tl_t_o.a_address;
    assign tl_u_o[i].a_mask    = tl_t_o.a_mask;
    assign tl_u_o[i].a_data    = dev_select ?
                                 tl_t_o.a_data :
                                 tlul_pkg::BlankedAData;
    assign tl_u_o[i].a_user    = dev_select ?
                                 tl_t_o.a_user :
                                 blanked_auser;

    assign tl_u_o[i].d_ready   = tl_t_o.d_ready;
  end


  tlul_pkg::tl_d2h_t tl_t_p ;

  // for the returning reqready, only look at the device we're addressing
  logic hfifo_reqready;
  always_comb begin
    hfifo_reqready = tl_u_i[N].a_ready;  // default to error
    for (int idx = 0; idx < N; idx++) begin
      //if (dev_select_outstanding == NWD'(idx)) hfifo_reqready = tl_u_i[idx].a_ready;
      if (dev_select_t == NWD'(idx)) hfifo_reqready = tl_u_i[idx].a_ready;
    end
    if (hold_all_requests) hfifo_reqready = 1'b0;
  end
  // Adding a_valid as a qualifier. This prevents the a_ready from having unknown value
  // when the address is unknown and the Host TL-UL FIFO is bypass mode.
  assign tl_t_i.a_ready = tl_t_o.a_valid & hfifo_reqready;

  always_comb begin
    tl_t_p = tl_u_i[N];
    for (int idx = 0; idx < N; idx++) begin
      if (dev_select_outstanding == NWD'(idx)) tl_t_p = tl_u_i[idx];
    end
  end
  assign tl_t_i.d_valid  = tl_t_p.d_valid ;
  assign tl_t_i.d_opcode = tl_t_p.d_opcode;
  assign tl_t_i.d_param  = tl_t_p.d_param ;
  assign tl_t_i.d_size   = tl_t_p.d_size  ;
  assign tl_t_i.d_source = tl_t_p.d_source;
  assign tl_t_i.d_sink   = tl_t_p.d_sink  ;
  assign tl_t_i.d_data   = tl_t_p.d_data  ;
  assign tl_t_i.d_user   = tl_t_p.d_user  ;
  assign tl_t_i.d_error  = tl_t_p.d_error ;

  // Instantiate all the device FIFOs
  for (genvar i = 0; i < N; i++) begin : gen_dfifo
    tlul_fifo_sync #(
      .REQ_PASS(D_REQ_PASS[i]),
      .RSP_PASS(D_RSP_PASS[i]),
      .REQ_DEPTH(D_REQ_DEPTH[i*4+:4]),
      .RSP_DEPTH(D_RSP_DEPTH[i*4+:4])
    ) u_fifo_d (
      .clk_i,
      .rst_ni,
      .tl_h_i      (tl_u_o[i]),
      .tl_h_o      (tl_u_i[i]),
      .tl_d_o      (tl_d_o[i]),
      .tl_d_i      (tl_d_i[i]),
      .spare_req_i (1'b0),
      .spare_req_o (),
      .spare_rsp_i (1'b0),
      .spare_rsp_o ()
    );
  end

  // Instantiate the error responder. It's only needed if a value greater than
  // N-1 is actually representable in NWD bits.
  if ($clog2(N + 1) <= NWD) begin : gen_err_resp
    assign tl_u_o[N].d_ready     = tl_t_o.d_ready;
    assign tl_u_o[N].a_valid     = tl_t_o.a_valid &
                                   (dev_select_t >= NWD'(N)) &
                                   ~hold_all_requests;
    assign tl_u_o[N].a_opcode    = tl_t_o.a_opcode;
    assign tl_u_o[N].a_param     = tl_t_o.a_param;
    assign tl_u_o[N].a_size      = tl_t_o.a_size;
    assign tl_u_o[N].a_source    = tl_t_o.a_source;
    assign tl_u_o[N].a_address   = tl_t_o.a_address;
    assign tl_u_o[N].a_mask      = tl_t_o.a_mask;
    assign tl_u_o[N].a_data      = tl_t_o.a_data;
    assign tl_u_o[N].a_user      = tl_t_o.a_user;
    tlul_err_resp u_err_resp (
      .clk_i,
      .rst_ni,
      .tl_h_i     (tl_u_o[N]),
      .tl_h_o     (tl_u_i[N])
    );
  end else begin : gen_no_err_resp  // block: gen_err_resp
    assign tl_u_o[N] = '0;
    assign tl_u_i[N] = '0;
    logic unused_sig;
    assign unused_sig = ^tl_u_o[N];
  end

endmodule
