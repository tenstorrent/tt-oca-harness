// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI helper base sequence for the DTP SV-UVM flow — the SV analogue
// of the cocotb dtp_jtag2axi_base_test_seq.
//
// Geometry and DR layouts mirror cocotb env/dtp_types.py exactly:
//   SINGLE_OP DR (LSB-first): OP[2] | SIZE | WSTRB | DATA | ADDR
//     smc_otp / sep_otp: 2 + 2 + 4 + 32 + 32 = 72 bits
//     smc_axi:           2 + 2 + 8 + 64 + 56 = 132 bits
//   SERIES_CTRL DR (LSB-first): OP[2] | SIZE | PL_DEPTH[2] | ADDR | RESET
//     smc_otp / sep_otp: 39 bits; smc_axi: 63 bits
//   SERIES_DATA DR: 8*(1<<size) payload bits, plus one MSB increment/status
//     bit for *_DATA_WITH_ERROR_STATUS.
//   Capture: status = bits[1:0] (SUCCESS=0/SLVERR=1/DECERR=2/BUSY_OR_FULL=3,
//   NOT the AXI resp encoding), rdata at the DATA offset.
// Wide (>64-bit) TDR scans use the ocah_jtag_item wbits/rbits extension.
//
// Both responders are shared ocah_axi_vip UVM slave agents; the test plumbs
// the target-under-test handle bundle (axi_cfg / axi_evidence /
// axi_ref_model / slave_seq) before start(). Error arming discipline:
// arm_target_error() programs the responder injection AND
// cfg.arm_expected_resp() in one place, so the injected non-OKAY is
// EXPECTED for the shared AXI scoreboard; clear_target_error() reverses
// both. +DTP_AXI_SCOREBOARD_NEGATIVE is the documented negative-validation
// hook: it arms the WRONG expected response so the run must FAIL, proving
// the checker rejects a bad expectation end to end (plusarg twin of the
// cocotb DTP_AXI_SCOREBOARD_NEGATIVE env knob).
//
// Gated attempts must never arm credits: issue_single() skips intent arming
// whenever the target's lifecycle disable is asserted (an armed credit that
// is never consumed correctly fails at check_phase). The lifecycle debug
// disables reset to the fail-closed '1 tie-off, so the target's disable
// must be cleared before any JTAG2AXI op.

