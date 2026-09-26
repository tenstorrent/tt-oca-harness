// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Drive one GPIO pad from AXI-Lite registers with an LSIO override path.
//
// lsio_interface_select_i steers pad direction and data between register control and the
// LSIO plane.
// GPIO control-register access for the pad ring lives elsewhere; this block handles its
// own interface registers only.
// core2pad_* and pad2core_* are the pad-facing request wires.

module gpio
  import gpio_pkg::*;
#(
  parameter int unsigned MAX_TRANS = 32,                    // AXI-Lite outstanding capacity.
  parameter bit INPUT_BY_DEFAULT = 1'b1,                    // Pad defaults to input when unset.

  parameter bit [ADDR_WIDTH-1:0] GPIO_INTF_REG_MAP_BASE_ADDR = 0, // Interface register-map base.
  parameter bit [ADDR_WIDTH-1:0] GPIO_INTF_REG_MAP_SIZE      = 0, // Interface register-map size.
  parameter bit [ADDR_WIDTH-1:0] ADDRESS_MAP_SIZE_PER_GPIO   = 0 // Byte span allocated per GPIO.
) (
  input logic clk_i,                                        // System clock.
  input logic rst_primary_ni,                               // Primary async reset, active-low.
  input logic rst_cold_ni,                                  // Cold async reset, active-low.
  input logic test_en_i,                                    // DFT test enable.

  input  gpio_axil_req_t  axil_req_i,                       // AXI-Lite CSR request.
  output gpio_axil_resp_t axil_resp_o,                      // AXI-Lite CSR response.

  input  logic lsio_interface_select_i,                     // Selects LSIO pad control.
  input  logic lsio_core2pad_en_ni,                         // LSIO core-to-pad enable, active-low.
  input  logic lsio_core2pad_data_i,                        // LSIO core-to-pad data.
  input  logic lsio_pad2core_en_ni,                         // LSIO pad-to-core enable, active-low.
  output logic lsio_pad2core_data_o,                        // LSIO pad-to-core data.

  output logic interrupt_o,                                 // GPIO interrupt.

  output wire core2pad_o,                                   // Core-to-pad data.
  output wire core2pad_en_o,                                // Core-to-pad output enable.
  input  wire pad2core_i,                                   // Pad-to-core data.
  output wire pad2core_en_o                                 // Pad-to-core input enable.
);

  localparam int unsigned GPIO_INTF_ADDR_WIDTH = $clog2(GPIO_INTF_REG_MAP_SIZE);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  logic        filter__write_filter_enable;
  logic        filter__read_filter_enable;
  logic [2:0]  filter__awprot_requirement;
  logic [2:0]  filter__arprot_requirement;

  gpio_intf_reg_pkg::gpio_intf__out_t gpio_intf_hwif_out;
  gpio_intf_reg_pkg::gpio_intf__in_t gpio_intf_hwif_in;

  assign filter__write_filter_enable = gpio_intf_hwif_out.ACCESS_FILTER.write_filter_enable.value;
  assign filter__read_filter_enable = gpio_intf_hwif_out.ACCESS_FILTER.read_filter_enable.value;
  assign filter__awprot_requirement = gpio_intf_hwif_out.ACCESS_FILTER.awprot_requirement.value;
  assign filter__arprot_requirement = gpio_intf_hwif_out.ACCESS_FILTER.arprot_requirement.value;

  // Register signals from gpio_ctrl_reg hwif_out structure
  logic reg__pad2core;
  logic reg__lsio_select;
  logic reg__core2pad;
  logic [1:0] reg__enable_rx_tx;
  logic reg__interface_enable;
  logic reg__use_reg_core2pad;
  logic reg__use_reg_tx;
  logic reg__use_reg_rx;
  logic reg__lsio_disable;
  logic reg__interrupt_enable;
  logic [1:0] reg__interrupt_type;

  // Connect gpio_ctrl_reg hwif_out to internal signals
  assign reg__core2pad = gpio_intf_hwif_out.DATA_CTRL.core2pad.value;
  assign reg__enable_rx_tx = gpio_intf_hwif_out.DATA_CTRL.enable_rx_tx.value;
  assign reg__interface_enable = gpio_intf_hwif_out.DATA_CTRL.interface_enable.value;
  assign reg__lsio_select = gpio_intf_hwif_out.DATA_CTRL.lsio_select.value;
  assign reg__interrupt_enable = gpio_intf_hwif_out.DATA_CTRL.interrupt_enable.value;
  assign reg__lsio_disable = gpio_intf_hwif_out.DATA_CTRL.lsio_disable.value;
  assign reg__interrupt_type = gpio_intf_hwif_out.DATA_CTRL.interrupt_type.value;
  assign reg__use_reg_core2pad = gpio_intf_hwif_out.DATA_CTRL_ENABLE.use_reg_core2pad.value;
  assign reg__use_reg_tx = gpio_intf_hwif_out.DATA_CTRL_ENABLE.use_reg_tx.value;
  assign reg__use_reg_rx = gpio_intf_hwif_out.DATA_CTRL_ENABLE.use_reg_rx.value;

  assign gpio_intf_hwif_in.DATA_CTRL.pad2core.next = reg__pad2core;

  //--------------------//
  // GPIO ACCESS FILTER //
  //--------------------//

  gpio_axil_req_t  filtered_axil_req;
  gpio_axil_resp_t filtered_axil_resp;

  gpio_filter #(
    .MAX_TRANS(MAX_TRANS)
  ) u_gpio_access_filter (
    .clk_i(clk_i),
    .rst_ni(rst_primary_ni),
    .test_en_i(test_en_i),

    // Filter Configuration
    .write_filter_enable_i(filter__write_filter_enable),
    .read_filter_enable_i (filter__read_filter_enable),
    .awprot_requirement_i (filter__awprot_requirement),
    .arprot_requirement_i (filter__arprot_requirement),

    .axil_req_i(axil_req_i),
    .axil_resp_o(axil_resp_o),
    .filtered_axil_req_o(filtered_axil_req),
    .filtered_axil_resp_i(filtered_axil_resp)
  );

  // Direct connection to gpio_intf register block (no demux needed)
  gpio_axil_req_t  gpio_intf_axil_req;
  gpio_axil_resp_t gpio_intf_axil_resp;

  assign gpio_intf_axil_req = filtered_axil_req;
  assign filtered_axil_resp = gpio_intf_axil_resp;

  gpio_intf_reg u_gpio_intf_reg (
    .clk(clk_i),
    .arst_n(rst_primary_ni),

    .s_axil_awready(gpio_intf_axil_resp.aw_ready),
    .s_axil_awvalid(gpio_intf_axil_req.aw_valid),
    .s_axil_awaddr (gpio_intf_axil_req.aw.addr[GPIO_INTF_ADDR_WIDTH-1:0]),
    .s_axil_awprot (gpio_intf_axil_req.aw.prot),
    .s_axil_wready (gpio_intf_axil_resp.w_ready),
    .s_axil_wvalid (gpio_intf_axil_req.w_valid),
    .s_axil_wdata  (gpio_intf_axil_req.w.data),
    .s_axil_wstrb  (gpio_intf_axil_req.w.strb),
    .s_axil_bready (gpio_intf_axil_req.b_ready),
    .s_axil_bvalid (gpio_intf_axil_resp.b_valid),
    .s_axil_bresp  (gpio_intf_axil_resp.b.resp),
    .s_axil_arready(gpio_intf_axil_resp.ar_ready),
    .s_axil_arvalid(gpio_intf_axil_req.ar_valid),
    .s_axil_araddr (gpio_intf_axil_req.ar.addr[GPIO_INTF_ADDR_WIDTH-1:0]),
    .s_axil_arprot (gpio_intf_axil_req.ar.prot),
    .s_axil_rready (gpio_intf_axil_req.r_ready),
    .s_axil_rvalid (gpio_intf_axil_resp.r_valid),
    .s_axil_rdata  (gpio_intf_axil_resp.r.data),
    .s_axil_rresp  (gpio_intf_axil_resp.r.resp),
    .hwif_in(gpio_intf_hwif_in),
    .hwif_out(gpio_intf_hwif_out)
  );

  //------------------------//
  // DATA INTERFACE CONTROL //
  //------------------------//

  logic core2pad, pad2core;
  logic core2pad_en, pad2core_en;

  logic pad2core_synced;

  logic lsio_pin, lsio_sw, lsio_active;
  assign lsio_pin = lsio_interface_select_i && ~reg__lsio_disable;
  assign lsio_sw  = reg__lsio_select && ~reg__lsio_disable;

  // Any LSIO request. Used only for the pad2core return path, which does not participate in the ownership ranking.
  assign lsio_active = lsio_pin || lsio_sw;

  // Status back to software
  assign gpio_intf_hwif_in.DATA_CTRL.lsio_enable.next = lsio_pin;

  // Per-field register override, each OR'd with the global interface_enable
  logic sel_reg_core2pad, sel_reg_tx, sel_reg_rx;
  assign sel_reg_core2pad = reg__interface_enable || reg__use_reg_core2pad;
  assign sel_reg_tx       = reg__interface_enable || reg__use_reg_tx;
  assign sel_reg_rx       = reg__interface_enable || reg__use_reg_rx;

  always_comb begin
    reg__pad2core = 1'b0;
    lsio_pad2core_data_o = 1'b0;

    core2pad = 1'b0;
    core2pad_en = 1'b0;
    pad2core_en = INPUT_BY_DEFAULT;

    if (~rst_cold_ni) begin
      core2pad = 1'b0;
      core2pad_en = 1'b0;
      pad2core_en = INPUT_BY_DEFAULT;
      lsio_pad2core_data_o = pad2core;
    end else begin
      // core2pad data
      if (lsio_pin) begin
        core2pad = lsio_core2pad_data_i;
      end else if (sel_reg_core2pad) begin
        core2pad = reg__core2pad;
      end else if (lsio_sw) begin
        core2pad = lsio_core2pad_data_i;
      end

      // output enable (tx)
      if (lsio_pin) begin
        core2pad_en = ~lsio_core2pad_en_ni;
      end else if (sel_reg_tx) begin
        core2pad_en = reg__enable_rx_tx[0];
      end else if (lsio_sw) begin
        core2pad_en = ~lsio_core2pad_en_ni;
      end

      // input enable (rx)
      if (lsio_pin) begin
        pad2core_en = ~lsio_pad2core_en_ni;
      end else if (sel_reg_rx) begin
        pad2core_en = reg__enable_rx_tx[1];
      end else if (lsio_sw) begin
        pad2core_en = ~lsio_pad2core_en_ni;
      end

      if (lsio_active) begin
        lsio_pad2core_data_o = pad2core;
      end

      if (sel_reg_rx) begin
        reg__pad2core = pad2core_synced;
      end
    end
  end

  assign core2pad_o = core2pad;
  assign core2pad_en_o = core2pad_en;
  assign pad2core = pad2core_i;
  assign pad2core_en_o = pad2core_en;

  //-----------//
  // INTERRUPT //
  //-----------//

  logic prev_pad2core;
  logic interrupt, nxt_interrupt;

  prim_sync3r #(
    .WIDTH(1)
  ) u_pad2core_sync (
    .clk_i(clk_i),
    .d_i(pad2core),
    .rst_ni(rst_primary_ni),
    .q_o(pad2core_synced)
  );

  always_ff @(posedge clk_i or negedge rst_primary_ni) begin
    if (!rst_primary_ni) begin
      prev_pad2core <= 1'b0;
      interrupt <= 1'b0;
    end else begin
      prev_pad2core <= pad2core_synced;
      interrupt <= nxt_interrupt;
    end
  end

  typedef enum logic [1:0] {
    ACTIVE_HIGH  = 2'b00,
    ACTIVE_LOW   = 2'b01,
    RISING_EDGE  = 2'b10,
    FALLING_EDGE = 2'b11
  } interrupt_type_t;

  always_comb begin
    unique case (reg__interrupt_type)
      ACTIVE_HIGH: begin
        nxt_interrupt = pad2core_synced;
      end
      ACTIVE_LOW: begin
        nxt_interrupt = !pad2core_synced;
      end
      RISING_EDGE: begin
        if (!prev_pad2core && pad2core_synced) begin
          nxt_interrupt = 1'b1;
        end else begin
          nxt_interrupt = 1'b0;
        end
      end
      FALLING_EDGE: begin
        if (prev_pad2core && !pad2core_synced) begin
          nxt_interrupt = 1'b1;
        end else begin
          nxt_interrupt = 1'b0;
        end
      end
      default: begin
        nxt_interrupt = 1'b0;
      end
    endcase
  end

  assign interrupt_o = interrupt && reg__interrupt_enable;

endmodule
