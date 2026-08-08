<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS DV — Working Rules (AGENTS.md)

Rules for building and maintaining the SEP open-source DV env under
`hw/sys/sep/dv/`. Keep this tree self-contained and repo-root-relative so the
build, tests, shims, and docs are reviewable as one OSS DV unit.

`README.md` (same directory) is the **what and how to run** — layout, run modes,
build prerequisites, `run_dv.py` invocations. This file is the **house rules**:
hygiene gates, verification quality, the port workflow, and hard-won lessons.
Read `README.md` first; do not duplicate its content here.

For VPLAN creation and OSS-vs-internal coverage compression, read and follow
`docs/VPLAN_CREATION_RULES.md`.

**Provenance note.** Tests here are ported from the internal `tt-oca-hw` UVM SEP
TB (referred to below as **OCAH**), which lives in a separate checkout
(`dv/sep/tb/tb_uvm/` there). Those paths do not exist in this repository; when a
rule says "read the OCAH reference", it means the internal checkout.

## 1. Open-source hygiene is a HARD GATE
- This is an open-source project: **NO licensed/proprietary IP in the build.**
  No vendor/foundry/internal-NFS paths in any SEP filelist, ever
  (`/vendor_ip/*`, `/tech/*`, `/nfs/tools`, `/tools_vendor`, `/tools_soc` as
  *source* paths).
- Before declaring any build "done", run:
  `python3 tools/dv/check_no_vendor_paths.py --filelist <sep.flist>` → must exit 0.
- Bender targets: `["sep", "sep_el2", "sep_wrapper"]` only — NEVER add
  `"simulation"` (it pulls Cadence + Samsung padring).
- Never reuse the Samsung efuse models (`efuse_*_samsung`,
  `sf_otp32kb_*_ln04lpp_*`). The DUT uses the generic OSS eFuse model (see
  `docs/OSS_EFUSE_OTP_MODEL_SPEC.md`); `+skip_fuse_sense` bypasses sense entirely
  for tests that do not need it.
- **TT-authored firmware IS in scope when it open-sources alongside the RTL it
  exercises** — this is distinct from third-party vendor IP, which stays out.
  The Key Manager ROM firmware (`hw/ip/key_manager/dv/fw/`, built to
  `rom_main.rom.parhex`) is TT's own code that ships open-source with the
  `key_manager` RTL, so an OSS SEP test MAY load it via `+km_rom_hex` to drive
  the real KM key-management datapath (the KM→crypto sideload KATs need the real
  firmware: `CMD_KEY_GENERATE`/`CMD_KEY_TRANSFER` are firmware, not pure HW).
  Caveats: build it from the tracked source (rv32emc/ilp32e GCC), never depend on
  an untracked prebuilt artifact.
- A TT-authored wrapper that *depends on* licensed leaf cells is itself out of
  scope: **drop it from the filelist** via `[build].exclude_files`, do NOT
  blackbox-stub the licensed cell. Current exclusion: `sep_cdns_spi_wrap.sv`
  (needs Cadence xSPI/PHY); the wrapper's SPI path uses the OpenTitan
  `sep_ot_spi_wrap`, so excluding it is free. `check_no_vendor_paths` does NOT
  catch these (the wrapper sits on a TT path), so they need manual care.
- **Do NOT borrow OCAH-internal testcase IDs.** The `TC_*` codes
  (`TC_FABRIC_036`, `TC_SPIOT_017`, `TC_CLK_009`, …) are OCAH-tb-internal
  identifiers and must not appear anywhere in this tree (test/seq/fw/toml
  comments, docstrings, VPLAN docs). Cite provenance by the OCAH **test name**
  + behavior instead (e.g. "OCAH `sep_cpu_lsu_negative_matrix_test`") — the
  VPLAN provenance gate (§9, `docs/VPLAN_CREATION_RULES.md`) requires the name,
  not the ID. Grep new work for `TC_[A-Z]+_[0-9]+` before committing.
- **Do NOT expose local VPLAN representative IDs in user-facing DV surfaces.**
  Local rep IDs matching `\b(TD|CRY|CPU|MEM|DMA|EFL|KM|SPI|PIO|FAB|RST)-[0-9]+\b`
  are planning shorthand only. They may live in VPLAN/tracker planning docs, but
  must not appear in simulator logs, firmware `PASS`/`FAIL` text, Python
  `logger.*` messages, `print()` output, cocotb/PyUVM test descriptions that
  appear in results, testlist comments intended for run display, or source
  comments/docstrings that explain shipped tests. Use descriptive names instead,
  e.g. "crypto-EDN multisink arbitration" or "AES mode/key-size breadth". Grep
  runtime-facing changes for the same pattern.

## 2. Layout rules
- SEP-local DV stays self-contained under `hw/sys/sep/dv/`. Shared OSS DV Python
  lives in the installed package under `hw/common/dv/`; VIPs live under
  `hw/common/dv/vip/` (`ocah_axi_vip`, `ocah_spi_vip`, `ocah_entropy_vip`, …).
- Repo-root-relative paths only (the runlib resolves them). No absolute
  `/proj_soc/...` paths in committed files.
- SPDX `Apache-2.0` header on every file.
- Python imports use the current package/module names directly, for example
  `from ocah_spi_vip import OcahSpiFlash`, `from env.sep_axi_agent import ...`,
  and `from seq_lib... import ...`.
- **DELIBERATE layout choices over `dv-directory-structure-guide.md` — do NOT
  "realign" these to the guide:**
  - Verilator/behavioral shims live under `shims/` by function (`shims/prim/`,
    `shims/cpu/`, `shims/crypto/`, `shims/analog/`), not `tb/verilator_stubs/`.
    This is a SEP layout choice and intentionally diverges from smc/dtp-style stub
    dirs. Two deliberate policy differences come with it, and neither is drift:
    - **SEP allows a product-module override; SMC forbids one.** SMC's README
      restricts `tb/verilator_stubs/` to tooling shims and bans product-module
      overrides. `shims/cpu/sep_cpu_stub.sv` is exactly such an override — it
      replaces `sep_cpu`. It is allowed here because it *is* the `no_cpu` build
      target (a first-class run mode, not a workaround) and is the sole driver of
      the LSU master bus (§4). It is selected per-target, never in the CPU build.
    - **`shims/prim/prim_sync2.sv` is not a copy of the same-named smc/dtp stub.**
      Those substitute a behavioral two-flop model; SEP's is a pure port remap that
      keeps the real `prim_flop_2sync` in the design. Do not consolidate them —
      collapsing SEP onto the shared stub would silently lower CDC fidelity.
  - `sep_sim.core` + `[build].manifest` are kept (the guide says skip `.core`
    unless a real consumer exists).
  Everything else follows the guide (env/seq_lib/tests/tb/testlists/docs layout).

## 3. Scope & stack
- The internal UVM TB is a separate stack; ours is greenfield cocotb/PyUVM on
  Verilator. Reference it for *method* only.
- DUT = `sep_wrapper` (`hw/top/sep_wrapper.sv` + `hw/top/sep_ip_integration.sv`),
  which instantiates the bare `sep` core (`hw/sys/sep/rtl/sep.sv`) plus its IP
  integration: real memory macros, the generic eFuse model, the OpenTitan SPI mux.
- **No-CPU AXI path (primary stimulus).** cocotbext-axi master spliced onto the
  CPU LSU bus with the CPU held off. Testlist `run_modes = ["no_cpu"]`; bring-up
  via `bring_up_no_cpu` / `bring_up_and_wait_fuse_sense`. This path has **NO
  inbound filter**.
- **External SMN-inbound master.** The DUT's real `smn_inbound_axi_*` port is
  brought out of `tb_top` as a flat `m_axi_*` master and driven by a SECOND
  `SepAxiAgent` (`sep_env.ext_axi_agent`, run via `sep_base_test.start_ext_seq`).
  It idles unless a test drives it. Unlike the CPU-LSU splice, this path
  TRAVERSES the inbound filter (`u_inbound_filter`, block-by-default →
  RESP_DECERR; skipped only when `feat_ctrl.sep_debug=1`), so it is the OSS
  analog of OCAH's `ext_axi_sqr` for inbound-filter / security-boundary tests.
  Driving a real DUT port is frontdoor, NOT a backdoor. With
  `smc_global_base_addr_i=0` the inbound global→local remap is identity, so the
  external master drives local SEP addresses directly (e.g. `0x1091_8000`).
- **CPU FW-boot path.** VeeR EL2 boots firmware from ICCM; `sep_cpu_trace`
  PC-advance + outbound-mailbox console/PASS magic. Testlist
  `run_modes = ["cpu"]` adds `+cpu_boot`; bring-up via `boot_firmware` (§10).
- Port selected OCAH tests through these paths — follow the per-test workflow in
  §9 after the VPLAN selection follows `docs/VPLAN_CREATION_RULES.md`. Status is
  tracked in `docs/SEP_OSS_VPLAN_PHASE1.md` (smoke + TOP-20, closed),
  `docs/SEP_OSS_VPLAN_PHASE2.md` (basic-feature breadth), and
  `docs/SEP_OSS_VPLAN_PHASE3.md`.
