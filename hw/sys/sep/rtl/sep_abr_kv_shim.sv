// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Present Adams Bridge Caliptra Key-Vault ports from the ABR sideload CSR hardware
// interface.
//
// SEP has no Caliptra KV; the Key Manager pushes keys into abr_wrapper_key_reg over a
// private 32-bit AXI4-Lite bus. This shim consumes that decoded hwif and re-presents
// Caliptra kv_read / kv_rd_resp / kv_write / kv_wr_resp.
//
// Seeds are stored as dual XOR shares; plaintext dwords on the KV bus are SHARE0[i] ^
// SHARE1[i], gated by key_valid. The seed is write-only in the CSR and never reconstructed
// outside this shim, so abr_top's mldsa_privkey_lock stays engaged.
//
// kv_read is combinational with respect to read_offset: AB's kv_read_client samples
// kv_rd_resp.read_data in the same cycle. The client ends on (offset == num_dwords-1) or
// kv_rd_resp.last; kv_rd_resp.error latches KV_READ_FAIL. The kv_read ports carry:
//
// - kv_read[0]: the ML-DSA seed (256b / 8 dwords).
// - kv_read[1]: the ML-KEM seed D||Z (512b / 16 dwords: offsets 0..7 stream seed_D,
//   8..15 stream seed_Z); succeeds only when both D and Z are valid.
// - kv_read[2]: the ML-KEM msg (256b / 8 dwords).
//
// kv_write writes ML-KEM shared-key dwords into MLKEM_SHARED_KEY via hwif_o and, on the
// final dword, pulses KEY_CTRL.key_valid.hwset and IRQ_STATUS.key_valid.hwset. kv_wr_resp
// is acknowledged with no error.

module sep_abr_kv_shim
  import kv_defines_pkg::*;
  import abr_wrapper_key_reg_pkg::*;
