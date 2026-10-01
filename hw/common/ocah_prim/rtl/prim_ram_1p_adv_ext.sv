// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap a single-port SRAM with optional ECC or parity, pipelines, and tiled external RAM ports.
//
// INST_DEPTH smaller than DEPTH tiles into ceil(DEPTH/INST_DEPTH) external RAM instances,
// each INST_DEPTH deep.
//
// ENABLE_ECC and ENABLE_PARITY select per-word ECC or per-byte parity. HAMMING_ECC switches
// from HSIAO to Hamming; HSIAO is more compact and faster. ECC supports WIDTH of 16 or 32
// and whole-word writes only; parity is odd per byte and needs DATA_BITS_PER_MASK of 8.
//
// Read data returns one cycle after the request; ENABLE_INPUT_PIPELINE and
// ENABLE_OUTPUT_PIPELINE each add one cycle of read latency.
//
// alert_o rises on an invalid multi-bit (MuBi4) encoding of the internal request, write or
// read-valid controls. rerror_o bit1 is uncorrectable and bit0 is correctable; parity errors
// set bit1.

module prim_ram_1p_adv_ext
  import prim_ram_1p_pkg::*;

  `include "prim_assert.sv"
  import prim_ram_1p_adv_ext_pkg::*;
#(
  parameter  int DEPTH                  = 512,  // Logical memory depth.
  parameter  int INST_DEPTH             = DEPTH,  // Per-tile depth; smaller than DEPTH tiles into
                                                  // ceil(DEPTH/INST_DEPTH) external RAM ports, each
                                                  // INST_DEPTH deep.
  parameter  int WIDTH                  = 32,  // Data width.
  parameter  int DATA_BITS_PER_MASK     = 1,  // Data bits covered by each write-mask bit; only
                                              // checked to be 8 when ENABLE_PARITY is set.
  parameter      MEM_INIT_FILE          = "",  // Declared but unused; the external RAM owns
                                               // initialization.

  parameter  bit ENABLE_ECC             = 0,  // Enables per-word ECC.
  parameter  bit ENABLE_PARITY          = 0,  // Enables per-byte parity.
  parameter  bit ENABLE_INPUT_PIPELINE  = 0,  // Adds an input register; read latency +1.
  parameter  bit ENABLE_OUTPUT_PIPELINE = 0,  // Adds an output register; read latency +1.

  parameter bit HAMMING_ECC             = 0,  // Selects Hamming ECC instead of HSIAO;
                                              // HSIAO is more compact and faster.

  parameter type ram_req_t              = prim_ram_1p_adv_ext_req_t,  // External RAM request struct; may override the package default.
  parameter type ram_rsp_t              = prim_ram_1p_adv_ext_rsp_t,  // External RAM response struct; may override the package default.

  localparam int Aw                     = prim_util_pkg::vbits(DEPTH),  // Logical address width.
  localparam int NumRamInst             = prim_util_pkg::ceil_div(DEPTH, INST_DEPTH),  // Number of tiled RAM instances.
  localparam int InstAw                 = prim_util_pkg::vbits(INST_DEPTH)  // Per-instance address width.
) (
  input clk_i,  // Memory clock.
  input rst_ni,  // Async reset, active-low.

  input                               req_i,  // Access request.
  input                               write_i,  // Write when high, read when low.
  input        [Aw-1:0]               addr_i,  // Logical word address.
  input        [WIDTH-1:0]            wdata_i,  // Write data.
  input        [WIDTH-1:0]            wmask_i,  // Per-bit write mask; must be all ones with ECC.
  output logic [WIDTH-1:0]            rdata_o,  // Read data.
  output logic                        rvalid_o,  // Read response (rdata_o) is valid.
  output logic [1:0]                  rerror_o,  // Bit1 uncorrectable, bit0 correctable; 0 unless
                                                 // rvalid_o.

  output logic                             alert_o,  // Invalid MuBi4 encoding on an internal
                                                     // control signal.

  output ram_req_t        [NumRamInst-1:0] ram_req_o,  // Per-tile external RAM requests.
  input  ram_rsp_t        [NumRamInst-1:0] ram_rsp_i  // Per-tile external RAM responses.

);

  import prim_mubi_pkg::mubi4_t;
  import prim_mubi_pkg::mubi4_and_hi;
  import prim_mubi_pkg::mubi4_bool_to_mubi;
  import prim_mubi_pkg::mubi4_test_invalid;
  import prim_mubi_pkg::mubi4_test_true_loose;
  import prim_mubi_pkg::mubi4_test_true_strict;
  import prim_mubi_pkg::MuBi4True;
  import prim_mubi_pkg::MuBi4False;
  import prim_mubi_pkg::MuBi4Width;

  `OCAH_OT_ASSERT_INIT(CannotHaveEccAndParity_A, !(ENABLE_PARITY && ENABLE_ECC))

  // Calculate ECC width
  localparam int ParWidth  = (ENABLE_PARITY) ? WIDTH/8 :
                             (!ENABLE_ECC)  ? 0 :
                             (WIDTH <=   4) ? 4 :
                             (WIDTH <=  11) ? 5 :
                             (WIDTH <=  26) ? 6 :
                             (WIDTH <=  57) ? 7 :
                             (WIDTH <= 120) ? 8 : 8 ;
  localparam int TotalWidth = WIDTH + ParWidth;

  // If byte parity is enabled, the write enable bits are used to write memory columns
  // with 8 + 1 = 9 bit width (data plus corresponding parity bit).
  // If ECC is enabled, the DATA_BITS_PER_MASK is ignored.
  localparam int LocalDataBitsPerMask = (ENABLE_PARITY) ? 9         :
                                        (ENABLE_ECC)   ? TotalWidth :
                                                         DATA_BITS_PER_MASK;

  /////////////////////////////
  // RAM Primitive Interface //
  /////////////////////////////

  mubi4_t                  req_q,     req_d,    req_buf_d ;
  logic [MuBi4Width-1:0]   req_buf_b_d;
  logic                    req_q_b ;
  mubi4_t                  write_q,   write_d,  write_buf_d ;
  logic [MuBi4Width-1:0]   write_buf_b_d;
  logic                    write_q_b ;
  logic [Aw-1:0]           addr_q,    addr_d ;
  logic [TotalWidth-1:0]   wdata_q,   wdata_d ;
  logic [TotalWidth-1:0]   wmask_q,   wmask_d ;
  mubi4_t                  rvalid_q,  rvalid_d, rvalid_sram_q, rvalid_sram_d ;
  logic [WIDTH-1:0]        rdata_q,   rdata_d ;
  logic [TotalWidth-1:0]   rdata_sram ;
  logic [1:0]              rerror_q,  rerror_d ;

  assign req_q_b = mubi4_test_true_loose(req_q);
  assign write_q_b = mubi4_test_true_loose(write_q);

  logic [NumRamInst-1:0] inst_req_d, inst_req_q, rvalid_inst;
  logic [InstAw-1:0] inst_addr;
  logic [NumRamInst-1:0] [WIDTH-1:0] inst_rdata;

  // The lower InstAw bits of the address are used to address within one RAM primitive
  assign inst_addr = addr_q[InstAw-1:0];

  // The upper bits Aw-1:InstAw of the address select which RAM instance is selected. A special case
  // is needed when no tiling is performed and only a single RAM macro is instantiated. Here, we
  // can directly use the request signal and no demuxing is needed.
  if (NumRamInst == 1) begin : gen_single_inst_req
    assign inst_req_d[0] = req_q_b;
  end else begin : gen_multi_inst_req
    always_comb begin
      inst_req_d = '0;

      for (int i = 0; i < NumRamInst; i++) begin
        if (req_q_b && (i == addr_q[Aw-1:InstAw])) begin
          inst_req_d[i] = 1'b1;
        end
      end
    end
  end

  // Flop the instance request signal to know to know which
  // tile to select for read data on the next cycle
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      inst_req_q <= '0;
    end else begin
      inst_req_q <= inst_req_d;
    end
  end

  // Ensure that only one RAM instance gets activated
  `OCAH_OT_ASSERT(OneHotInstReq_A, $onehot0(inst_req_d))

  ////////////////////////////////////////
  // External RAM Interface Connections //
  ////////////////////////////////////////

  for (genvar i = 0; i < NumRamInst; i++) begin : gen_ram_interface

    // Connect to external RAM req struct with proper size conversion
    assign ram_req_o[i].clk    = clk_i;
    assign ram_req_o[i].enable = inst_req_d[i];
    assign ram_req_o[i].write  = write_q_b;

    // Connect to external RAM with matching widths
    assign ram_req_o[i].addr  = inst_addr;
    assign ram_req_o[i].wdata = wdata_q;
    assign ram_req_o[i].wmask = wmask_q;

    // Connect from external RAM rsp struct
    assign inst_rdata[i] = ram_rsp_i[i].rdata;

  end

  // Mux output data
  always_comb begin
    rdata_sram = '0;

    for (int i = 0; i < NumRamInst; i++) begin
      // Determine which RAM tile we accessed based on the floped inst_req signal and we really
      // got an rvalid. This determines if we mux the output data of that particular RAM tile.
      rvalid_inst[i] = mubi4_test_true_strict(
        mubi4_and_hi(mubi4_bool_to_mubi(inst_req_q[i]), rvalid_sram_q));

      if(rvalid_inst[i]) begin
        rdata_sram = inst_rdata[i];
      end
    end
  end

  assign rvalid_sram_d = mubi4_and_hi(req_q, mubi4_t'(~write_q));

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      rvalid_sram_q <= MuBi4False;
    end else begin
      rvalid_sram_q <= rvalid_sram_d;
    end
  end

  assign req_d              = mubi4_bool_to_mubi(req_i);
  assign write_d            = mubi4_bool_to_mubi(write_i);
  assign addr_d             = addr_i;
  assign rvalid_o           = mubi4_test_true_loose(rvalid_q);
  assign rdata_o            = rdata_q;
  assign rerror_o           = rerror_q;

  prim_buf #(
    .Width(MuBi4Width)
  ) u_req_d_buf (
    .in_i (req_d),
    .out_o(req_buf_b_d)
  );

  assign req_buf_d = mubi4_t'(req_buf_b_d);

  prim_buf #(
    .Width(MuBi4Width)
  ) u_write_d_buf (
    .in_i (write_d),
    .out_o(write_buf_b_d)
  );

  assign write_buf_d = mubi4_t'(write_buf_b_d);

  /////////////////////////////
  // ECC / Parity Generation //
  /////////////////////////////

  if (ENABLE_PARITY == 0 && ENABLE_ECC) begin : gen_secded
    logic unused_wmask;
    assign unused_wmask = ^wmask_i;

    // check supported widths
    `OCAH_OT_ASSERT_INIT(SecDecWidth_A, WIDTH inside {16, 32})

    // the wmask is constantly set to 1 in this case
    `OCAH_OT_ASSERT(OnlyWordWritePossibleWithEccPortA_A, req_i |->
          wmask_i == {WIDTH{1'b1}})

    assign wmask_d = {TotalWidth{1'b1}};

    if (WIDTH == 16) begin : gen_secded_22_16
      if (HAMMING_ECC) begin : gen_hamming
        prim_secded_inv_hamming_22_16_enc u_enc (
          .data_i(wdata_i),
          .data_o(wdata_d)
        );
        prim_secded_inv_hamming_22_16_dec u_dec (
          .data_i     (rdata_sram),
          .data_o     (rdata_d[0+:WIDTH]),
          .syndrome_o ( ),
          .err_o      (rerror_d)
        );
      end else begin : gen_hsiao
        prim_secded_inv_22_16_enc u_enc (
          .data_i(wdata_i),
          .data_o(wdata_d)
        );
        prim_secded_inv_22_16_dec u_dec (
          .data_i     (rdata_sram),
          .data_o     (rdata_d[0+:WIDTH]),
          .syndrome_o ( ),
          .err_o      (rerror_d)
        );
      end
    end else if (WIDTH == 32) begin : gen_secded_39_32
      if (HAMMING_ECC) begin : gen_hamming
        prim_secded_inv_hamming_39_32_enc u_enc (
          .data_i(wdata_i),
          .data_o(wdata_d)
        );
        prim_secded_inv_hamming_39_32_dec u_dec (
          .data_i     (rdata_sram),
          .data_o     (rdata_d[0+:WIDTH]),
          .syndrome_o ( ),
          .err_o      (rerror_d)
        );
      end else begin : gen_hsiao
        prim_secded_inv_39_32_enc u_enc (
          .data_i(wdata_i),
          .data_o(wdata_d)
        );
        prim_secded_inv_39_32_dec u_dec (
          .data_i     (rdata_sram),
          .data_o     (rdata_d[0+:WIDTH]),
          .syndrome_o ( ),
          .err_o      (rerror_d)
        );
      end
    end

  end else if (ENABLE_PARITY) begin : gen_byte_parity

    `OCAH_OT_ASSERT_INIT(WidthNeedsToBeByteAligned_A, WIDTH % 8 == 0)
    `OCAH_OT_ASSERT_INIT(ParityNeedsByteWriteMask_A, DATA_BITS_PER_MASK == 8)

    always_comb begin : p_parity
      rerror_d = '0;
      for (int i = 0; i < WIDTH/8; i ++) begin
        // Data mapping. We have to make 8+1 = 9 bit groups
        // that have the same write enable such that FPGA tools
        // can map this correctly to BRAM resources.
        wmask_d[i*9 +: 8] = wmask_i[i*8 +: 8];
        wdata_d[i*9 +: 8] = wdata_i[i*8 +: 8];
        rdata_d[i*8 +: 8] = rdata_sram[i*9 +: 8];

        // parity generation (odd parity)
        wdata_d[i*9 + 8] = ~(^wdata_i[i*8 +: 8]);
        wmask_d[i*9 + 8] = &wmask_i[i*8 +: 8];
        // parity decoding (errors are always uncorrectable)
        rerror_d[1] |= ~(^{rdata_sram[i*9 +: 8], rdata_sram[i*9 + 8]});
      end
    end
  end else begin : gen_nosecded_noparity
    assign wmask_d = wmask_i;
    assign wdata_d = wdata_i;

    assign rdata_d  = rdata_sram[0+:WIDTH];
    assign rerror_d = '0;
  end

  assign rvalid_d = rvalid_sram_q;

  /////////////////////////////////////
  // Input/Output Pipeline Registers //
  /////////////////////////////////////

  if (ENABLE_INPUT_PIPELINE) begin : gen_regslice_input
    // Put the register slices between ECC encoding to SRAM port

    // If no ECC or parity is used, do not use prim_flop to allow synthesis
    // tool to optimize the registers.
    if (ENABLE_ECC || ENABLE_PARITY) begin : gen_prim_flop
      prim_flop #(
        .Width(MuBi4Width),
        .ResetValue(MuBi4Width'(MuBi4False))
      ) u_write_flop (
        .clk_i,
        .rst_ni,
        .d_i(MuBi4Width'(write_buf_d)),
        .q_o({write_q})
      );

      prim_flop #(
        .Width(MuBi4Width),
        .ResetValue(MuBi4Width'(MuBi4False))
      ) u_req_flop (
        .clk_i,
        .rst_ni,
        .d_i(MuBi4Width'(req_buf_d)),
        .q_o({req_q})
      );
    end else begin: gen_no_prim_flop
      always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
          write_q <= MuBi4False;
          req_q   <= MuBi4False;
        end else begin
          write_q <= write_buf_d;
          req_q   <= req_buf_d;
        end
      end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        addr_q  <= '0;
        wdata_q <= '0;
        wmask_q <= '0;
      end else begin
        addr_q  <= addr_d;
        wdata_q <= wdata_d;
        wmask_q <= wmask_d;
      end
    end
  end else begin : gen_dirconnect_input
    assign req_q   = req_buf_d;
    assign write_q = write_buf_d;
    assign addr_q  = addr_d;
    assign wdata_q = wdata_d;
    assign wmask_q = wmask_d;
  end

  if (ENABLE_OUTPUT_PIPELINE) begin : gen_regslice_output
    // Put the register slices between ECC decoding to output

    // If no ECC or parity is used, do not use prim_flop to allow synthesis
    // tool to optimize the registers.
    if (ENABLE_ECC || ENABLE_PARITY) begin : gen_prim_rvalid_flop
      prim_flop #(
        .Width(MuBi4Width),
        .ResetValue(MuBi4Width'(MuBi4False))
      ) u_rvalid_flop (
        .clk_i,
        .rst_ni,
        .d_i(MuBi4Width'(rvalid_d)),
        .q_o({rvalid_q})
      );
    end else begin: gen_no_prim_rvalid_flop
      always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
          rvalid_q <= MuBi4False;
        end else begin
          rvalid_q <= rvalid_d;
        end
      end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        rdata_q  <= '0;
        rerror_q <= '0;
      end else begin
        rdata_q  <= rdata_d;
        // tie to zero if the read data is not valid
        rerror_q <= rerror_d & {2{mubi4_test_true_loose(rvalid_d)}};
      end
    end
  end else begin : gen_dirconnect_output
    assign rvalid_q = rvalid_d;
    assign rdata_q  = rdata_d;
    // tie to zero if the read data is not valid
    assign rerror_q = rerror_d & {2{mubi4_test_true_loose(rvalid_d)}};
  end

  assign alert_o = mubi4_test_invalid(req_q) | mubi4_test_invalid(write_q) |
                   mubi4_test_invalid(rvalid_q) | mubi4_test_invalid(rvalid_sram_q);

endmodule : prim_ram_1p_adv_ext
