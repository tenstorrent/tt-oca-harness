<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS DV

Open-source DV environment for the SEP (Security Processor) subsystem, built on
cocotb/PyUVM and driven by `tools/dv/run_dv.py --dut sep`.

**DUT** = `sep_wrapper` (`hw/top/sep_wrapper.sv`) — the bare `sep` core
(`hw/sys/sep/rtl/sep.sv`) plus its IP integration
(`hw/top/sep_ip_integration.sv`: real memory macros and the generic eFuse model).
The OpenTitan SPI host is inside the `sep` core (`sep_io` / `sep_ot_spi_wrap`);
its pads come out of the wrapper. There is no SPI pad mux in this build.
**Backend** = Verilator is the reference backend; VCS and Xcelium also run.
Everything the environment needs lives under this tree.

## Prerequisites

| Need | Why | Notes |
|---|---|---|
| Verilator 5.x | the acceptance backend | CI pin 5.050 |
| g++ ≥ 10 | Verilator `--timing` / `-fcoroutines` | RHEL-8's default g++ 8.5 fails with `unrecognized command line option '-fcoroutines'`; `source /opt/rh/gcc-toolset-11/enable` |
| Python ≥ 3.11 | launcher | `run_dv.py` bootstraps the locked uv-managed DV env itself (root `uv.lock`, `dv` group → cocotb + pyuvm + cocotbext-axi) |
| RISC-V bare-metal GCC | firmware-boot tests only | not needed for the `smoke` tag |

