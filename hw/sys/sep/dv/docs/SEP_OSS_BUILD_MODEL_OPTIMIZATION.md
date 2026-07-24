<!-- SPDX-License-Identifier: Apache-2.0 -->

# SEP OSS DV — Verilator Build-Model Optimization Study

> **FINAL DECISION (supersedes the 4/5-target discussion below):** collapse to **2 models** —
> `default` (cpu_all_live: full VeeR CPU) for all cpu tests, and `lsu_stub_all_live` (CPU stubbed)
> for all no_cpu tests. Both external masters (m_axi/j_axi) are **always live** in tb_top, because
> the benchmark showed external-master gating costs ~nothing; the only meaningful split is CPU
> present vs stubbed (~15.5 → ~26 ns/s). The 5-model benchmark below is the evidence for that call.

**Date:** 2026-06-28
**Repo:** legacy internal checkout (pre-port measurement)
**SEP OSS DV:** `hw/sys/sep/dv/`
**Scope:** Measure the cost/benefit of the SEP OSS DV Verilator build-model family
(scoped-public `.vlt`, CPU-stub, external-master gating) and recommend a build-resource
and regression strategy. Nothing was rebuilt, re-simulated, or edited for this report —
numbers are taken verbatim from the benchmark dataset and the structural analysis.

---

## 1. Executive summary

- **The scoped-public `.vlt` was the real fix.** Constraining cocotb's forced
  `--public-flat-rw` to only `sep_uvm_top` (commits `6f79c800d` / `69f8ab5f9`) is what made
  the model buildable and fast (the ICO/SCC collapse). Everything in this study sits *on top*
  of that fix; none of the build-model variants re-create the ICO blow-up.
- **The CPU stub buys ~1.66x no_cpu SIM throughput, not build time.** `lsu_stub` runs the
  identical no_cpu workload at **26.08 ns/s vs 15.55 ns/s** (smoke) and **26.21 vs 15.80 ns/s**
  (`sep_address_map`, 466 s vs 773 s for the same 12,216 ns) — a consistent **~1.66–1.7x** win.
- **The build win from the stub is modest.** ~12% fewer translation units (562 vs 595) and
  ~12% less generated C++ (253 vs 289 MB); `hdl_compile` elapsed (240–295 s) is **not clearly
  faster** for the stub — within run-to-run noise. The build-time benefit alone would *not*
  justify the stub.
- **External-master gating gives ~no measurable speed benefit.** `baseline_all_live`
  (~415 s build / 15.34 ns/s sim) vs `default` (~393 s / 15.55 ns/s) differ negligibly on both
  axes. The scoped `.vlt` already subsumed what the ext-master gating was meant to recover.
