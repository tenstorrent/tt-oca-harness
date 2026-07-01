========
Overview
========

Introduction
============

The Cross Trigger Network (CTN) is a key component of the Debug and Test Ports (DTP) subsystem that enables cross trigger functionality between chiplets in a System-in-Package (SiP) as well as between on-chip debug modules. It implements the Open Chiplet Cross Triggering (OCCT) specification.

The CTN aggregates:

* External Cross Trigger Ports (CTPs) for die-to-die cross triggering via GPIO pads
* Internal Cross Trigger Ports for on-chip cross trigger signal processing
* A Cross Trigger Matrix (CTM) for routing triggers between all ports
* Clock stop control logic for system-wide clock gating

Purpose
=======

The primary purposes of the CTN are:

1. **Die-to-Die Cross Triggering**: Enable debug triggers to propagate between chiplets in a multi-die package
2. **On-Chip Cross Triggering**: Route cross trigger signals between internal debug modules (e.g., CLAs)
3. **Unified Management**: Provide a single AXI-Lite interface for configuring all cross trigger functionality
4. **Clock Stop Coordination**: Aggregate clock stop requests from multiple sources

Key Features
============

External Cross Trigger Ports
----------------------------

* Configurable number of external CTPs (1-32, default 16)
* Each CTP supports both Wire-OR and Point-to-Point signaling modes
* Four GPIO pads per CTP for full handshaking capability
* Individual CSR interfaces for runtime configuration

Internal Cross Trigger Ports
----------------------------

* Configurable number of internal CTPs (0-32, default 1)
* Use core-only CTP modules without CSRs (static configuration)
* Mode configured at synthesis time via parameters
* Direct connection to internal cross trigger interfaces

Cross Trigger Matrix
--------------------

* Routes triggers between all CTPs (external and internal)
* Configurable routing via CSR registers
* Supports OR-ing multiple source signals to a single destination

Clock Stop Control
------------------

* Aggregates multiple clock stop request inputs
* OR-tree reduction for combining requests
* Gated by CLA clock stop enable from JTAG interface
* Registered output for glitch-free operation

Configuration Parameters
========================

The CTN supports the following configuration parameters:

+-------------------+----------+---------+----------------------------------------+
| Parameter         | Range    | Default | Description                            |
+===================+==========+=========+========================================+
| NUM_CTP           | 1-32     | 16      | Number of external Cross Trigger Ports |
+-------------------+----------+---------+----------------------------------------+
| NUM_INT_CT        | 0-32     | 1       | Number of internal cross triggers      |
+-------------------+----------+---------+----------------------------------------+
| NUM_CLK_STOP_REQ  | 1-32     | 1       | Number of clock stop request inputs    |
+-------------------+----------+---------+----------------------------------------+
| INT_CT_MODE       | bit vec  | '0      | Mode per internal CTP (0=pulse, 1=hs)  |
+-------------------+----------+---------+----------------------------------------+

Address Map
===========

The CTN provides a unified address space for all CSRs within a 2KB (0x800) address range:

* **CTM**: 0x0000-0x01FF (512 bytes, enough for up to 64 CT_SRC register pairs, 8 bytes each)
* **External CTPs**: 0x0200 + (CTP_index × 0x10)

Each CT_SRC uses 8 bytes (CONFIG_0 + CONFIG_1) to support up to 64 CT_DST ports. Each CTP is allocated 16 bytes (0x10) of address space, which is sufficient for its 3 registers (CONFIG, STATUS, STRETCH_MULT).

Example for NUM_CTP = 16:

+------------+---------------------+---------------------+------------------+
| Module     | Start Address       | End Address         | Size             |
+============+=====================+=====================+==================+
| CTM        | 0x0000_0000         | 0x0000_01FF         | 512 bytes (0x200)|
+------------+---------------------+---------------------+------------------+
| CTP[0]     | 0x0000_0200         | 0x0000_020F         | 16 bytes (0x10)  |
+------------+---------------------+---------------------+------------------+
| CTP[1]     | 0x0000_0210         | 0x0000_021F         | 16 bytes (0x10)  |
+------------+---------------------+---------------------+------------------+
| ...        | ...                 | ...                 | ...              |
+------------+---------------------+---------------------+------------------+
| CTP[15]    | 0x0000_02F0         | 0x0000_02FF         | 16 bytes (0x10)  |
+------------+---------------------+---------------------+------------------+

Total address space: 0x300 bytes (768 bytes) for NUM_CTP=16, well within the 0x800 (2KB) limit.
