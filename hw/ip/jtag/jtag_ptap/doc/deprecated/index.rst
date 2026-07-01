=================================
JTAG Primary TAP IP Documentation
=================================

.. toctree::
   :maxdepth: 3
   :caption: Contents:

   overview
   architecture
   instruction_set
   register_interface
   implementation
   integration
   verification

Overview
========

The JTAG Primary TAP (PTAP) is the main Test Access Port controller for the Open Chiplet Harness (OCH) system. It implements a comprehensive JTAG interface compliant with IEEE 1149.1, IEEE 1687 (iJTAG), and IEEE 1838 (3D test) standards. The PTAP serves as the primary interface for debug, test, and configuration access to the chiplet, providing connectivity to boundary scan chains, internal test data registers, iJTAG networks, and AXI bus interfaces.

Key Features
------------

* **IEEE 1149.1 Compliance**: Full support for standard JTAG instructions including BYPASS, IDCODE, EXTEST, SAMPLE/PRELOAD, INTEST, and optional instructions
* **IEEE 1838 (3D Test) Support**: TAP 3DCR register for multi-die JTAG hierarchies with STAP (Secondary TAP) selection
* **IEEE 1687 (iJTAG) Support**: SELECT_IJTAG instruction for accessing embedded test instruments
* **Test Mode Persistence (TMP)**: IEEE 1149.1 Section 16 compliant persistence controller with CLAMP_HOLD/CLAMP_RELEASE
* **IC_RESET Control**: IEEE 1149.1 Section 17 compliant integrated circuit reset control
* **JTAG-to-AXI Bridge**: Multiple JTAG2AXI interfaces for system bus access (SMC fabric, SMC OTP, SEP OTP)
* **Parameterized Design**: Configurable instruction and feature set based on system requirements
* **Boundary Scan Interface**: Connects to external BSR (Boundary Scan Register) chain
* **Debug Control Interface**: Clock stop and boot stall control via DEBUG_CONTROL register

Architecture Highlights
-----------------------

The PTAP implements a modular design:

1. **TAP Controller**: IEEE 1149.1 compliant state machine with TMP extensions
2. **Instruction Register**: 6-bit instruction register with decoded outputs
3. **Data Registers**: Multiple TDRs including IDCODE, BYPASS, 3DCR, IC_RESET, DEBUG_CTRL, CAPS
4. **JTAG2AXI Interfaces**: Bridge modules for AXI bus transactions
5. **TDO Multiplexer**: IEEE 1149.1 Section 4.4 compliant data output selection
6. **STAP Interface**: IEEE 1838 compliant secondary TAP connectivity

Documentation Structure
=======================

This documentation is organized into the following sections:

* :doc:`overview` - System overview, requirements, and key features
* :doc:`architecture` - Detailed architectural description and block diagrams
* :doc:`instruction_set` - Complete JTAG instruction set and encoding
* :doc:`register_interface` - Data register definitions and bit fields
* :doc:`implementation` - Module implementation details and interfaces
* :doc:`integration` - Build flow, synthesis, and integration guidelines
* :doc:`verification` - Testbench descriptions and verification approach

Quick Start
===========

To integrate the JTAG PTAP:

1. **Include RTL files** from ``hw/ip/jtag_ptap/rtl/`` in your build
2. **Configure parameters** based on your system requirements
3. **Connect interfaces**: JTAG pins, BSR chain, iJTAG network, AXI buses
4. **Generate documentation** (optional)::

     cd hw/ip/jtag_ptap/doc
     make html

Standards Compliance
====================

The PTAP implements features from the following standards:

* **IEEE 1149.1-2013**: Standard Test Access Port and Boundary-Scan Architecture
* **IEEE 1687-2014**: Standard for Access and Control of Instrumentation Embedded within a Semiconductor Device
* **IEEE 1838-2019**: Standard for Test Access Architecture for Three-Dimensional Stacked Integrated Circuits

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
