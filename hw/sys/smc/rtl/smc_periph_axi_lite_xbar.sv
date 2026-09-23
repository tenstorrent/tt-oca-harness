// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SMC peripheral AXI-Lite crossbar.
//
// Hand-maintained: the fabric_gen source configs for this crossbar were not
// carried into the open tree, so it cannot be regenerated. AddrMap windows
// for reset_unit, misc, gpio, apb2avsbus, i2c, efuse_map, efuse_interface_ctrl,
// telemetry, and system_timer_octs derive from smc_top_addrmap_pkg so the RDL
// remains authoritative for those extents. Literal apertures are kept for uart,
// dtp_csr, and i3c (whose RDL SIZE already equals the window), and for
// efuse_shim (parametric) and external (non-RDL vendor region).
//
// ============================================================================
// ADDRESS MAP (RDL extents where narrowed; aperture retained otherwise)
// +────────────────────────+───────────+──────────────────+──────────────────+
// | Port                   | Protocol  |   Base Address   |   End Address    |
// +────────────────────────+───────────+──────────────────+──────────────────+
// | reset_unit             | AXI4_LITE | 0x0000_c000_2000 | 0x0000_c000_20cc |
// | misc                   | AXI4_LITE | 0x0000_c000_2800 | 0x0000_c000_2a0c |
// | gpio                   | AXI4_LITE | 0x0000_c000_3000 | 0x0000_c000_3410 |
// | apb2avsbus             | AXI4_LITE | 0x0000_c000_4000 | 0x0000_c000_405c |
// | i2c                    | AXI4_LITE | 0x0000_c000_5000 | 0x0000_c000_5e0c |
// | uart                   | AXI4_LITE | 0x0000_c000_6000 | 0x0000_c000_7000 |
// | efuse (SMC_EFUSE_MAP)  | AXI4_LITE | 0x0000_c000_7000 | 0x0000_c000_7400 |
// | efuse (INTF_CTRL)      | AXI4_LITE | 0x0000_c000_8000 | 0x0000_c000_801c |
// | telemetry              | AXI4_LITE | 0x0000_c000_9000 | 0x0000_c000_9300 |
// | system_timer_octs      | AXI4_LITE | 0x0000_c000_a000 | 0x0000_c000_a024 |
// | dtp_csr                | AXI4_LITE | 0x0000_c000_b000 | 0x0000_c000_b800 |
// | i3c                    | AXI4_LITE | 0x0000_c003_a000 | 0x0000_c004_0000 |
// | efuse (shim, param)    | AXI4_LITE | 0x0000_c040_0000 | 0x0000_c040_0000+EFUSE_SHIM_SIZE |
// | external               | AXI4_LITE | 0x0000_c040_0000+EFUSE_SHIM_SIZE | 0x0000_c080_0000 |
// +────────────────────────+───────────+──────────────────+──────────────────+
//
// ============================================================================
// CONNECTIVITY MATRIX
// +───────────+──────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────┬───────────────────+
// | Input     |     reset_unit    |        misc       |        gpio       |     apb2avsbus    |        i2c        |        uart       |       efuse       |     telemetry     | system_timer_octs |      dtp_csr      |        i3c        |      external     |
// +───────────+──────────────────┼───────────────────┼───────────────────┼───────────────────┼───────────────────┼───────────────────┼───────────────────┼───────────────────┼───────────────────┼───────────────────┼───────────────────┼───────────────────+
// | periph_in |        YES        |        YES        |        YES        |        YES        |        YES        |        YES        |        YES        |        YES        |        YES        |        YES        |        YES        |        YES        |
// +───────────+──────────────────┴───────────────────┴───────────────────┴───────────────────┴───────────────────┴───────────────────┴───────────────────┴───────────────────┴───────────────────┴───────────────────┴───────────────────┴───────────────────+

`include "axi/typedef.svh"
`include "axi/assign.svh"

module smc_periph_axi_lite_xbar
  import axi_pkg::*;
  import smc_periph_axi_lite_xbar_pkg::*;
