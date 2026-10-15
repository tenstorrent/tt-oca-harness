// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag2axi_sep_otp_axi_error_series_incr_write_with_status_test — 3-beat
// incrementing series write through the WITH_ERROR_STATUS TDR with the fault
// armed on the middle beat. The per-beat status/increment MSB rides every
// shift, the injected response must be classified as EXPECTED
// (CHK-AXI-ERR-INJ), and a SINGLE_OP recovery write lands (CHK-AXI-WMEM
// against the stimulus intent).

class dtp_jtag2axi_sep_otp_axi_error_series_incr_write_with_status_test extends dtp_base_test;
  `uvm_component_utils(dtp_jtag2axi_sep_otp_axi_error_series_incr_write_with_status_test)

  function new(string name = "dtp_jtag2axi_sep_otp_axi_error_series_incr_write_with_status_test",
               uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void configure_test_cfg(dtp_test_cfg cfg);
    super.configure_test_cfg(cfg);
    cfg.require_axi_ids("sep_otp",
                        '{
                            "CHK-AXI-RESP",
                            "CHK-AXI-ERR-INJ",
                            "CHK-AXI-STRB",
                            "CHK-AXI-WADDR",
                            "CHK-AXI-WDATA",
                            "CHK-AXI-WMEM",
                            "CHK-AXI-COMPLETION",
                            "CHK-AXI-NONVAC",
                            "CHK-J2A-BUS-REQ",
                            "CHK-J2A-FAULT-STATUS",
                            "CHK-J2A-SERIES-ADDR",
                            "CHK-J2A-STATUS-BIT"
                        });
  endfunction

  virtual function ocah_sequence create_scenario_seq();
    dtp_jtag2axi_error_test_seq seq = dtp_jtag2axi_error_test_seq::type_id::create(
        "sep_otp_error_series_incr_write_with_status_seq"
    );
    seq.target_name = "sep_otp";
    seq.scenario    = "error_series_incr_write_with_status";
    return seq;
  endfunction

  virtual function string specific_loops_knob();
    return "DTP_JTAG2AXI_SEP_OTP_AXI_ERROR_SERIES_INCR_WRITE_WITH_STATUS_TEST_LOOPS";
  endfunction

  virtual function string group_loops_knob();
    return "DTP_JTAG2AXI_TEST_LOOPS";
  endfunction

endclass : dtp_jtag2axi_sep_otp_axi_error_series_incr_write_with_status_test
