// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI helper base sequence for the DTP SV-UVM flow (issue #3295) — the
// SV analogue of the cocotb dtp_jtag2axi_base_test_seq.
//
// Geometry and DR layouts mirror cocotb env/dtp_types.py exactly:
//   SINGLE_OP DR (LSB-first): OP[2] | SIZE | WSTRB | DATA | ADDR
//     smc_otp / sep_otp: 2 + 2 + 4 + 32 + 32 = 72 bits
//     smc_axi:           2 + 2 + 8 + 64 + 56 = 132 bits
//   Capture: status = bits[1:0] (SUCCESS=0/SLVERR=1/DECERR=2/BUSY_OR_FULL=3,
//   NOT the AXI resp encoding), rdata at the DATA offset.
// Wide (>64-bit) TDR scans use the ocah_jtag_item wbits/rbits extension.
//
// Error arming discipline: arm_target_error() programs the responder error
// injection AND cfg.arm_expected_resp() in one place, so the injected
// non-OKAY is EXPECTED for the shared AXI scoreboard; clear_target_error()
// reverses both. The smc_otp responder is the shared ocah_axi_vip UVM slave
// agent (one-shot injection via its ocah_axi_slave_sequence); the smc_axi
// responder remains the plain-SV RAM module driven through tb_if error
// ports. Lifecycle enables must be raised before any JTAG2AXI op (they
// reset to the gated-off tie-off value).

