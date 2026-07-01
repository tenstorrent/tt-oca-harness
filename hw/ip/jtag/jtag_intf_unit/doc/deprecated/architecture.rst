=============
Architecture
=============

The JTAG Interface Unit architecture implements a hierarchical JTAG infrastructure with three primary subsystems: the PTAP core, the STAP scan chain, and the iJTAG SIB network. This section provides detailed architectural descriptions of each subsystem.

Module Hierarchy
================

The JTAG Interface Unit (``jtag_intf_unit``) instantiates the following sub-modules:

* **jtag_ptap**: JTAG Primary TAP (IEEE 1149.1/1687/1838 compliant)
* **jtag_stap** (I/O STAP): Chiplet-to-chiplet STAP interface
* **jtag_stap** (SEP Debug STAP): SEP debug STAP interface
* **jtag_stap** (Extra STAPs): Additional local STAP interfaces (0..N-1)
* **prim_jtag_sib_mux_post** (DFT SIB): iJTAG SIB for DFT access
* **prim_jtag_sib_mux_post** (DFD SIB): iJTAG SIB for DFD access

STAP Scan Chain
===============

The STAP scan chain implements IEEE 1838 multi-die test architecture support, allowing the PTAP to access secondary TAPs on remote dies or local on-chip TAP controllers.

Chain Topology
--------------

The STAP scan chain is organized as a daisy-chain of STAPs connected through the PTAP's STAP scan interface:

.. code-block:: text

                                  STAP Scan Chain Topology

      From PTAP                                                             Extended STAP Scan (External chain continuation)
    STAP Scan Out ──┐                                                   ┌─▶ STAP Scan In
                    │                                                   │
                    ▼                                                   │
              ┌───────────┐    ┌───────────┐    ┌───────────┐           │
              │  I/O STAP │───▶│  SEP STAP │───▶│Extra STAPs│───────────┘
              │           │    │           │    │  [0..N-1] │
              └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
                    │                │                │
                    ▼                ▼                ▼
              Host TAP I/F     Host TAP I/F    Host TAP I/F
              (to I/O pads)    (to SEP debug)  (to local TAPs)

Data Flow
~~~~~~~~~

1. **PTAP Scan Out**: Serial scan data from PTAP enters the STAP chain
2. **I/O STAP**: First STAP in chain; provides chiplet-to-chiplet connectivity
3. **SEP STAP**: Second STAP; provides SEP debug access (if enabled)
4. **Extra STAPs**: Additional STAPs for local connectivity (if NUM_EXTRA_STAPS > 0)
5. **Extended Scan**: Output continues to external STAP scan interface
6. **PTAP Scan In**: Return path from extended scan interface

.. note::
   The chain conditionally instantiates stages. If ``STAP_IO_ENABLE=0`` the I/O STAP is bypassed; if ``SEP_DBG_ENABLE=0`` the SEP STAP is bypassed. The scan path still closes through the remaining chain and the extended STAP scan interface.

Control Signals
~~~~~~~~~~~~~~~

All STAPs share common scan control from the PTAP:

* ``ptap_stap_host_scan_ctrl``: Merged IR/DR scan control signals
* ``ptap_host_tap_ctrl``: TAP control (TMS, TRST_n, TCK)

Each STAP can independently enable/disable its host interface via its 3DCR ``stap_sel`` bit.

I/O STAP (Chiplet-to-Chiplet)
-----------------------------

The I/O STAP provides JTAG connectivity between chiplets:

