========
Overview
========

The JTAG Interface Unit is the top-level JTAG integration component for the Open Chiplet Harness (OCH) system. It provides a unified interface that combines the JTAG Primary TAP (PTAP) with configurable Secondary TAP (STAP) chains and iJTAG SIB networks, presenting a single integration point for all JTAG-related functionality.

System Requirements
===================

The JTAG Interface Unit is designed to meet the following requirements:

Functionality
-------------

* Provide primary JTAG TAP interface for debug and test access
* Support IEEE 1838 multi-die architectures via STAP scan chain
* Enable IEEE 1687 iJTAG instrument access via SIB network
* Support chiplet-to-chiplet JTAG connectivity
* Provide debug access to SEP (Security Engine Processor)
* Enable parameterized extra STAPs for local connectivity
* Expose JTAG-to-AXI bridges for system bus access

Performance
-----------

* TCK clock frequency: System dependent (typically 10-50 MHz)
* Single-cycle data register shifts
* TDO retimed to falling edge of TCK per IEEE 1149.1
* Minimal latency through STAP chain (lockup latches optional)

Interface Summary
-----------------

* **Primary JTAG TAP**: Standard client interface to external JTAG controller
* **Boundary Scan**: Host interface to external BSR chain
* **STAP Interfaces**: Multiple host TAP interfaces for multi-die connectivity
* **iJTAG Interfaces**: SIB-controlled scan interfaces for DFT and DFD
* **AXI Interfaces**: Debug access to SMC fabric, SMC OTP, and SEP OTP
* **Control Outputs**: Clock stop, boot stall, IC reset controls

Block Diagram
=============

The following diagram shows the high-level structure of the JTAG Interface Unit:

.. code-block:: text

                           ┌───────────────────────────────────────────────────────────────────────┐
                           │                        JTAG Interface Unit                            │
                           │                                                                       │
    JTAG TAP Control ──────┤    ┌─────────────────────────────────────────────────────────────┐    │
    TDI ───────────────────┤    │                    JTAG PTAP                                │    │
                           │    │  • TAP Controller    • Instruction Register                 │    │
                           │    │  • Data Registers    • TMP Controller                       │    │
                           │    │  • JTAG2AXI Bridges  • TDO Multiplexer                      │    │
    TDO ◀──────────────────┤    └────┬────────────────────┬───────────────────┬───────────────┘    │
                           │         │                    │                   │                    │
                           │    BSR Scan          STAP Scan             iJTAG Scan                 │
                           │    Interface         Interface             Interface                  │
                           │         │                    │                   │                    │
                           │         ▼                    ▼                   ▼                    │
                           │    ┌─────────┐    ┌──────────────────────┐    ┌──────────────────┐    │
    BSR Chain ◀────────────┤    │External │    │   STAP Scan Chain    │    │  iJTAG Network   │    │
                           │    │BSR Chain│    │  ┌─────────────────┐ │    │                  │    │
                           │    └─────────┘    │  │ I/O STAP        │ │    │  ┌────────────┐  │    │
                           │                   │  │ (chiplet conn)  │ │    │  │  DFT SIB   │  │    │
    I/O STAP Host ◀────────┤                   │  └────────┬────────┘ │    │  └──────┬─────┘  │    │
                           │                   │           │          │    │         │        │    │
                           │                   │  ┌────────▼────────┐ │    │  ┌──────▼─────┐  │    │
    SEP STAP Host ◀────────┤                   │  │ SEP Debug STAP  │ │    │  │  DFD SIB   │  │    │
                           │                   │  └────────┬────────┘ │    │  └──────┬─────┘  │    │
                           │                   │           │          │    │         │        │    │
    Extra STAP Hosts ◀─────┤                   │  ┌────────▼────────┐ │    └─────────┼────────┘    │
                           │                   │  │  Extra STAPs    │ │              │             │
                           │                   │  │  (0..N-1)       │ │              │             │
    Extended STAP Scan ◀───┤                   │  └─────────────────┘ │              │             │
                           │                   └──────────────────────┘              │             │
                           │                                                         │             │
    DFT iJTAG ◀────────────┤─────────────────────────────────────────────────────────┤             │
    DFD iJTAG ◀────────────┤─────────────────────────────────────────────────────────┘             │
                           │                                                                       │
    AXI SMC Debug ◀────────┤                                                                       │
    AXI SMC OTP ◀──────────┤  (From PTAP JTAG2AXI bridges)                                         │
    AXI SEP OTP ◀──────────┤                                                                       │
                           │                                                                       │
    Clock/Reset Control ◀──┤  (From PTAP debug control)                                            │
                           └───────────────────────────────────────────────────────────────────────┘

Key Components
==============

JTAG Primary TAP (PTAP)
-----------------------

The PTAP provides the core JTAG functionality:

* IEEE 1149.1 TAP controller state machine
* 6-bit instruction register with decoded outputs
* Multiple data registers (BYPASS, IDCODE, 3DCR, IC_RESET, DEBUG_CTRL, CAPS)
* Test Mode Persistence (TMP) controller
* Three JTAG2AXI bridge instances for AXI bus access
* Scan control generation for BSR, STAP, and iJTAG paths

For detailed PTAP documentation, see :doc:`JTAG PTAP </hw/ip/jtag_ptap/doc/index>`.

STAP Scan Chain
---------------

The STAP scan chain provides IEEE 1838 multi-die connectivity:

* **I/O STAP**: Chiplet-to-chiplet JTAG connection with TDI lockup latch
* **SEP Debug STAP**: Security Engine Processor debug interface
* **Extra STAPs**: Parameterized additional STAPs for local connectivity
* **Extended STAP Scan**: External scan interface for additional STAP chains

Each STAP includes a 3-bit 3DCR control register for:

* ``tms_hold``: TMS parking value when STAP not selected
* ``stap_sel``: STAP selection enable
* ``config_hold``: Preserve register contents across TLR

For detailed STAP documentation, see :doc:`JTAG STAP </hw/ip/jtag_stap/doc/index>`.

iJTAG SIB Network
-----------------

The iJTAG network uses Segment Insertion Bits (SIBs) for hierarchical access:

* **DFT SIB**: Access to Design-for-Test instrument network
* **DFD SIB**: Access to Design-for-Debug instrument network

SIBs allow selective inclusion of instrument networks in the scan path, reducing scan chain length when instruments are not accessed.

Design Principles
=================

* **Modular Integration**: Combines PTAP, STAPs, and SIBs into single component
* **Parameterized Architecture**: Enable/disable features via module parameters
* **IEEE Compliance**: Implements IEEE 1149.1, 1687, and 1838 standards
* **Flexible Connectivity**: Supports chiplet-to-chiplet and local STAP connections
* **Clean Interfaces**: Type-parameterized control structures for extensibility

Use Cases
=========

The JTAG Interface Unit is typically used to:

* **Device Identification**: Read IDCODE from PTAP
* **Boundary Scan Test**: Access BSR chain via PTAP
* **Multi-Die Debug**: Connect to remote PTAPs via I/O STAP
* **SEP Access**: Debug Security Engine via SEP STAP
* **Local TAP Connection**: Connect to on-chip TAPs via Extra STAPs
* **DFT Instrument Access**: Access DFT networks via iJTAG SIBs
* **DFD Instrument Access**: Access DFD networks via iJTAG SIBs
* **System Bus Debug**: Read/write memory via JTAG2AXI bridges
* **Reset Control**: Manage chip resets via IC_RESET
* **Clock Control**: Stop clocks via DEBUG_CONTROL
