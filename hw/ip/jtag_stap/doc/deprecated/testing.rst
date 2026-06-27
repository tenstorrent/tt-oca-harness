Testing
=======

The JTAG STAP Interface IP includes a comprehensive test infrastructure for verification and validation.

Test Infrastructure
-------------------

Overview
~~~~~~~~

The test infrastructure consists of:

* SystemVerilog testbench with modular test tasks
* Verilator C++ driver for clock generation
* Shared utility functions for common operations
* Makefile for automated build and execution
* Comprehensive smoke tests for core functionality

File Organization
~~~~~~~~~~~~~~~~~

Test files are located in ``tb/`` directory:

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - File
     - Description
   * - ``jtag_stap_tb.sv``
     - SystemVerilog testbench with test logic
   * - ``test_jtag_stap_tb.cpp``
     - C++ driver for Verilator
   * - ``jtag_test_utils.h``
     - Shared utility functions
   * - ``Makefile``
     - Build and run system
   * - ``../config/jtag_stap_test.f``
     - File list for compilation

Test Environment
----------------

Prerequisites
~~~~~~~~~~~~~

* Verilator 5.036 or later
* GCC 13.2.1 or later
* Make build system

The required modules are loaded automatically by the Makefile.

Running Tests
~~~~~~~~~~~~~

From the ``tb/`` directory:

.. code-block:: bash

   # Show help (default target)
   make
   
   # Run all tests (clean, build, and execute)
   make all
   
   # Run tests without cleaning
   make stap-test
   
   # Run tests (alias)
   make run
   
   # Clean build artifacts
   make clean

Test Output
~~~~~~~~~~~

Test results are displayed on stdout with PASS/FAIL status:

.. code-block:: text

   === JTAG STAP Interface Test ===
   Test 1: Reset state verification
   PASS: Reset State - host_tdo expected 0, got 0
   PASS: Reset State - host_tdo_oen expected 0, got 0
   ...
   === TEST SUMMARY ===
   Tests Run: 6
   Tests Failed: 0
   Tests Passed: 6
   *** ALL TESTS PASSED ***

Waveforms are generated in ``jtag_stap_tb.vcd`` for debugging.

Smoke Tests
-----------

The testbench includes 6 comprehensive smoke tests covering core functionality:

Test 1: Reset State Verification
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Purpose**: Verify outputs are stable after reset

**Checks**:

* ``host_tdo_o`` is 0 after reset
* ``host_tdo_oen_o`` is 0 after reset
* TAP control signals are stable

**Expected Behavior**: All outputs in known safe state

Test 2: TAP Control Pass-through
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Purpose**: Check TCK, TMS, TRST propagation to host

**Checks**:

* ``host_tap_ctrl_o.tck`` equals input ``tck``
* ``host_tap_ctrl_o.trst_n`` equals input ``trst_n``
* TMS behavior observed (depends on stap_sel)

**Expected Behavior**: Clock and reset pass through directly

Test 3: Basic Scan Chain Operation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Purpose**: Test scan data propagation and verify latency

**Procedure**:

1. Generate random 16-bit scan data
2. Enable scan mode (``select=1``, ``scan_en=1``)
3. Scan data bit-by-bit through the chain
4. Capture output data
5. Verify each bit matches input using ``check_signal``

**Expected Behavior**: 

* Data propagates with 1-cycle latency through SIB
* Output bits match input bits exactly
* All 16 bits verified individually

**Key Features**:

* Uses random data for comprehensive testing
* Bit-by-bit verification with clear pass/fail reporting
* Tests SIB scan register functionality

Test 4: STAP Host Interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Purpose**: Verify bidirectional data flow with ``stap_sel`` enabled

**Procedure**:

1. Program 3DCR to enable ``stap_sel`` (using ``program_3dcr`` helper)
2. Disable SIB after programming
3. Verify ``host_tap_ctrl_o`` signals match inputs
4. Drive random data simultaneously on:

   * ``client_scan_in`` → verify appears on ``host_tdo``
   * ``host_tdi`` → verify appears on ``client_scan_out``

5. Capture and verify all 16 bits on both paths

**Expected Behavior**: 

* Bidirectional data flow works correctly
* Client-to-TDO path has no additional latency (lockup latch timing)
* TDI-to-client path has 1-cycle latency (SIB register)
* All bits verified with ``check_signal``

**Key Features**:

* Tests STAP active mode (``stap_sel=1``)
* Verifies simultaneous bidirectional data flow
* Uses ``program_3dcr`` helper for 3DCR access
* Random data for comprehensive testing