.. code-block:: text

                          ┌─────────────────────────────────────┐
                          │             I/O STAP                │
                          │                                     │
    ptap_stap_host_       │  ┌─────────────────────────────┐    │
    scan_ctrl ────────────┤  │    prim_jtag_sib_mux_pre    │    │
    ptap_stap_host_       │  │    (3DCR Register + SIB)    │    │
    scan_out ─────────────┤  └─────────────────────────────┘    │
                          │                 │                   │
                          │                 ▼                   │
                          │  ┌─────────────────────────────┐    │
                          │  │     TDI Lockup Latch        │    │  ◀── host_tdi_i
                          │  │   (TDI_LOCKUP=1)            │    │
                          │  └─────────────────────────────┘    │
                          │                                     │
    stap_io_scan_out ◀────┤  Scan Chain Output                  │
                          │                                     │
                          │  Host TAP Control:                  │
    stap_io_host_         │  • tms = stap_sel ? client_tms :   │
    tap_ctrl_o ◀──────────┤           tms_hold                  │
    stap_io_host_         │  • trst_n = client_trst_n           │
    tdo_o ◀───────────────┤  • tck = client_tck                 │
    stap_io_host_         │                                     │
    tdo_oen_o ◀───────────┤  TDO Enable = stap_sel && shift_en  │
                          └─────────────────────────────────────┘

**Key Configuration**:

* ``TDI_LOCKUP = 1``: Enabled for die boundary crossing timing
* ``SCAN_IN_PIPE = 0``: No additional pipeline stage
* ``SCAN_OUT_LOCKUP = 0``: No lockup on scan output

**3DCR Control Register**:

.. list-table::
   :widths: 15 20 65
   :header-rows: 1

   * - Bit
     - Name
     - Description
   * - [2]
     - ``tms_hold``
     - TMS value applied to host when STAP not selected
   * - [1]
     - ``stap_sel``
     - Enable host TAP interface (routes TDI to TDO path)
   * - [0]
     - ``config_hold``
     - Prevent 3DCR reset during Test-Logic-Reset

SEP Debug STAP
--------------

The SEP Debug STAP provides access to the Security Engine Processor debug interface:

**Key Configuration**:

* ``TDI_LOCKUP = 0``: No lockup latch (on-chip connection)
* ``SCAN_IN_PIPE = 0``: No additional pipeline stage
* ``SCAN_OUT_LOCKUP = 0``: No lockup on scan output

**Chain Position**: After I/O STAP in the STAP chain

**Conditional Generation**: Only instantiated when ``SEP_DBG_ENABLE = 1``

Extra STAPs (Local Connectivity)
--------------------------------

Additional STAPs for local on-chip TAP connections:

.. code-block:: text

                                Extra STAP Chain

    extra_stap_scan_out[0] ───┐                                       ┌───▶ extra_stap_scan_out[N]
    (from SEP STAP)           │                                       │     (to extended scan)
                              ▼                                       │
                        ┌───────────┐  ┌───────────┐           ┌───────────┐
                        │Extra STAP │─▶│Extra STAP │─▶ ... ───▶│Extra STAP │
                        │    [0]    │  │    [1]    │           │   [N-1]   │
                        └─────┬─────┘  └─────┬─────┘           └─────┬─────┘
                              │              │                       │
                              ▼              ▼                       ▼
                        Host TAP I/F   Host TAP I/F           Host TAP I/F

**Key Configuration**:

* ``TDI_LOCKUP = 0``: No lockup latches (on-chip connections)
* ``SCAN_IN_PIPE = 0``: No additional pipeline stage
* ``SCAN_OUT_LOCKUP = (NUM_EXTRA_STAPS-1)``: Enabled only when more than one extra STAP is present; applied to all extra STAP instances to ease chaining timing

**Parameterization**: Number of extra STAPs controlled by ``NUM_EXTRA_STAPS`` parameter

STAP Selection and Operation
----------------------------

STAP Selection Flow
~~~~~~~~~~~~~~~~~~~

1. Load PTAP instruction ``SELECT_3DCR`` to access PTAP's 3DCR register
2. Shift ``2'b10`` to set ``stap_sel=1``, ``config_hold=0`` in PTAP 3DCR
3. STAP scan interface becomes active; PTAP TDO muxes to STAP path
4. Shift data through STAP chain to configure individual STAP 3DCRs
5. Set desired STAP's ``stap_sel=1`` to enable its host interface
6. Shift JTAG data through selected STAP to remote/local TAP