- Template = DTP (PyUVM); style/minimalism = SMC. Reuse existing BFMs before
  writing new ones.

## 4. Boot/reset invariants (or the smoke hangs/SLVERRs)
- Drive `ext_boot_seq_done_i = 1` (DUT port — not a plusarg).
- Add `+skip_fuse_sense` (RTL plusarg) in a testlist entry when the test should
  bypass real fuse sense and release the fuse-gated fabric quickly. Tests that
  exercise real fuse sense omit this plusarg and use the OSS eFuse model.
- Keep run modes limited to CPU ownership: `no_cpu` for AXI-driver tests and
  `cpu` for VeeR EL2 firmware-boot tests. Test-specific knobs such as
  `+skip_fuse_sense`, `+km_rom_hex`, `+esrc_noise_force`, and `+sep_efuse_preload`
  live in the leaf testlist entry's `args`.
- For every new OCAH SEP test port, decide the fuse-sense mode from the OCAH
  reference **before** writing the testlist entry. If the test's checking depends
  on OTP/eFuse sense data, LC_STATE shadowing, resense, or an eFuse→consumer
  stitch such as LCC/KM, omit `+skip_fuse_sense`. If the OCAH test does not
  explicitly require real fuse sense, the OSS port must use `+skip_fuse_sense`.
  Do not guess from the test name; document the decision in the testlist comment
  or test header when it is non-obvious.
- Hold CPU off: `mpc_reset_run_req = 0`; the no_cpu build uses the `sep_cpu` STUB
  (`shims/cpu/sep_cpu_stub.sv`, target `lsu_stub_all_live`), which is the sole
  driver of the LSU master bus. The stub DRIVES the whole `lsu_axi_req` struct
  from the flat `s_axi_*` ports (`assign` — single driver, NO `force`), and the
  tb reads the response back by name.
- The inbound filter is exercised by the separate external `m_axi_*` master on
  the real `smn_inbound` port (§3) — never by forcing
  `u_inbound_filter.filter_skip_i` (which is driven by `feat_ctrl.sep_debug`).

## 5. Python / PyUVM test conventions
- Before coding a new SEP test or refactoring an existing one, first check
  `cocotb/tests/sep_base_test.py`, `cocotb/seq_lib/`, and `cocotb/env/` for
  reusable helpers. If new logic is broadly reusable, add it to the shared base
  helper or the proper env/seq_lib module instead of duplicating it in one test.
- New cocotb/PyUVM tests inherit from `cocotb/tests/sep_base_test.py` unless
  there is a specific reason not to. Do NOT copy/paste clock/reset/default-drive
  code into each test.
- Use `sep_base_test` helpers for shared system bring-up:
  `bring_up_no_cpu()` for CPU-held-off AXI tests,
  `bring_up_and_wait_fuse_sense()` for eFuse tests, and
  `bring_up_cpu_boot()` for CPU-owned boot flows.
- Real fuse-sense tests stage OTP data with `write_efuse_image(image)` before
  waiting for sense-done. The base wait path backdoor-compares all sensed shadow
  words against that image after every real sense/resense. Keep the AXI/frontdoor
  full-shadow proof in `sep_efuse_image_test`; other tests can rely on the common
  post-sense check plus their scenario-specific frontdoor checkers.
- **Reusability placement rule — put shared code in the right layer (do NOT
  duplicate across tests, and do NOT pile everything into one file):**
  - **Protocol stimulus = a `uvm_sequence`** → `cocotb/seq_lib/`. PARAMETERIZE it
    (constructor kwargs with safe defaults) so different tests vary the policy
    (addresses, lengths, mode) without copy/paste. Co-locate its register-map
    constants in the SAME module — never copy addresses into individual tests.
  - **Test-side orchestration = bring-up / poll-for-X / check-Y / golden-vs-probe
    assert helpers** → methods on `cocotb/tests/sep_base_test.py`, called
    `self.helper()`, alongside `bring_up_*`, `boot_firmware`, `write_efuse_image`,
    `wait_seed_ready`, `wait_km_entropy_handshake`, `check_entropy_alerts_zero`.
    Lazy-import a seq_lib sequence inside the method if it needs one.
  - **Golden models, scoreboards, monitors, agents, config, responder access =
    env plumbing** → `cocotb/env/` (e.g. `sep_*_golden.py`, `sep_*_scoreboard.py`).
  - A concrete test then reads like scenario STEPS — `self.bring_up_*()`,
    `self.start_seq(SomeSeq(...))`, `self.wait_*()`, `self.check_*()` — never raw
    register addresses, polling loops, or copy/pasted bring-up.
- **PyUVM config-object policy.** For tests with programmable policy (modes,
  masks, address ranges, LC states, timing, randomization, matrix points, or
  golden/scoreboard parameters), define one small config object and use it as the
  single source of truth for BOTH DUT programming sequences and golden /
  checker / scoreboard expectations. Log the resolved config values. Do not
  maintain two hand-kept copies of the same policy in a sequence and a checker.
  The entropy flow (`SepEntropyCfg` → ESRC programming + DRBG scoreboard golden)
  is the model. Fixed/simple smoke tests may use constants, and firmware-owned
  tests should keep their policy in firmware rather than duplicate it in Python.
- If two tests need the same staging, polling, responder access, or scoreboard
  pattern, move it to the right layer above BEFORE the second test copies it.
- cocotbext-axi accesses go through the SEP AXI agent. The driver uses
  `init_read()` / `init_write()` events and checks `event.data.resp`; do not add
  direct `AxiMaster.read()` / `AxiMaster.write()` calls in tests.
- **Seeded randomness = `random.Random(self.random_seed())` (REQUIRED; NOT a
  security defect).** DV stimulus MUST come from a per-run seeded PRNG instance so
  a failing regression seed reproduces the exact stimulus — this is the house
  pattern across SEP OSS tests, seq_lib, and env. Create a LOCAL instance
  (`rng = random.Random(seed)`), never the module-global `random.seed()`.
  - **Security-scanner note (cycode "Usage of weak Pseudo-Random Number Generator
    (PRNG)", severity High).** This is a **FALSE POSITIVE** on DV files and is
    **WAIVED**. Its remediation (`secrets` / `os.urandom` / `random.SystemRandom`)
    is cryptographically NON-reproducible and would BREAK seed-based failure
    reproduction — do NOT apply it. Our `random` values are test stimulus
    (addresses, payloads, which fuse bits to burn), never keys/tokens/nonces/
    access-control. Handling: leave the code as-is; if the finding must be cleared
    on a PR, waive it via cycode's own mechanism (a per-PR ignore / dashboard
    dismissal by the security owner), NOT by editing the code.
  - **cycode "Generic Password" on a hex seed constant (e.g. RTL
    `prog_fail_seed = 32'h1bad_f00d`) is also a FALSE POSITIVE** — `0x1badf00d` is
    a placeholder PRNG seed, not a credential. Do NOT change the constant to
    appease the scanner (cosmetic, and it can shift default fail-injection
    behavior); waive it via cycode `#cycode_secret_ignore_here <reason>`
    (this-PR only — prefer over the org-wide `#cycode_secret_false_positive`).

## 6. SV / Verilator conventions
- No project STATUS in DV-infra comments (code/config: `*.sv`, `*.toml`, `*.py`,
  `*.core`). No phase labels (`Phase #1`), `(current)`, progress/roadmap notes.
  Comments describe what the code *does*, timelessly. Status lives in docs
  (`docs/`, `README.md`, this file) or memory — not in infra that outlives it.
  Doc cross-refs (`see docs/SEP_OSS_VERILATOR_JOURNEY.md`) are fine; they're not
  status.
- `tb/tb_top.sv` SV style: 4-space indent, 100-col, `input wire logic`,
  active-low `rst_ni`. Module name `sep_uvm_top`.
- Verilator override shims go under `shims/` by function and are listed in
  `[build].stubs` ahead of the bender filelist so `-Wno-MODDUP` first-def-wins
  selects them. Do NOT blackbox-stub licensed leaf cells — exclude their wrapper
  instead (see §1, `[build].exclude_files`).
- The Verilator target does NOT use `--public-flat-rw`: cocotb only touches
  `sep_uvm_top` ports, and the CPU-LSU splice is SV-side — compiled in, no VPI,
  so no internal-signal access is needed. Keep it off; it balloons the generated
  C++ on this already-large DUT and re-arms the ICO wedge (§12). Only add it if a
  future phase truly needs cocotb to poke an internal net.
