module axi_spill_regs
#(
    parameter type aw_chan_t = logic,
    parameter type w_chan_t = logic,
    parameter type b_chan_t = logic,
    parameter type ar_chan_t = logic,
    parameter type r_chan_t = logic,
    parameter type req_t = logic,
    parameter type rsp_t = logic
) (
    input  req_t axi_req_i,
    output req_t axi_req_o,
    input  rsp_t axi_rsp_i,
    output rsp_t axi_rsp_o,
    input  clk,
    input  reset_n
);

  // --------------------------------------
  // Spill Registers for each AXI channels
  // --------------------------------------
    spill_register #(
      .T       ( aw_chan_t  )
    ) i_aw_spill_reg (
      .clk_i   ( clk                    ),
      .rst_ni  ( reset_n                ),
      .valid_i ( axi_req_i.aw_valid  ),
      .ready_o ( axi_rsp_o.aw_ready ),
      .data_i  ( axi_req_i.aw        ),
      .valid_o ( axi_req_o.aw_valid       ),
      .ready_i ( axi_rsp_i.aw_ready      ),
      .data_o  ( axi_req_o.aw             )
    );
    spill_register #(
      .T       ( w_chan_t )
    ) i_w_spill_reg (
      .clk_i   ( clk                    ),
      .rst_ni  ( reset_n                ),
      .valid_i ( axi_req_i.w_valid   ),
      .ready_o ( axi_rsp_o.w_ready  ),
      .data_i  ( axi_req_i.w         ),
      .valid_o ( axi_req_o.w_valid        ),
      .ready_i ( axi_rsp_i.w_ready       ),
      .data_o  ( axi_req_o.w              )
    );
    spill_register #(
      .T       ( b_chan_t )
    ) i_b_spill_reg (
      .clk_i   ( clk                    ),
      .rst_ni  ( reset_n                ),
      .valid_i ( axi_rsp_i.b_valid       ),
      .ready_o ( axi_req_o.b_ready        ),
      .data_i  ( axi_rsp_i.b             ),
      .valid_o ( axi_rsp_o.b_valid  ),
      .ready_i ( axi_req_i.b_ready   ),
      .data_o  ( axi_rsp_o.b        )
    );
    spill_register #(
      .T       ( ar_chan_t )
    ) i_ar_spill_reg (
      .clk_i   ( clk                    ),
      .rst_ni  ( reset_n                ),
      .valid_i ( axi_req_i.ar_valid  ),
      .ready_o ( axi_rsp_o.ar_ready ),
      .data_i  ( axi_req_i.ar        ),
      .valid_o ( axi_req_o.ar_valid       ),
      .ready_i ( axi_rsp_i.ar_ready      ),
      .data_o  ( axi_req_o.ar             )
    );
    spill_register #(
      .T       ( r_chan_t )
    ) i_r_spill_reg (
      .clk_i   ( clk                    ),
      .rst_ni  ( reset_n                ),
      .valid_i ( axi_rsp_i.r_valid       ),
      .ready_o ( axi_req_o.r_ready        ),
      .data_i  ( axi_rsp_i.r             ),
      .valid_o ( axi_rsp_o.r_valid  ),
      .ready_i ( axi_req_i.r_ready   ),
      .data_o  ( axi_rsp_o.r        )
    );

endmodule // spill_regs
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".svh" ".vh" ".h" ".v")
// verilog-typedef-regexp: "_[sute]$"
// End:




