// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Instantiate ICCM and DCCM RAM macros for the SEP CPU TCM interface.
//
// Uses the sep_cpu_tcm_req_t / sep_cpu_tcm_rsp_t struct interface from sep_cpu.
// Bank geometry comes from el2_param.vh via the EL2 parameter include. Each bank is one
// 39-bit RAM macro (32 data plus 7 ECC bits) chosen by the DCCM bank depth or the ICCM index
// width; an unsupported value is an elaboration error. The macro test and power pins are tied
// off, and a memory is built only when DCCM_ENABLE or ICCM_ENABLE is set.

module sep_tcm_wrapper
    import el2_pkg::*;
    import sep_pkg::*;
#(
`include "el2_param.vh"
)
(
    input  sep_cpu_tcm_req_t tcm_req_i,       // Per-bank ICCM and DCCM enables, addresses and write data plus ECC from sep_cpu,
                                              // with the macro clock.
    output sep_cpu_tcm_rsp_t tcm_rsp_o        // Per-bank ICCM and DCCM read data and ECC to sep_cpu.
);

  //////////
  // DCCM //
  //////////

  if (pt.DCCM_ENABLE == 1) begin : gen_dccm
    logic [pt.DCCM_NUM_BANKS-1:0][pt.DCCM_FDATA_WIDTH-1:0] dccm_wr_fdata_bank;
    logic [pt.DCCM_NUM_BANKS-1:0][pt.DCCM_FDATA_WIDTH-1:0] dccm_bank_fdout;
    localparam int unsigned DccmIndexDepth = pt.DCCM_SIZE * 1024 / (pt.DCCM_BYTE_WIDTH * pt.DCCM_NUM_BANKS); // Depth of memory bank

    for (genvar i = 0; i < pt.DCCM_NUM_BANKS; i++) begin : gen_bank
      assign dccm_wr_fdata_bank[i][pt.DCCM_FDATA_WIDTH-1:0] = {tcm_req_i.dccm_wr_ecc_bank[i], tcm_req_i.dccm_wr_data_bank[i]};
      assign tcm_rsp_o.dccm_bank_dout[i] = dccm_bank_fdout[i][31:0];
      assign tcm_rsp_o.dccm_bank_ecc [i] = dccm_bank_fdout[i][38:32];

      case (DccmIndexDepth)
        32768: begin : gen_dccm_ram
          ram_32768x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        16384: begin : gen_dccm_ram
          ram_16384x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        8192: begin : gen_dccm_ram
          ram_8192x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        4096: begin : gen_dccm_ram
          ram_4096x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        3072: begin : gen_dccm_ram
          ram_3072x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        2048: begin : gen_dccm_ram
          ram_2048x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        1024: begin : gen_dccm_ram
          ram_1024x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        512: begin : gen_dccm_ram
          ram_512x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        256: begin : gen_dccm_ram
          ram_256x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        128: begin : gen_dccm_ram
          ram_128x39 u_ram (
            // Primary ports
            .ME  (tcm_req_i.dccm_clken    [i]),
            .CLK (tcm_req_i.clk),
            .WE  (tcm_req_i.dccm_wren_bank[i]),
            .ADR (tcm_req_i.dccm_addr_bank[i]),
            .D   (dccm_wr_fdata_bank           [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .Q   (dccm_bank_fdout              [i][pt.DCCM_FDATA_WIDTH-1:0]),
            .ROP (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        default: begin : gen_invalid_ram
          $error("Invalid DccmIndexDepth: %d", DccmIndexDepth);
          $fatal;
        end
      endcase
    end : gen_bank
  end : gen_dccm

  //////////
  // ICCM //
  //////////

  if (pt.ICCM_ENABLE != 5'b0) begin : gen_iccm
    logic [pt.ICCM_NUM_BANKS-1:0][38:0] iccm_bank_wr_fdata;
    logic [pt.ICCM_NUM_BANKS-1:0][38:0] iccm_bank_fdout;

    for (genvar i = 0; i < pt.ICCM_NUM_BANKS; i++) begin : gen_bank
      assign iccm_bank_wr_fdata[i][32+pt.ICCM_ECC_WIDTH-1:0] = {tcm_req_i.iccm_bank_wr_ecc[i], tcm_req_i.iccm_bank_wr_data[i]};

      assign tcm_rsp_o.iccm_bank_dout[i] = iccm_bank_fdout[i][31:0];
      assign tcm_rsp_o.iccm_bank_ecc [i] = iccm_bank_fdout[i][(32+pt.ICCM_ECC_WIDTH)-1:32];

      case (pt.ICCM_INDEX_BITS)
        6: begin : gen_iccm_ram
          ram_64x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        7: begin : gen_iccm_ram
          ram_128x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        8: begin : gen_iccm_ram
          ram_256x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        9: begin : gen_iccm_ram
          ram_512x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        10: begin : gen_iccm_ram
          ram_1024x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        11: begin : gen_iccm_ram
          ram_2048x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        12: begin : gen_iccm_ram
          ram_4096x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        13: begin : gen_iccm_ram
          ram_8192x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        14: begin : gen_iccm_ram
          ram_16384x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        15: begin : gen_iccm_ram
          ram_32768x39 u_ram (
            // Primary ports
            .CLK      (tcm_req_i.clk),
            .ME       (tcm_req_i.iccm_clken    [i]),
            .WE       (tcm_req_i.iccm_wren_bank[i]),
            .ADR      (tcm_req_i.iccm_addr_bank[i]),
            .D        (iccm_bank_wr_fdata           [i][38:0]),
            .Q        (iccm_bank_fdout              [i][38:0]),
            .ROP      (),
            // These are used by SoC
            .TEST1    (1'b0),
            .RME      (1'b0),
            .RM       (4'b0),
            .LS       (1'b0),
            .DS       (1'b0),
            .SD       (1'b0),
            .TEST_RNM (1'b0),
            .BC1      (1'b0),
            .BC2      (1'b0)
          );
        end
        default: begin: gen_invalid_ram
          $error("Invalid ICCM_INDEX_BITS: %d", pt.ICCM_INDEX_BITS);
          $fatal;
        end
      endcase
    end : gen_bank
  end : gen_iccm

endmodule
