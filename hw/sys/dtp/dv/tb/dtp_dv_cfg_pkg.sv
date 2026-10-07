// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP bench configuration: the parameters tb_top elaborates the DUT with and
// the values the capability and identification scenarios expect the DUT to
// publish. Both realizations read this one table, SV-UVM through
// dtp_types.svh and cocotb through cocotb/env/dtp_dv_cfg.py; dtp_tb_if
// exposes the values so the cocotb bring-up rejects a divergent copy.
//
// The cross-trigger port counts come from the generated network address map,
// one CTP window per external port and one CTM source register per port,
// which the cross-trigger network document's parameter table states as
// NUM_CTP 16 and NUM_INT_CT 10; the clock-stop request count is that table's
// NUM_CLK_STOP_REQ. INT_CT_MODE '0 runs every internal port in pulse mode,
// where the acknowledge signals are unused. The STAP count, the IC_RESET
// slice widths, the instruction enables, the IDCODE fields, and the version
// are the bench's choice; the DUT publishes them through JTAG_CAPS ("JTAG
// Capabilities" table, PTAP document) and IDCODE. tb_top wires one extra STAP
// and one-bit IC_RESET slices and stops elaboration on any other count. The
// IDCODE fields and the version differ from the dtp parameter defaults, so a
// DUT that drops a parameter publishes a value the bench does not expect.
//
// The SMC fabric JTAG2AXI bridge drives SMC jtag_axi_in_req_i, whose row in
// the SMC port table states a 56-bit address, 64-bit data, a 2-bit ID, and a
// 12-bit user field. tb_top drives the response IDs from 2-bit slices and
// stops elaboration on any other ID width. The OTP bridges' AXI-Lite widths
// and every bridge's read and write pipeline depth are the bench's choice;
// each bridge publishes its bus type, widths, and depths through its
// *_JTAG2AXI_CAPS TDR ("PTAP JTAG2AXI capability fields" table, PTAP
// document). The depths differ per bridge and per direction, so a CAPS field
// wired to the wrong parameter reads back a value the bench does not expect.

package dtp_dv_cfg_pkg;

  `include "axi/typedef.svh"

  // Cross-trigger geometry.
  localparam int unsigned NumCtp =
      int'(cross_trigger_network_addrmap_pkg::CROSS_TRIGGER_NETWORK_CTP_NUM);
  localparam int unsigned NumCtmPorts =
      int'(cross_trigger_network_addrmap_pkg::CROSS_TRIGGER_NETWORK_CTM_CT_SRC_NUM);
  localparam int unsigned NumIntCt = NumCtmPorts - NumCtp;
  localparam int unsigned NumClkStopReq = 9;
  localparam logic [NumIntCt-1:0] IntCtMode = '0;

  // Wire-OR shared-wire polarity per CONFIG.INVERT (cross_trigger_port.rdl),
  // bit index = INVERT: INVERT=0 is an active-low wire with a pull-up, INVERT=1
  // an active-high wire with a pull-down. A port receives a trigger when its
  // synchronized wire moves from the pull level to the asserted level.
  localparam logic [1:0] WireOrPull = 2'b01;
  localparam logic [1:0] WireOrAssert = 2'b10;
  // Clock edges from the edge at which a wire-OR receive input moves to the
  // edge at which the port's ct_dst is high: the two synchronizer stages and
  // the registered ct_dst output.
  localparam int unsigned CtDstLatency = 3;

  // JTAG interface unit and PTAP configuration.
  localparam int unsigned NumExtraStaps = 1;
  localparam bit BsrEnable = 1'b1;
  localparam bit ExtestTrainEnable = 1'b1;
  localparam bit ExtestPulseEnable = 1'b1;
  localparam bit IntestEnable = 1'b1;
  localparam bit ClampEnable = 1'b1;
  localparam bit HighzEnable = 1'b1;
  localparam bit RunbistEnable = 1'b1;
  localparam bit TmpEnable = 1'b1;
  localparam bit IcResetSmcEnable = 1'b1;
  localparam bit IcResetExtEnable = 1'b1;
  localparam bit SmcDbgEnable = 1'b1;
  localparam bit StapIoEnable = 1'b1;
  // dtp declares the SEP-gated enables int unsigned.
  localparam int unsigned IcResetSepEnable = 1;
  localparam int unsigned SepDbgEnable = 1;

  localparam logic [10:0] IdcodeMfrId = 11'h2A5;
  localparam logic [15:0] IdcodePartNum = 16'hD7B1;
  localparam logic [3:0] IdcodeSiRev = 4'h9;
  localparam logic [7:0] OchVer = 8'h5C;
  // IEEE 1149.1 device identification: version, part number, manufacturer,
  // and the fixed marker bit.
  localparam logic [31:0] Idcode = {IdcodeSiRev, IdcodePartNum, IdcodeMfrId, 1'b1};

  // One IC_RESET override port per slice. Every slice type carries `.ovrd`
  // and `.val` of the same width (PTAP document, IC_RESET Support).
  localparam int unsigned NumSmcIcReset = 1;
  localparam int unsigned NumSepIcReset = 1;
  localparam int unsigned NumExtIcReset = 1;

  typedef struct packed {
    logic [NumSmcIcReset-1:0] ovrd;
    logic [NumSmcIcReset-1:0] val;
  } ic_reset_smc_t;

  typedef struct packed {
    logic [NumSepIcReset-1:0] ovrd;
    logic [NumSepIcReset-1:0] val;
  } ic_reset_sep_t;

  typedef struct packed {
    logic [NumExtIcReset-1:0] ovrd;
    logic [NumExtIcReset-1:0] val;
  } ic_reset_ext_t;

  // JTAG2AXI bridge geometry.
  localparam int unsigned SmcAxiAddrWidth = 56;
  localparam int unsigned SmcAxiDataWidth = 64;
  localparam int unsigned SmcAxiIdWidth = 2;
  localparam int unsigned SmcAxiUserWidth = 12;
  localparam int unsigned OtpAxilAddrWidth = 32;
  localparam int unsigned OtpAxilDataWidth = 32;

  localparam logic [1:0] SmcOtpRdPlDepth = 2'd2;
  localparam logic [1:0] SmcOtpWrPlDepth = 2'd1;
  localparam logic [1:0] SepOtpRdPlDepth = 2'd3;
  localparam logic [1:0] SepOtpWrPlDepth = 2'd2;
  localparam logic [1:0] SmcRdPlDepth = 2'd3;
  localparam logic [1:0] SmcWrPlDepth = 2'd0;

  typedef logic [SmcAxiAddrWidth-1:0] smc_axi_addr_t;
  typedef logic [SmcAxiIdWidth-1:0] smc_axi_id_t;
  typedef logic [SmcAxiDataWidth-1:0] smc_axi_data_t;
  typedef logic [SmcAxiDataWidth/8-1:0] smc_axi_strb_t;
  typedef logic [SmcAxiUserWidth-1:0] smc_axi_user_t;
  `AXI_TYPEDEF_ALL(smc_axi, smc_axi_addr_t, smc_axi_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)

  typedef logic [OtpAxilAddrWidth-1:0] otp_axil_addr_t;
  typedef logic [OtpAxilDataWidth-1:0] otp_axil_data_t;
  typedef logic [OtpAxilDataWidth/8-1:0] otp_axil_strb_t;
  `AXI_LITE_TYPEDEF_ALL(otp_axil, otp_axil_addr_t, otp_axil_data_t, otp_axil_strb_t)

endpackage : dtp_dv_cfg_pkg
