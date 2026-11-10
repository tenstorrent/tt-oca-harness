// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Completed SYS_OUT writes are split by enabled byte into declared command windows.
class smc_zeroer_burst_observer extends uvm_component;
  `uvm_component_utils(smc_zeroer_burst_observer)
  uvm_analysis_imp #(ocah_axi_item, smc_zeroer_burst_observer) analysis_export;
  uvm_analysis_port #(smc_zeroer_range_sample) declaration_ap, observed_ap;
  protected smc_zeroer_range_sample commands[string], samples[string];
  protected bit interrupted[string], closed[string];
  int unsigned epoch, out_of_scope;
  protected int unsigned next_command;
  protected ocah_checker evidence;
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    evidence = ocah_checker::type_id::create("evidence");
    evidence.name_tag = "zeroer_observer";
    evidence.required_ids = '{"CHK-ZEROER-OBSERVED-OUT-OF-SCOPE", "CHK-ZEROER-OBSERVED-DELTA"};
  endfunction
  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    evidence.finalize(1);
  endfunction
  function new(string name = "smc_zeroer_burst_observer", uvm_component parent = null);
    super.new(name, parent);
    analysis_export = new("analysis_export", this);
    declaration_ap = new("declaration_ap", this);
    observed_ap = new("observed_ap", this);
  endfunction
  function int unsigned declare_command(bit [63:0] dest, int unsigned size,
                                        int unsigned phase_index, int unsigned guard_bytes);
    smc_zeroer_range_sample d = smc_zeroer_range_sample::type_id::create("declared");
    smc_zeroer_range_sample s = smc_zeroer_range_sample::type_id::create("observed");
    d.epoch = epoch;
    d.command_id = ++next_command;
    d.destination = dest;
    d.size = size;
    d.phase_index = phase_index;
    d.guard_bytes = guard_bytes;
    s.epoch = epoch;
    s.command_id = d.command_id;
    s.destination = dest;
    s.size = size;
    if (commands.exists(d.key())) `uvm_fatal(get_type_name(), "duplicate Zeroer declaration")
    commands[d.key()] = d;
    samples[d.key()] = s;
    declaration_ap.write(d);
    return d.command_id;
  endfunction
  function void on_reset(int unsigned new_epoch);
    foreach (commands[k]) begin
      if (commands[k].epoch == epoch && !closed.exists(k)) begin
        interrupted[k] = 1;
        samples.delete(k);
      end
    end
    epoch = new_epoch;
    next_command = 0;
  endfunction
  function void write(ocah_axi_item t);
    if (t.direction != OCAH_AXI_DIR_WRITE) return;
    if (t.burst != OCAH_AXI_BURST_INCR || t.size != SmcMemSize ||
        t.address % SmcMemBytes != 0 || t.data_words.size() != t.expected_beats ||
        t.strobes.size() != t.data_words.size()) begin
      `uvm_fatal(get_type_name(), "Zeroer observer requires aligned full-beat INCR bursts")
    end
    foreach (t.data_words[beat]) begin
      for (int unsigned lane = 0; lane < SmcMemBytes; lane++) begin
        bit found = 0;
        bit [63:0] addr = t.address + 64'(beat * SmcMemBytes + lane);
        if (beat >= t.strobes.size() || !t.strobes[beat][lane]) continue;
        foreach (commands[k]) begin
          smc_zeroer_range_sample d = commands[k];
          bit old_command = interrupted.exists(k);
          bit active_command = d.epoch == epoch && !closed.exists(k);
          if (old_command && addr >= d.destination - 64'(d.guard_bytes) &&
                  addr < d.destination + 64'(d.size + d.guard_bytes)) begin
            found = 1;
            break;
          end
          if (active_command && addr >= d.destination && addr < d.destination + 64'(d.size)) begin
            samples[k].bytes_by_addr[addr] = t.data_words[beat][8*lane+:8];
            samples[k].response_error |= !t.is_ok();
            found = 1;
            break;
          end
        end
        if (!found) begin
          out_of_scope++;
          void'(evidence.expect_true(
              "CHK-ZEROER-OBSERVED-OUT-OF-SCOPE", 0, $sformatf("epoch=%0d byte=%016h", epoch, addr)
          ));
        end
      end
    end
  endfunction
  function int unsigned byte_count(int unsigned id);
    string k = $sformatf("%0d:%0d", epoch, id);
    return samples.exists(k) ? samples[k].bytes_by_addr.num() : 0;
  endfunction
  function void close_command(int unsigned id);
    string k = $sformatf("%0d:%0d", epoch, id);
    bit can_close = samples.exists(k) && !closed.exists(k);
    if (!evidence.expect_true(
            "CHK-ZEROER-OBSERVED-DELTA", can_close, {"close command key=", k}
        )) begin
      `uvm_fatal(get_type_name(), "closing unknown or closed Zeroer command")
    end
    void'(evidence.expect_true(
        "CHK-ZEROER-OBSERVED-OUT-OF-SCOPE",
        out_of_scope == 0,
        $sformatf(
            "key=%s outside_bytes=%0d", k, out_of_scope)
    ));
    closed[k] = 1;
    observed_ap.write(samples[k]);
  endfunction
endclass : smc_zeroer_burst_observer
