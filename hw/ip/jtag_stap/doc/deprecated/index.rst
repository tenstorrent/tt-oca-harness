JTAG STAP Interface IP Documentation
=====================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   architecture
   interface
   testing

Overview
========

The JTAG STAP (Secondary Test Access Port) Interface IP provides a scan chain interface module for integration into the OCH (Open Chiplet Harness) system. This IP serves as an interface for connecting to remote PTAPs (Primary Test Access Ports) on other chiplets or dies, as well as to local on-chip TAP controllers. It implements a flexible interface with optional pipeline stages, lockup latches, and a Segment Insertion Bit (SIB) for accessing the 3DCR (3-Die Control Register) control register.

Key Features
------------

* **Scan Chain Interface**: Full JTAG scan chain support for test and debug
* **3DCR Control Register**: 3-bit register for TMS hold, STAP selection, and configuration hold
* **Segment Insertion Bit (SIB)**: Mux-based SIB for accessing the 3DCR register
* **Optional Pipeline Stages**: Configurable scan input pipeline for timing optimization
* **Lockup Latches**: Optional TDI input and scan output lockup latches for timing control
* **TAP Control Management**: Host TAP control signal generation
* **Flexible Configuration**: Parameter-based feature selection

Quick Start
-----------

1. **Integration**: Include the JTAG STAP IP in your system design
2. **Configuration**: Set up parameters for optional features (SCAN_IN_PIPE, TDI_LOCKUP, SCAN_OUT_LOCKUP)
3. **Connection**: Connect client scan chain and TAP control interfaces
4. **Operation**: Access 3DCR register via scan chain for STAP configuration

.. note::
   This IP is designed for integration into multi-die JTAG architectures and requires
   proper understanding of scan chain protocols and timing requirements.

Use Cases
---------

**Remote PTAP Connection**: Interface to Primary Test Access Ports on remote chiplets or dies in multi-die systems

**Local TAP Controller Access**: Connect to on-chip TAP controllers for local test and debug operations

**Multi-Die JTAG Hierarchy**: Enable hierarchical JTAG control across multiple dies or chiplets

**Test Access**: Provide scan chain access for manufacturing test and system debug

**Configuration Control**: Dynamic control of TMS parking and STAP selection states via 3DCR register

**Timing Optimization**: Adjust pipeline and lockup stages for meeting timing constraints across die boundaries

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

