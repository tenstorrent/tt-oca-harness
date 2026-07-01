======================================
JTAG Interface Unit IP Documentation
======================================

.. toctree::
   :maxdepth: 3
   :caption: Contents:

   overview
   architecture
   integration

Overview
========

The JTAG Interface Unit (``jtag_intf_unit``) is a component-level wrapper module that provides a complete JTAG infrastructure for chiplet-level integration. It instantiates the JTAG Primary TAP (PTAP), a configurable chain of Secondary TAPs (STAPs) for multi-die and local connectivity, and an iJTAG Segment Insertion Bit (SIB) network for DFT and DFD access.

This module serves as the primary JTAG integration point in the Open Chiplet Harness (OCH), managing all JTAG-related interfaces including boundary scan, multi-die connectivity, debug instrument access, and system bus bridges.

Key Features
------------

* **PTAP Integration**: Complete JTAG Primary TAP with IEEE 1149.1/1687/1838 compliance
* **STAP Scan Chain**: Configurable chain of Secondary TAPs for multi-die architectures
* **iJTAG Network**: SIB-based access to DFT and DFD instrument networks
* **Chiplet I/O STAP**: Dedicated STAP for chiplet-to-chiplet JTAG connectivity
* **SEP Debug STAP**: Optional STAP for Security Engine Processor debug access
* **Extra STAPs**: Parameterized additional STAPs for local TAP connectivity
* **AXI Debug Interfaces**: JTAG-to-AXI bridges for SMC fabric, SMC OTP, and SEP OTP access

Architecture Highlights
-----------------------

The JTAG Interface Unit implements three primary data paths:

1. **STAP Scan Chain**: Serial scan chain connecting multiple STAPs for IEEE 1838 multi-die test access
2. **iJTAG Network**: SIB-controlled access to external DFT and DFD instruments
3. **AXI Debug Path**: JTAG2AXI bridges for system bus access (via PTAP)

Documentation Structure
=======================

This documentation is organized into the following sections:

* :doc:`overview` - System overview, requirements, and block diagram
* :doc:`architecture` - Detailed architecture of STAP chain and iJTAG network
* :doc:`integration` - Integration guidelines and instantiation examples

Quick Start
===========

To integrate the JTAG Interface Unit:

1. **Include RTL files** from ``hw/comp/jtag_intf_unit/rtl/`` and dependencies
2. **Configure parameters** for STAP enables and counts
3. **Connect interfaces**: JTAG TAP pins, BSR chain, STAP host interfaces, iJTAG networks, AXI buses
4. **Generate documentation** (optional)::

     cd hw/comp/jtag_intf_unit/doc
     make html

Related Documentation
=====================

* :doc:`JTAG PTAP </hw/ip/jtag_ptap/doc/index>` - Primary TAP implementation details
* :doc:`JTAG STAP </hw/ip/jtag_stap/doc/index>` - Secondary TAP interface details

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