class dtp_jtag2axi_base_seq extends dtp_jtag_base_seq;
    `uvm_object_utils(dtp_jtag2axi_base_seq)

    // JTAG2AXI single-op request/status encodings (dtp_types.py).
    typedef enum int unsigned {
        J2A_OP_NOP   = 0,
        J2A_OP_READ  = 1,
        J2A_OP_WRITE = 2
    } j2a_op_e;

    typedef enum int unsigned {
        J2A_SUCCESS      = 0,
        J2A_SLVERR       = 1,
        J2A_DECERR       = 2,
        J2A_BUSY_OR_FULL = 3
    } j2a_status_e;

    typedef struct {
        string       name;
        jtag_inst_reg_pkg::jtag_instruction_e single_op_instr;
        int unsigned addr_width;
        int unsigned data_width;
        int unsigned size_bits;
        int unsigned wstrb_bits;
        int unsigned default_size;
    } j2a_target_t;

    localparam int unsigned MaxStatusPolls = 16;

    // Plumbed by the test: the shared AXI VIP cfg for the target under test
    // (owns expected-response arming) and its scoreboard evidence recorder.
    ocah_axi_config     axi_cfg;
    ocah_axi_checker axi_evidence;

    // Plumbed by the test for smc_otp targets: the slave agent's test-facing
    // API (error injection / backdoor memory on the responder).
    ocah_axi_slave_sequence otp_slave_seq;

    function new(string name = "dtp_jtag2axi_base_seq");
        super.new(name);
    endfunction

    // --- target geometry (mirrors dtp_types.py JTAG2AXI_TARGETS) ----------
    static function j2a_target_t target_smc_otp();
        j2a_target_t t;
        t.name            = "smc_otp";
        t.single_op_instr = jtag_inst_reg_pkg::SMC_OTP_AXI_SINGLE_OP_INSTR;
        t.addr_width      = 32;
        t.data_width      = 32;
        t.size_bits       = 2;
        t.wstrb_bits      = 4;
        t.default_size    = 2;
        return t;
    endfunction

    static function j2a_target_t target_smc_axi();
        j2a_target_t t;
        t.name            = "smc_axi";
        t.single_op_instr = jtag_inst_reg_pkg::SMC_AXI_SINGLE_OP_INSTR;
        t.addr_width      = 56;
        t.data_width      = 64;
        t.size_bits       = 2;
        t.wstrb_bits      = 8;
        t.default_size    = 3;
        return t;
    endfunction

    static function int unsigned single_op_len(j2a_target_t t);
        return 2 + t.size_bits + t.wstrb_bits + t.data_width + t.addr_width;
    endfunction

    static function j2a_status_e axi_resp_to_status(ocah_axi_resp_e resp);
        case (resp)
            OCAH_AXI_RESP_SLVERR: return J2A_SLVERR;
            OCAH_AXI_RESP_DECERR: return J2A_DECERR;
            default:              return J2A_SUCCESS;
        endcase
    endfunction

    // --- DR packing (LSB-first: OP | SIZE | WSTRB | DATA | ADDR) ----------
    function void pack_single_op(
        j2a_target_t t,
        j2a_op_e     op,
        bit [63:0]   addr,
        bit [63:0]   data,
        bit [7:0]    wstrb,
        int unsigned size,
        ref bit      dr[]
    );
        int unsigned offset = 0;
        dr = new[single_op_len(t)];
        foreach (dr[i]) dr[i] = 1'b0;
        for (int unsigned i = 0; i < 2; i++)            dr[offset++] = (int'(op) >> i) & 1'b1;
        for (int unsigned i = 0; i < t.size_bits; i++)  dr[offset++] = (size >> i) & 1'b1;
        for (int unsigned i = 0; i < t.wstrb_bits; i++) dr[offset++] = (wstrb >> i) & 1'b1;
        for (int unsigned i = 0; i < t.data_width; i++) dr[offset++] = (data >> i) & 1'b1;
        for (int unsigned i = 0; i < t.addr_width; i++) dr[offset++] = (addr >> i) & 1'b1;
    endfunction

    function void unpack_single_op(
        j2a_target_t      t,
        bit               rbits[],
        output j2a_status_e status,
        output bit [63:0] rdata
    );
        int unsigned data_off = 2 + t.size_bits + t.wstrb_bits;
        int unsigned status_raw = 0;
        rdata = '0;
        for (int unsigned i = 0; i < 2 && i < rbits.size(); i++)
            status_raw |= int'(rbits[i]) << i;
        status = j2a_status_e'(status_raw);
        for (int unsigned i = 0; i < t.data_width && (data_off + i) < rbits.size(); i++)
            rdata[i] = rbits[data_off + i];
    endfunction

    // Wide DR scan (>64 bits) through the VIP sequence API's wbits/rbits path.
    task shift_dr_wide(input bit pattern[], output bit observed[]);
        dr_scan_wide(pattern, observed);
        check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after wide DR scan");
    endtask

    // --- single-op TDR flow ------------------------------------------------
    task issue_single(
        j2a_target_t t,
        j2a_op_e     op,
        bit [63:0]   addr,
        bit [63:0]   data  = '0,
        bit [7:0]    wstrb = '0,
        int unsigned size  = 0,
        bit          use_default_size = 1'b1
    );
        bit dr[];
        bit unused[];
        int unsigned eff_size = use_default_size ? t.default_size : size;
        `uvm_info(get_type_name(), $sformatf(
            "%s SINGLE_OP %s addr=0x%0h data=0x%0h wstrb=0x%0h size=%0d",
            t.name, op.name(), addr, data, wstrb, eff_size), UVM_MEDIUM)
        // Stimulus-intent write record: the address/data/wstrb programmed
        // into the TDR is the truth the observed bus transaction must match
        // (CHK-AXI-WADDR / CHK-AXI-WDATA / CHK-AXI-STRB).
        if (op == J2A_OP_WRITE && axi_cfg != null)
            axi_cfg.arm_expected_write(
                addr & ((t.addr_width >= 64) ? '1 : ((64'd1 << t.addr_width) - 1)),
                data & ((t.data_width >= 64) ? '1 : ((64'd1 << t.data_width) - 1)),
                wstrb);
        // Gated ops never reach the bus: do not arm read intents while a
        // required lifecycle enable is low (the no-activity evidence owns
        // that case; a dangling intent would false-fail at check_phase).
        if (op == J2A_OP_READ && axi_cfg != null && lifecycle_all_enabled())
            axi_cfg.arm_expected_read(
                addr & ((t.addr_width >= 64) ? '1 : ((64'd1 << t.addr_width) - 1)));
        pack_single_op(t, op, addr, data, wstrb, eff_size, dr);
        load_ir(6'(t.single_op_instr));
        shift_dr_wide(dr, unused);
    endtask

    // Poll SINGLE_OP (shifting zeros) until the bridge leaves BUSY_OR_FULL.
    task poll_single(
        j2a_target_t        t,
        output j2a_status_e status,
        output bit [63:0]   rdata
    );
        bit zeros[] = new[single_op_len(t)];
        bit rbits[];
        status = J2A_BUSY_OR_FULL;
        rdata  = '0;
        foreach (zeros[i]) zeros[i] = 1'b0;
        for (int unsigned poll = 0; poll < MaxStatusPolls; poll++) begin
            shift_dr_wide(zeros, rbits);
            unpack_single_op(t, rbits, status, rdata);
            if (status != J2A_BUSY_OR_FULL)
                break;
        end
        `uvm_info(get_type_name(), $sformatf(
            "%s SINGLE_OP status=%s rdata=0x%0h", t.name, status.name(), rdata),
            UVM_MEDIUM)
    endtask

    task single_write(
        j2a_target_t        t,
        bit [63:0]          addr,
        bit [63:0]          data,
        bit [7:0]           wstrb,
        output j2a_status_e status
    );
        bit [63:0] unused_rdata;
        issue_single(t, J2A_OP_WRITE, addr, data, wstrb);
        poll_single(t, status, unused_rdata);
    endtask

    task single_read(
        j2a_target_t        t,
        bit [63:0]          addr,
        output j2a_status_e status,
        output bit [63:0]   rdata
    );
        issue_single(t, J2A_OP_READ, addr);
        poll_single(t, status, rdata);
    endtask

    function void check_status(
        string       context_s,
        j2a_status_e observed,
        j2a_status_e expected
    );
        if (observed !== expected)
            `uvm_error("jtag2axi_status_chk", $sformatf(
                "%s: JTAG2AXI status %s, expected %s",
                context_s, observed.name(), expected.name()))
        else
            `uvm_info("jtag2axi_status_chk", $sformatf(
                "%s: JTAG2AXI status %s as expected", context_s, observed.name()),
                UVM_MEDIUM)
    endfunction

    // --- lifecycle enables (must precede any JTAG2AXI op) ------------------
    task set_lifecycle(bit sip, bit soc, bit ap, bit sep, bit fuse);
        tb_vif.feat_ctrl_sip_debug <= sip;
        tb_vif.feat_ctrl_soc_debug <= soc;
        tb_vif.feat_ctrl_ap_debug  <= ap;
        tb_vif.feat_ctrl_sep_debug <= sep;
        tb_vif.feat_ctrl_fuse_test <= fuse;
        #100ns;  // settle in the system-clock domain (10ns period)
        `uvm_info(get_type_name(), $sformatf(
            "lifecycle sip=%0d soc=%0d ap=%0d sep=%0d fuse=%0d",
            sip, soc, ap, sep, fuse), UVM_MEDIUM)
    endtask

    task enable_all_lifecycle();
        set_lifecycle(1'b1, 1'b1, 1'b1, 1'b1, 1'b1);
    endtask

    function bit lifecycle_all_enabled();
        return tb_vif.feat_ctrl_sip_debug && tb_vif.feat_ctrl_soc_debug
            && tb_vif.feat_ctrl_ap_debug && tb_vif.feat_ctrl_sep_debug
            && tb_vif.feat_ctrl_fuse_test;
    endfunction

    // --- error arming (responder ports + shared checker, one place) --------
    task arm_target_error(
        j2a_target_t    t,
        bit [63:0]      addr,
        ocah_axi_resp_e resp,
        bit             for_read,
        bit             for_write
    );
        if (t.name == "smc_otp") begin
            if (otp_slave_seq == null)
                `uvm_fatal(get_type_name(),
                    "smc_otp error arming needs otp_slave_seq (slave agent API) plumbed")
            otp_slave_seq.inject_error(addr, resp, for_read, for_write);
        end else begin
            tb_vif.smc_axi_err_addr     <= addr[55:0];
            tb_vif.smc_axi_err_resp     <= resp[1:0];
            tb_vif.smc_axi_err_on_read  <= for_read;
            tb_vif.smc_axi_err_on_write <= for_write;
            tb_vif.smc_axi_err_arm      <= 1'b1;
        end
        if (axi_cfg != null)
            axi_cfg.arm_expected_resp(addr, resp, for_read, for_write);
        #20ns;
        `uvm_info(get_type_name(), $sformatf(
            "%s armed error resp=%s addr=0x%0h read=%0d write=%0d",
            t.name, resp.name(), addr, for_read, for_write), UVM_MEDIUM)
    endtask

    task clear_target_error(j2a_target_t t);
        if (t.name == "smc_otp") begin
            if (otp_slave_seq != null)
                otp_slave_seq.clear_errors();
        end else begin
            tb_vif.smc_axi_err_arm <= 1'b0;
        end
        #20ns;
    endtask

    // --- request-activity evidence (security gating) -----------------------
    function void sample_activity(
        j2a_target_t t,
        output int unsigned aw,
        output int unsigned w,
        output int unsigned ar
    );
        if (t.name == "smc_otp") begin
            aw = tb_vif.smc_otp_axil_awvalid_count;
            w  = tb_vif.smc_otp_axil_wvalid_count;
            ar = tb_vif.smc_otp_axil_arvalid_count;
        end else begin
            aw = tb_vif.smc_axi_awvalid_count;
            w  = tb_vif.smc_axi_wvalid_count;
            ar = tb_vif.smc_axi_arvalid_count;
        end
    endfunction

    // Compare an activity snapshot pair through the shared evidence recorder.
    function void expect_no_activity_evidence(
        j2a_target_t t,
        int unsigned before_aw, int unsigned before_w, int unsigned before_ar,
        int unsigned after_aw,  int unsigned after_w,  int unsigned after_ar,
        string       context_s
    );
        if (axi_evidence == null)
            return;
        void'(axi_evidence.expect_equal("CHK-AXI-GATE-AW", after_aw, before_aw,
            $sformatf("%s target=%s source=tb_pulse_counters", context_s, t.name)));
        void'(axi_evidence.expect_equal("CHK-AXI-GATE-W", after_w, before_w,
            $sformatf("%s target=%s source=tb_pulse_counters", context_s, t.name)));
        void'(axi_evidence.expect_equal("CHK-AXI-GATE-AR", after_ar, before_ar,
            $sformatf("%s target=%s source=tb_pulse_counters", context_s, t.name)));
    endfunction

endclass : dtp_jtag2axi_base_seq
