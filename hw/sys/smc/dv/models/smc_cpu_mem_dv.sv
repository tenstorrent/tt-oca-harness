// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC CPU memory DV collateral
//
// The CPU ROM/scratch/L1$ macros live inside smc_ip_integration.sv, so this is
// bound into that module rather than instantiated in the testbench: it reaches
// the macro interfaces and the macro arrays by upward name resolution, and
// smc_ip_integration itself carries no DV behaviour.
//
// Provides, for the SMC testbench only:
//   * observability counters (ROM / scratch read+write / dcache write)
//   * the firmware mailbox magic detector
//   * bank0 ECC fault-injection HOOK: a counter of scratch bank0 reads taken
//     while ecc_inject_sbe_i / ecc_inject_dbe_i are asserted. It does NOT
//     corrupt the macro response -- there is no force anywhere in this bench --
//     so nothing downstream observes DUT SECDED behaviour. Treat the counter as
//     evidence that the hook is reached and gated, never as ECC coverage.
//   * the +smc_rom_hex / +smc_scratch_ram_hex time-zero image backdoors
//
// The SMU testbenches do not bind it. They load their SMC ROM through
// +rom_hex, which OCAH4CORECluster_rom_ext handles on its own.
//
// The testbench drives ecc_inject_* and reads the counters through the bound
// instance; see hw/sys/smc/dv/tb/tb_top.sv.
//-----------------------------------------------------------------------------

