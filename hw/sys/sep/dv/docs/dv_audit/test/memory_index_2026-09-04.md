<!-- SPDX-License-Identifier: Apache-2.0 -->
# DV audit index — SEP `memory` bucket, test scope

**No MUST-FIX in any of the five tests. All five are `NO-EVIDENCE` for one shared
reason: no run artifact in this bucket records a source revision, so policy 1.7
freshness cannot be evaluated for any of them.**

- Scope: test height, fanned out one agent per test · Date: 2026-09-04
- **Enumerated 5 · audited 5 · skipped 0** — declared (`testlists/memory.toml`),
  present on disk, and VPLAN-linked all agree at 5, with no disagreement to report.
- Findings across the bucket: **0 MUST-FIX · 2 GOOD-TO-HAVE · 12 OBSERVATION**
- Logs: run `20260904_065716__vcs__all`, all five PASS.
- Policy: `~/.claude-ai/skills/dv_audit/references/dv_policy.md`
  (not under git; SHA-256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210`)

## Per-test

| Test | Verdict | Findings | Report |
|---|---|---|---|
| `sep_boot_rom_smoke_test` | `NO-EVIDENCE` | 4 OBS | `sep_boot_rom_smoke_test_2026-09-04.md` |
| `sep_sram_smoke_test` | `NO-EVIDENCE` | 1 GTH · 3 OBS | `sep_sram_smoke_test_2026-09-04.md` |
| `sep_sram_datapath_breadth_test` | `NO-EVIDENCE` | 3 OBS | `sep_sram_datapath_breadth_test_2026-09-04.md` |
| `sep_rom_sanity_test` | `NO-EVIDENCE` | 3 OBS | `sep_rom_sanity_test_2026-09-04.md` |
| `sep_boot_rom_lsu_read_test` | `NO-EVIDENCE` | 1 GTH · 3 OBS | `sep_boot_rom_lsu_read_test_2026-09-04.md` |

## Needs a decision

| Test | What a human has to decide |
|---|---|
| all five | **Record the git revision on run artifacts.** Every log and `result.json` here names a build fingerprint (`c07fb8d96992`) and a seed, and no revision. This is the sole reason no test in the bucket reads `CLEAN`, and it is the one gap that cannot be retrofitted — a revision a log never wrote is unrecoverable. Owner: whoever owns `tools/dv/run_dv.py`. |
| `sep_sram_smoke_test` | **GOOD-TO-HAVE, policy 2.6.** The reset-read leg's passing value is 0, so a read that resolved X to zero would pass it. Its escalation trigger (can `RDATA` be X in that window, and how does the VIP resolve it?) was left unevaluated — it needs a waveform. Two exact non-zero readbacks over the same path and the response-channel check make it unlikely, not excluded. |
| `sep_boot_rom_lsu_read_test` | **GOOD-TO-HAVE, policy 2.1.** "Stores to ROM are ignored" is proven by content-unchanged, which a store dropped inside the LSU — or never issued — satisfies identically. Trigger evaluated and does not fire (the read leg reaches the same port). Fix named in the report: assert one write beat with `BRESP == OKAY` on the `lsu_rom_axi` monitor. |

## Shared infrastructure

Audited once in the parent and cited by all five reports, not re-read per test:
`sep_base_test.run_phase` and `poll_boot`, `sep_base_test.rd()`, the AXI register
driver (`seq_lib/sep_axi_reg_driver.py`), and the boot scoreboard
(`env/sep_boot_scoreboard.py`). **No finding against any of them.** The two firmware
tests' verdicts rest on firmware self-report through that scoreboard, so each agent
read the C under `fw/` for itself; both found the firmware's own checks real, with
goldens traceable to the committed ROM image rather than to the design.

## Tooling defects found while auditing (policy §5 — a tool never sets severity)

- `scripts/log_facts.py` reports "no simulation time found" on all five logs; four of
  them carry real timestamps (one ends at 25706 ns, another at 228834 ns) and
  `results.xml` records `sim_time_ns`. The extractor misses this simulator's format.
- `scripts/log_facts.py` reports "claims PASS but an assertion failure is logged" on
  all five; every hit is cocotb's `pytest not found, install it to enable better
  AssertionError messages` line. A false positive on every cocotb log in the tree.

Both are findings against the tool, not against any test.

## What this audit did not do

- **No package verdict.** Test scope produces per-test grades only. The IP-join
  products — helper dispositions as a table, enrollment joins, positive-control
  pairing across tests, log-to-test binding — are height 2b and were not performed.
  These five reports are exactly its input.
- **Completeness is not audited here.** Whether the `memory` bucket's five tests are
  enough for the behaviours the plan claims is a question for the plan and its review.
- Each report carries its own "what I did not check" list; the recurring entries are
  1.7 freshness (above), unevaluated X/Z triggers needing a waveform, and other seeds.
