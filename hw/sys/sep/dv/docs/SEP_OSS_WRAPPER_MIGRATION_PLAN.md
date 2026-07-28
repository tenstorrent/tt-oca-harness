<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS DV — Migrate DUT to `sep_wrapper`, retire TB responders

**Status: LANDED ON THE PR BRANCH (v8). All phases 0-5 complete; the DV migration
was fast-forwarded onto `3589-create-sep_ip_integration-module` (PR #3717, dkimTT)
and pushed — the branch is now ahead of `main` + our DV update.** Started
2026-07-17; landed 2026-07-18/19. Per user direction the throwaway integration
branch became the real deliverable: current `origin/main` was merged in first
(conflict-free), then the migration + our DV commits fast-forwarded 3589, then
`copilot-swe-agent` added the TRNG-stub handshake fix `94b3e305f` on top (reviewed
+ agreed). Governance sign-off DONE; cycode findings waived as false positives.
Remaining OUR-side quality items (below) + designer flags for dkimTT (SPDX headers,
rdl whitespace, AXI-extension ACK).

PROGRESS LOG (newest first):
- **2026-07-19 Landed on PR #3717 + post-land follow-ups.** FF'd `3589` onto our merge
  tip and pushed (`9fd2bd912..db473464d`); then: (a) cycode findings on the PR waived as
  false positives (seeded `random.Random(seed)` = required DV reproducibility, and
  `0x1badf00d` = placeholder seed not a credential) — in-thread replies + AGENTS.md §5
  rule; (b) `copilot-swe-agent` pushed `94b3e305f` (TRNG AXI-Lite stub handshake fix in
  `sep_ip_integration.sv`) — reviewed + agreed (original dropped B/R responses on
  non-aligned AW/W; new FSM holds until acknowledged), FF'd our local onto it; (c) fixed
  the `+sep_efuse_preload[=path]` prestage gap — `dv_sim_prestage.stage()` now parses the
  plusarg and honors it at t=0 exactly as `select_efuse_image` does at runtime (custom
  path / bare→default / absent→registry), runlib passes rendered `sim_args` to the hook
  (backward-compatible via signature inspection); 7/7 directed checks pass. NOTE the
  Copilot TRNG-stub change is wrapper RTL → it INVALIDATES the model cache, so the
  four-tool gate must re-build+re-run on this tip (not a cached sim-only run). Re-running
  Verilator + VCS on the clean committed head next.
- **2026-07-18 All four DV audit follow-ups DONE + green; no regressions.** Order
  4→1→2→3 (commits `c07edfb9b` P1 seed render, `c358bb3b1` image_test OCAH-parity
  checkers, `7efad8999` DMA-TX chunk_done RW1C + flash-cmd single-config). Post-items
  full **Verilator regression GREEN: no_cpu 47/47 + cpu 22/22, 0 fail/error** — the
  batch (incl. the shared-runlib P1 render) regressed nothing. **VCS reconfirm also
  GREEN: no_cpu 47/47 + cpu 22/22, 0 fail/error** — and P1 is proven on VCS too
  (`seed=0x0318c001 (plusarg)`, the per-leaf regression seed rendered through). => all
  four DV items are green on BOTH tools; the post-items four-tool matrix is clean.
  GOVERNANCE: the tb_backdoor_mem backdoor exception is ✅ SIGNED OFF 2026-07-18 by
  yenhenglai (SEP TB owner) via an explicit AskUserQuestion confirmation — recorded in
  AGENTS.md §11. (An earlier "Approve as-is" prompt landed in a rejected/clarify
  response and was correctly NOT treated as approval; this sign-off is the real one.)
- **2026-07-18 CLEAN-HEAD FOUR-TOOL GATE CLOSED — retained evidence, dirty=false.**
  All four regressions re-run on the committed retire HEAD `1ca5748c3` with a clean
  tree (result.json `git.dirty=false`, `exit_code=0` on all four):
  Verilator cpu 22/22 (`20260718_134540__verilator__cpu`), Verilator no_cpu 47/47
  (`20260718_134747__verilator__no_cpu`), VCS no_cpu 47/47
  (`20260718_135510__vcs__no_cpu`), VCS cpu 22/22 (`20260718_140757__vcs__cpu`) —
  zero fails/errors. NOTE: the FIRST VCS attempt this round hit 7 `VFS_SDB` errors
  (`simv.daidir/prof.sdb` in-use/IO race) purely from running the Verilator no_cpu
  BUILD concurrently with the 8 parallel VCS sim jobs (I/O contention); re-running
  VCS ALONE was clean 0/0. Lesson: do not run a Verilator build concurrently with a
  VCS sim regression (shared build-tree I/O). => the migration's integration bar is met.
- **2026-07-18 Phase 5 FULL RETIRE committed + eFuse model fix committed (clean HEAD).**
  Two commits on the branch: `e090ae0b1` = the designer efuse-model fix
  (`efuse_interface_shim.sv` clear `write_readback_phase_en` in `StWriteFinish` —
  MUST also land in #3717/dkimTT; committed here so HEAD is coherent, the efuse
  regression deadlocks without it); `1ca5748c3` = Phase 5 retire — `SEP_USE_WRAPPER`
  removed entirely (macros `SEP_CORE`/`SEP_IPI` unconditional), bare-sep instantiation
  + all `ifndef SEP_USE_WRAPPER` blocks deleted, dead `efuse_prog_fail_seed_i` port
  removed, 6 responder files deleted + their toml `[build].sources` entries, defines
  cleaned on both targets; kept `sep_outbound_mbx` + accepted shims. Verilator cpu
  smoke (`sep_hello_world_test`) PASS after the retire. Working tree clean (only
  untracked docs). **Re-running all four regressions on this clean committed HEAD**
  (dirty=false) for retained evidence. See AUDIT FOLLOW-UPS below for the 2026-07-18
  review triage.
- **2026-07-18 FINAL INTEGRATION GATE MET — all four regressions GREEN on the wrapper.**
  VCS cpu regression **22/22 PASS (exit 0)** on the `default` full-CPU target (fresh
  fingerprint `vcs/default/259e545eb8f6`, hdl_compile 120s); `sep_boot_rom_smoke_test`
  PASS index 1/22, non-vacuous (`boot-ROM PCs seen: ['0x1004000c']`). Full matrix:
  **Verilator no_cpu 47/47, Verilator cpu 22/22, VCS no_cpu 47/47, VCS cpu 22/22** —
  all four green, zero fails. `check_no_vendor_paths.py` PASS on BOTH generated
  filelists (`default/files.f` + `lsu_stub_all_live/files.f`). This is the user's
  "integration success" bar. REMAINING: Phase 5 full retire (remove `SEP_USE_WRAPPER`,
  delete the 6 responder files + dead wires) — a hard-to-reverse step, HOLD for user
  go-ahead — then final docs; and the designer efuse-model fix
  (`efuse_interface_shim.sv` `write_readback_phase_en` clear) must land in #3717.
- **2026-07-18 VCS no_cpu regression 47/47 PASS (exit 0) on the wrapper.** First real
  VCS *sim* run of the wrapper (P2 clean rebuild: `rm -rf build/cocotb/vcs` after the
  tb_top edit; `.venv-vcs` cocotb 1.9.2). `hdl_compile` PASS 147s on the
  **`lsu_stub_all_live`** target, then 47/47 sims PASS, 0 FAIL — including the slow KM
  sideload KATs (`sep_km_aes/hmac_sideload_kat` ~650s/226s), DRBG multisink, crypto EDN,
  fabric decode-err, wdt, irq aggregator. **RESOLVES the plan's VCS caveat:** the VCS
  flow DOES build + RUN the CPU-stub target for no_cpu (not compile-only on default as
  the earlier VCS runs were). => VCS no_cpu matches Verilator no_cpu. cpu VCS regression
  running now (default full-CPU target, fresh fingerprint). Then: all four green => Phase 5.
- **2026-07-18 `sep_boot_rom_smoke_test` FIXED — the last Verilator fail is green.**
  ROOT CAUSE (not RTL, not IFU): the test boots the CPU to EXECUTE from the boot ROM
  but passes NO `+sep_boot_rom_hex` plusarg — under bare-sep the retired
  `tb_boot_rom_responder` had a CWD FALLBACK (`$readmemh("sep_boot_rom.hex")` when the
  plusarg was absent, lines 37-43), and the committed `cocotb/tests/sep_boot_rom.hex`
  (a 4-instr program: `addi/addi/addi/jal x0,0` looping at base+12=`0x1004000c`) is
  staged into the sim CWD. The wrapper `tb_backdoor_mem::backdoor_image_loads` block
  only honored the plusarg (no fallback), so the boot ROM stayed zero-filled → CPU
  fetched `0x00000000` (illegal) → stalled at PC 0x0 (`trace_valid=0`). The other 3
  retired responders had the SAME CWD fallbacks (`sep_sram.hex`, `km_rom.parhex`), so
  the wrapper backdoor was missing all three — a Phase-5 full-retire hazard, not just
  this test. **FIX: restored all three CWD fallbacks in `backdoor_image_loads`
  (plusarg first, else `$fopen`-guarded `$readmemh` of the default filename; absent
  file leaves the default fill intact) — exact behavioral parity with the responders.**
  **VERIFIED: `sep_boot_rom_smoke_test` PASS on Verilator** (rst_vec 0x8020000 →
  boot PC 0x10040000, `boot-ROM PCs seen: ['0x1004000c']`, matches baseline). Full
  cpu Verilator regression re-run **22/22 PASS, exit 0** (was 21/22, sole fail was
  boot_rom_smoke; zero regression on the other 21) — commit `d3ddb8a42`.
  **=> VERILATOR NOW FULLY GREEN: no_cpu 47/47 + cpu 22/22.** REMAINING gate: the VCS
  no_cpu + cpu regressions (the final all-four-green bar), then Phase 5 full retire + docs.
- **2026-07-18 Verilator: no_cpu 47/47 + cpu 21/22 = 68/69 GREEN on the wrapper.**
  After the reset-vector fix + SPI-fw CS clear: cpu regression 21/22 PASS (was 0/22) —
  all boot/DMA/KM/efuse/crypto/SPI-flash cpu tests pass. ONE remaining fail:
  `sep_boot_rom_smoke_test` — the only test that boots the CPU to EXECUTE directly
  from the boot ROM (reset vector = boot-ROM base 0x10040000, no TCM firmware). Reset
  vector programs correctly (TDR←0x10040000) and the boot ROM is loaded (lsu_read reads
  it fine) + rom_sanity_rom.hex is staged/valid, but the CPU stalls at reset
  (`trace_valid=0`, PC never reaches 0x10040000, only 0x0 seen). => isolated to the
  IFU-fetch-from-boot-ROM path under the wrapper (prim_rom + sep_rom_interface_shim)
  vs the old tb_boot_rom_responder — needs waveform/probe-level debug (IFU fetch req to
  the boot ROM, or a reset-vector latch-timing edge specific to the no-TCM boot). Niche
  case; 68/69 otherwise green. cpu-fw SPI tests (dma_rx/tx/flash_cmd) PASS with the fw
  cs_force_high clear. REMAINING before all-green: this one test, then VCS regressions
  (both tools gate), then the full retire.
- **2026-07-18 Phase 5 cpu regression 0/22 — root-caused to reset-vector-TDR timing;
  fix in flight.** First cpu regression on the full-CPU wrapper: ALL 22 fail identically
  — PC stuck at 0x0, `iccm_act=0`, `run_ack_seen=True` ("core never booted out of ICCM").
  Root cause: the reset vector was never programmed during the boot window — `tb_top`'s
  `init_reset_vector_tdr` used a bare level `wait((rst_ni===0) && !$isunknown(rst_vec_i))`,
  and a cocotb/VPI-driven `rst_vec_i` update does not reliably re-trigger a `wait` under
  Verilator, so `program_reset_vector_tdr` fired only at sim-end with `rst_vec_i=0`
  ("Reset-vector TDR programmed to 0x00000000" after the FAIL). CPU used the default
  vector 0 → never reached ICCM. NOT a wrapper-RTL bug — a fragile tb one-shot the
  wrapper's boot timing exposed. FIX: poll on `@(posedge clk_i)` and program once when
  reset is asserted and `rst_vec_i` is known non-zero (clocks start while rst_ni is still
  low, so the window is always seen; bit math unchanged — RSTVEC = PC[31:1] = rst_vec_i,
  boot PC = {rst_vec_i,1'b0}). **FIX CONFIRMED: `sep_hello_world_test` PASS on Verilator**
  — TDR←0xc0000000, iccm_act=1, 49 distinct PCs, `'Hello from SEP OSS firmware!'`,
  fw_done/fw_pass. Commit for the fix pending; full cpu regression running (model cached
  now, so far faster than the 107-min cold+all-failing first run).
- **2026-07-18 no_cpu regression FULLY GREEN (47/47, pass_rate 1.0) on the wrapper.**
  Phases 0-4 done for no_cpu: wrapper DUT + tb_backdoor_mem + D2 efuse pre-hook + efuse
  model fix + P3 image_test (10-bit W1S) + Phase-4 SPI CS_FORCE_HIGH clear. 0 failing,
  0 regressions. Commits: `36dabe576` (Phase 4 jedec + shared spi_mux_release_cs).
  NEXT: Phase 5 cpu regression — cpu-fw SPI flash tests (dma_rx/tx/flash_cmd) need the
  same CS clear in firmware (added `sep_spi.h::sep_spi_mux_release_cs()`; dma_rx done,
  dma_tx+flash_cmd pending); boot/TCM tests validate the tb_backdoor_mem TCM load path.
- **2026-07-18 Phase 3 COMPLETE + Phase 4 (jedec) done; no_cpu 48/48 expected.**
  no_cpu regression after the efuse model fix + P3 = **47/48** (both efuse tests PASS
  under random regression seeds — D2 pre-hook seed plumbing works under `--regress`;
  zero regressions). Per user, strengthened `sep_efuse_image_test` to burn **10 random
  CHIPLET_UID bits** (real W1S, seeded) — PASS (scoreboard 554 checks/514 value-verified;
  `CHK-W1S-PERSIST PASS`), commit `22b685657`. **Phase 4:** the last no_cpu fail
  `sep_spi_flash_jedec_smoke_test` — root cause `SPI_MUX_CTRL.cs_force_high` resets 1
  (extension aperture `0x2000_0000`, routed to the real mux CSR under the wrapper; bare
  sep tied it off so the OCAH write was a no-op). Added shared
  `sep_base_test.spi_mux_release_cs()` (AXI `0x2000_0000<-0`) + called it in the jedec
  smoke → PASS (JEDEC read `0x0018ba20`, was `0x00ffffff`). Re-running full no_cpu (expect
  48/48). NEXT: Phase 5 = cpu regression (cpu-fw SPI flash tests dma_rx/tx/flash_cmd need
  the same CS clear in firmware; boot tests) → then remove `ifdef` + retire responders + docs.
- **2026-07-18 Phase 3 — MODEL BUG found + fixed (efuse program re-arm); image_test P3 PASS.**
  `sep_efuse_image_test` refactored to program-then-resense (commit `834edc475`... see
  below) → **PASS** (first sense 0 err → OTP bit[1600] W1S → resense 0 err). Then
  `sep_efuse_lcc_lc_state_stitch_test` exposed a **real RTL liveness bug in the generic
  efuse model** (`hw/.bos/models/efuse/efuse_interface_shim.sv`, designer/#3717):
  a `PROGRAM_READ_BACK` sets `write_readback_phase_en` in `StWriteWait` but NO state
  clears it on the way back to idle (`StWriteFinish`/`StWriteIdle` don't), so it stayed
  latched at 1. The req demux (line 494) then mis-routed the NEXT program's WRITE to the
  readback (read) path → `apb_fuse_bank_resp_w.pready` never asserts → `StWriteWait`
  hangs → no DONE on ANY second program-with-readback. (User confirmed: SEP RTL is good —
  works with Samsung + old responder — so it's the model.) Single-program tests
  (image_test) masked it; lcc's injection-retry (2nd program of a bit) tripped it, and it
  would also bite any multi-bit program walk. **FIX (local, on our throwaway branch):
  clear `write_readback_phase_en = 1'b0` in `StWriteFinish`.** This is a designer-model
  fix → must land in #3717 (flag to dkimTT); NOT a DV-only change. Verifying on Verilator.
- **2026-07-18 Phase 3 (D2) DONE + verified; P3 test refactor remains.** Implemented
  the D2 pre-sim efuse image hook (commit `834edc475`): generic per-DUT hook —
  `stages.py._run_sim_prestage` calls `<python_root>/dv_sim_prestage.py`
  `stage(item,seed,cwd)` after mem-image staging, before sim launch (no-op for DUTs
  without it → smc/dtp unaffected; SHARED-RUNLIB edit → owner sign-off, AGENTS.md §12).
  SEP `cocotb/dv_sim_prestage.py` = pure-Python registry (imports SepEfuseImage by
  FILE PATH to dodge env/__init__→pyuvm) reproducing each test's
  `select_efuse_image(seed)` bit-exactly. VERIFIED standalone (staged==golden for
  image/lcc_stitch/km_kat; unregistered=no-op) AND end-to-end: `sep_efuse_image_test`
  **first sense now 0 errors** (was 115 mismatches). REMAINING for the 2 efuse fails:
  (a) `sep_efuse_image_test` P3 — it still does a mid-run `write_efuse_image(img2)` +
  resense expecting a DIFFERENT image (lines 30/45), which the t=0-load model can't
  honor; refactor to program-then-resense (sense img1 → frontdoor OTP W1S a known-0
  bit → resense → check img1+bit). Reuse the OTP-program sequence in
  `sep_efuse_lcc_lc_state_stitch_test.py:170-190` (EFUSE_PROGRAM_CTRL write→poll→clear)
  by extracting a shared `sep_base_test` helper (AGENTS.md §5). (b) `lcc_stitch` —
  "OTP program bit 64 did not complete" with model prog-fail injection active
  (count=1 percent=30); sort the fail-injection wiring (P1 seed render) + retries.
- **2026-07-18 Strategy settled + D2 impl mapped.** User direction: end state = "make
  3717 AHEAD of main + our DV update eventually — don't break anything." Our local
  `sep-oss-wrapper-migration` branch (main + #3717 merged + DV work) IS that shape;
  keep it (no branch change). We are NOT authoring #3717 (designer dkimTT RTL PR); our
  DV migration is a separate deliverable that CONSUMES #3717's wrapper. HARD GATE:
  full `no_cpu`+`cpu` regression must stay green vs the bare-sep baseline (no regression).
  D2 approach chosen = **per-test Python pre-hook** (preserves VPLAN randomization).
  D2 impl map (agent-verified): `SepEfuseImage` @ `cocotb/env/sep_efuse_image.py` is
  PURE-PYTHON importable (`.randomize(seed,lc_raw=,lock_prob=,fixed=)`/`.load`/`.write_hex`
  = 256×`%08x`); seed reaches sim via `RANDOM_SEED` env (stages.py:1660 runner /
  :1341,:1351 VCS), = `sep_base_test.random_seed()`; inject at the per-leaf `*.hex`
  staging block (`cocotb_sim` stages.py:1677-1688 → `<item_dir>/out/sep_efuse.hex`;
  `_cocotb_make_sim` :1525-1536 → `<item_dir>/make/out/sep_efuse.hex`). Only real-fuse
  (no `+skip_fuse_sense`) tests need it — the km KATs etc. skip sense so they already
  pass; the 2 no_cpu fails (image, lcc_stitch) omit skip. Plan: pure-Python registry
  (test→{mode,lc_raw,lock_prob,fixed,preload}) in the OSS DV tree (NOT importing test modules) +
  a SEP-gated call from the two staging blocks (no-op for smc/dtp → zero blast radius;
  post-sense shadow compare is the drift detector). SHARED-RUNLIB EDIT → owner sign-off
  note (AGENTS.md §12).
- **2026-07-18 Phase 2 VALIDATED — no_cpu regression 45/48 PASS on the wrapper.**
  Verilator `no_cpu --regress`: 48 invocations, **45 PASS / 3 FAIL**, and the 3
  failures are EXACTLY the not-yet-done phases (no wrapper integration bug):
  (1) `sep_efuse_image_test` — backdoor shadow check `sensed != expected` (115 words)
  = the D2 t=0-vs-runtime image race → Phase 3; (2) `sep_efuse_lcc_lc_state_stitch_test`
  — `OTP program bit 64 did not complete`, model prog-fail injection active
  (count=1 percent=30) → Phase 3 (D2 + fail-inject wiring); (3)
  `sep_spi_flash_jedec_smoke_test` — JEDEC read 0x00ffffff, "BFM saw no completed
  transactions" = CS_FORCE_HIGH=1 keeps CS deasserted → Phase 4 (P4). Deepest tests
  PASS on the wrapper: KM sideload KATs (otbn/aes/hmac/kmac ~100s each — real KM ROM
  fw load + KM SRAM macro descramble + OTBN + TCM), crypto (aes/hmac/kmac/edn-multisink),
  entropy e2e, fabric/filter/remap, irq aggregator/fanin, wdt, mailbox, sram/rom/otbn
  smokes, sep_efuse_sense, reset-isolation. => Phase 2 (default-fill + image loads)
  is broadly proven. Committed `3eff6ea24` (Phase 1+2 tb_top+config+.vlt). NEXT:
  Phase 3 (D2 efuse pre-stage — the 2 efuse fails) then Phase 4 (P4 CS_FORCE_HIGH —
  the 1 SPI fail).
- **2026-07-18 Phase 2 — tb_backdoor_mem written; VCS compile PASS; Verilator
  smoke building.** Verilator wrapper MODEL build PASS (331s — macros verilate
  clean, no ICO/DFG wedge). Empty-memory wrapper smoke HUNG (exit 124) → confirmed
  default-fill is required. Added `tb_backdoor_mem` inline in `tb_top.sv` (under the
  wrapper `ifdef`): (a) both-tools non-zero default fill for KM ROM
  (`{word_parity(0x13),0x13}`), KM SRAM (`{4'hF,0}`), OTBN imem
  (`prim_secded_pkg::SecdedInv3932ZeroWord`), OTBN dmem (`{8{…}}`) — these are the
  likely wrapper-smoke wedge (0-init has bad KM parity / invalid OTBN SECDED);
  (b) VCS-only zero fill for SEP SRAM/boot ROM/ICCM/DCCM (Verilator 0-inits them;
  a big constant-bound Verilator `initial` sweep unrolls into an uncompilable C++
  fn — guarded `ifndef VERILATOR`); (c) plusarg image loads (sep_boot_rom_hex /
  sep_sram_hex / km_rom_hex); (d) TCM firmware load on `tcm_load_i` (ICCM/DCCM
  de-interleave + Hsiao `riscv_ecc32`, constant bank indices). Added 3
  `sep_public_scope.vlt` lines (prim_ram_1p.mem, prim_rom.mem, ram_16384x39.ram_core)
  so backdoor writes take effect under Verilator. **Spec agent CORRECTED the plan's
  Sub-problem A paths:** TCM generate arms are `gen_iccm_ram`/`gen_dccm_ram` (NOT
  `gen_ram` — that path is a silent no-op); OTBN dmem is 312b (8×39), SEP SRAM/boot
  ROM 64b, KM ROM/SRAM 36b. **VCS `flist,hdl_compile` PASS (112s)** with
  tb_backdoor_mem. NEXT: Verilator functional smoke result → then Phase 3 (efuse).
- **2026-07-18 Phase 1 — wrapper swap + XMR re-root, VCS elaborate PASS.**
  `tb/tb_top.sv` reworked behind `SEP_USE_WRAPPER`: (a) `` `SEP_CORE ``/`` `SEP_IPI ``
  macros; a single `replace_all` re-rooted all 46 `u_dut.sep_*` XMR reads to
  `` `SEP_CORE.sep_* `` (expands to `u_dut` when the wrapper is off, so both flavors
  stay correct). (b) `sep_wrapper #(.EXT_TRNG_NUM_AXIS(2)) u_dut` instantiation
  under `ifdef` (bare `sep` under `else`): SPI pads mapped (clk→sck, txd[0]→MOSI,
  cs_n→CS, rxd[1]←MISO), mem/efuse/spi/ext_trng/lc-status ports dropped (internalized
  / non-ports), no `rst_vec`. (c) bare-sep responders (tcm/sram/bootrom/efuse/km/otbn
  + SPI adapter) guarded `ifndef SEP_USE_WRAPPER`; under the wrapper, dbg_iccm/dccm
  taps from `u_dut.sep_cpu_tcm_req`, KM/OTBN activity counters re-derived from the
  wrapper req nets (km `.req/.we`, otbn `.enable/.write`), `km_sram_word0` peeks the
  real macro array. **VCS `flist,hdl_compile` PASS (115.8s)** on the wrapper build
  (SEP_USE_WRAPPER temporarily on `default` target) — proves the wrapper elaborates,
  the `rst_vec` reconciliation is correct, and every re-rooted XMR path resolves.
  Verilator confirm + functional CSR smoke IN PROGRESS. NEXT: proper wrapper targets
  (`default_wrapper`/`lsu_stub_wrapper`) + Phase 2 `tb_backdoor_mem` (memory content).
- **2026-07-18 Phase 0 — 10 files wired + compile-smoke PASS (VCS).** Added the 10
  SEP-subset files to `[build].sources` in `sep_sim_cfg.toml` (dependency order;
  emitted after the bender filelist per `stages.py` so DUT packages resolve).
  Verified: bender gating — real `hw/sep/sep_{wrapper,ip_integration}.sv` are behind
  `tt_sep_dv_files`/`sep_wrapper` targets (Bender.yml:2245/2570), NOT our
  `["sep","sep_el2"]` set → no MODDUP (confirmed absent from generated filelist).
  `flist` PASS; `check_no_vendor_paths.py` PASS on both targets' `files.f`; the SPI
  mux is inline (axi_dw_converter + axi_to_axi_lite + reg block — no separate `_ot`
  controller module). **VCS `flist,hdl_compile` PASS (187.7s, default target)** with
  the 10 files + rst_vec fix. Verilator-confirm folded into Phase 1 (tb_top edit
  forces full re-verilate; wrapper macros only elaborate once instantiated).
- **2026-07-17 Phase 0a — base set up + #3911×#3717 reconciled.** Created
  `sep-oss-wrapper-migration` off `origin/main`; `git merge origin/3589-...` was
  CONFLICT-FREE (0 conflicts, none in the OSS DV tree — main's 9 OSS DV commits preserved).
  Commit `d501a134a` = raw merge. Auto-merge was NOT semantically complete:
  #3911 removed the bare-sep `rst_vec` port (EL2 reset vector now via JTAG TDR),
  but the .bos `sep_wrapper` (pre-#3911) still wired `.rst_vec` into `u_sep`
  → compile break. Fixed in commit `f0d9bd045` by dropping the `rst_vec` port +
  connection (mirrors the real `hw/sep/sep_wrapper.sv`, which #3911 already fixed).
  Systematic port diff (PR-era vs main-era bare sep) confirmed `rst_vec` was the
  SOLE real mismatch (`sep_reset_n_o`/`wdt_timer_rst_req_o` diffs were comment-only;
  `ext_trng_axis_*` present on both; `sep_cpu_reset_n_o` correctly merged in).
- **NEXT:** Phase 0b — add the 10 SEP-subset files to the sep flist, wire P1 seed
  render, `check_no_vendor_paths.py`→0, compile both tools.

**CROSS-BRANCH CAUTION (now concrete):** the "rst_vec KEEP" line in the PORT DELTA
appendix was written for the pre-#3911 PR branch and is WRONG for main-based
execution — on main #3911 removed `rst_vec` from bare sep, so the wrapper DROPS it
and the reset vector reaches the DUT via the retained `jtag_*` ports (tb programs
it through TDR, `program_reset_vector_tdr` in `tb/tb_top.sv`). Appendix corrected
below. The designer's eventual #3717→main merge must make the same drop.
Re-audited against PR head `9fd2bd912d` on 2026-07-17: all other load-bearing
claims still hold (D1/D3/DC landed; D2 blocker still live; 10-file SEP subset,
instance paths, `.vlt` targets, PORT DELTA appendix). Remaining gates are OUR-side
(D2 pre-sim image stage + Verilator eFuse public-scope + P1-P4) plus one designer
ACK (AXI-extension aliasing). See Changelog for the v6→v7 delta.

## AUDIT FOLLOW-UPS (2026-07-18 review triage)
Independent review raised the items below; triaged here so nothing is lost.

**RESOLVED this turn:**
- *Committed HEAD deadlocked on 2nd eFuse PROGRAM_READ_BACK (fix was uncommitted).*
  Fixed: committed as `e090ae0b1` (flagged for #3717).
- *Phase 5 retirement incomplete (bare-sep paths + 6 responders remained).* Fixed:
  committed as `1ca5748c3`.
- *No clean-HEAD completed VCS regression (four-tool gate incomplete).* DONE: all four
  regressions pass on clean HEAD `1ca5748c3` (dirty=false, exit 0) — Verilator cpu
  22/22 + no_cpu 47/47, VCS cpu 22/22 + no_cpu 47/47. (VCS must run without a
  concurrent Verilator build — shared build-tree I/O causes VFS_SDB races.)
- *eFuse public-scope entry "required by the plan" is missing.* Analyzed: NOT needed.
  The model deposits via a parent→child **in-RTL hierarchical assignment** inside
  `efuse_bank_model`'s own `initial` (`$readmemh` into a local array, then assign into
  `u_efuse_bank_reg.field_storage...`), NOT a TB cross-hierarchy/VPI write, so Verilator
  compiles it natively without `public_flat_rw`. Proven non-vacuous: `sep_efuse_image_test`
  `CHK-W1S-PERSIST PASS`, 514 value-verified checks. The plan's Sub-problem-A line for
  `efuse_bank_reg field_storage` was over-cautious — do NOT add it (risks re-arming the
  ICO blowup). The 3 real `.vlt` entries (prim_ram_1p.mem / prim_rom.mem /
  ram_16384x39.ram_core) ARE needed — those are TB→DUT cross-hier writes.

**OWNER SIGN-OFF — DONE 2026-07-18:**
- *tb_backdoor_mem DUT-array writes + public scope (new backdoor posture).* ✅ SIGNED OFF
  2026-07-18 by yenhenglai (SEP TB owner). It is memory-init (same class as OCAH's TCM
  load and the retired responders), not a `force` and not pass-faking; it writes DUT-owned
  arrays (not TB-owned) and marks 3 DUT modules public — accepted as the unavoidable
  consequence of using the real macros, with no frontdoor alternative (boot-ROM reset
  fetch is circular) and default fills = valid idle patterns that cannot mask a functional
  bug. Recorded in AGENTS.md §11 backdoor-exceptions (flipped ⚠️PENDING → ✅ SIGNED OFF).

**FLAG TO DESIGNER (#3717 / dkimTT — not our DV deliverable):**
- efuse-model `write_readback_phase_en` fix (e090ae0b1) must land in #3717.
- Wrapper/model sources lack SPDX headers (`efuse_bank_model.sv`,
  `efuse_interface_shim.sv`, `sep_wrapper.sv`, `sep_ip_integration.sv`,
  `och_sep_spi_mux_ctrl_ot_reg{,_pkg}.sv`, ...) — OSS hygiene.
- `sep_axi_extension.rdl` trailing whitespace.
- AXI-extension RTL aliases the whole aperture while generated metadata advertises a
  4-byte map (aliasing already ACCEPTED-for-OSS; still needs the designer ACK the plan
  asked for). Relocated generated eFuse RTL lacks a reproducible generation recipe.

**DV FOLLOW-UPS (ours; post-retire quality) — being worked in order 4→1→2→3:**
- ✅ **[4] DONE (commit `c07edfb9b`): P1 seed render.** `_render_run_test_args()` renders
  `{seed}` into run_mode/test args at all 4 sim sites; `sep_efuse_lcc_lc_state_stitch_test`
  now passes `+sep_efuse_prog_fail_seed={seed}`. PROVEN on Verilator: seed 111→`0x0000006f
  (plusarg)`, seed 222→`0x000000de (plusarg)` (was `0x1badf00d (default)`), both PASS.
  SHARED-RUNLIB edit → owner sign-off per AGENTS.md §12.
- ✅ **[1] DONE (commit `c358bb3b1`): image_test OCAH-parity checkers.** New
  `sep_efuse_direct_read_seq` (raw OTP read via `EFUSE_READ_CTRL`, bypassing shadow);
  `CHK-OTP-DIRECT` (burned bits read 1 from OTP pre-resense, exact-word match) +
  `CHK-W1S-NOCLOBBER` (two same-word programs both persist → catches overwrite-vs-OR
  bank; the bank is HW W1S so no software clear path exists). All PASS on Verilator.
- ✅ **[2] DONE (commit `7efad8999`): DMA-TX chunk_done RW1C readback.** chunk_done
  (bit5) is interrupt-backed + per-chunk, NOT sticky at done (HW-handshake leaves it 0,
  pre=0x2 — an early wrong "set at done" assert was corrected). Fix: catch chunk_done
  mid-transfer and prove its W1C (hard-fail if seen-but-stuck); at done, W1C done+chunk
  and READ STATUS BACK to prove both clear (was a blind write). Verilator PASS.
- ✅ **[3] DONE (commit `7efad8999`): flash-cmd single config object.** New
  `SepSpiFlashCmdCfg` dataclass (mirrors `SepSpiDmaTxCfg`): `from_seed()` + `param_words()`
  (fw patch) + `EXPECTED_OPS`/`pp_bytes()` (BFM golden) all from one object. Verilator
  GOLDEN PASS. **=> all four DV follow-ups (4→1→2→3) DONE + green on Verilator.**
- ✅ **DONE (2026-07-19): custom `+sep_efuse_preload=<path>` prestage override.**
  `dv_sim_prestage.stage()` now parses `+sep_efuse_preload[=path]` from the test's
  rendered plusargs and honors it at t=0 exactly as `sep_base_test.select_efuse_image`
  does at runtime (custom path / bare→committed default / absent→registry). The runlib
  passes `sim_args` (+`root`) to the hook only if its signature accepts them (so other
  DUT hooks are unaffected). Proven with 7/7 directed checks incl. the previously-broken
  custom-path case + loud failure on a bad path. SHARED-RUNLIB edit → owner-directed.
- `sep_efuse_image_test` misses OCAH's pre-resense / direct-read / W1S-negative checkers.
- DMA RX/TX RW1C checks incomplete; flash-command randomization lacks a single config source.

**STATIC POSITIVES (from the same review):** vendor-path checks pass; wrapper filelist
selection clean; reset-vector reconciliation sound; CWD image-fallback restoration matches
the retired responder behavior.

## Goal & hard invariant
Replace the hand-wired `sep u_dut` + TB memory/efuse responders with
`sep_wrapper` (real memory macros + generic efuse model + OpenTitan-only SPI
mux). Preserve every existing verification contract on both VCS and Verilator.
`sep_efuse_image_test` is intentionally refactored to obey persistent OTP
semantics.

## Decisions (locked in review)
1. **Keep `tb/sep_outbound_mbx.sv`** — wrapper exposes `smn_outbound_axi` as a
   port (no internal slave); it's the fw console/PASS monitor, not a mem model.
2. **Execute on the branch** (final `hw/.bos/...` paths).
3. **Remove `efuse_prog_fail_seed_i` port**; runlib injects
   `+sep_efuse_prog_fail_seed=<RANDOM_SEED>` per leaf. CONFIRMED on PR head: the
   port is gone and fail-injection is fully inside `efuse_bank_model.sv` via
   plusargs, now with THREE knobs — `+sep_efuse_prog_fail_count=N` (fail first N
   writes/reset), `+sep_efuse_prog_fail_percent=N` (LCG-PRNG ~N% at random), and
   `+sep_efuse_prog_fail_seed` (default `0x1bad_f00d`). A "fail" zeroes W1S write
   data (silent, visible only via the shim PROGRAM_READ_BACK compare).
   `efuse_otp_responder.sv` was net-deleted by the PR (injection moved into the
   bank model). P1 wires the seed; count/percent are additionally available.

## PREREQUISITES

### Designer changes — LANDED on the #3717 branch 2026-07-16 (re-audited)
- **D1 — eFuse SYNTHESIS guards — DONE.** The `` `ifndef SYNTHESIS `` around both
  the `$readmemh` preload and the fail-injection in `efuse_bank_model.sv` were
  removed, so the model is live in our (SYNTHESIS-defined) build. NOTE the preload
  moved OUT of the generated register into the model's own `initial` block; see
  the new Verilator public-scope requirement in Sub-problem A.
- **D3 — WDT bite output — DONE.** `sep_wrapper` now exports
  `wdt_timer_rst_req_o` (tied off in the OCAH TBs; our tb wires it to
  `dbg_wdt_timer_rst_req_o`). The v3 sub-note is also RESOLVED: a WDT bite now
  DOES reset the SEP memories — `sep.sv` added `sep_cpu_reset_n_o = sep_reset_n &
  wdt_rst_ni`, and the .bos `sep_wrapper` feeds that (`sep_cpu_reset_n`,
  internal net) into `sep_ip_integration.sep_reset_n_i`. **Benign for existing
  tests:** when our tb holds `wdt_rst_ni` deasserted (no bite), `sep_cpu_reset_n
  == sep_reset_n`, so memory-reset behavior is unchanged; only an actual bite
  clears TCM/SRAM. Revisit the loopback (`wdt_timer_rst_req_o`→`wdt_rst_ni`) in
  Phase 4/WDT test if we want to exercise bite→memory-reset (tests must then
  re-init memory). `sep_reset_n_o` is still exposed unchanged.
- **DC — vestigial icache ports — DONE.** `sep_cpu_icache_req/rsp` ports and the
  `sep_pkg` typedefs were removed. Our `tb_top` must NOT declare/tie them.

### D2 — eFuse preload timing (BLOCKER, our-side, Phase-3 critical path)
Load the selected eFuse image once, before the first sense; do not reread/replace
it on later `rst_ni` resense. The bank's persistent W1S `field_storage` retains
frontdoor programs across reset (no separate overlay needed).
**ROOT CAUSE (audited on branch):** the new `efuse_bank_model` deposits ONLY at
pure **t=0 in an `initial` block** with no reset reload. But today the image is
written at **RUNTIME**: `sep_base_test.write_efuse_image()`
(`cocotb/tests/.../sep_base_test.py:379-389`) writes `$CWD/out/sep_efuse.hex`
from *inside the cocotb coroutine* (after t=0). The OLD `tb_sep_efuse_responder`
tolerated this because it **reloads on every reset assert**; the new model does
not. So after cutover every real-sense test (`sep_efuse_sense_test`,
`sep_efuse_image_test`, `sep_efuse_lcc_lc_state_stitch_test`,
`sep_efuse_km_axil_cpu_mux_coexist_test`, `sep_efuse_jtag_axil_el2_cpu_mux_test`,
`sep_lcc_uvm_inbound_filter_gating_test`, `sep_km_otbn_sideload_kat_test`) would
sense a **stale (prior-run) or empty** image — silently on VCS.
**FIX (do before Phase 3):** add a **pre-sim stage** that generates
`out/sep_efuse.hex` from the seed + `+sep_efuse_preload` BEFORE the simulator
launches (analogous to the `c_build` firmware stage) — i.e. factor per-seed image
selection OUT of the coroutine into a pre-sim hook; OR obtain a designer
"load on first `rst_ni` deassert" trigger. Neither exists today; this is the true
gating item (non-trivial). Makes **P3 mandatory** (program-then-resense, never a
mid-run image swap). `+sep_efuse_preload` itself still works — it's a Python
plusarg (`sep_base_test.py:358`), not a retired-responder RTL plusarg.

**D2 DESIGN NOTE (analyzed 2026-07-18):** the image choice lives in
`sep_base_test.select_efuse_image(seed_offset, lc_raw, lock_prob, fixed)` →
`SepEfuseImage().randomize(seed,...)` or `.load(preload_path)` (sep_base_test.py:342-376),
and `write_efuse_image()` writes `<cwd>/out/sep_efuse.hex` (sep_base_test.py:378-408).
The hard part: RANDOM images depend on PER-TEST params (`lc_raw`/`lock_prob`/`fixed`/
`seed_offset`) passed in the test body — a generic pre-sim stage can't know them.
Options: (a) EASIEST — for the efuse tests, drive the image via `+sep_efuse_preload=<committed hex>`
so the pre-sim stage is a deterministic FILE COPY into `out/sep_efuse.hex` (loses per-seed
randomization for those tests — acceptable if the VPLAN card is RAND-NONE, else stage a
seed-named committed image). (b) FULLER — a tiny per-test pre-sim Python hook that imports
`SepEfuseImage`, re-runs the same `randomize(seed, **params)` with a per-test param table,
and writes `out/sep_efuse.hex` before sim; the test body then only READS/checks (never writes).
Either way `SepEfuseImage` (the golden) must be importable outside cocotb. Affected efuse
tests: sep_efuse_sense/image/lcc_lc_state_stitch/km_axil_cpu_mux_coexist/jtag_axil_el2_cpu_mux,
sep_lcc_uvm_inbound_filter_gating, sep_km_otbn_sideload_kat.

### AXI-extension aliasing — ACCEPTED for OSS, flag to designers for ACK
The wrapper maps the ENTIRE extension aperture to the OT SPI mux CSR with no
decode: only offset `0x0` decodes (`MIN_ADDR_WIDTH=3`), every other address
aliases onto the 8-byte mux register and returns **OKAY (never DECERR)** — writes
to non-mux offsets are silently dropped, reads return aliased data. **DV decision
(no risk for OSS):** the removed piece is the Cadence xSPI controller, and the
XIP memory-mapped flash-read path was serviced BY that controller, so removing
Cadence removes both its CSRs and XIP. OSS flash goes through the OpenTitan SPI
host (CSR/FIFO-driven, no memory-mapped XIP through the aperture), so nothing
legitimately addresses the aperture beyond mux-CSR offset 0 and the aliasing is
never exercised. **Note OKAY-on-wrong-address is masking, not safety** (a clean
DECERR would catch a stray access; OKAY hides it) — so this rests on OSS fw/tests
being OSS-clean (no stale OCAH refs to the old XIP region / Cadence CSR addrs;
confirm in Phase 4). **Action: flag a warning to the designers to ACK the
accepted aliasing behavior; do not block on adding DECERR.**

### Our-side prerequisites (this env, no designer dependency)
- **P1 — seed→plusarg render.** Testlist `test.args` are appended literally
  (`runlib/stages.py:1289-1294` VCS, `:1606-1611` Verilator); only cov/wave/
  c_build templates go through `_render_list(...,ctx)`. Wire `run_mode.args` +
  `test.args` through `_render_list` with a seed-bearing ctx at both sim sites so
  a testlist can use `+sep_efuse_prog_fail_seed={seed}`. Prove `--regress
  --reseed` changes the model's logged seed (`efuse_bank_model` prints it).
- **P2 — VCS clean rebuild** on every `tb_top.sv` edit (incremental VCS reuses
  stale elaboration): `rm -rf build/cocotb/vcs` before each wrapper-phase build.
- **P3 — OTP testcase refactor.** `sep_efuse_image_test` must no longer replace
  its image mid-run. It loads one initial image, senses and checks it, programs
  a known-zero legal fuse bit through the frontdoor, then resenses and checks
  the initial image plus that W1S bit. Use separate simulation runs/seeds for
  different initial eFuse images.
- **P4 — SPI flash CS_FORCE_HIGH init.** `och_sep_spi_mux_ctrl_ot` resets
  `CS_FORCE_HIGH=1` (RDL `= 0x1`; reg reset `<= 1'h1`), forcing CS deasserted.
  Bare SEP fed the OT SPI host directly, so flash tests never wrote the mux. DV
  adds a shared frontdoor write clearing `CS_FORCE_HIGH` (mux CSR in the extension
  aperture) before each flash scenario.

## Architecture
```
BEFORE: sep_uvm_top -> sep u_dut + {tcm,sram,bootrom,km,otbn,efuse} responders + sep_outbound_mbx
AFTER:  sep_uvm_top -> sep_wrapper u_dut -> u_sep (bare sep)
                                          -> u_sep_ip_integration
                                             (prim_ram/prim_rom + EL2 TCM + efuse shim+bank + OT SPI mux)
                       + tb_backdoor_mem (memory default-fill + image load + observability)
                       + sep_outbound_mbx (kept)
```

## Retire / Keep / Add
**Retire (6):** `shims/mem/tb_tcm_responder.sv`, `tb_sep_sram_responder.sv`,
`tb_boot_rom_responder.sv`, `tb_km_mem_responder.sv`,
`tb_otbn_mem_responder.sv`, `shims/analog/tb_sep_efuse_responder.sv`.

**Keep:** `tb/sep_outbound_mbx.sv`; shims `cpu/sep_cpu_stub.sv`,
`prim/prim_sync2.sv`, `analog/entropy_ring_oscillator.sv`,
`crypto/abr_wrapper_key_reg_stub.sv`.

**Add to flist (10, dependency order — exact paths pinned vs PR head `9fd2bd912d`,
2026-07-17):**
```
hw/.bos/models/efuse/efuse_shim_ctrl_reg_pkg.sv
hw/.bos/models/efuse/efuse_bank_reg_pkg.sv
hw/.bos/models/efuse/efuse_shim_ctrl_reg.sv
hw/.bos/models/efuse/efuse_bank_reg.sv
hw/.bos/models/efuse/efuse_interface_shim.sv
hw/.bos/models/efuse/efuse_bank_model.sv
hw/.bos/meta/registers/rtl/och_sep_spi_mux_ctrl_ot_reg_pkg.sv
hw/.bos/meta/registers/rtl/och_sep_spi_mux_ctrl_ot_reg.sv
hw/.bos/wrapper/sep/sep_ip_integration.sv
hw/.bos/wrapper/sep/sep_wrapper.sv
```
The 6 efuse files RELOCATED here from `hw/periph/efuse/rtl/...` (the old
`efuse_interface_shim.sv` + `efuse_model/efuse_bank_model.sv` there are DELETED by
the PR — do not reference them). All vendor-clean.
**NEW `.f` HEAD DEPS ARE SMC/SMU-ONLY, NOT SEP:** `oss_wrapper_sources.f` now
opens with `vendor/opentitan/upstream/.../prim_pad_wrapper{_pkg,}.sv` (vendor
paths) for the SMC/SMU padring — the SEP subset above does NOT instantiate
`prim_pad_wrapper` (verified in `sep_wrapper.sv`/`sep_ip_integration.sv`), so
taking ONLY the SEP subset keeps `check_no_vendor_paths` clean.
**NAMING TRAP:** must add the `_ot_` SPI-mux reg files — the non-`_ot_`
`och_sep_spi_mux_ctrl_reg{,_pkg}` already in our flist is a different module
(different module+package names, so no collision — just add the `_ot_` pair).
The designer filelist `hw/.bos/filelists/oss_wrapper_sources.f` lists this
exact SEP subset in this dependency order — take ONLY the SEP subset, NOT the
whole `.f` (it also pulls `smc_wrapper`/`smu_wrapper`/pll/pvt/pad models).
**BENDER CAUTION:** the real `hw/sep/sep_wrapper.sv` + `hw/sep/sep_ip_integration.sv`
share these module names but are gated behind the `tt_sep_dv_files` / `sep_wrapper`
bender targets, which our `bender_targets = ["sep","sep_el2"]` does NOT enable —
so the .bos versions don't clash. NEVER add `tt_sep_dv_files` or
`sep_wrapper` to `bender_targets` or you pull the real ones and get a MODDUP.
Wrapper-instantiated deps (`prim_ram_1p_adv/1p/rom`, `sep_{sram,rom}_interface_shim`,
`sep_tcm_wrapper`) are already in the `sep`/prim closure — no hidden extras.

## Sub-problem A — Memory preload + DEFAULT FILL (make-or-break)
Wrapper macros use `MemInitFile("")` and have no runtime plusarg init; EL2
`ram_core` has none either. `prim_util_memload` init is `` `ifndef SYNTHESIS ``
(off in our build) — irrelevant since we backdoor the arrays directly. A tb
`tb_backdoor_mem` block `$readmemh`s images AND pre-fills correct DEFAULT
patterns (macros power up X on VCS / 0 on Verilator — both wrong for KM SRAM &
OTBN). Arrays must be public in `sep_public_scope.vlt`. **Current `.vlt` has ONLY
`public_flat_rw -module "sep_uvm_top" -var "*"`** — none of the DUT arrays or the
efuse storage are public, so backdoor/deposit writes silently no-op under
Verilator. Exact entries to ADD (all outside the hot AXI ready/valid cones, so
they don't re-arm the ICO blow-up):
```
public_flat_rw -module "prim_ram_1p"    -var "mem"           // SEP SRAM, KM SRAM (u_mem), OTBN imem, OTBN dmem
public_flat_rw -module "prim_rom"       -var "mem"           // SEP boot ROM, KM ROM
public_flat_rw -module "ram_16384x39"   -var "ram_core"      // ICCM gen_bank[0..3] + DCCM gen_bank[0..1]
public_flat_rw -module "efuse_bank_reg" -var "field_storage" // eFuse t=0 deposit target
```
(TCM macro is `ram_16384x39` — `EL2_RAM(16384,39)`, confirmed for BOTH ICCM
`ICCM_INDEX_BITS=0x0E` and DCCM 128KB/2-bank; the plan table's `ram_core` leaf is
the reg array inside it. Editing `.vlt` auto-triggers a Verilator rebuild.)

**Paths VERIFIED against RTL (2026-07-18, implemented in tb_backdoor_mem). Plan
CORRECTIONS: TCM generate arms are `gen_iccm_ram`/`gen_dccm_ram`, NOT `gen_ram`
(the old path was a silent no-op); widths pinned (dmem=312b=8×39, SRAM/ROM=64b,
KM=36b).**

| Mem | Path (root `u_dut`=`sep_wrapper`) — depth×width | Image trigger | DEFAULT fill (unloaded) |
|---|---|---|---|
| ICCM | `u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.gen_iccm.gen_bank[0..3].gen_iccm_ram.ram.ram_core` — 16384×39 | `tcm_load_i`; bank=`addr[3:2]`,row=`addr[17:4]`,+Hsiao ECC | ECC-valid zero (ecc(0)=0) |
| DCCM | `...gen_dccm.gen_bank[0..1].gen_dccm_ram.ram.ram_core` — 16384×39 | `tcm_load_i`; bank=`addr[2]`,row=`addr[16:3]`,+Hsiao ECC | ECC-valid zero |
| SEP SRAM | `u_dut.u_sep_ip_integration.u_sep_sram.gen_ram_inst[0].u_mem.mem` — 32768×64 | `+sep_sram_hex` | 0 |
| Boot ROM | `...u_sep_boot_rom.mem` — 16384×64 | `+sep_boot_rom_hex` | 0 (match `tb_boot_rom_responder`) |
| KM ROM | `...u_km_rom.mem` — 4096×36 | `+km_rom_hex` | `{word_parity(0x13),0x13}` (NOP+parity) |
| KM SRAM | `...u_km_sram.gen_ram_inst[0].u_mem.mem` — 4096×36 | — | `{4'hF,32'h0}` (else spurious `SRAM_PARITY` fault) |
| OTBN imem | `...u_otbn_imem_sram.mem` — 4096×39 | — | `prim_secded_pkg::SecdedInv3932ZeroWord` (raw 0 is NOT a valid codeword) |
| OTBN dmem | `...u_otbn_dmem_sram.mem` — 1024×312 | — | `{8{SecdedInv3932ZeroWord}}` |

eFuse is NOT tb-backdoored — the **model self-preloads** via `+sep_efuse_hex`
(default `out/sep_efuse.hex`). But its `initial` block deposits at t=0 into the
generated register storage:
`u_dut.u_sep_ip_integration.u_efuse_bank_model.u_efuse_bank_reg.field_storage.EFUSE_BANK_REG[*].dout.value`.
**Verilator public-scope requirement (BLOCKER, verify-on-integrate):** that
storage target is a cross-module hierarchical write; under Verilator it must be
public (`sep_public_scope.vlt`) or the deposit no-ops → **empty bank → all-zero
sense → real-sense tests fail silently.** VCS handles it and will hide the
problem, so verify one fuse word is non-zero specifically under Verilator. Image
must be PRE-STAGED before sim (see D2 — t=0 deposit); later `rst_ni` resense
retains the persistent W1S contents.

## Sub-problem B — Observables re-derivation (tb, from wrapper-internal nets)
- `dbg_iccm_active/addr`, `dbg_dccm_active` ← `u_dut.sep_cpu_tcm_req.*`.
- `km_*_count`, `otbn_{i,d}mem_{req,write}_count` ← tb counters on
  `u_dut.km_rom_mem_req` / `u_dut.km_sram_mem_req` /
  `u_dut.sep_crypto_pka_{imem,dmem}_sram_req`. These counts were
  `tb_km_mem_responder` / `tb_otbn_mem_responder` OUTPUTS; the retired responders
  take them away, so the tb must RE-IMPLEMENT the counters and match the old
  semantics (req vs req&gnt, write-detect). km SRAM gnt=1 and otbn req=enable, so
  counting `.req` is correct for those.
- `km_sram_word0` ← peek `u_dut.u_sep_ip_integration.u_km_sram.gen_ram_inst[0].u_mem.mem[0][31:0]`.
- `fw_*` ← unchanged (kept `sep_outbound_mbx`).

## Sub-problem C — Re-root + remap in `tb_top.sv`
- **XMR re-root (mechanical):** `u_dut.` → `u_dut.u_sep.` for `sep_cpu` (LSU resp
  mux, `o_cpu_run_ack`), `sep_crypto` (efuse shadow + all ESRC/DRBG/CSRNG/EDN
  taps + the ESRC noise `force`), `sep_system_peripherals` (scratch-cold),
  `sep_internal_interrupts`, `sep_cpu_reset_n`.
- **WDT probe (D3 done):** `dbg_wdt_timer_rst_req_o` ← wrapper output
  `wdt_timer_rst_req_o` (now exposed).
- **`sep_reset_n`:** `dbg_sep_reset_n_o` ← wrapper port `sep_reset_n_o` (still
  exposed, unchanged). Memories are internally reset by `sep_cpu_reset_n`
  (= `sep_reset_n & wdt_rst_ni`) inside the wrapper — no tb XMR change; holding
  `wdt_rst_ni` deasserted keeps this equal to `sep_reset_n`.
- **SPI remap:** tap wrapper pad ports — `spi_clk_o`→sck, `spi_txd_o[0]`→MOSI,
  `spi_cs_n_o`→CS, drive `spi_rxd_i[1]`=MISO. Top-level `spi_*` ports and the
  `OcahSpiFlash` BFM unchanged. NOTE: wrapper loops SPI host IRQ back into
  `u_sep.spi_irq_i` (was tied 0 in tb) — verify `sep_spi_ot_host_csr_irq_rand_test`.
- **efuse seed:** delete `efuse_prog_fail_seed_i` port (P1 supplies the plusarg).
- **Tie-offs:** `smc_fuse_sense_done_i`←0. (icache tie-off REMOVED — DC done.)
- **DELETE from the instantiation (or COMPILE FAILS "no such port"):** these are
  bare-`sep` ports currently wired `()` in tb_top (`:519-524,548-549`) that
  `sep_wrapper` ties off internally on `u_sep` and does NOT expose:
  `lc_state_o`, `feat_ctrl_o`, `lc_sigint_err_o`, `security_disable_o`,
  `secure_tm_o`, `km_unrecoverable_err_o`, `km_recoverable_err_o`.
- **New wrapper SPI INPUTS to tie 0 (X-prop guard):** `spi_rxds_i`,
  `spi_mem_rebar_ipad_i`, and the unused `spi_rxd_i[7:2,0]` (only `[1]`=MISO is
  driven). Wrapper SPI OUTPUTS (`spi_enable_o`, `spi_{cs,clk,dqs}_{oe,ie}_n_o`,
  `spi_dq_{oe,ie}_n_o`, `spi_mem_rebar_{oepad,opad,iepad}_o`) can stay open.
- **Param:** `#(.EXT_TRNG_NUM_AXIS(2))` — wrapper adds it (default 2); optional.
See the full PORT DELTA TABLE appendix for the KEEP/REMOVE/ADD breakdown.

## Phased execution (each phase regression-gated; one-step-then-review)
0. **Sync + compile-only** (on branch; D1/D3/DC already landed): add 10 files;
   `check_no_vendor_paths.py`→0; compile both tools. + P1 runlib change.
1. **Wrapper swap behind `SEP_USE_WRAPPER`** + re-rooted XMRs (ifdef, A/B).
   Smoke: `sep_hello_world_test`, `sep_rom_sanity_test`.
2. **`tb_backdoor_mem` (A+B):** default-fill + image load + observables;
   public-scope arrays. Validate boot / KM-KAT / OTBN / SRAM tests.
3. **efuse cutover:** drop efuse responder (relies on D1 done + D2 pre-stage +
   Verilator public-scope + P1/P3). Validate
   `sep_efuse_sense_test`, `sep_efuse_image_test`,
   `sep_efuse_lcc_lc_state_stitch_test` (resense + seed sweep),
   `sep_efuse_jtag_axil_el2_cpu_mux_test`,
   `sep_efuse_km_axil_cpu_mux_coexist_test`,
   `sep_lcc_uvm_inbound_filter_gating_test`, `sep_km_otbn_sideload_kat_test`.
   Gate: confirm `out/sep_efuse.hex` word count/width/order matches the model's
   1024x32b `EFUSE_BANK_REG` deposit.
4. **SPI remap + flash init (P4 — clear CS_FORCE_HIGH before flash scenarios):**
   validate `sep_spi_flash_jedec_smoke_test`,
   `sep_spi_ot_dma_rx_test`, `sep_spi_ot_dma_tx_test`,
   `sep_spi_ot_flash_cmd_rand_test`, + IRQ-loopback check on the csr/irq test.
5. **Full retire of the bare-sep path (user directive 2026-07-18) — do ONLY after
   no_cpu+cpu are green on BOTH tools.** Remove `SEP_USE_WRAPPER` entirely: make the
   XMR macros UNCONDITIONAL — `` `define SEP_CORE u_dut.u_sep `` and
   `` `define SEP_IPI u_dut.u_sep_ip_integration `` (no `ifdef`/`else`). Delete the
   bare-`sep` instantiation + all `ifndef SEP_USE_WRAPPER` blocks; delete the 6
   responder files (`shims/mem/tb_{tcm,sep_sram,boot_rom,km_mem,otbn_mem}_responder.sv`,
   `shims/analog/tb_sep_efuse_responder.sv`) + their `[build].sources` entries + the
   now-dead responder wires/`efuse_prog_fail_seed_i` port; remove `SEP_USE_WRAPPER`
   from both target `defines`. Keep `sep_outbound_mbx` + the accepted shims.
   **FINAL INTEGRATION GATE (user directive 2026-07-18): no_cpu AND cpu regressions
   must pass on BOTH VCS and Verilator** (not Verilator-only) — run all four, all
   green, then docs. This is the "integration success" bar.

## Verified OK — do NOT re-investigate
- **OTBN imem `q_valid`=0** in the wrapper (`sep_ip_integration.sv:375`) vs the
  responder pulsing it: benign — this is the OCAH/silicon integration (OTBN
  fetch uses fixed latency; external `q_valid` not load-bearing).
- **KM SRAM rvalid-on-write:** `prim_ram_1p_adv` asserts `rvalid` read-only
  (`rvalid_sram_d = req & ~write`, line 188) — matches responder.
- **SEP SRAM write-completion:** `sep_sram_interface_shim` synthesizes it
  (`rvalid = macro_rvalid_i | write_req_q`, line 64) — matches responder.

## Risks & mitigations
- **Verilator perf / public scope:** backdoor-writable arrays must be public;
  keep scoping targeted (not global) to preserve the ICO fix; verify SCC count
  after Phase 2.
- **Backdoor into DUT hierarchy:** we now write DUT-owned arrays (not TB-owned).
  It is memory-init (not a `force`, not pass-faking; same class as today's
  responders / OCAH TCM load), but the DUT-hierarchy write + public-scope is a
  new posture — document it and get owner ack.
- **efuse image format** (Phase-3 gate); **SPI IRQ loopback** (Phase-4 check);
  **responder-vs-macro timing** surfaces in per-phase regression.

## Validation
Develop on VCS (clean rebuild per P2), confirm on Verilator. **FINAL INTEGRATION GATE
(user directive 2026-07-18): the split `no_cpu` AND `cpu` regressions must pass on BOTH
VCS and Verilator** — all four runs green — plus `check_no_vendor_paths.py` on the
generated final sep filelist. Verilator-only green is NOT sufficient for this migration;
both tools confirm the wrapper integration. #3717's green CI does NOT cover this env.
(VCS no_cpu note: verify the VCS flow actually builds/runs the CPU-stub target for
no_cpu tests — the CPU-LSU splice is SV-side so it should, but confirm rather than
assume, since earlier VCS runs here were compile-only on the full-CPU `default` target.)

## Appendix — PORT DELTA: `sep u_dut` → `sep_wrapper u_dut` (audited)
- **KEEP (unchanged both):** clk_i, clk_ref_i, clk_wdt_i, rst_ni, dbg_rstb_i,
  wdt_rst_ni, entropy_rosc_sample_clk_i, `sep_reset_n_o`, `wdt_timer_rst_req_o`,
  jtag_{tck,tms,tdi,trst_n,tdo,tdoEn}, jtag_sep_reset_ctrl_i,
  axil_sep_otp_jtag_{req_i,resp_o}, mpc_{debug_halt_req,debug_run_req,reset_run_req},
  i_cpu_{halt,run}_req, test_en_i, scan_rst_ni, ext_boot_seq_done_i, dmi_*,
  sep_cpu_trace, jtag_id, timer_int, soft_int, extintsrc_req,
  smn_outbound_axi_*, smn_inbound_axi_*, sep_ext_to_smc_axi_*,
  lcc_demote_state_{1,2}_o, smc_mailbox_interrupt_o, smc_fuse_sense_done_i,
  sep_fuse_sense_done_o, sep_straps_i, smc_global_base_addr_i, smc_region_size_i,
  sep_global_base_addr_o, sep_region_size_o, ext_debug_bus_o.
- **REMOVE (internalized by wrapper → retire responders):** sep_cpu_tcm_{req_o,rsp_i},
  sep_sram_{req,rsp}, sep_boot_rom_{req,rsp}, sep_crypto_pka_{imem,dmem}_sram_{req,rsp},
  ext_trng_axil_{req_o,resp_i}, ext_trng_axis_{req_i,rsp_o}, ext_trng_{irq_i,alarm_i},
  km_{rom,sram}_mem_{req_o,rsp_i}, efuse_bank_ctrl_{req_o,resp_i},
  efuse_shim_command_{req_o,resp_i}, sep_io_spi_{req_o,rsp_i}, spi_irq_i,
  axi_extension_axi_{req_o,resp_i}.
- **DROP `rst_vec` (main-based execution only):** #3911 removed `rst_vec` from bare
  sep (EL2 reset vector sourced from JTAG TDR internally), so the .bos
  `sep_wrapper` must NOT declare/wire it (done, commit `f0d9bd045`). The reset
  vector reaches the DUT via the retained `jtag_*` ports; the tb programs it with
  `program_reset_vector_tdr` in `tb/tb_top.sv`. (On the raw pre-#3911 PR branch
  `rst_vec` was a KEEP port — that is the stale reading.)
- **REMOVE (currently `()`; NOT wrapper ports → compile error if kept):** lc_state_o,
  feat_ctrl_o, lc_sigint_err_o, security_disable_o, secure_tm_o,
  km_unrecoverable_err_o, km_recoverable_err_o.
- **ADD (wrapper SPI pads):** spi_clk_o→sck, spi_txd_o[0]→MOSI, spi_cs_n_o→CS,
  spi_rxd_i[1]←MISO; tie 0: spi_rxds_i, spi_mem_rebar_ipad_i, spi_rxd_i[7:2,0].
- **XMR body reads** `u_dut.` → `u_dut.u_sep.` for: sep_cpu.o_cpu_run_ack (~:725),
  sep_cpu_reset_n (~:729), sep_internal_interrupts (~:734), sep_crypto.* (:778,
  :809-895), sep_system_peripherals.* (:786), sep_cpu.lsu_axi_resp (:943-955).
  Sub-problem B taps stay at wrapper level `u_dut.`.

## Changelog
- **v7 (execution kickoff on local merge branch, 2026-07-17):** moved from PLANNING
  to EXECUTING. Per user, work on a branch (not main) with the wrapper present.
  Because #3717 is unmerged + 104 behind main, built a THROWAWAY local integration
  branch `sep-oss-wrapper-migration` = `origin/main` + `git merge origin/3589-...`
  (conflict-free; 0 conflicts in the OSS DV tree, so main's 9 recent OSS DV commits incl.
  the 95-line `tb_top.sv` work are preserved). Discovered + fixed the #3911×#3717
  semantic gap the auto-merge left: bare sep lost its `rst_vec` port under #3911,
  so dropped `rst_vec` from the .bos `sep_wrapper` (commit `f0d9bd045`,
  mirrors the real wrapper). Corrected the PORT DELTA appendix (`rst_vec` KEEP→DROP)
  and added a top-of-doc PROGRESS LOG. Do NOT push the local branch or the PR branch.
- **v6 (re-audit vs PR #3717 head `9fd2bd912d`, 2026-07-17):** plan re-verified
  against the live PR (updated same day). Every load-bearing claim CONFIRMED:
  D1/D3/DC landed (`hw/sep/sep.sv` now exports `sep_cpu_reset_n_o`, wrapper wires
  it into `u_sep_ip_integration.sep_cpu_reset_n_i`); **D2 blocker STILL LIVE** —
  `efuse_bank_model.sv` still deposits the OTP image at pure t=0 `initial` (not
  reset-gated), so the pre-sim `out/sep_efuse.hex` stage + P3 remain mandatory;
  10-file SEP subset + dependency order match `oss_wrapper_sources.f`; all
  Sub-problem A instance names + OTBN imem `q_valid=1'b0` at line 375 + `.vlt`
  deposit target `efuse_bank_reg.field_storage`; Sub-problem C `u_sep`/
  `u_sep_ip_integration` names + SPI-IRQ loopback; PORT DELTA appendix (DELETE-list
  ports absent from wrapper, "internalized" names are internal nets w/ port list
  closing at line 161, KEEP ports present, `EXT_TRNG_NUM_AXIS=2`). Folded in the
  staleness: (1) exact flist paths pinned — efuse files RELOCATED to
  `hw/.bos/models/efuse/` (old `hw/periph/efuse/rtl/...` copies DELETED);
  (2) fail-injection now has count + percent + seed plusargs (Decision 3);
  (3) new `.f`-head `prim_pad_wrapper` vendor deps are SMC/SMU-only, not SEP;
  (4) CROSS-BRANCH: PR is 104 commits behind main + diverged, does NOT contain
  #3911 reset-vector TDR → execute on main after #3717 lands, not on the PR branch.
- **v5 (fresh-agent kickoff-readiness audit vs branch, 2026-07-16):** plan verified
  "unusually accurate" — 10-file flist + order, all Sub-problem A memory leaf paths
  (TCM macro = `ram_16384x39`), eFuse deposit target + no-reset persistence, D1/D3/DC,
  SPI taps + IRQ-loopback, and all XMR re-root targets all CONFIRMED on branch. Folded
  in the gaps: D2 sharpened to a Phase-3 BLOCKER with concrete root cause (runtime
  `sep_base_test.write_efuse_image():379-389` vs t=0-only deposit; old responder
  reloaded on reset) + fix (pre-sim hex-gen stage); exact `.vlt` public-scope add-list
  (incl. `ram_16384x39 ram_core` + `efuse_bank_reg field_storage`); flist/bender
  cautions (SEP subset of `oss_wrapper_sources.f` only; never add `tt_sep_dv_files`/
  `sep_wrapper` targets → MODDUP); Sub-problem C now lists the ports that must be
  DELETED (else compile error) + new SPI input tie-offs; km/otbn counter re-impl note;
  added the PORT DELTA appendix.
- **v4 (re-audit vs #3717 branch, 2026-07-16):** D1/D3/DC LANDED on the branch —
  moved to "designer changes DONE"; D3 sub-note resolved (WDT bite now resets SEP
  memories via new `sep_cpu_reset_n_o = sep_reset_n & wdt_rst_ni`, benign when
  `wdt_rst_ni` held deasserted). D2 reframed as our-side: branch still deposits at
  pure t=0 `initial` (no first-`rst_ni` trigger) → DV must PRE-STAGE the image,
  P3 mandatory. Added Verilator public-scope BLOCKER for the model's t=0 eFuse
  deposit target (Sub-problem A). AXI-extension moved from "raise" to ACCEPTED
  (no risk for OSS: Cadence xSPI + its XIP path removed, OSS flash via OT SPI host
  at offset 0 only) — action is to flag designers for ACK, not to add DECERR.
  Removed the obsolete icache tie-off from Sub-problem C; OTBN `q_valid` line
  `:403`→`:375`. Confirmed still-valid: 10-file flist (incl. `efuse_shim_ctrl_reg`,
  which `efuse_interface_shim` instantiates) and all Sub-problem A memory instance
  paths.
- **v3:** dropped the eFuse resense file-reload — D2 is now a one-time preload
  with a load-trigger recommendation (load on first `rst_ni` deassert, not pure
  t=0); added P3 (OTP testcase refactor: program-then-resense persistence) and
  P4 (SPI CS_FORCE_HIGH flash init, reset value confirmed) + Phase-4 step; added
  AXI-extension DECERR as a non-blocking spec item; SPI init is DV-owned, dropped
  from the designer asks.
- **v2:** added blocking designer prereqs D1-D3 (eFuse SYNTHESIS, eFuse resense
  reload+overlay, WDT output) + optional DC (vestigial icache ports) + our-side
  P1 (seed render) / P2 (VCS rebuild); expanded Sub-problem A with correct
  DEFAULT fill patterns (KM SRAM `{4'hF,0}`, KM ROM NOP+parity, OTBN SECDED
  zero); added WDT + SPI-IRQ-loopback to Sub-problem C; added "Verified OK"
  (OTBN q_valid, KM/SEP SRAM rvalid); tightened validation. Corrected v1's
  "efuse self-preload matches responder" (missed SYNTHESIS + resense) and
  "OTBN zero-init" (needs SECDED encoding).