`timescale 1ps / 1fs

module smc_cpu_mem_dv
  import chipyard_4core_mem_pkg::*;
(
  input logic clk_i,
  input logic rst_ni,

  // Bound into smc_ip_integration: these connect to that module's own
  // memory interfaces, which the bind port list resolves in its scope.
  input rom_req_t            rom_req_i,
  input scratch_ram_req_t    scratch_ram_req_i    [NUM_SRAM_BANKS-1:0],
  input l1_dcache_data_req_t l1_dcache_data_req_i [NUM_DCACHE_DATA_BANKS-1:0],

  input logic ecc_inject_sbe_i,
  input logic ecc_inject_dbe_i,

  // Codeword poke. Scratch stores the full 72-bit ECC codeword, so XORing
  // bits into the array is a real corruption the CPU's ECC logic sees on the
  // next read -- one bit is correctable, two are not. Same posture as the
  // SEP testbench, which writes codewords into the macro arrays directly.
  input logic        ecc_poke_en_i,
  input logic [31:0] ecc_poke_entry_i,
  input logic [1:0]  ecc_poke_mask_i
);

  localparam logic [31:0] FW_MAGIC = 32'hACAF_ACA1;

  localparam int unsigned SCRATCH_WORDS = 1 << SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH;
  // Bank/entry decode: smc_scratch_map_pkg, whose header names the RDL and
  // architecture-document sources of the geometry and the DV-owned interleave
  // assumptions. Imported rather than restated so the loader and the tb_top
  // peeks cannot drift apart.
  localparam int unsigned BANK_STRIPE_BYTES = smc_scratch_map_pkg::SCRATCH_BANK_STRIPE_BYTES;
  localparam int unsigned BYTES_PER_ENTRY = smc_scratch_map_pkg::SCRATCH_BYTES_PER_ENTRY;
  localparam int unsigned BANKS_PER_GROUP = smc_scratch_map_pkg::SCRATCH_BANKS_PER_GROUP;
  localparam int unsigned GROUP_BYTES = smc_scratch_map_pkg::SCRATCH_GROUP_BYTES;
  // Staging depth for the +smc_scratch_ram_hex backdoor, in 64-bit words.
  //
  // Anything past the end of this array is dropped by $readmemh, and a
  // truncated image boots into whatever the tail of it happened to be, so the
  // cap has to sit well above the largest firmware image in this tree rather
  // than near it. 32768 words is 256 KB, a quarter of the 1 MB scratch
  // (NUM_SRAM_BANKS * SCRATCH_WORDS * BYTES_PER_ENTRY), and the array is
  // per-bank so raising it further costs NUM_SRAM_BANKS times as much
  // simulator memory. Over-length is reported below rather than left silent.
  localparam int unsigned MAX_LINEAR_WORDS = 32768;

  logic        magic_hit_scratch;
  logic        magic_hit_dcache;
  logic [31:0] fw_mailbox_q;
  logic        fw_mailbox_valid_q;
  logic [31:0] dcache_data_write_count_q;
  logic [31:0] rom_read_count_q;
  logic [31:0] scratch_ram_read_count_q;
  logic [31:0] scratch_ram_write_count_q;
  // Per-bank read counters: which of the 32 scratch banks the CPU actually
  // fetched from, so a caller can check an image's bank residency rather than
  // only that some scratch read happened.
  logic [NUM_SRAM_BANKS-1:0][31:0] scratch_ram_bank_read_count_q;
  logic        scratch0_inject_fire_q;

  // Counts scratch bank0 reads taken while an inject pin is asserted. No data
  // is corrupted: there is no force on smc_ip_integration's response net here
  // or in tb_top. A consumer of this counter is observing the hook's gating,
  // not the CPU's ECC response.
  always_ff @(posedge scratch_ram_req_i[0].clk or negedge rst_ni) begin
    if (!rst_ni) begin
      scratch0_inject_fire_q <= 1'b0;
    end else begin
      scratch0_inject_fire_q <= scratch_ram_req_i[0].en &&
                !scratch_ram_req_i[0].wmode &&
                (ecc_inject_sbe_i || ecc_inject_dbe_i);
    end
  end

  // ------------------------------------------------------------------
  // Codeword poke (rising edge of ecc_poke_en_i)
  // ------------------------------------------------------------------
  logic ecc_poke_en_q;
  always @(posedge clk_i) begin
    ecc_poke_en_q <= ecc_poke_en_i;
    if (ecc_poke_en_i && !ecc_poke_en_q) begin
      u_mems.gen_scratch_rams[0].u_mem.u_mem.mem[ecc_poke_entry_i][1:0] <=
                u_mems.gen_scratch_rams[0].u_mem.u_mem.mem[ecc_poke_entry_i][1:0]
                ^ ecc_poke_mask_i;
      $display("[smc_cpu_mem_dv] ECC poke: bank0 entry %0d ^= 2'b%b", ecc_poke_entry_i,
               ecc_poke_mask_i);
    end
  end

  // ------------------------------------------------------------------
  // Observability counters / FW mailbox
  // ------------------------------------------------------------------
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      rom_read_count_q <= '0;
      scratch_ram_read_count_q <= '0;
      scratch_ram_write_count_q <= '0;
      scratch_ram_bank_read_count_q <= '0;
      dcache_data_write_count_q <= '0;
      fw_mailbox_q <= '0;
      fw_mailbox_valid_q <= 1'b0;
    end else begin
      if (rom_req_i.en && !rom_req_i.wmode) begin
        rom_read_count_q <= rom_read_count_q + 32'd1;
      end
      for (int unsigned bank = 0; bank < NUM_SRAM_BANKS; bank++) begin
        if (scratch_ram_req_i[bank].en && scratch_ram_req_i[bank].wmode) begin
          scratch_ram_write_count_q <= scratch_ram_write_count_q + 32'd1;
        end else if (scratch_ram_req_i[bank].en) begin
          scratch_ram_read_count_q <= scratch_ram_read_count_q + 32'd1;
          scratch_ram_bank_read_count_q[bank] <= scratch_ram_bank_read_count_q[bank] + 32'd1;
        end
      end
      for (int unsigned bank = 0; bank < NUM_DCACHE_DATA_BANKS; bank++) begin
        if (l1_dcache_data_req_i[bank].en && l1_dcache_data_req_i[bank].wmode) begin
          dcache_data_write_count_q <= dcache_data_write_count_q + 32'd1;
        end
      end
      if (magic_hit_scratch || magic_hit_dcache) begin
        fw_mailbox_q <= FW_MAGIC;
        fw_mailbox_valid_q <= 1'b1;
      end
    end
  end

  always_comb begin
    magic_hit_scratch = 1'b0;
    for (int unsigned bank = 0; bank < NUM_SRAM_BANKS; bank++) begin
      if (scratch_ram_req_i[bank].en && scratch_ram_req_i[bank].wmode &&
                    scratch_ram_req_i[bank].wdata[31:0] == FW_MAGIC) begin
        magic_hit_scratch = 1'b1;
      end
    end
  end

  always_comb begin
    magic_hit_dcache = 1'b0;
    for (int unsigned bank = 0; bank < NUM_DCACHE_DATA_BANKS; bank++) begin
      if (l1_dcache_data_req_i[bank].en && l1_dcache_data_req_i[bank].wmode) begin
        for (int unsigned bit_base = 0; bit_base + 32 <= 144; bit_base += 8) begin
          if (l1_dcache_data_req_i[bank].wdata[bit_base+:32] == FW_MAGIC) begin
            magic_hit_dcache = 1'b1;
          end
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // Time-zero image load into the macro arrays (SEP backdoor posture).
  // MemInitFile is "" on the prim_* macros; images are written straight
  // into the public `mem` arrays.
  // ------------------------------------------------------------------
  initial begin : backdoor_rom_load
    string rom_path;
    int    rom_fd;
    // After OCAH4CORECluster_rom_ext's #0.1 plusarg load, so +smc_rom_hex
    // can override the default +rom_hex image.
    #0.2;
    if ($value$plusargs(
            "smc_rom_hex=%s", rom_path
        ) || $value$plusargs(
            "rom_hex=%s", rom_path
        )) begin
      rom_fd = $fopen(rom_path, "r");
      if (rom_fd != 0) begin
        $fclose(rom_fd);
        $readmemh(rom_path, u_mems.u_rom_mem.u_mem.mem);
        $display("[smc_cpu_mem_dv] backdoor ROM %s", rom_path);
      end else begin
        $display("[smc_cpu_mem_dv] WARN: missing ROM %s", rom_path);
      end
    end
  end

  for (genvar bank = 0; bank < NUM_SRAM_BANKS; bank++) begin : gen_scratch_load
    initial begin : backdoor_scratch_load
      string scratch_path;
      int    scratch_fd;
      int    word_i;
      int    offset_i;
      int    bank_i;
      int    entry_i;
      int    loaded_words;
      int    file_words;
      logic [SMC_4CORE_SCRATCH_RAM_DATA_WIDTH-1:0] scan_word;
      logic [SMC_4CORE_SCRATCH_RAM_DATA_WIDTH-1:0] linear_mem [0:MAX_LINEAR_WORDS-1];

      #0.2;
      if ($value$plusargs("smc_scratch_ram_hex=%s", scratch_path)) begin
        scratch_fd = $fopen(scratch_path, "r");
        if (scratch_fd != 0) begin
          $fclose(scratch_fd);
          for (int unsigned i = 0; i < MAX_LINEAR_WORDS; i++) begin
            linear_mem[i] = '0;
          end
          $readmemh(scratch_path, linear_mem);
          loaded_words = 0;
          for (word_i = 0; word_i < int'(MAX_LINEAR_WORDS); word_i++) begin
            offset_i = word_i * int'(BYTES_PER_ENTRY);
            bank_i   = int'(smc_scratch_map_pkg::smc_scratch_bank(unsigned'(offset_i)));
            entry_i  = int'(smc_scratch_map_pkg::smc_scratch_entry(unsigned'(offset_i)));
            if (bank_i == bank && entry_i < int'(SCRATCH_WORDS) && linear_mem[word_i] !== 'x) begin
              u_mems.gen_scratch_rams[bank].u_mem.u_mem.mem[entry_i] = linear_mem[word_i];
              if (linear_mem[word_i] != '0) begin
                loaded_words++;
              end
            end
          end
          // Per-bank count. A bank that loaded nothing while the file holds
          // data for it means the stripe filter above is wrong; every bank
          // loading its share while an AXI read at the matching address
          // returns other data means the DUT decodes the address differently
          // from this model.
          $display("[smc_cpu_mem_dv] scratch bank %0d loaded %0d nonzero words", bank,
                   loaded_words);
          if (bank == 0) begin
            // Count the words the file actually holds, so an image longer than
            // the staging array is reported instead of silently truncated. A
            // truncated image boots into whatever its tail happened to be,
            // which is far harder to diagnose than a loud line here.
            file_words = 0;
            scratch_fd = $fopen(scratch_path, "r");
            while (!$feof(
                scratch_fd
            )) begin
              if ($fscanf(scratch_fd, "%h", scan_word) == 1) begin
                file_words++;
              end else begin
                void'($fgetc(scratch_fd));
              end
            end
            $fclose(scratch_fd);
            if (file_words > int'(MAX_LINEAR_WORDS)) begin
              $error({"[smc_cpu_mem_dv] scratch image %s holds %0d words but the ",
                      "backdoor stages only %0d -- the image is TRUNCATED and the CPU will ",
                      "fetch whatever the cut left behind. Raise MAX_LINEAR_WORDS."}, scratch_path,
                       file_words, MAX_LINEAR_WORDS);
            end
            $display({"[smc_cpu_mem_dv] stripe params BANK_STRIPE_BYTES=%0d ",
                      "BYTES_PER_ENTRY=%0d BANKS_PER_GROUP=%0d GROUP_BYTES=%0d ",
                      "NUM_SRAM_BANKS=%0d SCRATCH_WORDS=%0d"}, BANK_STRIPE_BYTES, BYTES_PER_ENTRY,
                       BANKS_PER_GROUP, GROUP_BYTES, NUM_SRAM_BANKS, SCRATCH_WORDS);
            $display(
                "[smc_cpu_mem_dv] stripe-loaded scratch %s (%0d words in file, bank0 nonzero=%0d)",
                scratch_path, file_words, loaded_words);
          end
        end else if (bank == 0) begin
          $display("[smc_cpu_mem_dv] WARN: missing scratch %s", scratch_path);
        end
      end
    end
  end

endmodule
