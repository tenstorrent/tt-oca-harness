// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Predicts paired FIFO contents, errors and configuration from sequential
// SEP_IN requests. No other accessor or reset with outstanding traffic is supported.
class smc_mailbox_fifo_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_mailbox_fifo_ref_model)
  typedef bit [63:0] fifo_t[$];
  smc_env_cfg cfg;
  virtual smc_tb_if tb_vif;
  protected fifo_t fifo[SmcMailboxCount][2];
  protected bit [63:0] errors[SmcMailboxCount][2];
  protected bit [63:0] irqen[SmcMailboxCount][2];
  protected bit [63:0] wirqt[SmcMailboxCount][2];
  protected bit [63:0] rirqt[SmcMailboxCount][2];
  protected bit [63:0] reset_epoch;

  function new(string name = "smc_mailbox_fifo_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || tb_vif == null)
      `uvm_fatal(get_type_name(), "env_cfg/tb_vif not set")
    reset_shadow();
    if (cfg.mailbox_fifo_scoreboard_negative)
      `uvm_info(get_type_name(), "NEGATIVE VALIDATION: mailbox predictions corrupted", UVM_LOW)
  endfunction

  protected function void reset_shadow();
    foreach (fifo[m, p]) begin
      fifo[m][p].delete();
      errors[m][p] = AXIL_MAILBOX_ERROR_REG_DEFAULT;
      irqen[m][p] = AXIL_MAILBOX_IRQEN_REG_DEFAULT;
      wirqt[m][p] = AXIL_MAILBOX_WIRQT_REG_DEFAULT;
      rirqt[m][p] = AXIL_MAILBOX_RIRQT_REG_DEFAULT;
    end
  endfunction

  function void write(ocah_axi_item t);
    bit enabled = 0;
    int unsigned m, offset, p, peer;
    bit inbound, include_data;
    bit [63:0] value = 0;
    bit [63:0] data = t.first_data();
    bit [63:0] epoch;
    ocah_axi_resp_e response = OCAH_AXI_RESP_OKAY;
    ocah_axi_item expected;
    foreach (cfg.required_features[i])
    if (cfg.required_features[i] == SmcFeatureMailboxFifo) enabled = 1;
    if (!enabled || !smc_mailbox_decode(t.address, m, inbound, offset)) return;
    if (!smc_is_mailbox_fifo_access(t))
      `uvm_fatal(get_type_name(), "mailbox_fifo excludes this address, direction or access shape")
    epoch = smc_csr_reset_epoch(tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count);
    if (epoch !== reset_epoch) begin
      reset_epoch = epoch;
      reset_shadow();
    end
    p = int'(inbound);
    peer = 1 - p;
    include_data = t.direction == OCAH_AXI_DIR_READ && offset != MBX_IRQS;
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      case (offset)
        MBX_WRITE_DATA: begin
          if (fifo[m][p].size() == SmcMailboxDepth) begin
            response = OCAH_AXI_RESP_SLVERR;
            errors[m][p] |= AXIL_MAILBOX_ERROR_WRITE_ERROR_MASK;
          end else fifo[m][p].push_back(data);
        end
        MBX_IRQEN: irqen[m][p] = data & smc_mailbox_mask(MBX_IRQEN);
        MBX_WIRQT: wirqt[m][p] = data >= SmcMailboxDepth ? SmcMailboxDepth - 1 : data;
        MBX_RIRQT: rirqt[m][p] = data >= SmcMailboxDepth ? SmcMailboxDepth - 1 : data;
        MBX_CTRL: begin
          if (data & AXIL_MAILBOX_CTRL_WFLUSH_MASK) fifo[m][p].delete();
          if (data & AXIL_MAILBOX_CTRL_RFLUSH_MASK) fifo[m][peer].delete();
        end
        MBX_IRQS: begin end
        default: `uvm_fatal(get_type_name(), "unsupported mailbox write")
      endcase
    end else begin
      case (offset)
        MBX_READ_DATA: begin
          if (fifo[m][peer].size() == 0) begin
            response = OCAH_AXI_RESP_SLVERR;
            errors[m][p] |= AXIL_MAILBOX_ERROR_READ_ERROR_MASK;
            include_data = 0;
          end else value = fifo[m][peer].pop_front();
        end
        MBX_STATUS: begin
          if (fifo[m][peer].size() == 0) value |= AXIL_MAILBOX_STATUS_EMPTY_MASK;
          if (fifo[m][p].size() == SmcMailboxDepth) value |= AXIL_MAILBOX_STATUS_FULL_MASK;
          if (fifo[m][p].size() > wirqt[m][p])
            value |= AXIL_MAILBOX_STATUS_WRITE_LEVEL_ABOVE_THRESH_MASK;
          if (fifo[m][peer].size() > rirqt[m][p])
            value |= AXIL_MAILBOX_STATUS_READ_LEVEL_ABOVE_THRESH_MASK;
        end
        MBX_ERROR: begin
          value = errors[m][p];
          errors[m][p] = AXIL_MAILBOX_ERROR_REG_DEFAULT;
        end
        MBX_IRQEN: value = irqen[m][p];
        MBX_WIRQT: value = wirqt[m][p];
        MBX_RIRQT: value = rirqt[m][p];
        MBX_CTRL: value = AXIL_MAILBOX_CTRL_REG_DEFAULT;
        MBX_IRQS: begin end
        default: `uvm_fatal(get_type_name(), "unsupported mailbox read")
      endcase
    end
    expected = ocah_axi_item::type_id::create("expected");
    expected.protocol = t.protocol;
    expected.direction = t.direction;
    expected.address = t.address;
    expected.size = t.size;
    expected.expected_beats = 1;
    expected.source = get_full_name();
    // Corruption affects emitted predictions, never the functional shadow.
    if (cfg.mailbox_fifo_scoreboard_negative) begin
      response = response == OCAH_AXI_RESP_OKAY ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_OKAY;
      if (include_data) value ^= smc_mailbox_mask(offset);
    end
    expected.resp_list.push_back(response);
    if (include_data) expected.data_words.push_back(value);
    expected_ap.write(expected);
  endfunction
endclass : smc_mailbox_fifo_ref_model
