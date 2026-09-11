// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hand-maintained register block: regen-regs never touches this file. The EFUSE_BANK_REG storage
// process is a plain `always` so that efuse_bank_model's sim-only preload initial block may also
// write the storage array (a variable assigned in an `always_ff` admits no other writer).
module efuse_bank_reg (
  input wire clk,
  input wire arst_n,

  input wire s_apb_psel,
  input wire s_apb_penable,
  input wire s_apb_pwrite,
  input wire [2:0] s_apb_pprot,
  input wire [11:0] s_apb_paddr,
  input wire [31:0] s_apb_pwdata,
  input wire [3:0] s_apb_pstrb,
  output logic s_apb_pready,
  output logic [31:0] s_apb_prdata,
  output logic s_apb_pslverr,

  output efuse_bank_reg_pkg::efuse_bank__out_t hwif_out
);

  //--------------------------------------------------------------------------
  // CPU Bus interface logic
  //--------------------------------------------------------------------------
  logic cpuif_req;
  logic cpuif_req_is_wr;
  logic [11:0] cpuif_addr;
  logic [31:0] cpuif_wr_data;
  logic [31:0] cpuif_wr_biten;
  logic cpuif_req_stall_wr;
  logic cpuif_req_stall_rd;

  logic cpuif_rd_ack;
  logic cpuif_rd_err;
  logic [31:0] cpuif_rd_data;

  logic cpuif_wr_ack;
  logic cpuif_wr_err;

  // Request
  logic is_active;
  always_ff @(posedge clk or negedge arst_n) begin
    if (~arst_n) begin
      is_active <= '0;
      cpuif_req <= '0;
      cpuif_req_is_wr <= '0;
      cpuif_addr <= '0;
      cpuif_wr_data <= '0;
      cpuif_wr_biten <= '0;
    end else begin
      if (~is_active) begin
        if (s_apb_psel) begin
          is_active <= '1;
          cpuif_req <= '1;
          cpuif_req_is_wr <= s_apb_pwrite;
          cpuif_addr <= {s_apb_paddr[11:2], 2'b0};
          cpuif_wr_data <= s_apb_pwdata;
          for (int i = 0; i < 4; i++) begin
            cpuif_wr_biten[i*8+:8] <= {8{s_apb_pstrb[i]}};
          end
        end
      end else begin
        cpuif_req <= '0;
        if (cpuif_rd_ack || cpuif_wr_ack) begin
          is_active <= '0;
        end
      end
    end
  end

  // Response
  assign s_apb_pready = cpuif_rd_ack | cpuif_wr_ack;
  assign s_apb_prdata = cpuif_rd_data;
  assign s_apb_pslverr = cpuif_rd_err | cpuif_wr_err;

  logic cpuif_req_masked;

  // Read & write latencies are balanced. Stalls not required
  assign cpuif_req_stall_rd = '0;
  assign cpuif_req_stall_wr = '0;
  assign cpuif_req_masked = cpuif_req
                            & !(!cpuif_req_is_wr & cpuif_req_stall_rd)
                            & !(cpuif_req_is_wr & cpuif_req_stall_wr);

  //--------------------------------------------------------------------------
  // Address Decode
  //--------------------------------------------------------------------------
  typedef struct {logic EFUSE_BANK_REG[1024];} decoded_reg_strb_t;
  decoded_reg_strb_t decoded_reg_strb;
  logic decoded_err;
  logic [11:0] decoded_addr;
  logic decoded_req;
  logic decoded_req_is_wr;
  logic [31:0] decoded_wr_data;
  logic [31:0] decoded_wr_biten;

  always_comb begin
    automatic logic is_valid_addr;
    automatic logic is_valid_rw;
    is_valid_addr = '1; // No valid address check
    is_valid_rw = '1; // No valid RW check
    for (int i0 = 0; i0 < 1024; i0++) begin
      decoded_reg_strb.EFUSE_BANK_REG[i0] = cpuif_req_masked & (cpuif_addr == 12'h0 + (12)'(i0) * 12'h4);
    end
    decoded_err = '0;
  end

  // Pass down signals to next stage
  assign decoded_addr = cpuif_addr;
  assign decoded_req = cpuif_req_masked;
  assign decoded_req_is_wr = cpuif_req_is_wr;
  assign decoded_wr_data = cpuif_wr_data;
  assign decoded_wr_biten = cpuif_wr_biten;

  //--------------------------------------------------------------------------
  // Field logic
  //--------------------------------------------------------------------------
  typedef struct {
    struct {
      struct {
        logic [31:0] next;
        logic load_next;
      } dout;
    } EFUSE_BANK_REG[1024];
  } field_combo_t;
  field_combo_t field_combo;

  typedef struct {
    struct {struct {logic [31:0] value;} dout;} EFUSE_BANK_REG[1024];
  } field_storage_t;
  field_storage_t field_storage;

  for (genvar i0 = 0; i0 < 1024; i0++) begin
    // Field: efuse_bank.EFUSE_BANK_REG[].dout
    always_comb begin
      automatic logic [31:0] next_c;
      automatic logic load_next_c;
      next_c = field_storage.EFUSE_BANK_REG[i0].dout.value;
      load_next_c = '0;
      if (decoded_reg_strb.EFUSE_BANK_REG[i0] && decoded_req_is_wr) begin  // SW write 1 set
        next_c = field_storage.EFUSE_BANK_REG[i0].dout.value | (decoded_wr_data[31:0] & decoded_wr_biten[31:0]);
        load_next_c = '1;
      end
      field_combo.EFUSE_BANK_REG[i0].dout.next = next_c;
      field_combo.EFUSE_BANK_REG[i0].dout.load_next = load_next_c;
    end
    // Plain `always`: efuse_bank_model's preload initial block also writes this array (see header).
    always @(posedge clk) begin
      if (field_combo.EFUSE_BANK_REG[i0].dout.load_next) begin
        field_storage.EFUSE_BANK_REG[i0].dout.value <= field_combo.EFUSE_BANK_REG[i0].dout.next;
      end
    end
    assign hwif_out.EFUSE_BANK_REG[i0].dout.value = field_storage.EFUSE_BANK_REG[i0].dout.value;
  end

  //--------------------------------------------------------------------------
  // Write response
  //--------------------------------------------------------------------------
  assign cpuif_wr_ack = decoded_req & decoded_req_is_wr;
  // Writes are always granted with no error response
  assign cpuif_wr_err = '0;

  //--------------------------------------------------------------------------
  // Readback
  //--------------------------------------------------------------------------

  logic [11:0] rd_mux_addr;
  assign rd_mux_addr = decoded_addr;

  logic readback_err;
  logic readback_done;
  logic [31:0] readback_data;
  always_comb begin
    automatic logic [31:0] readback_data_var;
    readback_data_var = '0;
    for (int i0 = 0; i0 < 1024; i0++) begin
      if (rd_mux_addr == 12'h0 + (12)'(i0) * 12'h4) begin
        readback_data_var[31:0] = field_storage.EFUSE_BANK_REG[i0].dout.value;
      end
    end
    readback_data = readback_data_var;
    readback_done = decoded_req & ~decoded_req_is_wr;
    readback_err = '0;
  end

  assign cpuif_rd_ack = readback_done;
  assign cpuif_rd_data = readback_data;
  assign cpuif_rd_err = readback_err;
endmodule
