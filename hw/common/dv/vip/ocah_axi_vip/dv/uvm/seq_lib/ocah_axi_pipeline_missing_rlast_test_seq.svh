// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_axi_pipeline_missing_rlast_test: an AXI4 read
// whose responder answers its final beat with RLAST low and sends no
// further beat. Under a shortened handshake bound, a pipeline [read X0,
// read X1, write Y] with the RLAST of X1 withheld reports X1 timed out
// holding the beat it received, with no observed ID and is_ok() 0, while
// the read ahead of it and the write complete and alone count in the
// statistics; the recording shows one handshake per request channel and
// two R handshakes with RLAST low on the second only. A second armed read
// under allow_timeout=0 raises the sequence's timeout error, and plain
// accesses afterwards complete. SV-UVM only: the cocotb masters pipeline
// AXI4-Lite accesses, and that bundle carries no RLAST.

class ocah_axi_pipeline_missing_rlast_test_seq extends ocah_axi_pipeline_base_test_seq;
  `uvm_object_utils(ocah_axi_pipeline_missing_rlast_test_seq)

  // Distinct word-aligned addresses: X0 is the read ahead of X1, X1 and X2
  // take the missing RLAST, Y is the write of the pipeline, Z the plain pair
  // after the timeouts.
  protected bit [63:0] m_word_x0, m_word_x1, m_word_x2, m_word_y, m_word_z;
  protected bit [63:0] m_value_x1, m_data_y;

  function new(string name = "ocah_axi_pipeline_missing_rlast_test_seq");
    super.new(name);
  endfunction

  protected function void pick_words();
    bit [63:0] words[$];
    while (words.size() < 5) begin
      bit [63:0] addr = 64'($urandom_range(16383)) & ~64'h3;
      if (!(addr inside {words})) words.push_back(addr);
    end
    m_word_x0 = words[0];
    m_word_x1 = words[1];
    m_word_x2 = words[2];
    m_word_y  = words[3];
    m_word_z  = words[4];
  endfunction

  protected task preload();
    ocah_axi_item wres;
    pick_words();
    m_value_x1 = 64'($urandom());
    `uvm_info(get_type_name(),
              $sformatf("step 1: preload X0=0x%0h X1=0x%0h X2=0x%0h Y=0x%0h bound=%0d", m_word_x0,
                        m_word_x1, m_word_x2, m_word_y, ShortTimeout), UVM_LOW)
    write_result(m_word_x0, 64'($urandom()), wres);
    write_result(m_word_x1, m_value_x1, wres);
    write_result(m_word_x2, 64'($urandom()), wres);
    write_result(m_word_y, 64'($urandom()), wres);
  endtask

  // [read X0, read X1, write Y] with RLAST withheld on X1, under
  // allow_timeout.
  protected task run_partial_read();
    ocah_axi_item ops[$];
    ocah_axi_item result;
    int unsigned writes_before = write_transactions;
    int unsigned reads_before = read_transactions;
    int unsigned hs[$];
    m_data_y = 64'($urandom());
    slave_seq.inject_missing_rlast(m_word_x1);
    ops.push_back(pipeline_read(m_word_x0));
    ops.push_back(pipeline_read(m_word_x1));
    ops.push_back(pipeline_write(m_word_y, m_data_y));
    `uvm_info(get_type_name(),
              "step 2: pipeline [read X0, read X1, write Y] with RLAST withheld on X1", UVM_LOW)
    recorded_pipeline(ops, result, 0, 0, 1'b1);

    void'(evidence.expect_true("CHK-AXI-PIPE-RLAST-TIMEOUT", result.timed_out, "operation"));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-RLAST-TIMEOUT", ops[1].timed_out, "read X1 timed_out"
    ));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-RLAST-TIMEOUT", !ops[1].is_ok(), "read X1 is_ok() low"
    ));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-RLAST-TIMEOUT",
        !ops[1].observed_id_valid && !ops[1].id_match(),
        "read X1 reports no observed ID"
    ));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-RLAST-KEEP",
        ops[0].is_ok() && !ops[0].timed_out && ops[0].observed_id_valid,
        "read X0 ahead of X1 completed"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-KEEP", 64'(ops[1].resp_list.size()), 64'd1, "read X1 responses kept"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-KEEP", 64'(ops[1].data_words.size()), 64'd1, "read X1 beats kept"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-KEEP", ops[1].first_data(), m_value_x1, "read X1 data of the beat"
    ));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-RLAST-KEEP",
        ops[2].is_ok() && !ops[2].timed_out && ops[2].observed_id_valid,
        "write Y completed"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-STATS",
        64'(read_transactions - reads_before),
        64'd1,
        "read transactions counted"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-STATS",
        64'(write_transactions - writes_before),
        64'd1,
        "write transactions counted"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-STATS", 64'(slave_seq.pending_errors()), 64'd0, "armed faults left"
    ));
    handshakes(3, hs);
    void'(evidence.expect_equal("CHK-AXI-PIPE-RLAST-WIRE", 64'(hs.size()), 64'd2, "AR handshakes"));
    handshakes(4, hs);
    void'(evidence.expect_equal("CHK-AXI-PIPE-RLAST-WIRE", 64'(hs.size()), 64'd2, "R handshakes"));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-RLAST-WIRE",
        hs.size() == 2 && m_samples[hs[0]].rlast && !m_samples[hs[1]].rlast,
        "RLAST high on the first R handshake and low on the second"
    ));
    handshakes(0, hs);
    void'(evidence.expect_equal("CHK-AXI-PIPE-RLAST-WIRE", 64'(hs.size()), 64'd1, "AW handshakes"));
    handshakes(1, hs);
    void'(evidence.expect_equal("CHK-AXI-PIPE-RLAST-WIRE", 64'(hs.size()), 64'd1, "W handshakes"));
    handshakes(2, hs);
    void'(evidence.expect_equal("CHK-AXI-PIPE-RLAST-WIRE", 64'(hs.size()), 64'd1, "B handshakes"));
  endtask

  // [read X2] with RLAST withheld, under the default severity: the sequence
  // reports the timeout as an error, which the catcher counts.
  protected task run_timeout_error();
    ocah_axi_expected_error_catcher catcher;
    ocah_axi_item ops[$];
    ocah_axi_item result;
    slave_seq.inject_missing_rlast(m_word_x2);
    ops.push_back(pipeline_read(m_word_x2));
    catcher = ocah_axi_expected_error_catcher::type_id::create("catcher");
    catcher.message_id   = get_type_name();
    catcher.message_text = "timed out";
    `uvm_info(get_type_name(),
              "step 3: pipeline [read X2] with RLAST withheld, timeout is an error", UVM_LOW)
    uvm_report_cb::add(null, catcher);
    pipeline_result(ops, result);
    uvm_report_cb::delete(null, catcher);
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-ERROR", 64'(catcher.caught), 64'd1, "timeout errors reported"
    ));
    void'(evidence.expect_true("CHK-AXI-PIPE-RLAST-ERROR", ops[0].timed_out, "read X2 timed_out"));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-ERROR", 64'(slave_seq.pending_errors()), 64'd0, "armed faults left"
    ));
  endtask

  protected task run_recovery();
    ocah_axi_item wres, rres;
    bit [63:0] data_z = 64'($urandom());
    `uvm_info(get_type_name(), $sformatf("step 4: read Y, then write and read Z=0x%0h", m_word_z),
              UVM_LOW)
    read_result(m_word_y, rres);
    void'(evidence.expect_true("CHK-AXI-PIPE-RLAST-RECOVER", rres.is_ok(), "read Y response"));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-RLAST-RECOVER", rres.first_data(), m_data_y, "read Y"
    ));
    write_result(m_word_z, data_z, wres);
    read_result(m_word_z, rres);
    void'(evidence.expect_equal("CHK-AXI-PIPE-RLAST-RECOVER", rres.first_data(), data_z, "read Z"));
  endtask

  task body();
    int unsigned saved_timeout;
    if (evidence == null || slave_seq == null)
      `uvm_fatal(get_type_name(), "evidence/slave_seq handles not bound")
    void'(resolve_cfg());
    saved_timeout = cfg.timeout_cycles;
    cfg.timeout_cycles = ShortTimeout;
    slave_seq.disable_backpressure();
    preload();
    run_partial_read();
    run_timeout_error();
    run_recovery();
    cfg.timeout_cycles = saved_timeout;
  endtask

endclass : ocah_axi_pipeline_missing_rlast_test_seq
