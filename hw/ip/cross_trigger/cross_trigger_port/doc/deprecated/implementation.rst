===============
Implementation
===============

This section describes the implementation details of each module in the Cross Trigger Port IP.

Top Module: cross_trigger_port
===============================

The top module integrates all sub-modules and implements mode multiplexing.

**File**: ``rtl/cross_trigger_port.sv``

**Key Features**:
* Parameterized AXI-Lite bus interface types (default from package)
* AXI4-Lite register interface integration with request/response structures
* Mode multiplexing between Wire-OR and Point-to-Point
* Signal inversion support
* All outputs registered

**Parameters**:
* ``axil_req_t``: AXI-Lite request structure type (default: cross_trigger_port_pkg::ctp_axil_req_t)
* ``axil_resp_t``: AXI-Lite response structure type (default: cross_trigger_port_pkg::ctp_axil_resp_t)

**Implementation Details**:
* Instantiates generated register module with AXI4-Lite interface
* Connects request/response structures to flattened PeakRDL register signals
* Routes signals through synchronizer, pulse stretcher, edge detector, and handshake controller
* Multiplexes pad control signals based on MODE register bit
* Applies inversion to all I/O signals when INVERT bit is set
* Generates BUSY status from active transfers

Synchronizer Module: ctp_synchronizer
======================================

Synchronizes asynchronous GPIO input signals to the core clock domain.

**File**: ``rtl/ctp_synchronizer.sv``

**Implementation**:
* Uses ``prim_flop_2sync`` from hw/common for each input signal
* Synchronizes: ct_req_out_din, ct_req_in_din, ct_ack_in_din
* All outputs are registered (via prim_flop_2sync)

**Reset Behavior**:
* All synchronized outputs reset to 0

Pulse Stretcher Module: ctp_pulse_stretcher
============================================

Stretches core-side pulses for Wire-OR mode operation.

**File**: ``rtl/ctp_pulse_stretcher.sv``

**Implementation**:
* Counter-based implementation
* Counts down from STRETCH_MULT to 0
* Restarts counter if new pulse arrives during stretching
* Output remains high while counter is non-zero

**State Machine**:
* **IDLE**: Waiting for pulse input
* **ACTIVE**: Counter counting down, output asserted
* Transitions to IDLE when counter reaches zero

**Key Features**:
* Pulse width = (STRETCH_MULT + 1) clock cycles
* New pulse restarts counter (overrides previous pulse)
* Registered output prevents glitches

Edge Detector Module: ctp_edge_detector
=======================================

Detects positive edges on synchronized input signals.

**File**: ``rtl/ctp_edge_detector.sv``

**Implementation**:
* Uses ``prim_edge_detector`` from hw/common
* Synchronization disabled (input already synchronized)
* Generates one-cycle pulse on positive edge

**Output**:
* ``posedge_pulse_o``: Registered pulse output on positive edge

Handshake Controller Module: ctp_handshake_ctrl
===============================================

Implements four-phase handshaking protocol for Point-to-Point mode.

**File**: ``rtl/ctp_handshake_ctrl.sv``

**Sender State Machine**:
* **SENDER_IDLE**: Waiting for ct_src_i pulse
* **SENDER_REQ_ASSERTED**: CT_Req_out asserted, waiting for CT_Ack_in
* **SENDER_WAIT_ACK_DEASSERT**: CT_Req_out deasserted, waiting for CT_Ack_in to deassert

**Receiver State Machine**:
* **RECEIVER_IDLE**: Waiting for CT_Req_in positive edge
* **RECEIVER_ACK_ASSERTED**: CT_Ack_out asserted, CT_Dst pulse generated
* **RECEIVER_WAIT_REQ_DEASSERT**: CT_Ack_out deasserted, waiting for CT_Req_in to deassert

**Key Features**:
* Separate sender and receiver state machines
* RESET input for deadlock recovery
* BUSY output indicates active handshake
* All outputs registered

**Reset Behavior**:
* RESET bit clears sender state machine and CT_Req_out
* Receiver state machine unaffected by RESET (handles incoming requests)

Package: cross_trigger_port_pkg
================================

Defines types and constants for the CTP.

**File**: ``rtl/cross_trigger_port_pkg.sv``

**Contents**:
* Mode enumeration: MODE_WIRE_OR, MODE_POINT_TO_POINT
* AXI-Lite type definitions using ``AXI_LITE_TYPEDEF_ALL`` macro
* Request/response structure types: ``ctp_axil_req_t``, ``ctp_axil_resp_t``
* Address, data, and strobe type definitions

Register Module: cross_trigger_port_reg
=======================================

Generated from SystemRDL using PeakRDL.

**Generation**: Run ``data/registers/generate_register_files.sh``

**Interface**:
* AXI4-Lite slave interface (flattened signals)
* Hardware input/output structures (hwif_in/hwif_out)
* Register access with proper AXI-Lite timing
* Generated with ``--cpuif axi4-lite-flat`` option

Design Considerations
=====================

Glitch Prevention
-----------------

All combinatorial outputs are registered to prevent glitches:

* Pad control signals (dout_en, din_en, dout)
* Core-side outputs (ct_dst_o, busy_o)
* Status register inputs

This ensures clean signal transitions and prevents spurious triggers.

Synchronization Strategy
------------------------

All asynchronous GPIO inputs are synchronized using double-flop synchronizers:

* Prevents metastability issues
* Uses proven primitives from hw/common
* Proper reset handling

Mode Switching
--------------

Mode switching is handled via multiplexing:

* Pad control signals selected based on MODE bit
* Unused pads disabled in each mode
* No glitches during mode transitions (all outputs registered)

Signal Inversion
----------------

Inversion is applied consistently:

* All pad inputs inverted before use
* All pad outputs inverted before driving pads
* Status register readback reflects inverted values
* Applied uniformly across all I/O signals
