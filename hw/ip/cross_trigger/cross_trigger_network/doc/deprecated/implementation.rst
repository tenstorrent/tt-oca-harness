==============
Implementation
==============

Module Hierarchy
================

The CTN module hierarchy is as follows::

    cross_trigger_network
    ├── u_axil_xbar (axi_lite_xbar)
    ├── gen_ext_ctp[0..NUM_CTP-1]
    │   └── u_ctp (cross_trigger_port)
    │       └── u_core (cross_trigger_port_core)
    │       └── u_reg (cross_trigger_port_reg)
    ├── gen_int_ctp[0..NUM_INT_CT-1]
    │   └── u_int_ctp_core (cross_trigger_port_core)
    ├── u_ctm (cross_trigger_matrix)
    │   └── gen_src_selectors[0..NUM_CTM_PORTS-1]
    │       └── u_src_selector (ctm_src_selector)
    │   └── u_reg (cross_trigger_matrix_reg)
    └── u_clock_stop_ctrl (ctn_clock_stop_ctrl)

Source Files
============

RTL Files
---------

+--------------------------------+-------------------------------------------+
| File                           | Description                               |
+================================+===========================================+
| cross_trigger_network_pkg.sv   | Package with types and parameters         |
+--------------------------------+-------------------------------------------+
| cross_trigger_network.sv       | Top-level CTN module                      |
+--------------------------------+-------------------------------------------+
| ctn_clock_stop_ctrl.sv         | Clock stop aggregation module             |
+--------------------------------+-------------------------------------------+

Dependencies
------------

The CTN depends on the following IPs:

* ``hw/ip/cross_trigger_port`` - Cross Trigger Port IP
* ``hw/ip/cross_trigger_matrix`` - Cross Trigger Matrix IP
* ``deps/axi`` - AXI infrastructure (axi_lite_xbar)

Module Interfaces
=================

cross_trigger_network
---------------------

Parameters
^^^^^^^^^^

.. code-block:: systemverilog

    parameter logic [DEFAULT_NUM_INT_CT-1:0] INT_CT_MODE = '0  // Internal CTP modes
    parameter type axil_req_t = ctn_axil_req_t   // AXI-Lite request type
    parameter type axil_resp_t = ctn_axil_resp_t // AXI-Lite response type

Ports
^^^^^

.. code-block:: systemverilog

    // Global
    input  logic clk_i
    input  logic rst_ni

    // AXI-Lite CSR Interface
    input  axil_req_t  axil_req_i
    output axil_resp_t axil_resp_o

    // Clock Stop Interface
    input  logic [NUM_CLK_STOP_REQ-1:0] clk_stop_req_i
    input  logic cla_clock_stop_en_i
    input  logic jtag_clock_stop_i
    output logic stop_clks_o

    // Internal Cross Trigger Interface
    output logic [NUM_INT_CT-1:0] ctm_src_req_o
    input  logic [NUM_INT_CT-1:0] ctm_src_ack_i
    input  logic [NUM_INT_CT-1:0] ctm_dst_req_i
    output logic [NUM_INT_CT-1:0] ctm_dst_ack_o

    // External CTP GPIO Interface (per CTP)
    // CT_Req_out, CT_Req_in, CT_Ack_in, CT_Ack_out

ctn_clock_stop_ctrl
-------------------

Parameters
^^^^^^^^^^

.. code-block:: systemverilog

    // NUM_CLK_STOP_REQ is a templated localparam from cross_trigger_network_pkg
    localparam int unsigned NUM_CLK_STOP_REQ = DEFAULT_NUM_CLK_STOP_REQ

Ports
^^^^^

.. code-block:: systemverilog

    input  logic clk_i
    input  logic rst_ni
    input  logic [NUM_CLK_STOP_REQ-1:0] clk_stop_req_i
    input  logic cla_clock_stop_en_i
    input  logic jtag_clock_stop_i
    output logic stop_clks_o

Internal Signal Connections
===========================

Cross Trigger Signals
---------------------

The CTM ports are connected as follows:

.. code-block:: systemverilog

    // External CTPs (indices 0 to NUM_CTP-1)
    ctm_ct_dst[i] = gen_ext_ctp[i].u_ctp.ct_dst_o
    gen_ext_ctp[i].u_ctp.ct_src_i = ctm_ct_src[i]

    // Internal CTPs (indices NUM_CTP to NUM_CTP+NUM_INT_CT-1)
    ctm_ct_dst[NUM_CTP+i] = gen_int_ctp[i].u_int_ctp_core.ct_dst_o
    gen_int_ctp[i].u_int_ctp_core.ct_src_i = ctm_ct_src[NUM_CTP+i]

Internal CTP Interface Signals
------------------------------

Internal CTP signal routing is mode-dependent:

.. code-block:: systemverilog

    // Mode-specific signal routing (generated per internal CTP)
    if (MODE_WIRE_OR) begin : gen_wire_or_signals
        // Wire-OR mode: dout_en indicates stretched pulse
        assign ctm_src_req_o[i]   = int_ct_req_out_dout_en;
        assign int_ct_req_out_din = ctm_dst_req_i[i];
        assign int_ct_req_in_din  = 1'b0;  // Unused
        assign int_ct_ack_in_din  = 1'b0;  // Unused
        assign ctm_dst_ack_o[i]   = 1'b0;  // Unused
    end else begin : gen_p2p_signals
        // P2P mode: full handshake
        assign ctm_src_req_o[i]   = int_ct_req_out_dout;
        assign int_ct_req_out_din = 1'b0;  // Unused
        assign int_ct_req_in_din  = ctm_dst_req_i[i];
        assign int_ct_ack_in_din  = ctm_src_ack_i[i];
        assign ctm_dst_ack_o[i]   = int_ct_ack_out_dout;
    end

AXI-Lite Crossbar Connections
-----------------------------

.. code-block:: systemverilog

    // CTM gets port 0 (address 0x0000-0x01FF, 512 bytes)
    u_ctm.axil_req_i = xbar_mst_req[0]
    xbar_mst_resp[0] = u_ctm.axil_resp_o

    // External CTPs get ports 1 to NUM_CTP (addresses 0x0200+, 16 bytes each)
    gen_ext_ctp[i].u_ctp.axil_req_i = xbar_mst_req[i + 1]
    xbar_mst_resp[i + 1] = gen_ext_ctp[i].u_ctp.axil_resp_o

Design Considerations
=====================

Timing
------

* All outputs are registered for glitch-free operation
* Clock stop output has single-cycle latency
* CTM routing is combinational within the matrix

Resource Usage
--------------

* External CTPs: Full CTP with CSRs (~200 FFs each typical)
* Internal CTPs: Core-only (~100 FFs each typical)
* CTM: Scales with NUM_CTM_PORTS² for full connectivity
* Crossbar: Scales linearly with NUM_CTP

Reset
-----

* Active-low asynchronous reset (rst_ni)
* All registered outputs reset to safe states
* Clock stop output resets to 0 (clocks running)
