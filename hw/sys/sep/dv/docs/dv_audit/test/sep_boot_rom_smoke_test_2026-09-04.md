# DV Audit — `sep_boot_rom_smoke_test` (test height)

**CANNOT SIGN OFF (this test) — NO-EVIDENCE.** No MUST-FIX: the verdict is honestly
measured off the core's retired-instruction trace. The only thing in the way is
provenance — neither the log nor `result.json` records a source revision, so the
policy-1.7 freshness judgment cannot be made and the test cannot be called clean.

**1 test · 0 blocked · 0 weak · 0 accepted · 0 clean · 1 no-evidence · 0 skipped**
Policy `references/dv_policy.md` @ SHA-256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210` (no git) · log present, 1 of 1 · 2026-09-04

*This audit asks whether the green result lies. It does not assess whether the plan is
complete — a behaviour with no test is a plan matter, not a finding here.*

## Needs a decision

| Test | | Why |
|---|---|---|
| `sep_boot_rom_smoke_test` | NO-EVIDENCE | The check itself is sound and the log shows it firing on real DUT samples; nothing in the artifacts names the source revision they were built from, so the run cannot be tied to the code audited (F1, shared disposition D6) |

## Claim (ladder rung 1 — VPLAN entry)

`docs/SEP_VPLAN.adoc:820-845`, anchor `[[sep_boot_rom_smoke_test]]`:

> *Objective*: "Proves the CPU instruction fetch unit can fetch and retire instructions out of the boot ROM."
>
> *CHK-ROM-EXEC*: "All four boot-ROM fetch addresses are reached and retired on the core's
> retired-instruction trace. Instruction *content* is not compared here — a ROM returning
> different but sequentially-executable words at the same four addresses would pass; content is
> covered by `sep_boot_rom_lsu_read_test`."

Same objective sentence appears in the summary table at `docs/SEP_VPLAN.adoc:122-125`. The claim
was taken from the plan, not reconstructed from the test body.

## The line that decides pass/fail

`cocotb/tests/cpu/sep_boot_rom_smoke_test.py:63` — `assert not missing, (...)`, where
`missing` (line 62) is the set difference between the four expected ROM addresses (line 61) and
`pcs`, a set accumulated only from DUT probes `dut.cpu_trace_valid_o` / `dut.cpu_trace_addr_o`
(lines 38-40). The `AssertionError` propagates out of `run_scenario()` and fails the run —
shared disposition **D1** (`cocotb/tests/sep_base_test.py:1029-1031`, confirmed: `run_phase`
awaits `run_scenario()` with no `try`).

## Proof path

| File | What of it is on the path |
|---|---|
| `cocotb/tests/cpu/sep_boot_rom_smoke_test.py` | whole file (71 lines) |
| `cocotb/tests/sep_base_test.py` | `run_phase` (1029-1031, D1) · `bring_up_cpu_boot` (408-476) · `_wait_fuse_sense` (229-248) · `rd` (98-115, D5) |
| `tb/tb_top.sv` | `backdoor_image_loads` (1006-1022) — the t=0 `$readmemh` of the boot-ROM image |
| `cocotb/tests/sep_boot_rom.hex` | the 4-instruction program the expected addresses are derived from |
| `hw/top/sep_ip_integration.sv:221-232` | `prim_rom u_sep_boot_rom` — DUT RTL, the thing being fetched from |

No firmware under `fw/` is on this path: the test sets `build_env = False` and does not use
`boot_firmware`, the boot scoreboard (D3), or `poll_boot` (D4). Those dispositions are cited only
to record that they are *not* load-bearing here.

The expected addresses are traceable outside the design: `cocotb/tests/sep_boot_rom.hex` holds
two 64-bit words — `0010809300100093`, `0000006f00108093` — i.e. `addi`, `addi`, `addi`, `j .` at
base+0/4/8/12. That is where `(0, 4, 8, 12)` on line 61 comes from, not from reading the RTL
(policy 2.2 evaluated, does not fire).

## Findings

### F1 — No artifact from this run names a source revision

**OBSERVATION** · `build/runs/20260904_065716__vcs__all/sep_boot_rom_smoke_test/seed_37238489/attempt_0/result.json`
(no `git` field) · log line 7 carries only the build fingerprint path
`build/cocotb/vcs/default/coverage/c07fb8d96992/simv`, and that build directory holds no input
manifest (`cov_build.vdb  csrc  pli.tab  simv  simv.daidir  vc_hdrs.h`).

**Why it matters:** the skill's stated freshness method is to ask whether the log names a
revision or compile identity and whether the proof-path sources at that identity match what was
audited. A fingerprint with no manifest cannot answer the second half, so the policy-1.7
freshness judgment is **not evaluated** — and per the skill's verdict table an unfreshable log
cannot yield `CLEAN`. This is package-wide, not specific to this test: shared disposition **D6**.
Filed as an observation, not a MUST-FIX, and explicitly **not** settled with file timestamps.

**Fix:** have the runner record the git revision (and dirty state) of the source tree into
`result.json` / the log header, next to the existing build fingerprint.

### F2 — `+skip_fuse_sense` is on the bring-up path and the plan rung does not mention it

**OBSERVATION** · `testlists/memory.toml:19` — `args = ["+skip_fuse_sense"]`; consumed at
`cocotb/tests/sep_base_test.py:229-248` (`_wait_fuse_sense`), which the log shows completing at
cycle 1 (log line 82, "SEP fuse sense done at cycle 1").

**Why it is not red:** policy 1.6 lists `skip_fuse_sense` as a tell, and it is a genuine bypass of
a real init step. It becomes 1.6 only if the skipped step supplies the signal the verdict reads or
state the checked mechanism was supposed to produce. The verdict reads `cpu_trace_valid_o` /
`cpu_trace_addr_o`, which fuse sense does not produce, and the bring-up still gates on the DUT's
own `sep_fuse_sense_done_o` rather than a guessed delay. The fact row records `forces 0`, and
there is no `uvm_hdl_force`/deposit anywhere on the path.

**Why it is still worth a line:** the shortcut is declared in the testsuite (testlist args, and
the `_wait_fuse_sense` docstring documents both modes) but the VPLAN entry used as the claim says
only "*Run mode*: `cpu`" — sibling rows in the same table do state `+skip_fuse_sense`
(e.g. `sep_otbn_mem_smoke_test`, `docs/SEP_VPLAN.adoc:135`). A reader of the claim alone would not
know real fuse sense was skipped. Toss-up between 2.9 and OBSERVATION, filed at the lower tier per
the policy, with the escalation trigger evaluated above and not firing.

**Fix:** add `+skip_fuse_sense` to the entry's Run-mode line, as the sibling entries do.

### F3 — `+skip_fuse_sense` ran with no shadow-register preload

**OBSERVATION** · log line 35: "`+skip_fuse_sense` provided, but the required shadow register
preload plusarg (`+sep_shadow_reg_preload=filename`) was NOT found."

So the lifecycle shadow registers hold no programmed image for this run. Nothing on this verdict's
proof path reads them — the retire trace is the only observable — so it does not weaken CHK-ROM-EXEC.
Recorded because the run banner flags it as a missing "required" argument and a later reader of this
log should not have to re-derive that it is harmless here.

### F4 — Docstring calls DUT RTL a "responder"

**OBSERVATION** · `cocotb/tests/cpu/sep_boot_rom_smoke_test.py:4-5` — "the OSS behavioral
boot-ROM responder". The thing fetched from is `prim_rom u_sep_boot_rom`
(`hw/top/sep_ip_integration.sv:221-232`), design RTL inside the DUT hierarchy, backdoor-loaded at
t=0 by `tb/tb_top.sv:1016-1021`. Policy 1.6 explicitly permits a time-0 program-image load, so this
is not a stub on the proof path (2.9 does not fire) — but the wording reads as though a DV model
answers the fetches, which is the opposite of what makes this test meaningful.

**Fix:** call it the boot-ROM macro, and say the image is backdoor-loaded at time 0.

*Not reported:* the `log_facts.py` lead "claims PASS but an assertion failure is logged" resolves
to log line 24, `cocotb.regression  pytest not found, install it to enable better AssertionError
messages` — shared disposition **D7**, a false positive.

## The seven MUST-FIX classes

| Class | | Basis |
|---|---|---|
| 1.1 fabricated verdict | excluded | `pcs` is built only from `dut.cpu_trace_valid_o`/`cpu_trace_addr_o` samples (lines 38-40); the `CHK-ROM-EXEC PASS` token (lines 65-69) is emitted strictly *after* the assert at line 63, on no other path. `expected` (61) is a literal-offset list, never assigned from `pcs`. |
| 1.2 a check that cannot fail | excluded | The assert demands four specific addresses be present in a DUT-sampled set. A dead trace bus, a core held in reset, or a mis-bound probe all yield an empty or short `pcs` and the assert fires. `rd()` resolves X/Z to 0 per bit (D5), which is fail-safe in both directions here: an X `cpu_trace_valid_o` reads as no-sample, and an X `cpu_trace_addr_o` reads as `0x0`, which is not in `expected` (base is `0x10040000`). Policy 2.6 evaluated, does not fire. |
| 1.3 a mismatch that does not fail | excluded | `AssertionError` propagates (D1). The `finally` at line 48 only kills the sampler; it swallows nothing (fact row: swallows 0). The bounded `for _cycle in range(50_000)` (45-47) has no expiry-as-pass: falling out of it lands on the same assert, so a program that never reaches the loop PC fails. |
| 1.4 nothing was observed | excluded | The minimum activity count *is* the check: all four of `expected` must appear, so zero-items cannot pass. Log line 87 shows exactly the four PCs `0x10040000/4/8/c` observed, and line 65 confirms the image actually loaded (`[tb_backdoor_mem] boot ROM image loaded (sep_boot_rom.hex)`) — a missing hex would leave the zero-fill (`tb/tb_top.sv:992`) and fail. |
| 1.5 the wrong thing was proven | excluded | The claim is that the four boot-ROM fetch addresses are reached and retired on the retire trace; the test asserts exactly that, at addresses derived symbolically (`sym("SEP_BOOT_ROM_MEM_BASE_ADDR")`, line 16 — symbolic, so 2.3 does not fire) plus the four instruction offsets in the committed image. Instruction *content* is not compared, and the plan entry itself carves that out and names `sep_boot_rom_lsu_read_test` as its owner — so this is a claim/test match, not a narrowing to hide. |
| 1.6 the TB supplied the answer | excluded | Two candidate shortcuts, both evaluated: the t=0 `$readmemh` boot-ROM image load (`tb/tb_top.sv:1016-1021`), which policy 1.6 explicitly permits as a program-image load and which supplies the *program*, not the retire trace the verdict reads; and `+skip_fuse_sense` (F2), which does not produce the retire trace. No force, deposit, or scoreboard disable on the path (fact row: forces 0). |
| 1.7 evidence not from this test at this commit | **enrollment excluded; freshness NOT EVALUATED** | Enrolled at `testlists/memory.toml:13` (`run_modes = ["cpu"]`) and a group member at `testlists/all.toml:67` and `:155`; the audited log comes from the `20260904_065716__vcs__all` run of that group, so the test really executes. `result.json` reports `status: PASS` with positive evidence from `results.xml` ("1 testcase(s) passed"), not a bare clean exit. Freshness is unresolvable — F1 / D6. |

## Yellow triggers

Evaluated: 2.2 (expected values traced to the committed hex, not the RTL) · 2.3 (address is
symbolic) · 2.5 (seed 37238489 recorded in the log and `result.json`; the test is directed, not
random) · 2.6 (D5, fail-safe here) · 2.7 (the ROM image comes from the sim CWD default filename,
which is the per-attempt `make/` directory — `.../attempt_0/make/sep_boot_rom.hex`, staged from
`sep_sim.core:82` — so no cross-test CWD contamination; sibling ROM tests override with
`+sep_boot_rom_hex`, `testlists/memory.toml:54,71`).

Not applicable: 2.1 (not a deny test) · 2.4 (no bare delay carries a check; the settle waits in
`bring_up_cpu_boot` precede a bounded observation window, and no latency bound is claimed) ·
2.8 (the check is an exact address-set match, not a loose predicate) · 2.9 (no local model or
stub on the path — see F4).

## What I did not check

- **Whether the audited sources are the ones that produced this log.** Unresolvable from the
  artifacts (F1/D6). This is the sole reason the verdict is `NO-EVIDENCE` and not `CLEAN`.
- **Whether `prim_rom` and the ROM interface shim behave correctly.** That is design review, and
  reading the RTL to settle an expected value is the 2.2 defect, not a check for it.
- **Whether the four retired PCs correspond to the *right* instructions.** Deliberately out of
  scope: the plan entry assigns instruction content to `sep_boot_rom_lsu_read_test`.
- **The shared-infrastructure files themselves** (`sep_base_test.py` beyond the proof-path
  functions, `sep_axi_reg_driver.py`, `sep_boot_scoreboard.py`). Cited from the parent's
  dispositions D1-D7; not re-opened.
- **Coverage of the run.** Not this audit's subject.
- **Any waveform.** No run was performed; this audit is read-only.

<details>
<summary>Inputs</summary>

- Test: `cocotb/tests/cpu/sep_boot_rom_smoke_test.py` (71 lines, read whole)
- Claim: `docs/SEP_VPLAN.adoc:820-845` (entry) and `:122-125` (summary row) — extracted, not read whole
- Enrollment: `testlists/memory.toml:12-19`; `testlists/all.toml:67`, `:155`
- Closure: `cocotb/tests/sep_base_test.py` (proof-path functions only), `tb/tb_top.sv:975-1022`,
  `cocotb/tests/sep_boot_rom.hex`, `hw/top/sep_ip_integration.sv:210-232`, `sep_sim.core:82`
- Log: `build/runs/20260904_065716__vcs__all/sep_boot_rom_smoke_test/seed_37238489/attempt_0/logs/sep_boot_rom_smoke_test.log`
  (167 lines) — read via `scripts/log_facts.py` plus one targeted `grep`, never whole
- Verdict record: the sibling `result.json` (`status: PASS`, `exit_code: 0`, seed 37238489,
  build fingerprint `c07fb8d96992`)
- Shared dispositions: parent's `shared_infra_dispositions.md`, D1-D7
- Approval records searched for (policy 1.6 escape): none found beside the test, in the VPLAN
  entry, or in the testlist entry — and none needed, since no 1.6 was filed.

Enumerated 1 / audited 1 / skipped 0.
</details>

<details>
<summary>Policy gaps</summary>

None. Every judgment here mapped onto a rule in `dv_policy.md` §1-§3. One boundary worth flagging
to the policy owner rather than as a gap: F2 sits between §1.6's "a skipped fuse sense" tell and
§2.9's "undeclared shortcut", and was resolved by §1.6's own red criterion (does the skip supply
the checked state) plus the "toss-ups go to the lower tier" rule.
</details>
