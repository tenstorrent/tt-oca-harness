// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route SEP local AXI traffic among CPU, DMA, debug, and subsystem targets.
//
// The DMA, watchdog, reset controller, SPI controller and scratch rules start at their
// sep_top_addrmap_pkg base and end on the 4 KiB page boundary after the registers; each of
// those targets answers every address in its page. The remaining address rules are explicit
// integration apertures in AddrMap below. The efuse_shim rule takes the EFUSE_SHIM_SIZE bytes
// at the base of the external aperture, and the sep_external rule the rest.
// Initiator and target ports are AXI4 with 64-bit data; target IDs carry three more bits
// than initiator IDs. Unmapped addresses and initiator-target pairs cleared in Connectivity
// get DECERR.

`include "axi/typedef.svh"
`include "axi/assign.svh"

module sep_local_axi_xbar
  import sep_local_axi_xbar_pkg::axi64_req_t;
  import sep_local_axi_xbar_pkg::axi64_resp_t;
  import sep_local_axi_xbar_pkg::axi_out_req_t;
  import sep_local_axi_xbar_pkg::axi_out_resp_t;
#(
  parameter int unsigned EFUSE_SHIM_SIZE = 'h4  // Size in bytes of the eFuse shim CSR window
                                                // at the base of the external aperture.
)
(
  input  logic clk_i,                         // System clock.
  input  logic rst_ni,                        // Active-low reset.
  input  logic test_i,                        // DFT test mode to axi_xbar.

  input  axi64_req_t  ifu_sram_req_i,         // IFU fetch request for SEP SRAM addresses from
                                              // sep_cpu; reaches only the sram target.
  output axi64_resp_t ifu_sram_resp_o,        // Response to ifu_sram; unmapped or unconnected
                                              // addresses get DECERR.

  input  axi64_req_t  lsu_req_i,              // LSU request from sep_cpu for addresses outside the
                                              // boot ROM; reaches every target except cpu_tcm.
  output axi64_resp_t lsu_resp_o,             // Response to lsu; unmapped or unconnected addresses
                                              // get DECERR.

  input  axi64_req_t  dbg_req_i,              // Debug-module system-bus request from sep_cpu;
                                              // reaches every target except cpu_tcm.
  output axi64_resp_t dbg_resp_o,             // Response to dbg; unmapped or unconnected addresses
                                              // get DECERR.

  input  axi64_req_t  dma_req_i,              // Secure DMA master request; reaches every target
                                              // except dma_csr and entropy_fifo.
  output axi64_resp_t dma_resp_o,             // Response to dma; unmapped or unconnected addresses
                                              // get DECERR.

  input  axi64_req_t  ext_req_i,              // Request forwarded by sep_system_peripherals;
                                              // reaches sram, dma_csr, sep_wdt, sep_crypto, sep_io,
                                              // entropy_fifo, sep_external and efuse_shim.
  output axi64_resp_t ext_resp_o,             // Response to ext; unmapped or unconnected addresses
                                              // get DECERR.

  output axi_out_req_t  cpu_tcm_req_o,        // Request for the ICCM (0xC000_0000-0xC003_FFFF) or
                                              // DCCM (0xC004_0000-0xC005_FFFF), to the core DMA
                                              // slave port.
  input  axi_out_resp_t cpu_tcm_resp_i,       // Response from the core DMA slave port.

  output axi_out_req_t  sram_req_o,           // Request for the SEP SRAM, 0x1000_0000-0x1003_FFFF.
  input  axi_out_resp_t sram_resp_i,          // Response from the SEP SRAM.

  output axi_out_req_t  dma_csr_req_o,        // Request for the secure DMA register page.
  input  axi_out_resp_t dma_csr_resp_i,       // Response from the secure DMA registers.

  output axi_out_req_t  sep_wdt_req_o,        // Request for the watchdog timer register page.
  input  axi_out_resp_t sep_wdt_resp_i,       // Response from the watchdog timer.

  output axi_out_req_t  sep_reset_ctrl_req_o,  // Request for the sep_reset_ctrl register page.
  input  axi_out_resp_t sep_reset_ctrl_resp_i,  // Response from sep_reset_ctrl.

  output axi_out_req_t  sep_crypto_req_o,     // Request for sep_crypto, 0x1090_0000-0x1094_FFFF.
  input  axi_out_resp_t sep_crypto_resp_i,    // Response from sep_crypto.

  output axi_out_req_t  sep_system_peripherals_req_o,  // Request for sep_system_peripherals:
                                                       // scratch 0x1080_2000-0x1080_2FFF, CSRs
                                                       // 0x10A0_0000-0x10A4_FFFF, remap window
                                                       // 0x1100_0000-0x11FF_FFFF, external chiplet
                                                       // 0x0000_0000-0x0FFF_FFFF, and SMU
                                                       // 0x4000_0000-0xBFFF_FFFF.
  input  axi_out_resp_t sep_system_peripherals_resp_i,  // Response from sep_system_peripherals.

  output axi_out_req_t  sep_io_req_o,         // Request for the SPI controller register page, to
                                              // sep_io.
  input  axi_out_resp_t sep_io_resp_i,        // Response from sep_io.

  output axi_out_req_t  entropy_fifo_req_o,   // Request for the entropy pool,
                                              // 0x1095_0000-0x1095_FFFF.
  input  axi_out_resp_t entropy_fifo_resp_i,  // Response from the entropy pool.

  output axi_out_req_t  sep_external_req_o,   // Request for the external aperture
                                              // 0x2000_0000-0x3FFF_FFFF above the eFuse shim
                                              // window, to sep.
  input  axi_out_resp_t sep_external_resp_i,  // Response from the external aperture.

  output axi_out_req_t  efuse_shim_req_o,     // Request for the eFuse shim CSR window, to
                                              // sep_crypto.
  input  axi_out_resp_t efuse_shim_resp_i     // Response from the eFuse shim CSR window.
);

  // ===========================================================================
  // Address Map Configuration
  // ===========================================================================
  localparam sep_local_axi_xbar_pkg::addr_rule_t [sep_local_axi_xbar_pkg::NumAddrRules-1:0] AddrMap = '{
      // cpu_tcm.iccm: 0xc0000000 - 0xc0040000
      '{
          idx: 0,
          start_addr: 32'hc0000000,
          end_addr: 33'hc0040000
      },
      // cpu_tcm.dccm: 0xc0040000 - 0xc0060000
      '{
          idx: 0,
          start_addr: 32'hc0040000,
          end_addr: 33'hc0060000
      },
      // sram.main: 0x10000000 - 0x10040000
      '{
          idx: 1,
          start_addr: 32'h10000000,
          end_addr: 33'h10040000
      },
      // dma_csr.main: the secure_dma page; sep_dma_wrap answers the addresses outside the
      // window secure_dma_reg_top decodes.
      '{
          idx: 2,
          start_addr: 32'(sep_top_addrmap_pkg::SEP_TOP_SECURE_DMA_BASE_ADDR),
          end_addr: 33'(sep_pkg::reg_page_end(sep_top_addrmap_pkg::SEP_TOP_SECURE_DMA_BASE_ADDR,
                                              sep_top_addrmap_pkg::SEP_TOP_SECURE_DMA_SIZE))
      },
      // sep_wdt.main: the wdt_timer page; sep_wdt_wrap answers the addresses outside the
      // window aon_timer_reg_top decodes.
      '{
          idx: 3,
          start_addr: 32'(sep_top_addrmap_pkg::SEP_TOP_WDT_TIMER_BASE_ADDR),
          end_addr: 33'(sep_pkg::reg_page_end(sep_top_addrmap_pkg::SEP_TOP_WDT_TIMER_BASE_ADDR,
                                              sep_top_addrmap_pkg::SEP_TOP_WDT_TIMER_SIZE))
      },
      // sep_reset_ctrl.main: the sep_reset_ctrl page, all of which its register block decodes.
      '{
          idx: 4,
          start_addr: 32'(sep_top_addrmap_pkg::SEP_TOP_SEP_RESET_CTRL_BASE_ADDR),
          end_addr: 33'(sep_pkg::reg_page_end(sep_top_addrmap_pkg::SEP_TOP_SEP_RESET_CTRL_BASE_ADDR,
                                              sep_top_addrmap_pkg::SEP_TOP_SEP_RESET_CTRL_SIZE))
      },
      // sep_crypto.main: 0x10900000 - 0x10950000
      '{
          idx: 5,
          start_addr: 32'h10900000,
          end_addr: 33'h10950000
      },
      // sep_system_peripherals.scratch_region: the scratch page; sep_system_csr answers the
      // addresses outside the cold and warm scratch windows.
      '{
          idx: 6,
          start_addr: 32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR),
          end_addr: 33'(sep_pkg::reg_page_end(sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_WARM_BASE_ADDR,
                                              sep_top_addrmap_pkg::SEP_TOP_SEP_SCRATCH_WARM_SIZE))
      },
      // sep_system_peripherals.csr_region: 0x10a00000 - 0x10a50000
      '{
          idx: 6,
          start_addr: 32'h10a00000,
          end_addr: 33'h10a50000
      },
      // sep_system_peripherals.remap_region: 0x11000000 - 0x12000000
      '{
          idx: 6,
          start_addr: 32'h11000000,
          end_addr: 33'h12000000
      },
      // sep_system_peripherals.external_chiplet: 0x00000000 - 0x10000000
      '{
          idx: 6,
          start_addr: 32'h0,
          end_addr: 33'h10000000
      },
      // sep_system_peripherals.external_smu: 0x40000000 - 0xc0000000
      '{
          idx: 6,
          start_addr: 32'h40000000,
          end_addr: 33'hc0000000
      },
      // sep_io.main: the spi_controller page; sep_io answers the addresses outside the window
      // spi_host_reg_top decodes.
      '{
          idx: 7,
          start_addr: 32'(sep_top_addrmap_pkg::SEP_TOP_SPI_CONTROLLER_BASE_ADDR),
          end_addr: 33'(sep_pkg::reg_page_end(sep_top_addrmap_pkg::SEP_TOP_SPI_CONTROLLER_BASE_ADDR,
                                              sep_top_addrmap_pkg::SEP_TOP_SPI_CONTROLLER_SIZE))
      },
      // entropy_fifo.main: 0x10950000 - 0x10960000
      '{
          idx: 8,
          start_addr: 32'h10950000,
          end_addr: 33'h10960000
      },
      // sep_external.main: above the eFuse shim window - 0x40000000
      '{
          idx: 9,
          start_addr: 32'(sep_top_addrmap_pkg::SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_BASE_ADDR
                          + EFUSE_SHIM_SIZE),
          end_addr: 33'h40000000
      },
      // efuse_shim.main: the EFUSE_SHIM_SIZE bytes at the base of the external aperture
      '{
          idx: 10,
          start_addr: 32'(sep_top_addrmap_pkg::SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_BASE_ADDR),
          end_addr: 33'(sep_top_addrmap_pkg::SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_BASE_ADDR
                        + EFUSE_SHIM_SIZE)
      }
  };

  // ===========================================================================
  // Input Protocol/Width Conversion (to match crossbar)
  // ===========================================================================
  sep_local_axi_xbar_pkg::xbar_slv_req_t  [4:0] xbar_slv_req;
  sep_local_axi_xbar_pkg::xbar_slv_resp_t [4:0] xbar_slv_resp;

  // Input ifu_sram: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[0] = ifu_sram_req_i;
  assign ifu_sram_resp_o = xbar_slv_resp[0];

  // Input lsu: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[1] = lsu_req_i;
  assign lsu_resp_o = xbar_slv_resp[1];

  // Input dbg: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[2] = dbg_req_i;
  assign dbg_resp_o = xbar_slv_resp[2];

  // Input dma: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[3] = dma_req_i;
  assign dma_resp_o = xbar_slv_resp[3];

  // Input ext: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[4] = ext_req_i;
  assign ext_resp_o = xbar_slv_resp[4];

  // ===========================================================================
  // Crossbar
  // ===========================================================================
  sep_local_axi_xbar_pkg::xbar_mst_req_t  [10:0] xbar_mst_req;
  sep_local_axi_xbar_pkg::xbar_mst_resp_t [10:0] xbar_mst_resp;

  axi_xbar #(
    .Cfg          (sep_local_axi_xbar_pkg::XbarCfg),
    .ATOPs        (1'b0),
    .Connectivity (sep_local_axi_xbar_pkg::Connectivity),
    .slv_aw_chan_t(sep_local_axi_xbar_pkg::xbar_slv_aw_chan_t),
    .mst_aw_chan_t(sep_local_axi_xbar_pkg::xbar_mst_aw_chan_t),
    .w_chan_t     (sep_local_axi_xbar_pkg::xbar_slv_w_chan_t),
    .slv_b_chan_t (sep_local_axi_xbar_pkg::xbar_slv_b_chan_t),
    .mst_b_chan_t (sep_local_axi_xbar_pkg::xbar_mst_b_chan_t),
    .slv_ar_chan_t(sep_local_axi_xbar_pkg::xbar_slv_ar_chan_t),
    .mst_ar_chan_t(sep_local_axi_xbar_pkg::xbar_mst_ar_chan_t),
    .slv_r_chan_t (sep_local_axi_xbar_pkg::xbar_slv_r_chan_t),
    .mst_r_chan_t (sep_local_axi_xbar_pkg::xbar_mst_r_chan_t),
    .slv_req_t    (sep_local_axi_xbar_pkg::xbar_slv_req_t),
    .slv_resp_t   (sep_local_axi_xbar_pkg::xbar_slv_resp_t),
    .mst_req_t    (sep_local_axi_xbar_pkg::xbar_mst_req_t),
    .mst_resp_t   (sep_local_axi_xbar_pkg::xbar_mst_resp_t),
    .rule_t       (sep_local_axi_xbar_pkg::addr_rule_t)
  ) u_axi_xbar (
    .clk_i                 (clk_i),
    .rst_ni                (rst_ni),
    .test_i                (test_i),
    .sel_hash_i            (2'b0),
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
  // Output: cpu_tcm (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign cpu_tcm_req_o = xbar_mst_req[0];
  assign xbar_mst_resp[0] = cpu_tcm_resp_i;

  // ---------------------------------------------------------------------------
  // Output: sram (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign sram_req_o = xbar_mst_req[1];
  assign xbar_mst_resp[1] = sram_resp_i;

  // ---------------------------------------------------------------------------
  // Output: dma_csr (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign dma_csr_req_o = xbar_mst_req[2];
  assign xbar_mst_resp[2] = dma_csr_resp_i;

  // ---------------------------------------------------------------------------
  // Output: sep_wdt (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign sep_wdt_req_o = xbar_mst_req[3];
  assign xbar_mst_resp[3] = sep_wdt_resp_i;

  // ---------------------------------------------------------------------------
  // Output: sep_reset_ctrl (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign sep_reset_ctrl_req_o = xbar_mst_req[4];
  assign xbar_mst_resp[4] = sep_reset_ctrl_resp_i;

  // ---------------------------------------------------------------------------
  // Output: sep_crypto (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign sep_crypto_req_o = xbar_mst_req[5];
  assign xbar_mst_resp[5] = sep_crypto_resp_i;

  // ---------------------------------------------------------------------------
  // Output: sep_system_peripherals (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign sep_system_peripherals_req_o = xbar_mst_req[6];
  assign xbar_mst_resp[6] = sep_system_peripherals_resp_i;

  // ---------------------------------------------------------------------------
  // Output: sep_io (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign sep_io_req_o = xbar_mst_req[7];
  assign xbar_mst_resp[7] = sep_io_resp_i;

  // ---------------------------------------------------------------------------
  // Output: entropy_fifo (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign entropy_fifo_req_o = xbar_mst_req[8];
  assign xbar_mst_resp[8] = entropy_fifo_resp_i;

  // ---------------------------------------------------------------------------
  // Output: sep_external (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign sep_external_req_o = xbar_mst_req[9];
  assign xbar_mst_resp[9] = sep_external_resp_i;

  // ---------------------------------------------------------------------------
  // Output: efuse_shim (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  // Direct connection (no conversion needed)
  assign efuse_shim_req_o = xbar_mst_req[10];
  assign xbar_mst_resp[10] = efuse_shim_resp_i;

endmodule : sep_local_axi_xbar
