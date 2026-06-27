Architecture
============

The JTAG STAP Interface IP implements a scan chain interface with optional timing optimization features and a Segment Insertion Bit (SIB) for accessing a 3-bit control register.

System Overview
---------------

.. code-block:: text

                      ┌──────────────────────────────────────┐
                      │          JTAG STAP Interface         │
                      │                                      │
 client_scan_ctrl_i ──┤ Client Scan Control (struct)         │
 client_scan_in_i ────┤ Scan Data Input                      │
 client_tap_ctrl_i ───┤ Client TAP Control (struct)          │
                      │                                      │
                      │  ┌────────────────────┐              │
                      │  │   Optional         │              │
                      │  │   Scan Input       │              │
                      │  │   Pipeline         │              │
                      │  └────────────────────┘              │
                      │            │                         │
                      │            ▼                         │
                      │  ┌────────────────────┐              │
                      │  │   Segment          │              │
                      │  │   Insertion Bit    │              │
                      │  │   (SIB) Mux        │              │
                      │  └────────────────────┘              │
                      │            │                         │
                      │            ▼                         │
                      │  ┌────────────────────┐              │
                      │  │   3DCR Control     │              │
                      │  │   Register         │              │
                      │  │   (3 bits)         │              │
                      │  └────────────────────┘              │
                      │            │                         │
                      │            ▼                         │
                      │  ┌────────────────────┐              │
                      │  │   Optional TDI     │              │
                      │  │   Lockup Latch     │              │
                      │  └────────────────────┘              │
                      │                                      │
                      │            Scan Data Output          ├── client_scan_out_o
                      │            Host TAP Control (struct) ├── host_tap_ctrl_o
                      │            TDO Output Enable         ├── host_tdo_oen_o
                      │            TDO Data Output           ├── host_tdo_o
                      └──────────────────────────────────────┘

Core Components
---------------

Scan Input Pipeline
~~~~~~~~~~~~~~~~~~~

An optional pipeline stage for the client scan input:

* **Purpose**: Timing optimization
* **Configuration**: Enabled via ``SCAN_IN_PIPE`` parameter
* **Operation**: Registers scan input on positive edge with scan_en qualification
* **Timing**: Adds one clock cycle of latency when enabled

TDO Output Lockup Latch
~~~~~~~~~~~~~~~~~~~~~~~~

A lockup latch for the TDO output to the host:

* **Operation**: Always enabled, registers on negative clock edge
* **Purpose**: Prevents hold time violations and provides clean output transitions
* **Source**: Takes input from the pipeline stage (or direct input if pipeline disabled)

TDI Input Lockup Latch
~~~~~~~~~~~~~~~~~~~~~~~

An optional lockup latch for the TDI input from the host:

* **Configuration**: Enabled via ``TDI_LOCKUP`` parameter
* **Operation**: Registers host TDI on negative clock edge
* **Purpose**: Timing optimization for multi-die configurations

Segment Insertion Bit (SIB)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A mux-based SIB implementation for accessing the 3DCR register:

* **Type**: ``prim_jtag_sib_mux_pre`` (mux before scan register)
* **Purpose**: Provides selective access to the 3DCR control register
* **Control**: Enabled by its own internal 1-bit scan register (SIB enable bit)
* **Optional Lockup**: Configurable via ``SCAN_OUT_LOCKUP`` parameter
* **Safe Select**: Disabled (direct combinational path)

3DCR Control Register
~~~~~~~~~~~~~~~~~~~~~

A 3-bit scan register containing STAP control signals:

.. list-table::
   :widths: 15 15 70
   :header-rows: 1

   * - Bit
     - Name
     - Description
   * - [2]
     - ``tms_hold``
     - TMS hold value for host TAP when STAP not selected
   * - [1]
     - ``stap_sel``
     - STAP selection enable
   * - [0]
     - ``config_hold``
     - Configuration hold for reset control

Register Implementation:

* **Type**: ``prim_jtag_scan_reg``
* **Width**: 3 bits
* **Reset Value**: 3'b000
* **Update Timing**: Negative edge of TCK
* **Scan Path**: Accessible via SIB when enabled

Data Flow
---------

Client to Host Path
~~~~~~~~~~~~~~~~~~~

1. **Input**: Client scan data arrives at ``client_scan_in_i``
2. **Optional Pipeline**: Data may be registered if ``SCAN_IN_PIPE`` enabled
3. **TDO Generation**: Pipelined data is registered on negative edge to ``host_tdo_o``
4. **Host Output**: TDO provided to host interface die/chiplet

Scan Chain Path
~~~~~~~~~~~~~~~

1. **Input Selection**: Mux selects between client scan input and host interface TDI based on ``stap_sel``
2. **SIB Entry**: Data enters the SIB module
3. **3DCR Access**: If SIB enabled, data shifts through 3DCR register
4. **Output**: Scan data exits via ``client_scan_out_o``

TAP Control Flow
~~~~~~~~~~~~~~~~

1. **Input**: Client TAP control signals received
2. **TMS Selection**: Mux selects between client TMS and ``tms_hold`` based on ``stap_sel``
3. **Host Output**: Modified TAP control signals provided to host interface
4. **TDO Enable**: ``host_tdo_oen_o`` generated as ``stap_sel && scan_en``

