========
Overview
========

The Cross Trigger Port (CTP) is a module that controls the sending and receiving of cross triggers between chiplets using GPIO pads. Cross triggers are pulses sent and received by debug modules within the functional core of a chiplet. Each CTP connects to four separate I/O pads for inter-chiplet cross triggering.

System Requirements
===================

The CTP is designed to meet the following requirements:

Functionality
-------------

* Support two operating modes: Wire-OR and Point-to-Point
* Synchronize asynchronous GPIO inputs to core clock domain
* Generate stretched pulses for Wire-OR mode
* Implement four-phase handshaking for Point-to-Point mode
* Provide status monitoring and debug capabilities

Performance
-----------

* Low latency: < 10 cycles from pulse input to pad output
* Configurable pulse stretching duration
* Glitch-free operation with all outputs registered
* Support for multiple chiplets on shared wire (Wire-OR mode)

Interface
---------

* AXI4-Lite register interface for configuration and status
* Core-side pulse input/output ports
* GPIO pad control signals (output enable, input enable, data)
* Optional busy signal for transfer status

Operating Modes
===============

Wire-OR Mode
------------

Wire-OR mode is a 1-wire cross trigger signaling scheme compatible with many existing cross triggering implementations. Each chiplet has an open-drain I/O connected to a single shared wire. Any connected chiplet may pull this signal low to assert a cross trigger.

Key characteristics:

* Uses single CT_Req_out pad bidirectionally
* Pulse stretching required to ensure all chiplets see the trigger
* Stretch duration configurable via STRETCH_MULT register
* Compatible with active-low signaling (default) or active-high (with INVERT)

Point-to-Point Mode
-------------------

Point-to-Point mode utilizes a four-phase handshaking scheme to synchronize a cross trigger quickly and reliably between two chiplets without explicit pulse stretching. This scheme requires a dedicated CTP for each chiplet-to-chiplet interconnection.

Key characteristics:

* Uses four separate pads: CT_Req_out, CT_Req_in, CT_Ack_in, CT_Ack_out
* Four-phase handshake protocol
* Fast and reliable synchronization
* Supports bidirectional communication
* Deadlock recovery via RESET bit

Key Components
==============

Synchronizer Module
--------------------

Synchronizes all asynchronous GPIO input signals to the CTP core clock domain using double-flop synchronizers. Prevents metastability issues when sampling pad signals.

Pulse Stretcher
--------------

Stretches core-side pulses to (STRETCH_MULT + 1) clock cycles for Wire-OR mode. If a new pulse arrives before the current pulse finishes stretching, the counter is restarted to ensure all chiplets see the pulse.

Edge Detector
-------------

Detects positive edges on the synchronized cross trigger request input signal for Point-to-Point mode. Generates registered pulse outputs on edge detection.

Handshake Controller
--------------------

Implements four-phase handshaking protocol for Point-to-Point mode:

* **Sender Side**: Asserts CT_Req_out when CT_Src asserts, waits for CT_Ack_in, then deasserts
* **Receiver Side**: Asserts CT_Ack_out on positive edge of CT_Req_in, generates CT_Dst pulse, deasserts when CT_Req_in deasserts

Register Interface
-----------------

Three registers provide complete control and status:

* **CONFIG**: Mode selection, signal inversion, handshake reset
* **STATUS**: Busy indication, signal readback
* **STRETCH_MULT**: Pulse stretching duration for Wire-OR mode

Design Principles
=================

* **Glitch-Free Operation**: All combinatorial outputs registered
* **Common Primitives**: Uses standard synchronization and edge detection modules from hw/common
* **Generic Bus Interface**: Parameterized types for flexibility, AXI4-Lite with request/response structures
* **Mode Isolation**: Wire-OR and Point-to-Point logic properly multiplexed
* **Robust Synchronization**: All asynchronous inputs properly synchronized
