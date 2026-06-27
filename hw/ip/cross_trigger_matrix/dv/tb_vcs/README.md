Cross Trigger Matrix Testbench
==============================

This directory contains the VCS testbench for the Cross Trigger Matrix IP.

Testbench Structure
------------------

* **tb_cross_trigger_matrix.sv**: Top-level testbench module
* **test/**: Python test files using cocotb
  * **test_base.py**: Base test class with common utilities
  * **test_sanity.py**: Basic sanity test
  * **test_routing.py**: Comprehensive routing tests
* **axil_vip/**: AXI-Lite Verification IP for register access (reuse from cross_trigger_port)

Test Plan
---------

See doc/verification.rst for detailed test plan.

Quick Start
-----------

1. Generate IP files (registers, RTL package, testbench):
   ```bash
   cd ..
   python3 generate_ip.py --num-ct-src <N> --num-ct-dst <M>
   ```
   Where ``<N>`` and ``<M>`` are the number of CT_Src and CT_Dst ports (1-32, default: 4).

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
* AXI-Lite VIP (from cross_trigger_port/tb_vcs/axil_vip)
