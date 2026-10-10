// Copyright (c) 2020 ETH Zurich and University of Bologna.
// Copyright and related rights are licensed under the Solderpad Hardware
// License, Version 0.51 (the "License"); you may not use this file except in
// compliance with the License.  You may obtain a copy of the License at
// http://solderpad.org/licenses/SHL-0.51. Unless required by applicable law
// or agreed to in writing, software, hardware and materials distributed under
// this License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
// CONDITIONS OF ANY KIND, either express or implied. See the License for the
// specific language governing permissions and limitations under the License.
//
// Authors:
// - Wolfgang Roenninger <wroennin@iis.ee.ethz.ch>
// - Andreas Kurth <akurth@iis.ee.ethz.ch>

`include "ocah_registers.svh"

`ifdef QUESTA
// Derive `TARGET_VSIM`, which is used for tool-specific workarounds in this file, from `QUESTA`,
// which is automatically set in Questa.
`define TARGET_VSIM
`endif

// axi_lite_demux: Demultiplex an AXI4-Lite bus from one slave port to multiple master ports.
//                 The selection signal at the AW and AR channel has to follow the same
//                 stability rules as the corresponding AXI4-Lite channel.

module axi5_lite_demux_brcst #(
  parameter type         aw_chan_t      = logic, // AXI4-Lite AW channel
  parameter type         w_chan_t       = logic, // AXI4-Lite  W channel
  parameter type         b_chan_t       = logic, // AXI4-Lite  B channel
  parameter type         ar_chan_t      = logic, // AXI4-Lite AR channel
  parameter type         r_chan_t       = logic, // AXI4-Lite  R channel
  parameter type         axi_req_t      = logic, // AXI4-Lite request struct
  parameter type         axi_resp_t     = logic, // AXI4-Lite response struct
  parameter int unsigned NoMstPorts     = 32'd0, // Number of instantiated ports
  parameter int unsigned MaxTrans       = 32'd0, // Maximum number of open transactions per channel
  parameter bit          FallThrough    = 1'b0,  // FIFOs are in fall through mode
  parameter bit          SpillAw        = 1'b1,  // insert one cycle latency on slave AW
  parameter bit          SpillW         = 1'b0,  // insert one cycle latency on slave  W
  parameter bit          SpillB         = 1'b0,  // insert one cycle latency on slave  B
  parameter bit          SpillAr        = 1'b1,  // insert one cycle latency on slave AR
  parameter bit          SpillR         = 1'b0,  // insert one cycle latency on slave  R
  // Dependent parameters, DO NOT OVERRIDE!
  parameter type         select_t       = logic [$clog2(NoMstPorts)-1:0]
) (
  input  logic                        clk_i,
  input  logic                        rst_ni,
  input  logic                        test_i,
  // slave port (AXI4-Lite input), connect master module here
  input  axi_req_t                    slv_req_i,
  input  select_t                     slv_aw_select_i,
  input  logic                        brcst_wr_req_enable,
  input  select_t                     slv_ar_select_i,
  output axi_resp_t                   slv_resp_o,
  // master ports (AXI4-Lite outputs), connect slave modules here
  output axi_req_t  [NoMstPorts-1:0]  mst_reqs_o,
  input  axi_resp_t [NoMstPorts-1:0]  mst_resps_i
);