Example: Accessing Remote Chiplet
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   1. Enable STAP path in PTAP:
      IR ← SELECT_3DCR
      DR ← {stap_sel=1, config_hold=0}

   2. Configure I/O STAP 3DCR:
      DR ← {tms_hold=0, stap_sel=1, config_hold=1}

   3. Remote chiplet TAP is now accessible via I/O STAP TDI/TDO

iJTAG SIB Network
=================

The iJTAG network implements IEEE 1687 hierarchical instrument access using Segment Insertion Bits (SIBs).

Network Topology
----------------

The iJTAG network connects two SIB modules in series:

.. code-block:: text

                                 iJTAG SIB Network

    From PTAP                                                              To PTAP
    iJTAG Scan Out ──┐                                                 ┌── iJTAG Scan In
                     │                                                 │
                     ▼                                                 │
               ┌───────────┐         ┌───────────┐                     │
               │  DFT SIB  │────────▶│  DFD SIB  │─────────────────────┘
               └─────┬─────┘         └─────┬─────┘
                     │                     │
                     ▼                     ▼
               Host Scan I/F         Host Scan I/F
               (to DFT network)      (to DFD network)

Chain Order
~~~~~~~~~~~

1. **DFT SIB**: First SIB in chain; accesses Design-for-Test instruments
2. **DFD SIB**: Second SIB in chain; accesses Design-for-Debug instruments

SIB Architecture (prim_jtag_sib_mux_post)
-----------------------------------------

Each SIB implements a mux-after-register topology:

.. code-block:: text

                        ┌─────────────────────────────────────┐
                        │         prim_jtag_sib_mux_post      │
                        │                                     │
    client_scan_ctrl ───┤  ┌─────────────────────────────┐    │
    client_scan_in ─────┤  │   1-bit SIB Enable Register │    │
                        │  │   (prim_jtag_scan_reg)      │    │
                        │  └──────────────┬──────────────┘    │
                        │                 │                   │
                        │           sib_en│                   │
                        │                 │                   │
                        │                 ▼                   │
                        │           ┌───────────┐             │
                        │           │  Output   │             │
    client_scan_out ◀───┤◀──────────│   Mux     │◀────────────┤◀── host_scan_in
                        │           └───────────┘             │
                        │                                     │
                        │  host_scan_ctrl:                    │
    host_scan_ctrl ◀────┤  • select = client_select && sib_en│
    host_scan_out ◀─────┤  • capture_en = client_capture_en  │
                        │                    && client_select │
                        │  • shift_en = client_shift_en      │
                        │                    && client_select │
                        │  • update_en = client_update_en    │
                        │                    && client_select │
                        └─────────────────────────────────────┘

**Output Mux Logic**:

.. code-block:: systemverilog

   assign client_scan_out_o = sib_en ? host_scan_in_i : host_scan_out_o;

When ``sib_en=0``: Scan data bypasses the host network (single-bit path)
When ``sib_en=1``: Scan data routes through the host instrument network

SIB Configuration
-----------------

Both DFT and DFD SIBs are configured identically:

.. list-table::
   :widths: 25 15 60
   :header-rows: 1

   * - Parameter
     - Value
     - Description
   * - ``LOCKUP``
     - 0
     - No lockup latch on SIB register output
   * - ``SAFE_SELECT``
     - 0
     - No additional flop stage on sib_en output

iJTAG Access Flow
-----------------

1. Load PTAP instruction ``SELECT_IJTAG`` to access iJTAG scan path
2. Shift ``1'b1`` to enable DFT SIB (first bit)
3. Continue shifting to access DFT instrument network
4. Or shift ``1'b0`` to bypass DFT SIB, then ``1'b1`` to enable DFD SIB
5. Continue shifting to access DFD instrument network

Example: Accessing DFD Network
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   1. Select iJTAG path:
      IR ← SELECT_IJTAG

   2. Bypass DFT SIB, enable DFD SIB:
      DR ← {dfd_sib_en=1, dft_sib_en=0}
           (shifts through: DFT SIB → DFD SIB)

   3. DFD network is now in scan path
      Subsequent DR shifts access DFD instruments

Port Interface
==============

Primary JTAG Interface
----------------------

