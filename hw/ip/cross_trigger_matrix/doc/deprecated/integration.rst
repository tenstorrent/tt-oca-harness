============
Integration
============

This section describes how to integrate the Cross Trigger Matrix IP into a system.

Clock and Reset
===============

**Clock**:
* Single clock input (clk_i)
* All internal logic synchronous to this clock
* CT_Dst inputs are synchronous to this clock

**Reset**:
* Active-low asynchronous reset (rst_ni)
* Resets all internal registers and state
* Register values reset to default (all-zero)

Bus Interface
=============

The CTM uses AXI4-Lite interface for register access. The interface uses request and response structures with parameterized types defined in ``cross_trigger_matrix_pkg``:

* **axil_req_i**: AXI-Lite request structure containing:
  * Write address channel: ``aw.addr``, ``aw.prot``, ``aw_valid``
  * Write data channel: ``w.data``, ``w.strb``, ``w_valid``
  * Write response ready: ``b_ready``
  * Read address channel: ``ar.addr``, ``ar.prot``, ``ar_valid``
  * Read data ready: ``r_ready``
* **axil_resp_o**: AXI-Lite response structure containing:
  * Write address ready: ``aw_ready``
  * Write data ready: ``w_ready``
  * Write response: ``b.resp``, ``b_valid``
  * Read address ready: ``ar_ready``
  * Read data: ``r.data``, ``r.resp``, ``r_valid``

The bus interface types are parameterized to allow different implementations:

.. code-block:: systemverilog

   cross_trigger_matrix #(
       .NUM_CT_SRC(8),
       .NUM_CT_DST(8),
       .axil_req_t(cross_trigger_matrix_pkg::ctm_axil_req_t),
       .axil_resp_t(cross_trigger_matrix_pkg::ctm_axil_resp_t)
   ) u_ctm (
       // ... port connections
   );

The default types use 32-bit address and data widths as defined in ``cross_trigger_matrix_pkg``.

Build Integration
=================

RTL Files
---------

Add the following RTL files to your build:

* ``rtl/cross_trigger_matrix_pkg.sv`` (generated from template)
* ``rtl/cross_trigger_matrix.sv`` (generated from template)
* ``rtl/ctm_src_selector.sv``
* ``data/registers/rtl/cross_trigger_matrix_reg.sv`` (generated)
* ``data/registers/rtl/cross_trigger_matrix_reg_pkg.sv`` (generated)

**Note**: The main RTL module (``cross_trigger_matrix.sv``) is generated from a template to ensure the case statements match the configured NUM_CT_SRC exactly.

Dependencies
------------

The CTM depends on:

* AXI package (``hw/common/axi/`` or equivalent)
* AXI typedef macros (``axi/typedef.svh``)

Register Generation
-------------------

Before building, generate register files using the IP generation script:

.. code-block:: bash

   cd hw/ip/cross_trigger_matrix
   python3 generate_ip.py --num-ct-src <N> --num-ct-dst <M>

Where:
* ``<N>`` is the number of CT_Src ports (1-64, default: 4)
* ``<M>`` is the number of CT_Dst ports (1-64, default: 4)

This script:

1. Generates the SystemRDL register definition file from a template based on ``NUM_CT_SRC`` and ``NUM_CT_DST``
2. Generates all register-related files (RTL, headers, documentation) using PeakRDL
3. Generates main RTL module (``rtl/cross_trigger_matrix.sv``) with case statements matching ``NUM_CT_SRC``
4. Generates RTL package (``rtl/cross_trigger_matrix_pkg.sv``) with ``DEFAULT_NUM_CT_SRC`` and ``DEFAULT_NUM_CT_DST`` matching the generation parameters
5. Generates testbench (``tb_vcs/tb_cross_trigger_matrix.sv``) with ``NUM_CT_SRC`` and ``NUM_CT_DST`` localparams matching the generation parameters

The ``CT_DST_SELECT`` field width in each register matches ``NUM_CT_DST`` (bits [M-1:0]), with bits [31:M] reserved when M < 32.

**Important**: The main RTL module, RTL package, and testbench are all generated from templates and automatically synchronized with the register definitions. This ensures consistency between the register map and RTL, and prevents compilation errors from referencing non-existent register fields.

Alternatively, you can generate register files directly:

.. code-block:: bash

   cd hw/ip/cross_trigger_matrix/data/registers
   ./generate_register_files.sh

**Note**: The direct method only generates register files. The recommended approach is to use ``generate_ip.py`` which ensures the RDL file, main RTL module, RTL package, and testbench all match your ``NUM_CT_SRC`` and ``NUM_CT_DST`` parameters.

This requires:
* Python 3 with Mako template library (pip install mako)
* PeakRDL (pip install systemrdl-compiler peakrdl-regblock)
* SystemRDL template file (data/registers/rdl/templates/cross_trigger_matrix.rdl.tpl)
* OCH_ROOT environment variable set

Synthesis Constraints
=====================

See ``syn/cross_trigger_matrix.sdc`` for timing constraints:

* Clock definitions
* Input/output delays
* False paths if any
* Multi-cycle paths if any

Usage Example
=============

Basic instantiation:

.. code-block:: systemverilog

   cross_trigger_matrix #(
       .NUM_CT_SRC(4),
       .NUM_CT_DST(4)
   ) u_ctm (
       .clk_i              (clk),
       .rst_ni             (rst_n),

       // AXI-Lite interface
       .axil_req_i         (axil_req),
       .axil_resp_o        (axil_resp),

       // Cross trigger interface
       .ct_dst_i           (ct_dst_inputs),
       .ct_src_o           (ct_src_outputs)
   );

Configuration Example
=====================

Configure routing after reset:

.. code-block:: systemverilog

   // Route CT_Dst[0] to CT_Src[0]
   write_register(CTM_BASE_ADDR + 0x0, 32'h00000001);

   // Route CT_Dst[1] and CT_Dst[2] to CT_Src[1] (OR together)
   write_register(CTM_BASE_ADDR + 0x4, 32'h00000006);

   // Broadcast CT_Dst[3] to CT_Src[2] and CT_Src[3]
   write_register(CTM_BASE_ADDR + 0x8, 32'h00000008);
   write_register(CTM_BASE_ADDR + 0xC, 32'h00000008);

Parameter Selection
===================

Choose appropriate parameters based on system requirements:

* **NUM_CT_SRC**: Number of CT_Src output ports needed (1-64)
* **NUM_CT_DST**: Number of CT_Dst input ports needed (1-64)
* Typical configurations: 4x4, 8x8, 16x16
* Maximum configuration: 32x32

Address Space
=============

The CTM register space:

* Base address: System-dependent (assigned by system integrator)
* Address range: Base + 0x0 to Base + (NUM_CT_SRC * 8 - 1) bytes
* Each CT_SRC uses 8 bytes (two 4-byte registers)
* Register addresses:
  * CONFIG_0: Base + (i * 8) for CT_SRC[i]_CONFIG_0 (CT_Dst[31:0])
  * CONFIG_1: Base + (i * 8) + 4 for CT_SRC[i]_CONFIG_1 (CT_Dst[63:32], only when NUM_CT_DST > 32)
* Total address space: NUM_CT_SRC * 8 bytes (e.g., 32 bytes for NUM_CT_SRC=4, 256 bytes for NUM_CT_SRC=32, 512 bytes for NUM_CT_SRC=64)
