===============
Verification
===============

This section describes the testbench structure and test plan for the Cross Trigger Port IP.

Testbench Structure
==================

The testbench is located in ``tb_vcs/`` and follows the structure used by the entropy_source reference design.

Testbench Components
--------------------

**tb_cross_trigger_port.sv**:
* Top-level testbench module
* Instantiates CTP module with AXI-Lite interface
* Simulates GPIO pad connections
* Provides AXI-Lite request/response structures
* Clock and reset generation

**test/test_base.py**:
* Base test class with common utilities
* AXI-Lite transaction helpers
* Common setup and teardown

**test/test_sanity.py**:
* Basic sanity test
* Verifies core functionality has not broken

**test/test_wire_or_mode.py**:
* Wire-OR mode tests
* Pulse stretching verification
* Multiple source simulation

**test/test_point_to_point_mode.py**:
* Point-to-Point mode tests
* Handshake protocol verification
* Deadlock recovery tests

Test Plan
=========

Sanity Test
-----------

**Purpose**: Quick smoke test to verify basic functionality

**Steps**:
1. Configure CTP in Wire-OR mode
2. Set STRETCH_MULT to small value (e.g., 10)
3. Send single pulse on ct_src_i
4. Verify pulse appears on pad output
5. Verify BUSY bit asserts and clears
6. Verify STATUS register readback

**Expected Results**:
* Pulse stretched correctly
* BUSY bit tracks transfer
* Status register reflects correct values

Wire-OR Mode Tests
------------------

**Test 1: Pulse Stretching**
* Configure STRETCH_MULT to various values
* Send pulse and verify width = (STRETCH_MULT + 1) cycles
* Verify pulse restart on back-to-back pulses

**Test 2: Multiple Sources**
* Simulate multiple CTPs on shared wire
* Verify all chiplets see triggers
* Test simultaneous triggers

**Test 3: Signal Inversion**
* Test with INVERT = 0 (active-low)
* Test with INVERT = 1 (active-high)
* Verify pad output polarity changes
* Verify status readback reflects inversion

**Test 4: Edge Cases**
* Back-to-back pulses
* Very short STRETCH_MULT (0, 1)
* Very long STRETCH_MULT (65535)
* Reset during pulse stretching

Point-to-Point Mode Tests
--------------------------

**Test 1: Basic Handshake**
* Configure in Point-to-Point mode
* Send pulse from sender
* Verify four-phase handshake sequence
* Verify receiver generates ct_dst pulse
* Verify BUSY bit tracks handshake

**Test 2: Bidirectional Communication**
* Test sender → receiver
* Test receiver → sender
* Test simultaneous bidirectional

**Test 3: Handshake Timing**
* Verify timing matches specification diagrams
* Test various clock frequencies
* Test with clock domain crossing

**Test 4: Deadlock Recovery**
* Simulate deadlock condition
* Assert RESET bit
* Verify handshake clears
* Deassert RESET and verify recovery

**Test 5: Signal Inversion**
* Test with INVERT = 0 (active-high)
* Test with INVERT = 1 (active-low)
* Verify handshake works correctly

**Test 6: Edge Cases**
* Back-to-back handshakes
* Reset during handshake
* Mode switching during operation

Mode Switching Tests
--------------------

**Test 1: Wire-OR to Point-to-Point**
* Start in Wire-OR mode
* Switch to Point-to-Point mode
* Verify pad control signals change
* Verify handshake works

**Test 2: Point-to-Point to Wire-OR**
* Start in Point-to-Point mode
* Switch to Wire-OR mode
* Verify pad control signals change
* Verify pulse stretching works

**Test 3: Mode Switching During Transfer**
* Start transfer in one mode
* Switch mode during transfer
* Verify clean transition

Status Register Tests
---------------------

**Test 1: BUSY Bit**
* Verify BUSY asserts during transfers
* Verify BUSY clears when idle
* Test in both modes

**Test 2: Signal Readback**
* Read STATUS.REQ_OUT, ACK_IN, REQ_IN, ACK_OUT
* Verify values match actual signals
* Test with INVERT enabled

**Test 3: Synchronization**
* Verify synchronized signals in STATUS
* Test with asynchronous input changes

Protocol Compliance Tests
--------------------------

**Test 1: Wire-OR Timing**
* Verify pulse width matches specification
* Verify all chiplets can see pulse
* Test with various STRETCH_MULT values

**Test 2: Point-to-Point Handshake**
* Verify four-phase protocol
* Match timing diagrams from specification
* Test both directions

**Test 3: Edge Detection**
* Verify positive edge detection
* Test edge cases (glitches, slow transitions)

Corner Cases
------------

**Test 1: Reset During Operation**
* Reset during pulse stretching
* Reset during handshake
* Verify clean recovery

**Test 2: Clock Domain Crossing**
* Test with different clock frequencies
* Verify synchronization works correctly

**Test 3: Glitch Prevention**
* Verify no glitches on outputs
* Test mode switching
* Test register updates

**Test 4: Boundary Conditions**
* STRETCH_MULT = 0 (minimum pulse)
* STRETCH_MULT = 65535 (maximum pulse)
* Very fast clock
* Very slow clock

Testbench Implementation
========================

The testbench uses Python with cocotb framework for test control:

* AXI-Lite VIP (axil_vip/axil_master.py) for register access
* Clock and reset generation
* Stimulus generation
* Response checking
* Coverage collection

Documentation Requirements
==========================

The testbench documentation should include:

* Testbench structure description
* Test descriptions and expected results
* Coverage goals
* Known limitations
* Usage instructions
