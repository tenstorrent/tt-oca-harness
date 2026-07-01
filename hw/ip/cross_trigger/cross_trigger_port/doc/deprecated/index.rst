======================================
Cross Trigger Port IP Documentation
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

The Cross Trigger Port (CTP) is a module that controls the sending and receiving of cross triggers between chiplets using GPIO pads. Cross triggers are pulses sent and received by debug modules within the functional core of a chiplet. Each CTP connects to four separate I/O pads for inter-chiplet cross triggering.

Key Features
------------

* **Dual Mode Operation**: Supports both Wire-OR and Point-to-Point modes
* **Wire-OR Mode**: 1-wire cross trigger signaling compatible with existing implementations
* **Point-to-Point Mode**: Four-phase handshaking for reliable synchronization
* **Pulse Stretching**: Configurable pulse width for Wire-OR mode to ensure all chiplets see triggers
* **Signal Inversion**: Optional inversion of all I/O signals for different pad configurations
* **SystemRDL Interface**: Complete register-based configuration and status monitoring
* **Glitch-Free Operation**: All outputs registered to prevent glitches

Architecture Highlights
-----------------------

The CTP implements a modular design:

1. **Synchronization**: All asynchronous GPIO inputs synchronized to core clock
2. **Pulse Stretching**: Configurable pulse width extension for Wire-OR mode
3. **Edge Detection**: Positive edge detection for Point-to-Point mode handshaking
4. **Handshake Control**: Four-phase handshake state machine for Point-to-Point mode
5. **Mode Multiplexing**: Seamless switching between Wire-OR and Point-to-Point modes

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

To get started with the Cross Trigger Port:

1. **Generate register files**::

     cd hw/ip/cross_trigger_port/data/registers
     ./generate_register_files.sh

2. **Build the design**::

     # Add RTL files to your build system

3. **Generate documentation**::

     cd doc
     make html

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