Reset Control
~~~~~~~~~~~~~

The 3DCR register reset is controlled by:

.. code-block:: verilog

   client_reg_scan_ctrl.rst_n = client_tap_ctrl_i.trst_n && 
                                 (config_hold || host_sib_scan_ctrl.rst_n);

This allows:

* Reset control via TRST (``client_tap_ctrl_i.trst_n``)
* Configuration hold to maintain register state during TLR transitions

.. note::
   **Reset Sources**
   
   The ``client_scan_ctrl_i.rst_n`` signal (which feeds into ``host_sib_scan_ctrl.rst_n``) 
   can be asserted due to a TAP controller Test-Logic-Reset (TLR) state transition. The 
   ``config_hold`` bit in the 3DCR allows the register to maintain its state during TLR 
   transitions by masking the scan control reset, preventing unintended register resets 
   during TAP state machine operations. When ``config_hold`` is set, only TRST can reset 
   the 3DCR register.

Configuration Options
---------------------

Parameter-Based Features
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 15 60
   :header-rows: 1

   * - Parameter
     - Default
     - Description
   * - ``SCAN_IN_PIPE``
     - 0
     - Enable scan input pipeline stage
   * - ``TDI_LOCKUP``
     - 0
     - Enable TDI input lockup latch
   * - ``SCAN_OUT_LOCKUP``
     - 0
     - Enable lockup latch on scan output (SIB mux output)

Type Parameters
~~~~~~~~~~~~~~~

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - Parameter
     - Description
   * - ``jtag_scan_ctrl_t``
     - Scan control structure type (default: ``prim_jtag_pkg::jtag_scan_ctrl_t``)
   * - ``jtag_tap_ctrl_t``
     - TAP control structure type (default: ``prim_jtag_pkg::jtag_tap_ctrl_t``)

.. note::
   **Control Structure Templating**
   
   The scan and TAP control structures are parameterized as type parameters, enabling flexible 
   control signal templating. This design allows new signals to be added to the structures 
   (e.g., ``jtag_scan_ctrl_t`` or ``jtag_tap_ctrl_t``) and automatically 
   passed through the STAP module without requiring any RTL code modifications. The module 
   treats these structures as templates, preserving all signals during pass-through operations 
   while only modifying specific fields as needed (e.g., ``tms`` in TAP control, ``select`` 
   in scan control). This provides forward compatibility and allows system-level customization 
   of control interfaces.

Timing Characteristics
----------------------

Pipeline Latency
~~~~~~~~~~~~~~~~

Scan Input Path (client_scan_in to TDO):

* **Base Path**: Combinational through optional pipeline
* **Optional Pipeline Stage**: +1 clock cycle (if ``SCAN_IN_PIPE`` enabled)
* **TDO Output Lockup**: Always enabled, 0.5 clock cycle delay (negative edge)

Scan Chain Path (TDI to client_scan_out):

* **TDI Lockup Latch**: 0.5 clock cycle (if ``TDI_LOCKUP`` enabled)
* **SIB Scan Register**: 1 clock cycle (always present, 1-bit register)
* **3DCR Access**: +3 clock cycles when SIB enabled (3-bit register)
* **Scan Output Lockup**: 0.5 clock cycle (if ``SCAN_OUT_LOCKUP`` enabled)

Total Scan Chain Latency:

* **Minimum**: 1 cycle (SIB only, no lockups or pipeline)
* **Typical**: 1.5 cycles (SIB + scan output lockup)
* **With 3DCR**: 4 cycles (SIB + 3DCR, no lockups)
* **Maximum**: 6.5 cycles (pipeline + all lockups + SIB + 3DCR)

Clock Edges
~~~~~~~~~~~

* **Positive Edge**: Scan register capture, scan input pipeline
* **Negative Edge**: Update register, lockup latches, TDI pipeline

Use Case Examples
-----------------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

Minimal configuration with no optional features:

.. code-block:: systemverilog

   jtag_stap #(
       .SCAN_IN_PIPE(0),
       .TDI_LOCKUP(0),
       .SCAN_OUT_LOCKUP(0)
   ) u_stap (
       // connections...
   );

Timing-Optimized Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All timing features enabled for maximum margin:

.. code-block:: systemverilog

   jtag_stap #(
       .SCAN_IN_PIPE(1),
       .TDI_LOCKUP(1),
       .SCAN_OUT_LOCKUP(1)
   ) u_stap (
       // connections...
   );

Multi-Die System
~~~~~~~~~~~~~~~~

Configuration for multi-die JTAG architecture:

.. code-block:: systemverilog

   jtag_stap #(
       .SCAN_IN_PIPE(1),    // Pipeline for die crossing
       .TDI_LOCKUP(1),      // Lockup for long routes
       .SCAN_OUT_LOCKUP(1)  // Lockup for output timing
   ) u_stap (
       // Client interface from local PTAP
       .client_scan_ctrl_i(local_scan_ctrl),
       .client_tap_ctrl_i(local_tap_ctrl),
       // Host interface to remote die PTAP
       .host_tap_ctrl_o(remote_tap_ctrl),
       .host_tdo_o(remote_tdi),
       .host_tdi_i(remote_tdo)
   );