- **The live-master targets exist for FUNCTIONAL reasons, not speed.** `lsu_ext_smn_stub`
  (tests #20 inbound-filter) and `cpu_jtag_axil` (test #17 JTAG eFuse-mux) need the live
  `smn_inbound` / `axil_sep_otp_jtag` ports — keep them because the tests require the ports,
  not for any build/sim gain.
- **The regression multi-target prebuild is currently BROKEN.** Under `all --regress`, the
  four SEP targets share one `build_dir` with no per-target `filelist`, so the per-target flist
  loop is last-writer-wins and `lsu_stub` gets compiled as **full VeeR** (the stub file is never
  in the on-disk filelist). The fast model never actually runs in `--regress` today. **This must
  be fixed before the stub strategy pays off in regression.**
- **Parity is not yet validated.** Only `sep_axi_smoke` has passed on the stub; the broad
  no_cpu sweep (address_map / decode_error / efuse / sram / km / otbn / crypto) on `lsu_stub`
  vs full CPU has not run.
- **Verdict (Step 9):** keep the CPU stub for the ~1.66x no_cpu sim speedup across the ~23 no_cpu
  tests — **conditional** on fixing the regression bug AND validating parity. If parity proves
  shaky, fall back to full CPU for the affected tests.

---

## 2. Background / optimization journey

The build-model family is the tail of a multi-step Verilator bring-up effort. Relevant commit
context (`git log` on `hw/sys/sep/dv/`):

1. **External-master cones added (2026-06-24, `9d9080acf` "add TOP-16..20 testcases").**
   To support tests #17 and #20, two DUT external master ports were brought out to the tb_top
   boundary: `smn_inbound` (flat `m_axi_*`) and `axil_sep_otp_jtag` (`j_axi`). Driving real
   masters into the *inbound* side of the SEP AXI xbar lit up otherwise-dark slave-port
   arbitration cones in the fabric → observed slowdown.
2. **Scoped-public `.vlt` — the ICO fix (`6f79c800d`, refined in `69f8ab5f9`).** cocotb's runner
   hardcodes a global `--public-flat-rw`, which disabled the AXI `split_var` pragmas and exploded
   the combinational settle (ICO) region (SCCs 951→61, ICO 3.2M→160K per prior root-cause work).
   The fix scopes the public exposure to only `sep_uvm_top` via
   `sep_public_scope.vlt` + a runlib `cocotb_public_scope()` monkeypatch
   (`sep_sim_cfg.toml:110` `public_scope = ".../sep_public_scope.vlt"`; comment at
   `sep_sim_cfg.toml:143-144`). **This is the optimization that actually mattered.**
3. **Four-target split (`db2186977` "fold DFT/ext-master cones + split live targets + -j32").**
   The config defines `default` / `lsu_stub` / `lsu_ext_smn_stub` / `cpu_jtag_axil`
   (`sep_sim_cfg.toml:95`), each compiling a minimal cone set: the ext-master ports are gated
   OFF (`'0`, constant-folded) unless a target sets `SEP_SMN_INBOUND_AXI_LIVE` /
   `SEP_JTAG_AXIL_LIVE`.
4. **CPU-stub shim.** `shims/cpu/sep_cpu_stub.sv` (264 lines) is a DV-only compile-time stub of
   `sep_cpu` wrapped in `` `ifdef SEP_CPU_STUB ``. It removes `el2_veer_wrapper`, the IFU demux,
   the debug/DMI logic, and the LSU/IFU/DBG alias-remappers, but **reproduces the LSU AXI
   ROM/xbar demux + response mux verbatim** so the no_cpu force/probe hierarchy
   (`u_dut.sep_cpu.lsu_axi_req`/`lsu_axi_resp`) is byte-identical. **No RTL edits** — selection is
   purely via the per-target `defines = ["SYNTHESIS", "SEP_CPU_STUB"]` plus per-target
   `exclude_files` (the real `sep_cpu.sv`) + `sources` (the stub) merged by the runlib
   `targeted_sim_cfg` (`config.py:507-526`). The `baseline_all_live` target
   (`sep_sim_cfg.toml:226-232`) is the "everything on" pre-optimization reference (full VeeR +
   both ext masters live); no test is assigned to it.

---

## 3. Benchmark methodology

- **5 models** benchmarked: `baseline_all_live`, `default` (cpu_fw), `cpu_jtag_axil`,
  `lsu_stub`, `lsu_ext_smn_stub`.
- **Cold, fresh per-build ccache.** Each build exported a private `CCACHE_DIR=/tmp/ccb_<target>`
  and `rm -rf`'d it first, so each model's wall-clock is its *intrinsic* cold cost, not masked by
  the warm shared `~/.ccache`. All 5 builds confirmed `rebuild=True` (true cold rebuild).
- **Uniform build+sim probe:** `sep_axi_smoke_test` (no_cpu), run `--stage flist,hdl_compile,sim`
  on every target. The same no_cpu smoke (CPU-LSU force splice) runs on every model, giving a
  comparable build+sim datapoint per model. A second, longer no_cpu probe (`sep_address_map_test`)
  was run on `default` vs `lsu_stub` for a sim-rate measurement on a non-trivial test.
- **el2-count verification:** counted EL2 source files compiled into each model; expected 0 for
  the CPU-stub models (VeeR removed) and 4 for the full-CPU models. All as expected, no anomalies.
- **ccache caveat:** `[build.verilator] ccache = true` (`sep_sim_cfg.toml:103`). With a *warm*
  ccache the g++ stage is near-free and an incremental rebuild hides almost the entire build
  delta; this benchmark uses fresh per-build (cold) ccache, so its build deltas reflect the
  **cold / CI upper bound**. `TU_count` and `total_cpp_MB` are ccache-independent (pure codegen
  workload).

---

## 4. Results

### 4.1 Full 5-model table

| model | defines summary | build_wall_cold (s) | hdl_compile (s) | TU_count | total_cpp_MB | binary_MB | el2_files | smoke ns/s | PASS? |
|-------|-----------------|--------------------:|----------------:|---------:|-------------:|----------:|----------:|-----------:|:-----:|
| baseline_all_live | SYNTHESIS + SMN_INBOUND_LIVE + JTAG_AXIL_LIVE (full VeeR + both ext masters) | 415 | 294.7 | 595 | 290 | 24 | 4 | 15.34 | PASS |
| default (cpu_fw)  | SYNTHESIS (full VeeR, ext masters idle) | 393 | 274.8 | 595 | 289 | 24 | 4 | 15.55 | PASS |
| cpu_jtag_axil     | SYNTHESIS + JTAG_AXIL_LIVE (full VeeR + JTAG master) | 383 | 264.1 | 595 | 289 | 24 | 4 | 15.39 | PASS |
| lsu_stub          | SYNTHESIS + SEP_CPU_STUB (no VeeR, ext masters idle) | 356 | 282.2 | 562 | 253 | 20 | 0 | 26.08 | PASS |
| lsu_ext_smn_stub  | SYNTHESIS + SEP_CPU_STUB + SMN_INBOUND_LIVE (no VeeR + SMN master) | 315 | 239.8 | 563 | 253 | 20 | 0 | 26.01 | PASS |

All 5 models built cold to completion and the no_cpu smoke **PASSED on every one**. `el2_files`
verified: 0 on both CPU-stub models, 4 on the three full-CPU models — no anomalies.

### 4.2 Longer no_cpu sim comparison (`sep_address_map_test`, default vs lsu_stub)

| model | sim_time (ns) | real (s) | sim ns/s | PASS? |
|-------|--------------:|---------:|---------:|:-----:|
| default (full VeeR) | 12216 | 773.0 | 15.80 | PASS |
| lsu_stub (CPU stub) | 12216 | 466.2 | 26.21 | PASS |

Identical 12,216 ns of simulated time; **466 s vs 773 s** wall → **26.21 / 15.80 = ~1.66x**.
This matches the smoke ratio (~26 vs ~15.5 ns/s) — a consistent ~1.7x sim-rate win from removing
the VeeR EL2 core from the evaluated netlist. **This is the real win.**

### 4.3 Build wall-clock per model (call-out)

Cold `hdl_compile` elapsed (the apples-to-apples compile time): **240–295 s** across all five
models. The stub models (`lsu_stub` 282.2 s, `lsu_ext_smn_stub` 239.8 s) are **not clearly faster
than the full-CPU models** (`default` 274.8 s, `cpu_jtag_axil` 264.1 s, `baseline_all_live`
294.7 s) — the spread is within run-to-run noise and does not track the stub. The only
ccache-independent build signal that does move is codegen volume: **562 vs 595 TUs (~12% fewer)**
and **253 vs 289 MB C++ (~12% less)** for the stub. Conclusion: **build wall-clock is essentially
flat across the family**; the stub's benefit is a sim-time benefit.

---

## 5. Analysis — why sim-delta ≫ build-delta

From the structural analysis of the compiled file set
(`hw/sys/sep/dv/build/sep_bender.f`, 840 sources / 279,930 lines for the full-CPU target):

- **VeeR EL2 is only ~10.2% of compiled RTL lines** (51 files / 28,603 lines in-flist; the
  on-disk vendor tree is larger, 219 files / 62,503 lines, but SEP pulls one elaborated config).
- **The giant `Vtop___024root__*.cpp` eval TUs are dominated by the AXI fabric + crypto + i3c
  cones, not VeeR.** i3c-core is the single largest dep (13.0%); AXI fabric is 9.2%
  (rr_arb_tree / lzc / axi_demux / axi_xbar — wide combinational priority/one-hot cones); crypto
  (aes/kmac/hmac/otbn/sha) is ~18% combined. **All of these remain in every model** — the stub
  removes none of them, and even reproduces the LSU demux.
- VeeR is a *pipelined* core: mostly flops, modest combinational fan-in per TU. So removing it:
  - **drops** VeeR's eval code + ICCM/DCCM (≈ the 10% line share) → the modest ~12% TU/C++ cut and
    the flat-to-slightly-lower build time we observed; but
  - **leaves untouched** the fabric/crypto giant-cone TUs that actually gate compile time → no
    clear build speedup.
  - At sim time, however, removing the whole VeeR pipeline eliminates per-cycle eval ops for the
    core + its TCM (and, for no_cpu tests, all CPU clocking activity), so **per-cycle eval cost
    drops more than static compile cost** → the ~1.66x sim win.
- **External-master gating is subsumed by the scoped `.vlt`.** The ext-master cones it folds away
  (constant-`'0` inbound request → Verilator constant-folds the xbar slave-port cone,
  `tb_top.sv:459-463` / `390-394` / `669`) were the same fabric cones the scoped-public `.vlt`
  already kept out of the public/ICO region. Hence `baseline_all_live` vs `default` shows
  negligible build/sim difference — the gating provides no *additional* measurable speedup.

