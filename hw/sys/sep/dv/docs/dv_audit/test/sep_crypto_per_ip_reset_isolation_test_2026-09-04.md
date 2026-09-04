# DV Audit — `sep_crypto_per_ip_reset_isolation_test`

**CANNOT SIGN OFF** — the plan records this claim as `PROVEN`, but the only run at this revision **FAILS**, and 9 of the entry's 13 checker rows never executed.

**1 test · 1 blocked · 0 weak · 0 accepted · 0 clean · 0 skipped**
Policy `/home/yenhenglai/.claude-ai/skills/dv_audit/references/dv_policy.md` @ sha256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210` · tree `wtmain @ ced27e186` · 1 log · 2026-09-04

*This audit asks whether any green result lies. It does not assess whether the plan is complete — a behaviour with no test is a plan matter, not a finding here.*

## Needs a decision

| Test | | Why |
|---|---|---|
| `sep_crypto_per_ip_reset_isolation_test` | BLOCKED | The plan calls per-IP `SW_RESET_N` isolation proven "includes in-window DECERR"; the only run aborts at exactly that in-window write check (got SLVERR, not DECERR), so nine claimed checkers never ran |

## Findings

### F1 — The plan claims proven; the only run at this revision fails at the check the plan names

**MUST-FIX** (policy 1.7 — the evidence is not from a run that happened as described)
· `docs/SEP_VPLAN.adoc:628` (`Per-IP SW_RESET_N isolation | PROVEN | ... (includes in-window DECERR)`), detail entry `docs/SEP_VPLAN.adoc:2310`
· deciding line: `cocotb/tests/system/sep_crypto_per_ip_reset_isolation_test.py:312`
· log: `.../seed_1447222629/attempt_0/logs/sep_crypto_per_ip_reset_isolation_test.log:2126`
  `AssertionError: in-window HMAC CFG write resp=2 timed_out=False, expected DECERR`
· `result.json` for the same run: `"status": "FAIL"`, `exit_code 1`, `tests: {passing: 0, failing: 1}`, `git.commit ced27e186…` — i.e. the failure is at the audited revision, not a stale artifact.

**Claim (VPLAN detail entry, rung 1 of the ladder):** "Proves the per-IP software reset domains are isolated, using live crypto results rather than a poked status bit: each engine computes a golden-checked value, then one engine is reset and the other's held result must survive bit-exact." (`SEP_VPLAN.adoc:2318`)

**Why the record is false:** the DUT returns SLVERR (`resp=2`) rather than DECERR for the in-window HMAC `CFG` write, and the test's own assert — correctly strict — stops the scenario there. Everything after line 312 never executed: `CHK-ISOLATE-SIBLING`, `CHK-ISOLATE-REOPEN`, `CHK-ISOLATE-RESET-DEFAULT`, `CHK-KMAC-SELF`, `CHK-KMAC-NEIGHBOR`, `CHK-OTBN`, the final `SW_RESET_N` default readback, the `drbg_sb.report()` beat floor, and `CHK-TRNG-NEIGHBORS`. The log carries only the first six `CHK-` lines (`CHK-NONVAC`, `CHK-SELF-RESET`, `CHK-NEIGHBOR-SURVIVES`, `CHK-REVERSE`, `CHK-ISOLATE-PRE`, `CHK-ISOLATE-LANDED`, `CHK-ISOLATE-DECERR`), so the plan's checker table describes work that did not happen.

**Fix (owner's choice, both real):** either the RTL/plan disagreement over SLVERR-vs-DECERR on a write into a held reset domain is resolved and a green run at this revision is recorded, or the summary row stops saying `PROVEN` until one exists. Do not convert the assert to `!= OKAY` — the plan row names DECERR, so a looser check would be policy 1.5.

### F2 — The shared expected-error path logs a SLVERR probe as "as expected"

**OBSERVATION** · `cocotb/env/sep_scoreboard.py:60` (log line 2118: `expected-error write @ 0x10911010 returned resp=2 (as expected)`), reached via `expect_error=True` in `seq_lib/sep_axi_access_seq.py:47-52`
The tolerance is response-code agnostic: any non-OKAY beat is "as expected". Here the test's own assert is exact, so nothing is masked — but a sibling test that checks only `resp_ok`/`!= OKAY` would inherit a check that cannot distinguish SLVERR from DECERR, and the log line reads as confirmation of a contract that was in fact violated eight lines later. Also `arm_expected_decerr(1)` was armed for a beat that arrived as SLVERR, so the DECERR credit was left unconsumed.

### F3 — A `CHK-NONVAC` log line asserts a property no live check evaluates

**OBSERVATION** · `sep_crypto_per_ip_reset_isolation_test.py:215-226`
The message says the held results are "real golden results (!= reset 0)" while no `!= 0` comparison exists; the code comment declares this deliberately, and the load-bearing evidence (golden equality against `hashlib`/FIPS-197, then a second independent DUT re-read) is genuine, so nothing is vacuous. The log wording still overstates what ran.

## Seven MUST-FIX classes — ledger

| | Result |
|---|---|
| 1.1 fabricated verdict | excluded — every verdict is a Python `assert` over a value returned by a frontdoor AXI read (`sep_hmac_seq.py:194-197`, `sep_aes_seq.py:293-297`, `sep_crypto_reset_iso_seq.py:75-92`) |
| 1.2 check that cannot fail | excluded — it did fail, at line 312; goldens are `hashlib.sha256` and the FIPS-197 self-tested `env/sep_aes_golden`, independent of the DUT |
| 1.3 mismatch that does not fail | excluded — no `try/except` on the proof path (`swallows 0`); every bounded wait raises on expiry (`sep_aes_seq.py:130`, `sep_otbn_seq.py:101,105`) |
| 1.4 nothing observed | excluded — 741 completed waits, real digests/ciphertexts in the log (`HMAC[0]=0xc2fc0170`, `AES[0]=0x0f8886be`); the deny leg (DECERR read) has a live positive control in the same test (`CHK-ISOLATE-PRE` OKAY + golden at the same address) |
| 1.5 wrong thing proven | excluded for the executed part — steps match the claim's wording, including the deliberate inequality form of `CHK-SELF-RESET`, which the plan row itself states (`SEP_VPLAN.adoc` CHK-SELF-RESET) |
| 1.6 testbench supplied the answer | excluded — 8 forces in the closure, none intersecting a checked signal (`test_facts.py`: "forces 8 (checked too: none)"). `+skip_fuse_sense` and `+esrc_noise_force` are declared in both the test header and the VPLAN run-mode line, and neither supplies reset-domain state; the only backdoor in the log is the time-0 boot-ROM image load |
| 1.7 evidence not from this run/commit | **F1 — MUST-FIX** |

Enrollment is sound: `testlists/system.toml:118`, and the test is a member of the scheduled groups at `testlists/all.toml:94` and `:191`.

## What I did not check

- **2.4 fixed-delay triggers** — the `ClockCycles(…, 40)` settle windows after each reset pulse were not evaluated against a latency claim; the plan makes no latency claim, so the trigger cannot fire, but I did not confirm the 40-cycle value was not tuned upward.
- **Whether SLVERR or DECERR is the correct SEP response** for a write into a held reset domain. That is a spec question; a design specification is deliberately not an audit input, and either side of it leaves F1 standing (a plan row that names DECERR against a DUT that answers SLVERR).
- **The `drbg_sb.report()` beat floor and `check_entropy_alerts_zero()`** — never reached in this run, so no evidence either way.
- **KMAC/OTBN/TRNG legs** — source read, but no executed evidence; not graded.
- Log freshness beyond `result.json`: the log itself records no build identity (per `log_facts.py`); the run manifest alongside it does (`git.commit ced27e186…`, build fingerprint `a8e2c01f96b3`), and that is what I bound to.

<details>
<summary>Inputs</summary>

- Test: `hw/sys/sep/dv/cocotb/tests/system/sep_crypto_per_ip_reset_isolation_test.py` (wtmain @ `ced27e186`)
- Closure (30 files, partial — `start_seq`/`start_ext_seq` unresolved): `sep_base_test.py`, `seq_lib/sep_crypto_reset_iso_seq.py`, `seq_lib/sep_axi_access_seq.py`, `seq_lib/sep_axi_reg_driver.py`, `seq_lib/sep_hmac_seq.py`, `seq_lib/sep_aes_seq.py`, `seq_lib/sep_kmac_seq.py`, `seq_lib/sep_otbn_seq.py`, `seq_lib/sep_sw_reset_seq.py`, `env/sep_aes_golden.py`, `env/sep_kmac_golden.py`, `env/sep_axi_monitor.py`, `env/sep_scoreboard.py`
- Plan: `hw/sys/sep/dv/docs/SEP_VPLAN.adoc` — detail entry :2310, checker table :2334-2372, summary rows :278 and :628
- Testlist: `testlists/system.toml:118`; groups `testlists/all.toml:94`, `:191`
- Log (the only one): `hw/sys/sep/dv/build/runs/20260903_023408__verilator__sep_crypto_per_ip_reset_isolation_test/sep_crypto_per_ip_reset_isolation_test/seed_1447222629/attempt_0/logs/sep_crypto_per_ip_reset_isolation_test.log` — 2137 lines, FAIL claimed, `assert_fail=2`, seed 1447222629
- Approval/exception records searched for beside the test, in the plan entry, and across `docs/`: none found
- Enumerated 1 / audited 1 / skipped 0
</details>
