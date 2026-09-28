# The #1710 evidence gate and the `rom_fw` CHK- convention

**Filed as issue #1780.** This file is the working detail behind it.

For a conversation with **Yenheng Lai**, author of `e6d9a05f1`
*"dv/sep: Grade the sep_cpu_ctrl hole, make a leaf earn its pass, and fix the
signoff docs (#1710)"* (2026-09-11, now on `main`).

Untracked, so it does not land with the SEP ROM PR.

## One paragraph

#1710 added an evidence gate to `sep_base_test`: a leaf that emits no
`CHK-<ID> PASS` record of its own now fails, because a clean exit that grades
nothing should not read as a pass. The reasoning is right and I am not arguing
against it. The problem is a logging-convention mismatch: the counter's regex
requires the literal token `PASS` or `OK` after the ID, and the `rom_fw` leaves
write `CHK-<ID>: <detail>` with a colon and no token. Those leaves therefore
count zero records of their own and fail the gate's floor. This is **not** caused
by the SEP ROM branch — `main` has the same 68 `rom_fw` leaves with the same
convention. Nobody has hit it because SEP's CI gate runs exactly one test, and
that test is on the gate's exemption list.

## The mechanism

`sep_base_test.py`:

```python
_CHK = re.compile(r"\b(CHK-[A-Z0-9_-]+)\b\s*(?:\([^)]*\)\s*)?(PASS|OK)\b")
```

and the floor:

```python
if not own and self.get_type_name() not in _EvidenceFilter.NO_OWN_EVIDENCE:
    problems.append("no CHK-* PASS record of its own -- ...")
```

`rom_fw` leaves log like this — a colon, no `PASS`/`OK`:

```
CHK-STIMULUS-BL1-SIZE: %s BL1 length %d -> 0, ...
CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, ...
```

so the regex matches none of them, `own` is 0, and the floor fires. The floor is
unconditional — `min_evidence` and `required_evidence` are the opt-in tighteners,
but this one applies to every leaf not named in `NO_OWN_EVIDENCE`.

Worth noting: #1710's own commit message anticipates this class of problem while
explaining why `min_evidence` defaults to 0 —

> `rom_fw` leaves report a passing check as `CHK-UNARMED:` with no PASS token and
> would be rejected for a logging convention

— so the interaction was seen for the opt-in floor, but the unconditional floor
fires regardless.

## Evidence that it bites

Four `rom_fw` tests were run on a merge of this branch with `main`
(`20260911_220304__vcs__multi`, 4.25 h). All four completed. Three reached the
gate and all three failed it:

```
EVIDENCE FAIL sep_otbn_rsa_verify_failure_test: no CHK-* PASS record of its own
EVIDENCE FAIL sep_bl1_size_invalid_test:        no CHK-* PASS record of its own
EVIDENCE FAIL sep_firmware_primary_invalid_signature_test: (same)
```

with `EVIDENCE_SUMMARY ... observed=1 own=0`. The one `observed` record is
`CHK-OTP-JTAG2AXI-UNGATED PASS`, which the base class emits and which `BASE_IDS`
excludes from `own` by design. Those same logs contain 12-19 distinct `CHK-` IDs
in the colon form, so the checks did run — they are simply invisible to the
counter. (The fourth, `sep_bl1_entry_invalid_test`, died earlier on an unrelated
issue and never reached the gate.)

## Why CI is green

SEP's CI gate is `--items smoke`, and that group is a single test:

```toml
[[groups]]
name = "smoke"
tests = ["sep_axi_smoke_test"]
```

`sep_axi_smoke_test` is in `NO_OWN_EVIDENCE` ("sequence-level compares plus AXI
scoreboard check_phase"), so it is exempt and CI passes. The `all` group — 94
tests, `includes` `rom_fw.toml` — is nightly/manual, and the `rom_fw` group takes
about 14 h at `--sim-jobs 6`, so it is not something a PR run exercises.

## Scope

Counted by static grep over `hw/sys/sep/dv/cocotb/tests/**`, by whether a leaf's
FILE contains any `CHK-<ID> PASS|OK` form:

| test dir | leaves | file emits PASS-form | would fail |
|---|---|---|---|
| rom_fw | 70 | 2 | **68** |
| cpu | 16 | 7 | 9 |
| system | 26 | 20 | 6 |
| crypto | 11 | 9 | 2 |
| km | 11 | 9 | 2 |
| spi | 5 | 3 | 2 |
| efuse | 11 | 10 | 1 |
| otbn | 2 | 1 | 1 |
| sram | 2 | 1 | 1 |
| lcc | 4 | 4 | 0 |
| **total** | **158** | **66** | **92** |

Of the 229 `CHK-` log sites in `rom_fw`, 192 (84%) have an `assert` within the
preceding twelve lines, so most of the tree's records are already backed by a
check and only need the token.

**Treat the non-`rom_fw` rows as a weak upper bound.** The count is file-level,
so a file with one PASS-form record credits every class in it, and a leaf may
emit through a shared base or sequence that the grep does not attribute to it.
#1710 reports 1618 such records in a full regression, which suggests many leaves
do emit them at runtime. Subtract the 18 `NO_OWN_EVIDENCE` entries as well.

The number I would stand behind is `rom_fw`: **68 of 70 leaves**, corroborated by
runtime evidence (3 of 3 that reached the gate failed it), and identical on
`main` — 68 leaf classes, the same 2 emitting the PASS form.

## What the floor actually costs

The first draft of this note said relabelling meant ~68 files. It does not, and
the reason is worth stating because it changes the shape of every option below.

`own` is computed as

```python
own = [c for c in seen if c not in _EvidenceFilter.BASE_IDS]
BASE_IDS = frozenset({"CHK-OTP-JTAG2AXI-UNGATED"})
```

so it excludes ONE ID, not base-class records in general. A record emitted by a
shared base therefore counts for every leaf that inherits it. Clearing the floor
for all 70 `rom_fw` leaves needs **ten** labelled sites, one per file:

| file | leaves covered |
|---|---|
| `sep_rom_ot_dma_boot_test` | 27 |
| `sep_backup_manifest_fail_base` | 19 |
| `sep_pubkey_rom_revoked_primary_base` | 6 |
| `sep_chiplet_pubkey_base` | 4 |
| `sep_demotion_prod_base` | 4 |
| `sep_warm_dispatch_base` | 3 |
| `sep_firmware_mbist_fail_test` | 2 |
| `sep_scratch_7_test`, `sep_spi_not_detected_terminal_test`, `sep_warm_reset_invalid_hang_test` | 1 each |

## What was done

`4bc761ed4` on `inmcm/sep_rom_oca_manifest` labels exactly those ten sites, one
per file, 12 lines changed. Each already sat directly after passing asserts, so
the token states what had happened rather than claiming anything new. Verified
statically: 70 leaf classes, 70 reach a PASS-form record, 0 uncovered.

**That is a floor-clearer, not a decision about the convention.** It was kept
deliberately minimal so the group can run and so this note is the thing that
gets discussed, rather than a large diff.

## Options for the convention itself

1. **Relabel `rom_fw` broadly.** 229 `CHK-` log sites exist in `rom_fw`, of which
   192 (84%) have an `assert` within the preceding twelve lines -- those are
   records of contracts the test just checked, and labelling them is accurate.
   The remaining ~37 report rather than assert (a SPI transaction dump, a
   `CHK-SCOPE` line stating what a test does NOT cover); labelling those would
   claim a check that never ran. So the honest version is ~192 sites, not 229,
   and it is a read-each-one job rather than a sed.
2. **Widen the regex to accept the colon form.** One line. But a `CHK-X:` line
   that merely reports would then count as a graded contract, which is the exact
   failure mode #1710 exists to catch.
3. **Add `rom_fw` leaves to `NO_OWN_EVIDENCE`.** Against that list's stated rule
   that it "may only shrink", and it would hide 70 leaves from a gate they can
   now satisfy. Not recommended, and no longer necessary given the ten sites.

## A question the ten sites raise

Nine of the ten labelled records are `CHK-STIMULUS-*` -- they assert the defect
was planted correctly, not that the DUT behaved correctly. Both are checks, and
the gate asks whether the leaf checked anything, so they qualify. But if the
intent of #1710 is "evidence the DUT was graded", a leaf clearing the floor on a
stimulus assertion satisfies the letter and misses the point. If that matters,
the ten should move to DUT-behaviour checks instead -- same cost, better signal.

## What I would ask

- Was `rom_fw` in the regression the 1618-record figure came from? If it was, its
  records must have been counted some other way and I have mis-read something.
- Is the colon form a convention you want retired tree-wide, or is `rom_fw`
  legitimately different (its leaves grade largely through console markers and
  the `MANIFEST_ERR`/status-ring pair rather than per-check compares)?
- The ten sites above are mostly `CHK-STIMULUS-*`. Does a stimulus assertion
  count as a leaf earning its pass, or should the floor be cleared at a
  DUT-behaviour check? Same cost either way; it only changes which line gets the
  token.
- No grace period is needed now that ten sites clear the floor, but if the answer
  is a broad relabel, is an opt-in per-DUT switch worth having so `all` is not
  red while it lands?
