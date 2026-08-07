// SPDX-License-Identifier: Apache-2.0
//
// abr_wrapper_key_reg -- SEP OSS DV shim for the PeakRDL-generated ABR key CSR block.
//
// FIXME(SEP-DV): RETIRED from the active build. The current sep_crypto.sv no
// longer instantiates abr_wrapper_key_reg, so sep_sim_cfg.toml dropped the
// exclude/sources swap for this shim. Kept as deferred reference only; delete
// it (or re-wire the swap) when the ABR engine integration returns.
//
// WHY THIS EXISTS: main #3417 replaced the ABR DECERR placeholder with the generated
// abr_wrapper_key_reg. That generated block does NOT build under Verilator 5.046:
// sep_crypto.sv ties its hwif_in struct to '0, and Verilator then either (a) const-
// folds the tied-'0 struct and emits invalid C++ for the block's reads of it
// ("0U.__PVT__KEY[5U].__PVT__data..." -> g++ 'operator""U.__PVT__KEY'), or (b) if the
// module is marked public to defeat that fold, emits a mismatched nested-struct
// aggregate init. Neither builds, which breaks the shared OSS Verilator model for every
// crypto test. VCS builds the real block fine; this shim is swapped in for the OSS DV
// build (both tools, for model parity) via sep_sim_cfg.toml exclude_files/sources.
//
// FIDELITY: the real block is an ABR-engine placeholder -- there is no ABR engine
// (hwif_in tied '0), and no OSS test exercises the ABR datapath. sep_crypto only reads
// hwif_out.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid / IRQ_ENABLE.key_valid_en to derive
// the ML-KEM shared-key IRQ, which stays de-asserted with no engine. So this shim only
// needs to (1) service firmware AXI-lite reads/writes without DECERR (KM ROM boot
// touches ABR regs) and (2) drive hwif_out from REAL register state so Verilator cannot
// re-introduce the same const-fold bug in sep_crypto's hwif_out reads. It is a generic
// word-addressed register file; W1C/RO per-field semantics of the real block are NOT
// modelled (unnecessary -- the ABR path is un-exercised; the real block is covered by
// the KM IP / OCAH testbenches). Keep the port list in sync with
// hw/ip/key_manager/regs/gen/sv/abr_wrapper_key_reg.sv.
module abr_wrapper_key_reg (
    input  wire                                           clk,
    input  wire                                           arst_n,

    output logic                                          s_axil_awready,
    input  wire                                           s_axil_awvalid,
    input  wire  [10:0]                                   s_axil_awaddr,
    input  wire  [2:0]                                    s_axil_awprot,
    output logic                                          s_axil_wready,
    input  wire                                           s_axil_wvalid,
    input  wire  [31:0]                                   s_axil_wdata,
    input  wire  [3:0]                                    s_axil_wstrb,
    input  wire                                           s_axil_bready,
    output logic                                          s_axil_bvalid,
    output logic [1:0]                                    s_axil_bresp,
    output logic                                          s_axil_arready,
    input  wire                                           s_axil_arvalid,
    input  wire  [10:0]                                   s_axil_araddr,
    input  wire  [2:0]                                    s_axil_arprot,
    input  wire                                           s_axil_rready,
    output logic                                          s_axil_rvalid,
    output logic [31:0]                                   s_axil_rdata,
    output logic [1:0]                                    s_axil_rresp,

    input  abr_wrapper_key_reg_pkg::abr_wrapper_key__in_t  hwif_in,
    output abr_wrapper_key_reg_pkg::abr_wrapper_key__out_t hwif_out
);

    // hwif_in is intentionally NOT read: no ABR engine exists (sep_crypto ties it to
    // '0), and reading a tied-'0 struct input is exactly what miscompiles the real
    // block under Verilator. -Wno-UNUSEDSIGNAL is set for these DV targets.

    // Cover the full 11-bit decode space (word-addressed) so no in-range firmware
    // access is out of bounds. IRQ register word offsets from the generated block.
    localparam int unsigned NWORDS       = 1 << (11 - 2);   // 512 words
    localparam int unsigned IRQ_STATUS_W = 11'h424 >> 2;    // MLKEM_SHARED_KEY.IRQ_STATUS
    localparam int unsigned IRQ_ENABLE_W = 11'h428 >> 2;    // MLKEM_SHARED_KEY.IRQ_ENABLE

    logic [31:0] regfile [NWORDS];

    // ---------------------------- write channel -----------------------------------
    // AW and W latched independently; single outstanding B (accept next only once the
    // response is drained). Byte-strobed store, always OKAY.
    logic        aw_val_q;
    logic [10:0] aw_addr_q;
    logic        w_val_q;
    logic [31:0] w_data_q;
    logic [3:0]  w_strb_q;
    logic        do_wr;

    assign s_axil_awready = ~aw_val_q & ~s_axil_bvalid;
    assign s_axil_wready  = ~w_val_q  & ~s_axil_bvalid;
    assign do_wr          = aw_val_q & w_val_q & ~s_axil_bvalid;

    always_ff @(posedge clk or negedge arst_n) begin
        if (!arst_n) begin
            aw_val_q      <= 1'b0;
            w_val_q       <= 1'b0;
            aw_addr_q     <= '0;
            w_data_q      <= '0;
            w_strb_q      <= '0;
            s_axil_bvalid <= 1'b0;
            s_axil_bresp  <= 2'b00;
            for (int unsigned i = 0; i < NWORDS; i++) begin
                regfile[i] <= 32'h0;
            end
        end else begin
            if (s_axil_awvalid & s_axil_awready) begin
                aw_val_q  <= 1'b1;
                aw_addr_q <= s_axil_awaddr;
            end
            if (s_axil_wvalid & s_axil_wready) begin
                w_val_q  <= 1'b1;
                w_data_q <= s_axil_wdata;
                w_strb_q <= s_axil_wstrb;
            end
            if (do_wr) begin
                for (int unsigned b = 0; b < 4; b++) begin
                    if (w_strb_q[b]) begin
                        regfile[aw_addr_q[10:2]][8*b +: 8] <= w_data_q[8*b +: 8];
                    end
                end
                aw_val_q      <= 1'b0;
                w_val_q       <= 1'b0;
                s_axil_bvalid <= 1'b1;
                s_axil_bresp  <= 2'b00;   // OKAY -- never DECERR (KM boot depends on it)
            end else if (s_axil_bvalid & s_axil_bready) begin
                s_axil_bvalid <= 1'b0;
            end
        end
    end

    // ---------------------------- read channel ------------------------------------
    logic        ar_val_q;
    logic [10:0] ar_addr_q;

    assign s_axil_arready = ~ar_val_q & ~s_axil_rvalid;

    always_ff @(posedge clk or negedge arst_n) begin
        if (!arst_n) begin
            ar_val_q      <= 1'b0;
            ar_addr_q     <= '0;
            s_axil_rvalid <= 1'b0;
            s_axil_rdata  <= '0;
            s_axil_rresp  <= 2'b00;
        end else begin
            if (s_axil_arvalid & s_axil_arready) begin
                ar_val_q  <= 1'b1;
                ar_addr_q <= s_axil_araddr;
            end
            if (ar_val_q & ~s_axil_rvalid) begin
                s_axil_rdata  <= regfile[ar_addr_q[10:2]];
                s_axil_rvalid <= 1'b1;
                s_axil_rresp  <= 2'b00;    // OKAY
                ar_val_q      <= 1'b0;
            end else if (s_axil_rvalid & s_axil_rready) begin
                s_axil_rvalid <= 1'b0;
            end
        end
    end

    // ---------------------------- hw interface out ---------------------------------
    // Drive ONLY the two leaf fields sep_crypto reads, via continuous assigns, sourced
    // from real (AXI-written) regfile state. Two deliberate reasons:
    //   * regfile is a variable (AXI-written) -> Verilator cannot const-fold hwif_out
    //     into sep_crypto's reads (that would recreate the "0U.__PVT__..." bug).
    //   * NO struct-level aggregate ('{default:'0}) is written -- Verilator 5.046
    //     miscompiles an aggregate-zero of the nested abr_wrapper_key__out_t type
    //     ("abr_seed_rf__out_t has no member __PVT__MLDSA_SEED"). The other struct
    //     fields are left to Verilator's default zero-init (never read by sep_crypto).
    // With no ABR engine the ML-KEM shared-key IRQ stays de-asserted unless firmware
    // writes IRQ_ENABLE (still gated by IRQ_STATUS.key_valid, which no engine sets).
    assign hwif_out.MLKEM_SHARED_KEY.IRQ_STATUS.key_valid.value    = regfile[IRQ_STATUS_W][0];
    assign hwif_out.MLKEM_SHARED_KEY.IRQ_ENABLE.key_valid_en.value = regfile[IRQ_ENABLE_W][0];

endmodule