No VeeR EL2 setup step is needed — the config snapshot is committed collateral.
See [Troubleshooting](#troubleshooting) if a build complains about it.

## Quick start

```bash
PY=tools/dv/run_dv.py

# 1. What tests exist (testlists/ is the authoritative index).
python3 $PY --dut sep --items all --list

# 2. Green in minutes: the no-CPU AXI smoke subset. No firmware build needed.
python3 $PY --dut sep --items all --tag smoke --stage sim

# 3. One named test, from filelist through simulation. Include
#    --stage hdl_compile: --stage sim alone reuses whatever model is on disk,
#    and a stale one can report a pass that the current RTL would not give.
python3 $PY --dut sep --items sep_axi_smoke_test \
  --stage flist --stage hdl_compile --stage sim
```

Firmware-boot tests need their image built first:

```bash
make -C hw/sys/sep/dv/fw -f fw.mk dv-fw-tests TEST=hello_world OCAH_ROOT="$PWD"
python3 $PY --dut sep --items all --tag boot --stage sim
```

Full regression, fresh seed per leaf:

```bash
python3 $PY --dut sep --items all --stage sim --regress
```

The model rebuilds on SV/config change; Python-only changes reuse it. `all` is
the maximum group and tags select subsets. For a randomized test that should run
multiple seeds in one regression, set `reseed = N` in its TOML entry; reproduce a
single failing leaf with `--stage sim --seed N`.

## Results and evidence

Per-run logs land in `build/runs/<run-id>/` (gitignored).

**PASS/FAIL requires positive evidence from `results.xml` — a clean simulator
exit alone is not enough.** A test passing is the entry condition for reading
its checkers, never a substitute for them, and a checker row exists only if a run
can prove it. A log tag is not the proof.

The contracts themselves:

* [`docs/index.adoc`](docs/index.adoc) — SEP DV documentation book (entry point)
* [`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc) — testbench architecture: VIP
  policy, env hierarchy, HDL top, stimulus and checking. Also the detail the
  README leaves out — eFuse content selection (the `+sep_efuse_preload` selector,
  the `SepEfuseImage` golden, the sense-and-compare flow), what backs the memory
  / eFuse / SPI ports inside `sep_wrapper` and their backdoor plusargs, CPU-trace
  reconstruction and symbolization, and the Boot ROM image builds.
* [`docs/SEP_VPLAN.adoc`](docs/SEP_VPLAN.adoc) — verification plan: per-test
  contracts and checkers, naming rules, VIP policy, iconic feature scorecard.

## Code coverage

`--cov` is collected on VCS. Only `[coverage.vcs]` applies the compile-time
scope, so that is the graded number. It instruments the build, writes one
native database per test leaf (`coverage/simv.vdb` under each leaf), and
merges/reports through the `cov_merge`/`cov_report` stages into
`<run_dir>/cov/merged.vdb`. That is `-cm line+cond+tgl+fsm+branch+assert` at
both compile (`{build_cov_dir}`) and sim (`{cov_dir}/simv.vdb`), merged by
`urg`. `--cov --tool verilator` is not the graded number. Verilator 5.046
fails that C++ compile (`__PVT__MLKEM_SHARED_KEY` under `VM_COVERAGE=1`);
5.050 compiles.

```bash
python3 tools/dv/run_dv.py --dut sep --items all --regress --cov --tool vcs \
  --target default --sim-jobs 32 --build-jobs 32
```

`all` is the coverage set: every test the VPLAN grades, which is exactly `no_cpu`
+ `cpu`. Boot ROM firmware (`rom_fw`) is not a member -- another owner, a third
RTL target, firmware rather than hardware contracts -- so reaching those four
means naming `rom_fw`. `all`'s `expected_count` fails the run when membership
drifts from the class groups.

`--target default` compiles the full CPU once. no_cpu leaves force-splice the
LSU VIP onto the post-remap request; cpu leaves run as firmware. Every leaf is
one elaboration. Edit `cov/config/vcs/sep_cov_scope.hier` then `--rebuild`.

What the resulting number is not:

* **Not functional coverage.** These are code metrics only. No SV covergroups
  exist in the cocotb env, so "did we exercise the interesting scenarios" stays
  with [`docs/SEP_VPLAN.adoc`](docs/SEP_VPLAN.adoc).
* **The DUT minus the CPU, not the whole DUT.** `cov/config/vcs/sep_cov_scope.hier`
  excludes the testbench top, the outbound mailbox, the backdoor SMC memory, the
  AXI SVA module and the CPU subtree at compile time, across both code and
  assertion coverage (`-cm_hier` with `-cm_common_hier`). Measured on a merged
  database: the excluded instances leave the hierarchy entirely and `sep_uvm_top`
  matches `u_dut` in all six columns. So the percentage is the SEP DUT **with the
  CPU subtree removed** -- quote it that way, never as bare "SEP DUT coverage".
  `cov/config/vcs/README.md` records the scope and the measurements behind it.
* **Not a read on assertions.** Assertion coverage counts elaborated assertions
  only, and SEP gates those through the `prim_assert` shim. Confirm assertions
  are live before reading that column.
* **One seed per leaf.** `--regress` takes a fresh seed per leaf, so a randomized
  test contributes one sample. Pin seeds for any number that gets cited.

## Two run modes

The run mode selects who owns the CPU master buses. The entries below are
entry-point examples, not the full list — use `--items all --list` for that.

### No-CPU AXI — `run_modes.no_cpu`, tag `smoke`

The CPU is held off (`mpc_reset_run_req=0`) and a cocotbext-axi `AxiMaster`
drives the CPU LSU bus (`sep_cpu.lsu_axi_req` / `lsu_axi_resp`, bridged to the
flat `s_axi_*` ports). The no_cpu build swaps in the `sep_cpu` stub, which is the
sole driver of that bus and drives `lsu_axi_req` from `tb_top`'s `lsu_req_drive`
with a plain `assign` — not a `force`.

* `sep_axi_smoke_test` — reset-value read of `sep_cpu_ctrl.SEP_LOCAL_BASE_ADDR`
  (`+0x0C8`) for decode sanity, then a masked write/readback walk of
  `SEP_SW_DEBUG`, `SEP_NMI_VEC`, `RAS_BANK_INFO`, and `PKA_CTRL`.
* `sep_address_map_test` — `sep_cpu_ctrl` sweep plus one CSR per LSU-reachable
  block (DMA, WDT, scratch, reset, OTBN/AES/HMAC/KMAC, CSRNG/EDN/ESRC, ABR,
  entropy pool, lifecycle, KM/AXI mailbox, eFuse shadow, inbound filter,
  alias/outbound remap, SPI). Not CSR bit-bash and not dead-space refuse.

### CPU firmware boot — `run_modes.cpu`, tag `boot`

`+cpu_boot` runs the full-CPU build, so the core owns its buses and runs firmware
from the wrapper's real TCM macros, backdoor-loaded by `tb_backdoor_mem` in
`tb/tb_top.sv`.

* `sep_hello_world_test` — backdoor-loads the OSS `fw/tests/hello_world` image
  into ICCM/DCCM and passes `rst_vec=0xC0000000` to `tb_top.sv`, which programs
  the EL2 reset-vector TDR through JTAG before reset releases and sets
  `mpc_reset_run_req=1`. The test boots VeeR EL2 and checks PC advance
  (`sep_cpu_trace`) plus the firmware banner and PASS magic on the outbound
  mailbox (`tb/sep_outbound_mbx.sv`).

Boot/reset invariant: `ext_boot_seq_done_i=1`. Fuse-sense policy is testcase
metadata, not a run mode: non-eFuse tests usually add `+skip_fuse_sense` to their
testlist entry's `args` to bypass the slow sense path. Real eFuse tests omit that
bypass and let the RTL fuse-sense FSM finish against the generic eFuse model.

Production Boot ROM firmware tests belong to the ROM-FW owner and need extra
build steps — see
[`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc#_boot_rom_firmware_builds).
Key Manager `rom_main` tests declare
`firmware = { name = "rom_main", mode = "km_rom_main" }` so `c_compile` builds
the gitignored `rom_main.rom.parhex`.

## Layout

```
hw/sys/sep/dv/
├── cocotb/              # flow-first: cocotb owns env + stimulus + tests
│   ├── assertions/      #   cocotb Python checkers
│   ├── env/             #   PyUVM env: agents, scoreboards, config
│   ├── seq_lib/         #   sequences (scenarios)
│   ├── tests/           #   @pyuvm.test() entries, grouped by subsystem
│   └── dv_sim_prestage.py  # pre-sim hook (stages out/sep_efuse.hex)
├── cov/                 # cov/config/<tool>/ (questa, vcs, verilator, xcelium)
│                        #   and cov/sv/. `--cov` is graded on VCS ([coverage.vcs]).
├── docs/                # testbench architecture + verification plan (AsciiDoc)
├── fw/                  # OSS-owned firmware (drivers/ tests/) — see fw/README.md
│                        # the Boot ROM lives outside DV, at ../bootrom/prod/
├── models/              # SEP-local SystemRDL: models/regs/sep_external.rdl is the
│                        #   open stand-in that satisfies sep.rdl's sep_external
│                        #   include -- eFuse SHIM control plus the execute-in-place
│                        #   window. Excluded for OSS hygiene: proprietary IPs in
│                        #   nonfree. Firmware includes the open C headers
│                        #   (models/regs/gen/c/sep_external.h) via sep.h; the
│                        #   SV addrmap package is the RTL build input.
├── shims/               # SEP-local behavioral sim-models
│   ├── prim/            #   prim_sync2 → prim_flop_2sync override, prim_assert
│   ├── cpu/             #   sep_cpu_stub (no_cpu build: LSU demux, no VeeR)
│   ├── crypto/          #   abr_wrapper_key_reg_stub (Verilator ABR CSR shim)
│   └── analog/          #   entropy_ring_oscillator
├── tb/                  # DUT-only top + helper RTL
│   ├── tb_top.sv        #   module sep_uvm_top (wraps sep_wrapper) + tb_backdoor_mem
│   ├── sep_outbound_mbx.sv  # outbound mailbox responder + console/PASS monitor
│   ├── efuse_preloads/  #   efuse_configurations/*.toml declare OTP images by
│   │                    #   register/field; sep_efuse_default.hex is the one
│   │                    #   committed image (a random-vector snapshot)
│   └── interfaces/      #   (SV interfaces — empty for now)
├── testlists/           # native TOML testlists (all.toml + per-subsystem leaves)
├── sep_sim_cfg.toml     # block build/filelist manifest, run modes, tool knobs
├── sep_public_scope.vlt # scoped Verilator public list (narrow on purpose: a global
│                        #   --public-flat-rw wedges the Verilator model)
├── sep_sim.core         # FuseSoC-style manifest for external consumers
├── build/               # generated: per-tool models + build/runs/<run-id>/ logs (gitignored)
└── README.md
```

## OSS hygiene

The bender filelist uses targets `["sep", "sep_el2", "sep_wrapper"]` only — never
`"simulation"`, which pulls licensed I/O and a foundry padring. Verify
vendor-clean with `tools/dv/check_no_vendor_paths.py`.

`[build].exclude_files` holds only `abr_wrapper_key_reg.sv` — a Verilator
PeakRDL miscompile workaround, replaced by `shims/crypto/abr_wrapper_key_reg_stub.sv`.
Proprietary IPs that are not in the OSS checkout are simply not on the filelist.

## Troubleshooting

**`Define or directive not defined: '`TEC_RV_ICG'`** (from
`vendor/chipsalliance/Cores-VeeR-EL2/upstream/design/lib/beh_lib.sv`) — the committed VeeR EL2 config snapshot is
missing or was clobbered. Check it:

```bash
grep TEC_RV_ICG vendor/chipsalliance/Cores-VeeR-EL2/overlay/snapshots/sep/common_defines.vh
# expect: `define TEC_RV_ICG clockhdr
```

Restore it from git rather than regenerating. The snapshot is committed
collateral (see that package's `Bender.yml`), so a fresh clone builds as is; it
lives in `overlay/` so `bender vendor init` — which wipes and recreates
`upstream/` only — never touches it.

**`unrecognized command line option '-fcoroutines'`** — g++ is too old for
Verilator `--timing`. See [Prerequisites](#prerequisites).

**`No module named tt_boot_manifest`** — the manifest packer submodule is not
checked out; only affects Boot ROM builds. See
[`docs/SEP_TB_ARCH.adoc`](docs/SEP_TB_ARCH.adoc#_boot_rom_firmware_builds).
