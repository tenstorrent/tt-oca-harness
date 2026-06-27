=============
Architecture
=============

The Cross Trigger Matrix (CTM) architecture consists of a register interface and an array of source selector modules that route cross trigger pulses from M source ports (CT_Dst) to N sink ports (CT_Src).

Block Diagram
=============

The following diagram illustrates the high-level structure of the CTM:

.. image:: ../image1.png
   :alt: CTM Block Diagram
   :align: center

Module Hierarchy
================

The CTM top module (cross_trigger_matrix) instantiates the following sub-modules:

* **cross_trigger_matrix_reg**: Generated register module (from SystemRDL)
* **ctm_src_selector**: Array of N selector modules (one per CT_Src port)

Signal Descriptions
====================

Cross Trigger Interface
-----------------------

* **ct_dst_i[M-1:0]**: Cross trigger destination input pulses (sources for the matrix)
  * M is the number of CT_Dst ports (parameter NUM_CT_DST, range 1-64)
  * Each input is a pulse signal synchronous to clk_i
  * Multiple CT_Dst can pulse simultaneously

* **ct_src_o[N-1:0]**: Cross trigger source output pulses (sinks for the matrix)
  * N is the number of CT_Src ports (parameter NUM_CT_SRC, range 1-64)
  * Each output is a registered pulse signal
  * Output is high when any selected CT_Dst input is high

Register Interface
-----------------

* **axil_req_i**: AXI4-Lite request structure
* **axil_resp_o**: AXI4-Lite response structure
* Parameterized types allow generic bus interface
* Default types defined in cross_trigger_matrix_pkg

Architecture Details
====================

Register Structure
------------------

The CTM provides two configuration registers per CT_Src port (when NUM_CT_DST > 32) or one register (when NUM_CT_DST <= 32):

* **CTM_CT_SRC[i]_CONFIG_0**: Configuration register for CT_Src[i] - lower 32 ports
  * Offset: 0x0 + (i * 8) bytes
  * Contains CT_DST_SELECT field [min(M-1, 31):0]
  * Each bit selects corresponding CT_Dst port (CT_Dst[31:0])
  * Multiple bits can be set to OR multiple sources

* **CTM_CT_SRC[i]_CONFIG_1**: Configuration register for CT_Src[i] - upper 32 ports (only when NUM_CT_DST > 32)
  * Offset: 0x4 + (i * 8) bytes
  * Contains CT_DST_SELECT field [M-33:0]
  * Each bit selects corresponding CT_Dst port (CT_Dst[63:32])
  * Multiple bits can be set to OR multiple sources

Source Selector Logic
--------------------

Each CT_Src port has an associated selector module that implements:

1. **Selection**: AND each CT_Dst input with its corresponding select bit from register
2. **Aggregation**: OR all selected pulses together
3. **Registration**: Register the output to prevent glitches

The logic flow is:

.. code-block:: text

   CT_Dst[0] & Select[0] ─┐
   CT_Dst[1] & Select[1] ─┤
   CT_Dst[2] & Select[2] ─┤  OR ──> Register ──> CT_Src[i]
   ...                    │
   CT_Dst[M-1] & Select[M-1] ─┘

Signal Flow
-----------

1. **Configuration**: Software writes CT_DST_SELECT field via AXI4-Lite
2. **Selection**: Selector module reads register value and applies selection mask
3. **Pulse Routing**: When CT_Dst[j] pulses and Select[j] is set, pulse propagates
4. **OR Aggregation**: Multiple selected CT_Dst pulses are OR'd together
5. **Output**: Registered CT_Src output pulses one cycle after input

Timing Characteristics
======================

* **Configuration Latency**: Register writes take effect immediately (combinatorial path)
* **Pulse Latency**: CT_Dst pulse to CT_Src output = 1 clock cycle (registered)
* **Simultaneous Pulses**: Multiple CT_Dst can pulse simultaneously, all propagate correctly
* **Back-to-Back Pulses**: Consecutive pulses on same or different CT_Dst propagate independently

Parameter Constraints
====================

* **NUM_CT_SRC**: Number of CT_Src output ports (1-64)
* **NUM_CT_DST**: Number of CT_Dst input ports (1-64)
* Parameters are validated at elaboration time
* Register interface is parameterized: generates exactly NUM_CT_SRC registers (addresses 0x0 to 0x0 + (NUM_CT_SRC-1)*4)
* CT_DST_SELECT field width matches NUM_CT_DST (bits [NUM_CT_DST-1:0])
* Main RTL module is generated from template with exact case statements for NUM_CT_SRC
* Parameters are synchronized across register definitions, main RTL, RTL package, and testbench

Design Considerations
=====================

Glitch Prevention
-----------------

All CT_Src outputs are registered to prevent glitches:

* Selection logic is combinatorial (AND gates)
* OR aggregation is combinatorial
* Final output is registered in ctm_src_selector module
* Prevents spurious pulses during configuration changes

Register Access
---------------

* Register interface uses AXI4-Lite protocol
* Supports standard read/write transactions
* Register fields are accessible via hwif_out structure
* Only valid CT_DST_SELECT bits (based on NUM_CT_DST) are used

Scalability
-----------

* Design scales from 1x1 (minimum) to 32x32 (maximum) configurations
* Register space is parameterized: only NUM_CT_SRC registers are generated
* Main RTL module is generated from template: only references configured registers
* Register generation uses template-based approach for consistency
* Selector modules only instantiated for configured NUM_CT_SRC ports
* RTL package defaults (DEFAULT_NUM_CT_SRC, DEFAULT_NUM_CT_DST) match generation parameters
