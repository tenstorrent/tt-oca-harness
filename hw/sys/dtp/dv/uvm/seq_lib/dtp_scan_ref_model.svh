// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP-local iJTAG and STAP/3DCR reference models — the SV analogue of the
// cocotb dtp_scan_ref_model. The models intentionally describe the public
// OSS DTP testbench shape: the external instrument scan inputs are looped
// back from their scan outputs, so the models check SIB/STAP routing,
// security gating, and observable control signals without pretending there
// is a full downstream instrument behind the loopback.
//
// iJTAG SIB order (TDI to TDO): dft_secure, dft, dfd — all zero-width
// looped instruments, so the observable DR stream is the SIB chain itself.
//
// The TAP_3DCR data register is the 2-bit PTAP 3DCR followed serially by
// the STAP configuration chain (IEEE 1838 Section 5.4): one SIB flop per
// STAP, with the STAP's 3-bit 3DCR spliced TDI-side of its SIB while the
// SIB is open. Scan registers shift MSB-first (scan-in enters the MSB), so
// within each register the MSB field is TDI-nearest. A selected STAP
// splices its downstream loopback into the chain; ports with a TDI lockup
// latch (the I/O STAP) add one full extra flop while selected.

// Index order for the iJTAG SIBs and the STAP ports (TDI to TDO).
typedef enum int unsigned {
    IJ_DFT_SECURE = 0,
    IJ_DFT        = 1,
    IJ_DFD        = 2
} dtp_ijtag_sib_e;

typedef enum int unsigned {
    ST_IO     = 0,
    ST_SMC    = 1,
    ST_SEP    = 2,
    ST_EXTRA0 = 3
} dtp_stap_e;

localparam int unsigned DtpIjtagSibCount = 3;
localparam int unsigned DtpStapCount     = 4;

typedef struct {
    bit config_hold;
    bit stap_sel;
    bit tms_hold;
} dtp_stap_3dcr_state_t;

// Predict iJTAG SIB state for the DTP public loopback environment.
class dtp_ijtag_sib_model;

    // Per-SIB gate state from the direct disables (1 = SIB gated).
    static function void gates(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                               output bit g[DtpIjtagSibCount]);
        g[IJ_DFT_SECURE] = d.dft_secure;
        g[IJ_DFT]        = d.dft_nonsecure;
        g[IJ_DFD]        = d.dfd;
    endfunction

    // Bits shift LSB-first through the serial chain: after a full update
    // the first scanned bit is resident in the final SIB and the last
    // scanned bit in the first SIB.
    static function void pattern_bits(bit [DtpIjtagSibCount-1:0] pattern,
                                      output bit req[DtpIjtagSibCount]);
        for (int unsigned i = 0; i < DtpIjtagSibCount; i++)
            req[i] = pattern[DtpIjtagSibCount - 1 - i];
    endfunction

    // requested/gated/effective per SIB for a pattern under a disable mask.
    static function void state(
        bit [DtpIjtagSibCount-1:0]            pattern,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        output bit requested[DtpIjtagSibCount],
        output bit gated[DtpIjtagSibCount],
        output bit effective[DtpIjtagSibCount],
        output int unsigned chain_len
    );
        pattern_bits(pattern, requested);
        gates(d, gated);
        for (int unsigned i = 0; i < DtpIjtagSibCount; i++)
            effective[i] = requested[i] & ~gated[i];
        // Zero-width looped instruments: the chain is always the SIB flops.
        chain_len = DtpIjtagSibCount;
    endfunction

endclass : dtp_ijtag_sib_model

