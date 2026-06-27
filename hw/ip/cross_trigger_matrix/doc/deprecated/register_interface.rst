==================
Register Interface
==================

The Cross Trigger Matrix provides a register-based interface for configuration. The register interface is defined using SystemRDL and generated using PeakRDL with AXI4-Lite bus interface. The bus interface uses request and response structures with types defined in ``deps/axi/include/axi/typedef.svh``.

Register Documentation
======================

The complete register map and field descriptions are automatically generated from SystemRDL. The number of registers matches the ``NUM_CT_SRC`` parameter used during IP generation.

.. include:: ../data/registers/rst/cross_trigger_matrix_reg.rst
   :start-line: 1

Programming Model
=================

Initialization
--------------

1. Configure routing for each CT_Src port:
   * Each CT_Src has two registers: CT_SRCn_CONFIG_0 (CT_Dst[31:0]) and CT_SRCn_CONFIG_1 (CT_Dst[63:32])
   * Write CT_DST_SELECT field to select desired CT_Dst sources
   * Multiple CT_Dst can be selected by setting multiple bits
   * All-zero values in both registers disables the CT_Src output

2. Example: Route CT_Dst[0] to CT_Src[0]:
   * Write 0x00000001 to CT_SRC0_CONFIG_0 (offset 0x0)

3. Example: Route CT_Dst[0] and CT_Dst[1] to CT_Src[0] (OR together):
   * Write 0x00000003 to CT_SRC0_CONFIG_0 (offset 0x0)

4. Example: Route CT_Dst[35] to CT_Src[0] (port > 32):
   * Write 0x00000008 to CT_SRC0_CONFIG_1 (offset 0x4, bit 3 = CT_Dst[35])

5. Example: Broadcast CT_Dst[2] to multiple CT_Src:
   * Write 0x00000004 to CT_SRC0_CONFIG_0 (offset 0x0)
   * Write 0x00000004 to CT_SRC1_CONFIG_0 (offset 0x8)
   * Write 0x00000004 to CT_SRC2_CONFIG_0 (offset 0x10)

Configuration Examples
======================

Single Source Routing
---------------------

Route CT_Dst[0] to CT_Src[0]::

   Write CT_SRC0_CONFIG_0 = 0x00000001

Route CT_Dst[5] to CT_Src[3]::

   Write CT_SRC3_CONFIG_0 = 0x00000020  (bit 5 set)

Route CT_Dst[40] to CT_Src[2] (port > 32)::

   Write CT_SRC2_CONFIG_1 = 0x00000100  (bit 8 = CT_Dst[40])

Multi-Source ORing
------------------

Route CT_Dst[0] and CT_Dst[1] to CT_Src[0] (OR together)::

   Write CT_SRC0_CONFIG_0 = 0x00000003  (bits 0 and 1 set)

Route CT_Dst[0], CT_Dst[2], and CT_Dst[4] to CT_Src[1]::

   Write CT_SRC1_CONFIG_0 = 0x00000015  (bits 0, 2, 4 set)

Route CT_Dst[0] and CT_Dst[35] to CT_Src[0] (spanning both registers)::

   Write CT_SRC0_CONFIG_0 = 0x00000001  (CT_Dst[0])
   Write CT_SRC0_CONFIG_1 = 0x00000008  (CT_Dst[35], bit 3)

Broadcast
---------

Broadcast CT_Dst[2] to CT_Src[0], CT_Src[1], and CT_SRC[2]::

   Write CT_SRC0_CONFIG_0 = 0x00000004
   Write CT_SRC1_CONFIG_0 = 0x00000004
   Write CT_SRC2_CONFIG_0 = 0x00000004

Disable Output
--------------

Disable CT_Src[5] (no routing)::

   Write CT_SRC5_CONFIG_0 = 0x00000000
   Write CT_SRC5_CONFIG_1 = 0x00000000

Register Access
===============

Read Access
-----------

Read CT_SRC[i]_CONFIG_0 register::

   AXI4-Lite Read Transaction:
   - Address: 0x0 + (i * 8)
   - Returns: 32-bit CT_DST_SELECT field value for CT_Dst[31:0]

