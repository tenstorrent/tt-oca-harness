// SPDX-License-Identifier: Apache-2.0
//
// SMC eFuse/OTP behavioral responder for the OSS cocotb flow.
//
// Fork of tb_smc_efuse_responder adapted for smc_efuse_pkg (768x32) and
// smc_axil_32_32 bank-control types. Provides READ / PROGRAM /
// PROGRAM_READ_BACK so fuse-sense can complete without +skip_fuse_sense and
// U7-5 burn/shadow tests can exercise sticky-OR programming.

`timescale 1ps/1fs

module tb_smc_efuse_responder
    import smc_pkg::*;
    import smc_efuse_pkg::*;
    import efuse_pkg::*;
(
    input  wire logic clk_i,
    input  wire logic rst_ni,

    input  smc_axil_32_32_req_t  bank_ctrl_req_i,
    output smc_axil_32_32_resp_t bank_ctrl_resp_o,

    input  fuse_command_req_t    fuse_command_req_i,
    output fuse_command_resp_t   fuse_command_resp_o,

    // Program-fail injection LFSR seed from the tb (driven by cocotb from the
    // regression RANDOM_SEED). Used only when no +smc_efuse_prog_fail_seed plusarg
    // is given, so `--regress` sweeps the injection pattern per leaf.
    input  wire logic [31:0]     prog_fail_seed_ext_i,

    // Observability for burn/shadow scoreboards
    output logic [31:0]          otp_word0_o,
    output logic [31:0]          programmed_word0_o
);

    efuse_data_t otp_mem [NumFuseWords];
    efuse_data_t programmed_mem [NumFuseWords];
    fuse_command_resp_t fuse_resp_q;
    logic busy_q;
    logic served_req_q;
    efuse_addr_bit_t addr_q;
    efuse_word_counter_t remaining_q;
    logic [NumFuseBitsWidth-$clog2(NumFuseWordWidth)-1:0] program_word_idx;
    logic [$clog2(NumFuseWordWidth)-1:0] program_bit_idx;
    string image_path;
    int image_fd;

    // Program-failure injection. The *_cfg / config values are sampled once
    // from plusargs in the initial block (single writer); the working count and
    // LFSR state live only in the clocked block (the reset clause re-initializes
    // them from the config) so each reset / resense cycle gets a fresh,
    // repeatable injection budget and there is no multi-procedural driver on the
    // mutable state.
    int unsigned program_fail_count_cfg;
    int unsigned program_fail_percent;
    int unsigned program_fail_seed;
    int unsigned program_fail_count;
    logic [31:0] program_fail_lfsr_q;
    logic        seed_from_plusarg;

    // Latched copy of the currently-served fuse command, used only by the
    // no-backpressure contract check below to flag a dropped command.
    efuse_pkg::fuse_command_e served_cmd_q;
    efuse_addr_bit_t          served_addr_latch_q;
    logic                     served_program_data_latch_q;
    efuse_word_counter_t      served_access_length_latch_q;
    logic                     cmd_drop_reported_q;

    assign program_word_idx =
        fuse_command_req_i.address[NumFuseBitsWidth-1:$clog2(NumFuseWordWidth)];
    assign program_bit_idx =
        fuse_command_req_i.address[$clog2(NumFuseWordWidth)-1:0];

    task automatic load_otp_image();
        for (int unsigned i = 0; i < NumFuseWords; i++) begin
            otp_mem[i] = '0;
        end
        if ($value$plusargs("smc_efuse_hex=%s", image_path)) begin
            image_fd = $fopen(image_path, "r");
            if (image_fd != 0) begin
                $fclose(image_fd);
                $readmemh(image_path, otp_mem);
                $display("[tb_smc_efuse_responder] loaded %s", image_path);
            end
        end else begin
            image_fd = $fopen("out/smc_efuse.hex", "r");
            if (image_fd != 0) begin
                $fclose(image_fd);
                $readmemh("out/smc_efuse.hex", otp_mem);
                $display("[tb_smc_efuse_responder] loaded out/smc_efuse.hex");
            end
        end
        for (int unsigned i = 0; i < NumFuseWords; i++) begin
            otp_mem[i] |= programmed_mem[i];
        end
        // LC_STATE is just word efuse_pkg::SHADOW_IDX_LC_STATE of the loaded
        // image, holding the full differential encoding {~raw, raw}; the sense
        // FSM re-derives the shadow from the low (raw) nibble. There is no
        // separate LC plusarg override -- the image (preload or constrained
        // random) is the single source so it cannot be silently clobbered.
    endtask

    // Load at time 0 and re-load whenever reset asserts. Re-loading on reset
    // lets a test regenerate the hex image and trigger a fresh fuse-sense
    // (resense) that picks up the new contents; frontdoor-programmed bits are
    // overlaid after every reload to model OTP persistence across reset.
    initial begin
        for (int unsigned i = 0; i < NumFuseWords; i++) begin
            programmed_mem[i] = '0;
        end
        // Sample injection config once. The working state (program_fail_count,
        // program_fail_lfsr_q) is initialized from this config in the clocked
        // reset clause so it is re-armed on every reset / resense.
        program_fail_count_cfg = 0;
        program_fail_percent   = 0;
        program_fail_seed      = 32'h1bad_f00d;
        void'($value$plusargs("smc_efuse_prog_fail_count=%d", program_fail_count_cfg));
        void'($value$plusargs("smc_efuse_prog_fail_percent=%d", program_fail_percent));
        // An explicit seed plusarg wins; otherwise the LFSR is seeded at reset from
        // prog_fail_seed_ext_i (the regression RANDOM_SEED) so --regress varies the
        // injection. The port is not stable until cocotb drives it, so the actual
        // seed selection happens in the clocked reset clause, not here.
        seed_from_plusarg = $value$plusargs("smc_efuse_prog_fail_seed=%d", program_fail_seed);
        if (program_fail_percent > 100) begin
            program_fail_percent = 100;
        end
        if ((program_fail_count_cfg != 0) || (program_fail_percent != 0)) begin
            // When no seed plusarg is given, the LFSR is seeded at reset from the
            // tb port (regression RANDOM_SEED), so the effective seed is logged there,
            // not here -- this line only reports an explicit plusarg seed.
            $display(
                "[tb_smc_efuse_responder] program fail injection count=%0d percent=%0d seed=%s",
                program_fail_count_cfg,
                program_fail_percent,
                seed_from_plusarg ? $sformatf("0x%08x (plusarg)", program_fail_seed)
                                  : "<regression RANDOM_SEED via tb port>"
            );
        end
        load_otp_image();
    end
    always @(negedge rst_ni) begin
        load_otp_image();
    end

    // Registered minimal AXI-Lite slave for bank-control traffic. The fuse-sense
    // path uses fuse_command_req/resp and does not touch this; the slave exists
    // so future bank-register accesses do not hang. Unlike the earlier purely
    // combinational stub (b_valid = aw_valid & w_valid, ready ignored), this
    // version latches the AW/W/AR handshakes and holds B/R valid until the master
    // asserts b_ready / r_ready, so it never drops a response or violates
    // AXI-Lite valid-stability. AW and W may arrive on different cycles. Writes
    // ACK OKAY; reads return zero data (no register model yet).
    logic bank_aw_pend_q;  // AW accepted, awaiting W
    logic bank_w_pend_q;   // W accepted, awaiting AW
    logic bank_b_valid_q;  // write response pending (held until b_ready)
    logic bank_r_valid_q;  // read response pending  (held until r_ready)
    logic bank_aw_hs;
    logic bank_w_hs;
    logic bank_ar_hs;

    assign bank_ctrl_resp_o.aw_ready = ~bank_aw_pend_q & ~bank_b_valid_q;
    assign bank_ctrl_resp_o.w_ready  = ~bank_w_pend_q  & ~bank_b_valid_q;
    assign bank_ctrl_resp_o.ar_ready = ~bank_r_valid_q;
    assign bank_ctrl_resp_o.b_valid  = bank_b_valid_q;
    assign bank_ctrl_resp_o.b.resp   = 2'b00;
    assign bank_ctrl_resp_o.r_valid  = bank_r_valid_q;
    assign bank_ctrl_resp_o.r.data   = '0;
    assign bank_ctrl_resp_o.r.resp   = 2'b00;

    assign bank_aw_hs = bank_ctrl_req_i.aw_valid & bank_ctrl_resp_o.aw_ready;
    assign bank_w_hs  = bank_ctrl_req_i.w_valid  & bank_ctrl_resp_o.w_ready;
    assign bank_ar_hs = bank_ctrl_req_i.ar_valid & bank_ctrl_resp_o.ar_ready;

    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            bank_aw_pend_q <= 1'b0;
            bank_w_pend_q  <= 1'b0;
            bank_b_valid_q <= 1'b0;
            bank_r_valid_q <= 1'b0;
        end else begin
            // Write: latch AW and W (either order); raise B once both are in and
            // hold it until b_ready.
            if (bank_b_valid_q) begin
                if (bank_ctrl_req_i.b_ready) begin
                    bank_b_valid_q <= 1'b0;
                end
            end else if ((bank_aw_pend_q | bank_aw_hs) &&
                         (bank_w_pend_q  | bank_w_hs)) begin
                bank_b_valid_q <= 1'b1;
                bank_aw_pend_q <= 1'b0;
                bank_w_pend_q  <= 1'b0;
            end else begin
                if (bank_aw_hs) bank_aw_pend_q <= 1'b1;
                if (bank_w_hs)  bank_w_pend_q  <= 1'b1;
            end

            // Read: single zero-data beat, held until r_ready.
            if (bank_r_valid_q) begin
                if (bank_ctrl_req_i.r_ready) begin
                    bank_r_valid_q <= 1'b0;
                end
            end else if (bank_ar_hs) begin
                bank_r_valid_q <= 1'b1;
            end
        end
    end

    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            fuse_resp_q         <= '0;
            busy_q              <= 1'b0;
            served_req_q        <= 1'b0;
            addr_q              <= '0;
            remaining_q         <= '0;
            // Re-arm the injection budget from config on every reset / resense.
            program_fail_count  <= program_fail_count_cfg;
            // Seed precedence: explicit plusarg > regression seed (tb port) > fixed default.
            program_fail_lfsr_q <= seed_from_plusarg ? program_fail_seed[31:0]
                                   : (prog_fail_seed_ext_i != 32'b0 ? prog_fail_seed_ext_i
                                                                    : 32'h1bad_f00d);
            served_cmd_q                 <= FUSE_COMMAND_READ;
            served_addr_latch_q          <= '0;
            served_program_data_latch_q  <= 1'b0;
            served_access_length_latch_q <= '0;
            cmd_drop_reported_q          <= 1'b0;
        end else begin
            fuse_resp_q <= '0;
            if (!fuse_command_req_i.valid) begin
                served_req_q        <= 1'b0;
                cmd_drop_reported_q <= 1'b0;
            end

            if (!busy_q && fuse_command_req_i.valid && !served_req_q) begin
                automatic logic inject_program_fail = 1'b0;
                automatic logic [31:0] next_fail_lfsr;

                served_req_q                 <= 1'b1;
                served_cmd_q                 <= fuse_command_req_i.command;
                served_addr_latch_q          <= fuse_command_req_i.address;
                served_program_data_latch_q  <= fuse_command_req_i.program_data;
                served_access_length_latch_q <= fuse_command_req_i.access_length_words;
                addr_q                       <= fuse_command_req_i.address;
                remaining_q                  <= fuse_command_req_i.access_length_words;
                if (fuse_command_req_i.command == FUSE_COMMAND_READ) begin
                    // Sweep only when at least one word is requested; a
                    // zero-length read produces zero beats (the previous code
                    // emitted one spurious beat via the remaining_q<=1 terminator).
                    busy_q <= (fuse_command_req_i.access_length_words != '0);
                end else if (fuse_command_req_i.command inside {
                        FUSE_COMMAND_PROGRAM, FUSE_COMMAND_PROGRAM_READ_BACK}) begin
                    if (program_fail_count != 0) begin
                        inject_program_fail = 1'b1;
                        program_fail_count <= program_fail_count - 1;
                    end else if (program_fail_percent != 0) begin
                        next_fail_lfsr = (program_fail_lfsr_q * 32'd1664525) + 32'd1013904223;
                        program_fail_lfsr_q <= next_fail_lfsr;
                        inject_program_fail = ((next_fail_lfsr % 100) < program_fail_percent);
                    end

                    if (inject_program_fail) begin
                        $display(
                            "[tb_smc_efuse_responder] injected program failure at bit %0d",
                            fuse_command_req_i.address
                        );
                        fuse_resp_q.data   <= otp_mem[program_word_idx];
                        fuse_resp_q.status <= 1'b1;
                    end else begin
                        programmed_mem[program_word_idx] <= programmed_mem[program_word_idx] |
                            (efuse_data_t'(fuse_command_req_i.program_data) << program_bit_idx);
                        otp_mem[program_word_idx] <= otp_mem[program_word_idx] |
                            (efuse_data_t'(fuse_command_req_i.program_data) << program_bit_idx);
                        fuse_resp_q.data <= otp_mem[program_word_idx] |
                            (efuse_data_t'(fuse_command_req_i.program_data) << program_bit_idx);
                        fuse_resp_q.status <= 1'b0;
                    end
                    fuse_resp_q.valid  <= 1'b1;
                end else begin
                    // Return an error status (status = pslverr) so the controller
                    // FSM completes instead of hanging on an unsupported command.
                    fuse_resp_q.status <= 1'b1;
                    fuse_resp_q.valid  <= 1'b1;
                end
            end else if (busy_q) begin
                // fuse_command address is a fuse BIT address (efuse_addr_bit_t).
                // The real efuse_interface_shim byte-addresses the bank (addr >> 3)
                // and word-strides by NumFuseWordWidth bits (a +4-byte APB stride),
                // so decode the word index as bit_addr / NumFuseWordWidth and
                // advance one word per beat. (Bit address 0 yields word 0,1,2,...,
                // matching the auto-sense read.)
                fuse_resp_q.data   <= otp_mem[addr_q[NumFuseBitsWidth-1:$clog2(NumFuseWordWidth)]];
                fuse_resp_q.status <= 1'b0;
                fuse_resp_q.valid  <= 1'b1;
                addr_q             <= addr_q + efuse_addr_bit_t'(NumFuseWordWidth);
                if (remaining_q <= efuse_word_counter_t'(1)) begin
                    busy_q      <= 1'b0;
                    remaining_q <= '0;
                end else begin
                    remaining_q <= remaining_q - efuse_word_counter_t'(1);
                end
            end

            // No-backpressure contract: this model serves exactly one command
            // per `valid` assertion (the response interface has no `ready`) and
            // cannot be stalled. The requester MUST deassert `valid` between
            // commands; a different request payload presented while the previous
            // is still served (valid never dropped) is silently ignored. Flag it
            // once so a future controller change fails loudly instead of
            // silently dropping a command. A held READ sweep keeps the same
            // request payload, so this never fires on normal multi-beat reads.
            if (served_req_q && fuse_command_req_i.valid && !cmd_drop_reported_q &&
                    ((fuse_command_req_i.command != served_cmd_q) ||
                     (fuse_command_req_i.address != served_addr_latch_q) ||
                     (fuse_command_req_i.program_data != served_program_data_latch_q) ||
                     (fuse_command_req_i.access_length_words != served_access_length_latch_q))) begin
                cmd_drop_reported_q <= 1'b1;
                $error({"[tb_smc_efuse_responder] new fuse command presented while ",
                        "the previous is still served; deassert valid between ",
                        "commands (this command is being dropped)"});
            end
        end
    end

    assign fuse_command_resp_o = fuse_resp_q;
    assign otp_word0_o = otp_mem[0];
    assign programmed_word0_o = programmed_mem[0];

endmodule : tb_smc_efuse_responder
