Scrambler DV
============

IP-level cocotb bench for the SRAM scrambler family, running on the unified
DV flow (`tools/dv/run_dv.py`, DUT name `scrambler`).

Layout
------

* `scrambler_sim_cfg.toml` — flow configuration (build recipe, cocotb
  framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`scrambler_tb_top`): every sized
  variant (512 to 8192 words) in both `BYTE_WISE` modes, each behind its own
  `<mode><depth>_*` pin bundle (`w` word mode, `b` byte-wise mode). The design
  is combinational and the bench uses no clock.
* `cocotb/tests/` — test modules; `scrambler_base_test.py` carries the variant
  table, the pin-level scramble/descramble helpers and the byte-lane merge
  model of a byte-maskable memory.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).
* `lint/` — slang-tidy configuration for the scrambler RTL.

The RTL closure comes from the `scrambler` Bender target alone; the family
depends on no shared package.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut scrambler

# Everything
python3 tools/dv/run_dv.py --dut scrambler --items all

# One test with waves
python3 tools/dv/run_dv.py --dut scrambler --items scrambler_bytewise_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `scrambler_roundtrip_test` — on every variant with a random key: the
  address map is a permutation of the address space, random and sequential
  words round-trip through a memory indexed by scrambled address, and the
  scrambled data depends on both the address and the key.
* `scrambler_bytewise_test` — byte-wise variants keep every lane
  independently descramblable under byte-masked writes into a lane-merging
  memory, and a word-mode variant demonstrably does not.

Expected behavior is taken from `../doc/architecture.adoc` and the module
headers under `../rtl/`.
