===============
Instruction Set
===============

The JTAG PTAP implements a 6-bit instruction register supporting up to 64 instructions. This section documents all supported instructions, their encodings, and behavior.

Instruction Register
====================

Characteristics
---------------

* **Width**: 6 bits
* **Capture Value**: ``6'b000001`` (captures IDCODE encoding)
* **Shift Direction**: LSB towards TDO, MSB towards TDI
* **Default Instruction**: IDCODE (after reset)

Instruction Categories
======================

The instructions are organized into the following categories:

1. **Mandatory IEEE 1149.1 Instructions**: BYPASS, IDCODE, SAMPLE/PRELOAD, EXTEST
2. **Optional IEEE 1149.1 Instructions**: INTEST, CLAMP, HIGHZ, RUNBIST
3. **TMP Instructions (IEEE 1149.1 Section 16)**: CLAMP_HOLD, CLAMP_RELEASE, TMP_STATUS
4. **IC_RESET Instruction (IEEE 1149.1 Section 17)**: IC_RESET
5. **IEEE 1838 (3D Test) Instructions**: TAP_3DCR
6. **IEEE 1687 (iJTAG) Instructions**: SELECT_IJTAG
7. **Debug and Capabilities Instructions**: DEBUG_CONTROL, JTAG_CAPS
8. **JTAG2AXI Instructions**: AXI transaction control
9. **Special Bypass Instructions**: ZERO_LENGTH_BYPASS, INV_BYPASS
10. **Reserved Instructions**: RISC-V debug reserved

Instruction Reference
=====================

Standard JTAG Instructions
--------------------------

BYPASS (0x3F)
~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h3F`` (all ones)
   * - **Data Register**
     - 1-bit bypass register
   * - **Capture Value**
     - ``0``
   * - **Standard**
     - IEEE 1149.1 (mandatory)

Selects the 1-bit bypass register, providing minimum scan path length. Per IEEE 1149.1, the all-ones encoding must select bypass.

BYPASS_ALT (0x00)
~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h00`` (all zeros)
   * - **Data Register**
     - 1-bit bypass register
   * - **Capture Value**
     - ``0``
   * - **Standard**
     - IEEE 1149.1 (mandatory)

Alternative bypass encoding. Per IEEE 1149.1, the all-zeros encoding must select bypass.

IDCODE (0x01)
~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h01``
   * - **Data Register**
     - 32-bit IDCODE register
   * - **Capture Value**
     - Device IDCODE
   * - **Standard**
     - IEEE 1149.1 (mandatory)

Selects the 32-bit IDCODE register containing device identification. This is the default instruction after reset and on IR capture.

SAMPLE/PRELOAD (0x03)
~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h03``
   * - **Data Register**
     - Boundary scan register (BSR)
   * - **Capture Value**
     - Current pin/logic values
   * - **Standard**
     - IEEE 1149.1 (mandatory, requires BSR_ENABLE)

Captures current values of device pins (SAMPLE) or loads test data into BSR (PRELOAD) without affecting normal operation.

EXTEST (0x04)
~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h04``
   * - **Data Register**
     - Boundary scan register (BSR)
   * - **Capture Value**
     - Values at device input pins
   * - **Standard**
     - IEEE 1149.1 (mandatory, requires BSR_ENABLE)

External test mode. Captures values at input pins and drives output pins with BSR contents.

EXTEST_TRAIN (0x05)
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h05``
   * - **Data Register**
     - Boundary scan register (BSR)
   * - **Requires**
     - BSR_ENABLE && EXTEST_TRAIN_ENABLE
   * - **Standard**
     - IEEE 1149.1 (optional)

External test training mode for link training sequences.

EXTEST_PULSE (0x06)
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h06``
   * - **Data Register**
     - Boundary scan register (BSR)
   * - **Requires**
     - BSR_ENABLE && EXTEST_PULSE_ENABLE
   * - **Standard**
     - IEEE 1149.1 (optional)

External test pulse mode for single-pulse output generation.

CLAMP (0x07)
~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h07``
   * - **Data Register**
     - 1-bit bypass register
   * - **Requires**
     - CLAMP_ENABLE
   * - **Standard**
     - IEEE 1149.1 (optional)

Clamps output pins to values from previous PRELOAD while selecting bypass for scan operations.

HIGHZ (0x08)
~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h08``
   * - **Data Register**
     - 1-bit bypass register
   * - **Requires**
     - HIGHZ_ENABLE
   * - **Standard**
     - IEEE 1149.1 (optional)

Sets all output and bidirectional pins to high-impedance state.

INTEST (0x09)
~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h09``
   * - **Data Register**
     - Boundary scan register (BSR)
   * - **Requires**
     - BSR_ENABLE && INTEST_ENABLE
   * - **Standard**
     - IEEE 1149.1 (optional)

Internal test mode. Drives values from BSR to internal logic and captures internal logic outputs.

