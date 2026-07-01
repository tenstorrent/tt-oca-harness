## Description

The Cross Trigger Port (CTP) is a module that controls the sending and receiving of cross triggers between chiplets using GPIO pads. Cross triggers are pulses sent and received by debug modules within the functional core of a chiplet. Each CTP connects to four separate I/O pads for inter-chiplet cross triggering:

* **CT\_Req\_out** \- The cross trigger request output signal. The CTP asserts this signal to transmit a cross trigger in both point-to-point and wire-OR modes. In point-to-point mode the request is held high until the receiver acknowledges the request. In wire-OR mode, this signal drives the output-enable port of the I/O pad for duration defined by a pulse stretching module, and the pad output is driven static-low. Also in wire-OR mode the I/O pad input signal must be inverted, as the pad signal itself is an open-drain active-low signal.
* **CT\_Ack\_in** \- The cross trigger acknowledge input signal. Exclusive to point-to-point mode. The cross trigger receiver asserts this signal when it acknowledges the CTP’s cross trigger request.
* **CT\_Req\_in** \- The cross trigger request input signal. Exclusive to point-to-point mode. This is the external cross trigger request received by the CTP.
* **CT\_Ack\_out** \- The cross trigger acknowledge output signal. Exclusive to point-to-point mode. The CTP asserts this signal after receiving a cross trigger request, and de-asserts this signal after the cross trigger request is released.

These I/O pads are not included in the CTP itself, but the control and data signals for the pad come from the CTP. When a GPIO pad is configured for cross triggering by the System Management Controller (SMC), the I/O pad assumes the role of one of these four cross trigger signals, and the pad controls and I/O data signals are connected to the associated CTP. The GPIO input signals are asynchronous to the CTP and must first be synchronized before they can be used.

On the core-side of the CTP, there are pulse input and output ports for sending and receiving cross triggers. These pulses are synchronous to the CTP core clock.

The following table lists key I/O ports for the cross trigger protocol of the CTP:

| Name | Direction | Description |
| :---- | :---- | :---- |
| ct\_src | input | Core-side cross trigger input pulse. |
| ct\_dst | output | Core-side cross trigger output pulse. |
| busy | output | Optional signal indicating that an outgoing cross trigger pulse transfer is in progress. |
| reset | input | Resets the outgoing peer-to-peer handshake logic. This is a logical reset, not an asynchronous core reset. |
| ct\_req\_out\_dout\_en | output | Enables the output driver for the *CT\_Req\_out* pad. In wire-OR mode this signal is enabled by a cross trigger pulse from the pulse stretcher. In peer-to-peer mode it is always enabled. |
| ct\_req\_out\_din\_en | output | Enables the input buffer for the *CT\_Req\_out* pad. In wire-OR mode this signal is enabled and in peer-to-peer mode it is disabled. |
| ct\_req\_out\_dout | output | The output data to drive on the *CT\_Req\_out* pad. In peer-to-peer mode the pulse capture latch controls this signal. In wire-OR mode it is held static-low. |
| ct\_req\_out\_din | input | The input data that is driven on the *CT\_Req\_out* pad. In wire-OR mode this signal triggers a pulse on *ct\_dst* after synchronization. In peer-to-peer mode it is unused. |
| ct\_req\_in\_din\_en | output | Enables the input buffer for the *CT\_Req\_in* pad. In peer-to-peer mode this signal is enabled and in wire-OR mode it is disabled. |
| ct\_req\_in\_din | input | The input data that is driven on the *CT\_Req\_in* pad. In peer-to-peer mode this signal triggers a pulse on *ct\_dst* after synchronization. In wire-OR mode it is unused. |
| ct\_ack\_in\_din\_en | output | Enables the input buffer for the *CT\_Ack\_in* pad. In peer-to-peer mode this signal is enabled and in wire-OR mode it is disabled. |
| ct\_ack\_in\_din | input | The input data that is driven on the *CT\_Ack\_in* pad. This signal clears the cross trigger request output in peer-to-peer mode. In wire-OR mode it is unused. |
| ct\_ack\_out\_dout\_en | output | Enables the output driver for the *CT\_Ack\_out* pad. In peer-to-peer mode this signal is enabled and in wire-OR mode it is disabled. |
| ct\_ack\_out\_dout | output | The output data to drive on the *CT\_Ack\_out* pad. In peer-to-peer mode the *ct\_req\_in* pulse synchronizer controls this signal. In wire-OR mode it is unused. |

The following diagram illustrates the logical behavior of the CTP core:

![][image1]

The CTP supports two different pulse triggering protocols between chiplets, selected via the MODE bit of the CONFIG register, and their functionality is detailed in the following two sections.

## Wire-OR Mode

Wire-OR mode is a 1-wire cross trigger signaling scheme compatible with many existing cross triggering implementations. Each chiplet has an open-drain I/O connected to a single shared wire. Any connected chiplet may pull this signal low to assert a cross trigger. Depending on the electrical requirements, one or more internal pad pull-ups or external keepers ensure the cross trigger request signal remains high when no cross trigger is asserted.

To ensure no connected chiplet misses a cross trigger pulse, all chiplets transmitting a trigger pulse must stretch the pulse a mutually agreed upon length of time. The number of clock cycles that a core-side pulse is stretched is defined by the STRETCH\_MULT register. If another pulse arrives on CT\_Src before the previous pulse has been fully stretched, the previous pulse is overridden. In other words, the pulse stretch counter is simply restarted to count the full duration of another stretched pulse without interrupting the current GPIO pulse.

