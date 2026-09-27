// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// File: jtag_stap_tb.sv
// Description: JTAG STAP Interface Testbench
//              Tests STAP interface functionality including scan chain, 3DCR control,
//              and optional pipeline/lockup features
//              Supports both Verilator --timing mode (C++ clock) and standard simulators
//-----------------------------------------------------------------------------

module jtag_stap_tb;
  import prim_jtag_pkg::*;

  // Test parameters
  localparam bit SCAN_IN_PIPE = 0;
  localparam bit TDI_LOCKUP = 0;
  localparam bit SCAN_OUT_LOCKUP = 0;
  localparam time CLOCK_PERIOD = 10ns;  // 100MHz

  // Signals - only tck needs C++ access for clock generation
  logic                            tck /*verilator public*/;
  logic                            tms;
  logic                            trst_n;
  logic                            rst_n;

  // Client scan chain interface
  jtag_scan_ctrl_t                 client_scan_ctrl;
  logic                            client_scan_in;
  logic                            client_scan_out;

  // Client TAP control interface
  jtag_tap_ctrl_t                  client_tap_ctrl;

  // Host TAP control interface (outputs)
  jtag_tap_ctrl_t                  host_tap_ctrl;
  logic                            host_tdo_oen;
  logic                            host_tdo;

  // Host TDI input
  logic                            host_tdi;
  logic                            security_disable;

  // Test state variables
  int test_count = 0;
  int error_count = 0;
  logic test_select = 1'b0;
  logic test_shift_en = 1'b0;
  logic test_capture_en = 1'b0;
  logic test_update_en = 1'b0;

  // Create client_scan_ctrl from individual signals
  assign client_scan_ctrl.tck = tck;
  assign client_scan_ctrl.rst_n = rst_n;
  assign client_scan_ctrl.select = test_select;
  assign client_scan_ctrl.capture_en = test_capture_en;
  assign client_scan_ctrl.shift_en = test_shift_en;
  assign client_scan_ctrl.update_en = test_update_en;
  assign client_scan_ctrl.run_test_idle = 1'b0;
  assign client_scan_ctrl.test_logic_reset = 1'b0;

  // Create client_tap_ctrl from individual signals
  assign client_tap_ctrl.tck = tck;
  assign client_tap_ctrl.tms = tms;
  assign client_tap_ctrl.trst_n = trst_n;

  // DUT instantiation
  jtag_stap #(
    .SCAN_IN_PIPE(SCAN_IN_PIPE),
    .TDI_LOCKUP(TDI_LOCKUP),
    .SCAN_OUT_LOCKUP(SCAN_OUT_LOCKUP)
  ) u_dut (
    .client_scan_ctrl_i(client_scan_ctrl),
    .client_scan_in_i(client_scan_in),
    .client_scan_out_o(client_scan_out),

    .client_tap_ctrl_i(client_tap_ctrl),
    .security_disable_i(security_disable),

    .host_tap_ctrl_o(host_tap_ctrl),
    .host_tdo_oen_o(host_tdo_oen),
    .host_tdo_o(host_tdo),
    .host_tdi_i(host_tdi)
  );

