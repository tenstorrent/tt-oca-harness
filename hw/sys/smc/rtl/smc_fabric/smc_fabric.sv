// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Compose the SMC interconnect fabric from its input, local and output stages.
//
// The input fabric alias-remaps the JTAG, CPU MMIO, log and data accelerator initiators and
// filters system inbound AXI; SMC-window traffic, including SEP, goes to the local fabric
// toward the CPU front port and SMC CSRs, and other traffic goes to the output fabric, which
// applies the M-mode and Xvisor output remap and the outbound filter before the system AXI
// output. Window decode uses the base-config global base, local base and region size.

`include "axi/assign.svh"

module smc_fabric #(
  parameter bit          NO_ADDR_REMAP   = 1'b1,  // Removes the output fabric's M-mode and
                                                  // Xvisor output remap when the integration
                                                  // map is fixed, replacing it with an
                                                  // ID-width converter, which reduces area.
                                                  // The input fabric's alias remap remains.
  parameter int unsigned SYS_IN_ID_WIDTH = 9,  // Unused; the input fabric takes the system input ID
                                               // width from smc_pkg::SysInIdWidth.

  parameter int unsigned NUM_INBOUND_FILTERS        = 16,  // Number of filter entries on the system
                                                           // AXI input; sizes the inbound filter
                                                           // CSR arrays and the input fabric
                                                           // hit-index outputs.
  parameter int unsigned NUM_OUTBOUND_FILTERS       = 16,  // Number of filter entries on the system
                                                           // AXI output; sizes the outbound filter
                                                           // CSR arrays and the output fabric
                                                           // hit-index outputs.
  parameter int unsigned MAX_TRANS                  = smc_pkg::FabricMaxTrans,    // Outstanding transactions per ID bucket
                                                                                  // tracked by the output fabric remap demux
                                                                                  // and mux; unused when NO_ADDR_REMAP is set.
  parameter bit          FILTER_REQ_PIPELINE_ENABLE = 1'b0,  // Adds spill registers on the request
                                                             // channels at the inbound and outbound
                                                             // filter boundaries, trading a cycle
                                                             // of latency for easier timing
                                                             // closure.
  parameter bit          FILTER_RSP_PIPELINE_ENABLE = 1'b0  // Adds spill registers on the response
                                                            // channels at the inbound and outbound
                                                            // filter boundaries, trading a cycle of
                                                            // latency for easier timing closure.
) (
  input  logic clk_i,                   // SMC core clock.
  input  logic rst_ni,                  // Primary reset, active-low, synchronized to the SMC core
                                        // clock.
  input  logic test_en_i,               // Scan test mode enable, active-high; forwarded to the
                                        // fabric stages and forces their clock gates on.
  input  logic scan_rst_ni,             // Scan reset, active-low; forwarded to the input fabric,
                                        // which does not use it.

  input  smc_pkg::smc_axi_addr_t global_base_addr_i,  // Global base address of the SMC address
                                                      // window, from the base-config registers; the
                                                      // input and output fabrics decode SMC
                                                      // accesses against it.
  input  smc_pkg::smc_axi_addr_t local_base_addr_i,  // Local base address of the SMC address
                                                     // window, from the base-config registers; the
                                                     // input and output fabrics also decode SMC
                                                     // accesses against it, and the local fabric
                                                     // rebases every request onto it.
  input  logic [31:0]            region_size_i,  // Size in bytes of the SMC address window at
                                                 // either base, a power of two by software
                                                 // contract.

  input  logic                ob_filter_axi_cg_en_i,  // Enables clock gating of the system outbound
                                                      // filter, active-high; low keeps its clock
                                                      // running.
  input  logic                ib_filter_axi_cg_en_i,  // Enables clock gating of the system inbound
                                                      // filter, active-high; low keeps its clock
                                                      // running.
  input  logic                fabric_cg_en_i,  // Enables clock gating of the output fabric remap
                                               // demux and mux, active-high; low keeps their clock
                                               // running. Unused when NO_ADDR_REMAP is set.
  input  smc_pkg::cg_hyster_t cg_hysteresis_i,  // Idle SMC core clock cycles the fabric and filter
                                                // clock gates wait after their bus goes quiet
                                                // before stopping the gated clock.

  input  smc_pkg::smc_jtag_56_64_2_12_axi_req_t          axi_in_jtag_req_i,  // JTAG AXI request into the
                                                                             // input fabric, which widens
                                                                             // its ID and alias-remaps it.
  output smc_pkg::smc_jtag_56_64_2_12_axi_resp_t         axi_in_jtag_resp_o,  // JTAG AXI response from the
                                                                              // input fabric.
  input  smc_pkg::smc_cpu_mmio_axi_req_t                 axi_in_mmio_req_i,  // CPU MMIO AXI request into the
                                                                             // input fabric, which widens
                                                                             // its ID and alias-remaps it.
  output smc_pkg::smc_cpu_mmio_axi_resp_t                axi_in_mmio_resp_o,  // CPU MMIO AXI response from the
                                                                              // input fabric.
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t  axi_in_data_accel_req_i,  // Data accelerator AXI request
                                                                                   // into the input fabric, which
                                                                                   // alias-remaps it.
  output smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t axi_in_data_accel_resp_o,  // Data accelerator AXI response
                                                                                    // from the input fabric.
  input  smc_pkg::smc_axil_56_64_req_t                   axi_lite_log_req_i,  // Log engine AXI-Lite request
                                                                              // into the input fabric, which
                                                                              // converts it to AXI and
                                                                              // alias-remaps it.
  output smc_pkg::smc_axil_56_64_resp_t                  axi_lite_log_resp_o,  // Log engine AXI-Lite response
                                                                               // from the input fabric.

  input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req_i,  // System AXI input request;
                                                                      // passes the inbound filter,
                                                                      // and outside the SMC window
                                                                      // receives DECERR.
  output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp_o,  // System AXI input response.

  input  smc_pkg::smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req_i,  // SEP AXI input request;
                                                                      // unfiltered, and outside the
                                                                      // SMC window receives DECERR.
  output smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp_o,  // SEP AXI input response.

  output smc_pkg::smc_local_32_64_8_12_axi_req_t  axi_front_port_req_o,  // AXI request from the local
                                                                         // fabric to the CPU cluster's
                                                                         // front port.
  input  smc_pkg::smc_local_32_64_8_12_axi_resp_t axi_front_port_rsp_i,  // AXI response from the CPU
                                                                         // cluster's front port.
  output smc_pkg::smc_dfd_apb_req_t               apb_smc_dfd_reg_req_o,  // APB request from the local
                                                                          // fabric for the SMC CLA (DFD)
                                                                          // register window.
  input  smc_pkg::smc_dfd_apb_resp_t              apb_smc_dfd_reg_resp_i,  // APB response from the SMC
                                                                           // CLA (DFD) registers.
  output smc_pkg::smc_local_32_64_8_12_axi_req_t  axi_data_accel_ctrl_req_o,  // AXI request from the local
                                                                              // fabric to the data
                                                                              // accelerator's control port.
  input  smc_pkg::smc_local_32_64_8_12_axi_resp_t axi_data_accel_ctrl_rsp_i,  // AXI response from the data
                                                                              // accelerator's control port.
  output smc_pkg::smc_axil_32_32_req_t            axil_peripherals_req_o,  // 32-bit AXI-Lite request from
                                                                           // the local fabric to the
                                                                           // peripheral CSR crossbar.
  input  smc_pkg::smc_axil_32_32_resp_t           axil_peripherals_resp_i,  // 32-bit AXI-Lite response from
                                                                            // the peripheral CSR crossbar.

  output smc_pkg::smc_axil_32_64_req_t  axil_aR_ctrl_req_o,  // AXI-Lite request for the alias remap
                                                             // control registers.
  input  smc_pkg::smc_axil_32_64_resp_t axil_aR_ctrl_resp_i,  // AXI-Lite response from the alias
                                                              // remap control registers.
  output smc_pkg::smc_axil_32_64_req_t  axil_mR_ctrl_req_o,  // AXI-Lite request for the M-mode
                                                             // output remap control registers.
  input  smc_pkg::smc_axil_32_64_resp_t axil_mR_ctrl_resp_i,  // AXI-Lite response from the M-mode
                                                              // output remap control registers.
  output smc_pkg::smc_axil_32_64_req_t  axil_xR_ctrl_req_o,  // AXI-Lite request for the Xvisor
                                                             // output remap control registers.
  input  smc_pkg::smc_axil_32_64_resp_t axil_xR_ctrl_resp_i,  // AXI-Lite response from the Xvisor
                                                              // output remap control registers.
  output smc_pkg::smc_axil_32_64_req_t  axil_inbound_filter_ctrl_req_o,  // AXI-Lite request for the
                                                                         // inbound filter control
                                                                         // registers.
  input  smc_pkg::smc_axil_32_64_resp_t axil_inbound_filter_ctrl_resp_i,  // AXI-Lite response from the
                                                                          // inbound filter control
                                                                          // registers.
  output smc_pkg::smc_axil_32_64_req_t  axil_outbound_filter_ctrl_req_o,  // AXI-Lite request for the
                                                                          // outbound filter control
                                                                          // registers.
  input  smc_pkg::smc_axil_32_64_resp_t axil_outbound_filter_ctrl_resp_i,  // AXI-Lite response from the
                                                                           // outbound filter control
                                                                           // registers.
  output smc_pkg::smc_axil_32_64_req_t  axil_mailbox_req_o,  // AXI-Lite request for the SMC mailbox
                                                             // window.
  input  smc_pkg::smc_axil_32_64_resp_t axil_mailbox_resp_i,  // AXI-Lite response from the SMC
                                                              // mailbox.
  output smc_pkg::smc_axil_32_64_req_t  axil_smc_base_config_req_o,  // AXI-Lite request for the SMC base
                                                                     // configuration registers.
  input  smc_pkg::smc_axil_32_64_resp_t axil_smc_base_config_resp_i,  // AXI-Lite response from the SMC
                                                                      // base configuration registers.
  output smc_pkg::smc_axil_32_64_req_t  axil_dfx_csr_req_o,  // AXI-Lite request for the DFX control
                                                             // register window.
  input  smc_pkg::smc_axil_32_64_resp_t axil_dfx_csr_resp_i,  // AXI-Lite response from the DFX
                                                              // control registers.

  output smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  axi_filtered_remapped_req_o,  // System AXI output
                                                                                  // request from the
                                                                                  // output fabric, after
                                                                                  // output remap and the
                                                                                  // outbound filter.
  input  smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t axi_filtered_remapped_resp_i,  // System AXI output
                                                                                   // response.

  input  filter_ctrl_reg_pkg::filter_ctrl__out_t outbound_filter_ctrl_i [NUM_OUTBOUND_FILTERS-1:0],  // Per-entry
                                                                                                     // configuration
                                                                                                     // of the system
                                                                                                     // outbound filter.
  output filter_ctrl_reg_pkg::filter_ctrl__in_t  outbound_filter_status_o [NUM_OUTBOUND_FILTERS-1:0],  // Per-entry
                                                                                                       // status of the
                                                                                                       // system outbound
                                                                                                       // filter.
  input  filter_ctrl_reg_pkg::filter_ctrl__out_t inbound_filter_ctrl_i [NUM_INBOUND_FILTERS-1:0],  // Per-entry
                                                                                                   // configuration
                                                                                                   // of the system
                                                                                                   // inbound filter.
  output filter_ctrl_reg_pkg::filter_ctrl__in_t  inbound_filter_status_o [NUM_INBOUND_FILTERS-1:0],  // Per-entry
                                                                                                     // status of the
                                                                                                     // system inbound
                                                                                                     // filter.

  input  output_remap_reg_pkg::output_remap__out_t mR_ctrl_i [smc_pkg::NumMmodeOutputRemapRegions-1:0],      // M-mode output
                                                                                                             // remap region
                                                                                                             // configuration.
  input  output_remap_reg_pkg::output_remap__out_t xR_ctrl_i [smc_pkg::NumXvisorOutputRemapRegions-1:0],      // Xvisor output
                                                                                                              // remap region
                                                                                                              // configuration.
  input  alias_remap_reg_pkg::alias_remap__out_t   aR_ctrl_i [smc_pkg::NumAliasRemapRegions-1:0],     // Alias remap
                                                                                                      // region
                                                                                                      // configuration.

  output smc_pkg::remap_debug_t                   remap_debug_mmio_o,  // Alias region index hit by the MMIO
                                                                       // path.
  output smc_pkg::remap_debug_t                   remap_debug_jtag_o,  // Alias region index hit by the JTAG
                                                                       // path.
  output smc_pkg::remap_debug_t                   remap_debug_log_o,  // Alias region index hit by the log
                                                                      // path.
  output smc_pkg::remap_debug_t                   remap_debug_dma_o,  // Alias region index hit by the data
                                                                      // accelerator path.
  output logic [$clog2(NUM_INBOUND_FILTERS)-1:0]  inbound_write_filter_hit_debug_o,  // Lowest system inbound filter
                                                                                     // entry hit by a write.
  output logic [$clog2(NUM_INBOUND_FILTERS)-1:0]  inbound_read_filter_hit_debug_o,  // Lowest system inbound filter
                                                                                    // entry hit by a read.
  output logic [$clog2(NUM_OUTBOUND_FILTERS)-1:0] outbound_write_filter_hit_debug_o,  // Lowest system outbound filter
                                                                                      // entry hit by a write.
  output logic [$clog2(NUM_OUTBOUND_FILTERS)-1:0] outbound_read_filter_hit_debug_o,  // Lowest system outbound filter
                                                                                     // entry hit by a read.

  output logic fabric_clk_active_o,     // High while the output fabric remap clock runs; low when
                                        // NO_ADDR_REMAP is set.
  output logic fabric_bus_active_o,     // High while the output fabric input has a request valid or
                                        // a transaction outstanding; low when NO_ADDR_REMAP is set.
  output logic sys_out_filter_clk_active_o,  // High while the system outbound filter clock runs.
  output logic sys_out_filter_bus_active_o,  // High while the system outbound filter input has a
                                             // request valid or a transaction outstanding.
  output logic sys_in_filter_clk_active_o,  // High while the system inbound filter clock runs.
  output logic sys_in_filter_bus_active_o  // High while the system AXI input has a request valid
                                           // or a transaction outstanding.
);

  // Internal signals for fabric interconnections
  smc_pkg::smc_local_32_64_6_12_axi_req_t  axi_local_out_req;
  smc_pkg::smc_local_32_64_6_12_axi_resp_t axi_local_out_resp;
  smc_pkg::smc_56_64_6_12_axi_req_t  axi_to_output_fabric_req;
  smc_pkg::smc_56_64_6_12_axi_resp_t axi_to_output_fabric_resp;

  smc_pkg::smc_local_32_64_6_12_axi_req_t  filtered_sys_axi_out_req;
  smc_pkg::smc_local_32_64_6_12_axi_resp_t filtered_sys_axi_out_resp;
  smc_pkg::smc_local_32_64_6_12_axi_req_t  sep_axi_id_remap_req;
  smc_pkg::smc_local_32_64_6_12_axi_resp_t sep_axi_id_remap_resp;

  ////////////////////////
  // Input Fabric Logic //
  ////////////////////////

  smc_input_fabric #(
    .FILTER_REQ_PIPELINE_ENABLE (FILTER_REQ_PIPELINE_ENABLE),
    .FILTER_RSP_PIPELINE_ENABLE (FILTER_RSP_PIPELINE_ENABLE),
    .NUM_FILTERS                (NUM_INBOUND_FILTERS)
  ) u_smc_input_fabric (
    .clk_i                      (clk_i),
    .rst_ni                     (rst_ni),
    .test_en_i                  (test_en_i),
    .scan_rst_ni                (scan_rst_ni),

    .filter_axi_cg_en_i         (ib_filter_axi_cg_en_i),
    .cg_hysteresis_i            (cg_hysteresis_i),

    .global_base_addr_i         (global_base_addr_i),
    .local_base_addr_i          (local_base_addr_i),
    .region_size_i              (region_size_i),
    .axi_in_jtag_req_i          (axi_in_jtag_req_i),
    .axi_in_jtag_resp_o         (axi_in_jtag_resp_o),
    .axi_in_mmio_req_i          (axi_in_mmio_req_i),
    .axi_in_mmio_resp_o         (axi_in_mmio_resp_o),
    .axi_in_data_accel_req_i    (axi_in_data_accel_req_i),
    .axi_in_data_accel_resp_o   (axi_in_data_accel_resp_o),
    .axi_lite_log_req_i         (axi_lite_log_req_i),
    .axi_lite_log_resp_o        (axi_lite_log_resp_o),
    .axi_local_out_req_o        (axi_local_out_req),
    .axi_local_out_resp_i       (axi_local_out_resp),
    .axi_out_req_o              (axi_to_output_fabric_req),
    .axi_out_resp_i             (axi_to_output_fabric_resp),

    .sys_axi_in_req_i           (sys_axi_in_req_i),
    .sys_axi_in_resp_o          (sys_axi_in_resp_o),
    .filtered_sys_axi_out_req_o (filtered_sys_axi_out_req),
    .filtered_sys_axi_out_resp_i(filtered_sys_axi_out_resp),

    .sep_axi_in_req_i           (sep_axi_in_req_i),
    .sep_axi_in_resp_o          (sep_axi_in_resp_o),
    .sep_axi_id_remap_req_o     (sep_axi_id_remap_req),
    .sep_axi_id_remap_resp_i    (sep_axi_id_remap_resp),

    // CSR structs for filter configuration
    .filter_ctrl_i              (inbound_filter_ctrl_i),
    .filter_status_o            (inbound_filter_status_o),

    // CSR structs for remap configuration
    .aR_ctrl_i                  (aR_ctrl_i),

    // Debug outputs
    .remap_debug_mmio_o         (remap_debug_mmio_o),
    .remap_debug_jtag_o         (remap_debug_jtag_o),
    .remap_debug_log_o          (remap_debug_log_o),
    .remap_debug_dma_o          (remap_debug_dma_o),
    .write_filter_hit_debug_o   (inbound_write_filter_hit_debug_o),
    .read_filter_hit_debug_o    (inbound_read_filter_hit_debug_o),

    // Clock gater activity indicators
    .sys_in_filter_clk_active_o (sys_in_filter_clk_active_o),
    .sys_in_filter_bus_active_o (sys_in_filter_bus_active_o)
  );

  ///////////////////////
  // Local Fabric Logic //
  ///////////////////////

  smc_local_fabric u_smc_local_fabric (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),
    .test_en_i                          (test_en_i),
    .local_base_addr_i                  (local_base_addr_i),
    .region_size_i                      (region_size_i),
    .input_axi_req_i                    (filtered_sys_axi_out_req),
    .input_axi_rsp_o                    (filtered_sys_axi_out_resp),
    .sep_in_axi_req_i                   (sep_axi_id_remap_req),
    .sep_in_axi_rsp_o                   (sep_axi_id_remap_resp),
    .local_axi_req_i                    (axi_local_out_req),
    .local_axi_rsp_o                    (axi_local_out_resp),
    .axi_front_port_req_o               (axi_front_port_req_o),
    .axi_front_port_rsp_i               (axi_front_port_rsp_i),
    .apb_smc_dfd_reg_req_o              (apb_smc_dfd_reg_req_o),
    .apb_smc_dfd_reg_resp_i             (apb_smc_dfd_reg_resp_i),
    .axi_data_accel_ctrl_req_o          (axi_data_accel_ctrl_req_o),
    .axi_data_accel_ctrl_rsp_i          (axi_data_accel_ctrl_rsp_i),

    .periph_reg_req_o                   (axil_peripherals_req_o),
    .periph_reg_resp_i                  (axil_peripherals_resp_i),

    .axil_aR_ctrl_req_o                 (axil_aR_ctrl_req_o),
    .axil_aR_ctrl_resp_i                (axil_aR_ctrl_resp_i),
    .axil_mR_ctrl_req_o                 (axil_mR_ctrl_req_o),
    .axil_mR_ctrl_resp_i                (axil_mR_ctrl_resp_i),
    .axil_xR_ctrl_req_o                 (axil_xR_ctrl_req_o),
    .axil_xR_ctrl_resp_i                (axil_xR_ctrl_resp_i),
    .axil_inbound_filter_ctrl_req_o     (axil_inbound_filter_ctrl_req_o),
    .axil_inbound_filter_ctrl_resp_i    (axil_inbound_filter_ctrl_resp_i),
    .axil_outbound_filter_ctrl_req_o    (axil_outbound_filter_ctrl_req_o),
    .axil_outbound_filter_ctrl_resp_i   (axil_outbound_filter_ctrl_resp_i),
    .axil_mailbox_req_o                 (axil_mailbox_req_o),
    .axil_mailbox_resp_i                (axil_mailbox_resp_i),
    .axil_smc_base_config_req_o         (axil_smc_base_config_req_o),
    .axil_smc_base_config_resp_i        (axil_smc_base_config_resp_i),
    .axil_dfx_csr_req_o                 (axil_dfx_csr_req_o),
    .axil_dfx_csr_resp_i                (axil_dfx_csr_resp_i)
  );

  ////////////////////////
  // Output Fabric Logic //
  ////////////////////////

  smc_output_fabric #(
    .NO_ADDR_REMAP              (NO_ADDR_REMAP),
    .NUM_FILTERS                (NUM_OUTBOUND_FILTERS),
    .MAX_TRANS                  (MAX_TRANS),
    .FILTER_REQ_PIPELINE_ENABLE (FILTER_REQ_PIPELINE_ENABLE),
    .FILTER_RSP_PIPELINE_ENABLE (FILTER_RSP_PIPELINE_ENABLE)
  ) u_smc_output_fabric (
    .clk_i                        (clk_i),
    .rst_ni                       (rst_ni),
    .test_en_i                    (test_en_i),
    .global_base_addr_i           (global_base_addr_i),
    .local_base_addr_i            (local_base_addr_i),

    .filter_axi_cg_en_i           (ob_filter_axi_cg_en_i),
    .fabric_cg_en_i               (fabric_cg_en_i),
    .cg_hysteresis_i              (cg_hysteresis_i),

    // AXI Buses
    .axi_req_i                    (axi_to_output_fabric_req),
    .axi_resp_o                   (axi_to_output_fabric_resp),
    .axi_filtered_remapped_req_o  (axi_filtered_remapped_req_o),
    .axi_filtered_remapped_resp_i (axi_filtered_remapped_resp_i),

    // CSR structs for filter configurations
    .filter_ctrl_i                (outbound_filter_ctrl_i),
    .filter_status_o              (outbound_filter_status_o),

    // CSR structs for remap configurations
    .mR_ctrl_i                    (mR_ctrl_i),
    .xR_ctrl_i                    (xR_ctrl_i),

    // Debug outputs
    .write_filter_hit_debug_o     (outbound_write_filter_hit_debug_o),
    .read_filter_hit_debug_o      (outbound_read_filter_hit_debug_o),

    // Clock gater activity indicators
    .fabric_clk_active_o         (fabric_clk_active_o),
    .fabric_bus_active_o         (fabric_bus_active_o),
    .sys_out_filter_clk_active_o (sys_out_filter_clk_active_o),
    .sys_out_filter_bus_active_o (sys_out_filter_bus_active_o)
  );

endmodule
