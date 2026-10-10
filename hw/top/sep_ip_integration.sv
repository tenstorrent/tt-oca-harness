// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SEP IP Integration -- 3rd party IP, macros, and shims
//
// Open-source reference models for sep.sv's technology-specific IP: the
// shared eFuse bank/shim model, OpenTitan generic RAM/ROM primitives for
// the SRAM/ROM/OTBN/Key-Manager memory macros, the OpenTitan-derived TCM
// ICCM/DCCM wrapper, and DECERR slaves terminating the external-TRNG and
// AXI extension windows.
//
// sep_wrapper.sv instantiates this module alongside the bare sep.sv core
// and wires the two together for standalone SEP reference simulation.
//
// This is a reference integration example, provided for adopters to
// substitute with their own vendor IP/macros.
//-----------------------------------------------------------------------------

`include "ocah_assert.svh"
`include "ocah_registers.svh"

module sep_ip_integration
  import sep_pkg::*;
  import sep_crypto_pkg::*;
  import sep_efuse_pkg::*;
  import km_intf_pkg::*;
#(
  parameter int unsigned EXT_TRNG_NUM_AXIS = sep_crypto_pkg::SepCryptoEdnEndpointCount,
  parameter bit          ABR_MASKING_EN    = 1'b1
) (
  input logic clk_i,
  input logic rst_ni,

  // Test/DFT passthrough (used by the AXI extension error slave's test_i)
  input logic test_en_i,

  // SRAM interface (from sep.sv)
  input  sep_sram_req_t sep_sram_req,
  output sep_sram_rsp_t sep_sram_rsp,

  // Boot ROM interface (from sep.sv)
  input  sep_sram_req_t sep_boot_rom_req,
  output sep_sram_rsp_t sep_boot_rom_rsp,

  // TCM interface (from sep.sv)
  input  sep_cpu_tcm_req_t sep_cpu_tcm_req_i,
  output sep_cpu_tcm_rsp_t sep_cpu_tcm_rsp_o,

  // OTBN external SRAM interfaces (from prim_ram_1p_scr_ext inside OTBN,
  // re-exposed at sep.sv's boundary)
  input  sep_crypto_pka_imem_sram_req_t sep_crypto_pka_imem_sram_req,
  output sep_crypto_pka_imem_sram_rsp_t sep_crypto_pka_imem_sram_rsp,
  input  sep_crypto_pka_dmem_sram_req_t sep_crypto_pka_dmem_sram_req,
  output sep_crypto_pka_dmem_sram_rsp_t sep_crypto_pka_dmem_sram_rsp,

  // Adams Bridge SRAM channels (from sep.sv), packed as request/response structs
  input  sep_crypto_pkg::abr_mem_req_t abr_mem_req_i,
  output sep_crypto_pkg::abr_mem_rsp_t abr_mem_rsp_o,

  // Key Manager ROM/SRAM memory interfaces (from sep.sv)
  input  km_intf_pkg::km_rom_mem_req_t  km_rom_mem_req_i,
  output km_intf_pkg::km_rom_mem_rsp_t  km_rom_mem_rsp_o,
  input  km_intf_pkg::km_sram_mem_req_t km_sram_mem_req_i,
  output km_intf_pkg::km_sram_mem_rsp_t km_sram_mem_rsp_o,

  // Efuse interfaces (from sep.sv)
  input  sep_efuse_pkg::efuse_axil_req_t     efuse_bank_ctrl_req_i,
  output sep_efuse_pkg::efuse_axil_resp_t    efuse_bank_ctrl_resp_o,
  input  sep_efuse_pkg::fuse_command_req_t   efuse_shim_command_req_i,
  output sep_efuse_pkg::fuse_command_resp_t  efuse_shim_command_resp_o,

  // External TRNG AXI-Lite CSR interface (from sep.sv)
  input  sep_pkg::sep_32_32_axil_req_t  ext_trng_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t ext_trng_axil_resp_o,

  // External TRNG AXI-Stream (to sep.sv)
  output ext_trng_axis_req_t ext_trng_axis_req_o [EXT_TRNG_NUM_AXIS-1:0],
  input  ext_trng_axis_rsp_t ext_trng_axis_rsp_i [EXT_TRNG_NUM_AXIS-1:0],

  // External TRNG interrupt (to sep.sv)
  output logic ext_trng_irq_o,

  // AXI4 extension interface (from sep.sv)
  input  sep_pkg::sep_32_64_6_12_axi_req_t  axi_extension_axi_req_i,
  output sep_pkg::sep_32_64_6_12_axi_resp_t axi_extension_axi_resp_o,

  // eFuse debug bus (internal shim state, surfaced for DV visibility)
  output logic [15:0] efuse_debug_bus_o
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  sep_efuse_pkg::efuse_apb_req_t  efuse_model_otp_req;
  sep_efuse_pkg::efuse_apb_resp_t efuse_model_otp_resp;

  /////////////////////
  // eFuse SHIM      //
  /////////////////////

  efuse_interface_shim #(
    .SHADOW_REG_BITS      (sep_efuse_pkg::ShadowRegBits),
    .addr_t               (sep_efuse_pkg::addr_t),
    .data_t               (sep_efuse_pkg::data_t),
    .efuse_axil_req_t     (sep_efuse_pkg::efuse_axil_req_t),
    .efuse_axil_resp_t    (sep_efuse_pkg::efuse_axil_resp_t),
    .efuse_apb_req_t      (sep_efuse_pkg::efuse_apb_req_t),
    .efuse_apb_resp_t     (sep_efuse_pkg::efuse_apb_resp_t),
    .efuse_addr_byte_t    (sep_efuse_pkg::efuse_addr_byte_t),
    .efuse_data_t         (sep_efuse_pkg::efuse_data_t),
    .efuse_word_counter_t (sep_efuse_pkg::efuse_word_counter_t),
    .fuse_command_req_t   (sep_efuse_pkg::fuse_command_req_t),
    .fuse_command_resp_t  (sep_efuse_pkg::fuse_command_resp_t)
  ) u_efuse_interface_shim (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),

    .fuse_bank_ctrl_req_i  (efuse_bank_ctrl_req_i),
    .fuse_bank_ctrl_resp_o (efuse_bank_ctrl_resp_o),

    .fuse_command_req_i  (efuse_shim_command_req_i),
    .fuse_command_resp_o (efuse_shim_command_resp_o),

    .efuse_model_otp_req_o  (efuse_model_otp_req),
    .efuse_model_otp_resp_i (efuse_model_otp_resp),

    .debug_bus_o (efuse_debug_bus_o)
  );

  efuse_bank_model #(
    .NUM_FUSE_BYTE_WIDTH (sep_efuse_pkg::NumFuseByteWidth),
    .IS_SMC_INSTANCE     (1'b0),
    .efuse_apb_req_t     (sep_efuse_pkg::efuse_apb_req_t),
    .efuse_apb_resp_t    (sep_efuse_pkg::efuse_apb_resp_t)
  ) u_efuse_bank_model (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),

    .apb_req_i  (efuse_model_otp_req),
    .apb_resp_o (efuse_model_otp_resp),

    .hwif_out_o ()
  );

  //////////////////////////
  // SRAM External Module //
  //////////////////////////

  localparam int unsigned SramNEntries = 256 * 1024 / 8;  // 256KB
  localparam int unsigned SramAddrWidth = $clog2(SramNEntries);
  localparam int unsigned SramDataWidth = 64;

  logic                       sram_macro_req;
  logic                       sram_macro_write;
  logic [SramAddrWidth-1:0]   sram_macro_addr;
  logic [SramDataWidth-1:0]   sram_macro_wdata;
  logic [SramDataWidth-1:0]   sram_macro_wmask;
  logic [SramDataWidth-1:0]   sram_macro_rdata;
  logic                       sram_macro_rvalid;

  sep_sram_interface_shim #(
    .SRAM_ADDR_WIDTH(SramAddrWidth)
  ) u_sep_sram_interface_shim (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .mem_req_i      (sep_sram_req),
    .mem_rsp_o      (sep_sram_rsp),
    .macro_req_o    (sram_macro_req),
    .macro_write_o  (sram_macro_write),
    .macro_addr_o   (sram_macro_addr),
    .macro_wdata_o  (sram_macro_wdata),
    .macro_wmask_o  (sram_macro_wmask),
    .macro_rdata_i  (sram_macro_rdata),
    .macro_rvalid_i (sram_macro_rvalid)
  );

  prim_ram_1p_adv #(
    .Depth       (SramNEntries),
    .Width       (SramDataWidth),
    .MemInitFile ("")
  ) u_sep_sram (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .req_i     (sram_macro_req),
    .write_i   (sram_macro_write),
    .addr_i    (sram_macro_addr),
    .wdata_i   (sram_macro_wdata),
    .wmask_i   (sram_macro_wmask),
    .rdata_o   (sram_macro_rdata),
    .rvalid_o  (sram_macro_rvalid),
    .rerror_o  (),
    .alert_o   (),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  /////////////////////////
  // ROM External Module //
  /////////////////////////

  localparam int unsigned RomDataWidth = 64;
  localparam int unsigned RomNEntries = int'(
      sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_SIZE / (RomDataWidth / 8)
  );
  localparam int unsigned RomAddrWidth = $clog2(RomNEntries);

  logic                      rom_macro_req;
  logic [RomAddrWidth-1:0]   rom_macro_addr;
  logic [RomDataWidth-1:0]   rom_macro_rdata;

  sep_rom_interface_shim #(
    .ROM_ADDR_WIDTH(RomAddrWidth)
  ) u_sep_rom_interface_shim (
    .clk_i         (clk_i),
    .rst_ni        (rst_ni),
    .mem_req_i     (sep_boot_rom_req),
    .mem_rsp_o     (sep_boot_rom_rsp),
    .macro_req_o   (rom_macro_req),
    .macro_addr_o  (rom_macro_addr),
    .macro_rdata_i (rom_macro_rdata)
  );

  prim_rom #(
    .Width       (RomDataWidth),
    .Depth       (RomNEntries),
    .MemInitFile ("")
  ) u_sep_boot_rom (
    .clk_i   (clk_i),
    .rst_ni  (rst_ni),
    .req_i   (rom_macro_req),
    .addr_i  (rom_macro_addr),
    .rdata_o (rom_macro_rdata),
    .cfg_i   ('0)
  );

  /////////////////////////
  // TCM External Module //
  /////////////////////////

  // sep_tcm_wrapper instantiates the VeeR EL2 ICCM/DCCM bank macros
  // (ram_<depth>x39), generated by the core's RAM-generation flow like in
  // upstream VeeR EL2's own reference testbench.
  sep_tcm_wrapper u_sep_tcm_wrapper (
    .tcm_req_i (sep_cpu_tcm_req_i),
    .tcm_rsp_o (sep_cpu_tcm_rsp_o)
  );

  ////////////////////////////
  // KM ROM External Module //
  ////////////////////////////

  localparam int unsigned KmRomDepth = 4096;  // 4K words x 32b = 16KB
  localparam int unsigned KmRomAw = $clog2(KmRomDepth);
  localparam int unsigned KmRomWidth = 36;  // 32 data + 4 parity

  logic [KmRomWidth-1:0]   km_rom_rdata;
  logic                    km_rom_rvalid;

  assign km_rom_mem_rsp_o.gnt    = 1'b1;
  assign km_rom_mem_rsp_o.rvalid = km_rom_rvalid;
  assign km_rom_mem_rsp_o.rdata  = km_rom_rdata[31:0];
  assign km_rom_mem_rsp_o.parity = km_rom_rdata[35:32];

  `OCAH_FF(km_rom_rvalid, km_rom_mem_req_i.req, 1'b0, clk_i, rst_ni)

  prim_rom #(
    .Width       (KmRomWidth),
    .Depth       (KmRomDepth),
    .MemInitFile ("")
  ) u_km_rom (
    .clk_i   (clk_i),
    .rst_ni  (rst_ni),
    .req_i   (km_rom_mem_req_i.req),
    .addr_i  (km_rom_mem_req_i.addr[KmRomAw-1:0]),
    .rdata_o (km_rom_rdata),
    .cfg_i   ('0)
  );

  /////////////////////////////
  // KM SRAM External Module //
  /////////////////////////////

  localparam int unsigned KmSramDepth = 8192;  // 8K words x 32b = 32KB
  localparam int unsigned KmSramAw = $clog2(KmSramDepth);
  localparam int unsigned KmSramWidth = 36;  // 32 data + 4 parity

  logic [KmSramWidth-1:0] km_sram_wdata;
  logic [KmSramWidth-1:0] km_sram_wmask;
  logic [KmSramWidth-1:0] km_sram_rdata;

  assign km_sram_wdata = {km_sram_mem_req_i.wparity, km_sram_mem_req_i.wdata};

  for (genvar b = 0; b < 4; b++) begin : gen_km_sram_wmask
    assign km_sram_wmask[b*8+:8] = {8{km_sram_mem_req_i.be[b]}};
  end
  assign km_sram_wmask[35:32] = km_sram_mem_req_i.be;

  assign km_sram_mem_rsp_o.gnt     = 1'b1;
  assign km_sram_mem_rsp_o.rdata   = km_sram_rdata[31:0];
  assign km_sram_mem_rsp_o.rparity = km_sram_rdata[35:32];

  prim_ram_1p_adv #(
    .Depth       (KmSramDepth),
    .Width       (KmSramWidth),
    .MemInitFile ("")
  ) u_km_sram (
    .clk_i    (clk_i),
    .rst_ni   (rst_ni),
    .req_i    (km_sram_mem_req_i.req),
    .write_i  (km_sram_mem_req_i.we),
    .addr_i   (km_sram_mem_req_i.addr[KmSramAw-1:0]),
    .wdata_i  (km_sram_wdata),
    .wmask_i  (km_sram_wmask),
    .rdata_o  (km_sram_rdata),
    .rvalid_o (km_sram_mem_rsp_o.rvalid),
    .rerror_o (),
    .alert_o  (),
    .cfg_i    ('0),
    .cfg_rsp_o()
  );

  ////////////////////////////////
  // OTBN IMEM External Module //
  ////////////////////////////////

  logic [sep_crypto_pkg::SEP_CRYPTO_PKA_IMEM_WORD_WIDTH-1:0] otbn_imem_rdata;

  assign sep_crypto_pka_imem_sram_rsp.rdata   = otbn_imem_rdata;
  assign sep_crypto_pka_imem_sram_rsp.q_valid = 1'b0;

  prim_ram_1p #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_PKA_IMEM_WORD_WIDTH),
    .Depth           (2**sep_crypto_pkg::SEP_CRYPTO_PKA_IMEM_ADDR_WIDTH),
    .DataBitsPerMask (1)
  ) u_otbn_imem_sram (
    .clk_i    (sep_crypto_pka_imem_sram_req.clk),
    .rst_ni   (rst_ni),
    .req_i    (sep_crypto_pka_imem_sram_req.enable),
    .write_i  (sep_crypto_pka_imem_sram_req.write),
    .addr_i   (sep_crypto_pka_imem_sram_req.addr),
    .wdata_i  (sep_crypto_pka_imem_sram_req.wdata),
    .wmask_i  (sep_crypto_pka_imem_sram_req.wmask),
    .rdata_o  (otbn_imem_rdata),
    .cfg_i    ('0),
    .cfg_rsp_o()
  );

  ////////////////////////////////
  // OTBN DMEM External Module //
  ////////////////////////////////

  logic [sep_crypto_pkg::SEP_CRYPTO_PKA_DMEM_WORD_WIDTH-1:0] otbn_dmem_rdata;

  assign sep_crypto_pka_dmem_sram_rsp.rdata = otbn_dmem_rdata;

  prim_ram_1p #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_PKA_DMEM_WORD_WIDTH),
    .Depth           (2**sep_crypto_pkg::SEP_CRYPTO_PKA_DMEM_ADDR_WIDTH),
    .DataBitsPerMask (1)
  ) u_otbn_dmem_sram (
    .clk_i    (sep_crypto_pka_dmem_sram_req.clk),
    .rst_ni   (rst_ni),
    .req_i    (sep_crypto_pka_dmem_sram_req.enable),
    .write_i  (sep_crypto_pka_dmem_sram_req.write),
    .addr_i   (sep_crypto_pka_dmem_sram_req.addr),
    .wdata_i  (sep_crypto_pka_dmem_sram_req.wdata),
    .wmask_i  (sep_crypto_pka_dmem_sram_req.wmask),
    .rdata_o  (otbn_dmem_rdata),
    .cfg_i    ('0),
    .cfg_rsp_o()
  );

  /////////////////////////////////
  // Adams Bridge Memory Macros  //
  /////////////////////////////////
  // The ABR crypto engine (abr_top) lives in sep_crypto_abr_wrapper, under
  // sep_crypto. Its SRAM interface is threaded here as packed req/rsp structs
  // (abr_mem_req_i / abr_mem_rsp_o, OTBN convention); this is the home for the
  // technology macros. Every channel instantiates prim_ram_1r1w. Word-write
  // channels tie the write mask all-ones. sig_z and pk expand wstrobe onto
  // that mask (prim_ram_1r1w has no byte-write port). Reset comes from rst_ni.
  //
  // ABR_MASKING_EN must match the value given to sep_crypto_abr_wrapper / abr_top:
  // when set, four extra coefficient banks hold the second DOM share; when
  // clear those arrays are omitted and their rdata reads back 0.
  //
  // The `ifdef SEP_ABR_EN` below is the memory-side counterpart of the guard around
  // u_sep_crypto_abr_wrapper_s3c_scan in sep_crypto.sv: when Adams Bridge is compiled
  // out that file terminates the ABR AXI aperture with DECERR, and this file holds the
  // memory response quiescent so sep.sv's mandatory port stays driven. Keep the two
  // guards symmetric.
  //
  // Note that SEP_ABR_EN is defined for the WHOLE compilation by the `sep` Bender target
  // (alongside the vendor's CALIPTRA) because `bender script flist-plus` hoists every
  // define ahead of the source list, so every flow that pulls in the `sep` target takes
  // this branch and builds the SRAMs.
`ifdef SEP_ABR_EN
  // This file is compiled after the vendor packages, so depths can be taken from
  // them directly; sep_crypto_pkg is compiled ahead of them and has to mirror the
  // widths instead. The checks below pin the two together so a vendor geometry bump
  // fails elaboration instead of silently truncating an address.
  localparam int unsigned AbrW1Depth = abr_params_pkg::ABR_MEM_W1_DEPTH;
  localparam int unsigned AbrInst0Depth = abr_params_pkg::ABR_MEM_INST0_DEPTH;
  localparam int unsigned AbrInst1Depth = abr_params_pkg::ABR_MEM_INST1_DEPTH;
  localparam int unsigned AbrInst2Depth = abr_params_pkg::ABR_MEM_INST2_DEPTH;
  localparam int unsigned AbrSkDepth = abr_ctrl_pkg::SK_MEM_BANK_DEPTH;
  localparam int unsigned AbrSigzDepth = abr_ctrl_pkg::SIG_Z_MEM_DEPTH;
  localparam int unsigned AbrPkDepth = abr_ctrl_pkg::PK_MEM_DEPTH;

  // Address width each memory actually needs. The coefficient channels
  // (INST0/INST1/INST2, plus masked twins) share one struct type sized to the
  // widest of them (INST2), so the narrower ones are sliced down to these widths
  // below; every other channel's struct field is already exact.
  localparam int unsigned AbrW1AddrW = $clog2(AbrW1Depth);
  localparam int unsigned AbrInst0AddrW = $clog2(AbrInst0Depth);
  localparam int unsigned AbrInst1AddrW = $clog2(AbrInst1Depth);
  localparam int unsigned AbrInst2AddrW = $clog2(AbrInst2Depth);
  localparam int unsigned AbrSkAddrW = $clog2(AbrSkDepth);
  localparam int unsigned AbrSigzAddrW = $clog2(AbrSigzDepth);
  localparam int unsigned AbrPkAddrW = $clog2(AbrPkDepth);

  // Memory-side counterpart of the AbrMem*_A checks in sep_crypto_abr_wrapper:
  // those pin the struct against the vendor parameters, this one pins it against the
  // depths the SRAMs are actually built with. Every channel must match exactly --
  // including INST2, which additionally sets the shared coefficient field width,
  // so a mismatch there means the struct can no longer carry the address at all.
  // verilog_format: off
  `OCAH_ASSERT_STATIC(
      AbrMemDepth_A,
      AbrW1AddrW    == sep_crypto_pkg::SEP_CRYPTO_ABR_W1_ADDR_W    &&
      AbrInst0AddrW == sep_crypto_pkg::SEP_CRYPTO_ABR_INST0_ADDR_W &&
      AbrInst1AddrW == sep_crypto_pkg::SEP_CRYPTO_ABR_INST1_ADDR_W &&
      AbrInst2AddrW == sep_crypto_pkg::SEP_CRYPTO_ABR_INST2_ADDR_W &&
      AbrSkAddrW    == sep_crypto_pkg::SEP_CRYPTO_ABR_SK_ADDR_W    &&
      AbrSigzAddrW  == sep_crypto_pkg::SEP_CRYPTO_ABR_SIGZ_ADDR_W  &&
      AbrPkAddrW    == sep_crypto_pkg::SEP_CRYPTO_ABR_PK_ADDR_W,
      {"ABR SRAM depths no longer match the SEP_CRYPTO_ABR_*_ADDR_W mirrors; an ",
       "address bit would be dropped. Re-derive the mirrors in sep_crypto_pkg ",
       "from abr_params_pkg / abr_ctrl_pkg."})
  // verilog_format: on

  // w1_mem: 4-bit decomposed-w1 bits, own narrow addr/data fields.
  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_W1_DATA_W),
    .Depth           (AbrW1Depth),
    .DataBitsPerMask (1)
  ) u_abr_w1_mem (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.w1_we),
    .a_addr_i  (abr_mem_req_i.w1_waddr),
    .a_wdata_i (abr_mem_req_i.w1_wdata),
    .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_W1_DATA_W{1'b1}}),
    .b_req_i   (abr_mem_req_i.w1_re),
    .b_addr_i  (abr_mem_req_i.w1_raddr),
    .b_rdata_o (abr_mem_rsp_o.w1_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  // Unmasked 96-bit coefficient banks. These four ride in the shared
  // abr_mem_ch_req_t, so INST0/INST1 take the low ABR_INST*_ADDR_W address bits
  // (the wrapper zero-extends them into the struct) while INST2, the widest,
  // uses the whole field.
  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W),
    .Depth           (AbrInst0Depth),
    .DataBitsPerMask (1)
  ) u_abr_mem_inst0_bank0 (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.mem_inst0_bank0.we),
    .a_addr_i  (abr_mem_req_i.mem_inst0_bank0.waddr[AbrInst0AddrW-1:0]),
    .a_wdata_i (abr_mem_req_i.mem_inst0_bank0.wdata),
    .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W{1'b1}}),
    .b_req_i   (abr_mem_req_i.mem_inst0_bank0.re),
    .b_addr_i  (abr_mem_req_i.mem_inst0_bank0.raddr[AbrInst0AddrW-1:0]),
    .b_rdata_o (abr_mem_rsp_o.mem_inst0_bank0_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W),
    .Depth           (AbrInst0Depth),
    .DataBitsPerMask (1)
  ) u_abr_mem_inst0_bank1 (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.mem_inst0_bank1.we),
    .a_addr_i  (abr_mem_req_i.mem_inst0_bank1.waddr[AbrInst0AddrW-1:0]),
    .a_wdata_i (abr_mem_req_i.mem_inst0_bank1.wdata),
    .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W{1'b1}}),
    .b_req_i   (abr_mem_req_i.mem_inst0_bank1.re),
    .b_addr_i  (abr_mem_req_i.mem_inst0_bank1.raddr[AbrInst0AddrW-1:0]),
    .b_rdata_o (abr_mem_rsp_o.mem_inst0_bank1_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W),
    .Depth           (AbrInst1Depth),
    .DataBitsPerMask (1)
  ) u_abr_mem_inst1 (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.mem_inst1.we),
    .a_addr_i  (abr_mem_req_i.mem_inst1.waddr[AbrInst1AddrW-1:0]),
    .a_wdata_i (abr_mem_req_i.mem_inst1.wdata),
    .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W{1'b1}}),
    .b_req_i   (abr_mem_req_i.mem_inst1.re),
    .b_addr_i  (abr_mem_req_i.mem_inst1.raddr[AbrInst1AddrW-1:0]),
    .b_rdata_o (abr_mem_rsp_o.mem_inst1_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W),
    .Depth           (AbrInst2Depth),
    .DataBitsPerMask (1)
  ) u_abr_mem_inst2 (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.mem_inst2.we),
    .a_addr_i  (abr_mem_req_i.mem_inst2.waddr[AbrInst2AddrW-1:0]),
    .a_wdata_i (abr_mem_req_i.mem_inst2.wdata),
    .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W{1'b1}}),
    .b_req_i   (abr_mem_req_i.mem_inst2.re),
    .b_addr_i  (abr_mem_req_i.mem_inst2.raddr[AbrInst2AddrW-1:0]),
    .b_rdata_o (abr_mem_rsp_o.mem_inst2_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  // Masked (second DOM share) twins of the four coefficient banks. They only exist
  // when abr_top is built with masking; otherwise their read data reads back zero.
  if (ABR_MASKING_EN) begin : gen_abr_masked_mem
    prim_ram_1r1w #(
      .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W),
      .Depth           (AbrInst0Depth),
      .DataBitsPerMask (1)
    ) u_abr_mem_inst0_bank0_masked (
      .clk_a_i   (abr_mem_req_i.clk),
      .clk_b_i   (abr_mem_req_i.clk),
      .rst_a_ni  (rst_ni),
      .rst_b_ni  (rst_ni),
      .a_req_i   (abr_mem_req_i.mem_inst0_bank0_masked.we),
      .a_addr_i  (abr_mem_req_i.mem_inst0_bank0_masked.waddr[AbrInst0AddrW-1:0]),
      .a_wdata_i (abr_mem_req_i.mem_inst0_bank0_masked.wdata),
      .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W{1'b1}}),
      .b_req_i   (abr_mem_req_i.mem_inst0_bank0_masked.re),
      .b_addr_i  (abr_mem_req_i.mem_inst0_bank0_masked.raddr[AbrInst0AddrW-1:0]),
      .b_rdata_o (abr_mem_rsp_o.mem_inst0_bank0_masked_rdata),
      .cfg_i     ('0),
      .cfg_rsp_o ()
    );

    prim_ram_1r1w #(
      .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W),
      .Depth           (AbrInst0Depth),
      .DataBitsPerMask (1)
    ) u_abr_mem_inst0_bank1_masked (
      .clk_a_i   (abr_mem_req_i.clk),
      .clk_b_i   (abr_mem_req_i.clk),
      .rst_a_ni  (rst_ni),
      .rst_b_ni  (rst_ni),
      .a_req_i   (abr_mem_req_i.mem_inst0_bank1_masked.we),
      .a_addr_i  (abr_mem_req_i.mem_inst0_bank1_masked.waddr[AbrInst0AddrW-1:0]),
      .a_wdata_i (abr_mem_req_i.mem_inst0_bank1_masked.wdata),
      .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W{1'b1}}),
      .b_req_i   (abr_mem_req_i.mem_inst0_bank1_masked.re),
      .b_addr_i  (abr_mem_req_i.mem_inst0_bank1_masked.raddr[AbrInst0AddrW-1:0]),
      .b_rdata_o (abr_mem_rsp_o.mem_inst0_bank1_masked_rdata),
      .cfg_i     ('0),
      .cfg_rsp_o ()
    );

    prim_ram_1r1w #(
      .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W),
      .Depth           (AbrInst1Depth),
      .DataBitsPerMask (1)
    ) u_abr_mem_inst1_masked (
      .clk_a_i   (abr_mem_req_i.clk),
      .clk_b_i   (abr_mem_req_i.clk),
      .rst_a_ni  (rst_ni),
      .rst_b_ni  (rst_ni),
      .a_req_i   (abr_mem_req_i.mem_inst1_masked.we),
      .a_addr_i  (abr_mem_req_i.mem_inst1_masked.waddr[AbrInst1AddrW-1:0]),
      .a_wdata_i (abr_mem_req_i.mem_inst1_masked.wdata),
      .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W{1'b1}}),
      .b_req_i   (abr_mem_req_i.mem_inst1_masked.re),
      .b_addr_i  (abr_mem_req_i.mem_inst1_masked.raddr[AbrInst1AddrW-1:0]),
      .b_rdata_o (abr_mem_rsp_o.mem_inst1_masked_rdata),
      .cfg_i     ('0),
      .cfg_rsp_o ()
    );

    prim_ram_1r1w #(
      .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W),
      .Depth           (AbrInst2Depth),
      .DataBitsPerMask (1)
    ) u_abr_mem_inst2_masked (
      .clk_a_i   (abr_mem_req_i.clk),
      .clk_b_i   (abr_mem_req_i.clk),
      .rst_a_ni  (rst_ni),
      .rst_b_ni  (rst_ni),
      .a_req_i   (abr_mem_req_i.mem_inst2_masked.we),
      .a_addr_i  (abr_mem_req_i.mem_inst2_masked.waddr[AbrInst2AddrW-1:0]),
      .a_wdata_i (abr_mem_req_i.mem_inst2_masked.wdata),
      .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_MEM_DATA_W{1'b1}}),
      .b_req_i   (abr_mem_req_i.mem_inst2_masked.re),
      .b_addr_i  (abr_mem_req_i.mem_inst2_masked.raddr[AbrInst2AddrW-1:0]),
      .b_rdata_o (abr_mem_rsp_o.mem_inst2_masked_rdata),
      .cfg_i     ('0),
      .cfg_rsp_o ()
    );
  end else begin : gen_abr_no_masked_mem
    assign abr_mem_rsp_o.mem_inst0_bank0_masked_rdata = '0;
    assign abr_mem_rsp_o.mem_inst0_bank1_masked_rdata = '0;
    assign abr_mem_rsp_o.mem_inst1_masked_rdata       = '0;
    assign abr_mem_rsp_o.mem_inst2_masked_rdata       = '0;
  end

  // Secret-key memory, split into two 32-bit banks (even dwords in bank0, odd in
  // bank1).
  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_SK_DATA_W),
    .Depth           (AbrSkDepth),
    .DataBitsPerMask (1)
  ) u_abr_sk_mem_bank0 (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.sk_bank0_we),
    .a_addr_i  (abr_mem_req_i.sk_bank0_waddr),
    .a_wdata_i (abr_mem_req_i.sk_bank0_wdata),
    .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_SK_DATA_W{1'b1}}),
    .b_req_i   (abr_mem_req_i.sk_bank0_re),
    .b_addr_i  (abr_mem_req_i.sk_bank0_raddr),
    .b_rdata_o (abr_mem_rsp_o.sk_bank0_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_SK_DATA_W),
    .Depth           (AbrSkDepth),
    .DataBitsPerMask (1)
  ) u_abr_sk_mem_bank1 (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.sk_bank1_we),
    .a_addr_i  (abr_mem_req_i.sk_bank1_waddr),
    .a_wdata_i (abr_mem_req_i.sk_bank1_wdata),
    .a_wmask_i ({sep_crypto_pkg::SEP_CRYPTO_ABR_SK_DATA_W{1'b1}}),
    .b_req_i   (abr_mem_req_i.sk_bank1_re),
    .b_addr_i  (abr_mem_req_i.sk_bank1_raddr),
    .b_rdata_o (abr_mem_rsp_o.sk_bank1_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  // Signature-z and public-key memories: wide rows written a dword at a time.
  // wstrobe is ABR's one-bit-per-byte enable; prim_ram_1r1w has no byte-write
  // port, so each strobe is expanded across its byte. Adopters with byte-write
  // macros connect wstrobe directly.
  // verilog_format: off
  `OCAH_ASSERT_STATIC(
      AbrWstrobeWidth_A,
      SEP_CRYPTO_ABR_SIGZ_DATA_W == 8 * SEP_CRYPTO_ABR_SIGZ_WSTRB_W &&
      SEP_CRYPTO_ABR_PK_DATA_W   == 8 * SEP_CRYPTO_ABR_PK_WSTRB_W,
      "ABR sig_z / pk data widths must be 8 bits per wstrobe bit")
  // verilog_format: on

  logic [sep_crypto_pkg::SEP_CRYPTO_ABR_SIGZ_DATA_W-1:0] abr_sig_z_wmask;
  for (
      genvar b = 0; b < sep_crypto_pkg::SEP_CRYPTO_ABR_SIGZ_WSTRB_W; b++
  ) begin : gen_abr_sig_z_wmask
    assign abr_sig_z_wmask[b*8+:8] = {8{abr_mem_req_i.sig_z_wstrobe[b]}};
  end

  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_SIGZ_DATA_W),
    .Depth           (AbrSigzDepth),
    .DataBitsPerMask (8)
  ) u_abr_sig_z_mem (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.sig_z_we),
    .a_addr_i  (abr_mem_req_i.sig_z_waddr),
    .a_wdata_i (abr_mem_req_i.sig_z_wdata),
    .a_wmask_i (abr_sig_z_wmask),
    .b_req_i   (abr_mem_req_i.sig_z_re),
    .b_addr_i  (abr_mem_req_i.sig_z_raddr),
    .b_rdata_o (abr_mem_rsp_o.sig_z_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );

  logic [sep_crypto_pkg::SEP_CRYPTO_ABR_PK_DATA_W-1:0] abr_pk_wmask;
  for (genvar b = 0; b < sep_crypto_pkg::SEP_CRYPTO_ABR_PK_WSTRB_W; b++) begin : gen_abr_pk_wmask
    assign abr_pk_wmask[b*8+:8] = {8{abr_mem_req_i.pk_mem.wstrobe[b]}};
  end

  prim_ram_1r1w #(
    .Width           (sep_crypto_pkg::SEP_CRYPTO_ABR_PK_DATA_W),
    .Depth           (AbrPkDepth),
    .DataBitsPerMask (8)
  ) u_abr_pk_mem (
    .clk_a_i   (abr_mem_req_i.clk),
    .clk_b_i   (abr_mem_req_i.clk),
    .rst_a_ni  (rst_ni),
    .rst_b_ni  (rst_ni),
    .a_req_i   (abr_mem_req_i.pk_mem.we),
    .a_addr_i  (abr_mem_req_i.pk_mem.waddr),
    .a_wdata_i (abr_mem_req_i.pk_mem.wdata),
    .a_wmask_i (abr_pk_wmask),
    .b_req_i   (abr_mem_req_i.pk_mem.re),
    .b_addr_i  (abr_mem_req_i.pk_mem.raddr),
    .b_rdata_o (abr_mem_rsp_o.pk_rdata),
    .cfg_i     ('0),
    .cfg_rsp_o ()
  );
`else
  // Adams Bridge compiled out (see above: not reached in any flow today). Hold the
  // response quiescent so smu.sv's mandatory port is never left floating.
  assign abr_mem_rsp_o = '0;
`endif  // SEP_ABR_EN


  //=========================================================================
  // External TRNG -- terminated with a DECERR slave; entropy-stream/irq/
  // alarm outputs are idled.
  //=========================================================================

  prim_axi_lite_err_slv #(
    .AXI_DATA_WIDTH (32),
    .AXI_ADDR_WIDTH (32),
    .axil_req_t     (sep_pkg::sep_32_32_axil_req_t),
    .axil_resp_t    (sep_pkg::sep_32_32_axil_resp_t)
  ) u_ext_trng_axil_err_slv (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .axil_req_i  (ext_trng_axil_req_i),
    .axil_resp_o (ext_trng_axil_resp_o)
  );

  assign ext_trng_axis_req_o = '{default: '0};
  assign ext_trng_irq_o      = 1'b0;

  //=========================================================================
  // AXI Extension -- terminated with a DECERR slave, keeping the bus from
  // hanging until an adopter connects a real peripheral here.
  //=========================================================================

  axi_err_slv #(
    .AxiIdWidth (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .axi_req_t  (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_resp_t (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .Resp       (axi_pkg::RESP_DECERR),
    .RespWidth  (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .RespData   (64'hBADCAB1EBADCAB1E),
    .ATOPs      (1'b0),
    .MaxTrans   (2)
  ) u_axi_extension_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (axi_extension_axi_req_i),
    .slv_resp_o (axi_extension_axi_resp_o)
  );

endmodule
