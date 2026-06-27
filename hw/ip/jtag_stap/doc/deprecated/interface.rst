Interface Specification
=======================

The JTAG STAP Interface IP provides a comprehensive scan chain and TAP control interface for multi-die JTAG systems.

Signal List
-----------

Client Scan Control Interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 30 10 10 50
   :header-rows: 1

   * - Signal Name
     - Width
     - Direction
     - Description
   * - ``client_scan_ctrl_i``
     - struct
     - Input
     - Client scan control structure
   * - ``client_scan_ctrl_i.tck``
     - 1
     - Input
     - Test clock
   * - ``client_scan_ctrl_i.rst_n``
     - 1
     - Input
     - Active-low reset
   * - ``client_scan_ctrl_i.select``
     - 1
     - Input
     - Scan chain select
   * - ``client_scan_ctrl_i.capture_en``
     - 1
     - Input
     - Capture enable
   * - ``client_scan_ctrl_i.scan_en``
     - 1
     - Input
     - Scan shift enable
   * - ``client_scan_ctrl_i.update_en``
     - 1
     - Input
     - Update enable

Client Scan Data Interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 30 10 10 50
   :header-rows: 1

   * - Signal Name
     - Width
     - Direction
     - Description
   * - ``client_scan_in_i``
     - 1
     - Input
     - Scan data input from scan host
   * - ``client_scan_out_o``
     - 1
     - Output
     - Scan data output to scan host

Client TAP Control Interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 30 10 10 50
   :header-rows: 1

   * - Signal Name
     - Width
     - Direction
     - Description
   * - ``client_tap_ctrl_i``
     - struct
     - Input
     - Client TAP control structure
   * - ``client_tap_ctrl_i.tck``
     - 1
     - Input
     - Test clock
   * - ``client_tap_ctrl_i.tms``
     - 1
     - Input
     - Test mode select
   * - ``client_tap_ctrl_i.trst_n``
     - 1
     - Input
     - Test reset (active-low)

Host TAP Control Interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 30 10 10 50
   :header-rows: 1

   * - Signal Name
     - Width
     - Direction
     - Description
   * - ``host_tap_ctrl_o``
     - struct
     - Output
     - Host TAP control structure
   * - ``host_tap_ctrl_o.tck``
     - 1
     - Output
     - Test clock (pass-through)
   * - ``host_tap_ctrl_o.tms``
     - 1
     - Output
     - Test mode select (muxed)
   * - ``host_tap_ctrl_o.trst_n``
     - 1
     - Output
     - Test reset (pass-through)

Host TDO Interface
~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 30 10 10 50
   :header-rows: 1

   * - Signal Name
     - Width
     - Direction
     - Description
   * - ``host_tdo_o``
     - 1
     - Output
     - Test data output to host
   * - ``host_tdo_oen_o``
     - 1
     - Output
     - TDO output enable
   * - ``host_tdi_i``
     - 1
     - Input
     - Test data input from host

Module Parameters
-----------------

Configuration Parameters
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 25 15 15 45
   :header-rows: 1

   * - Parameter
     - Type
     - Default
     - Description
   * - ``SCAN_IN_PIPE``
     - bit
     - 0
     - Adds a pipeline stage to the client interface scan input. When enabled, scan input is registered on positive edge when scan_en is active. Adds 1 cycle latency.
   * - ``TDI_LOCKUP``
     - bit
     - 0
     - Adds a lockup latch to the STAP TDI input. When enabled, host TDI is registered on negative edge. Improves timing margin for long routes.
   * - ``SCAN_OUT_LOCKUP``
     - bit
     - 0
     - Adds a lockup latch to the STAP scan out output. When enabled, adds negative edge register on SIB output. Part of the SIB module configuration.

Type Parameters
~~~~~~~~~~~~~~~

.. list-table::
   :widths: 30 30 40
   :header-rows: 1

   * - Parameter
     - Type
     - Description
   * - ``jtag_scan_ctrl_t``
     - type
     - Scan control structure type (default: ``prim_jtag_pkg::jtag_scan_ctrl_t``)
   * - ``jtag_tap_ctrl_t``
     - type
     - TAP control structure type (default: ``prim_jtag_pkg::jtag_tap_ctrl_t``)

.. note::
   **Control Structure Templating**
   
   The control structures are parameterized as type parameters to enable flexible signal 
   templating. This allows new signals to be added to ``jtag_scan_ctrl_t`` or ``jtag_tap_ctrl_t`` 
   at the integration level and automatically passed through the STAP module without requiring 
   RTL modifications. The module preserves all structure signals during pass-through, modifying 
   only specific fields where needed (e.g., ``tms`` in TAP control, ``select`` in scan control). 
   This provides forward compatibility and system-level extensibility.

Signal Descriptions
-------------------

Scan Control Structure (jtag_scan_ctrl_t)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The scan control structure contains all signals needed for JTAG scan chain operation:

.. code-block:: systemverilog

   typedef struct packed {
       logic update_en;    // Update register enable
       logic scan_en;      // Scan shift enable
       logic capture_en;   // Capture enable
       logic select;       // Chain select
       logic rst_n;        // Active-low reset
       logic tck;          // Test clock
   } jtag_scan_ctrl_t;

**Signal Timing**:

* ``capture_en``: Active during Capture-DR/Capture-IR states
* ``scan_en``: Active during Shift-DR/Shift-IR states
* ``update_en``: Active during Update-DR/Update-IR states
* ``select``: Must be high for scan chain to be active

TAP Control Structure (jtag_tap_ctrl_t)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The TAP control structure contains basic JTAG TAP signals:

.. code-block:: systemverilog

   typedef struct packed {
       logic tms;      // Test mode select
       logic trst_n;   // Test reset (active-low)
       logic tck;      // Test clock
   } jtag_tap_ctrl_t;

**Signal Descriptions**:

* ``tms``: Controls TAP state machine transitions
* ``trst_n``: Asynchronous reset for TAP controller
* ``tck``: Test clock for synchronous operations

3DCR Control Register
~~~~~~~~~~~~~~~~~~~~~

The 3-bit control register accessed via the SIB:

.. list-table::
   :widths: 15 20 65
   :header-rows: 1

   * - Bit
     - Field Name
     - Description
   * - [2]
     - ``tms_hold``
     - TMS hold value. When ``stap_sel=0``, this value is output on ``host_tap_ctrl_o.tms`` to park the host TAP in a known state (Run-Test/Idle or Test-Logic-Reset).
   * - [1]
     - ``stap_sel``
     - STAP selection enable. When ``1``, this STAP is active and ``client_tap_ctrl_i.tms`` passes through to ``host_tap_ctrl_o.tms``. When ``0``, ``tms_hold`` value is used instead.
   * - [0]
     - ``config_hold``
     - Configuration hold. When ``1``, prevents reset of the 3DCR register even when ``host_sib_scan_ctrl.rst_n`` is low. Allows holding configuration across scan operations.

**Register Access**:

* Accessible via scan chain when SIB is enabled
* Updates on negative edge of TCK
* Reset value: 3'b000 (all zeros)
* Reset controlled by: ``trst_n && (config_hold || host_sib_scan_ctrl.rst_n)``

Interface Timing
----------------

Clock Domains
~~~~~~~~~~~~~

All signals operate in a single clock domain defined by ``client_scan_ctrl_i.tck`` and ``client_tap_ctrl_i.tck`` (which should be the same clock).

Setup and Hold
~~~~~~~~~~~~~~

**Inputs** (relative to TCK positive edge):

* ``client_scan_in_i``: Must meet setup/hold for capture
* ``client_scan_ctrl_i.*``: Must meet setup/hold for scan operations
* ``client_tap_ctrl_i.*``: Must meet setup/hold for control logic

**Outputs** (relative to TCK):

* ``host_tdo_o``: Launched on negative edge (lockup latch)
* ``client_scan_out_o``: Timing depends on SIB configuration
* ``host_tap_ctrl_o.*``: Combinational from inputs (with mux delay)

Scan Chain Timing
~~~~~~~~~~~~~~~~~

**Without Pipeline** (``SCAN_IN_PIPE=0``):

* Input to output path: 1.5 clock cycles (combinational + lockup)
* Data valid on negative edge after capture

**With Pipeline** (``SCAN_IN_PIPE=1``):

* Input to output path: 2.5 clock cycles (pipeline + lockup)
* Additional latency on scan path

TDO Output Enable
~~~~~~~~~~~~~~~~~

The ``host_tdo_oen_o`` signal is generated as:

.. code-block:: verilog

   host_tdo_oen_o = stap_sel && client_scan_ctrl_i.scan_en;

This ensures:

* TDO is only driven when STAP is selected
* TDO is only driven during scan operations
* Proper tri-state behavior in multi-drop configurations

Integration Guidelines
----------------------

Connection Example
~~~~~~~~~~~~~~~~~~

.. code-block:: systemverilog

   jtag_stap #(
       .SCAN_IN_PIPE(0),
       .TDI_LOCKUP(0),
       .SCAN_OUT_LOCKUP(0)
   ) u_jtag_stap (
       // Client scan interface
       .client_scan_ctrl_i (local_scan_ctrl),
       .client_scan_in_i   (local_scan_in),
       .client_scan_out_o  (local_scan_out),
       
       // Client TAP interface
       .client_tap_ctrl_i  (local_tap_ctrl),
       
       // Host TAP interface
       .host_tap_ctrl_o    (remote_tap_ctrl),
       .host_tdo_oen_o     (remote_tdo_oen),
       .host_tdo_o         (remote_tdo),
       .host_tdi_i         (remote_tdi)
   );

Reset Handling
~~~~~~~~~~~~~~

The module requires proper reset sequencing:

1. Assert ``client_tap_ctrl_i.trst_n`` (low) to reset TAP-related logic
2. Assert ``client_scan_ctrl_i.rst_n`` (low) to reset scan registers
3. Hold reset for minimum 2 clock cycles
4. Release resets and wait for stabilization

**Reset Sources**:

* ``client_tap_ctrl_i.trst_n``: Asynchronous test reset (TRST)
* ``client_scan_ctrl_i.rst_n``: Scan chain reset, can be asserted due to TAP controller Test-Logic-Reset (TLR) state transitions

**3DCR Register Reset**:

The 3DCR register reset can be controlled via the ``config_hold`` bit:

* When ``config_hold=0``: 3DCR resets on either TRST or TLR transitions
* When ``config_hold=1``: 3DCR maintains state during TLR transitions, only TRST can reset it

This allows the 3DCR configuration to persist across TAP state machine operations.

Power Considerations
~~~~~~~~~~~~~~~~~~~~

The module is fully synchronous with:

* No asynchronous logic (except reset)
* Clock gating friendly (all registers enable-qualified)
* Minimal power in idle state (no toggling when not selected)

Testing Recommendations
~~~~~~~~~~~~~~~~~~~~~~~

1. **Scan Chain Integrity**: Test scan path with known patterns
2. **3DCR Access**: Verify read/write of all 3 bits
3. **TMS Control**: Validate mux operation with stap_sel
4. **Pipeline Stages**: Test with all configuration options
5. **Reset Behavior**: Verify config_hold functionality
