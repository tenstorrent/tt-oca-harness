<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMU OSS Skill-3 Peer-Audit (Advisory)

> **Status:** Advisory findings only — not signoff.  
> **Date:** 2026-07-28  
> **Scope:** OSS SMU DV (`dv/oss/hw/sys/smu/dv`) against `dv/aidv_audit.md`.  
> **Inputs:** `SMU_FEATURE_LIST.md` v0.5, `smu_evidence_map.py`, scoreboard/base test,
> Project #335 leaves under `#2900`/`#2901`/`#2902`.

## Verdict

**Not ready for aidv signoff.** Contract plumbing is now aligned (TOKEN map,
scoreboard aliases, GitHub leaf regeneration pending re-sim proof). Remaining
hard gates are human `[DESIGN-APPROVAL]`, re-sim evidence posting, and three
deferred test sources.

## Findings

| ID | Severity | Finding | Recommendation |
|----|----------|---------|----------------|
| P-01 | High | Designer approval of FEATURE_LIST still pending | Obtain human `[DESIGN-APPROVAL]` against pinned SPEC/VPLAN |
| P-02 | High | Prior leaf `#4027` claimed wrapper ROM/scratch CHKs while DUT cocotb smoke logs `RST_*`/`AXI_*` | Leaf bodies regenerated from `TEST_EVIDENCE`; uncheck until log re-proven |
| P-03 | Med | Same testcase name `smu_smc_smoke_test` on DUT vs wrapper with different TOKENS | Documented in FEATURE_LIST; keep `#4027` = DUT; wrapper boot uses SMC_* tokens |
| P-04 | Med | Three P1 leaves lack `.py` sources (deferred.toml) | Keep Deferred; do not invent green checkboxes |
| P-05 | Med | Wrapper elaboration/boot previously lacked greppable `EVIDENCE:` | Fixed in wrapper elaboration test + boot scoreboards |
| P-06 | Low | TB infrastructure leaves (`#3357`–`#3361`, I3C `#3546/#3547`) are not FEATURE_LIST TOKENS | Track as TB readiness, not IF-* coverage |
| P-07 | Info | `prove_mapped_features()` hard-fails missing mapped TOKENS | Good aidv gate; requires `evidence=` on real expects |

## Coverage sampling (Skill-3 style)

Sampled contracts after map align (must re-grep post re-sim):

| Testcase | Required TOKENS | Prior gap |
|----------|-----------------|-----------|
| `smu_smc_smoke_test` (DUT) | `RST_PRIMARY_SMC_1`, `RST_COLD_STABLE_1`, `AXI_SMOKE_DECERR`, `AXI_GLOBAL_BASE` | Issue claimed ROM/scratch |
| `smc_wdt_timeout_irq_test` | map TOKEN(s) + `CHK-NONVAC` | Format mismatch |
| `smu_wrapper_elaboration_*` | `WRAP_ELAB_OK` / `WRAP_ELAB_SEP_OK` + `CHK-NONVAC` | No EVIDENCE lines |

## Blind spots

1. No independent re-run of full `sep0_all` / wrapper `all` after scoreboard change in this audit pass.
2. FCOV auto-hit in base test is convenience sampling — not a substitute for feature TOKENS.
3. Commercial leaf cross-links (`#3821` etc.) may still describe non-OSS contracts.

## Exit criteria for closing this peer-audit

- [ ] Designer records `[DESIGN-APPROVAL]` on FEATURE_LIST
- [ ] Re-sim posts retain `EVIDENCE:` lines matching leaf CHK contracts
- [ ] Deferred three tests implemented or explicitly waived by DV owner
- [ ] Skill-2 self-audit green on at least one leaf per category (dtp/smc/fabric/wrapper/corner)