// Reference state for the PTAP 3DCR and downstream STAP 3DCRs.
class dtp_stap_3dcr_model;

    typedef enum int unsigned {
        FLD_STAP_SEL,
        FLD_CONFIG_HOLD,
        FLD_TMS_HOLD,
        FLD_SIB,
        FLD_SPLICE
    } field_e;

    typedef struct {
        int     owner;  // -1 = PTAP, otherwise dtp_stap_e index
        field_e field;
    } layout_entry_t;

    // Extra full-cycle flops a STAP's selected splice inserts into the chain.
    protected static function int unsigned splice_extra(int unsigned stap);
        return (stap == int'(ST_IO)) ? 1 : 0;
    endfunction

    bit ptap_config_hold;
    bit ptap_select;
    dtp_stap_3dcr_state_t staps[DtpStapCount];
    bit sib_en[DtpStapCount];

    function new();
        trst();
    endfunction

    // Per-STAP gate state from the direct disables (1 = STAP gated).
    static function void gates(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                               output bit g[DtpStapCount]);
        g[ST_IO]     = d.stap_io;
        g[ST_SMC]    = d.stap_smc;
        g[ST_SEP]    = d.stap_sep;
        g[ST_EXTRA0] = d.stap_extra;
    endfunction

    // (owner, field) per chain flop in TDI-to-TDO order, current state.
    function void chain_layout(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                               ref layout_entry_t layout[$]);
        bit g[DtpStapCount];
        gates(d, g);
        layout.delete();
        layout.push_back('{-1, FLD_STAP_SEL});
        layout.push_back('{-1, FLD_CONFIG_HOLD});
        for (int unsigned s = 0; s < DtpStapCount; s++) begin
            if (staps[s].stap_sel && !g[s])
                repeat (splice_extra(s))
                    layout.push_back('{int'(s), FLD_SPLICE});
            if (sib_en[s]) begin
                layout.push_back('{int'(s), FLD_TMS_HOLD});
                layout.push_back('{int'(s), FLD_STAP_SEL});
                layout.push_back('{int'(s), FLD_CONFIG_HOLD});
            end
            layout.push_back('{int'(s), FLD_SIB});
        end
    endfunction

    protected function bit field_value(
        layout_entry_t entry,
        int            new_ptap_select,
        int            new_ptap_config_hold,
        int            new_sib_en[int],
        dtp_stap_3dcr_state_t new_payloads[int]
    );
        bit eff_ptap_sel  = (new_ptap_select < 0) ? ptap_select
                                                  : bit'(new_ptap_select);
        bit eff_ptap_hold = (new_ptap_config_hold < 0) ? ptap_config_hold
                                                       : bit'(new_ptap_config_hold);
        if (entry.owner < 0)
            return (entry.field == FLD_STAP_SEL) ? eff_ptap_sel : eff_ptap_hold;
        case (entry.field)
            FLD_SIB:
                return new_sib_en.exists(entry.owner)
                     ? bit'(new_sib_en[entry.owner]) : sib_en[entry.owner];
            FLD_SPLICE:
                return 1'b0;
            FLD_TMS_HOLD:
                return new_payloads.exists(entry.owner)
                     ? new_payloads[entry.owner].tms_hold
                     : staps[entry.owner].tms_hold;
            FLD_STAP_SEL:
                return new_payloads.exists(entry.owner)
                     ? new_payloads[entry.owner].stap_sel
                     : staps[entry.owner].stap_sel;
            default:
                return new_payloads.exists(entry.owner)
                     ? new_payloads[entry.owner].config_hold
                     : staps[entry.owner].config_hold;
        endcase
    endfunction

    // Scan value that writes the given end-state through the current chain.
    // Negative ptap args and absent associative entries keep stored values.
    // The layout is the chain as it exists during the scan (updates land at
    // Update-DR).
    function bit [63:0] compose_scan(
        int unsigned                          width,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        int                                   new_ptap_select,
        int                                   new_ptap_config_hold,
        int                                   new_sib_en[int],
        dtp_stap_3dcr_state_t                 new_payloads[int]
    );
        layout_entry_t layout[$];
        bit [63:0] value = '0;
        chain_layout(d, layout);
        if (width < layout.size())
            `uvm_fatal("dtp_stap_3dcr_model", $sformatf(
                "scan width %0d < chain length %0d", width, layout.size()))
        foreach (layout[depth])
            if (field_value(layout[depth], new_ptap_select,
                            new_ptap_config_hold, new_sib_en, new_payloads))
                value |= 64'h1 << (width - 1 - depth);
        return value;
    endfunction

    // Commit a composed scan's Update-DR: a gated STAP ignores its 3DCR
    // payload write; SIB bits and the PTAP 3DCR always update. Payload
    // flops are only in the chain if the SIB was open during the scan
    // (per the pre-update state).
    function void apply_scan(
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        int                                   new_ptap_select,
        int                                   new_ptap_config_hold,
        int                                   new_sib_en[int],
        dtp_stap_3dcr_state_t                 new_payloads[int]
    );
        bit g[DtpStapCount];
        bit in_chain[DtpStapCount];
        gates(d, g);
        for (int unsigned s = 0; s < DtpStapCount; s++)
            in_chain[s] = sib_en[s];
        if (new_ptap_select >= 0)
            ptap_select = bit'(new_ptap_select);
        if (new_ptap_config_hold >= 0)
            ptap_config_hold = bit'(new_ptap_config_hold);
        foreach (new_sib_en[s])
            if (s >= 0 && s < int'(DtpStapCount))
                sib_en[s] = bit'(new_sib_en[s]);
        foreach (new_payloads[s])
            if (s >= 0 && s < int'(DtpStapCount) && !g[s] && in_chain[s])
                staps[s] = new_payloads[s];
    endfunction

    // Commit an all-zero over-length scan: every in-chain field cleared.
    function void flush_scan();
        ptap_select      = 1'b0;
        ptap_config_hold = 1'b0;
        for (int unsigned s = 0; s < DtpStapCount; s++) begin
            sib_en[s] = 1'b0;
            staps[s]  = '{1'b0, 1'b0, 1'b0};
        end
    endfunction

    // (expected, care_mask, chain_len) for a readback with PTAP select=1.
    // Captured bit j of the TDO stream is the flop at depth chain_len-1-j;
    // splice flops capture unknown data and are masked out. A STAP captures
    // its masked stap_sel: 0 while its disable is asserted, even though the
    // stored bit survives the gate.
    function void expected_capture(
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        output bit [63:0]   expected,
        output bit [63:0]   care,
        output int unsigned chain_len
    );
        layout_entry_t layout[$];
        int unsigned bit_pos;
        int no_sib[int];
        dtp_stap_3dcr_state_t no_pl[int];
        bit g[DtpStapCount];
        bit value;
        gates(d, g);
        chain_layout(d, layout);
        chain_len = layout.size();
        expected  = '0;
        care      = '0;
        foreach (layout[depth]) begin
            bit_pos = chain_len - 1 - depth;
            if (layout[depth].field == FLD_SPLICE)
                continue;
            care |= 64'h1 << bit_pos;
            value = field_value(layout[depth], -1, -1, no_sib, no_pl);
            if (layout[depth].owner >= 0 &&
                layout[depth].field == FLD_STAP_SEL && g[layout[depth].owner])
                value = 1'b0;
            if (value)
                expected |= 64'h1 << bit_pos;
        end
    endfunction

    // PTAP 3DCR is LSB-first: config_hold then stap_select.
    static function bit [63:0] ptap_3dcr_value(bit config_hold, bit stap_sel);
        return {62'b0, stap_sel, config_hold};
    endfunction

    function void update_ptap(bit [63:0] value);
        ptap_config_hold = value[0];
        ptap_select      = value[1];
    endfunction

    // SIB bits have no config_hold protection and clear in Test-Logic-Reset;
    // a 3DCR survives when its config_hold is set.
    function void tlr();
        if (!ptap_config_hold)
            ptap_select = 1'b0;
        for (int unsigned s = 0; s < DtpStapCount; s++) begin
            sib_en[s] = 1'b0;
            if (!staps[s].config_hold) begin
                staps[s].stap_sel = 1'b0;
                staps[s].tms_hold = 1'b0;
            end
        end
    endfunction

    function void trst();
        ptap_config_hold = 1'b0;
        ptap_select      = 1'b0;
        for (int unsigned s = 0; s < DtpStapCount; s++) begin
            sib_en[s] = 1'b0;
            staps[s]  = '{1'b0, 1'b0, 1'b0};
        end
    endfunction

endclass : dtp_stap_3dcr_model
