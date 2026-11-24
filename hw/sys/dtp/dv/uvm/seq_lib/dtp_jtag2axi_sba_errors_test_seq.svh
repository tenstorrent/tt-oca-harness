// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI System Bus Access errors on every bridge, each bridge in a seeded
// order. A SLVERR or DECERR response to a write or a read sets sberror 2, and
// an access size above the data width sets 4 without a bus transfer. While
// sberror is not 0 neither an sbdata0 write nor an sbaddress0 write under
// sbreadonaddr starts an access; an sbcs write with a nonzero sberror field
// clears it, and the next access completes. Each bridge keeps one error while
// the bridges after it run, which shows that an error on one bridge leaves the
// others working. The cocotb twin is
// seq_lib/dtp_jtag2axi_sba_errors_test_seq.py.

class dtp_jtag2axi_sba_errors_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_sba_errors_test_seq)

  localparam bit [2:0] SberrorBus = 3'd2;
  localparam bit [2:0] SberrorSize = 3'd4;
  // The largest sbaccess encoding, 128 bytes.
  localparam int unsigned SbaccessMax = 7;

  typedef struct {
    ocah_axi_resp_e resp;
    bit             is_read;
  } bus_error_t;

  protected string m_ledger;

  function new(string name = "dtp_jtag2axi_sba_errors_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  task body();
    string             names [$] = '{"smc_otp", "sep_otp", "smc_axi"};
    bus_error_t        errors[$];
    bit         [63:0] base;
    bit         [63:0] beat;
    bit         [63:0] rdata;
    bit         [63:0] data;
    seed_scenario_rng();
    `uvm_info(get_type_name(), "=== System Bus Access errors on every bridge ===", UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      m_ledger = t.name;
      open_bus_ledger();
      size_error_case(t);
      bus_error_case(t);
      bus_errors(errors);
      errors.shuffle();
      bus_error(t, errors[0].resp, errors[0].is_read, {t.name, ".held"}, base, beat);
      check_responder_activity(t, 1, {t.name, ".sba_errors"});
      close_bus_ledger();
      m_ledger = "";
    end
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      m_ledger = t.name;
      open_bus_ledger();
      check_sberror(t, SberrorBus, {t.name, ".held"});
      clear_sberror(t, {t.name, ".held"});
      write_neighbour_then_read(t, random_target_addr(t), {t.name, ".held.recovery"}, rdata, data);
      close_bus_ledger();
      m_ledger = "";
      `uvm_info(get_type_name(), $sformatf("Summary: %s System Bus Access errors complete", t.name),
                UVM_LOW)
    end
  endtask

  function string op_name(bit is_read);
    if (is_read) return "read";
    return "write";
  endfunction

  // SLVERR and DECERR, each on a write and on a read.
  function void bus_errors(output bus_error_t errors[$]);
    ocah_axi_resp_e resps[2] = '{OCAH_AXI_RESP_SLVERR, OCAH_AXI_RESP_DECERR};
    errors = {};
    foreach (resps[r]) begin
      errors.push_back('{resp: resps[r], is_read: 1'b0});
      errors.push_back('{resp: resps[r], is_read: 1'b1});
    end
  endfunction

  // Every sbaccess above the data width, started by an sbdata0 write and by
  // an sbaddress0 write, sets sberror 4 and reaches no bus.
  task size_error_case(dtp_j2a_target_t t);
    int unsigned cases[$];
    for (int unsigned size = t.default_size + 1; size <= SbaccessMax; size++) begin
      cases.push_back(2 * size);
      cases.push_back(2 * size + 1);
    end
    cases.shuffle();
    foreach (cases[i]) begin
      int unsigned        size = cases[i] / 2;
      bit                 is_read = cases[i] % 2;
      string              ctx = $sformatf("%s.size_error.size%0d.%s", t.name, size,
                                          op_name(is_read));
      // Aligned to the access size: the alignment error takes precedence.
      bit          [63:0] addr = random_target_addr(t) & ~((64'h1 << size) - 1);
      sba_setup(t, addr, size, is_read, ctx);
      if (!is_read) dmi_write(t, DTP_DM_SBDATA0, $urandom(), {ctx, ".sbdata0"});
      wait_sba_idle(t, ctx, 1'b0, SberrorSize);
      check_sberror(t, SberrorSize, ctx);
      expect_no_bus_request(t, ctx);
      clear_sberror(t, ctx);
    end
  endtask

  // SLVERR and DECERR on a write and on a read, in a seeded order. Each error
  // refuses the next accesses until an sbcs write clears it, and an access at
  // the same beat then completes.
  task bus_error_case(dtp_j2a_target_t t);
    bus_error_t        errors[$];
    bit         [63:0] base;
    bit         [63:0] beat;
    bit         [63:0] rdata;
    bit         [63:0] data;
    bus_errors(errors);
    errors.shuffle();
    foreach (errors[i]) begin
      string ctx = $sformatf("%s.%s.%s", t.name, errors[i].resp.name(), op_name(errors[i].is_read));
      bus_error(t, errors[i].resp, errors[i].is_read, ctx, base, beat);
      refused_accesses(t, base, ctx);
      check_target_word(t, base, beat, t.default_size, {ctx, ".refused.mem"});
      clear_sberror(t, ctx);
      write_neighbour_then_read(t, base, {ctx, ".recovery"}, rdata, data);
    end
  endtask

  // A `resp` answer to a seeded access of a seeded size sets sberror 2, and
  // the beat at `base` keeps the content `beat` it was filled with.
  task bus_error(input dtp_j2a_target_t t, input ocah_axi_resp_e resp, input bit is_read,
                 input string context_s, output bit [63:0] base, output bit [63:0] beat);
    int unsigned        size = $urandom_range(t.default_size);
    int unsigned        offset = $urandom_range(t.beat_bytes / dtp_j2a_size_bytes(size) - 1) *
        dtp_j2a_size_bytes(size);
    bit          [63:0] mask = dtp_j2a_data_mask(size) << (8 * offset);
    bit          [63:0] lanes;
    base = random_target_addr(t);
    beat = random_distinct_word(t);
    sba_write(t, base, beat, t.default_size, {context_s, ".fill"});
    inject_bus_error(t, base, resp, is_read);
    if (is_read) begin
      sba_read_request(t, base + offset, size, context_s, 1'b0, SberrorBus);
    end else begin
      do lanes = ({$urandom(), $urandom()} << (8 * offset)) & mask; while (lanes == (beat & mask));
      sba_setup(t, base + offset, size, 1'b0, context_s);
      sba_write_data(t, base + offset, lanes >> (8 * offset), size, context_s, SberrorBus);
    end
    check_sberror(t, SberrorBus, context_s);
    check_target_word(t, base, beat, t.default_size, {context_s, ".mem"});
  endtask

  // While sberror is set, an sbdata0 write and an sbaddress0 write under
  // sbreadonaddr start no access and sberror keeps its value.
  task refused_accesses(dtp_j2a_target_t t, bit [63:0] addr, string context_s);
    bit reads[$] = '{1'b0, 1'b1};
    reads.shuffle();
    foreach (reads[i]) begin
      string ctx = {context_s, ".refused_", op_name(reads[i])};
      sba_setup(t, addr, t.default_size, reads[i], ctx);
      if (!reads[i]) dmi_write(t, DTP_DM_SBDATA0, $urandom(), {ctx, ".sbdata0"});
      check_sberror(t, SberrorBus, ctx);
      expect_no_bus_request(t, ctx);
    end
  endtask

  // An sbcs write with a seeded nonzero sberror field clears sberror.
  task clear_sberror(dtp_j2a_target_t t, string context_s);
    dtp_sbcs_t sbcs = '0;
    sbcs.sberror = 3'($urandom_range(7, 1));
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {context_s, ".clear.sbcs"});
    check_sberror(t, '0, {context_s, ".clear"});
  endtask

  // CHK-J2A-SBA-ERROR: sbcs reads sberror `expected`.
  // +DTP_J2A_SBA_ERROR_NEGATIVE flips the expected bit 0, so the run must fail.
  task check_sberror(dtp_j2a_target_t t, bit [2:0] expected, string context_s);
    ocah_axi_checker        ev = evidence(t);
    bit              [31:0] value;
    dtp_sbcs_t              sbcs;
    dmi_read(t, DTP_DM_SBCS, {context_s, ".sbcs"}, value);
    sbcs = dtp_sbcs_t'(value);
    if (test_cfg != null && test_cfg.j2a_sba_error_negative) expected ^= 3'h1;
    void'(ev.expect_equal(
        DtpJ2aSbaErrorCheckId,
        64'(sbcs.sberror),
        64'(expected),
        $sformatf(
            "%s target=%s sberror", context_s, t.name)
    ));
  endtask

endclass : dtp_jtag2axi_sba_errors_test_seq
