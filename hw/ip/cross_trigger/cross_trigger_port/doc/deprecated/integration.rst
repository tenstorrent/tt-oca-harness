============
Integration
============

This section describes how to integrate the Cross Trigger Port IP into a system.

GPIO Pad Integration
=====================

The CTP requires GPIO pads to be configured for cross triggering by the System Management Controller (SMC). The pad configuration depends on the operating mode.

Wire-OR Mode Pad Configuration
--------------------------------

In Wire-OR mode, one GPIO pad is used:

**CT_Req_out Pad**:
* Configured as open-drain output
* Output enable controlled by ct_req_out_dout_en_o
* Input enable controlled by ct_req_out_din_en_o
* Output data from ct_req_out_dout_o (static low, or high if inverted)
* Input data to ct_req_out_din_i
* Requires pull-up resistor (or active pull-up) when INVERT=0
* Requires pull-down resistor (or active pull-down) when INVERT=1

**Other pads**: Not used, can be configured as regular GPIO

Point-to-Point Mode Pad Configuration
--------------------------------------

In Point-to-Point mode, four GPIO pads are used:

**CT_Req_out Pad**:
* Configured as push-pull output
* Output enable always enabled
* Input enable disabled
* Output data from ct_req_out_dout_o

**CT_Req_in Pad**:
* Configured as input
* Input enable always enabled
* Input data to ct_req_in_din_i

**CT_Ack_in Pad**:
* Configured as input
* Input enable always enabled
* Input data to ct_ack_in_din_i

**CT_Ack_out Pad**:
* Configured as push-pull output
* Output enable always enabled
* Output data from ct_ack_out_dout_o

Chiplet Interconnection
========================

Wire-OR Mode
-------------

Multiple chiplets connect their CT_Req_out pads to a single shared wire:

.. code-block:: text

   Chiplet 1 CT_Req_out ──┐
   Chiplet 2 CT_Req_out ──┼── Shared Wire (with pull-up)
   Chiplet 3 CT_Req_out ──┘

Point-to-Point Mode
--------------------

Two chiplets cross-connect their pads:

.. code-block:: text

   Chiplet A                    Chiplet B
   CT_Req_out ────────────────> CT_Req_in
   CT_Ack_in  <──────────────── CT_Ack_out
   CT_Req_in  <──────────────── CT_Req_out
   CT_Ack_out ────────────────> CT_Ack_in

Clock and Reset
===============

**Clock**:
* Single clock input (clk_i)
* All internal logic synchronous to this clock
* GPIO pad inputs are asynchronous and synchronized internally

**Reset**:
* Active-low asynchronous reset (rst_ni)
* Resets all internal state machines and registers
* Register RESET bit provides logical reset for handshake only

Bus Interface
=============

The CTP uses AXI4-Lite interface for register access. The interface uses request and response structures with parameterized types defined in ``cross_trigger_port_pkg``:

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

   cross_trigger_port #(
       .axil_req_t(cross_trigger_port_pkg::ctp_axil_req_t),
       .axil_resp_t(cross_trigger_port_pkg::ctp_axil_resp_t)
   ) u_ctp (
       // ... port connections
   );

The default types use 32-bit address and data widths as defined in ``cross_trigger_port_pkg``.

Build Integration
=================

RTL Files
---------

Add the following RTL files to your build:

* ``rtl/cross_trigger_port_pkg.sv``
* ``rtl/cross_trigger_port.sv``
* ``rtl/ctp_synchronizer.sv``
* ``rtl/ctp_pulse_stretcher.sv``
* ``rtl/ctp_edge_detector.sv``
* ``rtl/ctp_handshake_ctrl.sv``
* ``data/registers/rtl/cross_trigger_port_reg.sv`` (generated)
* ``data/registers/rtl/cross_trigger_port_reg_pkg.sv`` (generated)

Dependencies
------------

The CTP depends on primitives from hw/common:

* ``prim_flop_2sync`` (from prim/rtl)
* ``prim_edge_detector`` (from prim/rtl)

Register Generation
-------------------

Before building, generate register files:

.. code-block:: bash

   cd hw/ip/cross_trigger_port/data/registers
   ./generate_register_files.sh

This requires:
* PeakRDL (pip install systemrdl-compiler peakrdl-regblock)
* SystemRDL source file (rdl/cross_trigger_port.rdl)

Synthesis Constraints
=====================

See ``syn/cross_trigger_port.sdc`` for timing constraints:

* Clock definitions
* False paths for asynchronous inputs
* Multi-cycle paths where appropriate
* I/O delays for pad interfaces

Usage Example
=============

Basic instantiation:

.. code-block:: systemverilog

   cross_trigger_port u_ctp (
       .clk_i              (clk),
       .rst_ni             (rst_n),

       // AXI-Lite interface
       .axil_req_i         (axil_req),
       .axil_resp_o        (axil_resp),

       // Core-side interface
       .ct_src_i           (debug_trigger),
       .ct_dst_o           (received_trigger),
       .busy_o             (ctp_busy),

       // GPIO pad interface
       .ct_req_out_dout_en_o (gpio_req_out_oen),
       .ct_req_out_din_en_o  (gpio_req_out_ien),
       .ct_req_out_dout_o    (gpio_req_out_dout),
       .ct_req_out_din_i     (gpio_req_out_din),

       .ct_req_in_din_en_o  (gpio_req_in_ien),
       .ct_req_in_din_i     (gpio_req_in_din),

       .ct_ack_in_din_en_o  (gpio_ack_in_ien),
       .ct_ack_in_din_i     (gpio_ack_in_din),

       .ct_ack_out_dout_en_o (gpio_ack_out_oen),
       .ct_ack_out_dout_o    (gpio_ack_out_dout)
   );
