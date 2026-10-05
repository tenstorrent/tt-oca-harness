// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Demux one AXI-Lite slave onto NUM_I2CS I2C cores and a shared ctrl map.
//
// NumRegMaps is NUM_I2CS plus one for ctrl and one for the error slave.
// Addresses outside every map reach the error slave, which answers DECERR with read data
// 0xBADCAB1E.
// The ctrl map holds one I2C_CTRL register per instance, which drives i2c_en_o,
// i2c_controller_mode_en_o and that instance's SMBus enable.
// SMBus, DMA ready, IRQ, and debug ports are vectors with one slice per instance.
// Each instance's debug nibble matches i2c_core's four-bit debug bus.

module i2c_wrap #(
  parameter int unsigned NUM_I2CS                 = 3,      // Number of I2C instances; 1 to
                                                            // i2c_wrap_pkg::MaxNumI2cs.
  parameter int unsigned CONTROLLER_TX_FIFO_DEPTH = 64,     // Entries in the controller format
                                                            // (FMT) FIFO in each instance; 1 to
                                                            // 4095.
  parameter int unsigned CONTROLLER_RX_FIFO_DEPTH = 64,     // Entries in the controller receive
                                                            // (RX) FIFO in each instance; 1 to
                                                            // 4095.
  parameter int unsigned TARGET_TX_FIFO_DEPTH     = 64,     // Entries in the target transmit (TX)
                                                            // FIFO in each instance; 1 to 4095.
  parameter int unsigned TARGET_RX_FIFO_DEPTH     = 268,    // Entries in the target acquisition
                                                            // (ACQ) FIFO in each instance; 1 to
                                                            // 4095.
  parameter int unsigned INPUT_DELAY_CYCLES       = 0,      // External SCL/SDA input delay in clk_i
                                                            // cycles; lengthens the
                                                            // interference-detection blanking
                                                            // window after each output change.

  parameter bit [i2c_wrap_pkg::RegAddrWidth-1:0] I2C_CTRL_REG_MAP_BASE_ADDR = 0, // Shared ctrl register-map base.
  parameter bit [i2c_wrap_pkg::RegAddrWidth-1:0] I2C_CTRL_REG_MAP_SIZE      = 0, // Shared ctrl register-map size.

  parameter bit [i2c_wrap_pkg::RegAddrWidth-1:0] I2C_0__REG_MAP_BASE_ADDR = 0, // Instance 0 register-map base.
  parameter bit [i2c_wrap_pkg::RegAddrWidth-1:0] I2C_0__REG_MAP_SIZE      = 0, // Per-instance register-map size.
  parameter bit [i2c_wrap_pkg::RegAddrWidth-1:0] I2C_INSTANCE_SPACING     = 0, // Byte spacing between instances.

  localparam int unsigned NumRegMaps = NUM_I2CS + 2,        // Decode targets: instances + ctrl +
                                                            // error slave.
  localparam type i2c_wrap_reg_map_select_t = logic [$clog2(NumRegMaps)-1:0], // Register-map select type.
  localparam i2c_wrap_reg_map_select_t CtrlRegMap =       // Select index for the ctrl map.
        i2c_wrap_reg_map_select_t'(NumRegMaps - 2),
  localparam i2c_wrap_reg_map_select_t UndefinedRegMap =  // Select index for the error slave.
        i2c_wrap_reg_map_select_t'(NumRegMaps - 1)
) (
  input  logic                clk_i,                        // System clock.
  input  logic                rst_ni,                       // Async reset, active-low.

  input  i2c_wrap_pkg::axil_req_t           axil_req_i,     // Shared AXI-Lite request.
  output i2c_wrap_pkg::axil_resp_t          axil_resp_o,    // Shared AXI-Lite response.

  output logic [NUM_I2CS-1:0] i2c_en_o,                     // Per-instance I2C_CTRL.I2C_EN value;
                                                            // not consumed by the I2C instance.
  output logic [NUM_I2CS-1:0] i2c_controller_mode_en_o,     // Per-instance
                                                            // I2C_CTRL.I2C_CONTROLLER_MODE_EN
                                                            // value; not consumed by the I2C
                                                            // instance.

  input  logic [NUM_I2CS-1:0] scl_i,                        // Per-instance SCL pad input,
                                                            // synchronized to clk_i inside each
                                                            // instance.
  output logic [NUM_I2CS-1:0] scl_o,                        // Per-instance SCL pad output; 0 pulls
                                                            // the line low, 1 releases it.
  input  logic [NUM_I2CS-1:0] sda_i,                        // Per-instance SDA pad input,
                                                            // synchronized to clk_i inside each
                                                            // instance.
  output logic [NUM_I2CS-1:0] sda_o,                        // Per-instance SDA pad output; 0 pulls
                                                            // the line low, 1 releases it.

  input  logic [NUM_I2CS-1:0] smbsus_ni,                    // Per-instance SMBus SUS in,
                                                            // active-low; synchronized and reported
                                                            // in SMBUS_STATUS.
  output logic [NUM_I2CS-1:0] smbsus_no,                    // Per-instance SMBus SUS out,
                                                            // active-low; high unless the instance
                                                            // is in host mode.
  input  logic [NUM_I2CS-1:0] smbalert_ni,                  // Per-instance SMBus ALERT in,
                                                            // active-low; masked while
                                                            // I2C_CTRL.SMBUS_EN is low.
  output logic [NUM_I2CS-1:0] smbalert_no,                  // Per-instance SMBus ALERT out,
                                                            // active-low; high unless the instance
                                                            // is in target mode.

  output logic [NUM_I2CS-1:0] controller_tx_ready_o,        // Per-instance controller TX DMA ready;
                                                            // low from FMT FIFO full until below
                                                            // threshold.
  output logic [NUM_I2CS-1:0] controller_rx_ready_o,        // Per-instance controller RX DMA ready;
                                                            // high from above RX threshold until
                                                            // empty.
  output logic [NUM_I2CS-1:0] target_tx_ready_o,            // Per-instance target TX DMA ready; low
                                                            // from TX FIFO full until below
                                                            // threshold.
  output logic [NUM_I2CS-1:0] target_rx_ready_o,            // Per-instance target RX DMA ready;
                                                            // high from above ACQ threshold until
                                                            // empty.

  output logic [NUM_I2CS-1:0] i2c_irq_o,                    // Per-instance level interrupt; OR of
                                                            // the enabled INTR_STATE sources.

  output logic [NUM_I2CS-1:0][3:0] i2c_debug_o              // Per-instance four-bit debug; see
                                                            // i2c_core.
);

  `include "axi/assign.svh"
  `include "prim_assert.sv"

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  logic [NUM_I2CS-1:0] smbus_en;

  i2c_wrap_pkg::axil_req_t  [NumRegMaps-1:0] axil_reqs;
  i2c_wrap_pkg::axil_resp_t [NumRegMaps-1:0] axil_resps;


  //////////////////////////////
  // AXI4-Lite Register Demux //
  //////////////////////////////

  i2c_wrap_reg_map_select_t axil_aw_select, axil_ar_select;

  always_comb begin
    axil_aw_select = UndefinedRegMap;

    if (axil_req_i.aw.addr >= I2C_CTRL_REG_MAP_BASE_ADDR &&
            axil_req_i.aw.addr <  I2C_CTRL_REG_MAP_BASE_ADDR +
                                  I2C_CTRL_REG_MAP_SIZE) begin
      axil_aw_select = CtrlRegMap;
    end else begin
      for (int i = 0; i < NUM_I2CS; i++) begin
        logic [i2c_wrap_pkg::RegAddrWidth-1:0] i2c_i_base_addr;
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
    axil_ar_select = UndefinedRegMap;

    if (axil_req_i.ar.addr >= I2C_CTRL_REG_MAP_BASE_ADDR &&
            axil_req_i.ar.addr <  I2C_CTRL_REG_MAP_BASE_ADDR +
                                  I2C_CTRL_REG_MAP_SIZE) begin
      axil_ar_select = CtrlRegMap;
    end else begin
      for (int i = 0; i < NUM_I2CS; i++) begin
        logic [i2c_wrap_pkg::RegAddrWidth-1:0] i2c_i_base_addr;
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
    .NoMstPorts      (NumRegMaps),
    .MaxTrans        (1),
    .FallThrough     (1'b0),
    .SpillAw         (1'b1),
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b1),
    .SpillR          (1'b0)
  ) u_axi_lite_demux (
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
    .AXI_ADDR_WIDTH (i2c_wrap_pkg::RegAddrWidth),
    .AXI_DATA_WIDTH (i2c_wrap_pkg::RegDataWidth),
    .axil_req_t     (i2c_wrap_pkg::axil_req_t),
    .axil_resp_t    (i2c_wrap_pkg::axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (i2c_wrap_pkg::RegDataWidth),
    .RESP_DATA      (32'hBADCAB1E),
    .MAX_TRANS      (1)
  ) u_prim_axi_lite_err_slv (
    .clk_i,
    .rst_ni,

    .axil_req_i     (axil_reqs [UndefinedRegMap]),
    .axil_resp_o    (axil_resps[UndefinedRegMap])
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
    ) u_i2c (
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

  i2c_ctrl_reg u_i2c_ctrl_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_resps[CtrlRegMap].aw_ready),
    .s_axil_awvalid (axil_reqs [CtrlRegMap].aw_valid),
    .s_axil_awaddr  (axil_reqs [CtrlRegMap].aw.addr[
                            i2c_ctrl_reg_pkg::I2C_CTRL_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_awprot  (axil_reqs [CtrlRegMap].aw.prot),
    .s_axil_wready  (axil_resps[CtrlRegMap].w_ready),
    .s_axil_wvalid  (axil_reqs [CtrlRegMap].w_valid),
    .s_axil_wdata   (axil_reqs [CtrlRegMap].w.data),
    .s_axil_wstrb   (axil_reqs [CtrlRegMap].w.strb),
    .s_axil_bready  (axil_reqs [CtrlRegMap].b_ready),
    .s_axil_bvalid  (axil_resps[CtrlRegMap].b_valid),
    .s_axil_bresp   (axil_resps[CtrlRegMap].b.resp),
    .s_axil_arready (axil_resps[CtrlRegMap].ar_ready),
    .s_axil_arvalid (axil_reqs [CtrlRegMap].ar_valid),
    .s_axil_araddr  (axil_reqs [CtrlRegMap].ar.addr[
                            i2c_ctrl_reg_pkg::I2C_CTRL_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_arprot  (axil_reqs [CtrlRegMap].ar.prot),
    .s_axil_rready  (axil_reqs [CtrlRegMap].r_ready),
    .s_axil_rvalid  (axil_resps[CtrlRegMap].r_valid),
    .s_axil_rdata   (axil_resps[CtrlRegMap].r.data),
    .s_axil_rresp   (axil_resps[CtrlRegMap].r.resp),

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
  `OCAH_OT_ASSERT_INIT(paramCheckMaxNumI2cs_A, NUM_I2CS <= i2c_wrap_pkg::MaxNumI2cs)

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
