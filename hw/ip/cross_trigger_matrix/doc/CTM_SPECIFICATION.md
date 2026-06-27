### Cross Trigger Matrix (CTM)

The CTM is a crossbar that aggregates and statically routes cross trigger pulses between various sources and sinks. Typical connections to the CTM include Core Logic Analyzers (CLAs) and CTPs, including other miscellaneous devices. The CTM is compatible with CTPs operating in either of the two signaling modes, point-to-point or wire-OR. Typically, each device or logic module connected to the CTM will act as both a source and a sink for cross trigger pulses.

The CTM has the following data ports and logical structure:

* **CT\_Src\[N-1:0\]** \- Cross trigger pulse output signals from the CTM to CLAs, CTPs, or other cross trigger sinking devices, where N is the number of these cross trigger sinks.
* **CT\_Dst\[M-1:0\]** \- Cross trigger pulse input signals to the CTM from CLAs, CTPs, or other cross trigger generating devices, where M is the number of these cross trigger sources.

![CTM Block Diagram](image1.png)

The CTM is programmed at runtime via firmware or debug transactions. Proper configuration of the CTMs in each chiplet will minimize trigger latency and prevent loops in the SiP cross trigger network. Configuration is accomplished via CSRs.

## Register Interface

The following tables describe the register interface for each CT\_Src signal of the CTM module.

| CTM\_CT\_SRC\[N\]\_CONFIG |  |  |  |  |
| ----- | :---: | ----- | :---: | :---: |
| **Bits** | **Field** | **Description** | **Access** | **Reset** |
| \[M-1:0\] | CT\_DST\_SELECT | Selects the *CT\_Dst* port(s) to forward on this *CT\_Src*. Each bit is mapped to a *CT\_Dst* port, up to a maximum of 32 ports. Multiple ports may be selected as a trigger source. All selected source ports are then OR’d together to produce CT\_Src. Set this register to all-zero to disable the CT\_Src output. | R/W | 0 |

The registers should be defined using SystemRDL and they should be generated using PeakRDL. The top module should have system bus request/response ports that have parameterized types so that the bus interface protocol can be generic. The types should have a default value of `logic` so that the user is forced to explicitly define them. Setup PeakRDL to generate registers with an AXI4-Lite bus interface. The bus interface uses request and response structures with types defined in `deps/axi/include/axi/typedef.svh`.

## Design Implementation Plan

Define a design specification and implementation plan for this IP that any agent can execute. The IP should be called cross\_trigger\_matrix and located in hw/ip. Your specification and implementation plan should also be placed here. Use the hw/ip/cross\_trigger\_port as a reference for the project structure and style. The design implementation agent must document their design using Sphinx. Documentation should focus on describing implementation details, usage guidelines, and integration.

The cross\_trigger\_matrix module should be the top module that includes the following instantiated sub-modules and logic:

* Generated SystemRDL registers (One set of CTM\_CT\_SRC\[N\]\_CONFIG registers per CT\_Src port)
* A generated vector of modules that implement the CT\_Dst selection and pulse aggregation logic for each CT\_Src port
* The number of CT\_Dst and CT\_Src signals is parameterized, with valid values ranging from 1 \- 32\.

Always make use of common primitive modules in hw/common whenever possible. All combinatorial output signals in the top module must be registered to prevent glitches.

## Testbench Implementation Plan

Define a test plan for this IP that any agent can execute. Include the test plan with the testbench. The testbench should check all core features of the IP. Be sure to include a basic sanity test for designers to use to check that core functionality of the design has not broken. The design verification agent must document their testbench using Sphinx. Documentation should focus on describing the testbench structure and test descriptions.
