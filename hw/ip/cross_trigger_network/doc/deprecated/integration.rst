===========
Integration
===========

DTP Integration
===============

The CTN is designed to be instantiated within the Debug and Test Ports (DTP) module.

Instantiation Example
---------------------

.. code-block:: systemverilog

    cross_trigger_network #(
        .INT_CT_MODE      (XTRIG_INT_CT_MODE),
        .axil_req_t       (xtrig_axil_req_t),
        .axil_resp_t      (xtrig_axil_resp_t)
    ) u_cross_trigger_network (
        .clk_i               (clk_i),
        .rst_ni              (rst_n_i),

        // AXI-Lite CSR interface
        .axil_req_i          (axil_xtrig_req_i),
        .axil_resp_o         (axil_xtrig_resp_o),

        // Clock stop control
        .clk_stop_req_i      (xtrig_clk_stop_req_i),
        .cla_clock_stop_en_i (cla_clock_stop_en),
        .jtag_clock_stop_i   (jtag_clock_stop),
        .stop_clks_o         (cla_clock_stop),

        // Internal cross trigger interface
        .ctm_src_req_o       (xtrig_ctm_src_req_o),
        .ctm_src_ack_i       (xtrig_ctm_src_ack_i),
        .ctm_dst_req_i       (xtrig_ctm_dst_req_i),
        .ctm_dst_ack_o       (xtrig_ctm_dst_ack_o),

        // External CTP GPIO interface
        .ctp_req_out_dout_o    (xtrig_ctp_req_out_dout_o),
        .ctp_req_out_dout_en_o (xtrig_ctp_req_out_dout_en_o),
        .ctp_req_out_din_i     (xtrig_ctp_req_out_din_i),
        .ctp_req_out_din_en_o  (xtrig_ctp_req_out_din_en_o),
        .ctp_req_in_dout_o     (xtrig_ctp_req_in_dout_o),
        .ctp_req_in_dout_en_o  (xtrig_ctp_req_in_dout_en_o),
        .ctp_req_in_din_i      (xtrig_ctp_req_in_din_i),
        .ctp_req_in_din_en_o   (xtrig_ctp_req_in_din_en_o),
        .ctp_ack_in_dout_o     (xtrig_ctp_ack_in_dout_o),
        .ctp_ack_in_dout_en_o  (xtrig_ctp_ack_in_dout_en_o),
        .ctp_ack_in_din_i      (xtrig_ctp_ack_in_din_i),
        .ctp_ack_in_din_en_o   (xtrig_ctp_ack_in_din_en_o),
        .ctp_ack_out_dout_o    (xtrig_ctp_ack_out_dout_o),
        .ctp_ack_out_dout_en_o (xtrig_ctp_ack_out_dout_en_o),
        .ctp_ack_out_din_i     (xtrig_ctp_ack_out_din_i),
        .ctp_ack_out_din_en_o  (xtrig_ctp_ack_out_din_en_o)
    );

DTP Signal Mapping
------------------

The following DTP ports map to CTN ports:

+-------------------------+---------------------------+
| DTP Port                | CTN Port                  |
+=========================+===========================+
| axil_xtrig_req_i        | axil_req_i                |
+-------------------------+---------------------------+
| axil_xtrig_resp_o       | axil_resp_o               |
+-------------------------+---------------------------+
| xtrig_clk_stop_req_i    | clk_stop_req_i            |
+-------------------------+---------------------------+
| xtrig_ctm_src_req_o     | ctm_src_req_o             |
+-------------------------+---------------------------+
| xtrig_ctm_src_ack_i     | ctm_src_ack_i             |
+-------------------------+---------------------------+
| xtrig_ctm_dst_req_i     | ctm_dst_req_i             |
+-------------------------+---------------------------+
| xtrig_ctm_dst_ack_o     | ctm_dst_ack_o             |
+-------------------------+---------------------------+
| xtrig_ctp_*             | ctp_*                     |
+-------------------------+---------------------------+

Configuration
=============

Pre-Synthesis Configuration
---------------------------

Run the configuration script before synthesis to generate CTM files:

.. code-block:: bash

    cd hw/comp/cross_trigger_network
    ./generate_comp.py --num-ctp 16 --num-int-ct 1

This will:

1. Generate CTM source files for the specified port count:

   * SystemRDL register definitions
   * Main RTL module with matching case statements
   * RTL package with default parameters
   * Register RTL and headers

2. Generate CTN testbench files:

   * ``tb_vcs/tb_cross_trigger_network.sv`` - Testbench with matching NUM_CTP/NUM_INT_CT
   * ``tb_vcs/test/test_base.py`` - Test utilities with dynamic address calculations

3. Display the address map for reference

**Note**: Both the CTM and CTN testbench are generated from templates, ensuring consistency between the RTL configuration and testbench parameters.

Build Flow
==========

File Lists
----------

Include the following files in your build:

1. CTN RTL files::

    hw/comp/cross_trigger_network/rtl/cross_trigger_network_pkg.sv
    hw/comp/cross_trigger_network/rtl/ctn_clock_stop_ctrl.sv
    hw/comp/cross_trigger_network/rtl/cross_trigger_network.sv

2. CTP RTL files (from hw/ip/cross_trigger_port/rtl/)
3. CTM RTL files (from hw/ip/cross_trigger_matrix/rtl/)
4. AXI infrastructure files (from deps/axi/src/)

Include Paths
-------------

Ensure the following include paths are set:

* ``deps/axi/include`` - For AXI typedef macros

Synthesis Constraints
=====================

Timing
------

The CTN should be constrained with the system clock. Key paths:

* AXI-Lite crossbar: Single-cycle transactions
* Cross trigger routing: Combinational within CTM
* Clock stop output: Single FF, minimal timing impact

Area
----

The CTN area scales with:

* NUM_CTP: Linear (one CTP per external port)
* NUM_INT_CT: Linear (one core CTP per internal port)
* CTM routing: Quadratic with total port count

Example SDC constraints are provided in ``syn/cross_trigger_network.sdc``.