- Expect `BLKLOOPINIT` on dynamically-indexed CSR struct-arrays → handled via
  `-Wno-BLKLOOPINIT`. Guard SV covergroups with `` `ifndef VERILATOR ``.

## 7. Verification quality (house rules)
- **NO BACKDOOR ACCESS unless the user explicitly asks for it.** "Backdoor" means
  any read OR write of an internal DUT signal that does not go through a real
  bus/port: SV `force`/`deposit` on internal nets, hierarchical XMR reads of
  internal state, `uvm_hdl_force/read/deposit`, `--public-flat-rw` VPI pokes, etc.
  Drive and observe the DUT through its FRONTDOOR (the CPU-LSU AXI master, the
  external SMN-inbound master, and the DUT's real register/memory apertures). If
  you believe a backdoor is genuinely necessary, STOP and ASK the user first — do
  not add it autonomously.
  - **Accepted backdoor/probe exceptions (signed off, all in `tb/tb_top.sv`).**
    This is the complete list; adding anything here needs explicit user sign-off,
    and a new probe must record its justification + the frontdoor alternative (or
    its absence):
    - **CPU-LSU master splice** — the no_cpu `sep_cpu` STUB drives `lsu_axi_req`
      from the tb (`assign`, single driver — NOT a `force`), and the tb XMR-reads
      the response back. Primary stimulus path; no inbound filter.
    - **ESRC raw-noise force** — the decorrelator `noise_i` input, driven from
      `esrc_noise_ext_i` (deterministic noise the golden also consumes).
    - **`tb_backdoor_mem` memory init (SIGNED OFF 2026-07-18 by yenhenglai, SEP TB
      owner — added with the `sep_wrapper` migration).** The wrapper's real memory
      macros have no runtime init (`MemInitFile("")`), so `tb_backdoor_mem` writes
      DUT-owned macro arrays at t=0 for a valid power-up state + image loads:
      `prim_ram_1p.mem` (SEP SRAM, KM SRAM, OTBN imem/dmem), `prim_rom.mem` (boot
      ROM, KM ROM), and EL2 TCM `ram_16384x39.ram_core` (ICCM/DCCM, with
      de-interleave + Hsiao ECC on `tcm_load_i`). These 3 modules are marked public
      in `sep_public_scope.vlt`. **Justification:** this is memory-INIT, the same
      class as OCAH's TCM load — NOT a `force`, NOT pass-faking, and it writes only
      power-up/image content the RTL would otherwise get from real macros. **No
      frontdoor alternative exists:** the macros expose no init port in a SYNTHESIS
      build, and the boot ROM is the CPU's reset-fetch source, so a CPU-driven load
      is circular. Default fills are the valid idle patterns (ECC-valid zero / KM
      parity / OTBN SECDED) so they cannot mask a functional bug. Public scope is 3
      narrow vars, all outside the hot AXI ready/valid cones, so the Verilator ICO
      fix is preserved. eFuse is NOT in this list — the generic eFuse model
      self-initializes its own storage in RTL.
    - **Observation-only XMR probe ports** (continuous `assign … = u_dut.<net>`):
      `o_cpu_run_ack_o`, `cpu_trace_*`, `dbg_sep_reset_n_o`, `sep_cpu_reset_n_o`,
      `efuse_shadow_probe_o`, `scratch_cold_probe_o`, the KM/OTBN mem req/write
      counters, the ESRC/DRBG/CSRNG/EDN datapath probes for the entropy CHK1–CHK5
      scoreboard, `sep_internal_interrupts_probe_o` (the IP-IRQ aggregate vector
      feeding the VeeR PIC — no frontdoor equivalent, the aggregate has no CSR
      mirror and the PIC is unreachable with the CPU held off), and the
      `axis1_tvalid/tready/tdata` crypto-leg pre-adapter stream (for bit-exact
      per-sink CHK5 routing; no frontdoor equivalent).
    Anything not on this list needs explicit sign-off.
- **Liveness is a first-class checked property — design tests so a deadlock FAILS
  loud, never hangs.** Every accepted request/transaction must terminate (complete
  or error) in bounded time under EVERY legal input/CSR combination, not just the
  documented happy-path sequence. To reveal this bug class: (1) bound every wait —
  no unbounded `while(!done)`; a poll/`wait_*` times out with a descriptive error
  naming which handshake didn't retire (turns a silent sim timeout into an
  attributed failure). (2) Exercise the illegal/concurrent corners of any
  arbiter/mux/shared resource — two requesters at once, both mode-enables set,
  request-during-busy, back-to-back with no teardown, reset mid-transaction,
  sustained backpressure. (3) Do NOT let the test's own protocol discipline hide
  the HW bug: keep an adversarial/negative test that violates the discipline and
  asserts graceful termination. (4) Cross-cover the dangerous concurrent states so
  an untested corner shows as a coverage hole, not a silent pass; where feasible
  add a bounded-response assertion (`req |-> ##[1:N] (done||err)`). A sim-level
  timeout is a candidate deadlock triaged to an FSM/handshake, never "flaky."
- **eFuse program/read arbitration is a liveness trap — always clear
  `EFUSE_PROGRAM_CTRL` after a program.** `program_enable`
  (EFUSE_PROGRAM_CTRL[27]) and `read_enable` (EFUSE_READ_CTRL[28]) are independent
  RW mode bits that share ONE command channel in `efuse_interface_controller`. If
  BOTH are set, the priority mux picks program and starves the read: the read FSM
  waits on a response the mux ties to default, so the read HANGS (stuck, not wrong
  data). Test rule: after `PROGRAM_DONE`, write `EFUSE_PROGRAM_CTRL=0` before any
  read — the "clear-after-program" discipline every SEP/SMC eFuse flow uses.
  Never leave both enables asserted. `program_enable` never reaches the OTP macro
  — it is pure controller arbitration, NOT an OTP requirement. Audit red-flag: a
  pass that only holds because of this discipline masks a real RTL deadlock; flag
  the hang, don't bless the workaround.
- A checker must demonstrably FAIL on a broken DUT — value-agnostic cross-checks
  give false confidence. The smoke asserts a *specific* value, not just "no X".
- **Prefer source-derived expected values over hardcoded literals.** When an
  authoritative machine-readable source exists, import or generate expected values
  from SystemRDL, generated register metadata/headers (`hw/sys/sep/regs/gen/`),
  architecture packages, memory maps, or the test's shared config/golden model.
  Avoid keeping duplicate address/reset constants in sequences and checkers. Never
  derive an expected value from the DUT's observed runtime value or generated RTL
  implementation. Hardcode only when no suitable specification artifact exists or
  when an intentionally independent golden value is required; document its
  authoritative source and why it must remain independent.
- **Severity is binary.** `uvm_error`/test-fail for bugs, `uvm_info` for tolerated.
  **Never `uvm_warning`** — a warning is a verdict nobody owns: it does not fail
  the test, so it protects nothing, and it trains readers to skim past lines that
  later turn out to matter. Being unable to decide between error and info means
  the check is not finished. (Snapshotting warning counts to gate a `[PASS]` line
  is still fine as a backstop against stray warnings from components DV does not
  own — that is defense, not emission.)
- PASS requires positive evidence (parser policy), not exit 0.
- VPLAN / GitHub testcase checker boxes are evidence-backed, not aspirational.
  When creating a testcase issue or VPLAN entry, list the concrete checkers the
  test must prove. After the test runs, mark a checker `[x]` only when the kept
  log shows positive evidence for that exact checker (scoreboard summary, value
  compare, firmware PASS text naming the contract, CSR/status proof, etc.). If a
  checker is implemented but not visible in the log, add positive-evidence logging
  or leave the tracker item in progress. Existing testcase issues need the same
  audit before being marked Done.
- **OSS testcase audit status convention.** "Audit green" for a new OSS SEP
  testcase means ALL of the following are true: the OSS checker set is
  OCAH-aligned or stronger (accepted deltas explicitly documented), a kept log
  proves every listed checker, and both the local VPLAN and the GitHub testcase
  issue have their proven checker boxes marked `[x]`. At that point the GitHub
  Project item should be **In progress**, not Done. Only a kept **Verilator** PASS
  log with the same positive checker evidence upgrades the item to **Done**.
- **Architecture/spec proof source of truth.** When auditing issues, VPLAN checker
  contracts, testcase quality, or any claim that needs spec proof, use the
  repository `.adoc` architecture docs as the golden reference, not only the OCAH
  test source. Primary SEP sources are `hw/sys/sep/doc/index.adoc` and its
  chapters (`introduction`, `overview`, `fabric`, `memory_map`, `cpu`, `crypto`,
  `periphs`, `token_processing`, `security_disable`, `lifecycle_controller`,
  `test_mode`, `threat_model`, `attack_countermeasures`, `port_table`).
  Top-level integration sources are `doc/architecture.adoc` and
  `doc/integration_guide.adoc`. SEP-relevant IP specs include
  `hw/ip/key_manager/doc/`, `hw/ip/efuse/doc/`, `hw/ip/entropy_source/doc/`,
  `hw/ip/drbg/doc/`, `hw/ip/axi_lite_mailbox_unit/`, and the JTAG docs under
  `hw/ip/jtag_*`. Use these docs to justify checker intent, expected datapaths,
  run-mode/fuse-sense decisions, and accepted scope deltas; if the docs and a test
  disagree, stop and call out the discrepancy before updating VPLAN/GitHub status.
- Interrupt/status tests must prove the full status-clear contract, not only that
  an ISR ran or DONE was seen. For every RW1C interrupt/status path under test:
  capture status, write 1 to the asserted RW1C bit(s), then read back and assert
  the cleared bit(s) are 0. **This applies equally to POLLED status (no ISR):** a
  test that polls a DMA/IP `STATUS.done` must still W1C-clear and assert the bits
  read back 0 — do not skip the clear just because there is no interrupt handler.
  If the original OCAH test only checks the flag, close this gap in the OSS port
  instead of copying the weakness.