#(
  parameter int unsigned SEED_DWORDS       = 8,  // ML-DSA-87 / ML-KEM seed block = 256 bits.
  parameter int unsigned MSG_DWORDS        = 8,  // ML-KEM message = 256 bits.
  parameter int unsigned SHARED_KEY_DWORDS = 8  // ML-KEM shared key = 256 bits.
) (
  input       abr_wrapper_key__out_t hwif_i,  // ABR sideload CSR hardware outputs from u_abr_key_csr: KM-written seed shares and shared-key control
                                              // Unpacked PeakRDL struct; declare without wire so it defaults to var for Xcelium SVUPSL.
  output      abr_wrapper_key__in_t  hwif_o,  // ABR sideload CSR hardware inputs to u_abr_key_csr for ML-KEM shared-key writeback.

  input  wire kv_read_t    [2:0] kv_read_i,   // Adams Bridge Caliptra KV read commands; three lanes.
  output      kv_rd_resp_t [2:0] kv_rd_resp_o,  // Adams Bridge Caliptra KV read responses.
  input  wire kv_write_t         kv_write_i,  // Adams Bridge Caliptra KV write command for the ML-KEM shared key.
  output      kv_wr_resp_t       kv_wr_resp_o  // Adams Bridge Caliptra KV write response; acknowledged with no error.
);

  // ML-KEM seed is D||Z: two SEED_DWORDS blocks streamed as one KV entry.
  localparam int unsigned MLKEM_SEED_DWORDS = 2 * SEED_DWORDS;

  localparam int unsigned SEED_IDX_W = (SEED_DWORDS > 1) ? $clog2(SEED_DWORDS) : 1;
  localparam int unsigned MSG_IDX_W = (MSG_DWORDS > 1) ? $clog2(MSG_DWORDS) : 1;
  localparam int unsigned MKSEED_IDX_W = (MLKEM_SEED_DWORDS > 1) ? $clog2(MLKEM_SEED_DWORDS) : 1;

  // kv_read[] lane assignment (abr_ctrl.sv kv_read_client instantiation order).
  localparam int unsigned KV_RD_MLDSA_SEED = 0;
  localparam int unsigned KV_RD_MLKEM_SEED = 1;
  localparam int unsigned KV_RD_MLKEM_MSG = 2;

  // =========================================================================
  // Recover the plaintext dwords from the two XOR shares for each seed block.
  // val[i] = KEY_SHARE0[i] ^ KEY_SHARE1[i]; each block is only valid once the
  // KM firmware sets that block's KEY_CTRL.KEY_VALID.
  // =========================================================================
  logic [31:0] mldsa_seed   [SEED_DWORDS];
  logic [31:0] mlkem_seed_d [SEED_DWORDS];
  logic [31:0] mlkem_seed_z [SEED_DWORDS];
  logic [31:0] mlkem_msg    [MSG_DWORDS];

  for (genvar i = 0; i < SEED_DWORDS; i++) begin : gen_seed_share_xor
    assign mldsa_seed[i]   = hwif_i.MLDSA_SEED.KEY_SHARE0[i].data.value ^
                                 hwif_i.MLDSA_SEED.KEY_SHARE1[i].data.value;
    assign mlkem_seed_d[i] = hwif_i.MLKEM_SEED_D.KEY_SHARE0[i].data.value ^
                                 hwif_i.MLKEM_SEED_D.KEY_SHARE1[i].data.value;
    assign mlkem_seed_z[i] = hwif_i.MLKEM_SEED_Z.KEY_SHARE0[i].data.value ^
                                 hwif_i.MLKEM_SEED_Z.KEY_SHARE1[i].data.value;
  end
  for (genvar i = 0; i < MSG_DWORDS; i++) begin : gen_msg_share_xor
    assign mlkem_msg[i]    = hwif_i.MLKEM_MSG.KEY_SHARE0[i].data.value ^
                                 hwif_i.MLKEM_MSG.KEY_SHARE1[i].data.value;
  end

  logic mldsa_seed_valid, mlkem_seed_d_valid, mlkem_seed_z_valid, mlkem_msg_valid;
  assign mldsa_seed_valid   = hwif_i.MLDSA_SEED.KEY_CTRL.key_valid.value;
  assign mlkem_seed_d_valid = hwif_i.MLKEM_SEED_D.KEY_CTRL.key_valid.value;
  assign mlkem_seed_z_valid = hwif_i.MLKEM_SEED_Z.KEY_CTRL.key_valid.value;
  assign mlkem_msg_valid    = hwif_i.MLKEM_MSG.KEY_CTRL.key_valid.value;

  // =========================================================================
  // KV read responders (combinational, per kv_fsm: data sampled same cycle as
  // read_offset; terminate at num_dwords-1 / assert last on the final dword).
  // =========================================================================

  // kv_read[0] : ML-DSA seed (8 dwords).
  wire [SEED_IDX_W-1:0] mldsa_off = kv_read_i[KV_RD_MLDSA_SEED].read_offset[SEED_IDX_W-1:0];
  assign kv_rd_resp_o[KV_RD_MLDSA_SEED].read_data = mldsa_seed[mldsa_off];
  assign kv_rd_resp_o[KV_RD_MLDSA_SEED].last      =
        (kv_read_i[KV_RD_MLDSA_SEED].read_offset == KV_ENTRY_SIZE_W'(SEED_DWORDS - 1));
  assign kv_rd_resp_o[KV_RD_MLDSA_SEED].error     = ~mldsa_seed_valid;

  // kv_read[1] : ML-KEM seed (16 dwords = D[0..7] then Z[0..7]). offset[3]
  // selects the Z half; the low bits index within the selected 8-dword block.
  wire [MKSEED_IDX_W-1:0] mlkem_seed_off  = kv_read_i[KV_RD_MLKEM_SEED].read_offset[MKSEED_IDX_W-1:0];
  wire                    mlkem_seed_is_z = mlkem_seed_off[SEED_IDX_W];
  wire [SEED_IDX_W-1:0]   mlkem_seed_sub  = mlkem_seed_off[SEED_IDX_W-1:0];
  assign kv_rd_resp_o[KV_RD_MLKEM_SEED].read_data =
        mlkem_seed_is_z ? mlkem_seed_z[mlkem_seed_sub] : mlkem_seed_d[mlkem_seed_sub];
  assign kv_rd_resp_o[KV_RD_MLKEM_SEED].last      =
        (kv_read_i[KV_RD_MLKEM_SEED].read_offset == KV_ENTRY_SIZE_W'(MLKEM_SEED_DWORDS - 1));
  assign kv_rd_resp_o[KV_RD_MLKEM_SEED].error     = ~(mlkem_seed_d_valid & mlkem_seed_z_valid);

  // kv_read[2] : ML-KEM message (8 dwords).
  wire [MSG_IDX_W-1:0] mlkem_msg_off = kv_read_i[KV_RD_MLKEM_MSG].read_offset[MSG_IDX_W-1:0];
  assign kv_rd_resp_o[KV_RD_MLKEM_MSG].read_data = mlkem_msg[mlkem_msg_off];
  assign kv_rd_resp_o[KV_RD_MLKEM_MSG].last      =
        (kv_read_i[KV_RD_MLKEM_MSG].read_offset == KV_ENTRY_SIZE_W'(MSG_DWORDS - 1));
  assign kv_rd_resp_o[KV_RD_MLKEM_MSG].error     = ~mlkem_msg_valid;

  // =========================================================================
  // KV write : ML-KEM shared-key writeback into MLKEM_SHARED_KEY.
  //
  // abr_top's kv_write_client walks write_offset = 0,1,... asserting write_en
  // with write_data each cycle. Each dword is written into the matching KEY[*]
  // sideload register (data.we pulses combinationally with write_en). On the
  // final dword (write_offset == SHARED_KEY_DWORDS-1) we pulse
  // KEY_CTRL.key_valid.hwset (latches the shared-key-valid status) and
  // IRQ_STATUS.key_valid.hwset (raises the interrupt the wrapper gates with
  // IRQ_ENABLE). Signatures are public, so ML-DSA never drives kv_write.
  // =========================================================================
  localparam int unsigned SK_IDX_W = (SHARED_KEY_DWORDS > 1) ? $clog2(SHARED_KEY_DWORDS) : 1;

  wire [SK_IDX_W-1:0] sk_off = kv_write_i.write_offset[SK_IDX_W-1:0];

  always_comb begin
    hwif_o = '{default: '0};
    if (kv_write_i.write_en) begin
      hwif_o.MLKEM_SHARED_KEY.KEY[sk_off].data.next = kv_write_i.write_data;
      hwif_o.MLKEM_SHARED_KEY.KEY[sk_off].data.we   = 1'b1;
      if (kv_write_i.write_offset == KV_ENTRY_SIZE_W'(SHARED_KEY_DWORDS - 1)) begin
        hwif_o.MLKEM_SHARED_KEY.KEY_CTRL.key_valid.hwset   = 1'b1;
        hwif_o.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.hwset = 1'b1;
      end
    end
  end

  // No back-pressure / error path from the sideload CSR writeback.
  assign kv_wr_resp_o = '{error: 1'b0};

endmodule
