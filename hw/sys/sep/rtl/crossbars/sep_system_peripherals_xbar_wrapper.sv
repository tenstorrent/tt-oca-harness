// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Adapt sep_pkg AXI structs to the system-peripherals crossbar types.
//
// sep_local_from_remap and smn_inbound use 6-bit ID and 56-bit address.
// Output ports use 7-bit ID and 56-bit address, except mailbox and system_csr which are
// AXI4-Lite.

`include "ocah_assert.svh"

module sep_system_peripherals_xbar_wrapper

    `include "axi/assign.svh"
(
    input  logic                                       clk_i,  // System clock.
    input  logic                                       rst_ni,  // Active-low reset.
    input  logic                                       test_i,  // DFT test mode to axi_xbar.

    input  sep_pkg::sep_system_peripherals_internal_axi_req_t   sep_local_from_remap_req_i,  // Local-master request after the alias remap and SEP_LOCAL decode in
                                                                                             // sep_system_peripherals.
    output sep_pkg::sep_system_peripherals_internal_axi_resp_t  sep_local_from_remap_resp_o,  // Response to the local-master request.
    input  sep_pkg::sep_system_peripherals_internal_axi_req_t   smn_inbound_req_i,  // SMN inbound request after the inbound filter and global-to-local rebase.
    output sep_pkg::sep_system_peripherals_internal_axi_resp_t  smn_inbound_resp_o,  // Response to the SMN inbound request.

    output sep_pkg::sep_system_peripherals_xbar_slv_axi_req_t          smn_inbound_from_xbar_axi_req_o,  // Request for any address below 0x4000_0000 outside the mailbox and system CSR
                                                                                                         // windows, forwarded to the SEP local xbar in sep_system_peripherals.
    input  sep_pkg::sep_system_peripherals_xbar_slv_axi_resp_t         smn_inbound_from_xbar_axi_resp_i,  // Response to smn_inbound_from_xbar_axi_req_o.
    output sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t   mailbox_req_o,  // Mailbox request for 0x10A0_0000-0x10A0_FFFF.
    input  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t  mailbox_resp_i,  // Mailbox response.
    output sep_pkg::sep_system_peripherals_system_csr_axi_lite_req_t   system_csr_req_o,  // System CSR request for 0x10A1_0000-0x10A4_FFFF or 0x1080_2000-0x1080_20FF.
    input  sep_pkg::sep_system_peripherals_system_csr_axi_lite_resp_t  system_csr_resp_i  // System CSR response.
);

    // =========================================================================
    // Internal signals using xbar package types
    // =========================================================================

    // Initiator ports (inputs to xbar) - 5-bit ID (MaxInputIdW), 56-bit addr
    sep_system_peripherals_xbar_pkg::axi64_req_t       sep_local_from_remap_req;
    sep_system_peripherals_xbar_pkg::axi64_resp_t      sep_local_from_remap_resp;
    sep_system_peripherals_xbar_pkg::axi64_req_t       smn_inbound_req;
    sep_system_peripherals_xbar_pkg::axi64_resp_t      smn_inbound_resp;

    // Target ports (outputs from xbar) - 6-bit ID (XbarOutputIdW), 56-bit addr
    sep_system_peripherals_xbar_pkg::axi_out_req_t        smn_inbound_from_xbar_axi_req;
    sep_system_peripherals_xbar_pkg::axi_out_resp_t       smn_inbound_from_xbar_axi_resp;
    sep_system_peripherals_xbar_pkg::axi_lite64_req_t     mailbox_req;
    sep_system_peripherals_xbar_pkg::axi_lite64_resp_t    mailbox_resp;
    sep_system_peripherals_xbar_pkg::axi_lite64_req_t     system_csr_req;
    sep_system_peripherals_xbar_pkg::axi_lite64_resp_t    system_csr_resp;

    // =========================================================================
    // Input port assignments (sep_pkg -> xbar_pkg)
    // =========================================================================

    // sep_local_from_remap (3-bit ID input, zero-extended to 5-bit for xbar)
    `AXI_ASSIGN_REQ_STRUCT(sep_local_from_remap_req, sep_local_from_remap_req_i)
    `AXI_ASSIGN_RESP_STRUCT(sep_local_from_remap_resp_o, sep_local_from_remap_resp)

    // smn_inbound (5-bit ID input, matches xbar's axi64_req_t)
    `AXI_ASSIGN_REQ_STRUCT(smn_inbound_req, smn_inbound_req_i)
    `AXI_ASSIGN_RESP_STRUCT(smn_inbound_resp_o, smn_inbound_resp)

    // =========================================================================
    // Output port assignments (xbar_pkg -> sep_pkg)
    // All AXI4 output ports have 6-bit ID, 56-bit addr, 64-bit data, 12-bit user
    // =========================================================================

    // smn_inbound_from_xbar_axi_req
    `AXI_ASSIGN_REQ_STRUCT(smn_inbound_from_xbar_axi_req_o, smn_inbound_from_xbar_axi_req)
    `AXI_ASSIGN_RESP_STRUCT(smn_inbound_from_xbar_axi_resp, smn_inbound_from_xbar_axi_resp_i)

    // mailbox
    `AXI_LITE_ASSIGN_REQ_STRUCT(mailbox_req_o, mailbox_req)
    `AXI_LITE_ASSIGN_RESP_STRUCT(mailbox_resp, mailbox_resp_i)

    // system_csr
    `AXI_LITE_ASSIGN_REQ_STRUCT(system_csr_req_o, system_csr_req)
    `AXI_LITE_ASSIGN_RESP_STRUCT(system_csr_resp, system_csr_resp_i)

    // =========================================================================
    // Crossbar
    // =========================================================================
    sep_system_peripherals_xbar u_sep_system_peripherals_xbar (
        .clk_i                              (clk_i),
        .rst_ni                             (rst_ni),
        .test_i                             (test_i),

        // Initiator ports
        .sep_local_from_remap_req_i         (sep_local_from_remap_req),
        .sep_local_from_remap_resp_o        (sep_local_from_remap_resp),
        .smn_inbound_req_i                  (smn_inbound_req),
        .smn_inbound_resp_o                 (smn_inbound_resp),

        // Target ports
        .smn_inbound_from_xbar_req_o        (smn_inbound_from_xbar_axi_req),
        .smn_inbound_from_xbar_resp_i       (smn_inbound_from_xbar_axi_resp),
        .mailbox_req_o                      (mailbox_req),
        .mailbox_resp_i                     (mailbox_resp),
        .system_csr_req_o                   (system_csr_req),
        .system_csr_resp_i                  (system_csr_resp)
    );

    // =========================================================================
    // Type Width Assertions
    // Verify sep_pkg types match sep_system_peripherals_xbar_pkg types
    // =========================================================================

