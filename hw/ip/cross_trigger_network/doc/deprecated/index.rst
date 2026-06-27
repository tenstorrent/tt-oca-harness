========================================
Cross Trigger Network IP Documentation
========================================

.. toctree::
   :maxdepth: 3
   :caption: Contents:

   overview
   architecture
   implementation
   integration
   verification

Overview
========

The Cross Trigger Network (CTN) is a component-level module that aggregates cross trigger functionality within the Debug and Test Ports (DTP). It provides a unified interface for managing both external (die-to-die) and internal cross trigger signals.

Key Features
------------

* **External Cross Trigger Ports**: Configurable number of CTPs (default 16) for GPIO-based die-to-die cross triggering
* **Internal Cross Trigger Ports**: Configurable number of internal CTPs for on-chip cross triggering with CLAs and other debug modules
* **Cross Trigger Matrix**: Flexible routing of cross trigger signals between all CTPs
* **Clock Stop Control**: Aggregates clock stop requests with programmable gating
* **AXI-Lite Interface**: Unified CSR access through an integrated crossbar

Architecture Highlights
-----------------------

The CTN implements a modular design:

1. **External CTPs**: Full Cross Trigger Port modules with CSRs for die-to-die triggering
2. **Internal CTPs**: Core-only CTP modules (no CSRs) with static configuration
3. **CTM**: Cross Trigger Matrix for routing triggers between all CTPs
4. **AXI-Lite Crossbar**: Routes CSR access to external CTPs and CTM
5. **Clock Stop Control**: OR-tree aggregation with JTAG gating

Documentation Structure
=======================

This documentation is organized into the following sections:

* :doc:`overview` - System overview, requirements, and key features
* :doc:`architecture` - Detailed architectural description and block diagrams
* :doc:`implementation` - Module implementation details and interfaces
* :doc:`integration` - Build flow, synthesis, and DTP integration guidelines
* :doc:`verification` - Testbench descriptions and verification results

Quick Start
===========

To configure the Cross Trigger Network:

1. **Run the configuration script**::

     cd hw/comp/cross_trigger_network
     ./generate_comp.py --num-ctp 16 --num-int-ct 1

2. **Integrate into DTP**::

     # The CTN is instantiated within the DTP module
     # See integration.rst for details

3. **Generate documentation**::

     cd doc
     make html

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
