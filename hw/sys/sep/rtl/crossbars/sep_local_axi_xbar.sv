// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route SEP local AXI traffic among CPU, DMA, debug, and subsystem targets.
//
// DMA and watchdog address bounds come from och_sep_top_addrmap_pkg; the remaining address
// rules are explicit integration apertures in AddrMap below.
// Initiator and target ports are AXI4 with 64-bit data.

`include "axi/typedef.svh"
`include "axi/assign.svh"

module sep_local_axi_xbar
  import axi_pkg::*;
  import sep_local_axi_xbar_pkg::*;
(
  input  logic clk_i,                         // System clock.
  input  logic rst_ni,                        // Active-low reset.
  input  logic test_i,                        // axi_xbar test mode.

  input  axi64_req_t  ifu_sram_req_i,         // IFU SRAM initiator request (AXI4, 64-bit)
                                              // ifu_sram (AXI4, 64-bit).
  output axi64_resp_t ifu_sram_resp_o,        // IFU SRAM initiator response (AXI4, 64-bit).

  input  axi64_req_t  lsu_req_i,              // LSU initiator request (AXI4, 64-bit)
                                              // lsu (AXI4, 64-bit).
  output axi64_resp_t lsu_resp_o,             // LSU initiator response (AXI4, 64-bit).

  input  axi64_req_t  dbg_req_i,              // Debug initiator request (AXI4, 64-bit)
                                              // dbg (AXI4, 64-bit).
  output axi64_resp_t dbg_resp_o,             // Debug initiator response (AXI4, 64-bit).

  input  axi64_req_t  dma_req_i,              // DMA initiator request (AXI4, 64-bit)
                                              // dma (AXI4, 64-bit).
  output axi64_resp_t dma_resp_o,             // DMA initiator response (AXI4, 64-bit).

  input  axi64_req_t  ext_req_i,              // External initiator request (AXI4, 64-bit)
                                              // ext (AXI4, 64-bit).
  output axi64_resp_t ext_resp_o,             // External initiator response (AXI4, 64-bit).

  output axi_out_req_t  cpu_tcm_req_o,        // CPU TCM target request (AXI4, 64-bit)
                                              // cpu_tcm (AXI4, 64-bit).
  input  axi_out_resp_t cpu_tcm_resp_i,       // CPU TCM target response (AXI4, 64-bit).

  output axi_out_req_t  sram_req_o,           // SRAM target request (AXI4, 64-bit)
                                              // sram (AXI4, 64-bit).
  input  axi_out_resp_t sram_resp_i,          // SRAM target response (AXI4, 64-bit).

  output axi_out_req_t  dma_csr_req_o,        // DMA CSR target request (AXI4, 64-bit)
                                              // dma_csr (AXI4, 64-bit).
  input  axi_out_resp_t dma_csr_resp_i,       // DMA CSR target response (AXI4, 64-bit).

  output axi_out_req_t  sep_wdt_req_o,        // SEP WDT target request (AXI4, 64-bit)
                                              // sep_wdt (AXI4, 64-bit).
  input  axi_out_resp_t sep_wdt_resp_i,       // SEP WDT target response (AXI4, 64-bit).

  output axi_out_req_t  sep_reset_ctrl_req_o,  // SEP reset controller target request (AXI4, 64-bit)
                                               // sep_reset_ctrl (AXI4, 64-bit).
  input  axi_out_resp_t sep_reset_ctrl_resp_i,  // SEP reset controller target response (AXI4, 64-bit).

  output axi_out_req_t  sep_crypto_req_o,     // SEP crypto target request (AXI4, 64-bit)
                                              // sep_crypto (AXI4, 64-bit).
  input  axi_out_resp_t sep_crypto_resp_i,    // SEP crypto target response (AXI4, 64-bit).

  output axi_out_req_t  sep_system_peripherals_req_o,  // SEP system peripherals target request (AXI4, 64-bit)
                                                       // sep_system_peripherals (AXI4, 64-bit).
  input  axi_out_resp_t sep_system_peripherals_resp_i,  // SEP system peripherals target response (AXI4, 64-bit).

  output axi_out_req_t  sep_io_req_o,         // SEP IO target request (AXI4, 64-bit)
                                              // sep_io (AXI4, 64-bit).
  input  axi_out_resp_t sep_io_resp_i,        // SEP IO target response (AXI4, 64-bit).

  output axi_out_req_t  entropy_fifo_req_o,   // Entropy FIFO target request (AXI4, 64-bit)
                                              // entropy_fifo (AXI4, 64-bit).
  input  axi_out_resp_t entropy_fifo_resp_i,  // Entropy FIFO target response (AXI4, 64-bit).

  output axi_out_req_t  sep_external_req_o,   // SEP external aperture target request (AXI4, 64-bit)
                                              // sep_external (AXI4, 64-bit).
  input  axi_out_resp_t sep_external_resp_i   // SEP external aperture target response (AXI4, 64-bit).
);

  // ===========================================================================
  // Address Map Configuration
  // ===========================================================================
  localparam addr_rule_t [NumAddrRules-1:0] AddrMap = '{
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
      // dma_csr.main: secure_dma register extent, not the 4 kB spec aperture --
      // secure_dma_reg_top decodes 9 bits, so a wider window aliases.
      '{
          idx: 2,
          start_addr: 32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_SECURE_DMA_BASE_ADDR),
          end_addr:
          33'(
          och_sep_top_addrmap_pkg::OCH_SEP_TOP_SECURE_DMA_BASE_ADDR
          +
          och_sep_top_addrmap_pkg::OCH_SEP_TOP_SECURE_DMA_SIZE
          )
      },
      // sep_wdt.main: wdt_timer register extent, not the 4 kB spec aperture --
      // aon_timer_reg_top decodes 6 bits, so a wider window aliases.
      '{
          idx: 3,
          start_addr: 32'(och_sep_top_addrmap_pkg::OCH_SEP_TOP_WDT_TIMER_BASE_ADDR),
          end_addr:
          33'(
          och_sep_top_addrmap_pkg::OCH_SEP_TOP_WDT_TIMER_BASE_ADDR
          +
          och_sep_top_addrmap_pkg::OCH_SEP_TOP_WDT_TIMER_SIZE
          )
      },
      // sep_reset_ctrl.main: 0x10803000 - 0x10803008
      '{
          idx: 4,
          start_addr: 32'h10803000,
          end_addr: 33'h10803008
      },
      // sep_crypto.main: 0x10900000 - 0x10950000
      '{
          idx: 5,
          start_addr: 32'h10900000,
          end_addr: 33'h10950000
      },
      // sep_system_peripherals.scratch_region: 0x10802000 - 0x10802100
      '{
          idx: 6,
          start_addr: 32'h10802000,
          end_addr: 33'h10802100
      },
      // sep_system_peripherals.csr_region: 0x10a00000 - 0x10a60000
      '{
          idx: 6,
          start_addr: 32'h10a00000,
          end_addr: 33'h10a60000
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
      // sep_io.main: 0x10b00000 - 0x10bfffff
      '{
          idx: 7,
          start_addr: 32'h10b00000,
          end_addr: 33'h10bfffff
      },
      // entropy_fifo.main: 0x10950000 - 0x10960000
      '{
          idx: 8,
          start_addr: 32'h10950000,
          end_addr: 33'h10960000
      },
      // sep_external.main: 0x20000000 - 0x40000000
      '{
          idx: 9,
          start_addr: 32'h20000000,
          end_addr: 33'h40000000
      }
  };

  // ===========================================================================
  // Input Protocol/Width Conversion (to match crossbar)
  // ===========================================================================
  xbar_slv_req_t  [4:0] xbar_slv_req;
  xbar_slv_resp_t [4:0] xbar_slv_resp;

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
  xbar_mst_req_t  [9:0] xbar_mst_req;
  xbar_mst_resp_t [9:0] xbar_mst_resp;

  axi_xbar #(
    .Cfg          (XbarCfg),
    .ATOPs        (1'b0),
    .Connectivity (Connectivity),
    .slv_aw_chan_t(xbar_slv_aw_chan_t),
    .mst_aw_chan_t(xbar_mst_aw_chan_t),
    .w_chan_t     (xbar_slv_w_chan_t),
    .slv_b_chan_t (xbar_slv_b_chan_t),
    .mst_b_chan_t (xbar_mst_b_chan_t),
    .slv_ar_chan_t(xbar_slv_ar_chan_t),
    .mst_ar_chan_t(xbar_mst_ar_chan_t),
    .slv_r_chan_t (xbar_slv_r_chan_t),
    .mst_r_chan_t (xbar_mst_r_chan_t),
    .slv_req_t    (xbar_slv_req_t),
    .slv_resp_t   (xbar_slv_resp_t),
    .mst_req_t    (xbar_mst_req_t),
    .mst_resp_t   (xbar_mst_resp_t),
    .rule_t       (addr_rule_t)
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

endmodule : sep_local_axi_xbar
