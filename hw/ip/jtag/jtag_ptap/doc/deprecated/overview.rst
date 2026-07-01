========
Overview
========

The JTAG Primary TAP (PTAP) is the main Test Access Port controller for the Open Chiplet Harness (OCH) system. It provides the primary interface for debug, test, and configuration operations, implementing a comprehensive JTAG architecture compliant with IEEE 1149.1, IEEE 1687 (iJTAG), and IEEE 1838 (3D test) standards.

System Requirements
===================

The PTAP is designed to meet the following requirements:

Functionality
-------------

* Implement IEEE 1149.1 compliant TAP controller state machine
* Support mandatory JTAG instructions: BYPASS, IDCODE, SAMPLE/PRELOAD, EXTEST
* Support optional instructions: INTEST, CLAMP, HIGHZ, RUNBIST, IC_RESET
* Provide IEEE 1838 multi-die test architecture support via TAP 3DCR
* Enable IEEE 1687 iJTAG instrument access via SELECT_IJTAG
* Support Test Mode Persistence (TMP) per IEEE 1149.1 Section 16
* Provide JTAG-to-AXI bridge for system bus access
* Allow debug control including clock stop and boot stall

Performance
-----------

* TCK clock frequency: System dependent (typically 10-50 MHz)
* Single-cycle data register shifts
* TDO retimed to falling edge of TCK per IEEE 1149.1
* Minimal latency for JTAG-to-AXI transactions

Interface
---------

* Standard JTAG pins: TCK, TMS, TDI, TDO, TRST_n
* Boundary scan chain interface (external BSR)
* iJTAG network interface (IEEE 1687)
* STAP interface for multi-die connectivity (IEEE 1838)
* AXI4 and AXI4-Lite manager interfaces for bus access
* Debug control outputs (clock stop, boot stall, IC reset)

Block Diagram
=============

The PTAP block diagram shows the high-level structure:

.. code-block:: text

                           ┌───────────────────────────────────────────────────────┐
                           │                    JTAG PTAP                          │
                           │                                                       │
    TCK, TMS, TRST_n ──────┤  TAP Controller                                       │
    TDI ───────────────────┤  (jtag_tap_ctrlr)                                     │
                           │       │                                               │
                           │       ▼                                               │
                           │  ┌─────────────┐    ┌─────────────┐                   │
                           │  │ Instruction │───▶│ Instruction │                   │
                           │  │  Register   │    │  Decoder    │                   │
                           │  └─────────────┘    └─────────────┘                   │
                           │                           │                           │
                           │       ┌───────────────────┴────────────────┐          │
                           │       ▼                   ▼                ▼          │
                           │  ┌─────────┐       ┌──────────┐      ┌─────────┐      │
                           │  │ BYPASS  │       │  IDCODE  │      │ 3DCR    │      │
                           │  │ Register│       │ Register │      │Register │      │
                           │  └─────────┘       └──────────┘      └─────────┘      │
                           │       │                  │                │           │
                           │       ▼                  ▼                ▼           │
                           │  ┌──────────────────────────────────────────────┐     │
                           │  │              TDR Multiplexer                 │     │
                           │  │          (IEEE 1149.1 Section 4.4)           │     │
                           │  └──────────────────────────────────────────────┘     │
                           │                          │                            │
                           │                          ▼                            │
    TDO ◀──────────────────┤                    TDO Retiming                       │
    TDO_OEN ◀──────────────┤                                                       │
                           │                                                       │
                           │  ┌─────────────────────────────────────────────────┐  │
                           │  │            External Interfaces                  │  │
                           │  │  • BSR Chain      • iJTAG Network               │  │
                           │  │  • STAP Interface • AXI/AXI-Lite Buses          │  │
                           │  └─────────────────────────────────────────────────┘  │
                           └───────────────────────────────────────────────────────┘

Key Components
==============

TAP Controller
--------------

The TAP controller implements the IEEE 1149.1 state machine:

* 16-state finite state machine
* One-hot state encoding for error detection
* TMP controller integration for persistence mode
* Generates scan control signals for all data registers
* Provides test_logic_reset, capture_en, shift_en, update_en

Instruction Register
--------------------

The 6-bit instruction register:

* Captures ``6'b000001`` (IDCODE) on capture
* Default instruction after reset: IDCODE
* One-hot decoded outputs for efficient instruction selection
* Supports 64 unique instruction encodings

Data Registers
--------------

Multiple data registers accessible based on instruction:

* **BYPASS**: 1-bit bypass register (mandatory)
* **INV_BYPASS**: 1-bit inverted bypass register
* **IDCODE**: 32-bit device identification (mandatory)
* **3DCR**: 2-bit 3-Die Control Register for STAP selection
* **TMP_STATUS**: 2-bit TMP status register
* **IC_RESET**: Reset control register (configurable width)
* **DEBUG_CTRL**: 5-bit debug control register
* **JTAG_CAPS**: 40-bit capabilities register (read-only)
* **JTAG2AXI_CAPS**: 14-bit AXI bridge capabilities (read-only)

TMP Controller
--------------

Test Mode Persistence controller per IEEE 1149.1 Section 16:

* CLAMP_HOLD instruction enters persistence mode
* CLAMP_RELEASE instruction exits persistence mode
* Bypass-escape condition for automatic exit
* Controls TAP controller state during persistence

JTAG2AXI Bridge
---------------

JTAG-to-AXI bridge modules for bus access:

* Single operation mode for individual transactions
* Series mode for burst/streaming operations
* Supports both AXI4 and AXI4-Lite interfaces
* Three instances: SMC fabric, SMC OTP, SEP OTP

Design Principles
=================

* **IEEE Compliance**: Strict adherence to JTAG, iJTAG, and 3D test standards
* **Parameterized Design**: Configurable features via module parameters
* **Glitch-Free Outputs**: TDO retimed on falling TCK edge
* **Modular Architecture**: Independent sub-modules for each function
* **Flexible Interfaces**: Type-parameterized AXI interfaces

Use Cases
=========

The PTAP is typically used to:

* **Device Identification**: Read IDCODE for chip identification
* **Boundary Scan Test**: Control pins via EXTEST/SAMPLE/PRELOAD
* **Internal Test**: Access internal logic via iJTAG network
* **Multi-Die Debug**: Access STAPs on remote dies via 3DCR
* **System Debug**: Read/write memory via JTAG2AXI bridge
* **Reset Control**: Manage chip resets via IC_RESET instruction
* **Clock Control**: Stop/start clocks via DEBUG_CONTROL register
