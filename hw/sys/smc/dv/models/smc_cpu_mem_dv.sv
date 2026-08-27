// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC CPU memory DV collateral
//
// Everything simulation-only that used to sit inside smc_cpu_mem_integration:
// observability counters, the firmware mailbox magic detector, bank0 ECC fault
// injection, and the time-zero image backdoors. Keeping it here leaves the
// macro wrapper a pure structural model an adopter can swap out.
//
// Two pieces, because they need different access:
//
//   smc_cpu_mem_dv       - port-based. Taps the request buses for the counters
//                          and the mailbox, and sits in the scratch response
//                          path so bank0 injection can corrupt what the DUT
//                          sees. The testbench instantiates it.
//
//   smc_cpu_mem_backdoor - needs the macro arrays themselves, so it is bound
//                          into smc_cpu_mem_integration and reaches u_mems by
//                          upward name resolution. Only the SMC TB binds it;
//                          the SMU TBs load their SMC ROM through the macro's
//                          own +rom_hex loader in OCAH4CORECluster_rom_ext.
//-----------------------------------------------------------------------------

`timescale 1ps/1fs

module smc_cpu_mem_dv
    import chipyard_4core_mem_pkg::*;
(
    input  logic clk_i,
    input  logic rst_ni,

    // Observed request buses (tapped off the DUT -> macro path).
    input  rom_req_t            rom_req_i,
    input  scratch_ram_req_t    scratch_ram_req_i     [NUM_SRAM_BANKS-1:0],
    input  l1_dcache_data_req_t l1_dcache_data_req_i  [NUM_DCACHE_DATA_BANKS-1:0],

    // Scratch response path: macro -> here -> DUT, so bank0 injection lands
    // on the data the CPU actually consumes.
    input  scratch_ram_rsp_t    scratch_ram_rsp_i     [NUM_SRAM_BANKS-1:0],
    output scratch_ram_rsp_t    scratch_ram_rsp_o     [NUM_SRAM_BANKS-1:0],

    input  logic        ecc_inject_sbe_i,
    input  logic        ecc_inject_dbe_i,
    output logic        scratch0_inject_fire_o,

    output logic [31:0] rom_read_count_o,
    output logic [31:0] scratch_ram_read_count_o,
    output logic [31:0] scratch_ram_write_count_o,
    output logic [31:0] dcache_data_write_count_o,
    output logic [31:0] fw_mailbox_o,
    output logic        fw_mailbox_valid_o
);

    localparam logic [31:0] FW_MAGIC = 32'hACAF_ACA1;

    logic        magic_hit_scratch;
    logic        magic_hit_dcache;
    logic [31:0] fw_mailbox_q;
    logic        fw_mailbox_valid_q;
    logic [31:0] dcache_data_write_count_q;
    logic [31:0] rom_read_count_q;
    logic [31:0] scratch_ram_read_count_q;
    logic [31:0] scratch_ram_write_count_q;
    logic        scratch0_inject_fire_q;
    logic [SMC_4CORE_SCRATCH_RAM_DATA_WIDTH-1:0] scratch0_rdata_mux;

    // ------------------------------------------------------------------
    // Bank0 ECC inject: corrupt returned rdata (SEP DV keeps inject outside
    // the prim macros).
    // ------------------------------------------------------------------
    always_comb begin
        scratch0_rdata_mux = scratch_ram_rsp_i[0].rdata;
        if (ecc_inject_dbe_i) begin
            scratch0_rdata_mux[0] = ~scratch0_rdata_mux[0];
            scratch0_rdata_mux[1] = ~scratch0_rdata_mux[1];
        end else if (ecc_inject_sbe_i) begin
            scratch0_rdata_mux[0] = ~scratch0_rdata_mux[0];
        end
    end

    for (genvar bank = 0; bank < NUM_SRAM_BANKS; bank++) begin : gen_scratch_rsp
        if (bank == 0) begin : gen_bank0
            assign scratch_ram_rsp_o[0].rdata = scratch0_rdata_mux;
        end else begin : gen_bank_n
            assign scratch_ram_rsp_o[bank] = scratch_ram_rsp_i[bank];
        end
    end

    always_ff @(posedge scratch_ram_req_i[0].clk or negedge rst_ni) begin
        if (!rst_ni) begin
            scratch0_inject_fire_q <= 1'b0;
        end else begin
            scratch0_inject_fire_q <= scratch_ram_req_i[0].en &&
                !scratch_ram_req_i[0].wmode &&
                (ecc_inject_sbe_i || ecc_inject_dbe_i);
        end
    end
    assign scratch0_inject_fire_o = scratch0_inject_fire_q;

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
                    if (l1_dcache_data_req_i[bank].wdata[bit_base +: 32] == FW_MAGIC) begin
                        magic_hit_dcache = 1'b1;
                    end
                end
            end
        end
    end

    assign rom_read_count_o          = rom_read_count_q;
    assign scratch_ram_read_count_o  = scratch_ram_read_count_q;
    assign scratch_ram_write_count_o = scratch_ram_write_count_q;
    assign dcache_data_write_count_o = dcache_data_write_count_q;
    assign fw_mailbox_o              = fw_mailbox_q;
    assign fw_mailbox_valid_o        = fw_mailbox_valid_q;

endmodule


//-----------------------------------------------------------------------------
// Time-zero image load into the macro arrays (SEP backdoor posture).
//
// Bound into smc_cpu_mem_integration, so `u_mems` below resolves upward into
// the bound-into instance. MemInitFile is "" on the prim_* macros; images are
// written straight into the public `mem` arrays.
//-----------------------------------------------------------------------------

module smc_cpu_mem_backdoor
    import chipyard_4core_mem_pkg::*;
();

    localparam int unsigned SCRATCH_WORDS = 1 << SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH;
    localparam int unsigned BANK_STRIPE_BYTES = 64;
    localparam int unsigned BYTES_PER_ENTRY = 8;
    localparam int unsigned ENTRIES_PER_STRIPE = BANK_STRIPE_BYTES / BYTES_PER_ENTRY;
    localparam int unsigned MAX_LINEAR_WORDS = 4096;

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
                $display("[smc_cpu_mem_backdoor] backdoor ROM %s", rom_path);
            end else begin
                $display("[smc_cpu_mem_backdoor] WARN: missing ROM %s", rom_path);
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
                            "[smc_cpu_mem_backdoor] stripe-loaded scratch %s (bank0 nonzero=%0d)",
                            scratch_path, loaded_words
                        );
                    end
                end else if (bank == 0) begin
                    $display("[smc_cpu_mem_backdoor] WARN: missing scratch %s",
                             scratch_path);
                end
            end
        end
    end

endmodule