---

## 6. Build-resource decision (recommendation)

**Observation:** build wall-clock is gated on a handful of giant cone TUs (fabric/crypto/i3c),
not on parallelizable breadth, and the build host has **32 cores + ~314 GB free RAM**. RAM is not
the constraint at these model sizes (binaries 20–24 MB; generated C++ 253–290 MB).

**Recommendations:**

1. **Single model:** build with `--jobs 32`. The giant TUs compile in parallel up to the
   available cores; there is no RAM pressure at 32-way for one model.
2. **Multiple models (e.g. the regression prebuild):** build them **in parallel** with a *total*
   job budget ≤ 32 — e.g. **4 models × `--jobs 8`**, or **5 models × `--jobs 6`**. Parallel build
   finishes all N models in roughly **one model's wall-time** (~5–6 min cold) instead of
   **N× sequential** (~25–30 min for 5), and RAM is not the limiter.
3. **Do NOT oversubscribe beyond 32 total jobs** (across all concurrent model builds). Past the
   core count you only add scheduling/cache thrash, not throughput.

**Prerequisites:** this only helps regression once (a) the regression prebuild is made parallel
(§8b) and (b) the per-target filelist-collision bug is fixed (§7) — otherwise the parallel
prebuild just builds the wrong (full-VeeR) model faster.

