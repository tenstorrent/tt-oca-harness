# DV Audit — `sep_km_aes_sideload_kat_test`

**Verdict:** The test itself is sound — every one of its nine checkers can fail on real RTL, and
the AES golden is independent of the design. But the log you pointed me at is not evidence of
anything: that Verilator run never started a simulation, it died looking for a simulator binary
that was not on disk. Judged on that log alone the test is NO-EVIDENCE. Judged on the VCS run of
the same day, which did simulate the current sources end to end, it is CLEAN.

| | |
|---|---|
| Scope | test — `sep_km_aes_sideload_kat_test` |
| Audited | 1 test |
| Enumerated / audited / skipped | 1 / 1 / 0 |
| Blocked | 0 |
| Accepted | 0 |
| Weak | 0 |
| Clean | 1 (against the VCS log of 2026-09-04 02:23 UTC) |
| No evidence | 1 (against the Verilator log named in the request) |
| Policy | `~/.claude-ai/skills/dv_audit/references/dv_policy.md` (no git; sha256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210`) |
| Date | 2026-09-03 |

The two rows are the same test read against two different runs, not two tests.

## What this was measured with

| Input | Status |
|---|---|
| Test source | `cocotb/tests/km/sep_km_aes_sideload_kat_test.py` (263 lines), plus the proof path through `seq_lib/sep_aes_seq.py`, `seq_lib/sep_km_mailbox_seq.py`, `seq_lib/sep_sw_reset_seq.py`, `env/sep_aes_golden.py`, `env/sep_drbg_scoreboard.py`, `tests/sep_base_test.py` |
| Verification plan | `docs/SEP_VPLAN.adoc`, section `sep_km_aes_sideload_kat_test` (line 1589) — claim ladder rung 1 |
| Testlists | `testlists/km.toml:68`; enrolled in `testlists/all.toml` at lines 88 and 195 |
| Simulation logs | named run: `build/runs/20260904_032049__verilator__all/.../logs/sep_km_aes_sideload_kat_test.log` — 20 lines, no simulation. Corroborating run: `build/runs/20260904_020551__vcs__all/sep_km_aes_sideload_kat_test/seed_2090462827/attempt_0/` — full run, `TESTS=1 PASS=1 FAIL=0` |

The missing specification leaves three policy triggers unevaluated on this test: 1.5 (did it
prove the property the claim names, as the spec defines that property), 2.2 (is the golden a
transcription of the design), and 2.8 (is the expectation looser than the specified behavior).
For 2.2 the gap is largely closed by other means: the AES golden is a from-scratch FIPS-197
implementation that self-tests at import against the published Appendix C.1/C.2/C.3 vectors, so
it cannot have been copied from the OpenTitan AES RTL and still pass those vectors. The DRBG
golden was not re-derived here.

## Tests

| Test | Verdict | Note |
|---|---|---|
| `sep_km_aes_sideload_kat_test` (named Verilator run) | NO-EVIDENCE | The run aborted before simulating — the runner looked for a `sep_uvm_top` binary under build fingerprint `1a8d5c70e7ed` that does not exist, while `result.json` records the built artifact as `0f9489eff530`. Zero checkers executed. |
| `sep_km_aes_sideload_kat_test` (VCS run, seed 2090462827) | CLEAN | Verdict lines: `cocotb/tests/km/sep_km_aes_sideload_kat_test.py:219` (`ct_side == golden`) and `:262` (`assert self.drbg_sb.report()`). Claim (VPLAN, rung 1): "The sideload ciphertext equals the independent golden for the known key." All nine checkers logged, and the entropy scoreboard scored 16035/3184/1/46 items across CHK1–CHK4 with zero mismatches. |

### MUST-FIX ledger for the CLEAN row

| Policy class | Result |
|---|---|
| 1.1 fabricated verdict | Excluded. Every logged PASS line sits after its own `assert`, never before it; no value is assigned from its expectation. |
| 1.2 a check that cannot fail | Excluded for CHK-F/CHK-H/CHK-NEG/CHK-RT — each compares a DUT ciphertext against a golden computed by an independent AES implementation from a key the DUT never told the test. See F1 for the one checker where this is close to the line. |
| 1.3 a mismatch that does not fail | Excluded. Every helper on the proof path raises `AssertionError`, including timeouts: `sep_aes_seq.py:128`, `sep_km_mailbox_seq.py:321`, `sep_sw_reset_seq.py:54/63`. No `except: pass`, no mismatch reported at info level. |
| 1.4 nothing was observed | Excluded. The scoreboard enforces a minimum match count per checkpoint and fails on a checkpoint that never fired (`env/sep_drbg_scoreboard.py:1217-1224`); the VCS log shows non-zero counts on every enabled stream, including 24 KM and 56 AES entropy beats. |
| 1.5 the wrong thing proven | Not fully evaluated — no specification. All register addresses come from the generated map by symbol (`sep_reg_meta.sym` / `AES.addr`), so the 1.5 sub-case of a literal resolving to the wrong register is excluded. |
| 1.6 the testbench supplied the answer | Excluded on the key path. The key value is delivered frontdoor over the KM mailbox and never read back through a backdoor; the checked ciphertext comes from `DATA_OUT` over the same AXI. The two shortcuts in the run — the time-0 OTP image write and `+esrc_noise_force` — are covered in the observations below and neither supplies a checked value. |
| 1.7 evidence not from this test at this commit | Excluded for the VCS run: it ran at 2026-09-04 02:23 UTC against build `569ee76b8c80`, and the newest commit touching any proof-path source is `ae75d1960`, 2026-09-03 10:16. The test is in `km.toml` and in two `all.toml` groups, and it was in fact selected by the `all` run. Not excluded for the Verilator run — see F2. |

## Findings

### F1 — The public-key-register readback can only catch a register-map change, not a key leak — OBSERVATION

**Where:** `cocotb/tests/km/sep_km_aes_sideload_kat_test.py:196-210`, reading through
`seq_lib/sep_aes_seq.py:250-269`
**Claim it is judged against:** "After the sideload transfer, frontdoor reads of the AES public
`KEY_SHARE0`/`KEY_SHARE1` registers return zero — the software-unreadability property of a
sideloaded key." (VPLAN, rung 1)
**Why this is only an observation:** `KEY_SHARE0/1` are declared write-only and the generated
register block ties their read data to zero, so `all(w == 0)` holds regardless of whether the
key was delivered, mirrored elsewhere, or never transferred at all. That is a 1.2 shape. It does
not block, for two reasons the policy makes decisive: the check is paired with a live-read
positive control in the same CSR window (`STATUS`, asserted non-zero at line 197, and the VCS log
records `STATUS=0x00000011`), so a dead bus cannot produce the pass; and both the test docstring
and the VPLAN checker text state the limitation in full. Policy §3 puts a documented shortcut
used within its stated scope in OBSERVATION.
**What would strengthen it:** nothing at test level. The property this checker is reaching for —
that the sideloaded key is not readable anywhere in software — needs a different mechanism than
reading registers that are architecturally tied to zero, and belongs in the plan rather than here.

### F2 — The named Verilator run produced no simulation, and its own status machinery caught it — OBSERVATION (infrastructure, not the test)

**Where:** `build/runs/20260904_032049__verilator__all/sep_km_aes_sideload_kat_test/seed_500924786/attempt_0/logs/sep_km_aes_sideload_kat_test.log:20`
**What happened:** `FileNotFoundError: .../build/cocotb/verilator/1a8d5c70e7ed/sep_uvm_top`. The
run script was pointed at build fingerprint `1a8d5c70e7ed`; `result.json` for the same attempt
records the built artifact as `0f9489eff530`. The two disagree, so the simulator binary the
script wanted was never built. `result.json` reports `status=ERROR`, `exit_code=2`, duration 31
seconds, and `results.xml` carries `errors="1"` with no test case result — the run is correctly
reported as an error, not as a pass. The same failure hit this test in the earlier
`20260904_013151__verilator__all` run.
**Why it is here at all:** it is the reason the requested log cannot support any verdict about
the DUT. It is not a defect in the test, and nothing about it inflates a pass.
**What would fix it:** a rerun on Verilator once the build-fingerprint mismatch between the
elaborate step and the per-leaf sim script is resolved.

### F3 — Key-bus isolation is proven by reset state rather than by watching the key buses — OBSERVATION, routed to the plan owner

**Where:** `cocotb/tests/km/sep_km_aes_sideload_kat_test.py:171-187`
**Claim:** "Only the Key Manager and AES are released during the transfer. The reset-control
readback that records this is `SW_RESET_N=0x25` ... the check is a mask over the engine bits
rather than an equality." (VPLAN, rung 1)
**Why this is only an observation:** the test does exactly what its claim says, with a real DUT
readback (`seq_lib/sep_sw_reset_seq.py:56-64`, and the VCS log shows `SW_RESET_N=0x25`), so it is
honest against its claim and there is no testcase finding. The note is about the claim: it was
written to what a `SW_RESET_N` readback can show, which is that OTBN, KMAC and HMAC are in reset,
not that no key material appeared on their key buses. Both the test header and the VPLAN entry
declare this delta from the reference environment's per-engine bus monitor, so it is a declared
narrowing rather than the silent kind policy §4 targets. Worth the plan owner's eye, nothing more.

## What I did not check

- Policy 1.5, 2.2 and 2.8 against a specification — none was located for the KM mailbox command
  encoding, the SEP reset-control field map, or the AES sideload CSR semantics. What the DUT is
  *supposed* to do on `CMD_KEY_TRANSFER` was taken from the VPLAN entry, not from a spec.
- The DRBG/entropy golden in `env/sep_drbg_scoreboard.py` was read only far enough to confirm it
  enforces per-checkpoint minimum counts and fails on mismatch. Whether that golden was derived
  independently of the CSRNG/EDN RTL (policy 2.2) was not evaluated; for an algorithmic golden
  that is a real question and it needs its own read of the model.
- Whether `+esrc_noise_force` is within scope as a stand-in for the analog ring oscillators
  (policy 1.6 / 2.9) was decided on the declaration alone: it is named in the testlist comment,
  the test header, and the base-test docstring, and it has a positive control that asserts the
  forced noise reaches the DUT and toggles (`tests/sep_base_test.py:909-923`). I did not read
  `tb/tb_top.sv:1449-1490` or the shim to confirm the force lands only on the analog boundary.
- The 4 unmatched `CHK1_decor` items in the VCS log (`dut_items=16035 match=16031 mismatch=0`)
  were not chased. Zero mismatches and a satisfied minimum count mean this cannot be masking a
  failure, but I did not establish where those four went.
- No waveform was opened, and nothing was rerun. Per the skill's own rule, an audit that reruns
  the simulation destroys the evidence it came to read.

Budget actually spent: 9 source files read on the proof path, 2 logs opened, 8 shell searches.

## Policy gaps

None. Every judgment above was reachable with a rule the policy states.