`ifndef VERILATOR
  // Standard simulator - generate clock in SystemVerilog
  initial begin
    tck = 0;
    forever #(CLOCK_PERIOD / 2) tck = ~tck;
  end
`endif

  // Clock synchronization task - waits for clock edges
  task automatic advance_clock(int cycles = 1);
    // Wait for clock edges - works for both Verilator and standard simulators
    repeat (cycles) @(posedge tck);
  endtask

  // Reset task - resets the DUT to a known state
  task automatic reset_dut();
    // Assert resets
    rst_n = 1'b0;
    trst_n = 1'b0;

    // Reset test control signals
    test_select = 1'b0;
    test_shift_en = 1'b0;
    test_capture_en = 1'b0;
    test_update_en = 1'b0;

    // Reset inputs
    client_scan_in = 1'b0;
    host_tdi = 1'b0;
    tms = 1'b0;
    security_disable = 1'b0;

    // Hold reset for multiple clock cycles
    advance_clock(3);

    // Deassert resets
    rst_n = 1'b1;
    trst_n = 1'b1;

    // Wait for stabilization
    advance_clock(2);
  endtask

  // Helper function for basic test checks
  task automatic check_signal(logic actual, logic expected, string signal_name, string test_name);
    if (actual == expected) begin
      $display("PASS: %s - %s expected %0d, got %0d", test_name, signal_name, expected, actual);
    end else begin
      $display("FAIL: %s - %s expected %0d, got %0d", test_name, signal_name, expected, actual);
      error_count++;
    end
  endtask

  // Helper task to program the 3DCR register
  task automatic program_3dcr(logic tms_hold_val, logic stap_sel_val, logic config_hold_val);
    int i;

    // Enable the SIB
    test_select = 1'b1;
    test_shift_en = 1'b1;
    client_scan_in = 1'b1;
    advance_clock(1);

    // Update SIB to enable it
    test_shift_en = 1'b0;
    test_update_en = 1'b1;
    advance_clock(1);
    test_update_en = 1'b0;
    test_shift_en = 1'b1;

    // Scan in SIB disable (0) followed by 3DCR value [tms_hold, stap_sel, config_hold]
    client_scan_in = 1'b0;  // Disable SIB after this operation
    advance_clock(1);
    client_scan_in = config_hold_val;  // Bit 0
    advance_clock(1);
    client_scan_in = stap_sel_val;  // Bit 1
    advance_clock(1);
    client_scan_in = tms_hold_val;  // Bit 2
    advance_clock(1);

    // Update both SIB and 3DCR
    test_shift_en = 1'b0;
    test_update_en = 1'b1;
    advance_clock(1);
    test_update_en = 1'b0;
    test_select = 1'b0;
    advance_clock(1);
  endtask

  // Helper task to read the 3DCR register
  task automatic read_3dcr(output logic tms_hold_val, output logic stap_sel_val,
                           output logic config_hold_val);
    logic [3:0] readback;
    int i;

    // Enable the SIB
    test_select = 1'b1;
    test_shift_en = 1'b1;
    client_scan_in = 1'b1;
    advance_clock(1);

    // Update SIB to enable it
    test_shift_en = 1'b0;
    test_update_en = 1'b1;
    advance_clock(1);
    test_update_en = 1'b0;
    test_capture_en = 1'b1;
    advance_clock(1);

    // Capture both SIB and 3DCR value
    test_capture_en = 1'b0;
    test_shift_en = 1'b1;

    // Scan out SIB + 3DCR value (4 bits total: 1 SIB + 3 3DCR)
    // Scan back what we read to preserve the register values
    for (i = 0; i < 4; i++) begin
      readback[i] = client_scan_out;
      client_scan_in = client_scan_out;  // Scan back what we read
      advance_clock(1);
    end

    // Extract bits: SIB comes first, then 3DCR bits
    // readback[0] is the SIB enable bit
    config_hold_val = readback[1];  // First 3DCR bit
    stap_sel_val = readback[2];     // Second 3DCR bit
    tms_hold_val = readback[3];     // Third 3DCR bit

    // Now disable the SIB in a separate sequence without corrupting 3DCR
    // Scan in: 0 (SIB disable) + 3DCR values
    test_shift_en = 1'b1;
    client_scan_in = 1'b0;  // Disable SIB
    advance_clock(1);
    client_scan_in = config_hold_val;  // Write back 3DCR bit 0
    advance_clock(1);
    client_scan_in = stap_sel_val;  // Write back 3DCR bit 1
    advance_clock(1);
    client_scan_in = tms_hold_val;  // Write back 3DCR bit 2
    advance_clock(1);

    // Update to disable SIB with preserved 3DCR value
    test_shift_en = 1'b0;
    test_update_en = 1'b1;
    advance_clock(1);
    test_update_en = 1'b0;
    test_select = 1'b0;
    advance_clock(1);
  endtask

  // Individual test tasks
  task automatic test_reset_state();
    reset_dut();
    test_count++;
    $display("Test %0d: Reset state verification", test_count);

    // After reset, check that outputs are stable
    check_signal(host_tdo, 1'b0, "host_tdo", "Reset State");
    check_signal(host_tdo_oen, 1'b0, "host_tdo_oen", "Reset State");
    $display("INFO: host_tap_ctrl.tck = %0d", host_tap_ctrl.tck);
    $display("INFO: host_tap_ctrl.tms = %0d", host_tap_ctrl.tms);
    $display("INFO: host_tap_ctrl.trst_n = %0d", host_tap_ctrl.trst_n);
  endtask

  task automatic test_tap_ctrl_passthrough();
    reset_dut();
    test_count++;
    $display("Test %0d: TAP control signal pass-through", test_count);

    // Test that TCK passes through
    check_signal(host_tap_ctrl.tck, tck, "host_tap_ctrl.tck", "TCK Pass-through");

    // Test that TRST passes through
    check_signal(host_tap_ctrl.trst_n, trst_n, "host_tap_ctrl.trst_n", "TRST Pass-through");

    // TMS behavior depends on stap_sel and tms_hold from 3DCR
    $display("INFO: TMS input = %0d, host TMS output = %0d", tms, host_tap_ctrl.tms);
  endtask

  task automatic test_scan_chain_basic();
    logic [15:0] random_data;
    logic [15:0] captured_output;
    int i;
    reset_dut();
    test_count++;
    $display("Test %0d: Basic scan chain operation with latency check", test_count);

    // Generate random scan data (16 bits to verify latency)
    random_data = $urandom & 16'hFFFF;
    $display("INFO: Scanning random data pattern: 0x%04h", random_data);

    // Select the scan chain and enable scan mode
    test_select = 1'b1;
    test_shift_en = 1'b1;

    // Scan in the data and capture output
    // Note: SIB has 1-bit register, so there's at least 1 cycle latency
    for (i = 0; i < 16; i++) begin
      client_scan_in = random_data[i];
      advance_clock(1);
      captured_output[i] = client_scan_out;
    end

    // Shift out remaining data to flush the chain
    client_scan_in = 1'b0;
    advance_clock(4);

    // Disable scan mode and deselect chain
    test_shift_en = 1'b0;
    test_select = 1'b0;

    // Verify each bit of the scan chain output
    for (i = 0; i < 16; i++) begin
      check_signal(captured_output[i], random_data[i], $sformatf("scan_out[%0d]", i), "Scan Chain");
    end
  endtask

  task automatic test_stap_host_interface();
    logic [15:0] client_random_data;
    logic [15:0] host_random_data;
    logic [15:0] captured_tdo;
    logic [15:0] captured_scan_out;
    int i;
    reset_dut();
    test_count++;
    $display("Test %0d: STAP host interface with stap_sel enabled", test_count);

    // Program 3DCR to set stap_sel bit [1]
    $display("INFO: Programming 3DCR to enable stap_sel");
    program_3dcr(.tms_hold_val(1'b0), .stap_sel_val(1'b1), .config_hold_val(1'b0));

    // Check host_tap_ctrl_o signals with stap_sel enabled
    $display("INFO: Verifying host TAP control signals");
    check_signal(host_tap_ctrl.tck, tck, "host_tap_ctrl.tck", "Host TAP");
    check_signal(host_tap_ctrl.trst_n, trst_n, "host_tap_ctrl.trst_n", "Host TAP");
    check_signal(host_tap_ctrl.tms, tms, "host_tap_ctrl.tms", "Host TAP");

    // Drive random data on both paths simultaneously
    client_random_data = $urandom & 16'hFFFF;
    host_random_data = $urandom & 16'hFFFF;
    $display("INFO: Client scan data: 0x%04h, Host TDI data: 0x%04h", client_random_data,
             host_random_data);

    // Enable scan mode
    test_select = 1'b1;
    test_shift_en = 1'b1;

    // Scan data through both paths simultaneously
    for (i = 0; i < 16; i++) begin
      client_scan_in = client_random_data[i];
      host_tdi = host_random_data[i];
      advance_clock(1);
      captured_tdo[i] = host_tdo;
      captured_scan_out[i] = client_scan_out;
    end

    // Flush the scan chain (1 cycle for SIB since it's disabled and bypasses 3DCR)
    client_scan_in = 1'b0;
    host_tdi = 1'b0;
    advance_clock(1);

    // Disable scan mode
    test_shift_en = 1'b0;
    test_select = 1'b0;

    // Verify client_scan_in -> host_tdo path
    $display("INFO: Verifying client scan input to host TDO path");
    for (i = 0; i < 16; i++) begin
      check_signal(captured_tdo[i], client_random_data[i], $sformatf("host_tdo[%0d]", i),
                   "Client->TDO");
    end

    // Verify host_tdi -> client_scan_out path
    // Capturing after the clock edge absorbs the 1-cycle latency
    $display("INFO: Verifying host TDI to client scan output path");
    for (i = 0; i < 16; i++) begin
      check_signal(captured_scan_out[i], host_random_data[i], $sformatf("scan_out[%0d]", i),
                   "TDI->Client");
    end
  endtask

  task automatic test_tms_output_modes();
    reset_dut();
    test_count++;
    $display("Test %0d: TMS output modes with stap_sel and tms_hold combinations", test_count);

    // Test Case 1: stap_sel=0, tms_hold=0 → host TMS should be 0 regardless of client TMS
    $display("INFO: Test Case 1 - stap_sel=0, tms_hold=0");
    program_3dcr(.tms_hold_val(1'b0), .stap_sel_val(1'b0), .config_hold_val(1'b0));

    tms = 1'b0;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b0, "host_tms", "stap_sel=0, tms_hold=0, client_tms=0");

    tms = 1'b1;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b0, "host_tms", "stap_sel=0, tms_hold=0, client_tms=1");

    // Test Case 2: stap_sel=0, tms_hold=1 → host TMS should be 1 regardless of client TMS
    $display("INFO: Test Case 2 - stap_sel=0, tms_hold=1");
    program_3dcr(.tms_hold_val(1'b1), .stap_sel_val(1'b0), .config_hold_val(1'b0));

    tms = 1'b0;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b1, "host_tms", "stap_sel=0, tms_hold=1, client_tms=0");

    tms = 1'b1;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b1, "host_tms", "stap_sel=0, tms_hold=1, client_tms=1");

    // Test Case 3: stap_sel=1, tms_hold=0 → host TMS should follow client TMS
    $display("INFO: Test Case 3 - stap_sel=1, tms_hold=0");
    program_3dcr(.tms_hold_val(1'b0), .stap_sel_val(1'b1), .config_hold_val(1'b0));

    tms = 1'b0;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b0, "host_tms", "stap_sel=1, tms_hold=0, client_tms=0");

    tms = 1'b1;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b1, "host_tms", "stap_sel=1, tms_hold=0, client_tms=1");

    // Test Case 4: stap_sel=1, tms_hold=1 → host TMS should follow client TMS (tms_hold ignored)
    $display("INFO: Test Case 4 - stap_sel=1, tms_hold=1");
    program_3dcr(.tms_hold_val(1'b1), .stap_sel_val(1'b1), .config_hold_val(1'b0));

    tms = 1'b0;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b0, "host_tms", "stap_sel=1, tms_hold=1, client_tms=0");

    tms = 1'b1;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b1, "host_tms", "stap_sel=1, tms_hold=1, client_tms=1");

    // Reset TMS to 0
    tms = 1'b0;
    advance_clock(1);
  endtask

  task automatic test_config_hold();
    logic tms_hold_read, stap_sel_read, config_hold_read;
    reset_dut();
    test_count++;
    $display("Test %0d: Config hold functionality", test_count);

    // Test Case 1: config_hold=1 should preserve 3DCR during scan reset (TLR)
    $display("INFO: Test Case 1 - config_hold=1 preserves 3DCR during scan reset");

    // Program 3DCR with config_hold=1, stap_sel=0, tms_hold=1
    // Note: stap_sel=0 so scan data comes from client_scan_in, not host_tdi
    program_3dcr(.tms_hold_val(1'b1), .stap_sel_val(1'b0), .config_hold_val(1'b1));

    // Verify the values were programmed correctly
    read_3dcr(tms_hold_read, stap_sel_read, config_hold_read);
    check_signal(config_hold_read, 1'b1, "config_hold", "After programming");
    check_signal(stap_sel_read, 1'b0, "stap_sel", "After programming");
    check_signal(tms_hold_read, 1'b1, "tms_hold", "After programming");

    // Assert scan reset (simulating TLR transition)
    $display("INFO: Asserting scan reset (simulating TLR)");
    rst_n = 1'b0;
    advance_clock(3);
    rst_n = 1'b1;
    advance_clock(2);

    // Read back 3DCR and verify it maintained its values
    $display("INFO: Reading back 3DCR after scan reset");
    read_3dcr(tms_hold_read, stap_sel_read, config_hold_read);
    check_signal(config_hold_read, 1'b1, "config_hold", "After scan reset with config_hold=1");
    check_signal(stap_sel_read, 1'b0, "stap_sel", "After scan reset with config_hold=1");
    check_signal(tms_hold_read, 1'b1, "tms_hold", "After scan reset with config_hold=1");

    // Test Case 2: config_hold=0 should reset 3DCR during scan reset (TLR)
    $display("INFO: Test Case 2 - config_hold=0 allows 3DCR reset during scan reset");

    // Program 3DCR with config_hold=0, stap_sel=0, tms_hold=1
    program_3dcr(.tms_hold_val(1'b1), .stap_sel_val(1'b0), .config_hold_val(1'b0));

    // Verify the values were programmed correctly
    read_3dcr(tms_hold_read, stap_sel_read, config_hold_read);
    check_signal(config_hold_read, 1'b0, "config_hold", "After programming");
    check_signal(stap_sel_read, 1'b0, "stap_sel", "After programming");
    check_signal(tms_hold_read, 1'b1, "tms_hold", "After programming");

    // Assert scan reset (simulating TLR transition)
    $display("INFO: Asserting scan reset (simulating TLR)");
    rst_n = 1'b0;
    advance_clock(3);
    rst_n = 1'b1;
    advance_clock(2);

    // Read back 3DCR and verify it was reset to all zeros
    $display("INFO: Reading back 3DCR after scan reset");
    read_3dcr(tms_hold_read, stap_sel_read, config_hold_read);
    check_signal(config_hold_read, 1'b0, "config_hold", "After scan reset with config_hold=0");
    check_signal(stap_sel_read, 1'b0, "stap_sel", "After scan reset with config_hold=0");
    check_signal(tms_hold_read, 1'b0, "tms_hold", "After scan reset with config_hold=0");

    // Test Case 3: TRST should reset 3DCR regardless of config_hold
    $display("INFO: Test Case 3 - TRST resets 3DCR regardless of config_hold");

    // Program 3DCR with config_hold=1, stap_sel=0, tms_hold=1
    program_3dcr(.tms_hold_val(1'b1), .stap_sel_val(1'b0), .config_hold_val(1'b1));

    // Verify the values were programmed correctly
    read_3dcr(tms_hold_read, stap_sel_read, config_hold_read);
    check_signal(config_hold_read, 1'b1, "config_hold", "After programming");
    check_signal(stap_sel_read, 1'b0, "stap_sel", "After programming");
    check_signal(tms_hold_read, 1'b1, "tms_hold", "After programming");

    // Assert TRST
    $display("INFO: Asserting TRST");
    trst_n = 1'b0;
    advance_clock(3);
    trst_n = 1'b1;
    advance_clock(2);

    // Read back 3DCR and verify it was reset to all zeros
    $display("INFO: Reading back 3DCR after TRST");
    read_3dcr(tms_hold_read, stap_sel_read, config_hold_read);
    check_signal(config_hold_read, 1'b0, "config_hold", "After TRST with config_hold=1");
    check_signal(stap_sel_read, 1'b0, "stap_sel", "After TRST with config_hold=1");
    check_signal(tms_hold_read, 1'b0, "tms_hold", "After TRST with config_hold=1");
  endtask

  task automatic test_security_disable();
    logic tms_hold_read, stap_sel_read, config_hold_read;
    reset_dut();
    test_count++;
    $display("Test %0d: Security disable functionality", test_count);

    // Program the 3DCR while enabled so the disabled state has
    // a non-default hold configuration to preserve.
    program_3dcr(.tms_hold_val(1'b1), .stap_sel_val(1'b1), .config_hold_val(1'b1));
    tms = 1'b0;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b0, "host_tms", "Security Disable setup");
    check_signal(host_tdo_oen, 1'b0, "host_tdo_oen", "Security Disable setup");

    // Assert security disable and verify that the host port is blocked
    // while the 3DCR state still provides the hold value.
    security_disable = 1'b1;
    tms = 1'b0;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b1, "host_tms", "Security Disable host hold state");
    check_signal(host_tdo_oen, 1'b0, "host_tdo_oen", "Security Disable host blocked");
    check_signal(host_tdo, 1'b0, "host_tdo", "Security Disable host clamped");

    // Readback should still be accessible through the 3DCR path, with the
    // captured stap_sel value forced low while disabled.
    read_3dcr(tms_hold_read, stap_sel_read, config_hold_read);
    check_signal(config_hold_read, 1'b1, "config_hold", "Security Disable readback");
    check_signal(stap_sel_read, 1'b0, "stap_sel", "Security Disable readback");
    check_signal(tms_hold_read, 1'b1, "tms_hold", "Security Disable readback");

    // Writes while disabled should not update the stored 3DCR state.
    program_3dcr(.tms_hold_val(1'b0), .stap_sel_val(1'b0), .config_hold_val(1'b0));
    read_3dcr(tms_hold_read, stap_sel_read, config_hold_read);
    check_signal(config_hold_read, 1'b1, "config_hold", "Security Disable blocked update");
    check_signal(stap_sel_read, 1'b0, "stap_sel", "Security Disable blocked update");
    check_signal(tms_hold_read, 1'b1, "tms_hold", "Security Disable blocked update");

    // Re-enable the host port and confirm the original STAP host behavior returns.
    security_disable = 1'b0;
    test_select = 1'b1;
    test_shift_en = 1'b1;
    tms = 1'b1;
    advance_clock(1);
    check_signal(host_tap_ctrl.tms, 1'b1, "host_tms", "Security Disable release");
    check_signal(host_tdo_oen, 1'b1, "host_tdo_oen", "Security Disable release");
    test_shift_en = 1'b0;
    test_select = 1'b0;
  endtask

  // Test initialization phase
  task automatic initialize_testbench();
    $display("=== JTAG STAP Interface Test ===");

    // Initialize signals
    tck = 0;
    tms = 1;        // Start in Test-Logic-Reset
    trst_n = 0;     // Hold in reset initially
    rst_n = 0;      // Hold scan reset

    client_scan_in = 0;
    host_tdi = 0;
    security_disable = 0;
  endtask

  // Reset sequence phase
  task automatic reset_sequence();
    // Hold reset for a few cycles
    advance_clock(4);

    // Release resets
    trst_n = 1;
    rst_n = 1;

    // Wait for reset to propagate
    advance_clock(3);
  endtask

  // Execute all tests phase
  task automatic execute_tests();
    test_reset_state();
    test_tap_ctrl_passthrough();
    test_scan_chain_basic();
    test_stap_host_interface();
    test_tms_output_modes();
    test_config_hold();
    test_security_disable();
  endtask

  // Test summary and finish phase
  task automatic finalize_testbench();
    // Test summary
    $display("\n=== TEST SUMMARY ===");
    $display("Tests Run: %0d", test_count);
    $display("Tests Failed: %0d", error_count);
    $display("Tests Passed: %0d", test_count - error_count);

    if (error_count == 0) begin
      $display("*** ALL TESTS PASSED ***");
      $display("=== JTAG STAP Test Complete ===");

      // Wait a few more cycles before finishing
      advance_clock(2);

      $finish;
    end else begin
      $display("*** %0d TESTS FAILED ***", error_count);
      $display("=== JTAG STAP Test FAILED ===");

      // Wait a few more cycles before finishing
      advance_clock(2);

      // Force error exit code
      $fatal(1, "Test failures detected - see above for details");
    end
  endtask

  // Timeout watchdog - separate initial block
  initial begin
    #10us;  // 10 microsecond timeout
    $error("Test timeout reached - forcing finish");
    $fatal(1, "Test timeout - terminating simulation");
  end

  // Main test sequence - orchestrates all phases
  initial begin
    initialize_testbench();
    reset_sequence();
    execute_tests();
    finalize_testbench();
  end

endmodule : jtag_stap_tb
