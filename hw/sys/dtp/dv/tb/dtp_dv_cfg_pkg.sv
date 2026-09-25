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
// Capabilities" table, PTAP document) and IDCODE.

package dtp_dv_cfg_pkg;

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

  localparam logic [10:0] IdcodeMfrId = 11'h000;
  localparam logic [15:0] IdcodePartNum = 16'h0000;
  localparam logic [3:0] IdcodeSiRev = 4'h0;
  localparam logic [7:0] OchVer = 8'h00;
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

endpackage : dtp_dv_cfg_pkg
