============
Verification
============

This section describes the verification approach for the JTAG PTAP IP.

Test Strategy
=============

The PTAP verification strategy covers:

1. **IEEE 1149.1 Compliance**: TAP state machine, mandatory instructions
2. **Optional Features**: TMP, IC_RESET, boundary scan
3. **IEEE 1838 Compliance**: 3DCR register, STAP selection
4. **IEEE 1687 Compliance**: iJTAG network access
5. **JTAG2AXI Functionality**: AXI transaction generation
6. **Parameterization**: Feature enable/disable coverage

Testbench Architecture
======================

Components
----------

**JTAG Driver**:

* Generates TCK clock
* Drives TMS, TDI signals
* Captures TDO responses
* Provides high-level transaction API

**TAP Sequence Library**:

* Reset sequences (TRST, TLR)
* IR scan operations
* DR scan operations
* Complex instruction sequences

**Reference Models**:

* TAP state machine checker
* Instruction decoder checker
* Data register models

**Coverage Collectors**:

* TAP state coverage
* Instruction coverage
* Feature coverage

Test Plan
=========

TAP Controller Tests
--------------------

**Test 1: TRST Reset**

* Assert TRST_n
* Verify TAP enters TEST_LOGIC_RESET
* Verify instruction register defaults to IDCODE
* Release TRST_n and verify stable operation

**Test 2: TLR via TMS**

* Drive TMS=1 for 5+ TCK cycles
* Verify TAP enters TEST_LOGIC_RESET
* Verify from all possible starting states

**Test 3: State Machine Traversal**

* Visit all 16 TAP states
* Verify correct transitions for TMS=0 and TMS=1
* Check one-hot state encoding

**Test 4: IR Scan**

* Navigate to Shift-IR state
* Shift various instruction patterns
* Verify capture value (IDCODE encoding)
* Verify update loads instruction

**Test 5: DR Scan**

* Navigate to Shift-DR state for each instruction
* Verify correct TDR is selected
* Check capture, shift, and update behavior

Instruction Tests
-----------------

**Test 6: BYPASS Instruction**

* Load BYPASS (0x3F) and BYPASS_ALT (0x00)
* Scan through bypass register
* Verify single-bit delay
* Verify capture value is 0

**Test 7: IDCODE Instruction**

* Load IDCODE instruction (default)
* Shift out 32-bit IDCODE
* Verify manufacturer ID, part number, revision
* Verify bit[0] = 1

**Test 8: INV_BYPASS Instruction**

* Load INV_BYPASS (0x3E)
* Scan through register
* Verify capture value is 1

**Test 9: ZERO_LENGTH_BYPASS**

* Load ZERO_LENGTH_BYPASS (0x3D)
* Verify TDI passes directly to TDO
* Verify no additional latency during shift

**Test 10: SAMPLE/PRELOAD**

* Load SAMPLE_PRELOAD instruction
* Verify BSR scan chain is selected
* Capture current pin values
* Preload test data

**Test 11: EXTEST**

* Load EXTEST instruction
* Verify BSR scan chain selected
* Verify output pins driven from BSR

**Test 12: RUNBIST**

* Load RUNBIST instruction
* Verify iJTAG network selected
* Verify TAP stays in Run-Test/Idle during test

TMP Tests (IEEE 1149.1 Section 16)
----------------------------------

**Test 13: TMP Status Register**

* Load TMP_STATUS instruction
* Read persistence mode (should be 0)
* Write bypass_escape enable bit

**Test 14: CLAMP_HOLD**

* Load CLAMP_HOLD instruction
* Verify persistence mode activates
* Verify TAP held in Run-Test/Idle
* Verify TMP_STATUS reflects persistence

**Test 15: CLAMP_RELEASE**

* While in persistence mode, load CLAMP_RELEASE
* Verify persistence mode deactivates
* Verify normal TAP operation resumes

**Test 16: Bypass-Escape**

* Enable bypass_escape bit in TMP_STATUS
* Enter persistence mode via CLAMP_HOLD
* Load explicit BYPASS instruction
* Verify automatic exit from persistence

IC_RESET Tests (IEEE 1149.1 Section 17)
---------------------------------------

**Test 17: IC_RESET Register Access**

* Load IC_RESET instruction
* Scan register (verify width: 2*N+1)
* Verify reset_hold bit behavior

**Test 18: Reset Enable Control**

* Set reset_enable[i] for each port
* Verify ic_reset_ovrd_o[i] reflects enable
* Toggle reset_control[i]
* Verify ic_reset_ctrl_n_o[i] reflects value

**Test 19: Reset Hold**

* Set reset_hold = 1
* Program reset configuration
* Enter TLR state
* Verify configuration preserved
* Clear reset_hold and enter TLR
* Verify configuration resets

3DCR Tests (IEEE 1838)
----------------------

**Test 20: 3DCR Register Access**

* Load TAP_3DCR instruction
* Scan 2-bit register
* Verify capture and update behavior

**Test 21: STAP Selection**

* Set stap_sel = 1 in 3DCR
* Verify STAP scan path selected
* Verify TDO comes from STAP input
* Clear stap_sel and verify local TDRs

**Test 22: Config Hold**

* Set config_hold = 1 in 3DCR
* Set stap_sel = 1
* Enter TLR state
* Verify stap_sel preserved
* Apply TRST
* Verify 3DCR resets

iJTAG Tests (IEEE 1687)
-----------------------

**Test 23: SELECT_IJTAG**