RUNBIST (0x02)
~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h02``
   * - **Data Register**
     - iJTAG network (BIST results)
   * - **Requires**
     - RUNBIST_ENABLE
   * - **Standard**
     - IEEE 1149.1 (optional)

Initiates built-in self-test. TAP controller remains in Run-Test/Idle during test execution.

TMP Instructions (IEEE 1149.1 Section 16)
-----------------------------------------

CLAMP_HOLD (0x0A)
~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h0A``
   * - **Data Register**
     - 1-bit bypass register
   * - **Requires**
     - TMP_ENABLE
   * - **Standard**
     - IEEE 1149.1 Section 16

Enters Test Mode Persistence mode. TAP controller is held in Run-Test/Idle while persistence is active. Clamps output pin values.

CLAMP_RELEASE (0x0B)
~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h0B``
   * - **Data Register**
     - 1-bit bypass register
   * - **Requires**
     - TMP_ENABLE
   * - **Standard**
     - IEEE 1149.1 Section 16

Exits Test Mode Persistence mode, returning to normal TAP operation.

TMP_STATUS (0x0C)
~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h0C``
   * - **Data Register**
     - 2-bit TMP status register
   * - **Requires**
     - TMP_ENABLE
   * - **Standard**
     - IEEE 1149.1 Section 16.1

Accesses the TMP status register:

* Bit [1]: TMP-status (read-only) - reflects persistence mode state
* Bit [0]: bypass-escape (read/write) - enables bypass-escape condition

IC_RESET Instruction (IEEE 1149.1 Section 17)
---------------------------------------------

IC_RESET (0x0D)
~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h0D``
   * - **Data Register**
     - IC_RESET register (2*NUM_IC_RESET + 1 bits)
   * - **Requires**
     - IC_RESET_ENABLE
   * - **Standard**
     - IEEE 1149.1 Section 17

Controls integrated circuit reset signals. Register contains:

* ``reset_hold`` (1 bit): Holds reset configuration across TLR
* For each reset port:
  - ``reset_enable``: Gives JTAG control over reset
  - ``reset_control``: Reset control value when enabled

IEEE 1838 (3D Test) Instructions
--------------------------------

TAP_3DCR (0x0E)
~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h0E``
   * - **Data Register**
     - 2-bit 3DCR register
   * - **Requires**
     - STAP_IO_ENABLE or SEP_DBG_ENABLE or NUM_EXTRA_STAPS > 0
   * - **Standard**
     - IEEE 1838

Accesses the 3-Die Control Register for STAP selection:

* Bit [1]: ``stap_sel`` - Selects STAP scan path
* Bit [0]: ``config_hold`` - Prevents reset during TLR transitions

IEEE 1687 (iJTAG) Instructions
------------------------------

SELECT_IJTAG (0x1A)
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h1A``
   * - **Data Register**
     - iJTAG network scan chain
   * - **Standard**
     - IEEE 1687

Selects the iJTAG network for accessing embedded test instruments. The iJTAG network provides hierarchical access to internal test data registers through Segment Insertion Bits (SIBs).

Debug and Capabilities Instructions
-----------------------------------

DEBUG_CONTROL (0x18)
~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h18``
   * - **Data Register**
     - 5-bit debug control register
   * - **Always enabled**
     - Yes

Accesses the debug control register for clock and boot control.

JTAG_CAPS (0x19)
~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h19``
   * - **Data Register**
     - 40-bit capabilities register
   * - **Access**
     - Read-only (captures constant value)
   * - **Always enabled**
     - Yes

Reports PTAP capabilities and configuration. See :doc:`register_interface` for bit field details.

JTAG2AXI Instructions
---------------------

SMC OTP Instructions
~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 15 30 55
   :header-rows: 1

   * - Encoding
     - Instruction
     - Description
   * - 0x1B
     - SMC_OTP_JTAG2AXI_CAPS
     - SMC OTP JTAG2AXI capabilities (read-only)
   * - 0x1C
     - SMC_OTP_AXI_SINGLE_OP
     - Single AXI transaction
   * - 0x1D
     - SMC_OTP_AXI_SERIES_CTRL
     - Series transaction control
   * - 0x1E
     - SMC_OTP_AXI_SERIES_DATA_INCR
     - Series data with address increment
   * - 0x1F
     - SMC_OTP_AXI_SERIES_DATA_NO_INCR
     - Series data without address increment
   * - 0x20
     - SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS
     - Series data with error status

Requires ``SMC_DBG_ENABLE`` parameter.

SEP OTP Instructions
~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 15 30 55
   :header-rows: 1

   * - Encoding
     - Instruction
     - Description
   * - 0x21
     - SEP_OTP_JTAG2AXI_CAPS
     - SEP OTP JTAG2AXI capabilities (read-only)
   * - 0x22
     - SEP_OTP_AXI_SINGLE_OP
     - Single AXI transaction
   * - 0x23
     - SEP_OTP_AXI_SERIES_CTRL
     - Series transaction control
   * - 0x24
     - SEP_OTP_AXI_SERIES_DATA_INCR
     - Series data with address increment
   * - 0x25
     - SEP_OTP_AXI_SERIES_DATA_NO_INCR
     - Series data without address increment
   * - 0x26
     - SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS
     - Series data with error status

