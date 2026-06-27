===============
Verification
===============

This section describes the testbench structure and test plan for the Cross Trigger Matrix IP.

Testbench Structure
===================

The testbench is located in ``tb_vcs/`` and follows the structure used by the cross_trigger_port reference design.

Testbench Components
--------------------

**tb_cross_trigger_matrix.sv**:
* Top-level testbench module (generated from template)
* Instantiates CTM module with AXI-Lite interface
* Provides CT_Dst stimulus signals
* Monitors CT_Src outputs
* Clock and reset generation
* Cocotb integration
* Parameters (NUM_CT_SRC, NUM_CT_DST) match IP generation settings

**test/test_base.py**:
* Base test class with common utilities
* AXI-Lite transaction helpers
* Common setup and teardown
* Clock and reset handling

**test/test_sanity.py**:
* Basic sanity test
* Verifies core functionality has not broken

**test/test_routing.py**:
* Comprehensive routing tests
* Single-source, multi-source, broadcast tests
* Edge cases and corner cases

Test Plan
=========

Sanity Test
-----------

**Purpose**: Quick smoke test to verify basic functionality

**Steps**:
1. Reset CTM
2. Write CT_SRC0_CONFIG_0.CT_DST_SELECT = 0x00000001 (select CT_Dst[0])
3. Assert pulse on ct_dst_i[0]
4. Verify pulse appears on ct_src_o[0] after 1 cycle (registered)
5. Verify no pulses on other CT_Src outputs
6. Read back register to verify configuration

For NUM_CT_DST > 32, test upper ports:
7. Write CT_SRC0_CONFIG_1.CT_DST_SELECT = 0x00000001 (select CT_Dst[32])
8. Assert pulse on ct_dst_i[32]
9. Verify pulse appears on ct_src_o[0]

**Expected Results**:
* Pulse routed correctly from CT_Dst[0] to CT_Src[0]
* Pulse appears 1 cycle after input (registered)
* Other CT_Src outputs remain low
* Register readback matches written value

Routing Tests
-------------

**Test 1: Single Source Routing**
* Configure each CT_Src to select single CT_Dst
* Verify correct routing for all combinations
* Test all N×M routing paths
* Verify register readback

**Test 2: Multi-Source OR**
* Configure CT_Src[0] to select multiple CT_Dst (e.g., 0x00000003 for CT_Dst[0:1])
* Send pulses on CT_Dst[0] and CT_Dst[1] separately
* Verify CT_Src[0] pulses for both
* Send simultaneous pulses, verify OR behavior
* Verify pulse appears when any selected CT_Dst pulses

**Test 3: Broadcast**
* Configure multiple CT_Src to same CT_Dst
* Send pulse on CT_Dst
* Verify all configured CT_Src outputs pulse
* Test with different CT_Dst sources

**Test 4: Disable Output**
* Configure CT_Src with CT_DST_SELECT = 0x00000000
* Send pulses on all CT_Dst
* Verify CT_Src remains low
* Verify no spurious pulses

**Test 5: Register Updates**
* Start with one routing configuration
* Send pulses and verify routing
* Update configuration during operation
* Verify new routing takes effect immediately
* Test rapid configuration changes

**Test 6: Simultaneous Pulses**
* Send pulses on multiple CT_Dst simultaneously
* Verify all configured CT_Src respond correctly
* Test OR behavior with overlapping pulses
* Verify no pulse loss

**Test 7: Back-to-Back Pulses**
* Send consecutive pulses on CT_Dst
* Verify all pulses propagate through
* Test minimum pulse spacing
* Verify no pulse merging

**Test 8: Edge Cases**
* Test with N=1, M=1 (minimum configuration)
* Test with N=32, M=32 (maximum configuration)
* Test all CT_Src selecting all CT_Dst
* Test rapid configuration changes
* Test with unused register bits set

Corner Cases
------------

**Test 9: Reset During Operation**
* Send pulses on CT_Dst
* Assert reset during operation
* Verify clean recovery, outputs go low
* Verify registers reset to default values

**Test 10: Register Readback**
* Write various CT_DST_SELECT values
* Read back and verify
* Test all register addresses
* Verify unused bits are ignored

**Test 11: Parameter Validation**
* Test with invalid parameters (if possible)
* Verify assertions catch invalid configurations
* Test boundary conditions (1, 32)

**Test 12: Glitch Prevention**
* Rapidly change configuration
* Verify no glitches on outputs
* Test mode switching during pulses
* Verify all outputs remain registered

Testbench Implementation
========================

The testbench uses Python with cocotb framework for test control:

* AXI-Lite VIP (axil_vip/axil_master.py) for register access
* Clock and reset generation
* Stimulus generation for CT_Dst inputs
* Response checking for CT_Src outputs
* Coverage collection

Documentation Requirements
=========================

The testbench documentation should include:

* Testbench structure description
* Test descriptions and expected results
* Coverage goals
* Known limitations
* Usage instructions
