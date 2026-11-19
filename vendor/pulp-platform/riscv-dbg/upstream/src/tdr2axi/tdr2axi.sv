// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// SPDX-License-Identifier: Apache-2.0

//
// Description:
//   TDR to AXI bridge using the RISC-V Debug Module System Bus Access (SBA).
//
//     41-bit DMI TDR -> dmi_tdr_bridge -> dm_csrs -> dm_sba -> mem port
//       AXI4_LITE = 1: axi_lite_from_mem            -> AXI4-Lite manager
//       AXI4_LITE = 0: axi_from_mem (+ lite_to_axi) -> AXI4 manager (single beat,
//                                                     AxSIZE = sbcs.sbaccess)
//
//   Only the SBA registers are useful: there is no hart behind this DM, so hart 0
//   reports unavailable and every abstract command fails with "not supported".
//   AXI_DATA_WIDTH (32 or 64) sets the SBA data width: sbdata and the largest access.
//   AXI_ADDR_WIDTH sets the SBA address width independently: sbaddress and
//   sbcs.sbasize, so e.g. a 32-bit data bus can still reach a 64-bit address space.
//   It must cover the data-bus byte offset (dm_sba): 2..64 for 32-bit, 3..64 for 64-bit.
//
//   Reset: everything, the TDR bridge included, is on one reset, i_arst_n: power-on or
//   system reset, never TRST. A system reset must also reset the fabric tdr2axi
//   accesses, so an outstanding AXI transaction never survives on one side only, and a
//   hung bus access is cleared by that reset; with power-on reset only, a hung access
//   needs a power cycle. dm_top is likewise meant for the root reset. i_arst_n may be fully asynchronous: it is synchronised
//   here into i_clk and TCK (asynchronous assert, synchronous release, scan bypass).
//   TRST does not reset tdr2axi (upstream resets the dmi_jtag TCK half on trst_ni); see
//   dmi_tdr_bridge for why that is safe. Software clears: op 3 for the DMI error,
//   dmcontrol.dmactive = 0 for the DM. ndmreset_o is not connected, so the debugger
//   cannot reset the system through tdr2axi.

