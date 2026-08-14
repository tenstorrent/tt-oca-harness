Cross Trigger Matrix Testbench
==============================

This directory contains the VCS testbench for the Cross Trigger Matrix IP.

This testbench does not run in this repository. Two pieces were never
ported: the top-level module `tb_cross_trigger_matrix.sv` that `tb.f` names is
absent, and the `Makefile` reads its filelists from `hw/ip/cross_trigger_matrix/tb_vcs/`,
a path that predates the move to `hw/ip/cross_trigger/cross_trigger_matrix/dv/`.
The tests and `rtl.f` below are kept current, so bringing this up means porting
the top module and repointing those two `Makefile` paths.

Until then the matrix is verified at the DTP level, where the `dtp_ctm_*` and
`dtp_xtrig_*` scenarios cover routing, CSR access, and reset behavior:

```bash
python3 tools/dv/run_dv.py --dut dtp --items dtp_ctm_rand_all_scenarios_test
```

Testbench Structure
------------------

* **tb_cross_trigger_matrix.sv**: Top-level testbench module (not present, see above)
* **test/**: Python test files using cocotb
  * **test_base.py**: Base test class with common utilities
  * **test_sanity.py**: Basic sanity test
  * **test_routing.py**: Comprehensive routing tests
* **axil_vip/**: AXI-Lite Verification IP for register access (reuse from cross_trigger_port)

Register addresses and the port count come from the generated Python header in
`regs/gen/py/`, so resizing the matrix is a change to the RDL defaults plus a
rerun of the register flow; see the IP README for that flow. There is no
`generate_ip.py` in this repository.

Test Plan
---------

The CTM scenarios are enrolled in the DTP verification plan,
`hw/sys/dtp/dv/docs/DTP_VPLAN.adoc`.

Intended Usage
--------------

Once the top module is ported, the `Makefile` targets are:

```bash
make test_sanity              # sanity test
make test                     # all tests
make TEST=test_routing run    # a specific test
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
