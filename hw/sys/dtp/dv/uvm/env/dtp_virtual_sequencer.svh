// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP virtual sequencer: one typed handle per agent sequencer and one per
// responder sequence, wired by dtp_env in connect_phase, and the XTRIG CTP
// shadow (programmed CTP mode and polarity) that the cross-trigger
// sequences share across passes; the cocotb realization keeps that shadow
// on DtpEnvCfg. Scenario virtual sequences (dtp_base_test_seq family) run
// on it and start
// reusable sequences on the handle each step needs: JTAG operations on
// m_jtag_seqr, CSR AXI-Lite operations on m_xtrig_seqr, responder backdoor
// and injection through the slave sequences. In the cocotb realization the
// scenario runs on the primary-TAP JTAG sequencer and reaches the responder
// memories and the XTRIG master through the env configuration that
// dtp_base_test.plumb_scenario_seq hands it.

class dtp_virtual_sequencer extends ocah_sequencer;
  `uvm_component_utils(dtp_virtual_sequencer)

  // Agent sequencers (VIP typedefs: uvm_sequencer over the VIP item).
  ocah_jtag_master_sequencer m_jtag_seqr;
  ocah_axi_master_sequencer  m_xtrig_seqr;

  // Responder sequences: the three JTAG2AXI bridge targets and the four
  // downstream STAP TAP devices (dtp_stap_ds_name order).
  ocah_axi_slave_sequence  m_smc_otp_slave_seq;
  ocah_axi_slave_sequence  m_sep_otp_slave_seq;
  ocah_axi_slave_sequence  m_smc_axi_slave_seq;
  ocah_jtag_slave_sequence m_stap_ds_seq[DtpStapCount];
  // Programmed CTP mode/polarity, written by the XTRIG sequences and kept
  // across passes because the DUT keeps its configuration between them.
  dtp_xtrig_ctp_shadow m_xtrig_ctp_shadow;

  function new(string name = "dtp_virtual_sequencer", uvm_component parent = null);
    super.new(name, parent);
    m_xtrig_ctp_shadow = new();
  endfunction

  // Responder sequence of a JTAG2AXI bridge by target name.
  function ocah_axi_slave_sequence axi_slave_seq(string target);
    case (target)
      "smc_axi": return m_smc_axi_slave_seq;
      "sep_otp": return m_sep_otp_slave_seq;
      "smc_otp": return m_smc_otp_slave_seq;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown JTAG2AXI target `%s`", target))
        return null;
      end
    endcase
  endfunction

endclass : dtp_virtual_sequencer
