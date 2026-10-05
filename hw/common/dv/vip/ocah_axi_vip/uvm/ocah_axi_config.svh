// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Configuration for one passive ocah_axi_vip UVM instance (one observed bus).
//
// Owns the expected-response arming table — the single source of truth that
// classifies EXPECTED versus UNEXPECTED non-OKAY responses. A sequence that
// injects an error into a responder arms the same beat-aligned address here
// (see the DTP dtp_jtag2axi_base_test_seq arm_target_error helper); the reference
// model consumes the one-shot when predicting, and the scoreboard reports the
// consumed expectation as CHK-AXI-ERR-INJ evidence.

class ocah_axi_config extends uvm_object;
  `uvm_object_utils(ocah_axi_config)

  // Observation surface. The virtual interface uses ocah_axi_if's DEFAULT
  // (maximum) parameterization; the real bus geometry is set below and used
  // by the monitor to mask sampled values.
  virtual ocah_axi_if vif;

  ocah_axi_protocol_e protocol   = OCAH_AXI_PROTO_AXI4_LITE;
  int unsigned        addr_width = 32;
  int unsigned        data_width = 32;
  int unsigned        id_width   = 0;

  // Component gating.
  bit en_monitor    = 1'b1;
  bit en_ref_model  = 1'b1;
  bit en_scoreboard = 1'b1;
  bit en_cov        = 1'b0;

  // Zero-check rejection is armed only by tests that expect AXI traffic so
  // non-AXI tests (e.g. dtp_sanity_test) stay green.
  bit require_checks = 1'b0;
  string required_ids[$];

  // Stable CHECKER_SUMMARY name for this instance.
  string name_tag = "ocah_axi";

  // Commercial-VIP integration hook (opaque; template parity with JTAG cfg).
  uvm_object vendor_cfg;

  // One-shot expected-response tables, keyed by beat-aligned address.
  protected ocah_axi_resp_e m_expected_rd[bit [63:0]];
  protected ocah_axi_resp_e m_expected_wr[bit [63:0]];

  // Stimulus-intent write records (FIFO, one entry per expected write):
  // the address, data, and strobes the TEST programmed, independent of the
  // observed bus. Single-beat contract (the DTP single-op flow).
  typedef struct {
    bit [63:0] addr;
    bit [63:0] data;
    bit [7:0]  strb;
  } ocah_axi_write_intent_t;

  protected ocah_axi_write_intent_t m_expected_writes[$];

  // Stimulus-intent read addresses (one entry per expected read).
  protected bit [63:0] m_expected_reads[$];

  function new(string name = "ocah_axi_config");
    super.new(name);
  endfunction

  function int unsigned beat_bytes();
    return data_width / 8;
  endfunction

  function bit [63:0] beat_align(bit [63:0] addr);
    return (addr / beat_bytes()) * beat_bytes();
  endfunction

  // Arm a one-shot expected non-OKAY response (same alignment contract as
  // the responder error controls).
  function void arm_expected_resp(bit [63:0] addr, ocah_axi_resp_e resp, bit for_read = 1'b1,
                                  bit for_write = 1'b1);
    bit [63:0] aligned = beat_align(addr);
    if (for_read) m_expected_rd[aligned] = resp;
    if (for_write) m_expected_wr[aligned] = resp;
    `uvm_info(get_type_name(), $sformatf(
              "armed expected resp=%s addr=0x%0h (aligned 0x%0h) read=%0d write=%0d",
              resp.name(),
              addr,
              aligned,
              for_read,
              for_write
              ), UVM_LOW)
  endfunction

  function void clear_expected_resp();
    m_expected_rd.delete();
    m_expected_wr.delete();
  endfunction

  function int unsigned pending_expected_resp();
    return m_expected_rd.size() + m_expected_wr.size();
  endfunction

  // Peek the expected response for one beat address (no consumption).
  function ocah_axi_resp_e expected_resp_for(bit [63:0] addr, ocah_axi_dir_e dir);
    bit [63:0] aligned = beat_align(addr);
    if (dir == OCAH_AXI_DIR_READ && m_expected_rd.exists(aligned)) return m_expected_rd[aligned];
    if (dir == OCAH_AXI_DIR_WRITE && m_expected_wr.exists(aligned)) return m_expected_wr[aligned];
    return OCAH_AXI_RESP_OKAY;
  endfunction

  // Arm the stimulus address/data/wstrb the next observed write must match.
  function void arm_expected_write(bit [63:0] addr, bit [63:0] data, bit [7:0] strb);
    ocah_axi_write_intent_t intent;
    intent.addr = addr;
    intent.data = data;
    intent.strb = strb;
    m_expected_writes.push_back(intent);
    `uvm_info(get_type_name(), $sformatf(
              "armed expected write addr=0x%0h data=0x%0h strb=0x%0h (pending=%0d)",
              addr,
              data,
              strb,
              m_expected_writes.size()
              ), UVM_LOW)
  endfunction

  // Consume the intent matching the observed beat-aligned address (NOT
  // FIFO order: B responses may legally reorder across IDs).
  function bit consume_expected_write(bit [63:0] observed_addr,
                                      output ocah_axi_write_intent_t intent);
    bit [63:0] aligned = beat_align(observed_addr);
    foreach (m_expected_writes[i]) begin
      if (beat_align(m_expected_writes[i].addr) == aligned) begin
        intent = m_expected_writes[i];
        m_expected_writes.delete(i);
        return 1'b1;
      end
    end
    return 1'b0;
  endfunction

  function int unsigned pending_expected_writes();
    return m_expected_writes.size();
  endfunction

  // Arm the stimulus address the next observed read must match.
  function void arm_expected_read(bit [63:0] addr);
    m_expected_reads.push_back(addr);
    `uvm_info(get_type_name(), $sformatf(
              "armed expected read addr=0x%0h (pending=%0d)", addr, m_expected_reads.size()),
              UVM_LOW)
  endfunction

  function bit consume_expected_read(bit [63:0] observed_addr, output bit [63:0] intent_addr);
    bit [63:0] aligned = beat_align(observed_addr);
    foreach (m_expected_reads[i]) begin
      if (beat_align(m_expected_reads[i]) == aligned) begin
        intent_addr = m_expected_reads[i];
        m_expected_reads.delete(i);
        return 1'b1;
      end
    end
    return 1'b0;
  endfunction

  function int unsigned pending_expected_reads();
    return m_expected_reads.size();
  endfunction

  // Consume a one-shot expectation; `armed` reports whether one existed.
  function ocah_axi_resp_e consume_expected_resp(bit [63:0] addr, ocah_axi_dir_e dir,
                                                 output bit armed);
    bit [63:0] aligned = beat_align(addr);
    ocah_axi_resp_e resp = OCAH_AXI_RESP_OKAY;
    armed = 1'b0;
    if (dir == OCAH_AXI_DIR_READ && m_expected_rd.exists(aligned)) begin
      resp  = m_expected_rd[aligned];
      armed = 1'b1;
      m_expected_rd.delete(aligned);
    end else if (dir == OCAH_AXI_DIR_WRITE && m_expected_wr.exists(aligned)) begin
      resp  = m_expected_wr[aligned];
      armed = 1'b1;
      m_expected_wr.delete(aligned);
    end
    return resp;
  endfunction

endclass : ocah_axi_config
