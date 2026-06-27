## Cross Trigger Network (CTN)

The DTP supports generating and sinking cross triggers between chiplets in a SiP as specified in the Open Chiplet Cross Triggering (OCCT) specification. A Cross Trigger Port (CTP) module serves as the signaling interface between the chiplet core logic and the I/O pads, while a Cross Trigger Matrix (CTM) module statically routes cross triggers between CTPs and the on-chip resources generating and sinking cross trigger pulses.

CTPs are used for sending and capturing the cross trigger ports from various components internal to the chiplet. The CTPs support two different inter-chiplet cross trigger signalling schemes, wire-OR and point-to-point. Wire-OR supports a wider range of existing chiplet implementations and is very resource efficient, while point-to-point is faster, more reliable, and simpler to configure. Refer to `hw/ip/cross_trigger_port` for its implementation.

The CTN contains a single Cross Trigger Matrix (CTM), as well as a configurable number of Cross Trigger Ports (CTP). The total number of CTPs is equal to the sum of the number of configured CTPs needed for external die-to-die cross triggering (XTRIG\_NUM\_CTP in the DTP) and the number of internal cross trigger signals (XTRIG\_NUM\_INT\_CT in the DTP). Refer to `hw/ip/cross_trigger_matrix` for the CTM implementation.

### External Cross Trigger Ports

The primary usage of the CTPs is for interfacing debug cross triggers with other chiplets. Each CTP requires four GPIOs external to the DTP. The CTN should have a parameterized number of CTPs (NUM\_CTP), with 16 CTPs by default. The GPIO signals should be passed up and out of the DTP, and the internal cross trigger signals should then connect to the CTM for routing.

### Internal Cross Triggers

There is an interface for internal cross triggers signals as detailed in the DTP module:

```
    // Note: XTRIG_NUM_INT_CT is a templated localparam from dtp_pkg (default: 10)
    output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_req_o,  // Cross trigger request signals sourced from the CTM to a cross trigger destination sink (such as a CLA)
    input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_src_ack_i,  // Acknowledge signals for cross trigger requests sourced from the CTM (unused in pulse sync mode)
    input  logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_req_i,  // Cross trigger request signals destined for the CTM from a cross trigger source generator (such as a CLA)
    output logic [XTRIG_NUM_INT_CT-1:0]  xtrig_ctm_dst_ack_o,  // Acknowledge signals for cross trigger requests destined for the CTM (unused in pulse sync mode)
```

CTP modules can be repurposed to process these cross trigger signals. The core CTP module should be used that does not contain the CSRs. The CTN should have top level parameters that the user can use to statically set the configuration signals for these CTPs. The mode signal should come from an INT\_CT\_MODE parameter for each internal CTP. See the DTP implementation for details. The CTN should have a parameterized number of internal CTPs, equal to the number of internal cross triggers (NUM\_INT\_CT), with 1 internal cross trigger by default.

Each src/dst pair of req/ack signals should connect to the GPIO data signals on these CTPs. The GPIO control and status signals can be left unconnected as these are not real GPIO interfaces. The core side of the CTP module should connect to the CTM.

### Clock Stop Control

The CTN has a number of incoming clock stop request signals, specified by NUM\_CLK\_STOP\_REQ. The CTN must aggregate these request signals using an OR tree and the final result is then conditioned on cla\_clock\_stop\_en from the JTAG interface unit being true. The result of this is OR’d with jtag\_clock\_stop to make the final clock stop output, stop\_clks\_o. This output signal should be flopped and passed out of the DTP.

### Bus Interface

The CTN will have a single AXI-lite bus interface port for CSRs. This subordinate port will connect to an AXI-lite bridge that has manager ports for the AXI-lite CSR modules of all of the CTP and the CTM CSRs. Organize the address space so that the CTM CSRs come first, followed by the external CTP CSRs. Internal CTPs do not have CSRs.

## Design Implementation Plan

Define a design specification and implementation plan for this IP that any agent can execute. The IP should be called cross\_trigger\_network and located in hw/comp. Your specification and implementation plan should also be placed here. Use the hw/ip/cross\_trigger\_port as a reference for the project structure and style. The CTN will be instantiated in `hw/dtp/rtl/dtp.sv` so look here to reference parameter and port names. The design implementation agent must document their design using Sphinx. Documentation should focus on describing implementation details, usage guidelines, and integration.

The top CTN module should include the following instantiated sub-modules and logic:

* Several instantiations of the Cross Trigger Port modules
  * A configurable number of CTPs for connecting to external GPIOs (NUM\_CTP)
  * A configurable number of core CTPs (without CSRs) for connecting to internal cross trigger interfaces (NUM\_INT\_CT)
* A cross trigger matrix module (`cross_trigger_matrix`) instantiation, connected to all of the CTPs.
* A module for clock stop control logic.
* An AXI-lite crossbar to connect the bus interface to the CTM and all of the external CTPs (see `deps/axi` for crossbar IP.

Implement a configuration script similar to the one for the CTM that allows the user to configure the number of internal and external cross trigger interfaces. The script should also call the CTM configuration script to generate the templated source code. Only use templated source code for the CTN itself if absolutely necessary.

Finally, the CTN should be integrated into the DTP.

Always make use of common primitive modules in hw/common whenever possible.

## Testbench Implementation Plan

Define a test plan for this IP that any agent can execute. Include the test plan with the testbench. The testbench should check all core features of the IP. Be sure to include a basic sanity test for designers to use to check that core functionality of the design has not broken. The design verification agent must document their testbench using Sphinx. Documentation should focus on describing the testbench structure and test descriptions.