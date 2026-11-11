// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Full-width sequential command programming; no other Zeroer CSR writer.
class smc_zeroer_range_ref_model extends ocah_ref_model #(ocah_axi_item, smc_zeroer_range_sample);
  `uvm_component_utils(smc_zeroer_range_ref_model)
  smc_env_cfg cfg;
  virtual smc_tb_if tb_vif;
  protected bit [63:0] destination, size_bytes;
  protected time previous_end;
  protected bit [63:0] epoch;
  protected int unsigned command_id;
  // Per-command allocation bound of this predictor.
  localparam int unsigned MaxPredictedBytes = 64 * 1024;
  protected bit negative_used, negative_armed;
  function new(string name = "smc_zeroer_range_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg))
      `uvm_fatal(get_type_name(), "env_cfg not set")
  endfunction
  function bit [63:0] current_epoch();
    sync_reset();
    return epoch;
  endfunction
  function void arm_recovery_negative();
    negative_armed = 1;
  endfunction
  protected function void sync_reset();
    bit [63:0] new_epoch = smc_csr_reset_epoch(
        tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count
    );
    if (new_epoch == epoch) return;
    destination = ZEROER_CTRL_DEST_ADDR_REG_DEFAULT;
    size_bytes = ZEROER_CTRL_SIZE_REG_DEFAULT;
    epoch = new_epoch;
    command_id = 0;
    previous_end = 0;
  endfunction
  function void write(ocah_axi_item t);
    smc_zeroer_range_sample expected;
    sync_reset();
    if (t.direction != OCAH_AXI_DIR_WRITE ||
        !(t.address inside {SmcZeroerDestAddr, SmcZeroerSizeAddr, SmcZeroerCtrlStatusAddr}))
      return;
    if (!t.is_ok()) return;
    if (t.size != SmcMemSize || t.data_words.size() != 1 ||
        t.strobes.size() != 1 || t.strobes[0] != 8'hFF || t.start_time < previous_end)
      `uvm_fatal(get_type_name(), "Zeroer predictor excludes narrow or overlapping writes")
    previous_end = t.end_time;
    if (t.address == SmcZeroerDestAddr) begin
      destination = t.data_words[0];
      if (destination[63:56] != 0)
        `uvm_fatal(get_type_name(), "Zeroer predictor excludes addresses above 56 bits")
    end else if (t.address == SmcZeroerSizeAddr) begin
      size_bytes = t.data_words[0];
    end else if (size_bytes != 0) begin
      if (size_bytes > MaxPredictedBytes || destination >= cfg.sys_out_mem_bytes ||
          size_bytes > cfg.sys_out_mem_bytes - destination)
        `uvm_fatal(get_type_name(), "Zeroer predictor exceeds allocation bound or responder window")
      expected = smc_zeroer_range_sample::type_id::create("expected");
      expected.epoch = epoch;
      expected.command_id = ++command_id;
      expected.destination = destination;
      expected.size = int'(size_bytes);
      for (int unsigned i = 0; i < expected.size; i++) begin
        expected.bytes_by_addr[destination+64'(i)] = 0;
      end
      if (cfg.zeroer_range_scoreboard_negative && negative_armed && !negative_used) begin
        expected.bytes_by_addr[destination] = 1;
        negative_used = 1;
        `uvm_info(get_type_name(), {"NEGATIVE VALIDATION: corrupt recovery byte ",
                                    expected.convert2string()}, UVM_LOW)
      end
      expected_ap.write(expected);
    end
  endfunction
endclass : smc_zeroer_range_ref_model