Connection to external JTAG controller:

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``ptap_client_tap_ctrl_i``
     - Input
     - TAP control (TMS, TRST_n, TCK)
   * - ``ptap_client_tdi_i``
     - Input
     - Test data input
   * - ``ptap_client_tdo_o``
     - Output
     - Test data output
   * - ``ptap_client_tdo_oen_o``
     - Output
     - TDO output enable

Boundary Scan Interface
-----------------------

Connection to external BSR chain:

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``bsr_host_scan_ctrl_o``
     - Output
     - BSR scan control signals
   * - ``bsr_host_scan_in_i``
     - Input
     - BSR chain return data
   * - ``bsr_host_scan_out_o``
     - Output
     - BSR chain input data

I/O STAP Interface
------------------

Chiplet-to-chiplet JTAG connection:

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``stap_io_host_tap_ctrl_o``
     - Output
     - TAP control to remote chiplet
   * - ``stap_io_host_tdi_i``
     - Input
     - TDI from remote chiplet
   * - ``stap_io_host_tdo_o``
     - Output
     - TDO to remote chiplet
   * - ``stap_io_host_tdo_oen_o``
     - Output
     - TDO output enable

SEP Debug STAP Interface
------------------------

SEP debug connection (when SEP_DBG_ENABLE=1):

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``stap_sep_host_tap_ctrl_o``
     - Output
     - TAP control to SEP debug
   * - ``stap_sep_host_tdi_i``
     - Input
     - TDI from SEP debug
   * - ``stap_sep_host_tdo_o``
     - Output
     - TDO to SEP debug
   * - ``stap_sep_host_tdo_oen_o``
     - Output
     - TDO output enable

Extra STAP Interfaces
---------------------

Additional local STAP connections (array size equals NUM_EXTRA_STAPS, minimum 1):

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``stap_extra_host_tap_ctrl_o``
     - Output
     - TAP control array to local TAPs
   * - ``stap_extra_host_tdi_i``
     - Input
     - TDI array from local TAPs
   * - ``stap_extra_host_tdo_o``
     - Output
     - TDO array to local TAPs
   * - ``stap_extra_host_tdo_oen_o``
     - Output
     - TDO output enable array

Extended STAP Scan Interface
----------------------------

External STAP chain continuation:

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``stap_host_scan_ctrl_o``
     - Output
     - STAP scan control signals
   * - ``stap_host_scan_in_i``
     - Input
     - Return data from extended chain
   * - ``stap_host_scan_out_o``
     - Output
     - Output to extended chain

iJTAG DFT Interface
-------------------

DFT instrument network connection:

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``dft_host_scan_ctrl_o``
     - Output
     - DFT scan control signals
   * - ``dft_host_scan_in_i``
     - Input
     - Return data from DFT network
   * - ``dft_host_scan_out_o``
     - Output
     - Output to DFT network

iJTAG DFD Interface
-------------------

DFD instrument network connection:

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``dfd_host_scan_ctrl_o``
     - Output
     - DFD scan control signals
   * - ``dfd_host_scan_in_i``
     - Input
     - Return data from DFD network
   * - ``dfd_host_scan_out_o``
     - Output
     - Output to DFD network

AXI Debug Interfaces
--------------------

JTAG-to-AXI bridge connections (from PTAP):

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``axi_smc_dbg_req_o``
     - Output
     - SMC fabric AXI4 request
   * - ``axi_smc_dbg_resp_i``
     - Input
     - SMC fabric AXI4 response
   * - ``axil_smc_otp_jtag_req_o``
     - Output
     - SMC OTP AXI-Lite request
   * - ``axil_smc_otp_jtag_resp_i``
     - Input
     - SMC OTP AXI-Lite response
   * - ``axil_sep_otp_jtag_req_o``
     - Output
     - SEP OTP AXI-Lite request
   * - ``axil_sep_otp_jtag_resp_i``
     - Input
     - SEP OTP AXI-Lite response

Control Outputs
---------------

Debug and control signals:

