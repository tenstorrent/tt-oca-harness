===============
Implementation
===============

This section describes the implementation details of each module in the Cross Trigger Matrix IP.

Top Module: cross_trigger_matrix
==================================

The top module integrates the register interface and selector modules.

**File**: ``rtl/cross_trigger_matrix.sv`` (generated from template)

**Template**: ``rtl/templates/cross_trigger_matrix.sv.tpl``

**Key Features**:
* Generated from Mako template to match register definitions exactly
* Only includes case statements for the configured number of CT_SRC ports
* Parameterized AXI-Lite bus interface types (default from package)
* AXI4-Lite register interface integration with request/response structures
* Array of selector modules (one per CT_Src port)
* Parameter validation assertions
* All outputs registered

**Parameters**:
* ``NUM_CT_SRC``: Number of CT_Src output ports (must match generated value)
* ``NUM_CT_DST``: Number of CT_Dst input ports (default from package: DEFAULT_NUM_CT_DST, valid 1-64)
* ``axil_req_t``: AXI-Lite request structure type (default: cross_trigger_matrix_pkg::ctm_axil_req_t)
* ``axil_resp_t``: AXI-Lite response structure type (default: cross_trigger_matrix_pkg::ctm_axil_resp_t)

**Note**: The main RTL module is generated from a template and contains only the case statements needed for the configured NUM_CT_SRC. This ensures the RTL matches the generated register package exactly, avoiding compilation errors from referencing non-existent register fields.

**Implementation Details**:
* Instantiates generated register module with AXI4-Lite interface
* Connects request/response structures to flattened PeakRDL register signals
* Generates array of ctm_src_selector modules (one per CT_Src port)
* Maps register fields to selector select_i inputs using generated if/else chain
* Only uses valid CT_DST_SELECT bits based on NUM_CT_DST parameter
* Validates NUM_CT_SRC at elaboration time (must match generated value)

Source Selector Module: ctm_src_selector
=========================================

Implements the selection and OR logic for a single CT_Src output port.

**File**: ``rtl/ctm_src_selector.sv``

**Parameters**:
* ``NUM_CT_DST``: Number of CT_Dst input ports (M)

**Inputs**:
* ``clk_i``: Clock signal
* ``rst_ni``: Active-low reset signal
* ``ct_dst_i[NUM_CT_DST-1:0]``: CT_Dst input pulses
* ``select_i[NUM_CT_DST-1:0]``: Selection mask from register

**Outputs**:
* ``ct_src_o``: Registered CT_Src output pulse

**Implementation**:
* Generates AND gates for each CT_Dst with its select bit
* ORs all selected pulses together combinatorially
* Registers the output to prevent glitches
* Reset clears output to 0

**Logic Flow**:
1. For each CT_Dst[i], compute: selected_pulses[i] = ct_dst_i[i] & select_i[i]
2. OR all selected_pulses together: ct_src_comb = |selected_pulses
3. Register: ct_src_o <= ct_src_comb (on clock edge)

Package: cross_trigger_matrix_pkg
===================================

Defines types and constants for the CTM.

**File**: ``rtl/cross_trigger_matrix_pkg.sv``

**Contents**:
* Default parameters: DEFAULT_NUM_CT_SRC = 4, DEFAULT_NUM_CT_DST = 4
* Parameter constraints: MIN/MAX values (1-64 for both CT_SRC and CT_DST)
* AXI-Lite type definitions using ``AXI_LITE_TYPEDEF_ALL`` macro
* Request/response structure types: ``ctm_axil_req_t``, ``ctm_axil_resp_t``
* Address, data, and strobe type definitions

Register Module: cross_trigger_matrix_reg
==========================================

Generated from SystemRDL template using PeakRDL.

**Generation**: Run ``python3 generate_ip.py --num-ct-src <N> --num-ct-dst <M>`` from the IP root directory.