* Load SELECT_IJTAG instruction
* Verify iJTAG scan chain selected
* Scan data through iJTAG network
* Access SIBs and TDRs in network

Debug Control Tests
-------------------

**Test 24: DEBUG_CONTROL Register**

* Load DEBUG_CONTROL instruction
* Read CLA clock stop status
* Write clock stop and boot stall controls
* Verify output signals reflect register values

**Test 25: Capabilities Register**

* Load JTAG_CAPS instruction
* Shift out 40-bit capabilities
* Verify reflects parameter settings

JTAG2AXI Tests
--------------

**Test 26: JTAG2AXI Capabilities**

* Read SMC_OTP_JTAG2AXI_CAPS
* Read SEP_OTP_JTAG2AXI_CAPS
* Read SMC_JTAG2AXI_CAPS
* Verify address/data width, bus type

**Test 27: AXI Single Operation**

* Load AXI_SINGLE_OP instruction
* Perform single AXI write
* Perform single AXI read
* Verify data integrity

**Test 28: AXI Series Operations**

* Configure series operation via AXI_SERIES_CTRL
* Stream data via AXI_SERIES_DATA_INCR
* Verify address auto-increment
* Test AXI_SERIES_DATA_NO_INCR mode

**Test 29: AXI Error Handling**

* Use AXI_SERIES_DATA_WITH_ERROR_STATUS
* Inject AXI error response
* Verify error status reported

Parameterization Tests
----------------------

**Test 30: Feature Disable**

* Test with BSR_ENABLE = 0
* Verify BSR instructions select bypass
* Test with TMP_ENABLE = 0
* Verify TMP instructions select bypass
* Repeat for all enable parameters

**Test 31: IDCODE Variation**

* Test with different IDCODE parameters
* Verify correct IDCODE returned

Corner Cases
============

Timing Tests
------------

**Test 32: TCK Frequency**

* Test at minimum TCK frequency
* Test at maximum TCK frequency
* Verify setup/hold margins

**Test 33: TDO Timing**

* Verify TDO changes on falling TCK
* Measure TDO valid window
* Check ZERO_LENGTH_BYPASS timing

Reset Tests
-----------

**Test 34: Reset During Operation**

* Apply TRST during active scan
* Verify clean recovery
* Apply TRST during JTAG2AXI transaction

**Test 35: TLR Immunity**

* Configure config_hold protected registers
* Enter TLR multiple times
* Verify protected values stable

Coverage Goals
==============

Functional Coverage
-------------------

* All TAP states visited
* All TAP state transitions exercised
* All instructions executed
* All data registers accessed
* All parameter combinations tested

Code Coverage
-------------

* Statement coverage: >95%
* Branch coverage: >90%
* Condition coverage: >85%
* FSM coverage: 100% states and transitions

Assertions
==========

The following assertions should be implemented:

TAP Controller Assertions
-------------------------

.. code-block:: systemverilog

   // State must be one-hot
   assert property (@(posedge tck) $onehot(current_state));

   // TRST must reset to TLR
   assert property (@(posedge tck) !trst_n |-> current_state == TEST_LOGIC_RESET);

   // 5 consecutive TMS=1 reaches TLR
   assert property (@(posedge tck)
       $rose(tms) ##1 tms[*4] |-> current_state == TEST_LOGIC_RESET);

Instruction Register Assertions
-------------------------------

.. code-block:: systemverilog

   // IR captures IDCODE encoding in Capture-IR
   assert property (@(posedge tck) capture_ir |-> ##1 ir_capture == 6'b000001);

   // Default instruction after reset is IDCODE
   assert property (@(posedge tck)
       $rose(trst_n) |-> inst_decoded_o == IDCODE_INSTR_DECODED);

TDO Assertions
--------------

.. code-block:: systemverilog

   // TDO output enable only during shift
   assert property (@(negedge tck)
       tdo_oen |-> (current_state == SHIFT_DR || current_state == SHIFT_IR));

   // TDO changes on falling edge
   assert property (@(negedge tck)
       !$stable(tdo) |-> (shift_dr || shift_ir));

Debugging Guidelines
====================

Common Issues
-------------

**TDO Always Zero**:

* Check TDO output enable
* Verify TAP is in shift state
* Check instruction register value
* Verify TDR mux selection

**Wrong IDCODE**:

* Verify IDCODE parameters
* Check IR captures to IDCODE
* Verify 32-bit shift count

**STAP Not Selected**:

* Check 3DCR stap_sel bit
* Verify PTAP_3DCR_ENABLE parameter
* Check STAP scan input connection

**JTAG2AXI Timeout**:

* Check system clock running
* Verify AXI interface connection
* Check for AXI bus errors

Waveform Analysis
-----------------

Key signals to observe:

* ``current_state``: TAP state machine
* ``inst_decoded_o``: Current instruction
* ``tdr_mux``: Selected TDR output
* ``stap_select``: STAP selection
* ``persistence_mode``: TMP state

Test Execution
==============

Running Tests
-------------

.. code-block:: bash

   # Navigate to testbench directory
   cd hw/ip/jtag_ptap/tb

   # Run all tests
   make all

   # Run specific test
   make test TEST=test_idcode

   # Run with coverage
   make test COVERAGE=1

   # Generate coverage report
   make coverage_report

Test Results
------------

Test results are reported in standard format:

.. code-block:: text

   === JTAG PTAP Test Results ===
   Test: test_bypass - PASS
   Test: test_idcode - PASS
   Test: test_tap_states - PASS
   ...
   === Summary ===
   Passed: 35
   Failed: 0
   Total: 35
