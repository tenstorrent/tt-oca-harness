// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Example Fuse Bank Model
//
//-----------------------------------------------------------------------------

module efuse_bank_model #(
  parameter int unsigned NUM_FUSE_BYTE_WIDTH = 12,
  parameter bit IS_SMC_INSTANCE = 1'b0,
  parameter type efuse_apb_req_t = logic,
  parameter type efuse_apb_resp_t = logic
) (
  // Global Interface
  input logic                   clk_i,
  input logic                   rst_ni,

  // APB Register Interface
  input  efuse_apb_req_t   apb_req_i,
  output efuse_apb_resp_t  apb_resp_o,

  output efuse_bank_reg_pkg::efuse_bank__out_t hwif_out_o
);

  // Sim-only failure injection for efuse program operations. Used to test that
  // firmware handles programming errors correctly.
  //
  // Two injection modes (configured via plusargs):
  //   Count mode   (+{sep,smc}_efuse_prog_fail_count=N)  -- fail the first N
  //                writes after each reset, then stop.
  //   Percent mode (+{sep,smc}_efuse_prog_fail_percent=N) -- fail roughly N%
  //                of writes at random, using a seeded PRNG.
  //                Seed: +{sep,smc}_efuse_prog_fail_seed (default 0x1badf00d).
  //
  // A "failure" zeroes the write data: efuse bits are write-one-to-set, so the
  // program silently does nothing. The bank reports no error -- like real OTP,
  // the failure is only visible via the shim's PROGRAM_READ_BACK compare.
  //
  // Both the count and PRNG state reset to their configured values on every rst_ni.
  logic prog_fail_act;

  // Config, sampled once from plusargs.
  int unsigned prog_fail_count_cfg;
  int unsigned prog_fail_percent;
  int unsigned prog_fail_seed;

  // Working state, re-armed from config on every reset.
  int unsigned prog_fail_count_q;
  logic [31:0] prog_fail_lfsr_q;

  logic        wr_setup;
  logic        prog_fail_now;
  logic [31:0] prog_fail_lfsr_next;

  initial begin
    string pfx;
    logic  seed_given;
    pfx = IS_SMC_INSTANCE ? "smc_" : "sep_";
    prog_fail_count_cfg = 0;
    prog_fail_percent   = 0;
    prog_fail_seed      = 32'h1bad_f00d;
    void'($value$plusargs({pfx, "efuse_prog_fail_count=%d"}, prog_fail_count_cfg));
    void'($value$plusargs({pfx, "efuse_prog_fail_percent=%d"}, prog_fail_percent));
    seed_given = $value$plusargs({pfx, "efuse_prog_fail_seed=%d"}, prog_fail_seed);
    if (prog_fail_percent > 100) prog_fail_percent = 100;
    if ((prog_fail_count_cfg != 0) || (prog_fail_percent != 0)) begin
      $display("[efuse_bank_model:%s] program fail injection count=%0d percent=%0d seed=0x%08x%s",
               IS_SMC_INSTANCE ? "SMC" : "SEP", prog_fail_count_cfg, prog_fail_percent,
               prog_fail_seed, seed_given ? " (plusarg)" : " (default)");
    end
  end

  // The bank macro samples pwdata in the APB setup cycle (penable=0), so the
  // fail/pass decision is made combinationally then and the data zeroed in the
  // same cycle. pwdata is ignored during the access cycle.
  assign wr_setup = apb_req_i.psel & apb_req_i.pwrite & ~apb_req_i.penable;

  always_comb begin
    prog_fail_lfsr_next = (prog_fail_lfsr_q * 32'd1664525) + 32'd1013904223;
    if (prog_fail_count_q != 0) begin
      prog_fail_now = 1'b1;
    end else if (prog_fail_percent != 0) begin
      prog_fail_now = ((prog_fail_lfsr_next % 100) < prog_fail_percent);
    end else begin
      prog_fail_now = 1'b0;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      prog_fail_count_q <= prog_fail_count_cfg;
      prog_fail_lfsr_q  <= prog_fail_seed;
    end else if (wr_setup) begin
      if (prog_fail_count_q != 0) begin
        prog_fail_count_q <= prog_fail_count_q - 1;
      end else if (prog_fail_percent != 0) begin
        prog_fail_lfsr_q <= prog_fail_lfsr_next;
      end
      if (prog_fail_now) begin
        $display("[efuse_bank_model:%s] injected program failure at paddr 0x%0h",
                 IS_SMC_INSTANCE ? "SMC" : "SEP", apb_req_i.paddr);
      end
    end
  end

  assign prog_fail_act = wr_setup & prog_fail_now;

  // Bank Macro
  efuse_bank_reg u_efuse_bank_reg (
    .clk(clk_i),
    .arst_n(rst_ni),

    // This is the interface to the OTP Bank Macro
    .s_apb_psel(apb_req_i.psel),
    .s_apb_penable(apb_req_i.penable),
    .s_apb_pwrite(apb_req_i.pwrite),
    .s_apb_pprot(apb_req_i.pprot),
    .s_apb_paddr(apb_req_i.paddr[NUM_FUSE_BYTE_WIDTH-1:0]),
    .s_apb_pwdata(prog_fail_act ? 32'h0 : apb_req_i.pwdata),
    .s_apb_pstrb(apb_req_i.pstrb),
    .s_apb_pready(apb_resp_o.pready),
    .s_apb_prdata(apb_resp_o.prdata),
    .s_apb_pslverr(apb_resp_o.pslverr),

    .hwif_out(hwif_out_o)
  );

  // Sim-only OTP image preload. The plusarg is a path sampled at time 0;
  // $readmemh waits for rst_ni so the testbench can write that file after the
  // simulator starts (per-run seed). Silicon has fuse contents from power-on;
  // the preload must land before fuse sense, which starts well after reset
  // release. EFUSE_BANK_REG.dout has no reset, so the image and later programs
  // survive every reset. $readmemh cannot target the unpacked struct array,
  // hence the scratch array. Selected by +smc_efuse_hex / +sep_efuse_hex
  // (default out/sep_efuse.hex). A named image that is still missing once
  // reset is released ends the run.
  initial begin
    string img;
    int fd;
    logic [31:0] otp_preload_mem [1024];
    for (int unsigned i = 0; i < 1024; i++) otp_preload_mem[i] = '0;
    if (IS_SMC_INSTANCE) begin
      if ($value$plusargs("smc_efuse_hex=%s", img)) begin
        wait (rst_ni);
        fd = $fopen(img, "r");
        if (fd == 0) begin
          $fatal(1, "[efuse_bank_model:SMC] +smc_efuse_hex=%s is not a readable file", img);
        end
        $fclose(fd);
        $readmemh(img, otp_preload_mem);
        $display("[efuse_bank_model:SMC] loaded %s", img);
      end
    end else begin
      if ($value$plusargs("sep_efuse_hex=%s", img)) begin
        wait (rst_ni);
        fd = $fopen(img, "r");
        if (fd == 0) begin
          $fatal(1, "[efuse_bank_model:SEP] +sep_efuse_hex=%s is not a readable file", img);
        end
        $fclose(fd);
        $readmemh(img, otp_preload_mem);
        $display("[efuse_bank_model:SEP] loaded %s", img);
      end else begin
        wait (rst_ni);
        $readmemh("out/sep_efuse.hex", otp_preload_mem);
        $display("[efuse_bank_model:SEP] loaded out/sep_efuse.hex");
      end
    end
    for (int unsigned i = 0; i < 1024; i++) begin
      u_efuse_bank_reg.field_storage.EFUSE_BANK_REG[i].dout.value = otp_preload_mem[i];
    end
  end

endmodule : efuse_bank_model