---

## 7. Known bug: regression multi-target prebuild (HIGH priority)

**Symptom:** under `all --regress`, the prebuild compiles `lsu_stub` as **full VeeR** — the
`SEP_CPU_STUB` shim is never reached, so the fast stub model never actually runs in regression.

**Root cause** (traced through `cli.py` + `config.py` + `stages.py`):

1. `all --regress` with multiple targets sets `multi_target = len(build_targets) > 1`
   (`cli.py:775`).
2. `targeted_sim_cfg(sim_cfg, t, force_target_filelist=True)` is called per target
   (`cli.py:777-779`). This **correctly** merges each target's `defines` (incl. `SEP_CPU_STUB`),
   `exclude_files` (`hw/sep/sep_cpu.sv`), and `sources` (the stub) into that target's cloned
   `[build]` (`config.py:507-526`). The *config object* is per-target-correct.
3. **The collision:** under `force_target_filelist`, the generated filelist paths are derived from
   `build_dir / "filelists"` (`config.py:537-549`) — but **all four SEP targets share the same
   `build_dir = ".../build/cocotb"`** (`sep_sim_cfg.toml:166,189,203,216`) and none set their own
   `filelist`/`bender_filelist`. So every target derives the **identical**
   `.../build/cocotb/filelists/{bender.f,files.f}`.
4. The flist/`hdl_compile` stages loop over `build_targets` (`cli.py:890-906`); the flist stage
   **writes** the bender filelist and applies `exclude_files` to it (`stages.py:599,640-657`) —
   each target **overwrites the same shared file**. Last-writer-wins: if `default` (no exclude, no
   stub) runs flist last, the on-disk filelist contains the **real** `sep_cpu.sv` and **lacks**
   the stub.