Test 5: TMS Output Modes
~~~~~~~~~~~~~~~~~~~~~~~~~

**Purpose**: Verify TMS output behavior with all ``stap_sel`` and ``tms_hold`` combinations

**Procedure**:

For each test case:

1. Program 3DCR with specific ``stap_sel`` and ``tms_hold`` values
2. Apply client TMS values (0 and 1)
3. Verify ``host_tap_ctrl_o.tms`` output using ``check_signal``

**Test Cases**:

* **Case 1**: ``stap_sel=0, tms_hold=0`` → host TMS = 0 (held at 0)
* **Case 2**: ``stap_sel=0, tms_hold=1`` → host TMS = 1 (held at 1)
* **Case 3**: ``stap_sel=1, tms_hold=0`` → host TMS follows client TMS
* **Case 4**: ``stap_sel=1, tms_hold=1`` → host TMS follows client TMS (``tms_hold`` ignored)

**Expected Behavior**: 

* When ``stap_sel=0``: TMS output equals ``tms_hold`` value
* When ``stap_sel=1``: TMS output follows client TMS input
* All combinations tested with both TMS input values

**Key Features**:

* Comprehensive coverage of TMS control logic
* Uses ``program_3dcr`` helper for register access
* Tests both STAP active and inactive modes

Test 6: Config Hold Functionality
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Purpose**: Verify 3DCR register persistence controlled by ``config_hold`` bit

**Procedure**:

**Test Case 1** - ``config_hold=1`` preserves 3DCR during scan reset:

1. Program 3DCR: ``config_hold=1, stap_sel=0, tms_hold=1``
2. Read back and verify values (using ``read_3dcr`` helper)
3. Assert scan reset (``rst_n=0``) to simulate TLR transition
4. Read back and verify values are preserved

**Test Case 2** - ``config_hold=0`` allows 3DCR reset during scan reset:

1. Program 3DCR: ``config_hold=0, stap_sel=0, tms_hold=1``
2. Read back and verify values
3. Assert scan reset (``rst_n=0``) to simulate TLR transition
4. Read back and verify values are reset to 0

**Test Case 3** - TRST resets 3DCR regardless of ``config_hold``:

1. Program 3DCR: ``config_hold=1, stap_sel=0, tms_hold=1``
2. Read back and verify values
3. Assert TRST (``trst_n=0``)
4. Read back and verify all values are reset to 0

**Expected Behavior**: 

* ``config_hold=1``: 3DCR preserves values during scan reset (TLR)
* ``config_hold=0``: 3DCR resets during scan reset (TLR)
* TRST always resets 3DCR regardless of ``config_hold``

**Key Features**:

* Tests critical configuration persistence functionality
* Uses helper functions: ``program_3dcr`` and ``read_3dcr``
* Verifies proper reset hierarchy (TRST vs scan reset)
* Reads back register values non-destructively
* Tests all three 3DCR bits for each scenario

**Implementation Notes**:

* ``read_3dcr`` scans out current values while scanning them back in to preserve register state
* SIB is enabled temporarily to access 3DCR, then disabled after operation
* Scan chain order: SIB bit first, then 3DCR bits (config_hold, stap_sel, tms_hold)
* All tests use ``stap_sel=0`` to ensure scan data comes from ``client_scan_in``

Helper Functions
----------------

The testbench includes reusable helper functions for common operations:

``reset_dut()``
~~~~~~~~~~~~~~~

**Purpose**: Initialize DUT to a known state before each test

**Operations**:

* Asserts both ``rst_n`` and ``trst_n``
* Resets all test control signals (``test_select``, ``test_scan_en``, etc.)
* Holds reset for 3 clock cycles
* Deasserts resets and waits 2 cycles for stabilization

**Usage**: Called at the beginning of every test task

``check_signal()``
~~~~~~~~~~~~~~~~~~

**Purpose**: Verify a signal value and report pass/fail

**Parameters**:

* ``actual``: Signal value read from DUT
* ``expected``: Expected value
* ``signal_name``: Name for reporting
* ``test_name``: Context description

**Output**: Displays "PASS" or "FAIL" with expected and actual values

**Usage**: Used throughout tests for verification

``program_3dcr()``
~~~~~~~~~~~~~~~~~~

**Purpose**: Write values to the 3DCR register through SIB

**Parameters**:

* ``tms_hold_val``: TMS hold bit value
* ``stap_sel_val``: STAP select bit value  
* ``config_hold_val``: Configuration hold bit value