#(
  // Vendor eFuse shim CSR block carved off the base of the smc_external window;
  // literal because the open smc_external map is opaque. Threaded from smc_peripherals.sv.
  parameter int unsigned EFUSE_SHIM_SIZE = 'h44
)
(
  input  logic clk_i,
  input  logic rst_ni,
  input  logic test_i,

  // ===========================================================================
  // Initiator Ports
  // ===========================================================================
  // periph_in (AXI4_LITE, 32-bit)
  input  axi_lite32_req_t  periph_in_req_i,
  output axi_lite32_resp_t periph_in_resp_o,

  // ===========================================================================
  // Target Ports
  // ===========================================================================
  // reset_unit (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  reset_unit_req_o,
  input  axi_lite32_resp_t reset_unit_resp_i,

  // misc (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  misc_req_o,
  input  axi_lite32_resp_t misc_resp_i,

  // gpio (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  gpio_req_o,
  input  axi_lite32_resp_t gpio_resp_i,

  // apb2avsbus (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  apb2avsbus_req_o,
  input  axi_lite32_resp_t apb2avsbus_resp_i,

  // i2c (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  i2c_req_o,
  input  axi_lite32_resp_t i2c_resp_i,

  // uart (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  uart_req_o,
  input  axi_lite32_resp_t uart_resp_i,

  // efuse (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  efuse_req_o,
  input  axi_lite32_resp_t efuse_resp_i,

  // telemetry (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  telemetry_req_o,
  input  axi_lite32_resp_t telemetry_resp_i,

  // system_timer_octs (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  system_timer_octs_req_o,
  input  axi_lite32_resp_t system_timer_octs_resp_i,

  // dtp_csr (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  dtp_csr_req_o,
  input  axi_lite32_resp_t dtp_csr_resp_i,

  // i3c (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  i3c_req_o,
  input  axi_lite32_resp_t i3c_resp_i,

  // external (AXI4_LITE, 32-bit)
  output axi_lite32_req_t  external_req_o,
  input  axi_lite32_resp_t external_resp_i

);

  // ===========================================================================
  // Address Map Configuration
  // ===========================================================================
  // Rules marked "RDL" use smc_top_addrmap_pkg symbols so the RDL is
  // authoritative for those decode windows. Rules marked "literal" keep the
  // spec aperture because the RDL SIZE already equals the window, or because
  // no RDL block backs the region.
  localparam addr_rule_t [NumAddrRules-1:0] AddrMap = '{
    // reset_unit: RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_{BASE_ADDR,SIZE}
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SIZE)},
    // misc: RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_{BASE_ADDR,SIZE}
    '{idx: 1,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SIZE)},
    // gpio: RDL — SMC_TOP_GPIO_INTF_BASE_ADDR(0)=0xC0003000, SMC_TOP_GPIO_INTF_TOTAL_SIZE=0x410
    '{idx: 2,
      start_addr: 32'hc0003000,
      end_addr:   33'(32'hc0003000 + smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_TOTAL_SIZE)},
    // apb2avsbus: RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_AVSBUS_CONTROLLER_{BASE_ADDR,SIZE}
    '{idx: 3,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_AVSBUS_CONTROLLER_SIZE)},
    // i2c: RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_{BASE_ADDR,SIZE}
    '{idx: 4,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_SIZE)},
    // uart: literal — RDL SIZE equals the 4 KiB aperture
    '{idx: 5, start_addr: 32'hc0006000, end_addr: 33'hc0007000},
    // efuse (SMC_EFUSE_MAP): RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_{BASE_ADDR,SIZE}
    '{idx: 6,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_EFUSE_MAP_SIZE)},
    // efuse (EFUSE_INTERFACE_CTRL): RDL — smc_top_addrmap_pkg::SMC_TOP_EFUSE_INTERFACE_CTRL_{BASE_ADDR,SIZE}
    '{idx: 6,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_EFUSE_INTERFACE_CTRL_SIZE)},
    // telemetry: RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_{BASE_ADDR,SIZE}
    '{idx: 7,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_SIZE)},
    // system_timer_octs: RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_SYSTEM_TIMER_OCTS_{BASE_ADDR,SIZE}
    '{idx: 8,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_SYSTEM_TIMER_OCTS_SIZE)},
    // dtp_csr: literal — RDL SIZE equals the 2 KiB aperture
    '{idx: 9, start_addr: 32'hc000b000, end_addr: 33'hc000b800},
    // i3c: literal — RDL TOTAL_SIZE equals the 24 KiB aperture
    '{idx: 10, start_addr: 32'hc003a000, end_addr: 33'hc0040000},
    // efuse_shim: parametric on EFUSE_SHIM_SIZE (vendor region; no RDL block)
    '{idx: 6, start_addr: 32'hc0400000, end_addr: 33'hc0400000 + 33'(EFUSE_SHIM_SIZE)},
    // external: literal — non-RDL vendor region after the shim
    '{idx: 11, start_addr: 32'hc0400000 + EFUSE_SHIM_SIZE, end_addr: 33'hc0800000}
  };

  // ===========================================================================
  // Input Protocol/Width Conversion (to match crossbar)
  // ===========================================================================
  xbar_slv_req_t  [0:0] xbar_slv_req;
  xbar_slv_resp_t [0:0] xbar_slv_resp;

  // Input periph_in: Direct connection (AXI4_LITE, 32-bit)
  assign xbar_slv_req[0] = periph_in_req_i;
  assign periph_in_resp_o = xbar_slv_resp[0];

  // ===========================================================================
  // Crossbar
  // ===========================================================================
  xbar_mst_req_t  [11:0] xbar_mst_req;
  xbar_mst_resp_t [11:0] xbar_mst_resp;

  axi_lite_xbar #(
    .Cfg          (XbarCfg),
    .aw_chan_t    (xbar_slv_aw_chan_t),
    .w_chan_t     (xbar_slv_w_chan_t),
    .b_chan_t     (xbar_slv_b_chan_t),
    .ar_chan_t    (xbar_slv_ar_chan_t),
    .r_chan_t     (xbar_slv_r_chan_t),
    .axi_req_t    (xbar_slv_req_t),
    .axi_resp_t   (xbar_slv_resp_t),
    .rule_t       (addr_rule_t)
  ) u_axi_lite_xbar (
    .clk_i                 (clk_i),
    .rst_ni                (rst_ni),
    .test_i                (test_i),
    .slv_ports_req_i       (xbar_slv_req),
    .slv_ports_resp_o      (xbar_slv_resp),
    .mst_ports_req_o       (xbar_mst_req),
    .mst_ports_resp_i      (xbar_mst_resp),
    .addr_map_i            (AddrMap),
    .en_default_mst_port_i ('0),
    .default_mst_port_i    ('0)
  );

  // ===========================================================================
  // Output Protocol/Width Conversion
  // ===========================================================================
  // ---------------------------------------------------------------------------
  // Output: reset_unit (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign reset_unit_req_o = xbar_mst_req[0];
  assign xbar_mst_resp[0] = reset_unit_resp_i;

  // ---------------------------------------------------------------------------
  // Output: misc (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign misc_req_o = xbar_mst_req[1];
  assign xbar_mst_resp[1] = misc_resp_i;

  // ---------------------------------------------------------------------------
  // Output: gpio (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign gpio_req_o = xbar_mst_req[2];
  assign xbar_mst_resp[2] = gpio_resp_i;

  // ---------------------------------------------------------------------------
  // Output: apb2avsbus (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign apb2avsbus_req_o = xbar_mst_req[3];
  assign xbar_mst_resp[3] = apb2avsbus_resp_i;

  // ---------------------------------------------------------------------------
  // Output: i2c (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign i2c_req_o = xbar_mst_req[4];
  assign xbar_mst_resp[4] = i2c_resp_i;

  // ---------------------------------------------------------------------------
  // Output: uart (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign uart_req_o = xbar_mst_req[5];
  assign xbar_mst_resp[5] = uart_resp_i;

  // ---------------------------------------------------------------------------
  // Output: efuse (AXI4_LITE, 32-bit) — serves both SMC_EFUSE_MAP and EFUSE_INTERFACE_CTRL rules
  // ---------------------------------------------------------------------------
  assign efuse_req_o = xbar_mst_req[6];
  assign xbar_mst_resp[6] = efuse_resp_i;

  // ---------------------------------------------------------------------------
  // Output: telemetry (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign telemetry_req_o = xbar_mst_req[7];
  assign xbar_mst_resp[7] = telemetry_resp_i;

  // ---------------------------------------------------------------------------
  // Output: system_timer_octs (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign system_timer_octs_req_o = xbar_mst_req[8];
  assign xbar_mst_resp[8] = system_timer_octs_resp_i;

  // ---------------------------------------------------------------------------
  // Output: dtp_csr (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign dtp_csr_req_o = xbar_mst_req[9];
  assign xbar_mst_resp[9] = dtp_csr_resp_i;

  // ---------------------------------------------------------------------------
  // Output: i3c (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign i3c_req_o = xbar_mst_req[10];
  assign xbar_mst_resp[10] = i3c_resp_i;

  // ---------------------------------------------------------------------------
  // Output: external (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  assign external_req_o = xbar_mst_req[11];
  assign xbar_mst_resp[11] = external_resp_i;

endmodule : smc_periph_axi_lite_xbar
