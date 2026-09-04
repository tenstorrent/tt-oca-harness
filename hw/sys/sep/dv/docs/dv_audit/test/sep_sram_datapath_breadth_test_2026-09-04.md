# DV Audit — `sep_sram_datapath_breadth_test` (test height)

**CANNOT SIGN OFF (this test alone)** — no MUST-FIX and no GOOD-TO-HAVE, but no artifact in this
run records a source revision, so the policy-1.7 freshness judgment cannot be made: `NO-EVIDENCE`,
not `CLEAN`.

**1 test · 0 blocked · 0 weak · 0 accepted · 0 clean · 1 no-evidence · 0 skipped**
Policy `references/dv_policy.md` @ SHA-256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210` (no git) · log present · 2026-09-04

*This audit asks whether any green result lies. It does not assess whether the plan is complete —
a behaviour with no test is a plan matter, not a finding here.*

## Needs a decision

| Test | | Why |
|---|---|---|
| `sep_sram_datapath_breadth_test` | NO-EVIDENCE | The five checks are real, executed, and could fail on a broken memory; the run's log and `result.json` carry a build fingerprint but no git revision, so nothing ties this green to the sources audited |

The verdict is about provenance of the artifacts, not about the test's proof. On source review the
test is honest: the deciding line is `cocotb/tests/sram/sep_sram_datapath_breadth_test.py:83`
(`assert rb == exp`), one of ten bare `assert`s whose `AssertionError` fails the run
(disposition **D1**, `cocotb/tests/sep_base_test.py:1029-1031`).

## Claim (ladder rung 1 — VPLAN entry)

`docs/SEP_VPLAN.adoc:3057` `[[sep_sram_datapath_breadth_test]]`, *Objective*:

> "SRAM strobe, pattern, sequential, and partial-write breadth on the 64-bit port."

with five checker contracts on the same entry (CHK-WSTRB, CHK-PATTERN, CHK-SEQ, CHK-BOUNDARY,
CHK-NONVAC). The claim was taken from the plan, not reconstructed from the test body.

## Shared code cited, not re-opened

| Shared | Disposition |
|---|---|
| `cocotb/tests/sep_base_test.py` `run_phase` | **D1** — an `AssertionError` on the proof path fails the run. My verdict depends on this and it is sound. |
| `cocotb/env/sep_axi_agent.py` driver | not in the parent's disposition set; read narrowly here (see below) |
| no source revision in any log in this bucket | **D6** — freshness `not evaluated`; reported below as O1, not as a MUST-FIX |
| `log_facts.py` "assertion failure logged" | **D7** — false positive (`pytest not found` banner at log line 24). Not reported. |

## Findings

Nothing at MUST-FIX or GOOD-TO-HAVE. Three OBSERVATIONs, none blocking.

### O1 — No artifact records the source revision

**OBSERVATION** (policy 1.7, freshness `not evaluated` per the skill's stated method) ·
`build/runs/20260904_065716__vcs__all/.../result.json` carries
`coverage.build_fingerprint = c07fb8d96992` and `random_seed = 1985438408`, and the log's line 7
records the `simv` path and plusargs — but no git revision anywhere.
**Consequence:** the log cannot be bound to the proof-path sources as audited, which is what holds
this test at `NO-EVIDENCE`. Timestamps were deliberately not used to settle it.
**Fix:** upstream, in the runner — stamp the git revision into `result.json` and the log header.

### O2 — `log_facts.py` reports "no simulation time found" on a log that has it

**OBSERVATION** (tooling, policy §5) · the log is timestamped throughout and ends at
`25706.00 ns` (`results/results.xml`, `sim_time_ns="25706.000001"`). The tool's simulation-time
extractor does not match this cocotb format, so its loudest freshness-adjacent lead is spurious
here. **Fix:** the tool, not the auditor.

### O3 — Region offsets are bare literal ranges

**OBSERVATION** (not policy 2.3) · `cocotb/seq_lib/sep_sram_breadth_seq.py:88,97,104,108` pick
offsets in literal windows (`0x1000`–`0x5000`). These are offsets *within* an aperture whose base
and size come from the generated map by symbol (`sym("SEP_SRAM_MEM_BASE_ADDR")` / `_SIZE`,
lines 37-38), and the boundary pair is computed as `base` and `base + size - 8` (line 100), which
matches the VPLAN's `0x1003fff8`. No literal stands in for a register address, so 2.3 does not
apply. The other 19 bare literals the fact row counted are data patterns and bit masks.

## The seven MUST-FIX classes

| Class | Result | Basis |
|---|---|---|
| 1.1 fabricated verdict | **excluded** | Every `[PASS]`-shaped log line sits *after* its `assert`s in the same coroutine (`:87`, `:101`, `:117`, `:132`, `:162`), and the summary line `:65` after all five sub-checks returned. No verdict is assigned; no compare's actual side is written before the compare. The fact row's "success message away from a compare" is the `:65` summary, reachable only if all ten asserts passed. |
| 1.2 a check that cannot fail | **excluded** | Judged deliberately, because 5 of 7 compares take the expected side from a value this test wrote. For a memory, write-then-read-back *is* the behaviour claimed, and each compare can fail on a broken device: a stuck, aliasing, or lane-dropping datapath returns something other than the written word. CHK-WSTRB (`:83`) is stronger still — the golden is `apply_wstrb` (`sep_sram_breadth_seq.py:159-168`), a byte-lane model written independently of the DUT, so a strobe-ignoring memory that overwrites neighbour lanes mismatches against a random non-zero `wstrb_init`. CHK-SEQ (`:131`) compares each address against its own distinct value (`seq_seed + 17*i`), so address aliasing fails. CHK-NONVAC (`:153`,`:157`) requires two addresses to hold complementary values, which no constant can satisfy. **This is not a 1.2 and not a 2.2:** the expected side is not transcribed from RTL and not the same code path that drove the DUT. |
| 1.3 a mismatch that does not fail | **excluded** | All ten verdicts are bare `assert` statements; no `try`/`except` on the proof path (grep: zero in either closure file), and none in `run_phase` (D1). `PYTHONOPTIMIZE` is not set in the run's `env/sim.env`, so the asserts are live. Access errors also fail: `SepSramBreadth.write`/`read` raise on `not seq.resp_ok` (`sep_sram_breadth_seq.py:144-145,156`), and `resp_ok` defaults `False` / fail-closed with `allow_timeout` left `False`, so a wedged access raises instead of passing. |
| 1.4 nothing was observed | **excluded** | Positively reconciled against the stimulus. The config asserts its own floor: 36 contiguous WSTRB specs or `RuntimeError` (`sep_sram_breadth_seq.py:82-86`); 6 required patterns always present (`:42-49`); `seq_words` in `[4,9)` (`:103`). The log confirms every loop ran with the counts the config declared — `wstrb_masks=36`, `patterns=9`, `seq_words=5` (log line 193) and the matching PASS lines at 820/911/932/983/1004. AXI transaction counts reconcile exactly: 90 writes / 54 reads observed in the log against 90/54 predicted from the config (72+9+2+5+2 and 36+9+2+5+2). Nothing here can pass on zero items. |
| 1.5 the wrong thing proven | **excluded** | Each VPLAN checker contract maps to a coroutine that performs it: CHK-WSTRB→`_chk_wstrb`, CHK-PATTERN→`_chk_pattern`, CHK-SEQ→`_chk_seq`, CHK-BOUNDARY→`_chk_boundary`, CHK-NONVAC→`_chk_nonvac`. The boundary extent matches the plan's cited `0x10000000`/`0x1003fff8` and is symbol-derived. The plan itself scopes the deferred cells (non-contiguous strobes, one-past-top decode, which belongs to `sep_axi_map_refuse_test`), so the test is not proving a narrower or different property than its claim. Note for the plan owner, unclassified: the objective's phrase "partial-write breadth" is covered by CHK-WSTRB; there is no partial *read* check, and the plan does not claim one. |
| 1.6 the testbench supplied the answer | **excluded** | Forces on the proof path: zero (fact row `forces 0`). The run's shortcuts do not supply checked state — `+skip_fuse_sense` (log line 198) skips OTP sense, which the VPLAN entry declares as the run mode and which is not the checked mechanism (the SRAM is reached over the xbar SRAM port, no OTP read); the `lsu_stub_all_live` LSU VIP force-splice (log line 229) is the declared *stimulus master* into the DUT's own AXI port, i.e. the frontdoor for this run mode, not a deposit of a read-back value; `tb_backdoor_mem` boot-ROM preload (line 230) is a time-0 image load away from this proof path; the four `Unable to create backdoor_*` GPI warnings (lines 36-42) are unused capabilities, not applied backdoors. Every value compared came back through a real AXI read (`sep_axi_agent.py:159-171`). |
| 1.7 evidence not from this test at this commit | **partially excluded; freshness not evaluated** | Enrolled and scheduled: `testlists/memory.toml:37` and two groups in `testlists/all.toml` (lines 112, 215). The log is per-test, per-seed, per-attempt — not a shared or overwritten path — and its own content names this test and this seed (`results/results.xml`, `random_seed=1985438408`, `PASS=1 FAIL=0 SKIP=0`, log line 1015). What cannot be settled is the revision: see O1 / D6. |

## What I did not check

- **Policy 1.7 freshness** — no revision in any artifact (O1). This is the reason for the verdict.
- **Whether the DUT's unselected write-data lanes actually carry zero**, which is the mechanism the
  VPLAN's CHK-WSTRB sentence offers for why a strobe-ignoring memory would fail. Settling it needs
  the RTL or the VIP's data-lane behaviour; it does not change the finding, because the compare can
  fail on other broken behaviours regardless.
- **Policy 2.6 (X/Z blindness)** — not evaluated for these compares. `rd()` (disposition D5) is not
  on this proof path; read data arrives via `int.from_bytes` on the VIP's bytes
  (`sep_axi_agent.py:164-166`), and how that resolves an X beat was not traced into cocotbext-axi.
  Left as a trigger, not filed: the passing branch here is equality with a random non-zero pattern,
  so an X resolved either way still mismatches for almost every seed.
- **Policy 2.4** — no bare settling delay exists on the proof path (every access awaits a sequence
  to completion), so the trigger was moot rather than skipped.
- **Whether the seed replays** — asserted from `SepSeededRng` being SHA-256 counter mode and the
  seed coming from `RANDOM_SEED` (`sep_base_test.py:80-82`); not demonstrated by a re-run, since
  this audit does not run simulations.
- **Only one seed's log** was reconciled. Other seeds were not examined.

---

<details>
<summary>Inputs</summary>

- Test: `hw/sys/sep/dv/cocotb/tests/sram/sep_sram_datapath_breadth_test.py` (167 lines, read whole)
- Closure: `cocotb/seq_lib/sep_sram_breadth_seq.py` (read whole);
  `cocotb/seq_lib/sep_axi_access_seq.py` (read whole);
  `cocotb/env/sep_axi_agent.py:55-215` (item fields, driver, `_apply_result`);
  `cocotb/tests/sep_base_test.py:80-82, 354-386, 687-689` (seed, bring-up, `start_seq`).
  The fact row's "closure incomplete (could not find `start_seq`)" is resolved: `start_seq` is
  `sep_base_test.py:687`, which starts the sequence on `env.axi_agent.sequencer`.
- Claim: `docs/SEP_VPLAN.adoc:3057-3086` (entry), `:421` (bucket row), `:552` (PROVEN row)
- Enrollment: `testlists/memory.toml:37`, `testlists/all.toml:112,215`
- Log/result: `build/runs/20260904_065716__vcs__all/sep_sram_datapath_breadth_test/seed_1985438408/attempt_0/`
  — via `log_facts.py` plus targeted greps; never read whole
- Approval records: none looked for beyond the plan entry and the test — none needed, no MUST-FIX filed
- Shared dispositions cited: D1, D5 (as a non-dependency), D6, D7

Enumerated 1 / audited 1 / skipped 0.

</details>

<details>
<summary>Policy gaps</summary>

None. One judgment came close: the policy gives no explicit rule for "the expected side is a value
this test wrote" when the device under test *is* a memory, so 1.2's "a golden taken from the same
testbench variable that programmed the DUT" reads as a hit on its face. The one question in §1
("does a PASS assert something never demonstrated?") settles it — a read-back compare on a memory
demonstrates storage and lane behaviour and fails on a broken device — but the policy owner may
want that carve-out written down, since a write/read-back pair is the normal shape of every memory
test and every auditor will meet it.

</details>
