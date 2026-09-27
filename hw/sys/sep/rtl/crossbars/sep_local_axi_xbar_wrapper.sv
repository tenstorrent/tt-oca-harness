// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Adapt sep_pkg AXI structs to the local crossbar request and response types.
//
// Initiator (slave-into-xbar) ports use 3-bit ID masters. Target (master-from-xbar) ports
// use 6-bit ID slaves. The crossbar test mode is tied to 0.

`include "axi/typedef.svh"
`include "axi/assign.svh"
`include "ocah_assert.svh"

module sep_local_axi_xbar_wrapper (
  input  logic                                clk_i,  // System clock.
  input  logic                                rst_ni,  // Active-low reset.

  input  sep_pkg::sep_32_64_3_12_axi_req_t     ifu_sram_axi_req_i,  // IFU fetch request for SEP SRAM addresses from
                                                                    // sep_cpu; reaches only the sram target.
  output sep_pkg::sep_32_64_3_12_axi_resp_t    ifu_sram_axi_resp_o,  // Response to ifu_sram; unmapped or unconnected
                                                                     // addresses get DECERR.
  input  sep_pkg::sep_32_64_3_12_axi_req_t     lsu_axi_req_i,  // LSU request from sep_cpu for
                                                               // addresses outside the boot ROM;
                                                               // reaches every target except
                                                               // cpu_tcm.
  output sep_pkg::sep_32_64_3_12_axi_resp_t    lsu_axi_resp_o,  // Response to lsu; unmapped or
                                                                // unconnected addresses get DECERR.
  input  sep_pkg::sep_32_64_3_12_axi_req_t     dbg_axi_req_i,  // Debug-module system-bus request
                                                               // from sep_cpu; reaches every target
                                                               // except cpu_tcm.
  output sep_pkg::sep_32_64_3_12_axi_resp_t    dbg_axi_resp_o,  // Response to dbg; unmapped or
                                                                // unconnected addresses get DECERR.
  input  sep_pkg::sep_32_64_3_12_axi_req_t     dma_axi_req_i,  // Secure DMA master request; reaches
                                                               // every target except dma_csr and
                                                               // entropy_fifo.
  output sep_pkg::sep_32_64_3_12_axi_resp_t    dma_axi_resp_o,  // Response to dma; unmapped or
                                                                // unconnected addresses get DECERR.
  input  sep_pkg::sep_32_64_3_12_axi_req_t     ext_axi_req_i,  // Request forwarded by
                                                               // sep_system_peripherals; reaches
                                                               // sram, dma_csr, sep_wdt,
                                                               // sep_crypto, sep_io, entropy_fifo
                                                               // and sep_external.
  output sep_pkg::sep_32_64_3_12_axi_resp_t    ext_axi_resp_o,  // Response to ext; unmapped or
                                                                // unconnected addresses get DECERR.
  output sep_pkg::sep_32_64_6_12_axi_req_t     cpu_tcm_axi_req_o,  // Request for the ICCM
                                                                   // (0xC000_0000-0xC003_FFFF) or
                                                                   // DCCM
                                                                   // (0xC004_0000-0xC005_FFFF), to
                                                                   // the core DMA slave port.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    cpu_tcm_axi_resp_i,  // Response from the core DMA slave port.
  output sep_pkg::sep_32_64_6_12_axi_req_t     dma_csr_axi_req_o,  // Request for the secure DMA
                                                                   // register extent from
                                                                   // och_sep_top_addrmap_pkg.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    dma_csr_axi_resp_i,  // Response from the secure DMA registers.
  output sep_pkg::sep_32_64_6_12_axi_req_t     sram_axi_req_o,  // Request for the SEP SRAM,
                                                                // 0x1000_0000-0x1003_FFFF.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    sram_axi_resp_i,  // Response from the SEP SRAM.

  output sep_pkg::sep_32_64_6_12_axi_req_t     sep_crypto_axi_req_o,  // Request for sep_crypto,
                                                                      // 0x1090_0000-0x1094_FFFF.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    sep_crypto_axi_resp_i,  // Response from sep_crypto.

  output sep_pkg::sep_32_64_6_12_axi_req_t     sep_io_axi_req_o,  // Request for sep_io,
                                                                  // 0x10B0_0000-0x10BF_FFFE.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    sep_io_axi_resp_i,  // Response from sep_io.

  output sep_pkg::sep_32_64_6_12_axi_req_t     entropy_fifo_axi_req_o,  // Request for the entropy pool,
                                                                        // 0x1095_0000-0x1095_FFFF.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    entropy_fifo_axi_resp_i,  // Response from the entropy pool.

  output sep_pkg::sep_32_64_6_12_axi_req_t     sep_system_peripherals_axi_req_o,  // Request for sep_system_peripherals:
                                                                                  // scratch 0x1080_2000-0x1080_20FF, CSRs
                                                                                  // 0x10A0_0000-0x10A5_FFFF, remap window
                                                                                  // 0x1100_0000-0x11FF_FFFF, external
                                                                                  // chiplet 0x0000_0000-0x0FFF_FFFF, and SMU
                                                                                  // 0x4000_0000-0xBFFF_FFFF.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    sep_system_peripherals_axi_resp_i,  // Response from sep_system_peripherals.

  output sep_pkg::sep_32_64_6_12_axi_req_t     sep_wdt_axi_req_o,  // Request for the watchdog timer
                                                                   // register extent from
                                                                   // och_sep_top_addrmap_pkg.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    sep_wdt_axi_resp_i,  // Response from the watchdog timer.

  output sep_pkg::sep_32_64_6_12_axi_req_t     sep_reset_ctrl_axi_req_o,  // Request for sep_reset_ctrl,
                                                                          // 0x1080_3000-0x1080_3007.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    sep_reset_ctrl_axi_resp_i,  // Response from sep_reset_ctrl.

  output sep_pkg::sep_32_64_6_12_axi_req_t     sep_external_axi_req_o,  // Request for the external aperture
                                                                        // 0x2000_0000-0x3FFF_FFFF, to sep.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t    sep_external_axi_resp_i  // Response from the external aperture.
);

  // =========================================================================
  // Internal signals using xbar package types
  // =========================================================================

  // Initiator ports (inputs to xbar) - 3-bit ID
  sep_local_axi_xbar_pkg::axi64_req_t  ifu_sram_req;
  sep_local_axi_xbar_pkg::axi64_resp_t ifu_sram_resp;
  sep_local_axi_xbar_pkg::axi64_req_t  lsu_req;
  sep_local_axi_xbar_pkg::axi64_resp_t lsu_resp;
  sep_local_axi_xbar_pkg::axi64_req_t  dbg_req;
  sep_local_axi_xbar_pkg::axi64_resp_t dbg_resp;
  sep_local_axi_xbar_pkg::axi64_req_t  dma_req;
  sep_local_axi_xbar_pkg::axi64_resp_t dma_resp;
  sep_local_axi_xbar_pkg::axi64_req_t  ext_req;
  sep_local_axi_xbar_pkg::axi64_resp_t ext_resp;

  // Target ports (outputs from xbar) - 6-bit ID
  sep_local_axi_xbar_pkg::axi_out_req_t  cpu_tcm_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t cpu_tcm_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  sram_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t sram_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  dma_csr_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t dma_csr_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  sep_wdt_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t sep_wdt_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  sep_reset_ctrl_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t sep_reset_ctrl_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  sep_crypto_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t sep_crypto_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  sep_system_peripherals_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t sep_system_peripherals_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  sep_io_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t sep_io_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  entropy_fifo_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t entropy_fifo_resp;
  sep_local_axi_xbar_pkg::axi_out_req_t  sep_external_req;
  sep_local_axi_xbar_pkg::axi_out_resp_t sep_external_resp;
  // =========================================================================
  // Input port assignments (sep_pkg -> xbar_pkg)
  // All input ports have 3-bit ID, 32-bit addr, 64-bit data, 12-bit user
  // =========================================================================

  // IFU
  `AXI_ASSIGN_REQ_STRUCT(ifu_sram_req, ifu_sram_axi_req_i)
  `AXI_ASSIGN_RESP_STRUCT(ifu_sram_axi_resp_o, ifu_sram_resp)

  // LSU
  `AXI_ASSIGN_REQ_STRUCT(lsu_req, lsu_axi_req_i)
  `AXI_ASSIGN_RESP_STRUCT(lsu_axi_resp_o, lsu_resp)

  // DBG
  `AXI_ASSIGN_REQ_STRUCT(dbg_req, dbg_axi_req_i)
  `AXI_ASSIGN_RESP_STRUCT(dbg_axi_resp_o, dbg_resp)

  // DMA
  `AXI_ASSIGN_REQ_STRUCT(dma_req, dma_axi_req_i)
  `AXI_ASSIGN_RESP_STRUCT(dma_axi_resp_o, dma_resp)

  // EXT
  `AXI_ASSIGN_REQ_STRUCT(ext_req, ext_axi_req_i)
  `AXI_ASSIGN_RESP_STRUCT(ext_axi_resp_o, ext_resp)

  // =========================================================================
  // Output port assignments (xbar_pkg -> sep_pkg)
  // All output ports have 6-bit ID, 32-bit addr, 64-bit data, 12-bit user
  // =========================================================================

  // cpu_tcm
  `AXI_ASSIGN_REQ_STRUCT(cpu_tcm_axi_req_o, cpu_tcm_req)
  `AXI_ASSIGN_RESP_STRUCT(cpu_tcm_resp, cpu_tcm_axi_resp_i)

  // sram
  `AXI_ASSIGN_REQ_STRUCT(sram_axi_req_o, sram_req)
  `AXI_ASSIGN_RESP_STRUCT(sram_resp, sram_axi_resp_i)

  // dma_csr
  `AXI_ASSIGN_REQ_STRUCT(dma_csr_axi_req_o, dma_csr_req)
  `AXI_ASSIGN_RESP_STRUCT(dma_csr_resp, dma_csr_axi_resp_i)

  // sep_wdt
  `AXI_ASSIGN_REQ_STRUCT(sep_wdt_axi_req_o, sep_wdt_req)
  `AXI_ASSIGN_RESP_STRUCT(sep_wdt_resp, sep_wdt_axi_resp_i)

  // sep_reset_ctrl
  `AXI_ASSIGN_REQ_STRUCT(sep_reset_ctrl_axi_req_o, sep_reset_ctrl_req)
  `AXI_ASSIGN_RESP_STRUCT(sep_reset_ctrl_resp, sep_reset_ctrl_axi_resp_i)

  // sep_crypto
  `AXI_ASSIGN_REQ_STRUCT(sep_crypto_axi_req_o, sep_crypto_req)
  `AXI_ASSIGN_RESP_STRUCT(sep_crypto_resp, sep_crypto_axi_resp_i)

  // sep_system_peripherals
  `AXI_ASSIGN_REQ_STRUCT(sep_system_peripherals_axi_req_o, sep_system_peripherals_req)
  `AXI_ASSIGN_RESP_STRUCT(sep_system_peripherals_resp, sep_system_peripherals_axi_resp_i)

  // sep_io
  `AXI_ASSIGN_REQ_STRUCT(sep_io_axi_req_o, sep_io_req)
  `AXI_ASSIGN_RESP_STRUCT(sep_io_resp, sep_io_axi_resp_i)

  // entropy_fifo
  `AXI_ASSIGN_REQ_STRUCT(entropy_fifo_axi_req_o, entropy_fifo_req)
  `AXI_ASSIGN_RESP_STRUCT(entropy_fifo_resp, entropy_fifo_axi_resp_i)

  // sep_external
  `AXI_ASSIGN_REQ_STRUCT(sep_external_axi_req_o, sep_external_req)
  `AXI_ASSIGN_RESP_STRUCT(sep_external_resp, sep_external_axi_resp_i)

  // =========================================================================
  // Crossbar
  // =========================================================================
  sep_local_axi_xbar u_sep_local_axi_xbar (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .test_i (1'b0),

    // Initiator ports
    .ifu_sram_req_i  (ifu_sram_req),
    .ifu_sram_resp_o (ifu_sram_resp),
    .lsu_req_i       (lsu_req),
    .lsu_resp_o      (lsu_resp),
    .dbg_req_i       (dbg_req),
    .dbg_resp_o      (dbg_resp),
    .dma_req_i       (dma_req),
    .dma_resp_o      (dma_resp),
    .ext_req_i       (ext_req),
    .ext_resp_o      (ext_resp),

    // Target ports
    .cpu_tcm_req_o                       (cpu_tcm_req),
    .cpu_tcm_resp_i                      (cpu_tcm_resp),
    .sram_req_o                          (sram_req),
    .sram_resp_i                         (sram_resp),
    .dma_csr_req_o                       (dma_csr_req),
    .dma_csr_resp_i                      (dma_csr_resp),
    .sep_wdt_req_o                       (sep_wdt_req),
    .sep_wdt_resp_i                      (sep_wdt_resp),
    .sep_reset_ctrl_req_o                (sep_reset_ctrl_req),
    .sep_reset_ctrl_resp_i               (sep_reset_ctrl_resp),
    .sep_crypto_req_o                    (sep_crypto_req),
    .sep_crypto_resp_i                   (sep_crypto_resp),
    .sep_system_peripherals_req_o        (sep_system_peripherals_req),
    .sep_system_peripherals_resp_i       (sep_system_peripherals_resp),
    .sep_io_req_o                        (sep_io_req),
    .sep_io_resp_i                       (sep_io_resp),
    .entropy_fifo_req_o                  (entropy_fifo_req),
    .entropy_fifo_resp_i                 (entropy_fifo_resp),
    .sep_external_req_o                 (sep_external_req),
    .sep_external_resp_i                (sep_external_resp)
  );

  // =========================================================================
  // Type Width Assertions
  // Verify sep_pkg types match sep_local_axi_xbar_pkg types
  // =========================================================================

`ifdef OCAH_DEBUG_LIVE  // elaboration-time width checks; excluded from synthesis
  // Input ports (3-bit ID, 32-bit addr, 64-bit data, 12-bit user)
  initial begin : gen_input_type_assertions
    // IFU SRAM
    assert ($bits(ifu_sram_axi_req_i.aw.id) == $bits(ifu_sram_req.aw.id))
    else $fatal(1, "IFU SRAM AW ID width mismatch");
    assert ($bits(ifu_sram_axi_req_i.aw.addr) == $bits(ifu_sram_req.aw.addr))
    else $fatal(1, "IFU SRAM AW ADDR width mismatch");
    assert ($bits(ifu_sram_axi_req_i.w.data) == $bits(ifu_sram_req.w.data))
    else $fatal(1, "IFU SRAM W DATA width mismatch");
    assert ($bits(ifu_sram_axi_req_i.ar.id) == $bits(ifu_sram_req.ar.id))
    else $fatal(1, "IFU SRAM AR ID width mismatch");
    assert ($bits(ifu_sram_axi_resp_o.r.id) == $bits(ifu_sram_resp.r.id))
    else $fatal(1, "IFU SRAM R ID width mismatch");
    assert ($bits(ifu_sram_axi_resp_o.b.id) == $bits(ifu_sram_resp.b.id))
    else $fatal(1, "IFU SRAM B ID width mismatch");

    // LSU
    assert ($bits(lsu_axi_req_i.aw.id) == $bits(lsu_req.aw.id))
    else $fatal(1, "LSU AW ID width mismatch");
    assert ($bits(lsu_axi_req_i.aw.addr) == $bits(lsu_req.aw.addr))
    else $fatal(1, "LSU AW ADDR width mismatch");
    assert ($bits(lsu_axi_req_i.w.data) == $bits(lsu_req.w.data))
    else $fatal(1, "LSU W DATA width mismatch");
    assert ($bits(lsu_axi_req_i.ar.id) == $bits(lsu_req.ar.id))
    else $fatal(1, "LSU AR ID width mismatch");
    assert ($bits(lsu_axi_resp_o.r.id) == $bits(lsu_resp.r.id))
    else $fatal(1, "LSU R ID width mismatch");
    assert ($bits(lsu_axi_resp_o.b.id) == $bits(lsu_resp.b.id))
    else $fatal(1, "LSU B ID width mismatch");

    // DBG
    assert ($bits(dbg_axi_req_i.aw.id) == $bits(dbg_req.aw.id))
    else $fatal(1, "DBG AW ID width mismatch");
    assert ($bits(dbg_axi_req_i.aw.addr) == $bits(dbg_req.aw.addr))
    else $fatal(1, "DBG AW ADDR width mismatch");
    assert ($bits(dbg_axi_req_i.w.data) == $bits(dbg_req.w.data))
    else $fatal(1, "DBG W DATA width mismatch");
    assert ($bits(dbg_axi_req_i.ar.id) == $bits(dbg_req.ar.id))
    else $fatal(1, "DBG AR ID width mismatch");
    assert ($bits(dbg_axi_resp_o.r.id) == $bits(dbg_resp.r.id))
    else $fatal(1, "DBG R ID width mismatch");
    assert ($bits(dbg_axi_resp_o.b.id) == $bits(dbg_resp.b.id))
    else $fatal(1, "DBG B ID width mismatch");

    // DMA
    assert ($bits(dma_axi_req_i.aw.id) == $bits(dma_req.aw.id))
    else $fatal(1, "DMA AW ID width mismatch");
    assert ($bits(dma_axi_req_i.aw.addr) == $bits(dma_req.aw.addr))
    else $fatal(1, "DMA AW ADDR width mismatch");
    assert ($bits(dma_axi_req_i.w.data) == $bits(dma_req.w.data))
    else $fatal(1, "DMA W DATA width mismatch");
    assert ($bits(dma_axi_req_i.ar.id) == $bits(dma_req.ar.id))
    else $fatal(1, "DMA AR ID width mismatch");
    assert ($bits(dma_axi_resp_o.r.id) == $bits(dma_resp.r.id))
    else $fatal(1, "DMA R ID width mismatch");
    assert ($bits(dma_axi_resp_o.b.id) == $bits(dma_resp.b.id))
    else $fatal(1, "DMA B ID width mismatch");

    // EXT
    assert ($bits(ext_axi_req_i.aw.id) == $bits(ext_req.aw.id))
    else $fatal(1, "EXT AW ID width mismatch");
    assert ($bits(ext_axi_req_i.aw.addr) == $bits(ext_req.aw.addr))
    else $fatal(1, "EXT AW ADDR width mismatch");
    assert ($bits(ext_axi_req_i.w.data) == $bits(ext_req.w.data))
    else $fatal(1, "EXT W DATA width mismatch");
    assert ($bits(ext_axi_req_i.ar.id) == $bits(ext_req.ar.id))
    else $fatal(1, "EXT AR ID width mismatch");
    assert ($bits(ext_axi_resp_o.r.id) == $bits(ext_resp.r.id))
    else $fatal(1, "EXT R ID width mismatch");
    assert ($bits(ext_axi_resp_o.b.id) == $bits(ext_resp.b.id))
    else $fatal(1, "EXT B ID width mismatch");
  end

  // Output ports (6-bit ID, 32-bit addr, 64-bit data, 12-bit user)
  initial begin : gen_output_type_assertions
    // cpu_tcm
    assert ($bits(cpu_tcm_axi_req_o.aw.id) == $bits(cpu_tcm_req.aw.id))
    else $fatal(1, "CPU_TCM AW ID width mismatch");
    assert ($bits(cpu_tcm_axi_req_o.aw.addr) == $bits(cpu_tcm_req.aw.addr))
    else $fatal(1, "CPU_TCM AW ADDR width mismatch");
    assert ($bits(cpu_tcm_axi_req_o.w.data) == $bits(cpu_tcm_req.w.data))
    else $fatal(1, "CPU_TCM W DATA width mismatch");
    assert ($bits(cpu_tcm_axi_req_o.ar.id) == $bits(cpu_tcm_req.ar.id))
    else $fatal(1, "CPU_TCM AR ID width mismatch");
    assert ($bits(cpu_tcm_axi_resp_i.r.id) == $bits(cpu_tcm_resp.r.id))
    else $fatal(1, "CPU_TCM R ID width mismatch");
    assert ($bits(cpu_tcm_axi_resp_i.b.id) == $bits(cpu_tcm_resp.b.id))
    else $fatal(1, "CPU_TCM B ID width mismatch");

    // sram
    assert ($bits(sram_axi_req_o.aw.id) == $bits(sram_req.aw.id))
    else $fatal(1, "SRAM AW ID width mismatch");
    assert ($bits(sram_axi_req_o.aw.addr) == $bits(sram_req.aw.addr))
    else $fatal(1, "SRAM AW ADDR width mismatch");
    assert ($bits(sram_axi_req_o.w.data) == $bits(sram_req.w.data))
    else $fatal(1, "SRAM W DATA width mismatch");
    assert ($bits(sram_axi_req_o.ar.id) == $bits(sram_req.ar.id))
    else $fatal(1, "SRAM AR ID width mismatch");
    assert ($bits(sram_axi_resp_i.r.id) == $bits(sram_resp.r.id))
    else $fatal(1, "SRAM R ID width mismatch");
    assert ($bits(sram_axi_resp_i.b.id) == $bits(sram_resp.b.id))
    else $fatal(1, "SRAM B ID width mismatch");

    // dma_csr
    assert ($bits(dma_csr_axi_req_o.aw.id) == $bits(dma_csr_req.aw.id))
    else $fatal(1, "DMA_CSR AW ID width mismatch");
    assert ($bits(dma_csr_axi_req_o.aw.addr) == $bits(dma_csr_req.aw.addr))
    else $fatal(1, "DMA_CSR AW ADDR width mismatch");
    assert ($bits(dma_csr_axi_req_o.w.data) == $bits(dma_csr_req.w.data))
    else $fatal(1, "DMA_CSR W DATA width mismatch");
    assert ($bits(dma_csr_axi_req_o.ar.id) == $bits(dma_csr_req.ar.id))
    else $fatal(1, "DMA_CSR AR ID width mismatch");
    assert ($bits(dma_csr_axi_resp_i.r.id) == $bits(dma_csr_resp.r.id))
    else $fatal(1, "DMA_CSR R ID width mismatch");
    assert ($bits(dma_csr_axi_resp_i.b.id) == $bits(dma_csr_resp.b.id))
    else $fatal(1, "DMA_CSR B ID width mismatch");

    // sep_wdt
    assert ($bits(sep_wdt_axi_req_o.aw.id) == $bits(sep_wdt_req.aw.id))
    else $fatal(1, "SEP_WDT AW ID width mismatch");
    assert ($bits(sep_wdt_axi_req_o.aw.addr) == $bits(sep_wdt_req.aw.addr))
    else $fatal(1, "SEP_WDT AW ADDR width mismatch");
    assert ($bits(sep_wdt_axi_req_o.w.data) == $bits(sep_wdt_req.w.data))
    else $fatal(1, "SEP_WDT W DATA width mismatch");
    assert ($bits(sep_wdt_axi_req_o.ar.id) == $bits(sep_wdt_req.ar.id))
    else $fatal(1, "SEP_WDT AR ID width mismatch");
    assert ($bits(sep_wdt_axi_resp_i.r.id) == $bits(sep_wdt_resp.r.id))
    else $fatal(1, "SEP_WDT R ID width mismatch");
    assert ($bits(sep_wdt_axi_resp_i.b.id) == $bits(sep_wdt_resp.b.id))
    else $fatal(1, "SEP_WDT B ID width mismatch");

    // sep_reset_ctrl
    assert ($bits(sep_reset_ctrl_axi_req_o.aw.id) == $bits(sep_reset_ctrl_req.aw.id))
    else $fatal(1, "SEP_RESET_CTRL AW ID width mismatch");
    assert ($bits(sep_reset_ctrl_axi_req_o.aw.addr) == $bits(sep_reset_ctrl_req.aw.addr))
    else $fatal(1, "SEP_RESET_CTRL AW ADDR width mismatch");
    assert ($bits(sep_reset_ctrl_axi_req_o.w.data) == $bits(sep_reset_ctrl_req.w.data))
    else $fatal(1, "SEP_RESET_CTRL W DATA width mismatch");
    assert ($bits(sep_reset_ctrl_axi_req_o.ar.id) == $bits(sep_reset_ctrl_req.ar.id))
    else $fatal(1, "SEP_RESET_CTRL AR ID width mismatch");
    assert ($bits(sep_reset_ctrl_axi_resp_i.r.id) == $bits(sep_reset_ctrl_resp.r.id))
    else $fatal(1, "SEP_RESET_CTRL R ID width mismatch");
    assert ($bits(sep_reset_ctrl_axi_resp_i.b.id) == $bits(sep_reset_ctrl_resp.b.id))
    else $fatal(1, "SEP_RESET_CTRL B ID width mismatch");

    // sep_crypto
    assert ($bits(sep_crypto_axi_req_o.aw.id) == $bits(sep_crypto_req.aw.id))
    else $fatal(1, "SEP_CRYPTO AW ID width mismatch");
    assert ($bits(sep_crypto_axi_req_o.aw.addr) == $bits(sep_crypto_req.aw.addr))
    else $fatal(1, "SEP_CRYPTO AW ADDR width mismatch");
    assert ($bits(sep_crypto_axi_req_o.w.data) == $bits(sep_crypto_req.w.data))
    else $fatal(1, "SEP_CRYPTO W DATA width mismatch");
    assert ($bits(sep_crypto_axi_req_o.ar.id) == $bits(sep_crypto_req.ar.id))
    else $fatal(1, "SEP_CRYPTO AR ID width mismatch");
    assert ($bits(sep_crypto_axi_resp_i.r.id) == $bits(sep_crypto_resp.r.id))
    else $fatal(1, "SEP_CRYPTO R ID width mismatch");
    assert ($bits(sep_crypto_axi_resp_i.b.id) == $bits(sep_crypto_resp.b.id))
    else $fatal(1, "SEP_CRYPTO B ID width mismatch");

    // sep_system_peripherals
    assert ($bits(
        sep_system_peripherals_axi_req_o.aw.id
    ) == $bits(
        sep_system_peripherals_req.aw.id
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS AW ID width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_req_o.aw.addr
    ) == $bits(
        sep_system_peripherals_req.aw.addr
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS AW ADDR width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_req_o.w.data
    ) == $bits(
        sep_system_peripherals_req.w.data
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS W DATA width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_req_o.ar.id
    ) == $bits(
        sep_system_peripherals_req.ar.id
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS AR ID width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_resp_i.r.id
    ) == $bits(
        sep_system_peripherals_resp.r.id
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS R ID width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_resp_i.b.id
    ) == $bits(
        sep_system_peripherals_resp.b.id
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS B ID width mismatch");

    // sep_io
    assert ($bits(sep_io_axi_req_o.aw.id) == $bits(sep_io_req.aw.id))
    else $fatal(1, "SEP_IO AW ID width mismatch");
    assert ($bits(sep_io_axi_req_o.aw.addr) == $bits(sep_io_req.aw.addr))
    else $fatal(1, "SEP_IO AW ADDR width mismatch");
    assert ($bits(sep_io_axi_req_o.w.data) == $bits(sep_io_req.w.data))
    else $fatal(1, "SEP_IO W DATA width mismatch");
    assert ($bits(sep_io_axi_req_o.ar.id) == $bits(sep_io_req.ar.id))
    else $fatal(1, "SEP_IO AR ID width mismatch");
    assert ($bits(sep_io_axi_resp_i.r.id) == $bits(sep_io_resp.r.id))
    else $fatal(1, "SEP_IO R ID width mismatch");
    assert ($bits(sep_io_axi_resp_i.b.id) == $bits(sep_io_resp.b.id))
    else $fatal(1, "SEP_IO B ID width mismatch");

    // entropy_fifo
    assert ($bits(entropy_fifo_axi_req_o.aw.id) == $bits(entropy_fifo_req.aw.id))
    else $fatal(1, "ENTROPY_FIFO AW ID width mismatch");
    assert ($bits(entropy_fifo_axi_req_o.aw.addr) == $bits(entropy_fifo_req.aw.addr))
    else $fatal(1, "ENTROPY_FIFO AW ADDR width mismatch");
    assert ($bits(entropy_fifo_axi_req_o.w.data) == $bits(entropy_fifo_req.w.data))
    else $fatal(1, "ENTROPY_FIFO W DATA width mismatch");
    assert ($bits(entropy_fifo_axi_req_o.ar.id) == $bits(entropy_fifo_req.ar.id))
    else $fatal(1, "ENTROPY_FIFO AR ID width mismatch");
    assert ($bits(entropy_fifo_axi_resp_i.r.id) == $bits(entropy_fifo_resp.r.id))
    else $fatal(1, "ENTROPY_FIFO R ID width mismatch");
    assert ($bits(entropy_fifo_axi_resp_i.b.id) == $bits(entropy_fifo_resp.b.id))
    else $fatal(1, "ENTROPY_FIFO B ID width mismatch");

    // sep_external
    assert ($bits(sep_external_axi_req_o.aw.id) == $bits(sep_external_req.aw.id))
    else $fatal(1, "SEP_EXTERNAL AW ID width mismatch");
    assert ($bits(sep_external_axi_req_o.aw.addr) == $bits(sep_external_req.aw.addr))
    else $fatal(1, "SEP_EXTERNAL AW ADDR width mismatch");
    assert ($bits(sep_external_axi_req_o.w.data) == $bits(sep_external_req.w.data))
    else $fatal(1, "SEP_EXTERNAL W DATA width mismatch");
    assert ($bits(sep_external_axi_req_o.ar.id) == $bits(sep_external_req.ar.id))
    else $fatal(1, "SEP_EXTERNAL AR ID width mismatch");
    assert ($bits(sep_external_axi_resp_i.r.id) == $bits(sep_external_resp.r.id))
    else $fatal(1, "SEP_EXTERNAL R ID width mismatch");
    assert ($bits(sep_external_axi_resp_i.b.id) == $bits(sep_external_resp.b.id))
    else $fatal(1, "SEP_EXTERNAL B ID width mismatch");
  end

  // User-field width assertions
  initial begin : gen_user_width_assertions
    // Input ports
    assert ($bits(ifu_sram_axi_req_i.aw.user) == $bits(ifu_sram_req.aw.user))
    else $fatal(1, "IFU SRAM AW USER width mismatch");
    assert ($bits(ifu_sram_axi_req_i.w.user) == $bits(ifu_sram_req.w.user))
    else $fatal(1, "IFU SRAM W USER width mismatch");
    assert ($bits(ifu_sram_axi_req_i.ar.user) == $bits(ifu_sram_req.ar.user))
    else $fatal(1, "IFU SRAM AR USER width mismatch");
    assert ($bits(ifu_sram_axi_resp_o.r.user) == $bits(ifu_sram_resp.r.user))
    else $fatal(1, "IFU SRAM R USER width mismatch");
    assert ($bits(ifu_sram_axi_resp_o.b.user) == $bits(ifu_sram_resp.b.user))
    else $fatal(1, "IFU SRAM B USER width mismatch");

    assert ($bits(lsu_axi_req_i.aw.user) == $bits(lsu_req.aw.user))
    else $fatal(1, "LSU AW USER width mismatch");
    assert ($bits(lsu_axi_req_i.w.user) == $bits(lsu_req.w.user))
    else $fatal(1, "LSU W USER width mismatch");
    assert ($bits(lsu_axi_req_i.ar.user) == $bits(lsu_req.ar.user))
    else $fatal(1, "LSU AR USER width mismatch");
    assert ($bits(lsu_axi_resp_o.r.user) == $bits(lsu_resp.r.user))
    else $fatal(1, "LSU R USER width mismatch");
    assert ($bits(lsu_axi_resp_o.b.user) == $bits(lsu_resp.b.user))
    else $fatal(1, "LSU B USER width mismatch");

    assert ($bits(dbg_axi_req_i.aw.user) == $bits(dbg_req.aw.user))
    else $fatal(1, "DBG AW USER width mismatch");
    assert ($bits(dbg_axi_req_i.w.user) == $bits(dbg_req.w.user))
    else $fatal(1, "DBG W USER width mismatch");
    assert ($bits(dbg_axi_req_i.ar.user) == $bits(dbg_req.ar.user))
    else $fatal(1, "DBG AR USER width mismatch");
    assert ($bits(dbg_axi_resp_o.r.user) == $bits(dbg_resp.r.user))
    else $fatal(1, "DBG R USER width mismatch");
    assert ($bits(dbg_axi_resp_o.b.user) == $bits(dbg_resp.b.user))
    else $fatal(1, "DBG B USER width mismatch");

    assert ($bits(dma_axi_req_i.aw.user) == $bits(dma_req.aw.user))
    else $fatal(1, "DMA AW USER width mismatch");
    assert ($bits(dma_axi_req_i.w.user) == $bits(dma_req.w.user))
    else $fatal(1, "DMA W USER width mismatch");
    assert ($bits(dma_axi_req_i.ar.user) == $bits(dma_req.ar.user))
    else $fatal(1, "DMA AR USER width mismatch");
    assert ($bits(dma_axi_resp_o.r.user) == $bits(dma_resp.r.user))
    else $fatal(1, "DMA R USER width mismatch");
    assert ($bits(dma_axi_resp_o.b.user) == $bits(dma_resp.b.user))
    else $fatal(1, "DMA B USER width mismatch");

    assert ($bits(ext_axi_req_i.aw.user) == $bits(ext_req.aw.user))
    else $fatal(1, "EXT AW USER width mismatch");
    assert ($bits(ext_axi_req_i.w.user) == $bits(ext_req.w.user))
    else $fatal(1, "EXT W USER width mismatch");
    assert ($bits(ext_axi_req_i.ar.user) == $bits(ext_req.ar.user))
    else $fatal(1, "EXT AR USER width mismatch");
    assert ($bits(ext_axi_resp_o.r.user) == $bits(ext_resp.r.user))
    else $fatal(1, "EXT R USER width mismatch");
    assert ($bits(ext_axi_resp_o.b.user) == $bits(ext_resp.b.user))
    else $fatal(1, "EXT B USER width mismatch");

    // Output ports
    assert ($bits(cpu_tcm_axi_req_o.aw.user) == $bits(cpu_tcm_req.aw.user))
    else $fatal(1, "CPU_TCM AW USER width mismatch");
    assert ($bits(cpu_tcm_axi_req_o.w.user) == $bits(cpu_tcm_req.w.user))
    else $fatal(1, "CPU_TCM W USER width mismatch");
    assert ($bits(cpu_tcm_axi_req_o.ar.user) == $bits(cpu_tcm_req.ar.user))
    else $fatal(1, "CPU_TCM AR USER width mismatch");
    assert ($bits(cpu_tcm_axi_resp_i.r.user) == $bits(cpu_tcm_resp.r.user))
    else $fatal(1, "CPU_TCM R USER width mismatch");
    assert ($bits(cpu_tcm_axi_resp_i.b.user) == $bits(cpu_tcm_resp.b.user))
    else $fatal(1, "CPU_TCM B USER width mismatch");

    assert ($bits(sram_axi_req_o.aw.user) == $bits(sram_req.aw.user))
    else $fatal(1, "SRAM AW USER width mismatch");
    assert ($bits(sram_axi_req_o.w.user) == $bits(sram_req.w.user))
    else $fatal(1, "SRAM W USER width mismatch");
    assert ($bits(sram_axi_req_o.ar.user) == $bits(sram_req.ar.user))
    else $fatal(1, "SRAM AR USER width mismatch");
    assert ($bits(sram_axi_resp_i.r.user) == $bits(sram_resp.r.user))
    else $fatal(1, "SRAM R USER width mismatch");
    assert ($bits(sram_axi_resp_i.b.user) == $bits(sram_resp.b.user))
    else $fatal(1, "SRAM B USER width mismatch");

    assert ($bits(dma_csr_axi_req_o.aw.user) == $bits(dma_csr_req.aw.user))
    else $fatal(1, "DMA_CSR AW USER width mismatch");
    assert ($bits(dma_csr_axi_req_o.w.user) == $bits(dma_csr_req.w.user))
    else $fatal(1, "DMA_CSR W USER width mismatch");
    assert ($bits(dma_csr_axi_req_o.ar.user) == $bits(dma_csr_req.ar.user))
    else $fatal(1, "DMA_CSR AR USER width mismatch");
    assert ($bits(dma_csr_axi_resp_i.r.user) == $bits(dma_csr_resp.r.user))
    else $fatal(1, "DMA_CSR R USER width mismatch");
    assert ($bits(dma_csr_axi_resp_i.b.user) == $bits(dma_csr_resp.b.user))
    else $fatal(1, "DMA_CSR B USER width mismatch");

    assert ($bits(sep_wdt_axi_req_o.aw.user) == $bits(sep_wdt_req.aw.user))
    else $fatal(1, "SEP_WDT AW USER width mismatch");
    assert ($bits(sep_wdt_axi_req_o.w.user) == $bits(sep_wdt_req.w.user))
    else $fatal(1, "SEP_WDT W USER width mismatch");
    assert ($bits(sep_wdt_axi_req_o.ar.user) == $bits(sep_wdt_req.ar.user))
    else $fatal(1, "SEP_WDT AR USER width mismatch");
    assert ($bits(sep_wdt_axi_resp_i.r.user) == $bits(sep_wdt_resp.r.user))
    else $fatal(1, "SEP_WDT R USER width mismatch");
    assert ($bits(sep_wdt_axi_resp_i.b.user) == $bits(sep_wdt_resp.b.user))
    else $fatal(1, "SEP_WDT B USER width mismatch");

    assert ($bits(sep_reset_ctrl_axi_req_o.aw.user) == $bits(sep_reset_ctrl_req.aw.user))
    else $fatal(1, "SEP_RESET_CTRL AW USER width mismatch");
    assert ($bits(sep_reset_ctrl_axi_req_o.w.user) == $bits(sep_reset_ctrl_req.w.user))
    else $fatal(1, "SEP_RESET_CTRL W USER width mismatch");
    assert ($bits(sep_reset_ctrl_axi_req_o.ar.user) == $bits(sep_reset_ctrl_req.ar.user))
    else $fatal(1, "SEP_RESET_CTRL AR USER width mismatch");
    assert ($bits(sep_reset_ctrl_axi_resp_i.r.user) == $bits(sep_reset_ctrl_resp.r.user))
    else $fatal(1, "SEP_RESET_CTRL R USER width mismatch");
    assert ($bits(sep_reset_ctrl_axi_resp_i.b.user) == $bits(sep_reset_ctrl_resp.b.user))
    else $fatal(1, "SEP_RESET_CTRL B USER width mismatch");

    assert ($bits(sep_crypto_axi_req_o.aw.user) == $bits(sep_crypto_req.aw.user))
    else $fatal(1, "SEP_CRYPTO AW USER width mismatch");
    assert ($bits(sep_crypto_axi_req_o.w.user) == $bits(sep_crypto_req.w.user))
    else $fatal(1, "SEP_CRYPTO W USER width mismatch");
    assert ($bits(sep_crypto_axi_req_o.ar.user) == $bits(sep_crypto_req.ar.user))
    else $fatal(1, "SEP_CRYPTO AR USER width mismatch");
    assert ($bits(sep_crypto_axi_resp_i.r.user) == $bits(sep_crypto_resp.r.user))
    else $fatal(1, "SEP_CRYPTO R USER width mismatch");
    assert ($bits(sep_crypto_axi_resp_i.b.user) == $bits(sep_crypto_resp.b.user))
    else $fatal(1, "SEP_CRYPTO B USER width mismatch");

    assert ($bits(
        sep_system_peripherals_axi_req_o.aw.user
    ) == $bits(
        sep_system_peripherals_req.aw.user
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS AW USER width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_req_o.w.user
    ) == $bits(
        sep_system_peripherals_req.w.user
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS W USER width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_req_o.ar.user
    ) == $bits(
        sep_system_peripherals_req.ar.user
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS AR USER width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_resp_i.r.user
    ) == $bits(
        sep_system_peripherals_resp.r.user
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS R USER width mismatch");
    assert ($bits(
        sep_system_peripherals_axi_resp_i.b.user
    ) == $bits(
        sep_system_peripherals_resp.b.user
    ))
    else $fatal(1, "SEP_SYSTEM_PERIPHERALS B USER width mismatch");

    assert ($bits(sep_io_axi_req_o.aw.user) == $bits(sep_io_req.aw.user))
    else $fatal(1, "SEP_IO AW USER width mismatch");
    assert ($bits(sep_io_axi_req_o.w.user) == $bits(sep_io_req.w.user))
    else $fatal(1, "SEP_IO W USER width mismatch");
    assert ($bits(sep_io_axi_req_o.ar.user) == $bits(sep_io_req.ar.user))
    else $fatal(1, "SEP_IO AR USER width mismatch");
    assert ($bits(sep_io_axi_resp_i.r.user) == $bits(sep_io_resp.r.user))
    else $fatal(1, "SEP_IO R USER width mismatch");
    assert ($bits(sep_io_axi_resp_i.b.user) == $bits(sep_io_resp.b.user))
    else $fatal(1, "SEP_IO B USER width mismatch");

    assert ($bits(entropy_fifo_axi_req_o.aw.user) == $bits(entropy_fifo_req.aw.user))
    else $fatal(1, "ENTROPY_FIFO AW USER width mismatch");
    assert ($bits(entropy_fifo_axi_req_o.w.user) == $bits(entropy_fifo_req.w.user))
    else $fatal(1, "ENTROPY_FIFO W USER width mismatch");
    assert ($bits(entropy_fifo_axi_req_o.ar.user) == $bits(entropy_fifo_req.ar.user))
    else $fatal(1, "ENTROPY_FIFO AR USER width mismatch");
    assert ($bits(entropy_fifo_axi_resp_i.r.user) == $bits(entropy_fifo_resp.r.user))
    else $fatal(1, "ENTROPY_FIFO R USER width mismatch");
    assert ($bits(entropy_fifo_axi_resp_i.b.user) == $bits(entropy_fifo_resp.b.user))
    else $fatal(1, "ENTROPY_FIFO B USER width mismatch");

    assert ($bits(sep_external_axi_req_o.aw.user) == $bits(sep_external_req.aw.user))
    else $fatal(1, "SEP_EXTERNAL AW USER width mismatch");
    assert ($bits(sep_external_axi_req_o.w.user) == $bits(sep_external_req.w.user))
    else $fatal(1, "SEP_EXTERNAL W USER width mismatch");
    assert ($bits(sep_external_axi_req_o.ar.user) == $bits(sep_external_req.ar.user))
    else $fatal(1, "SEP_EXTERNAL AR USER width mismatch");
    assert ($bits(sep_external_axi_resp_i.r.user) == $bits(sep_external_resp.r.user))
    else $fatal(1, "SEP_EXTERNAL R USER width mismatch");
    assert ($bits(sep_external_axi_resp_i.b.user) == $bits(sep_external_resp.b.user))
    else $fatal(1, "SEP_EXTERNAL B USER width mismatch");
  end
`endif  // OCAH_DEBUG_LIVE

endmodule : sep_local_axi_xbar_wrapper