- Every bounded wait/poll must FAIL-check on timeout. Never `(void)`-discard a
  wait's return or assume completion — a wedged DUT must surface as a test FAIL,
  not a silent pass (e.g. `if (spi_wait_idle(...) != 0) { fail; }`, never
  `(void)spi_wait_idle(...)`).
- **cocotb `TESTS=N PASS=N` is the WRAPPER, not the UVM-sequence verdict.** A UVM
  sequence started in `main_phase` (instead of the base `body()`/`run_phase` hook
  the base test blocks on) can be torn down after boot — the base `run_phase`
  signals sim-end once boot + its no-op `body()` finish — so later sequence steps
  silently never run while the harness still prints PASS. Start sequences in the
  `body()` hook, and **confirm the sequence's OWN completion (its final-step +
  check-count log AND `UVM_ERROR==0`), never just the wrapper's pass line.** A long
  fixed `#(N us)` wait inside a sequence can likewise overrun the sim budget and
  truncate the rest — keep waits bounded to fit the run.
- **A failed backdoor/`uvm_hdl_read` access is UNOBSERVABLE, not "didn't happen".**
  Treat it exactly like X/Z: it must FAIL a negative/"never happened" check, never
  be ignored so a sibling defined sample carries the pass.
- **Coverage-class honesty — label a register check by what it PROVES.** `[LIVE]`
  only if the downstream effect (output port / routing) is actually observed;
  `[LIVE:CONN]` = CSR→output-port connectivity only; `[STUB-CONST]` /
  `[INPUT-REFLECT]` / `[DECODE-ONLY]` for tie-off / reflected-input / unconsumed
  `reg2hw`. A CSR write+readback alone is storage/decode — never `[LIVE]`.
- **Count a failure ONCE**, at the downstream check that observes its effect — a
  `test_fail_count++` in a stimulus helper for a failure the caller's check already
  catches double-counts (benign for pass/fail, but the fail metric lies).
- **Backdoor deposit→read settle: real-time `#(ns)`, not `@(posedge)`** for a
  self-clearing (singlepulse) or CDC-crossing flop — a clock edge races the
  deposit's self-clear/CDC and the deposited value is missed. Clock-ordered
  `@(posedge)` sampling is for observing a DRIVEN signal, not deposit-then-read.