**Procedure**:

1. Enable SIB (scan and update 1 into SIB register)
2. Scan in 3DCR data (3 bits) plus SIB disable bit (0)
3. Update to program 3DCR and disable SIB
4. Deselect scan chain

**Usage**: Used by tests that need to configure STAP mode

``read_3dcr()``
~~~~~~~~~~~~~~~

**Purpose**: Read current 3DCR register values non-destructively

**Parameters** (output):

* ``tms_hold_val``: TMS hold bit value
* ``stap_sel_val``: STAP select bit value
* ``config_hold_val``: Configuration hold bit value

**Procedure**:

1. Enable SIB (scan and update 1 into SIB register)
2. Capture current SIB and 3DCR values
3. Scan out 4 bits while scanning them back in (preservation)
4. Extract 3DCR bits from readback (bits [3:1], bit [0] is SIB)
5. Re-scan with SIB disable (0) plus preserved 3DCR values
6. Update and deselect

**Key Feature**: Preserves register values during readout by scanning back what is read

**Usage**: Used by config_hold test to verify register contents

Debugging
---------

Waveform Analysis
~~~~~~~~~~~~~~~~~

View waveforms using GTKWave or similar VCD viewer:

.. code-block:: bash

   gtkwave jtag_stap_tb.vcd

Key signals to observe:

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Signal Path
     - Description
   * - ``client_scan_in``
     - Scan chain input data
   * - ``client_scan_out``
     - Scan chain output data
   * - ``host_tdo``
     - TDO output to host
   * - ``host_tdi``
     - TDI input from host
   * - ``host_tap_ctrl.*``
     - TAP control signals
   * - ``host_tdo_oen``
     - TDO output enable
   * - ``dut.stap_sel``
     - STAP selection (internal)
   * - ``dut.tms_hold``
     - TMS hold value (internal)
   * - ``dut.config_hold``
     - Config hold (internal)

Internal Signal Access
~~~~~~~~~~~~~~~~~~~~~~

The testbench provides access to internal DUT signals:

* ``dut.stap_scan_in`` - Scan input after optional pipeline
* ``dut.sib_client_scan_in`` - Input to SIB mux
* ``dut.host_sib_scan_ctrl`` - SIB host scan control
* ``dut.client_reg_scan_ctrl`` - 3DCR register scan control

Common Issues
~~~~~~~~~~~~~

**Issue**: Scan data not propagating

**Check**:

* ``client_scan_ctrl_i.select`` is high
* ``client_scan_ctrl_i.scan_en`` is toggling
* Clock is running

**Issue**: TDO always zero

**Check**:

* ``host_tdo_oen_o`` is high when expected
* ``stap_sel`` bit is set correctly
* Scan chain has valid data

**Issue**: TMS not changing

**Check**:

* ``stap_sel`` value in 3DCR register
* ``tms_hold`` value in 3DCR register
* TAP control input signals

Test Configuration
------------------

Testbench Parameters
~~~~~~~~~~~~~~~~~~~~

The testbench can be configured via parameters in ``jtag_stap_tb.sv``:

.. code-block:: systemverilog

   localparam bit  SCAN_IN_PIPE = 0;
   localparam bit  TDI_LOCKUP = 0;
   localparam bit  SCAN_OUT_LOCKUP = 0;
   localparam time CLOCK_PERIOD = 10ns;  // 100MHz

Modify these values to test different configurations:

* Enable pipeline stages for timing testing
* Change clock period for performance analysis
* Test various feature combinations

Timeout Settings
~~~~~~~~~~~~~~~~

Test timeout is set to 10 microseconds to catch infinite loops:

.. code-block:: systemverilog

   initial begin
       #10us;
       $error("Test timeout reached - forcing finish");
       $finish;
   end

Increase timeout for slower clock frequencies or additional test cases.

Coverage Analysis
-----------------

Functional Coverage
~~~~~~~~~~~~~~~~~~~

The 6 comprehensive smoke tests provide extensive functional coverage:

* **Reset behavior**: Reset state verification and reset hierarchy (TRST vs TLR)
* **Data path integrity**: Bidirectional scan chain with random data verification
* **Control signal functionality**: TAP control pass-through and TMS output modes
* **3DCR register**: Full read/write/verify through SIB with preservation
* **Configuration persistence**: Config_hold bit functionality across reset types
* **STAP modes**: Both active (stap_sel=1) and inactive (stap_sel=0) operation
* **Pipeline stage operation**: Timing verification through scan chain
* **Lockup latch timing**: TDO output timing in bidirectional test