module tdr2axi #(
    parameter bit              AXI4_LITE      = 1'b0,
    parameter int unsigned     AXI_ADDR_WIDTH = 64,
    parameter int unsigned     AXI_DATA_WIDTH = 64,
    // Non-secure, unprivileged, data
    parameter axi_pkg::prot_t  AXI_PROT       = 3'b010,
    parameter axi_pkg::cache_t AXI_CACHE      = 4'b0000,  // AXI4 only
    parameter int unsigned     SYNC_STAGES    = 3,
    // AXI4 or AXI4-Lite request/response structs (data width must be AXI_DATA_WIDTH).
    // Must be overridden by the parent.
    parameter type             axi_req_t      = logic,
    parameter type             axi_rsp_t      = logic
) (
    input logic i_clk,
    // Power-on or system reset, asynchronous
    input logic i_arst_n,
    input logic i_test_mode,
    input logic i_arst_scan_n,

    // DMI TDR (TCK domain)
    input  logic        i_tck,
    input  logic [40:0] i_dmi_tdr,
    input  logic        i_dmi_tdr_capture,
    input  logic        i_dmi_tdr_update,
    output logic [40:0] o_dmi_tdr,

    // AXI manager
    output axi_req_t o_axi_req,
    input  axi_rsp_t i_axi_rsp
);

  // ---------------------------------------------------------------------------
  // Resets: i_arst_n, released per clock
  // ---------------------------------------------------------------------------
  logic arst_clk_n;
  logic arst_tck_n;

  rstgen_bypass #(
      .NumRegs(SYNC_STAGES)
  ) u_rst_clk_sync (
      .clk_i           (i_clk),
      .rst_ni          (i_arst_n),
      .rst_test_mode_ni(i_arst_scan_n),
      .test_mode_i     (i_test_mode),
      .rst_no          (arst_clk_n),
      .init_no         ()
  );

  rstgen_bypass #(
      .NumRegs(SYNC_STAGES)
  ) u_rst_tck_sync (
      .clk_i           (i_tck),
      .rst_ni          (i_arst_n),
      .rst_test_mode_ni(i_arst_scan_n),
      .test_mode_i     (i_test_mode),
      .rst_no          (arst_tck_n),
      .init_no         ()
  );

  // ---------------------------------------------------------------------------
  // TDR -> DMI
  // ---------------------------------------------------------------------------
  dm::dmi_req_t  dmi_req;
  logic          dmi_req_valid;
  logic          dmi_req_ready;
  dm::dmi_resp_t dmi_resp;
  logic          dmi_resp_valid;
  logic          dmi_resp_ready;

  dmi_tdr_bridge #(
      .SYNC_STAGES(SYNC_STAGES)
  ) u_dmi_tdr_bridge (
      .i_clk            (i_clk),
      .i_arst_n         (arst_clk_n),
      .i_tck            (i_tck),
      .i_arst_tck_n     (arst_tck_n),
      .i_dmi_tdr        (i_dmi_tdr),
      .i_dmi_tdr_capture(i_dmi_tdr_capture),
      .i_dmi_tdr_update (i_dmi_tdr_update),
      .o_dmi_tdr        (o_dmi_tdr),
      .o_dmi_req        (dmi_req),
      .o_dmi_req_valid  (dmi_req_valid),
      .i_dmi_req_ready  (dmi_req_ready),
      .i_dmi_resp       (dmi_resp),
      .i_dmi_resp_valid (dmi_resp_valid),
      .o_dmi_resp_ready (dmi_resp_ready)
  );

  // ---------------------------------------------------------------------------
  // Debug Module registers
  // ---------------------------------------------------------------------------
  logic                      dmactive;
  logic                      cmd_valid;
  logic [AXI_ADDR_WIDTH-1:0] sbaddress_csr;
  logic [AXI_ADDR_WIDTH-1:0] sbaddress_sba;
  logic                      sbaddress_write_valid;
  logic                      sbreadonaddr;
  logic                      sbautoincrement;
  logic [               2:0] sbaccess;
  logic                      sbreadondata;
  logic [AXI_DATA_WIDTH-1:0] sbdata_csr;
  logic [AXI_DATA_WIDTH-1:0] sbdata_sba;
  logic                      sbdata_read_valid;
  logic                      sbdata_write_valid;
  logic                      sbdata_valid;
  logic                      sbbusy;
  logic                      sberror_valid;
  logic [               2:0] sberror;

  dm_csrs #(
      .NrHarts     (1),
      .BusWidth    (AXI_DATA_WIDTH),
      .SbaAddrWidth(AXI_ADDR_WIDTH)
  ) u_dm_csrs (
      .clk_i                  (i_clk),
      .rst_ni                 (arst_clk_n),
      .next_dm_addr_i         ('0),
      .testmode_i             (1'b0),
      // Response queue is always empty when the bridge is idle; see dmi_tdr_bridge
      .dmi_rst_ni             (1'b1),
      .dmi_req_valid_i        (dmi_req_valid),
      .dmi_req_ready_o        (dmi_req_ready),
      .dmi_req_i              (dmi_req),
      .dmi_resp_valid_o       (dmi_resp_valid),
      .dmi_resp_ready_i       (dmi_resp_ready),
      .dmi_resp_o             (dmi_resp),
      .ndmreset_o             (),
      .ndmreset_ack_i         (1'b0),
      .dmactive_o             (dmactive),
      // No hart behind this DM
      .hartinfo_i             ('0),
      .halted_i               (1'b0),
      .unavailable_i          (1'b1),
      .resumeack_i            (1'b0),
      .hartsel_o              (),
      .haltreq_o              (),
      .resumereq_o            (),
      .clear_resumeack_o      (),
      .cmd_valid_o            (cmd_valid),
      .cmd_o                  (),
      .cmderror_valid_i       (cmd_valid),
      .cmderror_i             (dm::CmdErrNotSupported),
      .cmdbusy_i              (1'b0),
      .progbuf_o              (),
      .data_o                 (),
      .data_i                 ('0),
      .data_valid_i           (1'b0),
      // System Bus Access
      .sbaddress_o            (sbaddress_csr),
      .sbaddress_i            (sbaddress_sba),
      .sbaddress_write_valid_o(sbaddress_write_valid),
      .sbreadonaddr_o         (sbreadonaddr),
      .sbautoincrement_o      (sbautoincrement),
      .sbaccess_o             (sbaccess),
      .sbreadondata_o         (sbreadondata),
      .sbdata_o               (sbdata_csr),
      .sbdata_read_valid_o    (sbdata_read_valid),
      .sbdata_write_valid_o   (sbdata_write_valid),
      .sbdata_i               (sbdata_sba),
      .sbdata_valid_i         (sbdata_valid),
      .sbbusy_i               (sbbusy),
      .sberror_valid_i        (sberror_valid),
      .sberror_i              (sberror)
  );

  // ---------------------------------------------------------------------------
  // System Bus Access engine
  // ---------------------------------------------------------------------------
  logic                        mem_req;
  logic [  AXI_ADDR_WIDTH-1:0] mem_addr;
  logic                        mem_we;
  logic [  AXI_DATA_WIDTH-1:0] mem_wdata;
  logic [AXI_DATA_WIDTH/8-1:0] mem_be;
  logic                        mem_gnt;
  logic                        mem_rsp_valid;
  logic [  AXI_DATA_WIDTH-1:0] mem_rsp_rdata;
  logic                        mem_rsp_error;

  dm_sba #(
      .BusWidth      (AXI_DATA_WIDTH),
      .SbaAddrWidth  (AXI_ADDR_WIDTH),
      .ReadByteEnable(1'b1)
  ) u_dm_sba (
      .clk_i                  (i_clk),
      .rst_ni                 (arst_clk_n),
      .dmactive_i             (dmactive),
      .master_req_o           (mem_req),
      .master_add_o           (mem_addr),
      .master_we_o            (mem_we),
      .master_wdata_o         (mem_wdata),
      .master_be_o            (mem_be),
      .master_gnt_i           (mem_gnt),
      .master_r_valid_i       (mem_rsp_valid),
      .master_r_err_i         (mem_rsp_error),
      .master_r_other_err_i   (1'b0),
      .master_r_rdata_i       (mem_rsp_rdata),
      .sbaddress_i            (sbaddress_csr),
      .sbaddress_write_valid_i(sbaddress_write_valid),
      .sbreadonaddr_i         (sbreadonaddr),
      .sbaddress_o            (sbaddress_sba),
      .sbautoincrement_i      (sbautoincrement),
      .sbaccess_i             (sbaccess),
      .sbreadondata_i         (sbreadondata),
      .sbdata_i               (sbdata_csr),
      .sbdata_read_valid_i    (sbdata_read_valid),
      .sbdata_write_valid_i   (sbdata_write_valid),
      .sbdata_o               (sbdata_sba),
      .sbdata_valid_o         (sbdata_valid),
      .sbbusy_o               (sbbusy),
      .sberror_valid_o        (sberror_valid),
      .sberror_o              (sberror)
  );

  // ---------------------------------------------------------------------------
  // Mem port -> AXI4 / AXI4-Lite (dm_sba has one request in flight at a time)
  // ---------------------------------------------------------------------------
  if (AXI4_LITE) begin : g_axi_lite
    axi_lite_from_mem #(
        .MemAddrWidth(AXI_ADDR_WIDTH),
        .AxiAddrWidth(AXI_ADDR_WIDTH),
        .DataWidth   (AXI_DATA_WIDTH),
        .MaxRequests (1),
        .AxiProt     (AXI_PROT),
        .axi_req_t   (axi_req_t),
        .axi_rsp_t   (axi_rsp_t)
    ) u_axi_lite_from_mem (
        .clk_i          (i_clk),
        .rst_ni         (arst_clk_n),
        .mem_req_i      (mem_req),
        .mem_addr_i     (mem_addr),
        .mem_we_i       (mem_we),
        .mem_wdata_i    (mem_wdata),
        .mem_be_i       (mem_be),
        .mem_gnt_o      (mem_gnt),
        .mem_rsp_valid_o(mem_rsp_valid),
        .mem_rsp_rdata_o(mem_rsp_rdata),
        .mem_rsp_error_o(mem_rsp_error),
        .axi_req_o      (o_axi_req),
        .axi_rsp_i      (i_axi_rsp)
    );
  end else begin : g_axi
    axi_req_t axi_req;

    axi_from_mem #(
        .MemAddrWidth(AXI_ADDR_WIDTH),
        .AxiAddrWidth(AXI_ADDR_WIDTH),
        .DataWidth   (AXI_DATA_WIDTH),
        .MaxRequests (1),
        .AxiProt     (AXI_PROT),
        .axi_req_t   (axi_req_t),
        .axi_rsp_t   (axi_rsp_t)
    ) u_axi_from_mem (
        .clk_i          (i_clk),
        .rst_ni         (arst_clk_n),
        .mem_req_i      (mem_req),
        .mem_addr_i     (mem_addr),
        .mem_we_i       (mem_we),
        .mem_wdata_i    (mem_wdata),
        .mem_be_i       (mem_be),
        .mem_gnt_o      (mem_gnt),
        .mem_rsp_valid_o(mem_rsp_valid),
        .mem_rsp_rdata_o(mem_rsp_rdata),
        .mem_rsp_error_o(mem_rsp_error),
        .slv_aw_cache_i (AXI_CACHE),
        .slv_ar_cache_i (AXI_CACHE),
        .axi_req_o      (axi_req),
        .axi_rsp_i      (i_axi_rsp)
    );

    // AxSIZE follows the SBA access size instead of the full bus width, so a narrow
    // read does not fetch the whole bus word. dm_sba only issues naturally aligned
    // accesses (else sberror = 3) and sbaccess <= 3 (else sberror = 4).
    always_comb begin
      o_axi_req         = axi_req;
      o_axi_req.aw.size = axi_pkg::size_t'(sbaccess);
      o_axi_req.ar.size = axi_pkg::size_t'(sbaccess);
    end
  end

  // ---------------------------------------------------------------------------
  // Parameter checks
  // ---------------------------------------------------------------------------
  initial begin : p_validate_params
    assert ((AXI_DATA_WIDTH == 32) || (AXI_DATA_WIDTH == 64)) else
      $fatal(1, "AXI_DATA_WIDTH must be 32 or 64.");
    assert ((AXI_ADDR_WIDTH >= $clog2(AXI_DATA_WIDTH / 8)) && (AXI_ADDR_WIDTH <= 64)) else
      $fatal(1, "AXI_ADDR_WIDTH must be 2..64 for 32-bit data, 3..64 for 64-bit data.");
    assert ($bits(o_axi_req.w.data) == AXI_DATA_WIDTH) else
      $fatal(1, "axi_req_t data width must be AXI_DATA_WIDTH.");
    assert ($bits(i_axi_rsp.r.data) == AXI_DATA_WIDTH) else
      $fatal(1, "axi_rsp_t data width must be AXI_DATA_WIDTH.");
  end

endmodule