.. list-table::
   :widths: 30 10 60
   :header-rows: 1

   * - Signal
     - Direction
     - Description
   * - ``jtag_clock_stop_o``
     - Output
     - Clock stop request
   * - ``cla_clock_stop_en_o``
     - Output
     - CLA clock stop enable
   * - ``boot_stall_ovrd_o``
     - Output
     - Boot stall override enable
   * - ``boot_stall_o``
     - Output
     - Boot stall value
   * - ``ic_reset_ovrd_o``
     - Output
     - IC reset override enables [NUM_IC_RESET-1:0]
   * - ``ic_reset_ctrl_n_o``
     - Output
     - IC reset control values [NUM_IC_RESET-1:0]
   * - ``ptap_state_o``
     - Output
     - Current PTAP TAP state
   * - ``ptap_inst_decoded_o``
     - Output
     - Current decoded instruction

Parameter Summary
=================

.. list-table::
   :widths: 30 15 55
   :header-rows: 1

   * - Parameter
     - Default
     - Description
   * - ``BSR_ENABLE``
     - 1
     - Enable boundary scan instructions
   * - ``EXTEST_TRAIN_ENABLE``
     - 1
     - Enable EXTEST_TRAIN instruction
   * - ``EXTEST_PULSE_ENABLE``
     - 1
     - Enable EXTEST_PULSE instruction
   * - ``INTEST_ENABLE``
     - 1
     - Enable INTEST instruction
   * - ``CLAMP_ENABLE``
     - 1
     - Enable CLAMP instruction
   * - ``HIGHZ_ENABLE``
     - 1
     - Enable HIGHZ instruction
   * - ``RUNBIST_ENABLE``
     - 1
     - Enable RUNBIST instruction
   * - ``TMP_ENABLE``
     - 1
     - Enable TMP controller
   * - ``IC_RESET_ENABLE``
     - 1
     - Enable IC_RESET instruction
   * - ``SMC_DBG_ENABLE``
     - 1
     - Enable SMC debug interfaces
   * - ``SEP_DBG_ENABLE``
     - 1
     - Enable SEP debug STAP
   * - ``STAP_IO_ENABLE``
     - 1
     - Enable I/O STAP for chiplet connectivity
   * - ``NUM_IC_RESET``
     - 3
     - Number of IC_RESET control bits
   * - ``NUM_EXTRA_STAPS``
     - 0
     - Number of additional local STAPs
   * - ``IDCODE_MFR_ID``
     - 11'h000
     - JTAG IDCODE manufacturer ID
   * - ``IDCODE_PART_NUM``
     - 16'h0000
     - JTAG IDCODE part number
   * - ``IDCODE_SI_REV``
     - 4'h0
     - JTAG IDCODE silicon revision
   * - ``NUM_XTRIG_CTP``
     - 8
     - Number of cross trigger ports
   * - ``NUM_XTRIG_INT_CT``
     - 1
     - Number of internal cross triggers
   * - ``OCH_VER``
     - 8'h00
     - OCH/DTP IP version number
   * - ``SMC_OTP_RD_PL_DEPTH / SMC_OTP_WR_PL_DEPTH``
     - 2'h3
     - FIFO depth encoding for SMC OTP JTAG2AXI queues
   * - ``SEP_OTP_RD_PL_DEPTH / SEP_OTP_WR_PL_DEPTH``
     - 2'h3
     - FIFO depth encoding for SEP OTP JTAG2AXI queues
   * - ``SMC_RD_PL_DEPTH / SMC_WR_PL_DEPTH``
     - 2'h3
     - FIFO depth encoding for SMC fabric JTAG2AXI queues
   * - ``smc_jtag_axi_req_t / smc_jtag_axi_resp_t``
     - logic
     - AXI4 request/response typedefs for SMC fabric debug bridge
   * - ``smc_otp_axil_req_t / smc_otp_axil_resp_t``
     - logic
     - AXI-Lite typedefs for SMC OTP debug bridge
   * - ``sep_otp_axil_req_t / sep_otp_axil_resp_t``
     - logic
     - AXI-Lite typedefs for SEP OTP debug bridge
