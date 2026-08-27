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
//   * bank0 ECC fault injection, forced onto the macro response so the CPU
//     consumes the corrupted data
//   * the +smc_rom_hex / +smc_scratch_ram_hex time-zero image backdoors
//
// The SMU testbenches do not bind it. They load their SMC ROM through
// +rom_hex, which OCAH4CORECluster_rom_ext handles on its own.
//
// The testbench drives ecc_inject_* and reads the counters through the bound
// instance; see hw/sys/smc/dv/tb/tb_top.sv.
//-----------------------------------------------------------------------------

`timescale 1ps/1fs

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
    input logic ecc_inject_dbe_i
);

    localparam logic [31:0] FW_MAGIC = 32'hACAF_ACA1;

    localparam int unsigned SCRATCH_WORDS = 1 << SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH;
    localparam int unsigned BANK_STRIPE_BYTES = 64;
    localparam int unsigned BYTES_PER_ENTRY = 8;
    localparam int unsigned ENTRIES_PER_STRIPE = BANK_STRIPE_BYTES / BYTES_PER_ENTRY;
    localparam int unsigned MAX_LINEAR_WORDS = 4096;

    logic        magic_hit_scratch;
    logic        magic_hit_dcache;
    logic [31:0] fw_mailbox_q;
    logic        fw_mailbox_valid_q;
    logic [31:0] dcache_data_write_count_q;
    logic [31:0] rom_read_count_q;
    logic [31:0] scratch_ram_read_count_q;
    logic [31:0] scratch_ram_write_count_q;
    logic        scratch0_inject_fire_q;

    // Bank0 ECC injection itself is a force on smc_ip_integration's response
    // net and lives in the testbench; this only counts the qualifying reads.
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
    // Observability counters / FW mailbox
    // ------------------------------------------------------------------
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            rom_read_count_q <= '0;
            scratch_ram_read_count_q <= '0;
            scratch_ram_write_count_q <= '0;
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
                end
            end
            for (int unsigned bank = 0; bank < NUM_DCACHE_DATA_BANKS; bank++) begin
                if (l1_dcache_data_req_i[bank].en &&
                        l1_dcache_data_req_i[bank].wmode) begin
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
            if (l1_dcache_data_req_i[bank].en &&
                    l1_dcache_data_req_i[bank].wmode) begin
                for (int unsigned bit_base = 0; bit_base + 32 <= 144; bit_base += 8) begin
                    if (l1_dcache_data_req_i[bank].wdata[bit_base +: 32] == FW_MAGIC) begin
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
        if ($value$plusargs("smc_rom_hex=%s", rom_path) ||
                $value$plusargs("rom_hex=%s", rom_path)) begin
            rom_fd = $fopen(rom_path, "r");
            if (rom_fd != 0) begin
                $fclose(rom_fd);
                $readmemh(rom_path, u_mems.rom_mem.mem.mem);
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
                        bank_i   = (offset_i / int'(BANK_STRIPE_BYTES)) % int'(NUM_SRAM_BANKS);
                        entry_i  = (offset_i /
                                      (int'(BANK_STRIPE_BYTES) * int'(NUM_SRAM_BANKS)))
                                   * int'(ENTRIES_PER_STRIPE)
                                   + (offset_i % int'(BANK_STRIPE_BYTES)) /
                                     int'(BYTES_PER_ENTRY);
                        if (bank_i == bank && entry_i < int'(SCRATCH_WORDS) &&
                                linear_mem[word_i] !== 'x) begin
                            u_mems.gen_scratch_rams[bank].mem.mem.mem[entry_i] =
                                linear_mem[word_i];
                            if (linear_mem[word_i] != '0) begin
                                loaded_words++;
                            end
                        end
                    end
                    if (bank == 0) begin
                        $display(
                            "[smc_cpu_mem_dv] stripe-loaded scratch %s (bank0 nonzero=%0d)",
                            scratch_path, loaded_words
                        );
                    end
                end else if (bank == 0) begin
                    $display("[smc_cpu_mem_dv] WARN: missing scratch %s", scratch_path);
                end
            end
        end
    end

endmodule