`ifdef OCAH_DEBUG_LIVE  // elaboration-time width checks; excluded from synthesis
    // Input ports
    initial begin : gen_input_type_assertions
        // sep_local_from_remap (3-bit ID input, xbar uses 5-bit - zero-extension is OK)
        assert ($bits(sep_local_from_remap_req_i.aw.addr) == $bits(sep_local_from_remap_req.aw.addr)) else $fatal(1, "SEP_LOCAL_FROM_REMAP AW ADDR width mismatch");
        assert ($bits(sep_local_from_remap_req_i.w.data)  == $bits(sep_local_from_remap_req.w.data))  else $fatal(1, "SEP_LOCAL_FROM_REMAP W DATA width mismatch");

        // smn_inbound (5-bit ID input, matches xbar's axi64_req_t)
        assert ($bits(smn_inbound_req_i.aw.id)   == $bits(smn_inbound_req.aw.id))   else $fatal(1, "SMN_INBOUND AW ID width mismatch");
        assert ($bits(smn_inbound_req_i.aw.addr) == $bits(smn_inbound_req.aw.addr)) else $fatal(1, "SMN_INBOUND AW ADDR width mismatch");
        assert ($bits(smn_inbound_req_i.w.data)  == $bits(smn_inbound_req.w.data))  else $fatal(1, "SMN_INBOUND W DATA width mismatch");
        assert ($bits(smn_inbound_req_i.ar.id)   == $bits(smn_inbound_req.ar.id))   else $fatal(1, "SMN_INBOUND AR ID width mismatch");
        assert ($bits(smn_inbound_resp_o.r.id)   == $bits(smn_inbound_resp.r.id))   else $fatal(1, "SMN_INBOUND R ID width mismatch");
        assert ($bits(smn_inbound_resp_o.b.id)   == $bits(smn_inbound_resp.b.id))   else $fatal(1, "SMN_INBOUND B ID width mismatch");
    end

    // Output ports (6-bit ID, 56-bit addr, 64-bit data, 12-bit user)
    initial begin : gen_output_type_assertions
        // smn_inbound_from_xbar_axi_req
        assert ($bits(smn_inbound_from_xbar_axi_req_o.aw.id)   == $bits(smn_inbound_from_xbar_axi_req.aw.id))   else $fatal(1, "SMN_INBOUND_FROM_XBAR_AXI_REQ AW ID width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_req_o.aw.addr) == $bits(smn_inbound_from_xbar_axi_req.aw.addr)) else $fatal(1, "SMN_INBOUND_FROM_XBAR_AXI_REQ AW ADDR width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_req_o.w.data)  == $bits(smn_inbound_from_xbar_axi_req.w.data))  else $fatal(1, "SMN_INBOUND_FROM_XBAR_AXI_REQ W DATA width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_req_o.ar.id)   == $bits(smn_inbound_from_xbar_axi_req.ar.id))   else $fatal(1, "SMN_INBOUND_FROM_XBAR_AXI_REQ AR ID width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_resp_i.r.id)   == $bits(smn_inbound_from_xbar_axi_resp.r.id))   else $fatal(1, "SMN_INBOUND_FROM_XBAR_AXI_RESP R ID width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_resp_i.b.id)   == $bits(smn_inbound_from_xbar_axi_resp.b.id))   else $fatal(1, "SMN_INBOUND_FROM_XBAR_AXI_RESP B ID width mismatch");

        // mailbox
        assert ($bits(mailbox_req_o.aw.addr) == $bits(mailbox_req.aw.addr)) else $fatal(1, "MAILBOX AW ADDR width mismatch");
        assert ($bits(mailbox_req_o.w.data)  == $bits(mailbox_req.w.data))  else $fatal(1, "MAILBOX W DATA width mismatch");
        assert ($bits(mailbox_resp_i.r.data)   == $bits(mailbox_resp.r.data))   else $fatal(1, "MAILBOX R DATA width mismatch");

        // system_csr
        assert ($bits(system_csr_req_o.aw.addr) == $bits(system_csr_req.aw.addr)) else $fatal(1, "SYSTEM_CSR AW ADDR width mismatch");
        assert ($bits(system_csr_req_o.w.data)  == $bits(system_csr_req.w.data))  else $fatal(1, "SYSTEM_CSR W DATA width mismatch");
        assert ($bits(system_csr_resp_i.r.data)   == $bits(system_csr_resp.r.data))   else $fatal(1, "SYSTEM_CSR R DATA width mismatch");

    end

    // User-field width assertions (AXI4 ports only; mailbox/system_csr are AXI-Lite)
    initial begin : gen_user_width_assertions
        // Input ports
        assert ($bits(sep_local_from_remap_req_i.aw.user)  == $bits(sep_local_from_remap_req.aw.user))  else $fatal(1, "SEP_LOCAL_FROM_REMAP AW USER width mismatch");
        assert ($bits(sep_local_from_remap_req_i.w.user)   == $bits(sep_local_from_remap_req.w.user))   else $fatal(1, "SEP_LOCAL_FROM_REMAP W USER width mismatch");
        assert ($bits(sep_local_from_remap_req_i.ar.user)  == $bits(sep_local_from_remap_req.ar.user))  else $fatal(1, "SEP_LOCAL_FROM_REMAP AR USER width mismatch");
        assert ($bits(sep_local_from_remap_resp_o.r.user)  == $bits(sep_local_from_remap_resp.r.user))  else $fatal(1, "SEP_LOCAL_FROM_REMAP R USER width mismatch");
        assert ($bits(sep_local_from_remap_resp_o.b.user)  == $bits(sep_local_from_remap_resp.b.user))  else $fatal(1, "SEP_LOCAL_FROM_REMAP B USER width mismatch");

        assert ($bits(smn_inbound_req_i.aw.user)  == $bits(smn_inbound_req.aw.user))  else $fatal(1, "SMN_INBOUND AW USER width mismatch");
        assert ($bits(smn_inbound_req_i.w.user)   == $bits(smn_inbound_req.w.user))   else $fatal(1, "SMN_INBOUND W USER width mismatch");
        assert ($bits(smn_inbound_req_i.ar.user)  == $bits(smn_inbound_req.ar.user))  else $fatal(1, "SMN_INBOUND AR USER width mismatch");
        assert ($bits(smn_inbound_resp_o.r.user)  == $bits(smn_inbound_resp.r.user))  else $fatal(1, "SMN_INBOUND R USER width mismatch");
        assert ($bits(smn_inbound_resp_o.b.user)  == $bits(smn_inbound_resp.b.user))  else $fatal(1, "SMN_INBOUND B USER width mismatch");

        // Output ports (AXI4)
        assert ($bits(smn_inbound_from_xbar_axi_req_o.aw.user)  == $bits(smn_inbound_from_xbar_axi_req.aw.user))  else $fatal(1, "SMN_INBOUND_FROM_XBAR AW USER width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_req_o.w.user)   == $bits(smn_inbound_from_xbar_axi_req.w.user))   else $fatal(1, "SMN_INBOUND_FROM_XBAR W USER width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_req_o.ar.user)  == $bits(smn_inbound_from_xbar_axi_req.ar.user))  else $fatal(1, "SMN_INBOUND_FROM_XBAR AR USER width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_resp_i.r.user)  == $bits(smn_inbound_from_xbar_axi_resp.r.user))  else $fatal(1, "SMN_INBOUND_FROM_XBAR R USER width mismatch");
        assert ($bits(smn_inbound_from_xbar_axi_resp_i.b.user)  == $bits(smn_inbound_from_xbar_axi_resp.b.user))  else $fatal(1, "SMN_INBOUND_FROM_XBAR B USER width mismatch");
    end
`endif  // OCAH_DEBUG_LIVE

endmodule : sep_system_peripherals_xbar_wrapper
