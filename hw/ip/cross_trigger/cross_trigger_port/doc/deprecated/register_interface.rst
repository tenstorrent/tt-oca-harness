==================
Register Interface
==================

The Cross Trigger Port provides a register-based interface for configuration and status monitoring. The register interface is defined using SystemRDL and generated using PeakRDL with AXI4-Lite bus interface. The bus interface uses request and response structures with types defined in ``deps/axi/include/axi/typedef.svh``.

Register Map
============

The CTP implements three registers:

+----------------+--------+------------------+
| Register Name  | Offset | Description      |
+================+========+==================+
| CONFIG         | 0x0    | Configuration    |
+----------------+--------+------------------+
| STATUS         | 0x4    | Status           |
+----------------+--------+------------------+
| STRETCH_MULT   | 0x8    | Pulse Stretch    |
+----------------+--------+------------------+

CONFIG Register (Offset: 0x0)
==============================

Configuration register for CTP operation.

+-------+--------+--------+--------+----------+
| Bits  | Field  | Access | Reset  | Description |
+=======+========+========+========+==========+
| 0     | MODE   | R/W    | 0x0    | Operating mode: 0=Wire-OR, 1=Point-to-Point |
+-------+--------+--------+--------+----------+
| 1     | INVERT | R/W    | 0x0    | Signal inversion: 0=No inversion, 1=Invert all I/O |
+-------+--------+--------+--------+----------+
| 2     | RESET  | R/W    | 0x0    | Handshake reset (Point-to-Point mode only) |
+-------+--------+--------+--------+----------+
| 31:3  | RSVD   | -      | -      | Reserved |
+-------+--------+--------+--------+----------+

**MODE**:
* 0: Wire-OR mode - Single wire shared between multiple chiplets
* 1: Point-to-Point mode - Dedicated four-wire connection between two chiplets

**INVERT**:
* 0: No inversion - Wire-OR uses active-low, Point-to-Point uses active-high
* 1: All I/O inverted - Wire-OR uses active-high, Point-to-Point uses active-low

**RESET**:
* Asserting this bit clears the Point-to-Point handshake state machine
* Used for deadlock recovery
* Only effective in Point-to-Point mode

STATUS Register (Offset: 0x4)
==============================

Status register for monitoring CTP operation.

+-------+----------+--------+--------+----------+
| Bits  | Field    | Access | Reset  | Description |
+=======+==========+========+========+==========+
| 0     | BUSY     | RO     | 0x0    | Transfer in progress |
+-------+----------+--------+--------+----------+
| 3:1   | RSVD     | -      | -      | Reserved |
+-------+----------+--------+--------+----------+
| 4     | REQ_OUT  | RO     | 0x0    | CT_Req_out signal value |
+-------+----------+--------+--------+----------+
| 5     | ACK_IN   | RO     | 0x0    | Synchronized CT_Ack_in signal value |
+-------+----------+--------+--------+----------+
| 6     | REQ_IN   | RO     | 0x0    | Synchronized CT_Req_in signal value |
+-------+----------+--------+--------+----------+
| 7     | ACK_OUT  | RO     | 0x0    | CT_Ack_out signal value |
+-------+----------+--------+--------+----------+
| 31:8  | RSVD     | -      | -      | Reserved |
+-------+----------+--------+--------+----------+

**BUSY**:
* 0: No transfer in progress
* 1: Pulse or handshake currently in progress

**REQ_OUT, ACK_IN, REQ_IN, ACK_OUT**:
* Readback of current signal values
* Values reflect inversion if INVERT bit is set
* Useful for debugging and status monitoring

STRETCH_MULT Register (Offset: 0x8)
====================================

Pulse stretch multiplier for Wire-OR mode.

+--------+-------------+--------+--------+----------+
| Bits   | Field       | Access | Reset  | Description |
+========+=============+========+========+==========+
| 15:0   | STRETCH_MULT| R/W    | 0x0    | Pulse stretch duration (cycles) |
+--------+-------------+--------+--------+----------+
| 31:16  | RSVD        | -      | -      | Reserved |
+--------+-------------+--------+--------+----------+

**STRETCH_MULT**:
* Number of clock cycles to stretch pulse
* Actual pulse width = STRETCH_MULT + 1 cycles
* Only used in Wire-OR mode
* Range: 0 to 65535 cycles

Programming Model
=================

Initialization
--------------

1. Configure STRETCH_MULT (Wire-OR mode only):
   * Set appropriate value based on system requirements
   * Typical values: 10-100 cycles depending on clock frequency

2. Configure MODE:
   * Set to 0 for Wire-OR mode
   * Set to 1 for Point-to-Point mode

3. Configure INVERT (optional):
   * Set based on pad configuration and pull-up/pull-down requirements

4. Clear RESET (if needed):
   * Write 0 to RESET bit to release handshake reset

Sending Cross Trigger (Wire-OR Mode)
-------------------------------------

1. Ensure MODE = 0 (Wire-OR)
2. Configure STRETCH_MULT for desired pulse width
3. Assert ct_src_i pulse (one cycle minimum)
4. Monitor BUSY bit to track transfer progress
5. Pulse stretcher automatically handles pad output

Sending Cross Trigger (Point-to-Point Mode)
--------------------------------------------

1. Ensure MODE = 1 (Point-to-Point)
2. Assert ct_src_i pulse
3. Monitor BUSY bit and STATUS.REQ_OUT
4. Handshake controller automatically manages protocol
5. Wait for BUSY to clear before sending next trigger

Receiving Cross Trigger
-----------------------

1. Monitor ct_dst_o output for received triggers
2. Read STATUS register for signal values
3. In Point-to-Point mode, handshake is automatic
4. In Wire-OR mode, edge detection is automatic

Deadlock Recovery (Point-to-Point Mode)
----------------------------------------

If handshake deadlock occurs:

1. Assert CONFIG.RESET bit (write 1)
2. Wait for handshake to clear
3. Deassert CONFIG.RESET bit (write 0)
4. Handshake state machine returns to idle

Register Generation
==================

Registers are generated from SystemRDL source using PeakRDL:

.. code-block:: bash

   cd hw/ip/cross_trigger_port/data/registers
   ./generate_register_files.sh

This generates:
* SystemVerilog RTL (rtl/cross_trigger_port_reg.sv)
* SystemVerilog package (rtl/cross_trigger_port_reg_pkg.sv)
* C header (c/cross_trigger_port_reg.h)
* Python header (py_headers/cross_trigger_port_reg.py)
* SystemVerilog header (svh/cross_trigger_port_reg.svh)
