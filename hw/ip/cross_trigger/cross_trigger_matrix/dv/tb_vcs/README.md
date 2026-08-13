Cross Trigger Matrix Testbench
==============================

This directory contains the VCS testbench for the Cross Trigger Matrix IP.

**Note**: the top-level testbench module is not present in this tree. Upstream
generated `tb_cross_trigger_matrix.sv` from a Mako template alongside the RDL and
the RTL, and only the generated RTL was carried over. `tb.f` still names the file,
so this testbench does not elaborate as-is; the CTM is covered here through the
CTN and DTP testbenches instead.

Testbench Structure
------------------

* **tb_cross_trigger_matrix.sv**: Top-level testbench module (not ported, see above)
* **test/**: Python test files using cocotb
  * **test_base.py**: Base test class with common utilities
  * **test_sanity.py**: Basic sanity test
  * **test_routing.py**: Comprehensive routing tests
* **axil_vip/**: AXI-Lite Verification IP for register access (reuse from cross_trigger_port)

Test Plan
---------

See ../../doc/architecture.adoc and ../../doc/interface.adoc for the design
description this testbench checks against.

Quick Start
-----------

1. Regenerate register collateral if `regs/gen/` is stale:
   ```bash
   make -f ocah.mk ocah-regen-regs TARGET=cross_trigger_matrix
   ```

2. Run sanity test:
   ```bash
   make test_sanity
   ```

3. Run all tests:
   ```bash
   make test
   ```

4. Run specific test:
   ```bash
   make TEST=test_routing run
   ```

5. Run with waveforms:
   ```bash
   make TEST=test_sanity WAVES=1 run
   ```

Test Descriptions
----------------

**test_sanity**: Basic smoke test that verifies:
- Register write/read functionality
- Basic routing (CT_Dst[0] -> CT_Src[0])
- Pulse propagation timing
- Output registration

**test_routing**: Comprehensive routing tests including:
- Single source routing (all combinations)
- Multi-source ORing
- Broadcast routing
- Disable output functionality
- Register readback verification

Requirements
------------

* VCS simulator
* Cocotb framework
* Python 3.7+
* AXI-Lite VIP (from cross_trigger_port/dv/tb_vcs/axil_vip)
