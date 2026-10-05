// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Configuration for one active ocah_axi_vip slave (memory-backed responder).
//
// Owns the responder-side one-shot fault controls (the SV-UVM analogue of
// the cocotb OcahFaultMixin): error-injection tables — a beat-aligned
// address armed for a direction answers the programmed non-OKAY response
// ONCE, skips the memory update (writes), and returns zero data (reads) —
// plus per-direction one-shot response-ID corruption, a one-shot missing
// RLAST per beat-aligned read address, and per-channel bounded READY
// backpressure. This table makes the responder MISBEHAVE; the separate
// passive ocah_axi_config arm_expected_resp table is what classifies the
// observed non-OKAY as EXPECTED for the scoreboard; tests arm both through
// their sequence layer.

class ocah_axi_slave_config extends uvm_object;
  `uvm_object_utils(ocah_axi_slave_config)

  // The responder drives its outputs on this interface procedurally; the
  // TB wires only the master-driven signals into it and routes the
  // responder-driven signals back to the DUT (see the DTP tb_top adoption).
  virtual ocah_axi_if vif;

  ocah_axi_protocol_e protocol   = OCAH_AXI_PROTO_AXI4_LITE;
  int unsigned        addr_width = 32;
  int unsigned        data_width = 32;
  int unsigned        id_width   = 0;

  uvm_active_passive_enum is_active = UVM_ACTIVE;

  // Backing memory footprint in bytes (power of two; addresses wrap).
  int unsigned mem_bytes = 65536;

  // Bounded READY backpressure, per master-driven channel (the SV-UVM
  // mirror of the cocotb bounded pause generator): when nonzero, the
  // responder repeats a low-for-N / high-for-one READY pattern on that
  // channel, so every handshake completes within N+1 cycles of VALID —
  // never a permanent stall.
  int unsigned aw_stall_cycles = 0;
  int unsigned w_stall_cycles  = 0;
  int unsigned ar_stall_cycles = 0;

  // Stable name for log messages.
  string name_tag = "ocah_axi_slave";

  // One-shot injected-error tables, keyed by beat-aligned address.
  protected ocah_axi_resp_e m_inject_rd[bit [63:0]];
  protected ocah_axi_resp_e m_inject_wr[bit [63:0]];

  // One-shot response-ID corruption masks per direction (the SV-UVM mirror
  // of the cocotb fault slave's inject_id_corruption): the next selected
  // transaction answers request_id ^ mask (ID-width truncated) instead of
  // echoing the request ID. 0 = disarmed (a zero mask is rejected — it
  // would be an echo).
  protected bit [15:0] m_id_corrupt_rd;
  protected bit [15:0] m_id_corrupt_wr;

  // One-shot missing-RLAST table, keyed by beat-aligned read address.
  protected bit m_missing_rlast[bit [63:0]];

  function new(string name = "ocah_axi_slave_config");
    super.new(name);
  endfunction

  function int unsigned beat_bytes();
    return data_width / 8;
  endfunction

  function bit [15:0] mask_id(bit [15:0] value);
    return (id_width == 0) ? '0 : (value & ((16'd1 << id_width) - 1));
  endfunction

  // Beat-align, then wrap into the memory footprint (mem_bytes is a power
  // of two).
  function bit [63:0] beat_align(bit [63:0] addr);
    return ((addr / 64'(beat_bytes())) * 64'(beat_bytes())) % 64'(mem_bytes);
  endfunction

  // Program a one-shot non-OKAY response at a beat-aligned address.
  function void inject_error(bit [63:0] addr, ocah_axi_resp_e resp, bit for_read = 1'b1,
                             bit for_write = 1'b1);
    bit [63:0] aligned = beat_align(addr);
    if (for_read) m_inject_rd[aligned] = resp;
    if (for_write) m_inject_wr[aligned] = resp;
    `uvm_info(get_type_name(), $sformatf(
              "%s: injecting error addr=0x%0h (aligned 0x%0h) resp=%s read=%0d write=%0d",
              name_tag,
              addr,
              aligned,
              resp.name(),
              for_read,
              for_write
              ), UVM_LOW)
  endfunction

  // Arm one-shot response-ID corruption (BID/RID answered as
  // request_id ^ mask, truncated to id_width; data path and response code
  // untouched). One-shot per selected direction; clear_errors() disarms.
  function void inject_id_corruption(bit [15:0] mask, bit for_read = 1'b1, bit for_write = 1'b1);
    if (mask == '0) `uvm_fatal(get_type_name(), "inject_id_corruption mask must be non-zero")
    if (for_read) m_id_corrupt_rd = mask;
    if (for_write) m_id_corrupt_wr = mask;
    `uvm_info(get_type_name(), $sformatf(
              "%s: injecting response-ID corruption mask=0x%0h read=%0d write=%0d",
              name_tag,
              mask,
              for_read,
              for_write
              ), UVM_LOW)
  endfunction

  // Consume the one-shot ID corruption for one direction, if armed.
  function bit consume_id_corruption(ocah_axi_dir_e dir, output bit [15:0] mask);
    mask = '0;
    if (dir == OCAH_AXI_DIR_READ && m_id_corrupt_rd != '0) begin
      mask = m_id_corrupt_rd;
      m_id_corrupt_rd = '0;
      return 1'b1;
    end
    if (dir == OCAH_AXI_DIR_WRITE && m_id_corrupt_wr != '0) begin
      mask = m_id_corrupt_wr;
      m_id_corrupt_wr = '0;
      return 1'b1;
    end
    return 1'b0;
  endfunction

  // Arm a one-shot missing RLAST at a beat-aligned address: the next read
  // whose AR address aligns there answers its final beat with RLAST low and
  // sends no further beat. clear_errors() disarms. AXI4 only.
  function void inject_missing_rlast(bit [63:0] addr);
    bit [63:0] aligned = beat_align(addr);
    if (protocol == OCAH_AXI_PROTO_AXI4_LITE)
      `uvm_fatal(
          get_type_name(), $sformatf(
          "%s: inject_missing_rlast needs an AXI4 responder (AXI4-Lite carries no RLAST)", name_tag
          ))
    m_missing_rlast[aligned] = 1'b1;
    `uvm_info(get_type_name(), $sformatf(
              "%s: injecting missing RLAST addr=0x%0h (aligned 0x%0h)", name_tag, addr, aligned),
              UVM_LOW)
  endfunction

  // Consume the one-shot missing RLAST for one read address, if armed.
  function bit consume_missing_rlast(bit [63:0] addr);
    bit [63:0] aligned = beat_align(addr);
    if (!m_missing_rlast.exists(aligned)) return 1'b0;
    m_missing_rlast.delete(aligned);
    return 1'b1;
  endfunction

  function void clear_errors();
    m_inject_rd.delete();
    m_inject_wr.delete();
    m_id_corrupt_rd = '0;
    m_id_corrupt_wr = '0;
    m_missing_rlast.delete();
  endfunction

  // Enable the bounded READY-stall pattern on the selected channels
  // (basename parity with the cocotb enable_backpressure API; valid
  // channel names are "aw", "w", "ar" — READY-carrying on the responder).
  function void enable_backpressure(string channels[$], int unsigned stall_cycles);
    foreach (channels[i]) begin
      case (channels[i])
        "aw": aw_stall_cycles = stall_cycles;
        "w":  w_stall_cycles  = stall_cycles;
        "ar": ar_stall_cycles = stall_cycles;
        default:
                    `uvm_fatal(get_type_name(), $sformatf(
                        "%s: unknown backpressure channel '%s' (expected aw/w/ar)",
                        name_tag, channels[i]))
      endcase
    end
    `uvm_info(get_type_name(), $sformatf(
              "%s: enabled backpressure channels=%p stall=%0d", name_tag, channels, stall_cycles),
              UVM_LOW)
  endfunction

  function void disable_backpressure();
    aw_stall_cycles = 0;
    w_stall_cycles  = 0;
    ar_stall_cycles = 0;
    `uvm_info(get_type_name(), $sformatf("%s: disabled backpressure", name_tag), UVM_LOW)
  endfunction

  function int unsigned pending_errors();
    return m_inject_rd.size() + m_inject_wr.size() + m_missing_rlast.size();
  endfunction

  // Consume the one-shot injection for one beat address, if armed.
  function ocah_axi_resp_e consume_injected(bit [63:0] addr, ocah_axi_dir_e dir, output bit armed);
    bit [63:0] aligned = beat_align(addr);
    ocah_axi_resp_e resp = OCAH_AXI_RESP_OKAY;
    armed = 1'b0;
    if (dir == OCAH_AXI_DIR_READ && m_inject_rd.exists(aligned)) begin
      resp  = m_inject_rd[aligned];
      armed = 1'b1;
      m_inject_rd.delete(aligned);
    end else if (dir == OCAH_AXI_DIR_WRITE && m_inject_wr.exists(aligned)) begin
      resp  = m_inject_wr[aligned];
      armed = 1'b1;
      m_inject_wr.delete(aligned);
    end
    return resp;
  endfunction

endclass : ocah_axi_slave_config