// FIXME_NONATHENA -> Clean up the implementation. Current one hard coded to
// 2 broadcast masters
  //--------------------------------------
  // Typedefs for the spill registers
  //--------------------------------------

  typedef logic brcst_t;
  typedef struct packed {
    aw_chan_t aw;
    select_t  select;
    brcst_t brcst_en;
  } aw_chan_select_t;
  typedef struct packed {
    ar_chan_t ar;
    select_t  select;
  } ar_chan_select_t;

  if (NoMstPorts == 32'd1) begin : gen_no_demux
    // degenerate case, connect slave to master port
    spill_register #(
      .T       ( aw_chan_t  ),
      .Bypass  ( ~SpillAw   )
    ) i_aw_spill_reg (
      .clk_i   ( clk_i                    ),
      .rst_ni  ( rst_ni                   ),
      .valid_i ( slv_req_i.aw_valid       ),
      .ready_o ( slv_resp_o.aw_ready      ),
      .data_i  ( slv_req_i.aw             ),
      .valid_o ( mst_reqs_o[0].aw_valid   ),
      .ready_i ( mst_resps_i[0].aw_ready  ),
      .data_o  ( mst_reqs_o[0].aw         )
    );
    spill_register #(
      .T       ( w_chan_t  ),
      .Bypass  ( ~SpillW   )
    ) i_w_spill_reg (
      .clk_i   ( clk_i                   ),
      .rst_ni  ( rst_ni                  ),
      .valid_i ( slv_req_i.w_valid       ),
      .ready_o ( slv_resp_o.w_ready      ),
      .data_i  ( slv_req_i.w             ),
      .valid_o ( mst_reqs_o[0].w_valid   ),
      .ready_i ( mst_resps_i[0].w_ready  ),
      .data_o  ( mst_reqs_o[0].w         )
    );
    spill_register #(
      .T       ( b_chan_t ),
      .Bypass  ( ~SpillB      )
    ) i_b_spill_reg (
      .clk_i   ( clk_i                  ),
      .rst_ni  ( rst_ni                 ),
      .valid_i ( mst_resps_i[0].b_valid ),
      .ready_o ( mst_reqs_o[0].b_ready  ),
      .data_i  ( mst_resps_i[0].b       ),
      .valid_o ( slv_resp_o.b_valid     ),
      .ready_i ( slv_req_i.b_ready      ),
      .data_o  ( slv_resp_o.b           )
    );
    spill_register #(
      .T       ( ar_chan_t  ),
      .Bypass  ( ~SpillAr   )
    ) i_ar_spill_reg (
      .clk_i   ( clk_i                    ),
      .rst_ni  ( rst_ni                   ),
      .valid_i ( slv_req_i.ar_valid       ),
      .ready_o ( slv_resp_o.ar_ready      ),
      .data_i  ( slv_req_i.ar             ),
      .valid_o ( mst_reqs_o[0].ar_valid   ),
      .ready_i ( mst_resps_i[0].ar_ready  ),
      .data_o  ( mst_reqs_o[0].ar         )
    );
    spill_register #(
      .T       ( r_chan_t ),
      .Bypass  ( ~SpillR      )
    ) i_r_spill_reg (
      .clk_i   ( clk_i                  ),
      .rst_ni  ( rst_ni                 ),
      .valid_i ( mst_resps_i[0].r_valid ),
      .ready_o ( mst_reqs_o[0].r_ready  ),
      .data_i  ( mst_resps_i[0].r       ),
      .valid_o ( slv_resp_o.r_valid     ),
      .ready_i ( slv_req_i.r_ready      ),
      .data_o  ( slv_resp_o.r           )
    );

  end else begin : gen_demux
    // normal non degenerate case


    //--------------------------------------
    //--------------------------------------
    // Signal Declarations
    //--------------------------------------
    //--------------------------------------

    //--------------------------------------
    // Write Transaction
    //--------------------------------------
    aw_chan_select_t       slv_aw_chan;
    logic                  slv_aw_valid,    slv_aw_ready;

    logic [NoMstPorts-1:0] mst_aw_valids, mst_aw_readies;

    logic                  w_fifo_push,     w_fifo_pop;
    logic                  w_fifo_full,     w_fifo_empty;

    w_chan_t               slv_w_chan;
    select_t               w_select;
    brcst_t                w_brcst;
    logic                  slv_w_valid,     slv_w_ready;

    logic [NoMstPorts-1:0] mst_w_valids, mst_w_readies;

    // logic                  /*w_pop*/        b_fifo_pop;
    // logic                  b_fifo_full,     b_fifo_empty;

    // B channles input into the arbitration
    b_chan_t [NoMstPorts-1:0] mst_b_chans;
    logic    [NoMstPorts-1:0] mst_b_valids,       mst_b_readies;

    b_chan_t               slv_b_chan;
    select_t               b_select;
    logic                  slv_b_valid,     slv_b_ready;

    //--------------------------------------
    // Read Transaction
    //--------------------------------------
    ar_chan_select_t slv_ar_chan;
    logic            slv_ar_valid,    slv_ar_ready;

    // logic            r_fifo_push,     r_fifo_pop;
    // logic            r_fifo_full,     r_fifo_empty;

    // R channles input into the arbitration
    r_chan_t [NoMstPorts-1:0] mst_r_chans;
    logic    [NoMstPorts-1:0] mst_r_valids,       mst_r_readies;

    r_chan_t         slv_r_chan;
    select_t         r_select;
    logic            slv_r_valid,     slv_r_ready;

    //--------------------------------------
    //--------------------------------------
    // Channel control
    //--------------------------------------
    //--------------------------------------
    
    //--------------------------------------
    // AW Channel
    //--------------------------------------

    typedef enum logic [2:0] {IDLE, REQ, LOCK, BREQ, BLOCK2, BLOCK1} state_e;
    state_e state, n_state;
    `OCAH_FFL(state, n_state, 1'b1, IDLE, clk_i, rst_ni)

    logic locked_idx;

    logic [NoMstPorts-1:0] A_d, A_q, A_en;
    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_A_mask
      `OCAH_FFL(A_q[i], A_d[i], A_en[i], 1'b1, clk_i, rst_ni)
    end

    `ifdef TARGET_VSIM
    // Workaround for bug in Questa 2020.2 and 2021.1: Flatten the struct into a logic vector before
    // instantiating `spill_register`.
    typedef logic [$bits(aw_chan_select_t)-1:0] aw_chan_select_flat_t;
    `else
    // Other tools, such as VCS, have problems with `$bits()`, so the workaround cannot be used
    // generally.
    typedef aw_chan_select_t aw_chan_select_flat_t;
    `endif
    aw_chan_select_flat_t slv_aw_chan_select_in_flat,
                          slv_aw_chan_select_out_flat;
    assign slv_aw_chan_select_in_flat = {slv_req_i.aw, slv_aw_select_i, brcst_t'(brcst_wr_req_enable)};
    spill_register #(
      .T      ( aw_chan_select_flat_t         ),
      .Bypass ( ~SpillAw                      )
    ) i_aw_spill_reg (
      .clk_i   ( clk_i                        ),
      .rst_ni  ( rst_ni                       ),
      .valid_i ( slv_req_i.aw_valid           ),
      .ready_o ( slv_resp_o.aw_ready          ),
      .data_i  ( slv_aw_chan_select_in_flat   ),
      .valid_o ( slv_aw_valid                 ),
      .ready_i ( slv_aw_ready                 ),
      .data_o  ( slv_aw_chan_select_out_flat  )
    );
    assign slv_aw_chan = slv_aw_chan_select_out_flat;

    //State Machine for Broadcast Handshake control with TWO downstream channels
    always_comb begin
        // default assginments
        slv_aw_ready    = 1'b0;
        mst_aw_valids   = '0;
        n_state = state;
        //A_mask
        A_d = A_q;
        A_en = '0;
        //locked channel index
        locked_idx = 1'b0;
        // W FIFO input control
        w_fifo_push     = 1'b0;

        case(state) 
            IDLE: 
            begin 
                // reset A_mask
                A_d = '1;
                A_en = '1;
                if (!w_fifo_full && slv_aw_valid) begin            
                    // new transaction, push select in the FIFO and then look if transaction happened
                    w_fifo_push = 1'b1;
                    if (slv_aw_chan.brcst_en) begin
                        n_state = BREQ;
                    end else begin
                        n_state = REQ;
                    end
                end else begin
                end
            end
            
            REQ: 
            begin
                mst_aw_valids[slv_aw_chan.select] = 1'b1;
                if (mst_aw_readies[slv_aw_chan.select]) begin
                    slv_aw_ready = 1'b1;
                    n_state = IDLE;
                end else begin
                    n_state = LOCK;
                end
            end

            LOCK:
            begin
                mst_aw_valids[slv_aw_chan.select] = 1'b1;
                if (mst_aw_readies[slv_aw_chan.select]) begin
                    slv_aw_ready    = 1'b1;
                    n_state = IDLE;
                end else begin
                end
            end

            BREQ:
            begin
                mst_aw_valids = '1;
                if (&mst_aw_readies[NoMstPorts - 2:0]) begin// : both channels ready
                    slv_aw_ready    = 1'b1;
                    n_state = IDLE;
                end else if (~|mst_aw_readies[NoMstPorts - 2:0]) begin// : both channels not ready
                    n_state = BLOCK2;
                end
                else begin// : one channel ready one not
                    n_state = BLOCK1;
                    for(int i = 0; i < NoMstPorts-1; i++) begin 
                        if (mst_aw_readies[i]) begin : this_channel_ready
                            // apply A_mask pull down valid_o for the ready channel @ next cycle;
                            // Using this A_mask to delay 1 cycle and pull down mst_aw_valids
                            A_d[i] = 1'b0;
                            A_en[i] = 1'b1;
                        end
                    end
                end
            end

            BLOCK2: 
            begin
                mst_aw_valids = '1;
                if (&mst_aw_readies[NoMstPorts - 2:0]) begin// : both channels ready
                    slv_aw_ready    = 1'b1;
                    n_state = IDLE;
                end else if (~|mst_aw_readies[NoMstPorts - 2:0]) begin// : both channels not ready
                    // n_state = BLOCK2;
                end
                else begin// : one channel ready one not
                    n_state = BLOCK1;
                    for(int i = 0; i < NoMstPorts-1; i++) begin 
                        if (mst_aw_readies[i]) begin : this_channel_ready
                            // apply A_mask pull down valid_o for the ready channel @ next cycle;
                            // Using this A_mask to delay 1 cycle and pull down mst_aw_valids
                            A_d[i] = 1'b0;
                            A_en[i] = 1'b1;
                        end
                    end
                end
            end

            BLOCK1:
            begin
                mst_aw_valids = '1;
                for(int i = 0; i < NoMstPorts-1; i++) begin 
                    if (!A_q[i]) begin
                        locked_idx = 1'(1-i);
                    end
                end
                if (mst_aw_readies[locked_idx]) begin
                    slv_aw_ready    = 1'b1;
                    n_state = IDLE;
                end else begin
                    // n_state = BLOCK1;
                end
            end
            
            default: 
            begin 
                n_state = IDLE;
            end
        endcase
    end

    // replicate AW channel to the request output
    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_mst_aw
      assign mst_aw_readies[i]      = mst_resps_i[i].aw_ready;
      assign mst_reqs_o[i].aw       = slv_aw_chan.aw;
      assign mst_reqs_o[i].aw_valid = (slv_aw_chan.brcst_en) ? ((i == NoMstPorts-1)? 1'b0 : mst_aw_valids[i]&A_q[i]) : mst_aw_valids[i];   
    end

    fifo_v3 #(
      .FALL_THROUGH( FallThrough ),
      .DEPTH       ( MaxTrans    ),
      .dtype       ( brcst_t    )
    ) i_w_brcst_fifo (
      .clk_i      ( clk_i              ),
      .rst_ni     ( rst_ni             ),
      .flush_i    ( 1'b0               ), // not used, because AXI4-Lite no preemtion rule
      .testmode_i ( test_i             ),
      .full_o     (),
      .empty_o    (),
      .usage_o    (),
      .data_i     ( slv_aw_chan.brcst_en ),
      .push_i     ( w_fifo_push        ),
      .data_o     ( w_brcst            ),
      .pop_i      ( w_fifo_pop         )
    );
    
    fifo_v3 #(
      .FALL_THROUGH( FallThrough ),
      .DEPTH       ( MaxTrans    ),
      .dtype       ( select_t    )
    ) i_w_fifo (
      .clk_i      ( clk_i              ),
      .rst_ni     ( rst_ni             ),
      .flush_i    ( 1'b0               ), // not used, because AXI4-Lite no preemtion rule
      .testmode_i ( test_i             ),
      .full_o     ( w_fifo_full        ),
      .empty_o    ( w_fifo_empty       ),
      .usage_o    ( /*not used*/       ),
      .data_i     ( slv_aw_chan.select ),
      .push_i     ( w_fifo_push        ),
      .data_o     ( w_select           ),
      .pop_i      ( w_fifo_pop         )
    );

    //--------------------------------------
    // W Channel
    //--------------------------------------

    state_e wstate, n_wstate;
    `OCAH_FFL(wstate, n_wstate, 1'b1, IDLE, clk_i, rst_ni)

    logic locked_widx;

    logic [NoMstPorts-1:0] B_d, B_q, B_en;
    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_B_mask
      `OCAH_FFL(B_q[i], B_d[i], B_en[i], 1'b1, clk_i, rst_ni)
    end

    spill_register #(
      .T      ( w_chan_t ),
      .Bypass ( ~SpillW  )
    ) i_w_spill_reg (
      .clk_i   ( clk_i              ),
      .rst_ni  ( rst_ni             ),
      .valid_i ( slv_req_i.w_valid  ),
      .ready_o ( slv_resp_o.w_ready ),
      .data_i  ( slv_req_i.w        ),
      .valid_o ( slv_w_valid        ),
      .ready_i ( slv_w_ready        ),
      .data_o  ( slv_w_chan         )
    );


    // replicate W channel
    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_mst_w_chan
      assign mst_w_readies[i]      = mst_resps_i[i].w_ready;
      assign mst_reqs_o[i].w       = slv_w_chan;
      assign mst_reqs_o[i].w_valid = (w_brcst) ? ((i==NoMstPorts-1) ? 1'b0 : mst_w_valids[i] & B_q[i]) : ~w_fifo_empty & mst_w_valids[i] & (w_select == select_t'(i));
    end

    assign w_fifo_pop = slv_w_valid & slv_w_ready; 

    //State Machine for W channel handshake control
    always_comb begin
        // default assginments
        slv_w_ready    = 1'b0;
        mst_w_valids   = '0;
        n_wstate = wstate;
        //B_mask
        B_d = B_q;
        B_en = '0;
        //locked channel index
        locked_widx = 1'b0;

        case(wstate) 
            IDLE: 
            begin 
                // reset B_mask
                B_d = '1;
                B_en = '1;
                if (slv_w_valid && ~w_fifo_empty) begin            
                    if (w_brcst) begin
                        n_wstate = BREQ;
                    end else begin
                        n_wstate = REQ;
                    end
                end else begin
                end
            end
            
            REQ: 
            begin
                mst_w_valids[w_select] = 1'b1;
                if (mst_w_readies[w_select]) begin
                    slv_w_ready = 1'b1;
                    n_wstate = IDLE;
                end else begin
                    n_wstate = LOCK;
                end
            end

            LOCK:
            begin
                mst_w_valids[w_select] = 1'b1;
                if (mst_w_readies[w_select]) begin
                    slv_w_ready    = 1'b1;
                    n_wstate = IDLE;
                end else begin
                end
            end

            BREQ:
            begin
                mst_w_valids = '1;
                if (&mst_w_readies[NoMstPorts - 2:0]) begin
                    slv_w_ready    = 1'b1;
                    n_wstate = IDLE;
                end else if (~|mst_w_readies[NoMstPorts - 2:0]) begin
                    n_wstate = BLOCK2;
                end
                else begin
                    n_wstate = BLOCK1;
                    for(int i = 0; i < NoMstPorts-1; i++) begin 
                        if (mst_w_readies[i]) begin : this_channel_ready
                            // apply B_mask pull down valid_o for the ready channel @ next cycle;
                            // Using this B_mask to delay 1 cycle and pull down mst_w_valid
                            B_d[i] = 1'b0;
                            B_en[i] = 1'b1;
                        end
                    end
                end
            end

            BLOCK2: 
            begin
                mst_w_valids = '1;
                if (&mst_w_readies[NoMstPorts - 2:0]) begin
                    slv_w_ready    = 1'b1;
                    n_wstate = IDLE;
                end else if (~|mst_w_readies[NoMstPorts - 2:0]) begin
                    // n_wstate = BLOCK2;
                end
                else begin
                    n_wstate = BLOCK1;
                    for(int i = 0; i < NoMstPorts-1; i++) begin 
                        if (mst_w_readies[i]) begin : this_channel_ready
                            // apply B_mask pull down valid_o for the ready channel @ next cycle;
                            // Using this B_mask to delay 1 cycle and pull down mst_w_valid
                            B_d[i] = 1'b0;
                            B_en[i] = 1'b1;
                        end
                    end
                end
            end

            BLOCK1:
            begin
                mst_w_valids = '1;
                for(int i = 0; i < NoMstPorts-1; i++) begin 
                    if (!B_q[i]) begin
                        locked_widx = 1'(1-i);
                    end
                end
                if (mst_w_readies[locked_widx]) begin
                    slv_w_ready    = 1'b1;
                    n_wstate = IDLE;
                end else begin
                    // n_wstate = BLOCK1;
                end
            end
            
            default: 
            begin 
                n_wstate = IDLE;
            end
        endcase
    end


    //--------------------------------------
    // B Channel
    //--------------------------------------

    // unpack the response B channels for the arbitration
    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_b_channels
      assign mst_b_chans[i]        = mst_resps_i[i].b;
      assign mst_b_valids[i]       = mst_resps_i[i].b_valid;
    end

    // Arbitration of the different B responses
    rr_arb_tree #(
      .NumIn    ( NoMstPorts ),
      .DataType ( b_chan_t   ),
      .AxiVldRdy( 1'b1       ),
      .LockIn   ( 1'b1       )
    ) i_b_mux (
      .clk_i  ( clk_i         ),
      .rst_ni ( rst_ni        ),
      .flush_i( 1'b0          ),
      .rr_i   ( '0            ),
      .req_i  ( mst_b_valids  ),
      .gnt_o  ( mst_b_readies ),
      .data_i ( mst_b_chans   ),
      .gnt_i  ( slv_b_ready   ),
      .req_o  ( slv_b_valid   ),
      .data_o ( slv_b_chan    ),
      .idx_o  (               )
    );

    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_mst_b
      assign mst_reqs_o[i].b_ready = mst_b_readies[i];
    end

    spill_register #(
      .T      ( b_chan_t ),
      .Bypass ( ~SpillB  )
    ) i_b_spill_reg (
      .clk_i   ( clk_i              ),
      .rst_ni  ( rst_ni             ),
      .valid_i ( slv_b_valid        ),
      .ready_o ( slv_b_ready        ),
      .data_i  ( slv_b_chan         ),
      .valid_o ( slv_resp_o.b_valid ),
      .ready_i ( slv_req_i.b_ready  ),
      .data_o  ( slv_resp_o.b       )
    );


    //--------------------------------------
    // AR Channel
    //--------------------------------------
    // Workaround for bug in Questa (see comments on AW channel for details).
    `ifdef TARGET_VSIM
    typedef logic [$bits(ar_chan_select_t)-1:0] ar_chan_select_flat_t;
    `else
    typedef ar_chan_select_t ar_chan_select_flat_t;
    `endif
    ar_chan_select_flat_t slv_ar_chan_select_in_flat,
                          slv_ar_chan_select_out_flat;
    assign slv_ar_chan_select_in_flat = {slv_req_i.ar, slv_ar_select_i};
    spill_register #(
      .T      ( ar_chan_select_flat_t         ),
      .Bypass ( ~SpillAr                      )
    ) i_ar_spill_reg (
      .clk_i   ( clk_i                        ),
      .rst_ni  ( rst_ni                       ),
      .valid_i ( slv_req_i.ar_valid           ),
      .ready_o ( slv_resp_o.ar_ready          ),
      .data_i  ( slv_ar_chan_select_in_flat   ),
      .valid_o ( slv_ar_valid                 ),
      .ready_i ( slv_ar_ready                 ),
      .data_o  ( slv_ar_chan_select_out_flat  )
    );
    assign slv_ar_chan = slv_ar_chan_select_out_flat;

    // replicate AR channel
    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_mst_ar
      assign mst_reqs_o[i].ar       = slv_ar_chan.ar;
      assign mst_reqs_o[i].ar_valid = slv_ar_valid & (slv_ar_chan.select == select_t'(i));
    end
    assign slv_ar_ready = mst_resps_i[slv_ar_chan.select].ar_ready;

    //--------------------------------------
    // R Channel
    //--------------------------------------
    
    // unpack the response R channels for the arbitration
    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_r_channels
      assign mst_r_chans[i]        = mst_resps_i[i].r;
      assign mst_r_valids[i]       = mst_resps_i[i].r_valid;
    end

    // Arbitration of the different R responses
    rr_arb_tree #(
      .NumIn    ( NoMstPorts ),
      .DataType ( r_chan_t   ),
      .AxiVldRdy( 1'b1       ),
      .LockIn   ( 1'b1       )
    ) i_r_mux (
      .clk_i  ( clk_i         ),
      .rst_ni ( rst_ni        ),
      .flush_i( 1'b0          ),
      .rr_i   ( '0            ),
      .req_i  ( mst_r_valids  ),
      .gnt_o  ( mst_r_readies ),
      .data_i ( mst_r_chans   ),
      .gnt_i  ( slv_r_ready   ),
      .req_o  ( slv_r_valid   ),
      .data_o ( slv_r_chan    ),
      .idx_o  (               )
    );
    
    spill_register #(
      .T      ( r_chan_t ),
      .Bypass ( ~SpillR  )
    ) i_r_spill_reg (
      .clk_i   ( clk_i              ),
      .rst_ni  ( rst_ni             ),
      .valid_i ( slv_r_valid        ),
      .ready_o ( slv_r_ready        ),
      .data_i  ( slv_r_chan         ),
      .valid_o ( slv_resp_o.r_valid ),
      .ready_i ( slv_req_i.r_ready  ),
      .data_o  ( slv_resp_o.r       )
    );

    for (genvar i = 0; i < NoMstPorts; i++) begin : gen_mst_r
      assign mst_reqs_o[i].r_ready = mst_r_readies[i];
    end

    // pragma translate_off
    `ifndef VERILATOR
      default disable iff (!rst_ni);
      aw_select: assume property( @(posedge clk_i) (slv_req_i.aw_valid |->
                                                  (slv_aw_select_i < NoMstPorts))) else
        $fatal(1, "slv_aw_select_i is %d: AW has selected a slave that is not defined.\
                  NoMstPorts: %d", slv_aw_select_i, NoMstPorts);
      ar_select: assume property( @(posedge clk_i) (slv_req_i.ar_valid |->
                                                  (slv_ar_select_i < NoMstPorts))) else
        $fatal(1, "slv_ar_select_i is %d: AR has selected a slave that is not defined.\
                  NoMstPorts: %d", slv_ar_select_i, NoMstPorts);
      aw_valid_stable: assert property( @(posedge clk_i) (slv_aw_valid && !slv_aw_ready && !slv_aw_chan.brcst_en)
                                                        |=> slv_aw_valid) else
        $fatal(1, "aw_valid was deasserted, when aw_ready = 0 in last cycle.");
      ar_valid_stable: assert property( @(posedge clk_i) (slv_ar_valid && !slv_ar_ready)
                                                        |=> slv_ar_valid) else
        $fatal(1, "ar_valid was deasserted, when ar_ready = 0 in last cycle.");
      aw_stable: assert property( @(posedge clk_i) (slv_aw_valid && !slv_aw_ready && !slv_aw_chan.brcst_en)
                                |=> $stable(slv_aw_chan)) else
        $fatal(1, "slv_aw_chan_select unstable with valid set.");
      ar_stable: assert property( @(posedge clk_i) (slv_ar_valid && !slv_ar_ready)
                                |=> $stable(slv_ar_chan)) else
        $fatal(1, "slv_aw_chan_select unstable with valid set.");
    `endif
    // pragma translate_on
  end

  // pragma translate_off
  `ifndef VERILATOR
    initial begin: p_assertions
      NoPorts:  assert (NoMstPorts > 0) else $fatal("Number of master ports must be at least 1!");
      NoMstPortsIs2:  assert (NoMstPorts == 3) else $fatal("Number of master ports must be at least 3!, as the FSM was coded based on this assertion");
      MaxTnx:   assert (MaxTrans   > 0) else $fatal("Number of transactions must be at least 1!");
    end
  `endif
  // pragma translate_on
endmodule

`include "axi/assign.svh"
`include "axi/typedef.svh"

module axi5_lite_demux_brcst_intf #(
  parameter int unsigned AxiIdWidth   = 32'd0,
  parameter int unsigned AxiAddrWidth = 32'd0,
  parameter int unsigned AxiDataWidth = 32'd0,
  parameter int unsigned AxiUserWidth = 32'd0,
  parameter int unsigned NoMstPorts   = 32'd0,
  parameter int unsigned MaxTrans     = 32'd0,
  parameter bit          FallThrough  = 1'b0,
  parameter bit          SpillAw      = 1'b1,
  parameter bit          SpillW       = 1'b0,
  parameter bit          SpillB       = 1'b0,
  parameter bit          SpillAr      = 1'b1,
  parameter bit          SpillR       = 1'b0,
  // Dependent parameters, DO NOT OVERRIDE!
  parameter type         select_t     = logic [$clog2(NoMstPorts)-1:0]
) (
  input  logic     clk_i,               // Clock
  input  logic     rst_ni,              // Asynchronous reset active low
  input  logic     test_i,              // Testmode enable
  input  select_t  slv_aw_select_i,     // has to be stable, when aw_valid
  input  select_t  slv_ar_select_i,     // has to be stable, when ar_valid
  AXI5_LITE.Slave   slv,                 // slave port
  AXI5_LITE.Master  mst [NoMstPorts-1:0] // master ports
);
  typedef logic [AxiIdWidth-1:0]     id_t;
  typedef logic [AxiAddrWidth-1:0]   addr_t;
  typedef logic [AxiDataWidth-1:0]   data_t;
  typedef logic [AxiDataWidth/8-1:0] strb_t;
  typedef logic [AxiUserWidth-1:0]   user_t;
  // channels typedef
  `AXI5_LITE_TYPEDEF_AW_CHAN_T(aw_chan_t, addr_t, id_t, user_t)
  `AXI5_LITE_TYPEDEF_W_CHAN_T(w_chan_t, data_t, strb_t, user_t)
  `AXI5_LITE_TYPEDEF_B_CHAN_T(b_chan_t, id_t, user_t)
  `AXI5_LITE_TYPEDEF_AR_CHAN_T(ar_chan_t, addr_t, id_t, user_t)
  `AXI5_LITE_TYPEDEF_R_CHAN_T(r_chan_t, data_t, id_t, user_t)
  `AXI5_LITE_TYPEDEF_REQ_T(axi_req_t, aw_chan_t, w_chan_t, ar_chan_t)
  `AXI5_LITE_TYPEDEF_RESP_T(axi_resp_t, b_chan_t, r_chan_t)

  axi_req_t                   slv_req;
  axi_resp_t                  slv_resp;
  axi_req_t  [NoMstPorts-1:0] mst_reqs;
  axi_resp_t [NoMstPorts-1:0] mst_resps;

  `AXI5_LITE_ASSIGN_TO_REQ(slv_req, slv)
  `AXI5_LITE_ASSIGN_FROM_RESP(slv, slv_resp)

  for (genvar i = 0; i < NoMstPorts; i++) begin : gen_assign_mst_ports
    `AXI5_LITE_ASSIGN_FROM_REQ(mst[i], mst_reqs[i])
    `AXI5_LITE_ASSIGN_TO_RESP(mst_resps[i], mst[i])
  end

  axi5_lite_demux_brcst #(
    .aw_chan_t   (  aw_chan_t  ),
    .w_chan_t    (   w_chan_t  ),
    .b_chan_t    (   b_chan_t  ),
    .ar_chan_t   (  ar_chan_t  ),
    .r_chan_t    (   r_chan_t  ),
    .axi_req_t   (  axi_req_t  ),
    .axi_resp_t  ( axi_resp_t  ),
    .NoMstPorts  ( NoMstPorts  ),
    .MaxTrans    ( MaxTrans    ),
    .FallThrough ( FallThrough ),
    .SpillAw     ( SpillAw     ),
    .SpillW      ( SpillW      ),
    .SpillB      ( SpillB      ),
    .SpillAr     ( SpillAr     ),
    .SpillR      ( SpillR      )
  ) i_axi_demux (
    .clk_i,
    .rst_ni,
    .test_i,
    // slave Port
    .slv_req_i       ( slv_req         ),
    .slv_aw_select_i ( slv_aw_select_i ), // must be stable while slv_aw_valid_i
    .slv_ar_select_i ( slv_ar_select_i ), // must be stable while slv_ar_valid_i
    .slv_resp_o      ( slv_resp        ),
    // mster ports
    .mst_reqs_o      ( mst_reqs        ),
    .mst_resps_i     ( mst_resps       )
  );

  // pragma translate_off
  `ifndef VERILATOR
    initial begin: p_assertions
      AddrWidth: assert (AxiAddrWidth > 0) else $fatal("Axi Parmeter has to be > 0!");
      DataWidth: assert (AxiDataWidth > 0) else $fatal("Axi Parmeter has to be > 0!");
    end
  `endif
  // pragma translate_on
endmodule