Requires ``SEP_DBG_ENABLE`` parameter.

SMC Fabric Instructions
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 15 30 55
   :header-rows: 1

   * - Encoding
     - Instruction
     - Description
   * - 0x27
     - SMC_JTAG2AXI_CAPS
     - SMC fabric JTAG2AXI capabilities (read-only)
   * - 0x28
     - SMC_AXI_SINGLE_OP
     - Single AXI transaction
   * - 0x29
     - SMC_AXI_SERIES_CTRL
     - Series transaction control
   * - 0x2A
     - SMC_AXI_SERIES_DATA_INCR
     - Series data with address increment
   * - 0x2B
     - SMC_AXI_SERIES_DATA_NO_INCR
     - Series data without address increment
   * - 0x2C
     - SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS
     - Series data with error status

Requires ``SMC_DBG_ENABLE`` parameter.

Special Bypass Instructions
---------------------------

ZERO_LENGTH_BYPASS (0x3D)
~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h3D``
   * - **Data Register**
     - None (direct TDI to TDO)
   * - **Latency**
     - Zero additional cycles

Provides direct TDI to TDO connection, bypassing the TDO retiming register during data shift phase.

INV_BYPASS (0x3E)
~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 75

   * - **Encoding**
     - ``6'h3E``
   * - **Data Register**
     - 1-bit inverted bypass register
   * - **Capture Value**
     - ``1``

Inverted bypass register for chain detection and debugging.

Reserved Instructions
---------------------

RISC-V Debug Reserved (0x10-0x17)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Instructions ``6'h10`` through ``6'h17`` are reserved for RISC-V debug operations. These select the bypass register by default.

Undefined/Reserved Instructions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Undefined instruction encodings (0x0F, 0x2D-0x3C) select the bypass register per IEEE 1149.1 compliance.

Instruction Encoding Summary
============================

.. list-table::
   :widths: 15 35 25 25
   :header-rows: 1

   * - Encoding
     - Instruction
     - Data Register
     - Enable Parameter
   * - 0x00
     - BYPASS_ALT
     - Bypass
     - Always
   * - 0x01
     - IDCODE
     - IDCODE
     - Always
   * - 0x02
     - RUNBIST
     - iJTAG/Bypass
     - RUNBIST_ENABLE
   * - 0x03
     - SAMPLE_PRELOAD
     - BSR/Bypass
     - BSR_ENABLE
   * - 0x04
     - EXTEST
     - BSR/Bypass
     - BSR_ENABLE
   * - 0x05
     - EXTEST_TRAIN
     - BSR/Bypass
     - BSR & EXTEST_TRAIN_ENABLE
   * - 0x06
     - EXTEST_PULSE
     - BSR/Bypass
     - BSR & EXTEST_PULSE_ENABLE
   * - 0x07
     - CLAMP
     - Bypass
     - CLAMP_ENABLE
   * - 0x08
     - HIGHZ
     - Bypass
     - HIGHZ_ENABLE
   * - 0x09
     - INTEST
     - BSR/Bypass
     - BSR & INTEST_ENABLE
   * - 0x0A
     - CLAMP_HOLD
     - Bypass
     - TMP_ENABLE
   * - 0x0B
     - CLAMP_RELEASE
     - Bypass
     - TMP_ENABLE
   * - 0x0C
     - TMP_STATUS
     - TMP Status/Bypass
     - TMP_ENABLE
   * - 0x0D
     - IC_RESET
     - IC_RESET/Bypass
     - IC_RESET_ENABLE
   * - 0x0E
     - TAP_3DCR
     - 3DCR/Bypass
     - PTAP_3DCR_ENABLE
   * - 0x10-0x17
     - RISC-V Reserved
     - Bypass
     - Always
   * - 0x18
     - DEBUG_CONTROL
     - DEBUG_CTRL
     - Always
   * - 0x19
     - JTAG_CAPS
     - JTAG_CAPS
     - Always
   * - 0x1A
     - SELECT_IJTAG
     - iJTAG Network
     - Always
   * - 0x1B-0x20
     - SMC_OTP_AXI_*
     - JTAG2AXI/Bypass
     - SMC_DBG_ENABLE
   * - 0x21-0x26
     - SEP_OTP_AXI_*
     - JTAG2AXI/Bypass
     - SEP_DBG_ENABLE
   * - 0x27-0x2C
     - SMC_AXI_*
     - JTAG2AXI/Bypass
     - SMC_DBG_ENABLE
   * - 0x3D
     - ZERO_LENGTH_BYPASS
     - None
     - Always
   * - 0x3E
     - INV_BYPASS
     - Inverted Bypass
     - Always
   * - 0x3F
     - BYPASS
     - Bypass
     - Always
