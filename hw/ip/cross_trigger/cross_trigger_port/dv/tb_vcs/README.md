Cross Trigger Port Testbench
=============================

This directory contains the VCS testbench for the Cross Trigger Port IP.

Testbench Structure
------------------

* **tb_cross_trigger_port.sv**: Top-level testbench module
* **test/**: Python test files using cocotb
  * **test_base.py**: Base test class with common utilities
  * **test_sanity.py**: Basic sanity test
  * **test_wire_or_mode.py**: Wire-OR mode tests
  * **test_point_to_point_mode.py**: Point-to-Point mode tests
* **axil_vip/**: AXI-Lite Verification IP for register access

Test Plan
---------

See doc/verification.rst for detailed test plan.

Quick Start
-----------

1. Generate register files:
   ```bash
   make -f ocah.mk ocah-regen-regs TARGET=cross_trigger_port
   ```

2. Run sanity test:
   ```bash
   make test_sanity
   ```

3. Run all tests:
   ```bash
   make test
   ```