class dtp_jtag2axi_base_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_base_test_seq)

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
    string                                name;
    jtag_inst_reg_pkg::jtag_instruction_e single_op_instr;
    jtag_inst_reg_pkg::jtag_instruction_e series_ctrl_instr;
    jtag_inst_reg_pkg::jtag_instruction_e series_data_incr_instr;
    jtag_inst_reg_pkg::jtag_instruction_e series_data_no_incr_instr;
    jtag_inst_reg_pkg::jtag_instruction_e series_data_with_status_instr;
    int unsigned                          addr_width;
    int unsigned                          data_width;
    int unsigned                          size_bits;
    int unsigned                          wstrb_bits;
    int unsigned                          default_size;
    int unsigned                          beat_bytes;
    // The one dbg_disable_t field that gates this bridge (one-hot mask).
    sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_mask;
  } j2a_target_t;

  localparam int unsigned MaxStatusPolls = 16;
  // Responder memory footprint (both slave agents; addresses wrap).
  localparam int unsigned TargetMemBytes = 65536;
  // The UVM harness system clock is fixed at 100 MHz (tb_top).
  localparam time SysClkPeriod = 10ns;

  // Plumbed by the test for the target under test: the shared AXI VIP
  // passive cfg (expected-response/intent arming), its scoreboard evidence
  // recorder, the passive reference model (backdoor-preload mirror), and
  // the slave agent's test-facing API (error injection / backdoor memory).
  ocah_axi_config         axi_cfg;
  ocah_axi_checker        axi_evidence;
  ocah_axi_ref_model      axi_ref_model;
  ocah_axi_slave_sequence slave_seq;

  function new(string name = "dtp_jtag2axi_base_test_seq");
    super.new(name);
  endfunction

  // --- target geometry (mirrors dtp_types.py JTAG2AXI_TARGETS) ----------
  static function j2a_target_t target_smc_otp();
    j2a_target_t t;
    t.name = "smc_otp";
    t.single_op_instr = jtag_inst_reg_pkg::SMC_OTP_AXI_SINGLE_OP_INSTR;
    t.series_ctrl_instr = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_CTRL_INSTR;
    t.series_data_incr_instr = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_INCR_INSTR;
    t.series_data_no_incr_instr = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR;
    t.series_data_with_status_instr =
            jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
    t.addr_width = 32;
    t.data_width = 32;
    t.size_bits = 2;
    t.wstrb_bits = 4;
    t.default_size = 2;
    t.beat_bytes = 4;
    t.dbg_disable_mask = '0;
    t.dbg_disable_mask.smc_otp_jtag2axi = 1'b1;
    return t;
  endfunction

  static function j2a_target_t target_sep_otp();
    j2a_target_t t;
    t.name = "sep_otp";
    t.single_op_instr = jtag_inst_reg_pkg::SEP_OTP_AXI_SINGLE_OP_INSTR;
    t.series_ctrl_instr = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_CTRL_INSTR;
    t.series_data_incr_instr = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_INCR_INSTR;
    t.series_data_no_incr_instr = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR;
    t.series_data_with_status_instr =
            jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
    t.addr_width = 32;
    t.data_width = 32;
    t.size_bits = 2;
    t.wstrb_bits = 4;
    t.default_size = 2;
    t.beat_bytes = 4;
    t.dbg_disable_mask = '0;
    t.dbg_disable_mask.sep_otp_jtag2axi = 1'b1;
    return t;
  endfunction

  static function j2a_target_t target_smc_axi();
    j2a_target_t t;
    t.name = "smc_axi";
    t.single_op_instr = jtag_inst_reg_pkg::SMC_AXI_SINGLE_OP_INSTR;
    t.series_ctrl_instr = jtag_inst_reg_pkg::SMC_AXI_SERIES_CTRL_INSTR;
    t.series_data_incr_instr = jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_INCR_INSTR;
    t.series_data_no_incr_instr = jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_NO_INCR_INSTR;
    t.series_data_with_status_instr =
            jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
    t.addr_width = 56;
    t.data_width = 64;
    t.size_bits = 2;
    t.wstrb_bits = 8;
    t.default_size = 3;
    t.beat_bytes = 8;
    t.dbg_disable_mask = '0;
    t.dbg_disable_mask.smc_jtag2axi = 1'b1;
    return t;
  endfunction

  static function int unsigned single_op_len(j2a_target_t t);
    return 2 + t.size_bits + t.wstrb_bits + t.data_width + t.addr_width;
  endfunction

  static function int unsigned series_ctrl_len(j2a_target_t t);
    return 2 + t.size_bits + 2 + t.addr_width + 1;
  endfunction

  static function j2a_status_e axi_resp_to_status(ocah_axi_resp_e resp);
    case (resp)
      OCAH_AXI_RESP_SLVERR: return J2A_SLVERR;
      OCAH_AXI_RESP_DECERR: return J2A_DECERR;
      default:              return J2A_SUCCESS;
    endcase
  endfunction

  // --- data/address helpers (cocotb parity) -------------------------------
  static function int unsigned size_bytes(int unsigned size);
    return 1 << size;
  endfunction

  static function bit [63:0] data_mask(int unsigned size);
    return bit_mask(8 * size_bytes(size));
  endfunction

  static function bit [7:0] full_wstrb(int unsigned size);
    return 8'((1 << size_bytes(size)) - 1);
  endfunction

  function bit [63:0] mask_target_data(j2a_target_t t, bit [63:0] value);
    return value & bit_mask(t.data_width);
  endfunction

  // Beat-aligned random address inside the responder memory window; wider
  // alignment when the transfer size exceeds the beat.
  function bit [63:0] random_target_aligned_addr(j2a_target_t t, int unsigned size);
    int unsigned align = (size_bytes(size) > t.beat_bytes) ? size_bytes(size) : t.beat_bytes;
    int unsigned max_slot = (TargetMemBytes - align) / align;
    return 64'($urandom_range(max_slot) * align);
  endfunction

  // --- responder backdoor memory (shared slave agents) --------------------
  protected function ocah_axi_slave_sequence responder(j2a_target_t t);
    if (slave_seq == null)
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s backdoor/error access needs slave_seq (slave agent API) plumbed", t.name))
    return slave_seq;
  endfunction

  // Backdoor-preload the responder RAM; mirrored into the passive reference
  // model's shadow so front-door reads of preloaded data compare clean.
  function void write_target_mem_int(j2a_target_t t, bit [63:0] addr, bit [63:0] value,
                                     int unsigned size);
    bit [7:0] payload[];
    bit [63:0] masked = value & data_mask(size);
    responder(t).write_int(addr, masked, size_bytes(size));
    payload = new[size_bytes(size)];
    foreach (payload[i]) payload[i] = masked[8*i+:8];
    if (axi_ref_model != null) axi_ref_model.backdoor_write(addr, payload);
  endfunction

  function bit [63:0] read_target_mem_int(j2a_target_t t, bit [63:0] addr, int unsigned size);
    return responder(t).read_int(addr, size_bytes(size)) & data_mask(size);
  endfunction

  // CHK-AXI-WMEM: responder RAM bytes versus the stimulus intent.
  function void check_target_memory(j2a_target_t t, bit [63:0] addr, bit [63:0] expected,
                                    int unsigned size, string context_s);
    bit [63:0] observed = read_target_mem_int(t, addr, size);
    if (axi_evidence != null)
      void'(axi_evidence.expect_equal(
          "CHK-AXI-WMEM",
          observed,
          expected & data_mask(
              size
          ),
          $sformatf(
              "%s target=%s addr=0x%0h bytes=%0d source=stimulus-intent",
              context_s,
              t.name,
              addr,
              size_bytes(
                  size
              ))
      ));
    else if (observed !== (expected & data_mask(size)))
      `uvm_error("jtag2axi_mem_chk", $sformatf(
                 "%s: memory at 0x%0h is 0x%0h, expected 0x%0h",
                 context_s,
                 addr,
                 observed,
                 expected & data_mask(
                     size
                 )
                 ))
  endfunction

  // --- DR packing (LSB-first: OP | SIZE | WSTRB | DATA | ADDR) ----------
  function void pack_single_op(j2a_target_t t, j2a_op_e op, bit [63:0] addr, bit [63:0] data,
                               bit [7:0] wstrb, int unsigned size, ref bit dr[]);
    int unsigned offset = 0;
    dr = new[single_op_len(t)];
    foreach (dr[i]) dr[i] = 1'b0;
    for (int unsigned i = 0; i < 2; i++) dr[offset++] = (int'(op) >> i) & 1'b1;
    for (int unsigned i = 0; i < t.size_bits; i++) dr[offset++] = (size >> i) & 1'b1;
    for (int unsigned i = 0; i < t.wstrb_bits; i++) dr[offset++] = (wstrb >> i) & 1'b1;
    for (int unsigned i = 0; i < t.data_width; i++) dr[offset++] = (data >> i) & 1'b1;
    for (int unsigned i = 0; i < t.addr_width; i++) dr[offset++] = (addr >> i) & 1'b1;
  endfunction

  function void unpack_single_op(j2a_target_t t, bit rbits[], output j2a_status_e status,
                                 output bit [63:0] rdata);
    int unsigned data_off = 2 + t.size_bits + t.wstrb_bits;
    int unsigned status_raw = 0;
    rdata = '0;
    for (int unsigned i = 0; i < 2 && i < rbits.size(); i++) status_raw |= int'(rbits[i]) << i;
    status = j2a_status_e'(status_raw);
    for (int unsigned i = 0; i < t.data_width && (data_off + i) < rbits.size(); i++)
    rdata[i] = rbits[data_off+i];
  endfunction

  // SERIES_CTRL packing (LSB-first: OP | SIZE | PL_DEPTH | ADDR | RESET).
  function bit [63:0] pack_series_ctrl(j2a_target_t t, j2a_op_e op, bit [63:0] addr,
                                       int unsigned pipeline_depth, int unsigned size,
                                       bit series_reset);
    int unsigned size_off = 2;
    int unsigned pl_depth_off = size_off + t.size_bits;
    int unsigned addr_off = pl_depth_off + 2;
    int unsigned reset_off = addr_off + t.addr_width;
    return (64'(int'(op)) & 64'h3) | ((64'(size) & bit_mask(
        t.size_bits
    )) << size_off) | ((64'(pipeline_depth) & 64'h3) << pl_depth_off) | ((addr & bit_mask(
        t.addr_width
    )) << addr_off) | (64'(series_reset) << reset_off);
  endfunction

  function void unpack_series_ctrl(j2a_target_t t, bit [63:0] value, output bit series_reset,
                                   output bit [63:0] addr, output int unsigned pipeline_depth,
                                   output int unsigned size, output j2a_status_e status);
    int unsigned size_off = 2;
    int unsigned pl_depth_off = size_off + t.size_bits;
    int unsigned addr_off = pl_depth_off + 2;
    int unsigned reset_off = addr_off + t.addr_width;
    status         = j2a_status_e'(value & 64'h3);
    size           = int'((value >> size_off) & bit_mask(t.size_bits));
    pipeline_depth = int'((value >> pl_depth_off) & 64'h3);
    addr           = (value >> addr_off) & bit_mask(t.addr_width);
    series_reset   = value[reset_off];
  endfunction

  // Wide DR scan (>64 bits) through the VIP sequence API's wbits/rbits path.
  task shift_dr_wide(input bit pattern[], output bit observed[]);
    dr_scan_wide(pattern, observed);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after wide DR scan");
  endtask

  // --- single-op TDR flow ------------------------------------------------
  task issue_single(j2a_target_t t, j2a_op_e op, bit [63:0] addr, bit [63:0] data = '0,
                    bit [7:0] wstrb = '0, int unsigned size = 0, bit use_default_size = 1'b1);
    bit dr[];
    bit unused[];
    int unsigned eff_size = use_default_size ? t.default_size : size;
    `uvm_info(get_type_name(), $sformatf(
                                   "%s SINGLE_OP %s addr=0x%0h data=0x%0h wstrb=0x%0h size=%0d",
                                   t.name, op.name(), addr, data, wstrb, eff_size), UVM_MEDIUM)
    // Stimulus-intent records: the address/data/wstrb programmed into the
    // TDR is the truth the observed bus transaction must match
    // (CHK-AXI-WADDR / CHK-AXI-WDATA / CHK-AXI-STRB / CHK-AXI-RADDR).
    // Gated ops never reach the bus: do not arm intents while the
    // target's disable is asserted (the no-activity evidence owns that
    // case; a dangling intent would false-fail at check_phase).
    if (op == J2A_OP_WRITE && axi_cfg != null && target_enabled(t))
      axi_cfg.arm_expected_write(addr & bit_mask(t.addr_width), data & bit_mask(t.data_width),
                                 wstrb);
    if (op == J2A_OP_READ && axi_cfg != null && target_enabled(t))
      axi_cfg.arm_expected_read(addr & bit_mask(t.addr_width));
    pack_single_op(t, op, addr, data, wstrb, eff_size, dr);
    load_ir(6'(t.single_op_instr));
    shift_dr_wide(dr, unused);
  endtask

  // Poll SINGLE_OP (shifting zeros) until the bridge leaves BUSY_OR_FULL,
  // then land CHK-AXI-COMPLETION: a bridge stuck BUSY within the poll
  // bound fails (every call site expects a final, settled status).
  task poll_single(j2a_target_t t, output j2a_status_e status, output bit [63:0] rdata,
                   input string context_s = "single_op");
    bit zeros[] = new[single_op_len(t)];
    bit rbits[];
    status = J2A_BUSY_OR_FULL;
    rdata  = '0;
    foreach (zeros[i]) zeros[i] = 1'b0;
    for (int unsigned poll = 0; poll < MaxStatusPolls; poll++) begin
      shift_dr_wide(zeros, rbits);
      unpack_single_op(t, rbits, status, rdata);
      if (status != J2A_BUSY_OR_FULL) break;
    end
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP status=%s rdata=0x%0h", t.name,
                                         status.name(), rdata), UVM_MEDIUM)
    if (axi_evidence != null)
      void'(axi_evidence.expect_true(
          "CHK-AXI-COMPLETION",
          status != J2A_BUSY_OR_FULL,
          $sformatf(
              "%s target=%s polls=%0d", context_s, t.name, MaxStatusPolls)
      ));
  endtask

  task single_write(j2a_target_t t, bit [63:0] addr, bit [63:0] data, bit [7:0] wstrb,
                    output j2a_status_e status, input int unsigned size = 0,
                    input bit use_default_size = 1'b1, input string context_s = "single_write");
    bit [63:0] unused_rdata;
    issue_single(t, J2A_OP_WRITE, addr, data, wstrb, size, use_default_size);
    poll_single(t, status, unused_rdata, context_s);
  endtask

  task single_read(j2a_target_t t, bit [63:0] addr, output j2a_status_e status,
                   output bit [63:0] rdata, input int unsigned size = 0,
                   input bit use_default_size = 1'b1, input string context_s = "single_read");
    issue_single(t, J2A_OP_READ, addr, '0, '0, size, use_default_size);
    poll_single(t, status, rdata, context_s);
  endtask

  function void check_status(string context_s, j2a_status_e observed, j2a_status_e expected);
    if (observed !== expected)
      `uvm_error("jtag2axi_status_chk", $sformatf(
                 "%s: JTAG2AXI status %s, expected %s", context_s, observed.name(), expected.name()
                 ))
    else
      `uvm_info("jtag2axi_status_chk", $sformatf(
                "%s: JTAG2AXI status %s as expected", context_s, observed.name()), UVM_MEDIUM)
  endfunction

  // --- checked single operations (cocotb *_and_check parity) --------------
  // Write, poll to completion, and verify enabled byte lanes landed in the
  // responder memory.
  task write_target_single_and_check(j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                                     output j2a_status_e status, input int unsigned size,
                                     input bit [7:0] wstrb = 8'hFF,
                                     input string context_s = "single_write");
    bit [63:0] observed;
    bit [63:0] masked = data & data_mask(size);
    single_write(t, addr, masked, wstrb, status, size, 1'b0, context_s);
    check_status({context_s, ".status"}, status, J2A_SUCCESS);
    observed = read_target_mem_int(t, addr, size);
    for (int unsigned lane = 0; lane < size_bytes(size); lane++) begin
      if (wstrb[lane]) begin
        if (observed[8*lane+:8] !== masked[8*lane+:8])
          `uvm_error("jtag2axi_data_chk", $sformatf(
                     "%s.byte%0d: memory 0x%02h != written 0x%02h (addr=0x%0h wstrb=0x%02h)",
                     context_s,
                     lane,
                     observed[8*lane+:8],
                     masked[8*lane+:8],
                     addr + lane,
                     wstrb
                     ))
      end
    end
  endtask

  // Read, poll to completion, and verify the returned data.
  task read_target_single_and_check(j2a_target_t t, bit [63:0] addr, bit [63:0] expected,
                                    output j2a_status_e status, input int unsigned size,
                                    input string context_s = "single_read");
    bit [63:0] rdata;
    single_read(t, addr, status, rdata, size, 1'b0, context_s);
    check_status({context_s, ".status"}, status, J2A_SUCCESS);
    if ((rdata & data_mask(size)) !== (expected & data_mask(size)))
      `uvm_error("jtag2axi_data_chk", $sformatf(
                 "%s: rdata 0x%0h != expected 0x%0h (addr=0x%0h size=%0d)",
                 context_s,
                 rdata & data_mask(
                     size
                 ),
                 expected & data_mask(
                     size
                 ),
                 addr,
                 size
                 ))
  endtask

  // Error-path variants: complete and verify the requested status.
  task write_target_single_expect_status(j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                                         j2a_status_e expected_status, output j2a_status_e status,
                                         input int unsigned size, input bit [7:0] wstrb = 8'hFF,
                                         input string context_s = "single_write_error");
    single_write(t, addr, data & data_mask(size), wstrb, status, size, 1'b0, context_s);
    check_status({context_s, ".status"}, status, expected_status);
  endtask

  task read_target_single_expect_status(j2a_target_t t, bit [63:0] addr,
                                        j2a_status_e expected_status, output j2a_status_e status,
                                        output bit [63:0] rdata, input int unsigned size,
                                        input string context_s = "single_read_error");
    single_read(t, addr, status, rdata, size, 1'b0, context_s);
    check_status({context_s, ".status"}, status, expected_status);
  endtask

  // Verify an OKAY access after an error/reset path to catch stuck state.
  task verify_target_recovery(j2a_target_t t, bit [63:0] addr, bit [63:0] data, bit is_read,
                              string context_s);
    j2a_status_e status;
    int unsigned size = t.default_size;
    if (is_read) begin
      write_target_mem_int(t, addr, data, size);
      read_target_single_and_check(t, addr, data, status, size, {context_s, ".recover_read"});
    end else begin
      write_target_single_and_check(t, addr, data, status, size, full_wstrb(size), {
                                    context_s, ".recover_write"});
      // CHK-AXI-WMEM against the STIMULUS intent (non-circular).
      check_target_memory(t, addr, data, size, {context_s, ".recover_write"});
    end
  endtask

  // --- series TDR flow -----------------------------------------------------
  // Program SERIES_CTRL (WRITE/READ arms a stream; NOP+reset clears it).
  task series_ctrl_op(j2a_target_t t, j2a_op_e op, bit [63:0] addr, int unsigned size,
                      int unsigned pipeline_depth = 0, bit series_reset = 1'b0);
    bit [63:0] value = pack_series_ctrl(t, op, addr, pipeline_depth, size, series_reset);
    bit [63:0] unused;
    `uvm_info(get_type_name(),
              $sformatf("%s SERIES_CTRL %s addr=0x%0h size=%0d pl_depth=%0d reset=%0d", t.name,
                        op.name(), addr, size, pipeline_depth, series_reset), UVM_MEDIUM)
    load_ir(6'(t.series_ctrl_instr));
    shift_dr(value, series_ctrl_len(t), unused);
  endtask

  // Capture and decode SERIES_CTRL (shifting a NOP image), landing
  // CHK-AXI-COMPLETION on the settled status.
  task read_series_ctrl(j2a_target_t t, input int unsigned size, output bit series_reset,
                        output bit [63:0] addr_after, output int unsigned pipeline_depth,
                        output int unsigned size_rd, output j2a_status_e status);
    bit [63:0] nop_image = pack_series_ctrl(t, J2A_OP_NOP, '0, 0, size, 1'b0);
    bit [63:0] observed;
    load_ir(6'(t.series_ctrl_instr));
    shift_dr(nop_image, series_ctrl_len(t), observed);
    unpack_series_ctrl(t, observed, series_reset, addr_after, pipeline_depth, size_rd, status);
    `uvm_info(get_type_name(),
              $sformatf("%s SERIES_CTRL reset=%0d addr=0x%0h pl_depth=%0d size=%0d status=%s",
                        t.name, series_reset, addr_after, pipeline_depth, size_rd, status.name()),
              UVM_MEDIUM)
    // Every series stream ends with this status capture; a bridge stuck
    // BUSY fails here (call sites expect a settled status, never BUSY).
    if (axi_evidence != null)
      void'(axi_evidence.expect_true(
          "CHK-AXI-COMPLETION",
          status != J2A_BUSY_OR_FULL,
          $sformatf(
              "series_ctrl target=%s", t.name)
      ));
  endtask

  // One series-data shift: payload-sized TDR, optional MSB increment bit
  // (with-status mode), five idle TCK cycles for the op to launch.
  protected task series_data_shift(j2a_target_t t, jtag_inst_reg_pkg::jtag_instruction_e instr,
                                   bit [63:0] data, int unsigned size,
                                   input int increment,  // <0: no increment/status bit in the TDR
                                   output bit [63:0] result);
    int unsigned payload_bits = 8 * size_bytes(size);
    int unsigned width = payload_bits + ((increment >= 0) ? 1 : 0);
    bit pattern[];
    bit rbits[];
    pattern = new[width];
    for (int unsigned i = 0; i < payload_bits; i++) pattern[i] = data[i];
    if (increment >= 0) pattern[payload_bits] = bit'(increment);
    load_ir(6'(instr));
    shift_dr_wide(pattern, rbits);
    result = '0;
    foreach (rbits[i]) if (i < 64) result[i] = rbits[i];
    repeat (5) step(1'b0);
  endtask

  task series_data_incr(j2a_target_t t, bit [63:0] data, int unsigned size);
    bit [63:0] unused;
    series_data_shift(t, t.series_data_incr_instr, data, size, -1, unused);
  endtask

  task series_data_no_incr(j2a_target_t t, bit [63:0] data, int unsigned size);
    bit [63:0] unused;
    series_data_shift(t, t.series_data_no_incr_instr, data, size, -1, unused);
  endtask

  task series_data_with_status(j2a_target_t t, bit [63:0] data, int unsigned size, bit increment,
                               output bit [63:0] rdata, output bit status_bit);
    bit [63:0] result;
    int unsigned payload_bits = 8 * size_bytes(size);
    series_data_shift(t, t.series_data_with_status_instr, data, size, int'(increment), result);
    rdata      = result & data_mask(size);
    status_bit = result[payload_bits];
  endtask

  // --- lifecycle debug disables (must be cleared before JTAG2AXI ops) ----
  task set_dbg_disable(sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    tb_vif.dbg_disable <= d;
    // The DUT synchronizes dbg_disable through 2-stage TCK-domain flops;
    // four toggling idle TCK cycles are the TB settle margin.
    for (int unsigned i = 0; i < 4; i++) step(1'b0);
    wait_sys_cycles(4);
    `uvm_info(get_type_name(), $sformatf("dbg_disable=0x%03h", d), UVM_MEDIUM)
  endtask

  task enable_all_debug();
    set_dbg_disable('0);
  endtask

  // Assert exactly the disable that gates this target (all others clear).
  task gate_target(j2a_target_t t);
    set_dbg_disable(t.dbg_disable_mask);
  endtask

  function bit target_enabled(j2a_target_t t);
    return (tb_vif.dbg_disable & t.dbg_disable_mask) == '0;
  endfunction

  // --- error arming (responder injection + shared checker, one place) ----
  task arm_target_error(j2a_target_t t, bit [63:0] addr, ocah_axi_resp_e resp, bit for_read,
                        bit for_write, bit arm_expected = 1'b1);
    ocah_axi_resp_e armed_resp = resp;
    responder(t).inject_error(addr, resp, for_read, for_write);
    // arm_expected=0 injects WITHOUT arming the scoreboard expectation —
    // for gated attempts whose op must never reach the bus.
    if (arm_expected && axi_cfg != null) begin
      if ($test$plusargs("DTP_AXI_SCOREBOARD_NEGATIVE")) begin
        armed_resp = (resp == OCAH_AXI_RESP_DECERR) ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_DECERR;
        `uvm_warning(get_type_name(),
                     $sformatf("NEGATIVE VALIDATION: arming resp=%s instead of injected resp=%s",
                               armed_resp.name(), resp.name()))
      end
      axi_cfg.arm_expected_resp(addr, armed_resp, for_read, for_write);
    end
    #20ns;
    `uvm_info(get_type_name(), $sformatf("%s armed error resp=%s addr=0x%0h read=%0d write=%0d",
                                         t.name, resp.name(), addr, for_read, for_write),
              UVM_MEDIUM)
  endtask

  task clear_target_error(j2a_target_t t);
    if (slave_seq != null) slave_seq.clear_errors();
    #20ns;
  endtask

  // Bounded responder READY backpressure on the target under test (cocotb
  // configure_target_backpressure parity; channel names are "aw"/"w"/"ar").
  function void configure_target_backpressure(j2a_target_t t, string channels[$],
                                              int unsigned stall_cycles);
    `uvm_info(
        get_type_name(), $sformatf(
        "%s configure backpressure channels=%p stall_cycles=%0d", t.name, channels, stall_cycles),
        UVM_MEDIUM)
    responder(t).enable_backpressure(channels, stall_cycles);
  endfunction

  function void clear_target_backpressure(j2a_target_t t);
    responder(t).disable_backpressure();
  endfunction

  // --- system-domain helpers ----------------------------------------------
  // The UVM harness clock is fixed at 100 MHz, so system-domain waits are
  // exact delays (sequences hold no clock handle).
  task wait_sys_cycles(int unsigned cycles);
    #(cycles * SysClkPeriod);
  endtask

  // Pulse rst_n_i without POR/TRST, preserving TAP accessibility.
  task pulse_system_reset(int unsigned cycles = 5);
    tb_vif.sys_rst_n <= 1'b0;
    wait_sys_cycles(cycles);
    tb_vif.sys_rst_n <= 1'b1;
    wait_sys_cycles(cycles);
  endtask

  // --- request-activity evidence (security gating) -----------------------
  function void sample_activity(j2a_target_t t, output int unsigned aw, output int unsigned w,
                                output int unsigned ar);
    if (t.name == "smc_otp") begin
      aw = tb_vif.smc_otp_axil_awvalid_count;
      w  = tb_vif.smc_otp_axil_wvalid_count;
      ar = tb_vif.smc_otp_axil_arvalid_count;
    end else if (t.name == "sep_otp") begin
      aw = tb_vif.sep_otp_axil_awvalid_count;
      w  = tb_vif.sep_otp_axil_wvalid_count;
      ar = tb_vif.sep_otp_axil_arvalid_count;
    end else begin
      aw = tb_vif.smc_axi_awvalid_count;
      w  = tb_vif.smc_axi_wvalid_count;
      ar = tb_vif.smc_axi_arvalid_count;
    end
  endfunction

  // Compare an activity snapshot pair through the shared evidence recorder.
  function void expect_no_activity_evidence(
      j2a_target_t t, int unsigned before_aw, int unsigned before_w, int unsigned before_ar,
      int unsigned after_aw, int unsigned after_w, int unsigned after_ar, string context_s);
    if (axi_evidence == null) return;
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-AW",
        after_aw,
        before_aw,
        $sformatf(
            "%s target=%s source=tb_pulse_counters", context_s, t.name)
    ));
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-W",
        after_w,
        before_w,
        $sformatf(
            "%s target=%s source=tb_pulse_counters", context_s, t.name)
    ));
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-AR",
        after_ar,
        before_ar,
        $sformatf(
            "%s target=%s source=tb_pulse_counters", context_s, t.name)
    ));
  endfunction

  // Wait until an operation reaches the target's request channel (series
  // ops launch in the system domain after the TDR shift completes).
  task wait_for_target_activity(j2a_target_t t, int unsigned before_aw, int unsigned before_w,
                                int unsigned before_ar, bit is_read, string context_s,
                                int unsigned timeout_cycles = 200);
    int unsigned aw, w, ar;
    for (int unsigned cycle = 0; cycle < timeout_cycles; cycle++) begin
      sample_activity(t, aw, w, ar);
      if (is_read ? (ar > before_ar) : (aw > before_aw)) begin
        `uvm_info(get_type_name(), $sformatf("%s: %s %s activity after %0d cycles", context_s,
                                             t.name, is_read ? "AR" : "AW", cycle), UVM_MEDIUM)
        return;
      end
      wait_sys_cycles(1);
    end
    `uvm_error("jtag2axi_activity_chk",
               $sformatf("%s: expected %s %s activity within %0d cycles (aw=%0d->%0d ar=%0d->%0d)",
                         context_s, t.name, is_read ? "AR" : "AW", timeout_cycles, before_aw, aw,
                         before_ar, ar))
  endtask

  // CHK-AXI-NONVAC: scenario-level non-vacuity through the shared recorder
  // (the SV analogue of the cocotb stream-minimum + nonvacuous evidence).
  function void emit_nonvacuity_evidence(bit condition, string context_s);
    if (axi_evidence != null)
      void'(axi_evidence.expect_true("CHK-AXI-NONVAC", condition, context_s));
  endfunction

  // Completed-burst counters from the responder (exact per-transaction
  // counts; the tb pulse counters count VALID-high cycles, which are
  // timing-dependent per transaction on the reactive slave driver).
  function int unsigned write_bursts_now(j2a_target_t t);
    return responder(t).write_burst_count();
  endfunction

  function int unsigned read_bursts_now(j2a_target_t t);
    return responder(t).read_burst_count();
  endfunction

  // Wait until the responder completes a write burst beyond before_count
  // (bounded), so a backdoor memory check cannot race the W-beat commit —
  // the request-pulse wait above returns on AW, cycles before the data
  // beat lands in memory.
  task wait_for_write_completion(j2a_target_t t, int unsigned before_count, string context_s,
                                 int unsigned timeout_cycles = 200);
    for (int unsigned cycle = 0; cycle < timeout_cycles; cycle++) begin
      if (write_bursts_now(t) > before_count) return;
      wait_sys_cycles(1);
    end
    `uvm_error("jtag2axi_activity_chk",
               $sformatf("%s: %s write burst did not complete within %0d cycles", context_s,
                         t.name, timeout_cycles))
  endtask

endclass : dtp_jtag2axi_base_test_seq
