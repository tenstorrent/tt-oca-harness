// SPDX-License-Identifier: Apache-2.0
//
// SMC CPU memory behavioral responders for the OSS cocotb flow.
//
// These DV-side memories use the OSS memory-shim pattern, but use the
// Chipyard SRAM-like memory structs exported by bare `smc`.

`timescale 1ps/1fs

module tb_smc_sync_mem_responder #(
    parameter int unsigned ADDR_WIDTH = 1,
    parameter int unsigned DATA_WIDTH = 1,
    parameter int unsigned MASK_WIDTH = 1,
    parameter int unsigned WORDS = 1 << ADDR_WIDTH,
    parameter type mem_req_t = logic,
    parameter type mem_rsp_t = logic,
    parameter string PLUSARG_NAME = "",
    parameter string DEFAULT_IMAGE = "",
    // When STRIPE_LOAD=1, PLUSARG is a linear ecc/image hex that is distributed
    // across banks using the legacy 64B-stripe map (BANK_ID selects this bank).
    parameter bit STRIPE_LOAD = 1'b0,
    parameter int BANK_ID = 0,
    parameter int unsigned BANK_COUNT = 32,
    parameter int unsigned BANK_STRIPE_BYTES = 64,
    parameter int unsigned BYTES_PER_ENTRY = 8,
    parameter int unsigned MAX_LINEAR_WORDS = 4096
) (
    input  wire logic clk_i,
    input  wire logic rst_ni,
    input  mem_req_t  mem_req_i,
    output mem_rsp_t  mem_rsp_o,
    output logic [31:0] read_count_o,
    output logic [31:0] write_count_o,
    // U7-1: optional single/double-bit flip on read data.
    input  wire logic inject_sbe_i,
    input  wire logic inject_dbe_i,
    output logic      inject_fire_o
);

    localparam int unsigned SLICE_WIDTH = DATA_WIDTH / MASK_WIDTH;
    localparam int unsigned ENTRIES_PER_STRIPE = BANK_STRIPE_BYTES / BYTES_PER_ENTRY;

    logic [DATA_WIDTH-1:0] mem [0:WORDS-1];
    logic [DATA_WIDTH-1:0] rdata_q;
    logic [DATA_WIDTH-1:0] linear_mem [0:MAX_LINEAR_WORDS-1];
    string                image_path;
    int                   image_fd;
    int                   word_i;
    int                   offset_i;
    int                   bank_i;
    int                   entry_i;
    int                   loaded_words;

    initial begin
        for (int unsigned i = 0; i < WORDS; i++) begin
            mem[i] = '0;
        end

        if ((PLUSARG_NAME != "") && $value$plusargs(PLUSARG_NAME, image_path)) begin
            if (STRIPE_LOAD) begin
                for (int unsigned i = 0; i < MAX_LINEAR_WORDS; i++) begin
                    linear_mem[i] = '0;
                end
                $readmemh(image_path, linear_mem);
                loaded_words = 0;
                for (word_i = 0; word_i < int'(MAX_LINEAR_WORDS); word_i++) begin
                    offset_i = word_i * int'(BYTES_PER_ENTRY);
                    bank_i   = (offset_i / int'(BANK_STRIPE_BYTES)) % int'(BANK_COUNT);
                    entry_i  = (offset_i / (int'(BANK_STRIPE_BYTES) * int'(BANK_COUNT)))
                               * int'(ENTRIES_PER_STRIPE)
                               + (offset_i % int'(BANK_STRIPE_BYTES)) / int'(BYTES_PER_ENTRY);
                    if (bank_i == BANK_ID && entry_i < int'(WORDS) && linear_mem[word_i] !== 'x) begin
                        mem[entry_i] = linear_mem[word_i];
                        if (linear_mem[word_i] != '0) begin
                            loaded_words++;
                        end
                    end
                end
                $display(
                    "[tb_smc_sync_mem_responder] stripe-loaded %s into bank %0d (%0d nonzero words)",
                    image_path, BANK_ID, loaded_words
                );
            end else begin
                $readmemh(image_path, mem);
                $display("[tb_smc_sync_mem_responder] loaded %s", image_path);
            end
        end else if (DEFAULT_IMAGE != "") begin
            image_fd = $fopen(DEFAULT_IMAGE, "r");
            if (image_fd != 0) begin
                $fclose(image_fd);
                $readmemh(DEFAULT_IMAGE, mem);
                $display("[tb_smc_sync_mem_responder] loaded %s", DEFAULT_IMAGE);
            end
        end
    end

    // Match prim_ram_1p / OCAH*Cluster_mem_*_ext: clock comes from the
    // Chipyard memory port (mem_req_i.clk), not the TB SMC clock.
    wire mem_clk = mem_req_i.clk;
    int unsigned dbg_reads;

    initial begin
        dbg_reads = 0;
        if (STRIPE_LOAD && BANK_ID == 0) begin
            #1;
            $display(
                "[tb_smc_sync_mem_responder] bank0 mem[0]=0x%018x mem[1]=0x%018x",
                mem[0], mem[1]
            );
        end
    end

    logic inject_fire_q;

    always @(posedge mem_clk or negedge rst_ni) begin
        if (!rst_ni) begin
            rdata_q <= '0;
            read_count_o <= '0;
            write_count_o <= '0;
            inject_fire_q <= 1'b0;
        end else if (mem_req_i.en) begin
            automatic logic [DATA_WIDTH-1:0] rd_word = mem[mem_req_i.addr];
            inject_fire_q <= 1'b0;
            if (mem_req_i.wmode) begin
                rdata_q <= rd_word;
                write_count_o <= write_count_o + 32'd1;
                for (int unsigned i = 0; i < MASK_WIDTH; i++) begin
                    if (mem_req_i.wmask[i]) begin
                        mem[mem_req_i.addr][SLICE_WIDTH*i +: SLICE_WIDTH] <=
                            mem_req_i.wdata[SLICE_WIDTH*i +: SLICE_WIDTH];
                    end
                end
            end else begin
                // U7-1: corrupt returning read data (SBE = bit0, DBE = bit0+1).
                if (inject_dbe_i && DATA_WIDTH > 1) begin
                    rd_word[0] = ~rd_word[0];
                    rd_word[1] = ~rd_word[1];
                    inject_fire_q <= 1'b1;
                end else if (inject_sbe_i) begin
                    rd_word[0] = ~rd_word[0];
                    inject_fire_q <= 1'b1;
                end
                rdata_q <= rd_word;
                read_count_o <= read_count_o + 32'd1;
                if (STRIPE_LOAD && BANK_ID == 0 && dbg_reads < 8) begin
                    $display(
                        "[tb_smc_sync_mem_responder] bank0 RD addr=%0d data=0x%018x",
                        mem_req_i.addr, rd_word
                    );
                    dbg_reads++;
                end
            end
        end else begin
            inject_fire_q <= 1'b0;
        end
    end

    assign mem_rsp_o.rdata = rdata_q;
    assign inject_fire_o = inject_fire_q;

endmodule : tb_smc_sync_mem_responder


module tb_smc_cpu_mem_responder
    import chipyard_4core_mem_pkg::*;
(
    input  wire logic clk_i,
    input  wire logic rst_ni,

    input  rom_req_t            rom_req_i,
    output rom_rsp_t            rom_rsp_o,

    input  scratch_ram_req_t    scratch_ram_req_i     [NUM_SRAM_BANKS-1:0],
    output scratch_ram_rsp_t    scratch_ram_rsp_o     [NUM_SRAM_BANKS-1:0],

    input  l1_icache_tag_req_t  l1_icache_tag_req_i   [NUM_ICACHE_TAG_BANKS-1:0],
    output l1_icache_tag_rsp_t  l1_icache_tag_rsp_o   [NUM_ICACHE_TAG_BANKS-1:0],

    input  l1_icache_data_req_t l1_icache_data_req_i  [NUM_ICACHE_DATA_BANKS-1:0],
    output l1_icache_data_rsp_t l1_icache_data_rsp_o  [NUM_ICACHE_DATA_BANKS-1:0],

    input  l1_dcache_tag_req_t  l1_dcache_tag_req_i   [NUM_DCACHE_TAG_BANKS-1:0],
    output l1_dcache_tag_rsp_t  l1_dcache_tag_rsp_o   [NUM_DCACHE_TAG_BANKS-1:0],

    input  l1_dcache_data_req_t l1_dcache_data_req_i  [NUM_DCACHE_DATA_BANKS-1:0],
    output l1_dcache_data_rsp_t l1_dcache_data_rsp_o  [NUM_DCACHE_DATA_BANKS-1:0],

    output logic [31:0] rom_read_count_o,
    output logic [31:0] scratch_ram_read_count_o,
    output logic [31:0] scratch_ram_write_count_o,
    output logic [31:0] dcache_data_write_count_o,
    // Snoop PASS magic on scratch / D$ data writes (CPU MMIO may be isolated).
    output logic [31:0] fw_mailbox_o,
    output logic        fw_mailbox_valid_o,
    // U7-1: ECC inject knobs apply to scratch bank0 reads only.
    input  wire logic   ecc_inject_sbe_i,
    input  wire logic   ecc_inject_dbe_i,
    input  wire logic   ecc_inject_probe_i,
    output logic [31:0] ecc_inject_fire_count_o
);

    localparam logic [31:0] FW_MAGIC = 32'hACAF_ACA1;

    logic [31:0] rom_write_count_unused;
    logic [31:0] scratch_ram_read_count  [NUM_SRAM_BANKS-1:0];
    logic [31:0] scratch_ram_write_count [NUM_SRAM_BANKS-1:0];
    logic        magic_hit_scratch;
    logic        magic_hit_dcache;
    logic [31:0] fw_mailbox_q;
    logic        fw_mailbox_valid_q;
    logic [31:0] dcache_data_write_count_q;
    int unsigned dbg_dc_wr;

    tb_smc_sync_mem_responder #(
        .ADDR_WIDTH    (14),
        .DATA_WIDTH    (64),
        .MASK_WIDTH    (1),
        .mem_req_t     (rom_req_t),
        .mem_rsp_t     (rom_rsp_t),
        .PLUSARG_NAME  ("smc_rom_hex=%s"),
        .DEFAULT_IMAGE ("smc_rom.hex")
    ) u_rom (
        .clk_i,
        .rst_ni,
        .mem_req_i (rom_req_i),
        .mem_rsp_o (rom_rsp_o),
        .read_count_o  (rom_read_count_o),
        .write_count_o (rom_write_count_unused),
        .inject_sbe_i  (1'b0),
        .inject_dbe_i  (1'b0),
        .inject_fire_o ()
    );

    logic        scratch_inject_fire [NUM_SRAM_BANKS-1:0];
    logic [31:0] ecc_inject_fire_count_q;

    // Scratch: 64B stripes across 32 banks (legacy write_sram_direct map).
    for (genvar bank = 0; bank < NUM_SRAM_BANKS; bank++) begin : gen_scratch_ram
        tb_smc_sync_mem_responder #(
            .ADDR_WIDTH    (SMC_4CORE_SCRATCH_RAM_ADDR_WIDTH),
            .DATA_WIDTH    (SMC_4CORE_SCRATCH_RAM_DATA_WIDTH),
            .MASK_WIDTH    (1),
            .mem_req_t     (scratch_ram_req_t),
            .mem_rsp_t     (scratch_ram_rsp_t),
            .PLUSARG_NAME  ("smc_scratch_ram_hex=%s"),
            .DEFAULT_IMAGE (""),
            .STRIPE_LOAD   (1'b1),
            .BANK_ID       (bank),
            .BANK_COUNT    (NUM_SRAM_BANKS)
        ) u_scratch_ram (
            .clk_i,
            .rst_ni,
            .mem_req_i (scratch_ram_req_i[bank]),
            .mem_rsp_o (scratch_ram_rsp_o[bank]),
            .read_count_o  (scratch_ram_read_count[bank]),
            .write_count_o (scratch_ram_write_count[bank]),
            .inject_sbe_i  ((bank == 0) ? ecc_inject_sbe_i : 1'b0),
            .inject_dbe_i  ((bank == 0) ? ecc_inject_dbe_i : 1'b0),
            .inject_fire_o (scratch_inject_fire[bank])
        );
    end

    logic probe_fire;
    assign probe_fire = ecc_inject_probe_i && (ecc_inject_sbe_i || ecc_inject_dbe_i);

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            ecc_inject_fire_count_q <= '0;
        end else if (scratch_inject_fire[0] || probe_fire) begin
            ecc_inject_fire_count_q <= ecc_inject_fire_count_q + 32'd1;
        end
    end
    assign ecc_inject_fire_count_o = ecc_inject_fire_count_q;

    always_comb begin
        scratch_ram_read_count_o = '0;
        scratch_ram_write_count_o = '0;
        magic_hit_scratch = 1'b0;
        for (int unsigned bank = 0; bank < NUM_SRAM_BANKS; bank++) begin
            scratch_ram_read_count_o += scratch_ram_read_count[bank];
            scratch_ram_write_count_o += scratch_ram_write_count[bank];
            if (scratch_ram_req_i[bank].en && scratch_ram_req_i[bank].wmode &&
                    scratch_ram_req_i[bank].wdata[31:0] == FW_MAGIC) begin
                magic_hit_scratch = 1'b1;
            end
        end
    end

    for (genvar bank = 0; bank < NUM_ICACHE_TAG_BANKS; bank++) begin : gen_l1_icache_tag
        tb_smc_sync_mem_responder #(
            .ADDR_WIDTH (5),
            .DATA_WIDTH (94),
            .MASK_WIDTH (2),
            .mem_req_t  (l1_icache_tag_req_t),
            .mem_rsp_t  (l1_icache_tag_rsp_t)
        ) u_l1_icache_tag (
            .clk_i,
            .rst_ni,
            .mem_req_i (l1_icache_tag_req_i[bank]),
            .mem_rsp_o (l1_icache_tag_rsp_o[bank]),
            .read_count_o  (),
            .write_count_o (),
            .inject_sbe_i  (1'b0),
            .inject_dbe_i  (1'b0),
            .inject_fire_o ()
        );
    end

    for (genvar bank = 0; bank < NUM_ICACHE_DATA_BANKS; bank++) begin : gen_l1_icache_data
        tb_smc_sync_mem_responder #(
            .ADDR_WIDTH (8),
            .DATA_WIDTH (66),
            .MASK_WIDTH (2),
            .mem_req_t  (l1_icache_data_req_t),
            .mem_rsp_t  (l1_icache_data_rsp_t)
        ) u_l1_icache_data (
            .clk_i,
            .rst_ni,
            .mem_req_i (l1_icache_data_req_i[bank]),
            .mem_rsp_o (l1_icache_data_rsp_o[bank]),
            .read_count_o  (),
            .write_count_o (),
            .inject_sbe_i  (1'b0),
            .inject_dbe_i  (1'b0),
            .inject_fire_o ()
        );
    end

    for (genvar bank = 0; bank < NUM_DCACHE_TAG_BANKS; bank++) begin : gen_l1_dcache_tag
        tb_smc_sync_mem_responder #(
            .ADDR_WIDTH (5),
            .DATA_WIDTH (108),
            .MASK_WIDTH (2),
            .mem_req_t  (l1_dcache_tag_req_t),
            .mem_rsp_t  (l1_dcache_tag_rsp_t)
        ) u_l1_dcache_tag (
            .clk_i,
            .rst_ni,
            .mem_req_i (l1_dcache_tag_req_i[bank]),
            .mem_rsp_o (l1_dcache_tag_rsp_o[bank]),
            .read_count_o  (),
            .write_count_o (),
            .inject_sbe_i  (1'b0),
            .inject_dbe_i  (1'b0),
            .inject_fire_o ()
        );
    end

    for (genvar bank = 0; bank < NUM_DCACHE_DATA_BANKS; bank++) begin : gen_l1_dcache_data
        tb_smc_sync_mem_responder #(
            .ADDR_WIDTH (8),
            .DATA_WIDTH (144),
            .MASK_WIDTH (2),
            .mem_req_t  (l1_dcache_data_req_t),
            .mem_rsp_t  (l1_dcache_data_rsp_t)
        ) u_l1_dcache_data (
            .clk_i,
            .rst_ni,
            .mem_req_i (l1_dcache_data_req_i[bank]),
            .mem_rsp_o (l1_dcache_data_rsp_o[bank]),
            .read_count_o  (),
            .write_count_o (),
            .inject_sbe_i  (1'b0),
            .inject_dbe_i  (1'b0),
            .inject_fire_o ()
        );
    end

    always_comb begin
        magic_hit_dcache = 1'b0;
        for (int unsigned bank = 0; bank < NUM_DCACHE_DATA_BANKS; bank++) begin
            if (l1_dcache_data_req_i[bank].en && l1_dcache_data_req_i[bank].wmode) begin
                // Scan every aligned 32b window in the 144b ECC data word.
                for (int unsigned bit_base = 0; bit_base + 32 <= 144; bit_base += 8) begin
                    if (l1_dcache_data_req_i[bank].wdata[bit_base +: 32] == FW_MAGIC) begin
                        magic_hit_dcache = 1'b1;
                    end
                end
            end
        end
    end

    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            fw_mailbox_q <= '0;
            fw_mailbox_valid_q <= 1'b0;
            dcache_data_write_count_q <= '0;
            dbg_dc_wr = 0;
        end else begin
            for (int unsigned bank = 0; bank < NUM_DCACHE_DATA_BANKS; bank++) begin
                if (l1_dcache_data_req_i[bank].en && l1_dcache_data_req_i[bank].wmode) begin
                    dcache_data_write_count_q <= dcache_data_write_count_q + 32'd1;
                    if (dbg_dc_wr < 8) begin
                        $display(
                            "[tb_smc_cpu_mem_responder] D$ WR bank=%0d addr=%0d data0=0x%08x",
                            bank,
                            l1_dcache_data_req_i[bank].addr,
                            l1_dcache_data_req_i[bank].wdata[31:0]
                        );
                        dbg_dc_wr++;
                    end
                end
            end
            if (magic_hit_scratch || magic_hit_dcache) begin
                fw_mailbox_q <= FW_MAGIC;
                fw_mailbox_valid_q <= 1'b1;
            end
        end
    end

    assign fw_mailbox_o = fw_mailbox_q;
    assign fw_mailbox_valid_o = fw_mailbox_valid_q;
    assign dcache_data_write_count_o = dcache_data_write_count_q;

endmodule : tb_smc_cpu_mem_responder
