// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Completed SYS_OUT writes are split by enabled byte into declared command windows.
class smc_zeroer_burst_observer extends ocah_subscriber #(ocah_axi_item);
  `uvm_component_utils(smc_zeroer_burst_observer)
  virtual smc_tb_if tb_vif;
  uvm_analysis_port #(smc_zeroer_range_sample) declaration_ap, observed_ap, status_ap;
  protected smc_zeroer_range_sample commands[string], samples[string];
  protected bit interrupted[string], closed[string];
  protected bit [63:0] epoch;
  protected int unsigned out_of_scope, next_command;
  protected int unsigned completed[string], old_bursts[2], old_bytes[2];

  function new(string name = "smc_zeroer_burst_observer", uvm_component parent = null);
    super.new(name, parent);
    declaration_ap = new("declaration_ap", this);
    observed_ap = new("observed_ap", this);
    status_ap = new("status_ap", this);
  endfunction

  protected function void sync_reset();
    bit [63:0] new_epoch = smc_csr_reset_epoch(
        tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count
    );
    if (new_epoch == epoch) return;
    foreach (commands[k]) begin
      if (commands[k].epoch == epoch && !closed.exists(k)) begin
        interrupted[k] = 1;
        samples.delete(k);
      end
    end
    epoch = new_epoch;
    next_command = 0;
  endfunction

  function bit [63:0] current_epoch();
    sync_reset();
    return epoch;
  endfunction

  function int unsigned outside_count();
    return out_of_scope;
  endfunction

  function int unsigned old_completed_count(bit phase_index);
    sync_reset();
    return old_bursts[phase_index];
  endfunction

  function int unsigned old_byte_count(bit phase_index);
    sync_reset();
    return old_bytes[phase_index];
  endfunction

  function int unsigned completed_count(int unsigned id);
    string k;
    sync_reset();
    k = $sformatf("%0d:%0d", epoch, id);
    return completed.exists(k) ? completed[k] : 0;
  endfunction

  function int unsigned declare_command(bit [63:0] dest, int unsigned size,
                                        int unsigned phase_index, int unsigned guard_bytes);
    smc_zeroer_range_sample d = smc_zeroer_range_sample::type_id::create("declared");
    smc_zeroer_range_sample s = smc_zeroer_range_sample::type_id::create("observed");
    sync_reset();
    d.epoch = epoch;
    d.command_id = ++next_command;
    d.destination = dest;
    d.size = size;
    d.phase_index = phase_index;
    d.guard_bytes = guard_bytes;
    s.copy(d);
    if (commands.exists(d.key()))
      `uvm_fatal(get_type_name(), {"duplicate Zeroer declaration key=", d.key()})
    commands[d.key()] = d;
    samples[d.key()] = s;
    declaration_ap.write(d);
    return d.command_id;
  endfunction

  virtual function void write(ocah_axi_item t);
    smc_zeroer_range_sample status = smc_zeroer_range_sample::type_id::create("burst_status");
    sync_reset();
    if (t.direction != OCAH_AXI_DIR_WRITE) return;
    status.epoch = epoch;
    status.detail = t.convert2string();
    if (t.burst != OCAH_AXI_BURST_INCR || t.size != SmcMemSize ||
        t.address % SmcMemBytes != 0 || t.data_words.size() != t.expected_beats ||
        t.strobes.size() != t.data_words.size()) begin
      status.shape_errors = 1;
      status_ap.write(status);
      return;
    end
    foreach (commands[k]) begin
      smc_zeroer_range_sample d = commands[k];
      bit old_command = interrupted.exists(k);
      bit active = d.epoch == epoch && !closed.exists(k);
      if (t.address < d.destination + 64'(d.size) &&
          t.address + 64'(t.data_words.size() * SmcMemBytes) > d.destination) begin
        if (old_command) old_bursts[d.phase_index]++;
        else if (active) completed[k]++;
      end
    end
    foreach (t.data_words[beat]) begin
      for (int unsigned lane = 0; lane < SmcMemBytes; lane++) begin
        bit found = 0;
        bit [63:0] addr = t.address + 64'(beat * SmcMemBytes + lane);
        if (!t.strobes[beat][lane]) continue;
        foreach (commands[k]) begin
          smc_zeroer_range_sample d = commands[k];
          bit old_command = interrupted.exists(k);
          bit active = d.epoch == epoch && !closed.exists(k);
          if (old_command && addr >= d.destination - 64'(d.guard_bytes) &&
              addr < d.destination + 64'(d.size + d.guard_bytes)) begin
            old_bytes[d.phase_index]++;
            found = 1;
            break;
          end
          if (active && addr >= d.destination && addr < d.destination + 64'(d.size)) begin
            samples[k].bytes_by_addr[addr] = t.data_words[beat][8*lane+:8];
            samples[k].response_error |= !t.is_ok();
            found = 1;
            break;
          end
        end
        if (!found) begin
          out_of_scope++;
          status.outside_bytes++;
        end
      end
    end
    status_ap.write(status);
  endfunction

  function int unsigned byte_count(int unsigned id);
    string k;
    sync_reset();
    k = $sformatf("%0d:%0d", epoch, id);
    return samples.exists(k) ? samples[k].bytes_by_addr.num() : 0;
  endfunction

  function void close_command(int unsigned id);
    string k;
    smc_zeroer_range_sample status = smc_zeroer_range_sample::type_id::create("close_status");
    sync_reset();
    k = $sformatf("%0d:%0d", epoch, id);
    status.closing = 1;
    status.close_valid = samples.exists(k) && !closed.exists(k);
    status.detail = {"close command key=", k};
    status_ap.write(status);
    if (!status.close_valid)
      `uvm_fatal(get_type_name(), {"closing unknown or closed Zeroer command key=", k})
    closed[k] = 1;
    observed_ap.write(samples[k]);
  endfunction
endclass : smc_zeroer_burst_observer