- **Every checker needs a positive log line — including the no-progress path.** A
  firmware checker that only prints on FAIL is not auditable ("absence of a FAIL is
  not evidence"): emit a `CHK-X PASS: <contract>` line on success so the kept log
  proves the box. Beware a short-circuited guard like
  `if (!(st & DONE) || check_words(...)) e++;` — when the first clause is true it
  SKIPS the `check_words()` call that would have logged the diagnostic, so the
  failure increments silently with no STATUS in the log. Log the STATUS on the
  no-DONE path explicitly.

## 8. Process
- Build prerequisites and the `run_dv.py` invocations are in `README.md`. A C++20
  toolchain (g++ ≥10, e.g. `source /opt/rh/gcc-toolset-11/enable`) is required —
  the default RHEL-8 g++ 8.5 fails on `-fcoroutines`.
- **`run_dv.py` is the contract; `sim/run.sh` is personal.** `hw/sys/sep/dv/sim/`
  is gitignored, so anything written down for other people — testlist headers,
  docs, this file, issue text — must express commands in `run_dv.py` terms. A
  site-local `run.sh` may wrap it with host-adaptive convenience (build lock, VCS
  env, job fan-out), and that is where such smarts belong rather than the shared
  runlib (§11) — but no tracked file may depend on it existing.
- **CI runs the `sanity` group on Verilator** (`.github/workflows/sim.yml`). That
  is a no-CPU smoke only: hosted runners have no RISC-V toolchain, so anything
  needing `c_compile` (every `boot`-tagged test) is out of CI scope and its
  Verilator evidence stays a manual pre-merge step.
- **The VeeR EL2 config snapshot is committed collateral, not a build step.**
  `vendor/chipsalliance/Cores-VeeR-EL2/overlay/snapshots/sep/` is TT-generated
  (perl `configs/veer.config`) but tracked in git, and it lives in `overlay/`
  specifically so `bender vendor init` — which wipes and recreates `upstream/`
  only — never destroys it. A fresh clone needs no setup script. If a build fails
  on `` `TEC_RV_ICG ``, the snapshot is missing or clobbered: restore it from git.
  Regenerating it is a deliberate, reviewed change to tracked collateral (it moves
  `el2_param.vh`, `pd_defines.vh`, the PIC map, and the linker script in lockstep
  with the RTL), never a routine fix — and never hand-edit `upstream/`, which must
  stay byte-reproducible from the upstream rev.
- **VCS-develop / Verilator-confirm is the standing strategy.** VCS or Xcelium may
  be used during bring-up/debug iterations, but they are development accelerators
  only. Before a new OSS SEP test is merged to main or marked done, it must run and
  pass in the cocotb/PyUVM + Verilator flow with the OSS-safe filelist and a kept
  Verilator log containing the positive checker evidence.
  - Concrete VCS dev loop: use **cocotb 1.9.2** in a py3.11 venv (cocotb 2.0.1
    breaks the VCS classic-make flow with a `load_entry` error — Verilator's
    Python-runner path is unaffected). The VCS env must be set explicitly by the
    caller (VCS_HOME + SNPSLMD_LICENSE_FILE + `LD_LIBRARY_PATH` with the python-3.9
    lib dir the 32-bit `vcs` driver needs) — `module load synopsys/vcs` does NOT
    apply in a non-interactive shell, so a wrapper script is the practical way to
    carry it. ~3 min/iter vs Verilator ~40 min. Serialise concurrent SEP runs (a
    wrapper-held build lock is the usual mechanism): they share `build/`, so two at
    once invalidate each other's Verilator intermediates. Separate per-tool build
    dirs mean VCS and Verilator never clobber each other's models.
  - **VCS stale-model trap.** If an RTL parameter/source change should affect
    decode or generated constants (for example `sep_pkg::MAILBOX_SIZE` changing
    mailbox stride), do not trust a sim-only VCS failure as a real OSS-vs-RTL
    discrepancy until a clean VCS model rebuild proves it. Symptom: a
    `hdl_compile,sim` stage may print `make: Nothing to be done for 'compile'` and
    reuse old elaboration; runtime then shows impossible old behavior. Clean first,
    then re-run, before filing a gap or rewriting VPLAN/GitHub wording.
  - For a merge that pulls in main, also run the **full OSS SEP regression** before
    push: main's RTL/firmware changes + our shared-DV-file changes must not regress
    any other test, not just the one under development. Prefer the **`no_cpu` /
    `cpu` split** over `all --regress`: the mixed path uses conservative fan-out,
    and the KM-sideload + drbg-multisink tests are the known-flaky-under-`all`-
    concurrency set (heavy `rom_main`); a clean per-class run is the reliable gate.

    ```bash
    python3 tools/dv/run_dv.py --dut sep --items no_cpu --regress \
        --tool verilator --stage flist --stage hdl_compile --stage sim
    python3 tools/dv/run_dv.py --dut sep --items cpu --regress \
        --tool verilator --stage flist --stage hdl_compile --stage sim
    ```
  - Verilator timeout triage: first decide whether the time is checker-essential.
    For small smoke/FW tests, remove or shrink non-checker work (long quiet loops,
    oversize copies, gratuitous stress windows) only if the positive checker still
    proves the same contract. For long security KATs whose runtime is the checker
    payload (real KM firmware + OTBN sideload consume proof), do **not** shrink
    scope just to save wall-clock; give the testlist `timeout_sec` enough Verilator
    headroom and keep the KAT intact. Store such knobs in the testlist/config, not
    hidden environment variables.
  - **Sim time is a design constraint.** When porting a threshold/count/loop from a
    silicon-timed reference, judge whether it gates coverage or only timing; shrink
    timing-only knobs to the smallest value that still proves the mechanism. Anchor
    on the slowest clock (e.g. WDT ticks at `clk_wdt_i`, ~1000x slower than core)
    and document it as a sim-timing knob, not a silent scope change. Shrink only to
    where the mechanism still genuinely exercises the intended path (a bark
    threshold must still increment through the bark path and let firmware reach its
    spin before the NMI fires). `sep_nmi_sanity_test` shrinks WDT `bark_threshold`
    from 100 to 4 ticks — ~25x less sim time, identical bark-to-NMI coverage.
  - **Running the regression fast — three independent parallelism levers (don't
    conflate them):**
    1. **Build C++ compile = `--build-jobs`** (defaults to `--sim-jobs`). The
       cocotb `make -f Vtop.mk` step compiles the ~31 `Vtop_vm_classes_*` top TUs;
       without parallelism a cold build is near-serial (hours instead of ~28 min).
       A cold rebuild is triggered by any `tb_top.sv` edit (all top TUs re-hash).
    2. **Regression test-level = `--sim-jobs N`.** Each test is its own
       single-threaded sim process, so run several across cores. Suite wall-clock
       drops to ~the slowest single test (the KM KAT, ~48 min on Verilator) instead
       of the serial sum. Default is 1 (serial), so pass it explicitly on any
       `--regress` run (a reasonable value is nproc/2, capped around 16).
    3. **Single-sim intra-test = verilator `--threads N` (OPT-IN, default OFF).**
       `--sim-jobs` does NOT speed a lone test. The model must be *built* with
       `--threads` to run multi-core; express this through the EXISTING passthrough
       — `[build.verilator] extra_args = ["--threads", "8"]` — NOT a dedicated
       config key. `--threads` is a verilation flag, so `extra_args` already feeds
       the build fingerprint. There is intentionally NO `sim_threads` key in the
       runlib. The gain is small: **measured 1.21x (697.8s→577.1s, 1-vs-8 threads,
       sim-only cocotb REAL TIME) on the CPU-bound `sep_dma_hash_test`** — ~15%
       parallel efficiency; VeeR/OTBN serial chains partition poorly. **Do NOT
       combine with `--sim-jobs` for regressions:** `--threads` is baked into the
       model so it applies to EVERY sim, and N jobs × M threads oversubscribes the
       cores and makes the suite SLOWER. So: regressions ⇒ no `--threads` +
       `--sim-jobs`; one long test in isolation ⇒ `--threads`, no `--sim-jobs`.
       (Measure sim cost via cocotb REAL TIME, not stage elapsed — the stage
       bundles the build.)
  - The cocotb working dir is the per-test run dir (`item_dir`), not the source
    test dir. `runlib/stages.py` stages the source test-dir `*.hex`/`*.parhex` into
    it so `tb_backdoor_mem`'s sim-t=0 CWD-relative image loads (`sep_boot_rom.hex`,
    `sep_sram.hex`, `km_rom.parhex`) and the eFuse model's `out/sep_efuse.hex` still
    resolve.
  - Run outputs live under `hw/sys/sep/dv/build/runs/`. For a single-test run,
    check `build/runs/<run-id>/<test-name>/logs/<test-name>.log` for kept stdout and
    `build/runs/<run-id>/<test-name>/make/out/` for the simulator working `out/`
    directory (e.g. generated `sep_efuse.hex`). Start log/evidence searches there
    before looking under `sim/` or source directories.
- For multi-step build work: fan out independent pieces to agents and **audit each
  finished task with an independent agent** before relying on it.
- Do **not** create, close, rename, relabel, reparent, assign, or otherwise update
  GitHub issues/projects unless the user explicitly asks for that GitHub action.
  It is OK to read/list GitHub issues for context when asked, but issue/project
  writes require an explicit request in the current conversation.
- SEP OSS DV testcase tracker sync is scoped to the OSS project only:
  `https://github.com/orgs/tenstorrent/projects/335`. Do not update unrelated
  GitHub projects or trackers.
- **GitHub issue bodies are durable testcase contracts, not status ledgers.** Every
  testcase issue body must keep the standard structure: `Description`, `Steps`, and
  `Checkers` as GitHub task-list checkboxes. The prose describes the durable
  contract: scope, mapping, run/fuse mode, scenario, datapath, randomization
  policy, checker requirements, DV infra, accepted deltas. Do NOT put transient
  workflow state in the body (`Current Evidence`, `Audit Status`, `planned only`,
  `Done`, `In progress`, local log snippets, per-run PASS summaries). Project 335
  fields carry workflow status; VPLAN/audit reports carry evidence summaries.
- In GitHub issue prose, do NOT use bare low-number shortcuts such as `#11`, `#15`,
  or `#20` for TOP-20/VPLAN items or prior SEP lessons. GitHub auto-links them to
  unrelated repository issues/PRs. Use the durable rep ID, test name, or plain
  wording such as `TOP-20 item 15` instead.
- Do not paste non-persistent kept-log file paths into GitHub issues, VPLAN
  entries, or tracker status text. Local logs under `build/runs/<run-id>/…` are
  audit inputs, not durable references; summarize the positive evidence and cite
  only the tool + run ID.
- **Never invent placeholder `#NNNN` issue numbers in VPLAN cards/rows.** GitHub
  issues and PRs share one number space, so a guessed number collides with a real,
  unrelated PR/issue. The VPLAN row's durable rep identifier is the source of
  truth; leave the issue field as `GITHUB: TBD (owner to file)` until a real issue
  exists, then backfill.

## 9. Porting an OCAH test (per-test workflow)
Every OSS test ports a *real* OCAH SEP test or an explicitly documented merged set
of OCAH coverage intents (see `docs/SEP_OSS_VPLAN_PHASE1.md`,
`docs/SEP_OSS_VPLAN_PHASE2.md`, `docs/SEP_OSS_VPLAN_PHASE3.md` for the selection +
provenance). During VPLAN/test-selection work, follow
`docs/VPLAN_CREATION_RULES.md` first: build the subsystem-level OSS-vs-OCAH
coverage map before creating tests. The goal is 100% parity with the OCAH
version's CHECKING, or a stronger/frontdoor OSS checker — not just a green run.

0. **Selection/compression gate.** Map the OCAH testcase(s) by coverage intent
   using `COVERED_BY`, `COVERED_STRONGER`, `MERGED_INTO`, `OSS_DELTA_ACCEPTED`, or
   `GAP` from `docs/VPLAN_CREATION_RULES.md`. If an existing OSS representative can
   cover the intent with clear evidence, strengthen that test/checker list instead
   of adding a narrow duplicate. Keep a separate test only for a real run-mode,
   fuse-mode, runtime, debug-isolation, or unique security/negative-coverage
   reason. Record this mapping in the VPLAN detail / tracker before implementation.
1. **Scope the OCAH reference first.** Read the OCAH test + its sequence(s) +
   base-seq checkers + the RTL it targets. Enumerate every checker/assertion/
   covergroup and the exact values it asserts. Decide whether this test truly needs
   real OTP/eFuse sense (§4).
2. **Infra gate — build missing DV components BEFORE the test.** Identify the
   checkers/monitors/golden-models/responders the test needs and that the env
   lacks; build those first (golden models as pure-Python in `env/`, protocol
   checkers as `env/` monitors, stimulus in `seq_lib/`). Reuse existing
   BFMs/responders/helpers before writing new ones (§5). Confirm the DUT datapath
   is actually exercisable on this build.
3. **Port golden models from the RTL/spec, independently** — never hardcode
   observed DUT output (the value-agnostic trap, §7). Prove the golden + each
   checker FAIL on a mutated input with a throwaway local Python harness (no sim),
   then delete the harness.
4. **Write the test in PyUVM style** (§5): inherit `sep_base_test`, reuse bring-up
   helpers, drive AXI through the agent sequence. Run on Verilator to PASS with
   positive evidence. The log must make every VPLAN/GitHub checker auditable; if a
   checker only fails silently through an assertion path, add a `uvm_info` or
   firmware PASS line that names the proven contract. VCS/Xcelium PASS logs can
   speed development, but cannot replace the Verilator PASS log for merge/done.
   - **Randomization is a per-VPLAN decision, taken via a directed-first flow.**
     The VPLAN card's `RANDOMIZATION` label decides whether/how to randomize — see
     the taxonomy in `docs/VPLAN_CREATION_RULES.md`: `RAND-REP` (a `MERGED_INTO` rep
     that collapses an OCAH directed family), `RANDCFG` (a directed rep whose
     contract stays directed but the legal instance is seed-selected), or
     `RAND-NONE` (fully directed, the default). Do NOT silently upgrade a
     `RAND-NONE` rep. For either randomized label the endorsed flow is: write a
     **directed** version first and get it **green** (it pins the datapath,
     addresses, and exact contract cheaply), THEN **upgrade it to the randomized
     version**. When you upgrade, a **config object is the single source of truth**
     for BOTH the DUT programming AND the golden/checker expectations; **walk the
     required discrete coverage cells deterministically** (so a single seed never
     skips a required cell) and randomize only the legal continuous knobs with
     masked values (so they read back exactly); keep the checkers exact/
     value-specific; log the seed + resolved choices. The directed pass is a
     legitimate stepping stone, and the randomized upgrade routinely surfaces RTL
     facts the directed values hid (e.g. an address field's real alignment).
5. **Independent-agent audit for OCAH parity** (§8): a separate agent compares the
   port against the OCAH reference and these house rules, producing a parity table
   (COVERED/PARTIAL/GAP). Close real gaps; **document accepted scope deltas in the
   test header** (do not leave a silently-skipped checker — that is false
   confidence, worse than none). The audit's golden reference is always the
   internal OCAH SEP test/sequence/checkers plus the RTL/spec they target. A port
   is not done until it is 100% aligned with OCAH checking, or stronger. If the OSS
   env intentionally exceeds OCAH (e.g. full RW1C proof where OCAH only checked an
   ISR flag), keep the stronger checker.
6. **Audit VPLAN / tracker checkers before marking done**: compare the durable
   GitHub issue checker contract and VPLAN checker list against the kept log.
   Update checker boxes only when the kept log proves that contract. Leave
   missing/unproven VPLAN evidence unchecked and keep the Project 335 item In
   progress until the test/log is strengthened.
7. **Update docs + memory**: mark the test ported/passing in the active VPLAN only
   after the checker audit passes, and record the outcome in memory.

### Porting lessons
- **The OCAH reference is a moving target.** The OCAH test/seq can change AFTER the
  initial scope read — one port silently lacked a checker its reference had gained
  between scope and parity-claim. Before declaring parity AND again before opening
  the PR, `git log -3` the OCAH test+seq and re-read the body.
- **Don't default to a documented scope-delta when the stronger proof is feasible.**
  If the deferred thing is just effort (not blocked) AND is the test's core
  coverage claim, build it. A documented delta is for the truly-out-of-scope tail,
  not the headline.
- **A new test must be enrolled in BOTH its leaf testlist AND `testlists/all.toml`'s
  "all" group** — the leaf entry alone is silently skipped by an `all` regression.
- **The VPLAN is the single source of truth for which leaf testlist a rep belongs
  to** — do not infer it from the test name or its subsystem group. Read the rep's
  row in the VPLAN (and `*_DETAIL.txt`) for the assigned `toml`; the bucket can
  differ from the subsystem group (e.g. `sep_dma_basic_test` is a DMA test but
  lands in `cpu.toml` because it runs cpu-fw mode; `sep_boot_rom_lsu_read_test` is
  a memory test in cpu mode; `sep_spi_ot_dma_tx_test` lands in `spi.toml`).
  Bucket ⇒ VPLAN, always.
- **Expected randomization is an audit gate, not a nice-to-have.** If a VPLAN card,
  issue, or test name targets `[RAND-REP]` / `[RANDCFG]`, a green directed run or
  one seed-selected point is NOT audit-green. The kept log must prove the config
  object as the single source of truth, the required discrete cells walked
  deterministically in one invocation, and the seed-resolved legal continuous knobs.
- `sep_efuse_lcc_lc_state_stitch_test`: do not replace OTP programming with hex
  rewrite alone. Advance LC_STATE through `EFUSE_PROGRAM_CTRL`, model OTP W1S in
  the OSS responder, perform RMA token matches before gated program steps, resense,
  and check both LC shadow and LCC `FEAT_CTRL` against independent goldens.
- `sep_dma_hash_test`: firmware-self-checking PASS is meaningful only when the
  firmware proves DMA completion/error status, digest equality, copied data, and
  interrupt delivery. Add full RW1C status-clear proof for DMA done/error handling
  before calling interrupt coverage complete.
- `sep_spi_ot_dma_rx_test`: the OCAH test only checks "DMA done + no SPI error" with
  idle MISO (no flash model), leaving received data unchecked. The OSS port preloads
  the flash BFM (`OcahSpiFlash.write_memory`) with a known constant, issues a real
  flash READ (TX opcode+addr with CSAAT, then RX), and value-checks SRAM == pattern
  (use a uniform byte like `0xA5` so the check is RXDATA-packing agnostic), PLUS the
  DMA STATUS RW1C clear even though this path is POLLED (§7). `lsio_trigger`
  (SPI-FIFO → DMA) is internal to `sep` — no tb wiring needed.

### Entropy datapath golden (CHK1–CHK5)
The OCAH C/SV reference models live under `dv/sep/tb/tb_uvm/common/dpi/` in the
internal checkout (`drbg_noise/decor/compress/sha256_cond_dpi.c`,
`drbg_ctr_drbg_pkg.sv`) with the orchestrating scoreboard at
`env/drbg/sep_drbg_scoreboard.sv`. These are ported to pure-Python
`env/sep_*_golden.py` (each stage KAT-self-tested; CTR_DRBG validated against a
NIST CAVP AES-256 no-df vector). **FOLLOW OCAH's method exactly — re-deriving the
flow from RTL alone wastes days.** Specifically:
- **Feedback shift registers: SEED the golden from the live RTL SR, don't infer the
  reset phase.** The decorrelator is a feedback SR (`ff[0]=noise^ff[28]`): the
  difference between two such SRs fed identical noise is a PURE 29-bit rotation
  (`d[0]=d[28]`, noise cancels) — it never decays, so a wrong reset phase leaves a
  rotating diff that matches the sampled byte `ff[28:21]` only while it sits outside
  those bits → INTERMITTENT match (the multi-day trap). And `ff_stage` resets only on
  `rst_ni`; `CTRL.RESET`/`decor_bytes→0` zeroes the SAMPLE not the SR, and
  `decor_bytes` lags the true SR reset by a full divider period, so the reset phase
  is NOT recoverable from `decor_bytes`. FIX: probe the raw `ff_stage` (tb_top
  `esrc_decor_sr_o`, 12x29), and after the SR refills snapshot it and
  `seed_decor_sr()` the golden → exact lockstep. Drive the noise each cycle
  (`feed_noise`) and compare `decor_sr_word()` vs `esrc_decor_bytes_o` on each
  decor-change.
- **Decouple the CHK2..CHK5 chain from the SR divider phase: drive it off the
  per-sample decor-valid strobe** (tb_top `esrc_decor_valid_o`). `CTRL.RESET`
  (`rst_n = rst_ni & ~CTRL.RESET`) soft-resets the WHOLE entropy_source (SR + SHA +
  FIFO + `delay_count`), so restart the chain at `decor→0` and feed ONE
  CHK1-verified `decor` sample into BIW→SHA→seed→DRBG→KM per decor-valid (every
  sample incl. repeated SR-fill zeros — change-detect would miss them and misframe
  the SHA 16:1 block). `STARTUP_CTRL.DELAY_CYCLES` resets to 0, so no BIW words are
  dropped before the SHA.
- **Single source of truth for config.** The golden's parameters (sample_clk_div,
  byte_mask, glen, reseed, sha_whitening, …) MUST be the SAME object that programs
  the DUT registers — never two hand-kept copies.
- **CHK2 ESRC-FIFO output = AXI frontdoor `FIFO_RDATA` read, not a backdoor
  wire-tap** of `entropy_stream_data_o`: the wire-tap drops words when the FIFO is
  full and misses the FIFO churn XOR (`FIFO_CTRL.ENTROPY_CHURN_ENABLE` bit 4; OFF by
  default).
- Noise injection under Verilator: force the decorrelator INPUT port directly
  (matching OCAH `force_noise`), driven from the cocotb `tb_top.esrc_noise_ext_i`
  port on the **core clock** (OCAH paces noise on `core_clk`, not the 3 ns sample
  clock). Multi-mode bias/corr/stuck comes from porting `drbg_noise_dpi.c`.

### KM → OTBN sideload KAT (`sep_km_otbn_sideload_kat_test`)
- **A mem model must pulse `rvalid` ONLY for reads** (`rvalid <= req && !we`).
  `km_sram_interface` treats `rvalid` as `read_complete` and runs the
  descramble+parity check on it against the *previous* read's
  `read_pending_addr_q`, so a spurious post-write `rvalid` mis-descrambles →
  `SRAM_PARITY` unrecoverable fault. INVISIBLE with the scrambler off (smoke
  passes) but fatal once `rom_main` locks the scrambler. The wrapper's real
  `prim_ram_1p_adv` already gates `rvalid = req & ~write`, so this class is closed
  for the current DUT; keep the rule for any future mem model.
- `rom_main` cold-boot recipe (matches the OCAH subsystem tb): build with
  `PROD_BOOT_WIPE=0 PROD_UNREC_WIPE=0`, and power the KM SRAM up to zero+valid-parity
  (`{word_parity(0),0}`), not `'x`.
- OTBN sideload ordering/access: release OTBN from SW reset BEFORE
  `CMD_KEY_TRANSFER` (the wrapper KEY CSRs are in the `otbn` sw-reset domain;
  parked → the KM's wrapper write hangs, no mailbox response), AND wait OTBN
  `STATUS==IDLE` (post-reset secure wipe) before the transfer and before IMEM load.
  OTBN IMEM/DMEM need **32-bit** AXI beats (`size=2`); a default 64-bit beat →
  SLVERR on IMEM.
- KM entropy dedication: `park("otbn","aes","kmac")` BEFORE `bring_up_entropy` so
  the KM owns the EDN stream; otherwise OTBN's post-reset entropy requests starve
  the transfer's DRBG mask reads. `rom_load_key` uses NO DRBG; `rom_transfer_key`
  does (`rand_mask`, 12 words) — the first big consumer after boot, so starvation
  first bites at the transfer (hang, not fault). `SW_RESET_N` reset default is
  **0x1E** (km held, crypto released) — seed the shadow with it and park explicitly.
- CHK5_km bit-exact golden-match is INFEASIBLE for `rom_main` (its firmware-driven
  entropy-pull sequence is not golden-predictable → drift after a few aligned
  words). Use the scoreboard `score_km="observe"` mode: CHK1..CHK4 stay strict and
  CHK5 requires real post-mux KM `tvalid&&tready` beats, without a bit-exact value
  compare. Bit-exact CHK5_km only holds for the controlled `km_rom_entropy.S`
  firmware.
- Prove 2-share-mask non-degeneracy FRONTDOOR (no backdoor): the wrapper KEY CSRs
  are write-only / KM-private, so extend the OTBN keydump program to dump its own
  KEY_S0/S1 WSRs to DMEM, then host-check shares non-trivial/distinct,
  neither==key, `share0^share1==K`. Hand-assembled OTBN `bn.sid`/`addi` are verified
  by `ERR_BITS==0`.

### Build/iteration cost model
The cocotb Verilator model is `VM_TRACE`-specific — switching a run between waved
(`--waves`, VM_TRACE=1) and unwaved forces a full ~15-min model recompile (ccache is
cold across the flip). Keep a stage on one trace setting while iterating. Two
concurrent SEP sims on the shared `build/` also invalidate each other's Verilator
intermediates → repeated full rebuilds; serialise them (a wrapper-held build lock
is the usual mechanism). Re-verilation IS skipped when no Verilog/build-input
changed: the flow calls
`runner.build(always=False)` into a stable build dir, and cocotb's make-level
dependency check reuses the model. Empirically a Python-only `--stage sim` (edit
env/scoreboard, run) reports `rebuild=False` and a ~30 s total run. Only a Verilog
source edit (RTL or `tb_top.sv`, e.g. adding a probe port) triggers the full
~15–20 min re-verilate. So: **probe/port changes are expensive — batch them, add
all probes you'll need in one `tb_top` edit** — but golden/scoreboard/seq Python
iteration is cheap; run freely. (`.toml` run-mode/plusarg changes are also cheap;
build-option changes only take effect on a real rebuild.)

ccache: keep `cache_dir` on `/proj_soc`, NEVER the `/home` quota (~9.4 G). A
`max_size` larger than `/home` silently fills it and breaks the build with "No space
left on device", and the constant eviction pins the hit rate near 0. On `/proj_soc`
the cache persists so the ~1000 unchanged module TUs hit (only top/decor TUs change
per `tb_top` edit). `CCACHE_DISABLE=1` bypasses it for one run.

## 10. CPU firmware-boot & interrupts
- FW-boot tests use `sep_base_test.boot_firmware(sb, itcm_hex, dtcm_hex, rst_vec=…)`:
  it stages the TCM image into the sim CWD, backdoor-loads via `tcm_load_i`, runs
  `bring_up_cpu_boot`, and polls boot observables into a `SepBootScoreboard`
  (PC-advance + fw_done + fw_pass + console banner). Do NOT re-implement
  staging/poll per test (§5).
- The boot scoreboard's expected console banner is `sb.expected_line`. Set it in
  `run_scenario` (run_phase), NOT `build_phase` — the scoreboard's own
  `build_phase` runs after the test's and would reset it to the default. `""` skips
  the banner check.
- Firmware is bare-metal (`fw/`, no libc): `-nostdlib -ffreestanding`. Provide
  `mem*` yourself (`fw/drivers/sep_libc.c`). The common makefile compiles `start.S`
  + the test `.c` + every `fw/drivers/*.c` (`--gc-sections` drops unused). Build
  with an rv32imc GCC; `*.itcm/.dtcm.hex` are gitignored — rebuilt via
  `make -C hw/sys/sep/dv/fw/tests/<name>`.
- VeeR EL2 interrupts (fast_interrupt_redirect): `start.S` sets `meivt` and
  pre-fills the 256-entry vector table (1024-aligned `.intvec` in DCCM) with a dummy
  handler; `pic_register_handler` overrides one entry; C ISRs use
  `__attribute__((interrupt("machine")))`. **PIC source id = `sep_internal_interrupts`
  index + 1** (DMA done [8]→9, error [11]→12; see `hw/sys/sep/rtl/sep.sv`).
  Driver = `fw/drivers/sep_pic.h`.
- KM entropy consumption needs KM firmware, not just a flowing EDN stream. The
  EDN→KM stream `tready` (`km_drbg_sampler`) asserts ONLY on a KM-CPU DRBG `DATA`
  read or an enabled prefetch (`CFG.PREFETCH`, reset 0) — the KM never pulls
  autonomously, so the post-mux `km_entropy tvalid && tready` handshake never fires
  from EDN alone. `CFG.TIMEOUT` resets to 256 cycles, so a blocking `DATA` read must
  write `CFG=0` first or it aborts (SLVERR) before a slow seed arrives. A "KM
  consumes entropy" test therefore releases the KM CPU (`sep_km_release_seq`) AND
  loads a KM ROM image (`+km_rom_hex` in the testlist args) whose firmware reads the
  sampler. Hand-assembled example: `cocotb/tests/km_fw/` (`km_rom_entropy.S` →
  `.parhex`, parity nibble per `tb_backdoor_mem`'s `bd_km_word_parity`).
- A wedged crt0 (boot trap, no banner, very few distinct PCs) classic cause: `la
  <DCCM-symbol>` is linker-relaxed to gp-relative, so **set `gp` BEFORE any DCCM
  `la`** in `start.S` — otherwise the access uses a garbage base.
- Do NOT assume a CPU-internal memory (DCCM/ICCM) is unreachable to fabric masters.
  The Secure DMA reaches DCCM (`0xC004_xxxx`) via the SEP xbar → VeeR EL2 `dma_axi`
  slave → the same wrapper TCM macros the CPU reads, so a faithful SRAM→DCCM
  transfer works. Verify reachability empirically before falling back to a
  less-faithful datapath.
- **Driving an IP interrupt to the CPU via `INTR_TEST` (no real datapath):** the IP
  must be out of sw-reset AND clocked, then write `INTR_ENABLE` then `INTR_TEST`
  (sets `INTR_STATE` → `intr_o` → `sep_internal_interrupts[idx]` → PIC).
  OTBN/AES/HMAC/KMAC are released at cold reset (`SW_RESET_N` reset = `0x1E`, only
  KM bit0 held) and SPACC-clocked by default (`CLOCK_GATE_CTRL` bit 0); CSRNG/EDN
  need the entropy clock ungated (`CLOCK_GATE_CTRL` bit 12); the mailbox has no
  `INTR_TEST` so use a real FIFO push. Source-id map = `sep_internal_interrupts`
  idx + 1 (mailbox[0]→1, CSRNG-cmd-done[21]→22, OTBN-done[27]→28). Clear via the IP
  `INTR_STATE` W1C; the (level) PIC claim completes when the source de-asserts.
- **Secure-DMA multi-chunk is firmware-paced in pure memory mode**: a transfer with
  `CHUNK_DATA_SIZE < TOTAL_DATA_SIZE` does NOT auto-iterate (no LSIO handshake for
  SRAM) — the DMA does ONE chunk per `GO`, raising `STATUS.CHUNK_DONE` (bit 5) and
  dropping BUSY. Firmware must W1C `CHUNK_DONE` and re-`GO` with
  `CONTROL.INITIAL_TRANSFER=0` per chunk until the final chunk raises `DONE`.
  Address modes (`SRC/DST_CONFIG`, INCREMENT[0]/WRAP[1]): FIXED = INC0/WRAP1
  (canonical; INC0/WRAP0 unsupported) = re-read/overwrite in place; INCR = INC1/WRAP0
  (linear); WRAP = INC1/WRAP1 (increment within chunk, wrap to chunk start).
  `CFG_REGWEN` (+0x34) HW auto-locks `0x9` while BUSY; `RANGE_REGWEN` (+0x30) is FW
  rw0c (write `0x9` to lock, one-way until reset); `RANGE_VALID=0` →
  `ERROR_CODE.range_valid_error` (bit 6); invalid opcode 0x4–0xF →
  `ERROR_CODE.opcode_error` (bit 2). Driver: `fw/drivers/sep_dma.h`.
- **Bound every firmware poll.** Cap the poll-iteration count (e.g. `POLL_ITERS`) so
  a transfer that never completes fails ITS OWN checker (returns a STATUS with
  neither DONE nor ERROR) instead of spinning until the whole-run cycle budget is
  exhausted — the latter surfaces as a misleading "no fw_done" wedge and costs a
  multi-minute debug iteration. Size the cap well above a real completion.
- **Exposing a tb-hardwired reset/control input as a controllable port**: an input
  the tb ties to `rst_ni` (e.g. `dbg_rstb_i`, like `wdt_rst_ni_i`) can be brought out
  as its own default-released (`1`) top-level input for an isolation test — add the
  `input wire logic` port, rewire the DUT connection off `rst_ni`, default-drive it
  in `drive_idle_defaults`. This is a `tb_top` edit (full Verilator re-verilate, and
  VCS misses tb_top edits → clear the VCS build dir) AND it changes EVERY test's
  reset sequence, so it OWES a full `no_cpu` + `cpu` regression as the merge gate
  (§8). Reset-observable `==1` (released) checks are X-safe (`rd` resolves X→0 ≠ 1 →
  FAIL); `==0` (asserted) checks are X-permissive — make them non-vacuous with a
  liveness contrast (drive a known reset source, e.g. `wdt_rst_ni_i=0`, and prove the
  SAME observable drops to 0).

## 11. Config is the user interface — the runlib is a thin Flow intermediary
- **Design principle (from the OSS/runlib owner):** every tunable parameter is
  expressed through the config file (`sep_sim_cfg.toml`, e.g. `[build.verilator]
  extra_args`, `[build.options]`, `[targets.*]`). The runlib (`tools/dv/run_dv.py` +
  `tools/dv/runlib/`) is only a thin intermediary that chains the underlying Flow —
  it deliberately does **not** do work behind the user's back. This is the explicit
  contrast with TTEM, which silently does a lot for you. So a setting belongs in the
  config, and we add a code/env knob ONLY when the config genuinely cannot express
  the need (and then prefer extending the config schema over a hidden env var).
- **Consequence for new knobs:** before adding an env var, a new config key, or a
  code path that reads the environment, check whether `extra_args`/options already
  cover it. Worked example (owner-endorsed outcome): multi-threaded Verilator sim
  first shipped as a `VERILATOR_SIM_THREADS` env shim, then a proposed first-class
  `sim_threads` config key. Both were dropped: `--threads` is a Verilator verilation
  flag, so the EXISTING `[build.verilator] extra_args` passthrough already expresses
  it AND feeds the build fingerprint. The env shim was removed and no `sim_threads`
  key exists.
- **Build parallelism follows the same charter (owner's policy):** SEP carries NO
  hardcoded `build_jobs`, so the job count falls back to the invoker's CLI flags,
  keeping the runlib a thin pass-through with no hidden host-adaptive behavior.
  Host-detection / "auto" job-and-thread tuning stays OUT of the shared runlib (it
  would make the build vary with host load and break clone-matches-CI determinism);
  any such smarts live only in the site-local `sim/run.sh`.
- **Shared-runlib changes need a blast-radius note.** `cli.py`/`config.py`/
  `stages.py` are shared with smc/dtp. Gate SEP-only behavior behind "tool is
  Verilator AND `public_scope` is set", keep new flags defaulting to prior behavior,
  and flag any un-gated change (e.g. a `run_subprocess` rewrite, which touches every
  DUT's process launch) for owner sign-off.

## 12. Verilator bring-up & debugging playbook (hard-won)
Full narrative in `docs/SEP_OSS_VERILATOR_JOURNEY.md`; root-cause detail in
`docs/SEP_OSS_VERILATOR_ICO_BLOWUP.md`; perf/benchmark data in
`docs/SEP_OSS_BUILD_MODEL_OPTIMIZATION.md`. Read these before re-debugging a
Verilator hang or "optimizing" the model — most of the dead ends are already mapped.

- **First rule: a Verilator-only hang on this DUT is almost never the RTL.**
  VCS/Xcelium green + Verilator wedged ⇒ suspect the DV toolchain/build first, not
  the design. Twice we were one step from a wrong fix (an AXI-fabric cut/spill RTL
  change, and an over-clever auto-tuner) and both times the right move was to step
  back, get an A/B, and fix the plumbing. Ruled-out-by-A/B dead ends for the classic
  hang: tie-able inputs, clock-gating, and AXI-fabric comb loops — do not re-chase.

- **Symptom → first suspect (Verilator):**
  - **Sim hangs, 0-byte log, one core pinned ~770% CPU, killed at timeout** ⇒
    cocotb's global `--public-flat-rw` (the ICO blow-up). Marking every signal public
    disables the RTL's `split_var` hints ⇒ false AXI ready/valid combinational loops
    can't be split ⇒ a monstrous settle region; a read transaction never converges.
    Confirm via Verilator stats: SCC count + ICO input-region size (≈951 SCCs / 3.2 M
    ICO broken → ≈61 / 160 K scoped; smoke 1800 s-hang → ~130 s PASS). Fix = scoped
    `.vlt` exposing only `sep_uvm_top` via `[build.verilator] public_scope` — NOT an
    RTL change, NOT `--public-flat-rw` (§6).
  - **One specific bus transaction never returns (e.g. an OTP-program write hangs),
    `--waves` makes it disappear, VCS green** ⇒ Verilator DFG opt mis-converging a
    comb loop. Fix = `[build.verilator] extra_args = ["-fno-dfg"]`.
  - **Cold rebuild takes hours, C++ compiling ≈one file at a time** ⇒ lost build
    parallelism (cocotb caps `make -j4`). Fix via `--build-jobs`/`MAKEFLAGS` — §8
    lever 1.

- **"Same sim command" ≠ "same model" — the #1 false lead.** runlib changes patch
  the *build* command (Verilator args, via the cocotb `_build_command` wrapper), not
  the runtime sim invocation. Reverting a runlib change while the sim command stays
  byte-identical silently rebuilds a *different* model. When A/B-ing any runlib/build
  change you MUST force a model rebuild (`rm -rf` the per-tool build dir); a cached
  model masks the effect and sends you chasing ghosts.
- **The scoped `.vlt` is folded into the build fingerprint** (`stages.py` hashes the
  file's text), so editing `sep_public_scope.vlt` DOES auto-trigger a rebuild — no
  manual clean needed. A fail-loud guard also errors if a cocotb upgrade ever leaves
  the runner unpatched. For internal observation under scoped-public, bring the
  signal out as an explicit `tb_top` probe port and rebuild — you can no longer poke
  arbitrary internals from Python (and per §7 you shouldn't).

- **Public-scope is necessary, not overkill — but it has a debuggability cost. Don't
  widen public globally to "get visibility back"; that just re-arms the ICO wedge.
  Use these instead:**
  1. **`--waves fst` is the on-demand full-visibility debug build — NEVER enabled in
     regression.** Run it only on the single test you're debugging; it forces a
     one-off traced rebuild (separate fingerprint from the fast untraced regression
     model). It exposes every signal as a waveform AND (bonus) disables the DFG fold
     — so a DFG-class wedge won't even reproduce under tracing, and that
     non-reproduction is itself the diagnostic ("works with `--waves`, hangs
     without" ⇒ optimizer artifact, not RTL).
  2. **The `.vlt` is granular, not all-or-nothing.** To VPI-observe one internal
     signal, add a NAMED `public_flat_rd -module "<m>" -var "<sig>"` (read-only is
     gentler on optimization than `_rw`), rebuild, debug, remove. Pick signals
     OUTSIDE the hot AXI ready/valid cones so you don't re-trigger the ICO blow-up.
  3. **`split_var` breaks a false loop surgically.** Instead of disabling an
     optimizer model-wide, `split_var -module "<m>" -var "<sig>"` on the offending
     net (named by `-Wwarn-UNOPTFLAT`) forces Verilator to split it. More precise
     than `-fno-dfg` but fragile to RTL churn (names move); keep `-fno-dfg` as the
     safe blunt default.

- **Optimizer wedges are a CLASS, not a one-off — manage them as a standing risk:**
  - `-fno-dfg` neutralizes the WHOLE DFG class model-wide, and disabling an
    optimization can only make logic *more* correct, never less — VCS confirms the
    values — so these workarounds never mask a real bug.
  - The **VCS-vs-Verilator dual-run is the tripwire**: any Verilator-only hang or
    value-mismatch = an optimizer/convergence issue. It caught both the ICO and DFG
    wedges and will catch the next class; never ship a Verilator-only result
    unconfirmed.
  - Periodically `verilator --lint-only -Wwarn-UNOPTFLAT -f <files.f>` (≈2 min, no
    C++ build) to inventory the circular-comb loops (baseline 94 as of 2026-06-29, 69
    of them inside `sep_crypto`) — the candidate wedge sites. If the count jumps
    after a main-merge, investigate the new loops proactively.

- **Optimize the model only on measured evidence — never on a hunch:**
  - **CPU stub is a SIM-time win, not a BUILD-time win** (~1.66x sim; build
    wall-clock flat, ~12% fewer files). VeeR is only ~10% of compiled RTL and is
    flop-heavy; the slow-to-compile cones are the AXI fabric, crypto, and i3c —
    which the stub does not remove.
  - **External-master (SMN-inbound / JTAG-AXIL) gating buys ≈nothing** — the scoped
    `.vlt` already kept those cones out of the hot region. Keep the live-master
    targets because tests functionally need the ports, not for speed.

- **Multi-target regression gotcha:** targets sharing one build dir derived the same
  on-disk filelist path ⇒ last-writer-wins ⇒ the CPU-stub target was silently built
  with the real VeeR (the fast model existed on paper but never ran). Key the
  generated filelist on the *target name* and make `exclude_files` additive
  per-target so each target builds its own source set.

- **Current setup is pressure-tested optimal (multi-agent analysis, 2026-06-29) — do
  NOT change the build/model/opt choices speculatively.** Verdicts: (a) scoped `.vlt`
  is minimal at the granularity that matters (the win is DUT-fabric-private;
  narrowing further is fragile for zero gain). (b) global `-fno-dfg` is the right fix
  — `split_var` is *inapplicable* to the wedge loop (1-bit handshake, nothing to
  split) and would patch 1 of 94 loops. (c) the 2-model set (full-CPU + CPU-stub) is
  optimal — a crypto-stub buys ~0 (build wall-clock is g++-bound, flat across models)
  and i3c is already pruned to zero generated TUs.
- **Optional FUTURE improvements (observability, NOT corrections):** (1) promote the
  UNOPTFLAT lint to a CI tripwire that fails when the loop count rises after a
  main-merge. (2) a periodic `--x-assign unique --x-initial unique` "X-hunt" build
  (NOT in regression) — closes the one false-GREEN direction: Verilator's default
  `--x-assign fast` can mask an X that VCS would catch. Neither is done; neither
  blocks anything.