Read CT_SRC[i]_CONFIG_1 register::

   AXI4-Lite Read Transaction:
   - Address: 0x4 + (i * 8)
   - Returns: 32-bit CT_DST_SELECT field value for CT_Dst[63:32]

Write Access
------------

Write CT_SRC[i]_CONFIG_0 register::

   AXI4-Lite Write Transaction:
   - Address: 0x0 + (i * 8)
   - Data: 32-bit CT_DST_SELECT field value for CT_Dst[31:0]
   - Write strobe: 0xF (all bytes)

Write CT_SRC[i]_CONFIG_1 register::

   AXI4-Lite Write Transaction:
   - Address: 0x4 + (i * 8)
   - Data: 32-bit CT_DST_SELECT field value for CT_Dst[63:32]
   - Write strobe: 0xF (all bytes)

Register Generation
==================

Registers are generated from a SystemRDL template using the IP generation script:

.. code-block:: bash

   cd hw/ip/cross_trigger_matrix
   python3 generate_ip.py --num-ct-src <N> --num-ct-dst <M>

Where:
* ``<N>`` is the number of CT_Src ports (1-64, default: 4)
* ``<M>`` is the number of CT_Dst ports (1-64, default: 4)

The generation process:

1. **Template Processing**: Generates the SystemRDL register definition file (``rdl/cross_trigger_matrix.rdl``) from a Mako template based on ``NUM_CT_SRC`` and ``NUM_CT_DST`` parameters
2. **PeakRDL Processing**: Processes the generated RDL file to create all register-related files
3. **RTL Generation**: Generates RTL package and testbench with synchronized parameters

This generates:
* SystemRDL register definition (rdl/cross_trigger_matrix.rdl) - generated from template
* SystemVerilog RTL (rtl/cross_trigger_matrix_reg.sv)
* SystemVerilog package (rtl/cross_trigger_matrix_reg_pkg.sv)
* C header (c/cross_trigger_matrix_reg.h)
* Python header (py_headers/cross_trigger_matrix_reg.py)
* SystemVerilog header (svh/cross_trigger_matrix_reg.svh)
* reStructuredText documentation (rst/cross_trigger_matrix_reg.rst) - for Sphinx integration
* RTL package (rtl/cross_trigger_matrix_pkg.sv) - with DEFAULT_NUM_CT_SRC and DEFAULT_NUM_CT_DST
* Testbench (tb_vcs/tb_cross_trigger_matrix.sv) - with NUM_CT_SRC and NUM_CT_DST localparams

**Note**:
* Each CT_SRC uses two registers (CONFIG_0 and CONFIG_1) when NUM_CT_DST > 32, or one register (CONFIG_0) when NUM_CT_DST <= 32
* The number of register pairs generated matches the ``NUM_CT_SRC`` parameter (1-64)
* Each register pair uses 8 bytes of address space (CONFIG_0 at offset 0, CONFIG_1 at offset 4)
* The ``CT_DST_SELECT`` field in CONFIG_0 handles CT_Dst[31:0], CONFIG_1 handles CT_Dst[63:32]
* RTL parameters are automatically synchronized with register definitions
* The RST file is automatically included in the Sphinx documentation build

Register Field Access
====================

In SystemVerilog, register fields are accessed via the hwif_out structure:

.. code-block:: systemverilog

   import cross_trigger_matrix_reg_pkg::*;

   cross_trigger_matrix__out_t reg_out;

   // Access CT_SRC0_CONFIG_0.CT_DST_SELECT field (CT_Dst[31:0])
   logic [31:0] select_mask_lo = reg_out.CT_SRC0_CONFIG_0.CT_DST_SELECT.value;

   // Access CT_SRC0_CONFIG_1.CT_DST_SELECT field (CT_Dst[63:32])
   logic [NUM_CT_DST-33:0] select_mask_hi = reg_out.CT_SRC0_CONFIG_1.CT_DST_SELECT.value;

   // Combine both registers for full 64-bit select mask
   logic [NUM_CT_DST-1:0] select_mask = {select_mask_hi, select_mask_lo};

   // For NUM_CT_DST <= 32, only CONFIG_0 is needed
   logic [NUM_CT_DST-1:0] select_mask_simple = reg_out.CT_SRC5_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