**Coverage Metrics**:

* 75+ individual signal checks across all tests
* All 3DCR register bits tested (config_hold, stap_sel, tms_hold)
* All TMS output modes (4 combinations of stap_sel and tms_hold)
* Both reset types (TRST and scan reset/TLR)
* Bidirectional data flow verification

Code Coverage
~~~~~~~~~~~~~

For detailed code coverage analysis, run with coverage enabled:

.. code-block:: bash

   # Add coverage flags to Makefile VERILATOR flags:
   # --coverage --coverage-line --coverage-toggle

Then analyze coverage reports in ``obj_dir/coverage.dat``

Extending Tests
---------------

Adding New Tests
~~~~~~~~~~~~~~~~

To add a new test:

1. Create a new task in ``jtag_stap_tb.sv``:

.. code-block:: systemverilog

   task automatic test_new_feature();
       reset_dut();  // Initialize to known state
       test_count++;
       $display("Test %0d: New feature description", test_count);
       
       // Test logic here
       
       check_signal(actual, expected, "signal_name", "Test Name");
   endtask

2. Add to test execution:

.. code-block:: systemverilog

   task automatic execute_tests();
       test_reset_state();
       test_tap_ctrl_passthrough();
       test_scan_chain_basic();
       test_stap_host_interface();
       test_tms_output_modes();
       test_config_hold();
       test_new_feature();  // Add your new test here
   endtask

3. Rebuild and run:

.. code-block:: bash

   make clean
   make stap-test

Advanced Testing
~~~~~~~~~~~~~~~~

The current test suite provides comprehensive coverage including:

* **Bidirectional data flow**: Simultaneous testing of both scan paths (Test 4)
* **3DCR register access**: Full read/write/verify via SIB (Tests 5 and 6)
* **Configuration persistence**: Reset hierarchy verification (Test 6)
* **Random data patterns**: Non-deterministic testing for comprehensive coverage

For additional advanced testing scenarios:

* **Multi-cycle patterns**: Extend pattern propagation tests with longer sequences
* **Timing corner cases**: Test setup/hold margins at different clock frequencies
* **Power state transitions**: Test behavior across power modes (if applicable)
* **Error injection**: Test fault handling (if implemented)
* **Parameter variations**: Test with different LOCKUP and PIPE settings

Regression Testing
~~~~~~~~~~~~~~~~~~

The test infrastructure supports regression testing:

.. code-block:: bash

   # Run tests multiple times
   for i in {1..10}; do
       make stap-test || break
   done

Tests use ``$urandom`` for data generation, providing different test vectors on each run for comprehensive coverage. While the test patterns vary, the verification logic remains consistent.

Performance Testing
-------------------

Latency Measurement
~~~~~~~~~~~~~~~~~~~

To measure scan chain latency:

1. Apply known pattern to scan input
2. Count clock cycles to scan output
3. Compare with expected latency

Expected latencies:

* No pipeline: ~1.5 cycles (lockup only)
* With pipeline: ~2.5 cycles
* Through SIB: Add 1 cycle for register
* Through 3DCR: Add 1 cycle per bit

Throughput Analysis
~~~~~~~~~~~~~~~~~~~

Scan throughput is 1 bit per clock cycle when:

* ``scan_en`` is continuously high
* Chain is selected (``select`` = 1)
* No stalls applied

Maximum theoretical throughput: 1 bit/cycle at clock frequency.

Test Automation
---------------

Continuous Integration
~~~~~~~~~~~~~~~~~~~~~~

The test Makefile is designed for CI/CD integration:

.. code-block:: bash

   # CI script example
   cd hw/ip/jtag_stap/tb
   make clean
   make stap-test
   exit_code=$?
   
   if [ $exit_code -eq 0 ]; then
       echo "Tests PASSED"
   else
       echo "Tests FAILED"
       exit 1
   fi

The testbench returns proper exit codes:

* 0: All tests passed
* Non-zero: Test failure or error

Nightly Testing
~~~~~~~~~~~~~~~

Recommended nightly test sequence:

1. Clean build
2. Run smoke tests
3. Generate waveforms
4. Check for linter warnings
5. Archive test results

Example script:

.. code-block:: bash

   #!/bin/bash
   cd hw/ip/jtag_stap/tb
   make clean
   make stap-test 2>&1 | tee test_results.log
   cp jtag_stap_tb.vcd archive/test_$(date +%Y%m%d_%H%M%S).vcd

