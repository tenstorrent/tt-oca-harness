======================================
Cross Trigger Matrix IP Documentation
======================================

.. toctree::
   :maxdepth: 3
   :caption: Contents:

   overview
   architecture
   implementation
   register_interface
   verification
   integration

Overview
========

The Cross Trigger Matrix (CTM) is a crossbar that aggregates and statically routes cross trigger pulses between various sources and sinks. Typical connections to the CTM include Core Logic Analyzers (CLAs) and Cross Trigger Ports (CTPs), including other miscellaneous devices. The CTM is compatible with CTPs operating in either of the two signaling modes, point-to-point or wire-OR. Typically, each device or logic module connected to the CTM will act as both a source and a sink for cross trigger pulses.

Key Features
------------

* **Configurable Crossbar**: Route M source ports (CT_Dst) to N sink ports (CT_Src)
* **Multi-Source ORing**: Each CT_Src can select and OR together multiple CT_Dst sources
* **Parameterized Design**: Supports 1-64 CT_Src outputs and 1-64 CT_Dst inputs
* **Register-Based Configuration**: SystemRDL-based registers with AXI4-Lite interface
* **Glitch-Free Operation**: All combinatorial outputs registered to prevent glitches
* **Static Routing**: Runtime configuration via CSRs minimizes trigger latency

Architecture Highlights
-----------------------

The CTM implements a modular design:

1. **Register Interface**: AXI4-Lite bus with parameterized types for flexibility
2. **Source Selectors**: One selector module per CT_Src port for independent configuration
3. **Selection Logic**: Bit-mask based selection of CT_Dst sources
4. **OR Aggregation**: Selected sources are OR'd together to produce CT_Src output
5. **Registered Outputs**: All CT_Src outputs registered to prevent glitches

Documentation Structure
======================

This documentation is organized into the following sections:

* :doc:`overview` - System overview, requirements, and key features
* :doc:`architecture` - Detailed architectural description and block diagrams
* :doc:`implementation` - Module implementation details and interfaces
* :doc:`register_interface` - Complete register map and programming model
* :doc:`verification` - Testbench descriptions and verification results
* :doc:`integration` - Build flow, synthesis, and integration guidelines

Quick Start
===========

To get started with the Cross Trigger Matrix:

1. **Generate IP files** (registers, RTL package, testbench)::

     cd hw/ip/cross_trigger_matrix
     python3 generate_ip.py --num-ct-src <N> --num-ct-dst <M>

   Where ``<N>`` and ``<M>`` are the number of CT_Src and CT_Dst ports (1-64, default: 4).

2. **Build the design**::

     # Add RTL files to your build system

3. **Run tests**::

     cd tb_vcs
     make test

4. **Generate documentation**::

     cd doc
     make html

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
