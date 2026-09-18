// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef _I3C_COVERAGE_IF_SV_
`define _I3C_COVERAGE_IF_SV_

// I3C functional-coverage interface for the OCA I3C controller block.
// Observes the shared I3C bus (SDA/SCL), the OD/PP mode select, interrupts,
// and the AXI-Lite command/response ports.
//
// All covergroups are guarded by +define+I3C_COVERAGE so the interface always
// compiles (inert) when coverage is not requested.

interface i3c_coverage_if (
  input logic        clk,
  // I3C bus (shared, open-drain modeled in the TB)
  input logic        scl,
  input logic        sda,
  input logic        sel_od_pp,     // 0 = Open-Drain, 1 = Push-Pull
  input logic [1:0]  irq,
  // AXI-Lite write channel (command / data ports)
  input logic        awvalid,
  input logic        awready,
  input logic [31:0] awaddr,
  input logic        wvalid,
  input logic        wready,
  input logic [31:0] wdata,
  // AXI-Lite read channel (response / data ports)
  input logic        arvalid,
  input logic        arready,
  input logic [31:0] araddr,
  input logic        rvalid,
  input logic        rready,
  input logic [31:0] rdata
);

  // Per-instance address window used to recover a register offset from an AXI address.
  localparam int unsigned INSTANCE_SPACING =
        int'(oca_i3c_wrap_addrmap_pkg::OCA_I3C_WRAP_I3C_CSR_STRIDE);

  // Port offsets come from the generated address map, so a regeneration that moves
  // a port cannot leave this interface sampling a neighbouring register. The map
  // indexes by instance; index 0 gives the offset within any instance's window.
  localparam logic [11:0] COMMAND_PORT_OFF  =
        12'(oca_i3c_wrap_addrmap_pkg::OCA_I3C_WRAP_I3C_CSR_PIOCONTROL_COMMAND_PORT_BASE_ADDR(
      0
  ));
  localparam logic [11:0] RESPONSE_PORT_OFF =
        12'(oca_i3c_wrap_addrmap_pkg::OCA_I3C_WRAP_I3C_CSR_PIOCONTROL_RESPONSE_PORT_BASE_ADDR(
      0
  ));

  //***********************************************************************
  // Captured-transaction state
  //***********************************************************************
  logic [31:0] last_awaddr;
  logic [31:0] last_araddr;

  // Decoded command-descriptor fields (from cmd_lo / first COMMAND_PORT write)
  logic [2:0]  cmd_attr;
  logic [7:0]  cmd_ccc;
  logic        cmd_cp;
  logic        cmd_rnw;
  logic        cmd_toc;
  logic        cmd_sample;    // pulse when a command lo-word is captured
  logic        cmd_hi_phase;  // next COMMAND_PORT write carries the descriptor's high DWORD

  // Decoded response-descriptor fields
  logic [3:0]  resp_err;
  logic        resp_sample;   // pulse when a response word is read

  // Bus protocol events
  logic        sda_q;
  logic        start_evt;
  logic        stop_evt;

  function automatic logic [11:0] port_off(input logic [31:0] addr);
    return addr % INSTANCE_SPACING;
  endfunction

  //***********************************************************************
  // Capture AXI write address
  //***********************************************************************
  always @(posedge clk) begin
    if (awvalid && awready) last_awaddr <= awaddr;
    if (arvalid && arready) last_araddr <= araddr;
  end

  // AXI-Lite permits the write address and its data to handshake on the same cycle,
  // in which case last_awaddr still holds the previous transaction's address when the
  // data beat is observed. Qualify against the live address whenever one is handshaking.
  wire [31:0] wr_addr = (awvalid && awready) ? awaddr : last_awaddr;
  wire        cmd_port_write = wvalid && wready &&
                                 (port_off(wr_addr) == COMMAND_PORT_OFF);

  //***********************************************************************
  // Capture command-descriptor low word on COMMAND_PORT write
  //***********************************************************************
  // A command descriptor is 64 bits written as two DWORDs to the same address. Only
  // the first carries the decoded fields; the second is data and must not be sampled.
  always @(posedge clk) begin
    cmd_sample <= 1'b0;
    if (cmd_port_write) begin
      cmd_hi_phase <= ~cmd_hi_phase;
      if (!cmd_hi_phase) begin
        cmd_attr   <= wdata[2:0];
        cmd_ccc    <= wdata[14:7];
        cmd_cp     <= wdata[15];
        cmd_rnw    <= wdata[29];
        cmd_toc    <= wdata[31];
        cmd_sample <= 1'b1;
      end
    end
  end

  //***********************************************************************
  // Capture response-descriptor on RESPONSE_PORT read
  //***********************************************************************
  always @(posedge clk) begin
    resp_sample <= 1'b0;
    if (rvalid && rready && (port_off(last_araddr) == RESPONSE_PORT_OFF)) begin
      resp_err    <= rdata[31:28];   // err_status[31:28] (matches i3c_api / HCI response)
      resp_sample <= 1'b1;
    end
  end

  //***********************************************************************
  // Simple START/STOP detection (SDA edge while SCL high)
  //***********************************************************************
  always @(posedge clk) begin
    start_evt <= 1'b0;
    stop_evt  <= 1'b0;
    if (scl) begin
      if (sda_q && !sda) start_evt <= 1'b1;  // SDA fall while SCL high
      if (!sda_q && sda) stop_evt <= 1'b1;  // SDA rise while SCL high
    end
    sda_q <= sda;
  end

`ifdef I3C_COVERAGE
  //***********************************************************************
  // Covergroups
  //***********************************************************************

  // Command-descriptor coverage
  covergroup i3c_cmd_cg @(posedge cmd_sample);
    cp_attr: coverpoint cmd_attr {
      bins regular = {3'h0}; bins immediate = {3'h1}; bins addr_assign = {3'h2};
    }
    cp_cp: coverpoint cmd_cp {bins ccc = {1'b1}; bins priv = {1'b0};}
    cp_rnw: coverpoint cmd_rnw {bins write = {1'b0}; bins read = {1'b1};}
    cp_toc: coverpoint cmd_toc {bins term = {1'b1}; bins cont = {1'b0};}
    cp_ccc: coverpoint cmd_ccc iff (cmd_cp) {
      bins setdasa = {8'h87};
      bins setnewda = {8'h88};
      bins setmwl = {8'h89};
      bins setmrl = {8'h8A};
      bins getmwl = {8'h8B};
      bins getmrl = {8'h8C};
      bins getbcr = {8'h8E};
      bins rstact = {8'h9A};
      // Broadcast ENEC/DISEC are 0x00/0x01; the direct forms set bit 7.
      bins enec = {8'h00, 8'h80};
      bins disec = {8'h01, 8'h81};
      bins others = default;
    }
    cx_attr_rnw: cross cp_attr, cp_rnw;
  endgroup

  // Response coverage
  covergroup i3c_resp_cg @(posedge resp_sample);
    cp_err: coverpoint resp_err {
      bins success = {4'h0};
      bins crc = {4'h1};
      bins parity = {4'h2};
      bins frame = {4'h3};
      bins other = {[4'h4 : 4'hF]};
    }
  endgroup

  // Bus mode and protocol-event coverage
  covergroup i3c_bus_cg @(posedge start_evt or posedge stop_evt);
    cp_mode: coverpoint sel_od_pp {bins od = {1'b0}; bins pp = {1'b1};}
    cp_start: coverpoint start_evt {bins start = {1'b1};}
    cp_stop: coverpoint stop_evt {bins stop = {1'b1};}
  endgroup

  // Interrupt coverage
  covergroup i3c_irq_cg @(posedge clk);
    cp_irq0: coverpoint irq[0] {bins low = {1'b0}; bins high = {1'b1};}
    cp_irq1: coverpoint irq[1] {bins low = {1'b0}; bins high = {1'b1};}
  endgroup

  i3c_cmd_cg  cmd_cg;
  i3c_resp_cg resp_cg;
  i3c_bus_cg  bus_cg;
  i3c_irq_cg  irq_cg;

  initial begin
    cmd_cg  = new();
    resp_cg = new();
    bus_cg  = new();
    irq_cg  = new();
  end

  final begin
    $display("========================================");
    $display("I3C Coverage Interface Report");
    $display("  cmd_cg  = %0.2f%%", cmd_cg.get_inst_coverage());
    $display("  resp_cg = %0.2f%%", resp_cg.get_inst_coverage());
    $display("  bus_cg  = %0.2f%%", bus_cg.get_inst_coverage());
    $display("  irq_cg  = %0.2f%%", irq_cg.get_inst_coverage());
    $display("========================================");
  end
`endif  // I3C_COVERAGE

  // Initialize state
  initial begin
    last_awaddr = '0;
    last_araddr = '0;
    cmd_attr = '0;
    cmd_ccc = '0;
    cmd_cp = 1'b0;
    cmd_rnw = 1'b0;
    cmd_toc = 1'b0;
    cmd_sample = 1'b0;
    cmd_hi_phase = 1'b0;
    resp_err = '0;
    resp_sample = 1'b0;
    sda_q = 1'b1;
    start_evt = 1'b0;
    stop_evt = 1'b0;
  end

endinterface : i3c_coverage_if

`endif  // _I3C_COVERAGE_IF_SV_