Note that in wire-OR mode the *CT\_Req\_out* signal is connected to an open-drain configured I/O pad. For I/O pads that do have explicit open-drain control, the request data signal should connect to the output-enable control pin of the I/O pad, and the output data signal of the I/O pin should be driven statically low. The CTP does not configure the pad’s open drain functionality. This is handled by the SMC.

The following diagram illustrates the logical behavior of the CTPs when configured in wire-OR mode:

![][image2]

## Point-to-Point Mode

Point-to-point mode utilizes a four-phase handshaking scheme to synchronize a cross trigger quickly and reliably between two chiplets without explicit pulse stretching. While this scheme is simple and fast, it requires a dedicated CTP for each chiplet-to-chiplet interconnection, and each CTP requires four I/O pads for bi-directional communication, or two pads for unidirectional communication. All output pads are configured for push-pull operation.

The following diagram illustrates the logical behavior of the CTPs when configured in point-to-point mode:

![][image3]

Any two chiplets may have their four cross trigger pads cross-coupled as shown in the following example diagram:

![][image4]

On the sender side, the receiver’s *CT\_Ack\_out* is connected to the sender’s *CT\_Ack\_in* pad. *CT\_Req\_out* asserts whenever *CT\_Src* asserts. *CT\_Req\_out* will then remain asserted until *CT\_Ack\_in* asserts.

On the receiver side, the sender’s *CT\_Req\_out* is connected to the receiver’s *CT\_Req\_in* pad. On any positive edge of *CT\_Req\_in*, the receiver generates a pulse on *CT\_Dst* and asserts *CT\_Ack\_out*. Deassertion proceeds in exactly the same sequence.

The timing of the request/acknowledge handshake is shown in the diagram below:

![][image5]

## Register Interface

The following tables describe the register interface for each CTP module.

| CONFIG |  |  |  |  |
| ----- | :---: | ----- | :---: | :---: |
| **Bits** | **Field** | **Description** | **Access** | **Reset** |
| 0 | MODE | Selects the operating mode of the CTP. 0 \- Wire-OR 1 \- Point-to-Point | R/W | 0 |
| 1 | INVERT | Inverts the sense of the incoming and outgoing GPIO signals. 0 \- No inversion. Wire-OR mode uses active-low signaling with active or passive pull-ups. Point-to-point mode uses active-high signaling. 1 \- All inputs and outputs of I/Os are inverted. Wire-OR mode uses active-high signaling with active or passive pull-downs. Point-to-point mode uses active-low signaling. | R/W | 0 |
| 2 | RESET | Forcefully clears the request output signal of the point-to-point handshake logic. Primarily for debug and recovery of handshake deadlock. | R/W | 0 |

| STATUS |  |  |  |  |
| ----- | :---: | ----- | :---: | :---: |
| **Bits** | **Field** | **Description** | **Access** | **Reset** |
| 0 | BUSY | Indicates whether a pulse assertion or handshake is currently in progress. 0 \- Pulse or handshake is not in progress 1 \- Pulse or handshake is currently in progress | RO | 0 |
| 4 | REQ\_OUT | Readout of the current CT\_Req\_out signal value. | RO | 0 |
| 5 | ACK\_IN | Readout of the current synchronized CT\_Ack\_in signal value. | RO | 0 |
| 6 | REQ\_IN | Readout of the current synchronized CT\_Req\_in signal value. | RO | 0 |
| 7 | ACK\_OUT | Readout of the current CT\_Ack\_out signal value. | RO | 0 |
|  |  |  |  |  |

| STRETCH\_MULT |  |  |  |  |
| ----- | :---: | ----- | :---: | :---: |
| **Bits** | **Field** | **Description** | **Access** | **Reset** |
| \[15:0\] | STRETCH\_MULT | The number of clock cycles a core-side cross trigger pulse is stretched on the GPIO pin when in wire-OR mode. Whenever a core-side pulse is received, the generated GPIO pulse has a width of (STRETCH\_MULT+1) clock cycles. | R/W | 0x0 |

The registers should be defined using SystemRDL and they should be generated using PeakRDL. The top module should have system bus request/response ports that have parameterized types so that the bus interface protocol can be generic. The types should have a default value of `logic` so that the user is forced to explicitly define them. Setup PeakRDL to generate registers with an AXI4-Lite bus interface. The bus interface uses request and response structures with types defined in `deps/axi/include/axi/typedef.svh`.

## Design Implementation Plan

Define a design specification and implementation plan for this IP that any agent can execute. The IP should be called cross\_trigger\_port and located in hw/ip. Your specification and implementation plan should also be placed here. Use the hw/comp/entropy\_source IP as a reference for the project structure and style. The design implementation agent must document their design using Sphinx. Documentation should focus on describing implementation details, usage guidelines, and integration.

The cross\_trigger\_port module should be the top module that includes the following instantiated sub-modules and logic:

* Generated SystemRDL registers
* Synchronizer module for all asynchronous input signals
* Pulse stretching module for wire-OR mode
* Positive edge detection module for the synchronized input cross trigger handshake request signal
* Handshaking control logic for Point-to-Point mode

Always make use of common primitive modules in hw/common whenever possible. All combinatorial outputs must be registered to prevent glitches.

## Testbench Implementation Plan

Define a test plan for this IP that any agent can execute. Include the test plan with the testbench. The testbench should check all core features of the IP. Be sure to include a basic sanity test for designers to use to check that core functionality of the design has not broken. The design verification agent must document their testbench using Sphinx. Documentation should focus on describing the testbench structure and test descriptions.

[image1]: ctp_diagram_1.png

[image2]: ctp_diagram_2.png

[image3]: ctp_diagram_3.png

[image4]: ctp_diagram_4.png

[image5]: ctp_diagram_5.png