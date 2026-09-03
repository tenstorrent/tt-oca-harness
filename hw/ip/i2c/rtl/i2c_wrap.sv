// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// I2C Wrapper

module i2c_wrap #(
  parameter int unsigned NUM_I2CS                 = 3,
  parameter int unsigned CONTROLLER_TX_FIFO_DEPTH = 64,
  parameter int unsigned CONTROLLER_RX_FIFO_DEPTH = 64,
  parameter int unsigned TARGET_TX_FIFO_DEPTH     = 64,
  parameter int unsigned TARGET_RX_FIFO_DEPTH     = 268,
  parameter int unsigned INPUT_DELAY_CYCLES       = 0,

  parameter bit [i2c_wrap_pkg::REG_ADDR_WIDTH-1:0] I2C_CTRL_REG_MAP_BASE_ADDR = 0,
  parameter bit [i2c_wrap_pkg::REG_ADDR_WIDTH-1:0] I2C_CTRL_REG_MAP_SIZE      = 0,

  parameter bit [i2c_wrap_pkg::REG_ADDR_WIDTH-1:0] I2C_0__REG_MAP_BASE_ADDR = 0,
  parameter bit [i2c_wrap_pkg::REG_ADDR_WIDTH-1:0] I2C_0__REG_MAP_SIZE      = 0,
  parameter bit [i2c_wrap_pkg::REG_ADDR_WIDTH-1:0] I2C_INSTANCE_SPACING     = 0,

  localparam int unsigned NUM_REG_MAPS = NUM_I2CS + 2, // +1 for ctrl +1 for error slave
  localparam type i2c_wrap_reg_map_select_t = logic [$clog2(NUM_REG_MAPS)-1:0],
  localparam i2c_wrap_reg_map_select_t CTRL_REG_MAP =
        i2c_wrap_reg_map_select_t'(NUM_REG_MAPS - 2),
  localparam i2c_wrap_reg_map_select_t UNDEFINED_REG_MAP =
        i2c_wrap_reg_map_select_t'(NUM_REG_MAPS - 1)
) (
  // Global Interface
  input  logic                clk_i,
  input  logic                rst_ni,

  // AXI4-Lite Register Interface
  input  i2c_wrap_pkg::axil_req_t           axil_req_i,
  output i2c_wrap_pkg::axil_resp_t          axil_resp_o,

  // Control Interface
  output logic [NUM_I2CS-1:0] i2c_en_o,
  output logic [NUM_I2CS-1:0] i2c_controller_mode_en_o,

  // I2C Interface
  input  logic [NUM_I2CS-1:0] scl_i,
  output logic [NUM_I2CS-1:0] scl_o,
  input  logic [NUM_I2CS-1:0] sda_i,
  output logic [NUM_I2CS-1:0] sda_o,

  // I2C SMBus Interface
  input  logic [NUM_I2CS-1:0] smbsus_ni,
  output logic [NUM_I2CS-1:0] smbsus_no,
  input  logic [NUM_I2CS-1:0] smbalert_ni,
  output logic [NUM_I2CS-1:0] smbalert_no,

  // I2C DMA Interface
  output logic [NUM_I2CS-1:0] controller_tx_ready_o,
  output logic [NUM_I2CS-1:0] controller_rx_ready_o,
  output logic [NUM_I2CS-1:0] target_tx_ready_o,
  output logic [NUM_I2CS-1:0] target_rx_ready_o,

  // Interrupt Interface
  output logic [NUM_I2CS-1:0] i2c_irq_o,

  // Debug Interface (4 bits per I2C; see i2c_core.sv for field definitions)
  output logic [NUM_I2CS-1:0][3:0] i2c_debug_o
);

  `include "axi/assign.svh"
  `include "prim_assert.sv"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  logic [NUM_I2CS-1:0] smbus_en;

  i2c_wrap_pkg::axil_req_t  [NUM_REG_MAPS-1:0] axil_reqs;
  i2c_wrap_pkg::axil_resp_t [NUM_REG_MAPS-1:0] axil_resps;


  //////////////////////////////
  // AXI4-Lite Register Demux //
  //////////////////////////////

  i2c_wrap_reg_map_select_t axil_aw_select, axil_ar_select;

  always_comb begin
    axil_aw_select = UNDEFINED_REG_MAP;

    if (axil_req_i.aw.addr >= I2C_CTRL_REG_MAP_BASE_ADDR &&
            axil_req_i.aw.addr <  I2C_CTRL_REG_MAP_BASE_ADDR +
                                  I2C_CTRL_REG_MAP_SIZE) begin
      axil_aw_select = CTRL_REG_MAP;
    end else begin
      for (int i = 0; i < NUM_I2CS; i++) begin
        logic [i2c_wrap_pkg::REG_ADDR_WIDTH-1:0] i2c_i_base_addr;
        i2c_i_base_addr = I2C_0__REG_MAP_BASE_ADDR + i * I2C_INSTANCE_SPACING;
        if (axil_req_i.aw.addr >= i2c_i_base_addr &&
                    axil_req_i.aw.addr <  i2c_i_base_addr +
                                          I2C_0__REG_MAP_SIZE) begin
          axil_aw_select = i2c_wrap_reg_map_select_t'(i);
        end
      end
    end
  end

  always_comb begin
    axil_ar_select = UNDEFINED_REG_MAP;

    if (axil_req_i.ar.addr >= I2C_CTRL_REG_MAP_BASE_ADDR &&
            axil_req_i.ar.addr <  I2C_CTRL_REG_MAP_BASE_ADDR +
                                  I2C_CTRL_REG_MAP_SIZE) begin
      axil_ar_select = CTRL_REG_MAP;
    end else begin
      for (int i = 0; i < NUM_I2CS; i++) begin
        logic [i2c_wrap_pkg::REG_ADDR_WIDTH-1:0] i2c_i_base_addr;
        i2c_i_base_addr = I2C_0__REG_MAP_BASE_ADDR + i * I2C_INSTANCE_SPACING;
        if (axil_req_i.ar.addr >= i2c_i_base_addr &&
                    axil_req_i.ar.addr <  i2c_i_base_addr +
                                          I2C_0__REG_MAP_SIZE) begin
          axil_ar_select = i2c_wrap_reg_map_select_t'(i);
        end
      end
    end
  end

  axi_lite_demux #(
    .aw_chan_t       (i2c_wrap_pkg::axil_aw_chan_t),
    .w_chan_t        (i2c_wrap_pkg::axil_w_chan_t),
    .b_chan_t        (i2c_wrap_pkg::axil_b_chan_t),
    .ar_chan_t       (i2c_wrap_pkg::axil_ar_chan_t),
    .r_chan_t        (i2c_wrap_pkg::axil_r_chan_t),
    .axi_req_t       (i2c_wrap_pkg::axil_req_t),
    .axi_resp_t      (i2c_wrap_pkg::axil_resp_t),
    .NoMstPorts      (NUM_REG_MAPS),
    .MaxTrans        (1),
    .FallThrough     (1'b0),
    .SpillAw         (1'b1),
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b1),
    .SpillR          (1'b0)
  ) axi_lite_demux (
    .clk_i,
    .rst_ni,
    .test_i          (1'b0),
    .slv_req_i       (axil_req_i),
    .slv_aw_select_i (axil_aw_select),
    .slv_ar_select_i (axil_ar_select),
    .slv_resp_o      (axil_resp_o),
    .mst_reqs_o      (axil_reqs),
    .mst_resps_i     (axil_resps)
  );

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (i2c_wrap_pkg::REG_ADDR_WIDTH),
    .AXI_DATA_WIDTH (i2c_wrap_pkg::REG_DATA_WIDTH),
    .axil_req_t     (i2c_wrap_pkg::axil_req_t),
    .axil_resp_t    (i2c_wrap_pkg::axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (i2c_wrap_pkg::REG_DATA_WIDTH),
    .RESP_DATA      (32'hBADCAB1E),
    .MAX_TRANS      (1)
  ) prim_axi_lite_err_slv (
    .clk_i,
    .rst_ni,

    .axil_req_i     (axil_reqs [UNDEFINED_REG_MAP]),
    .axil_resp_o    (axil_resps[UNDEFINED_REG_MAP])
  );


  //////////
  // I2Cs //
  //////////

  for (genvar i = 0; i < NUM_I2CS; i++) begin : gen_i2cs

    i2c_pkg::axil_req_t  i2c_axil_req;
    i2c_pkg::axil_resp_t i2c_axil_resp;

    `AXI_LITE_ASSIGN_REQ_STRUCT(i2c_axil_req, axil_reqs[i])
    `AXI_LITE_ASSIGN_RESP_STRUCT(axil_resps[i], i2c_axil_resp)

    i2c #(
      .CONTROLLER_TX_FIFO_DEPTH (CONTROLLER_TX_FIFO_DEPTH),
      .CONTROLLER_RX_FIFO_DEPTH (CONTROLLER_RX_FIFO_DEPTH),
      .TARGET_TX_FIFO_DEPTH     (TARGET_TX_FIFO_DEPTH),
      .TARGET_RX_FIFO_DEPTH     (TARGET_RX_FIFO_DEPTH),
      .INPUT_DELAY_CYCLES       (INPUT_DELAY_CYCLES)
    ) i2c (
      // Global Interface
      .clk_i,
      .rst_ni,

      // AXI4-Lite Register Interface
      .axil_req_i               (i2c_axil_req),
      .axil_resp_o              (i2c_axil_resp),

      // I2C Interface
      .scl_i                    (scl_i[i]),
      .scl_o                    (scl_o[i]),
      .sda_i                    (sda_i[i]),
      .sda_o                    (sda_o[i]),

      // SMBus Interface
      .smbus_en_i               (smbus_en   [i]),
      .smbsus_ni                (smbsus_ni  [i]),
      .smbsus_no                (smbsus_no  [i]),
      .smbalert_ni              (smbalert_ni[i]),
      .smbalert_no              (smbalert_no[i]),

      // DMA Interface
      .controller_tx_ready_o    (controller_tx_ready_o[i]),
      .controller_rx_ready_o    (controller_rx_ready_o[i]),
      .target_tx_ready_o        (target_tx_ready_o    [i]),
      .target_rx_ready_o        (target_rx_ready_o    [i]),

      // Interrupt Interface
      .irq_o                    (i2c_irq_o[i]),

      // Debug Interface
      .debug_o                  (i2c_debug_o[i])
    );

  end


  //////////
  // CSRs //
  //////////

  i2c_ctrl_reg_pkg::i2c_ctrl__out_t reg_out;

  i2c_ctrl_reg i2c_ctrl_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_resps[CTRL_REG_MAP].aw_ready),
    .s_axil_awvalid (axil_reqs [CTRL_REG_MAP].aw_valid),
    .s_axil_awaddr  (axil_reqs [CTRL_REG_MAP].aw.addr[
                            i2c_ctrl_reg_pkg::I2C_CTRL_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_awprot  (axil_reqs [CTRL_REG_MAP].aw.prot),
    .s_axil_wready  (axil_resps[CTRL_REG_MAP].w_ready),
    .s_axil_wvalid  (axil_reqs [CTRL_REG_MAP].w_valid),
    .s_axil_wdata   (axil_reqs [CTRL_REG_MAP].w.data),
    .s_axil_wstrb   (axil_reqs [CTRL_REG_MAP].w.strb),
    .s_axil_bready  (axil_reqs [CTRL_REG_MAP].b_ready),
    .s_axil_bvalid  (axil_resps[CTRL_REG_MAP].b_valid),
    .s_axil_bresp   (axil_resps[CTRL_REG_MAP].b.resp),
    .s_axil_arready (axil_resps[CTRL_REG_MAP].ar_ready),
    .s_axil_arvalid (axil_reqs [CTRL_REG_MAP].ar_valid),
    .s_axil_araddr  (axil_reqs [CTRL_REG_MAP].ar.addr[
                            i2c_ctrl_reg_pkg::I2C_CTRL_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_arprot  (axil_reqs [CTRL_REG_MAP].ar.prot),
    .s_axil_rready  (axil_reqs [CTRL_REG_MAP].r_ready),
    .s_axil_rvalid  (axil_resps[CTRL_REG_MAP].r_valid),
    .s_axil_rdata   (axil_resps[CTRL_REG_MAP].r.data),
    .s_axil_rresp   (axil_resps[CTRL_REG_MAP].r.resp),

    .hwif_out       (reg_out)
  );

  // I2C_CTRL Registers
  always_comb begin
    for (int i = 0; i < NUM_I2CS; i++) begin
      i2c_en_o[i]                 = reg_out.I2C_CTRL[i].I2C_EN.value;
      i2c_controller_mode_en_o[i] = reg_out.I2C_CTRL[i].I2C_CONTROLLER_MODE_EN.value;
      smbus_en[i]                 = reg_out.I2C_CTRL[i].SMBUS_EN.value;
    end
  end


  ////////////////
  // Assertions //
  ////////////////

  `OCAH_OT_ASSERT_INIT(paramCheckNumI2cs_A, NUM_I2CS > 0)
  `OCAH_OT_ASSERT_INIT(paramCheckMaxNumI2cs_A, NUM_I2CS <= i2c_wrap_pkg::MAX_NUM_I2CS)

  `OCAH_OT_ASSERT_KNOWN(AxilRespKnownO_A, axil_resp_o)
  `OCAH_OT_ASSERT_KNOWN(I2CEnKnownO_A, i2c_en_o)
  `OCAH_OT_ASSERT_KNOWN(I2CControllerModeEnKnownO_A, i2c_controller_mode_en_o)
  `OCAH_OT_ASSERT_KNOWN(SclKnownO_A, scl_o)
  `OCAH_OT_ASSERT_KNOWN(SdaKnownO_A, sda_o)
  `OCAH_OT_ASSERT_KNOWN(SmbsusKnownO_A, smbsus_no)
  `OCAH_OT_ASSERT_KNOWN(SmbalertKnownO_A, smbalert_no)
  `OCAH_OT_ASSERT_KNOWN(ControllerTxReadyKnownO_A, controller_tx_ready_o)
  `OCAH_OT_ASSERT_KNOWN(ControllerRxReadyKnownO_A, controller_rx_ready_o)
  `OCAH_OT_ASSERT_KNOWN(TargetTxReadyKnownO_A, target_tx_ready_o)
  `OCAH_OT_ASSERT_KNOWN(TargetRxReadyKnownO_A, target_rx_ready_o)
  `OCAH_OT_ASSERT_KNOWN(I2cIrqKnownO_A, i2c_irq_o)
  `OCAH_OT_ASSERT_KNOWN(I2cDebugKnownO_A, i2c_debug_o)

endmodule