5. The parallel-sim prebuild (`cli.py:937-957`) passes the correct `target_cfgs[target]`, but
   `_cocotb_build_info` reads the **filelist file from disk** (`stages.py:972,1011`) and passes
   `-f <that file>` to the build (`stages.py:765-766`). So the build gets the correct
   `+define+SEP_CPU_STUB` (`stages.py:755`) **but a filelist that still contains the real
   `sep_cpu.sv` and omits the stub** → `` `ifdef SEP_CPU_STUB `` is never hit → full VeeR compiles.

(The build *fingerprint* does differ per target — it hashes target name + target_cfg JSON incl.
defines, `stages.py:112-116,1015-1027` — so the compiled models land in distinct
`base_build/<fingerprint>` dirs and don't clobber each other. The bug is purely the **shared
on-disk filelist** they all point at, which is wrong for all-but-the-last target. The fingerprint
also folds in `filelist_text`, so the stale shared filelist even poisons the cache key.)

Single-test runs are immune because `multi_target=False` keeps
`[build].bender_filelist = .../build/sep_bender.f` verbatim and exactly one target's flist runs —
which is why only the single-test stub was ever validated.

**Fix (pick one):**
- (i) key the derived filelist path on **target name** (not just `build_dir`) so the flist loop
  writes four distinct files (`config.py:537-549`); or
- (ii) give each target a distinct `filelist`/`bender_filelist` key (or a per-target `build_dir`
  subpath) in `sep_sim_cfg.toml` so the four flists never collide.

---

## 8. Open items / next actions (prioritized)

a. **Fix the regression multi-target filelist-collision bug** (§7). HIGH — gates the entire fast-
   model strategy in `all --regress`. Without this, `lsu_stub` regression runs are silently full
   VeeR.
b. **Parallelize the regression prebuild** with a total job budget ≤ 32 (§6) — e.g. 4×`--jobs 8`.
   Sequential prebuild of all targets is the avoidable wall-time cost; parallel finishes in ~one
   model's time.
c. **Run the no_cpu parity sweep on `lsu_stub` vs full CPU**: address_map / decode_error / efuse /
   sram / km / otbn / crypto. Only `sep_axi_smoke` is proven on the stub today. The stub ties
   VeeR-side trace/ECC-error/perfcnt/dbg/IFU master nets to `'0` (stub lines ~209-260); any test
   that (even indirectly) depends on one of those could diverge. **Parity is the gating proof for
   keeping the stub.**
d. **Stand up the cpu-fw firmware / `c_compile` path** so the cpu smokes (hello_world, jtag)
   validate end-to-end through the new target machinery. Today a standalone `--stage sim` for a
   cpu test hits a `c_compile` ConfigError: the SEP cfg declares
   `[native.stages.c_compile] kind="c_compile"` (`native-cocotb.toml:78-79`) but there is **no
   `[c_build.<mode>]` template** in `sep_sim_cfg.toml` or the profile, and `c_compile_stage` raises
   `ConfigError` when `[c_build]` is absent (`stages.py:812-816`). Firmware is currently built by
   the separate `cgen`/Makefile flow, not the runlib c_compile stage.
e. **Fix the `sep_cpu_stub.sv` header comment.** The header should describe selection via the
   per-target `defines` + `exclude_files`/`sources` mechanism (the current scheme); confirm it no
   longer references the old `[build].stubs` mechanism anywhere in the file.
f. **Remove the benchmark-only `baseline_all_live` target** (`sep_sim_cfg.toml:226-232`) after this
   study — it has no test assigned and exists only as the pre-optimization reference.

---

## 9. Recommendation (Step-9 verdict)

**Keep the CPU stub.** The ~1.66x no_cpu sim speedup (26 vs 15.5 ns/s) across the **~23 no_cpu
tests** is a meaningful answer to the per-test timeout problem (Verilator ~370 ns/s ceiling, 1800 s
gate), where the firmware/loop-sizing workarounds otherwise dominate. This is the only first-order
win in the study.

**Conditions (both required):**
1. **Fix the regression multi-target filelist-collision bug** (§7) — otherwise `all --regress`
   silently runs the slow full-VeeR model and the speedup never materializes in regression.
2. **Validate no_cpu parity** on `lsu_stub` vs full CPU across the sweep in §8c — the byte-
   identical LSU-demux claim is sound but unproven beyond `sep_axi_smoke`.

**Keep the live-master targets** (`lsu_ext_smn_stub`, `cpu_jtag_axil`) on **functional** grounds —
tests #20 and #17 require the live `smn_inbound` / `axil_sep_otp_jtag` ports. They cost nothing
extra (ext-master gating gives ~no measurable speed difference), so this is purely about test
coverage, not performance.

**Do not justify the stub on build time** — build wall-clock is essentially flat across the family
(§4.3); the scoped `.vlt` already captured the real build/ICO win.

**Fallback:** if parity proves shaky for any test, run that test on the full-CPU `default` model
(it already passes there) rather than weakening the stub.