The generation process:
1. Generates SystemRDL register definition file from Mako template based on ``NUM_CT_SRC`` and ``NUM_CT_DST`` parameters
2. Processes the RDL file with PeakRDL to generate register RTL and headers
3. Generates main RTL module (``cross_trigger_matrix.sv``) from template with matching case statements
4. Generates RTL package and testbench from templates with matching parameters

**Interface**:
* AXI4-Lite slave interface (flattened signals)
* Hardware input/output structures (hwif_in/hwif_out)
* Register access with proper AXI-Lite timing
* Generated with ``--cpuif axi4-lite-flat`` option

**Register Structure**:
* NUM_CT_SRC register pairs: CT_SRC0_CONFIG_0/CONFIG_1 through CT_SRC[NUM_CT_SRC-1]_CONFIG_0/CONFIG_1
* Each CT_SRC uses 8 bytes: CONFIG_0 at offset (i * 8), CONFIG_1 at offset (i * 8) + 4
* CONFIG_0 contains CT_DST_SELECT[31:0] field for CT_Dst[31:0]
* CONFIG_1 contains CT_DST_SELECT[NUM_CT_DST-33:0] field for CT_Dst[63:32] (only when NUM_CT_DST > 32)
* When NUM_CT_DST <= 32, only CONFIG_0 is generated
* When NUM_CT_DST < 32, bits [31:NUM_CT_DST] in CONFIG_0 are reserved (RESERVED field)
* When NUM_CT_DST < 64, bits [31:NUM_CT_DST-32] in CONFIG_1 are reserved (RESERVED field)
* Fields are R/W, reset value is 0x0
* Only the required number of register pairs are generated (matches NUM_CT_SRC parameter)
* Field widths match NUM_CT_DST parameter (1-64 bits total)

Design Considerations
=====================

Glitch Prevention
-----------------

All combinatorial outputs are registered to prevent glitches:

* CT_Src outputs (registered in ctm_src_selector module)
* Selection logic is combinatorial but output is registered
* Prevents spurious pulses during configuration changes

Parameter Handling
------------------

* Parameters validated at elaboration time
* Only valid register bits (based on NUM_CT_DST) are used
* Unused CT_Src ports can be left unconfigured (all-zero select)
* Register interface supports full 32-port range

Register Field Mapping
----------------------

The top module maps register fields to selector inputs:

* Uses generated if/else chain to select appropriate register field
* The if/else chain is generated from a Mako template with only the configured ports
* Only extracts NUM_CT_DST bits from the register field
* Unused bits are ignored (masked to zero)

**Example**: With NUM_CT_SRC=6 and NUM_CT_DST=64, the generated RTL contains:

.. code-block:: systemverilog

    always_comb begin
        if (i == 0) begin
            // Combine CONFIG_0 (lower 32 bits) and CONFIG_1 (upper bits)
            select_mask = {reg_out.CT_SRC0_CONFIG_1.CT_DST_SELECT.value[NUM_CT_DST-33:0],
                           reg_out.CT_SRC0_CONFIG_0.CT_DST_SELECT.value};
        end
        else if (i == 1) begin
            select_mask = {reg_out.CT_SRC1_CONFIG_1.CT_DST_SELECT.value[NUM_CT_DST-33:0],
                           reg_out.CT_SRC1_CONFIG_0.CT_DST_SELECT.value};
        end
        // ... only up to CT_SRC5_CONFIG
        else begin
            select_mask = '0;
        end
    end

For NUM_CT_DST <= 32, only CONFIG_0 is used:

.. code-block:: systemverilog

    always_comb begin
        if (i == 0) begin
            select_mask = reg_out.CT_SRC0_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
        end
        // ...
    end

Scalability
-----------

* Design scales efficiently from 1x1 to 32x32
* Each selector module is independent
* Register interface generated for exact port count (no unused registers)
* Main RTL generated with exact case statements (no unused references)
* No shared resources that could limit scalability
* Template-based generation ensures consistency across all files

Common Primitives
-----------------

* Uses standard SystemVerilog constructs
* No special primitives required (simple AND/OR gates)
* Register uses standard always_ff blocks
* Compatible with any standard synthesis tool
