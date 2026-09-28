# rom_fw full-group regression triage (run 20260911_003223)

Recovered after the driving Claude session died at 2026-09-11 01:25:43.
The regression itself outlived the session and ran to completion.

## The run

| | |
|---|---|
| run_dir | `hw/sys/sep/dv/build/runs/20260911_003223__vcs__rom_fw` |
| tree under test | `6745362f1` (`sep/dv: correct the all-group expected_count to 93`) |
| started / ended | 00:32:23 -> 10:54:20 (51717 s wall, `--sim-jobs 6`) |
| scheduler verdict | `status=TIMEOUT`, `exit_code=124` |
| tests | 67 total: **33 PASS, 30 FAIL, 4 TIMEOUT** (pass_rate 0.4925) |

`flist` and `hdl_compile` both passed (41.5 s), so this was not a build break.
`tool_version` in `result.json` reads `Error-[VCS_COM_UNE] Cannot find VCS
compiler` — that is the end-of-run version probe running without the VCS module
loaded, not the state the sims ran under. Ignore it.

This was the **first** full 67-item `rom_fw` run. Earlier runs covered 11, 7 and
2 items, so most of these failures are first observations, not regressions from
a previously green group.

## Class A — DV fixture breakage (fails before sim time advances)

19 of the 30 failures die in under 10 s, inside the Python fixture, with sim
time still at `0.00ns`. Five distinct causes, all in DV, none in the ROM:

1. **Helper keyword drift.** `sep_manifest_mutate.py:914` defines
   `corrupt_public_key(buf, slot, *, offset=0)`, but
   `sep_firmware_backup_invalid_key_hash_test.py:77,80` calls it with
   `byte_index=`. -> `TypeError: corrupt_public_key() got an unexpected keyword
   argument 'byte_index'`. Confirmed still live in the tree.
2. **Return-shape drift.** `sep_decryption_failure_terminal_test`:
   `TypeError: cannot unpack non-iterable int object`.
3. **Validator tightened under the fixture.**
   `sep_firmware_primary_invalid_public_key_selection_test`: the fixture builds
   `public_key_select = 03000000...` (slots `[0, 1]`); the validator now refuses
   anything but exactly one slot, so the fixture's own precondition assert trips.
4. **Key material out of sync with `key_digests.c`.** The generated moduli do not
   hash to the provisioned digests:
   - `sep_firmware_primary_pubkey_rom_5_revoked_key_test`: `sha256(modulus)=a771ca63…`
     vs `key_digests.c=635962ef…`
   - `sep_firmware_chiplet_pubkey_0_test`: `CHIPLET_PUBK_HASH0` is `0xe3c304ff…`,
     expected `0xf6508284…` (LE SHA-256 of the dev0 modulus, `key_digests.c:18-21`)
   Hits the six `pubkey_rom_N_revoked` and five `chiplet_pubkey_*` tests.
5. **RTL hierarchy moved.** `sep_failover_sram_clear_assertion_test`:
   `IndexError: sep_uvm_top.u_dut.u_sep_ip_integration.u_sep_sram.gen_ram_inst
   contains no child object at index 0` — the SRAM backdoor walk is stale.

## Class B — manifest rejected at runtime: `MANIFEST_ERR=0x00030024`

`0x00030024` = `OCA_BOOT_ERR_RESULT(36)` = **`OCA_FAIL_SIGNATURE_CLASS_CONTROL`**:
the manifest's `secure_boot_control` class selection cannot be honoured — secure
boot in force with neither `secure_boot_classic` nor `secure_boot_pqc` set, or
`secure_boot_pqc` on a variant with no PQC region.

Both slots fail identically, so the ROM prints `MANIFEST_ALL_FAILED` /
`MANIFEST_BOOT_FAIL=0x00030024`. Seen on `sep_firmware_cntl_secure_boot_flow_test`
(a positive test expecting `MANIFEST_OK`) and the `backup_*` /
`*_rom_key_index_invalid` family.

Not new to last night: the same `0x00030024` appears in runs `20260910_172601`
and `20260910_183304`. But it is **selective** — `backup_invalid_signature_test`
(10502 s), `backup_rom_key_valid_test` (10319 s) and `bl1_ver_test` (9744 s) all
PASS, so the signing path works and only some fixtures compose the class bits
wrongly. Start from the difference between those fixtures.

### Stale comment worth fixing while here

`hw/sys/sep/bootrom/prod/include/oca_boot.h:22` states "an `oca_result_t` is
0..34". The enum now runs to 36 (`OCA_FAIL_ROOT_KEY_UNAUTHORIZED = 35`,
`OCA_FAIL_SIGNATURE_CLASS_CONTROL = 36`). The `0x000300xx` / `0x000301xx`
encoding is unaffected, but the stated range is wrong — and it is exactly the
range a reader would use to decode `0x24`.

## Class C — four timeouts, all parked at `RSA_EXEC`

**Resolved — `f56dafa0a`. Not hangs.** Each was inside its SECOND RSA-3072
verify when the 14400 s cap fired, at 94-99% completion.

Simulated time kept advancing at rates inside the band the passing members
occupy (1,389-3,334 ns/s against a passing 2,145-7,545), so nothing was stuck.
Taking the last `RSA_EXEC` each reached against where it stopped:

| member | into 2nd RSA | rate | ~wall short |
|---|---|---|---|
| `firmware_primary_invalid_signature` | 0.56 Mns | 1,389 ns/s | 2,546 s |
| `otbn_rsa_verify_failure` | 1.35 Mns | 3,334 ns/s | 824 s |
| `bl1_size_invalid` | 0.23 Mns | 3,056 ns/s | 1,267 s |
| `bl1_entry_invalid` | 0.00 Mns | 2,249 ns/s | 1,823 s |

14 to 42 more minutes apiece, against a four-hour cap. A passing verify costs
~2.3 Mns of simulated time and a failing slot ~5.0 Mns from `RSA_EXEC` through to
its terminal verdict; these four are the members running a modexp on **both**
slots, which `bl1_size_invalid`'s existing comment already noted.

Raised to 21600 s — roughly 3x headroom over the worst shortfall, worth having
given the `--sim-jobs 6` contention the rates were measured under.

There is no group budget: no scheduler-level cap exists, and the run's
`exit_code 124` is aggregated from these four per-test timeouts. 51717.2 s was a
natural end, not a ceiling — so raising these four is the whole fix.

Diagnosis and mitigation; **the confirmation is a run**, and these four are the
cheapest possible check since they need no group.

## Branch state (checked 2026-09-11 13:2x)

- Local `inmcm/sep_rom_oca_manifest_int` @ `e71d0529b`, tree clean, no stashes.
- Remote `origin/inmcm/sep_rom_oca_manifest` @ `fb167fba3` — **4 ahead of local,
  clean fast-forward**. Pushed by others overnight:
  - `fb167fba3` Merge branch 'main' (A. Ottaviano)
  - `8a59f0620` dv: Fix miscellaneous issues (#1648) — only `pyproject.toml`
    (`pyelftools>=0.33`), `tools/dv/runlib/cli.py`, `uv.lock`. Fixes none of the above.
  - `d8425b651` dv/sep: Fix the all-group test count (#1727) — duplicates local
    `6745362f1`; the merge resolved it cleanly, `all.toml` carries a single
    `expected_count = 93` (verified on `fb167fba3`). Nothing to do.
  - `927049b30` doc/sep: multi-chiplet feature-control description (#1631)
- Local is **17 commits behind `origin/main`**.
- PR **#1590** "dv/sep: Integrate the SEP ROM OCA manifest": OPEN, MERGEABLE,
  `mergeStateStatus=BLOCKED`, `reviewDecision=CHANGES_REQUESTED`.

## Next steps, in order

1. Fast-forward local to `fb167fba3` (clean FF, already verified).
2. Merge current `origin/main` (17 behind).
3. Fix Class A — five small, independent DV fixes. Cheapest, and they unblock 19
   items. Each is re-runnable in seconds, so no need to wait on a full group.
4. Diff a Class B failing fixture against `backup_rom_key_valid_test` to find the
   `secure_boot_control` composition bug.
5. Only then re-run the full group — and stage it, or raise the caps. A blind
   re-run costs another ~14 h and would re-observe Class A.
6. Address the #1590 review comments (CHANGES_REQUESTED).

Do not re-run the regression against the current local tree: it is 4 commits
behind the PR branch and 17 behind main, so the result would be stale on arrival.

---

# PR #1590 review items (Alessandro, 2026-09-11 02:09)

Local branch fast-forwarded to `fb167fba3` first; three commits on top.

| Item | State |
|---|---|
| ROM doc include / GH Pages `build-and-deploy` | **fixed** — `731f1bbfa` |
| `lint-spelling`: a misspelt "unparsable", and a base64 run in a PEM | **fixed** — `e0058e37f`, `76a1932dc` |
| `lint-vale`: two PMP expansions | **fixed** — `e0058e37f` |
| `lint-vale`: PCRV expansion | **left alone** — Alessandro is updating the acronym registry |
| `verilator-smoke (sep)`: submodule Python packages | **open** — needs the PAT (below) |

Both PMP hits were `Phrase (ACRONYM)` cross-references that the acronym rule
reads as definitions. Rephrased rather than registered as accepted expansions,
which would have put a wrong expansion in the registry.

## Also found: the submodule breaks four linters, not one

`vale`, `codespell`, `yamllint` and `markdownlint` all walk
`bootrom/prod/tools/tt-oca-manifest` when it is present, and all four have
findings in it (a PQC expansion, fifteen spelling hits in the boot-manifest
spec, trailing whitespace in the submodule's CI workflow, its README set). CI
checks out no submodules today, so this is invisible there — and becomes four
red checks the moment the PAT lands and `submodules: recursive` starts working.
`76a1932dc` excludes the submodule from all four, the same way `vendor/` already
is, so the PAT change trades no red for red.

## Still open: verilator-smoke (sep)

53 of 157 test modules fail to import:

    ImportError: .../tt-oca-manifest/src/oca is missing constants, validators,
    toc, payload, manifest.

`sep_manifest_mutate.py:79-86` raises this deliberately — the packer is the authority
for manifest layout and the guard refuses to hardcode it — so the fix is to
check the submodule out in CI, not to soften the guard.

No workflow sets `submodules:` at all, and `tt-oca-manifest` is a separate
INTERNAL repo, so the default `GITHUB_TOKEN` cannot clone it. No existing
cross-repo checkout token is in the workflows (`GH_AW_*` are agentic-workflow
tokens). PATs for `tt-oca-manifest` and `tt-oca-harness-model` have been
requested; wiring is deferred until the secret exists and its name is known.

Jobs that will need `submodules: recursive` plus the PAT:
`.github/workflows/sim.yml` (lines 31, 117 — `verilator-smoke`) and
`.github/workflows/regress.yml` (lines 152, 248). `doc.yml` does not: the doc
set only links to tt-oca-manifest, it includes no file from it.

`doc/starting/src/setup.adoc:12` already carries the matching TODO ("Need to add
requirements for tt-oca-manifest and tt-oca-harness-model").

## Verified locally

`ocah-lint-python`, `ocah-format-python-check`, `ocah-lint-toml`,
`ocah-lint-yaml` all exit 0. `ocah-lint-spelling` is clean over the CI scope
(remaining hits are all under gitignored `*/build/` trees). `ocah-lint-vale`
reports only the PCRV finding. `ocah-lint-markdown` cannot run here (no working
`npx`); it passed in CI and the change to it only narrows its file list.

---

# Class A: fixed, 18 of 19

Three commits on `76a1932dc`. Every one of these failed with sim time at
`0.00ns`, inside the Python stimulus, so each is verifiable without a simulator
— which is how all of them were checked, by replaying the fixture's own sequence
against the packed images in `bootrom/prod/build/`.

| Fix | Tests | Commit |
|---|---|---|
| `corrupt_public_key(byte_index=)` -> `offset=` | 1 | `203bd82f8` |
| `corrupt_ciphertext` unpacked as a 2-tuple | 1 | `203bd82f8` |
| `verify_public_key` called on a deliberately unresolvable selection | 1 | `203bd82f8` |
| revoke selector anchored at the resolved slot, not the signed one | 10 | `03be2419d` |
| chiplet fuse digests left at the retired dev0 key | 5 | `1d3863e40` |

## Why the revoke family broke, and why slot 0 did not

`select_{primary,backup}_rom_slot()` points the selector at ROM slot N, then
calls `verify_public_key()` to prove the modulus was untouched. That helper
resolves the selector it was just handed, so it compared the image's rom_key0
modulus against slot N's digest. Slot 0 passed only because the write is a
no-op there — which is exactly the observed split: `pubkey_rom_1..5` failed in
seconds, `pubkey_rom_0` ran the full sim and failed for a different (Class B)
reason.

`verify_public_key()` gained an optional `key_slot`; both helpers pass 0. The
signature check directly below them already drew the same distinction, loading
`rom_signing_key(0)` — "the key that signed the shipped image, not the one the
mutated selector now names".

## Why the chiplet fuses were stale from birth

`2166927ea` (2026-08-28) gave each ROM slot its own RSA key and regenerated
`key_digests.c`, changing the slot 0 digest. Its message says the DV
`CHIPLET_PUBK_HASH0` words "are re-derived" — but the commit touches no eFuse
TOML, and the chiplet preloads were only added later by `9317673f1`
(2026-09-07), carrying the pre-rename value. So they never matched.
`sep_chiplet_pubkey_base` computes what it wants from `key_digests.c`, so the
fixed values track the keys from here on.

## Still open: A5, and it is a framework gap not a fixture bug

`sep_failover_sram_clear_assertion_test` reads the SRAM array over VPI at
`gen_ram_inst[0].u_mem.mem`, which resolves under Verilator via
`sep_public_scope.vlt` and not under VCS. `rom_fw.toml:443` already says so:

> NEEDS THE VERILATOR FLOW, which is this DUT's default -- the runlib has no
> per-test tool key, so nothing enforces it.

`TEST_KEYS` in `tools/dv/runlib/config.py:262` confirms it: `name`, `module`,
`target`, `seed`, `reseed`, `timeout_sec`, `tags`, `run_modes`, `firmware`,
`args`, `overrides` — no simulator restriction. It passed standalone under
Verilator on 2026-09-09 (`20260909_170320__verilator__...` PASS).

Three ways out, and they differ enough to be the owner's call:

1. Add a per-test `tools` key to the testlist schema and have the scheduler
   report non-matching tests as SKIPPED. Correct and reusable; it touches shared
   runlib used by SMC/SMU/DTP. (An earlier draft of this file worried about the
   `expected_count` group guard — that was wrong, see the plan below.)
2. Make the test skip itself when the scope will not resolve. Cheap, but it
   then silently asserts nothing under VCS, which is how a coverage claim rots.
3. Give the backdoor a VCS-visible path. Keeps coverage on both simulators;
   most work, and needs VCS visibility flags the TB does not currently set.

## Documentation drift found while fixing A4 (not fixed)

15 files under `tests/rom_fw/` still assert that `key_digests.c` "populates slot
0 only" / that a slot "has no compiled-in digest", and 5 say "Only
`rsa_private_key.dev0.pem` ships here". All six slots are populated
(`public_key_digests[]`, `key_digests.c`) and six keys ship. The reasoning built
on it is wrong in the same way: without the revoke bit, slot N is now refused as
a digest mismatch, not as `PUBK_SLOT_UNPROVISIONED`. The verdicts still hold —
revocation is consulted before the digest table — so this is stale prose rather
than a broken test, but it is load-bearing prose. `KEY_SLOT_FIRST_UNPROVISIONED`
is computed (= 6), so `sep_firmware_backup_unpopulated_rom_key_slot_test`
adapted on its own and is unaffected.

## CI after the review-fix push (`76a1932dc`)

| Check | Was | Now |
|---|---|---|
| `build-and-deploy` | FAILURE | **SUCCESS** |
| `lint-spelling` | FAILURE | **SUCCESS** |
| `lint-vale` | FAILURE | FAILURE — the PCRV finding alone; both PMP hits gone |
| `verilator-smoke (sep)` | FAILURE | FAILURE — still needs the submodule PAT |

---

# Documentation drift: one part done, the rest blocked on a design call

## Done: the pre-OCA USE_EXT_SRAM narrative (`79aa4e2a6`)

`sep_failover_sram_clear_assertion_test` explained its uncovered SMC-SRAM half
as a split responsibility — packer emits a USE_EXT bit, ROM lacks the consuming
branch. `flag_args`, `use_ext_sram` and `FLAG_ARGS_BIT_USE_EXT_SRAM` exist
nowhere in this tree, and the cited `tt-boot-manifest` paths are two renames
stale with line numbers pointing at unrelated code. A CHK-SCOPE log line also
claimed the run "observes flag_args=0x00000000" — a marker the ROM never prints
and no run log contains. Both now say what `rom_fw.toml` already said: the OCA
manifest declares no such bit.

## BLOCKED: the revoke family's premise is broken, not just its prose

The stale claim is that `key_digests.c` "populates slot 0 only" and slots 1-5
"have no compiled-in digest" (11 sites), plus "Only `rsa_private_key.dev0.pem`
ships here" (5 sites). `2166927ea` made both false: six keys ship and
`public_key_digests[]` populates all six slots.

That is not cosmetic, because **the ROM authorizes before it checks
revocation**. Confirmed on a passing run
(`sep_firmware_backup_rom_key_valid_test`):

    PUBK_SEL -> PUBK_AUTHORIZED -> PUBK_REVOKE -> FUSE_VER -> RSA_EXEC -> RSA_VERIFY_OK

`plat_is_key_authorized` (`oca_platform.c:414-475`) looks up
`public_key_digests[slot]`, and a populated digest that does not match the
modulus yields `PUBK_UNAUTHORIZED` — before `plat_get_root_key_revocation` is
ever called. So for slots 1-5, where the booted image carries rom_key0's
modulus:

- **old world** — digest absent, so `PUBK_SLOT_UNPROVISIONED`; the docstrings'
  stated property (revocation preempts the empty-digest arm) held.
- **now** — digest present and mismatched, so `PUBK_UNAUTHORIZED` fires first.
  `sep_pubkey_rom_revoked_primary_base.py:293-295` forbids **both**
  `PUBK_SLOT_UNPROVISIONED` and `PUBK_UNAUTHORIZED`, and requires
  `MANIFEST_ERR=<KEY_REVOKED>`, which can no longer be reached.

So Class A's fix gets these ten tests to the simulator, where they should be
expected to fail on the verdict. The fixture fix is still right — it made the
stimulus consistent with the image the family actually loads — but it is not
sufficient.

### The fix the tree is already set up for

`2166927ea` added per-slot signed images for exactly this, "so an off-by-one in
slot resolution can no longer match a digest by accident". They are on disk and
fully self-consistent:

| image | selector | modulus |
|---|---|---|
| `oca_rom_key1_boot.bin` .. `key5` | slot N (both slots) | rom_keyN |
| `oca_secure_boot.bin` | slot 0 | rom_key0 |

Point each member at its own image and the selector rewrite becomes unnecessary:
the manifest already names slot N and carries rom_keyN, so `PUBK_AUTHORIZED`
passes, the fuse bit is then consulted, and `KEY_REVOKED` is the verdict. Every
member becomes the strict form the docstrings currently reserve for slot 0, and
the prose gets simpler and true rather than rewritten-but-still-weak.

Cost: `flash_image` per member (a class attribute, so trivial), retire the
selector-rewrite path in both bases — which supersedes the `key_slot=0` anchor
from `03be2419d` — and add the five images to `[c_build.boot_rom_ot].outputs` in
`sep_sim_cfg.toml:389-404`, whose comment currently explains that only four OCA
images are declared because nothing under `hw/sys/sep/dv` loads the rest.

The alternative is to keep the weaker stimulus and rewrite the prose to say
`PUBK_UNAUTHORIZED` is now the arm revocation must preempt — but it does not
preempt it, so the tests would have to change anyway. That is why this is a
design call and not a documentation pass.

### A second drift axis, outside `tests/rom_fw`

`rom_fw.toml` still names `boot_arguments.flag_args` (lines 1885, 2009, 2123,
2126, 2128) and `flag_args=0x00000000` (line 466). The OCA field is
`demotion_control` (22 uses across the DV demotion tests; `OCA_FAIL_DEMOTION_
CONTROL` in the validator). Same superseded-format class, different file — say
the word and it goes in with the rest.

---

# A5 in detail: a per-test `tools` key

The recommended option, and cheaper than the first draft of this file suggested.
The runlib already has a working precedent for exactly this shape of problem.

## The precedent to copy

A scenario with no `module` binding for the selected framework is handled by
`validate_item_bindings` (`tools/dv/runlib/cli.py:2050-2090`), whose semantics
are already the ones A5 wants:

- named explicitly in `--items` -> hard `ConfigError`, because the user asked
  for that test by name and silently dropping it would lie;
- reached via a group or tag -> dropped, but only under `--skip-unimplemented`,
  and recorded in run metadata;
- nothing left after dropping -> `ConfigError` rather than a vacuous green run.

It stores the dropped names on `args._skipped_unimplemented` (`cli.py:2090`),
which `results.py:809-811` surfaces as
`payload["selection"]["skipped_unimplemented"]`.

## What to add

1. **`models.py:58` `TestEntry`** — `tools: list[str] | None = None`.
2. **`config.py:262` `TEST_KEYS`** — add `"tools"`, and parse it in
   `_test_from_dict` with the existing `as_str_list` helper.
3. **`config.py`** — validate each name against the DUT's own `tools` list
   (`config.py:1218` already parses that for the sim_cfg and validates
   `default_tool` against it at line 1229), so a typo fails at config load with
   the file named, not at dispatch.
4. **`cli.py`** — a `validate_item_tools` beside `validate_item_bindings`,
   called from the same place (`cli.py:2382`), storing
   `args._skipped_wrong_tool`; extend the `results.py` payload alongside
   `skipped_unimplemented`.
5. **`rom_fw.toml:494`** — `tools = ["verilator"]` on the entry, replacing the
   comment at line 443 that currently says nothing enforces it.

## What it does not touch

`expected_count` is validated at config-load time against the length of the
group's static member list (`config.py:1845-1861`) and never sees a runtime
outcome, so skipping a test cannot trip the `all.toml` = 93 guard.

`SKIP` is already a first-class status: `junit.py:69-70` maps it to `skipped`,
`junit.py:245` excludes it from leaf counting, and `ui.py:303-313` reports it
separately from failures. So a skipped-for-tool test reports correctly without
new plumbing.

## Why not the other two

- **Self-skip inside the test.** Cheapest, but the test then asserts nothing
  under VCS while still reporting green, which is how a coverage claim rots
  quietly. It also puts simulator knowledge in a scenario rather than in the
  selection layer that already owns it.
- **A VCS-visible backdoor.** Keeps coverage on both simulators and is the only
  option that actually widens coverage, but it needs VCS visibility flags the TB
  does not set today, and the scope is a testbench change rather than a
  selection fix. Worth doing later on its own merits; it does not block the
  group from going green.

## Open question for the owner

Whether `--skip-unimplemented` should also gate the tool skip, or whether a
tool mismatch should skip unconditionally. The framework case is a gap in
coverage someone intends to close, so it is opt-in. A tool restriction is a
statement of fact about where the scenario can run, which argues for
unconditional — at the cost of one more way a group can quietly shrink.

---

# Both decisions implemented

## (a) revoke family on per-slot images — `76fafa5e0`, `33a60b2d3`

Not new configs. `mm.graft_slot()` moves a whole slot, manifest and payload
together, out of `mm.rom_key_image(N)` — the per-slot images `2166927ea` already
built. A payload offset is stored manifest-relative, so a grafted slot is
self-consistent at its new home, and both images share the packer's combined
layout (0x1000..0x41000 primary, 0x41000..0x50000 backup), which the helper
asserts.

Verified by replaying both reworked helpers for all six slots on each side: the
selector, the modulus it resolves to, and the full seal agree for all twelve
members, and the untouched slot stays rom_key0 and sealed.

Both helpers collapsed to one branch. Every slot now ends fully sealed, so the
stale-signature assertion is gone and `pm.verify_sealed()` covers all six —
every member is the strict case, where before only slot 0 was. That also made
the `key_slot` override from `03be2419d` dead, so it is removed.

The five per-slot images joined `[c_build.boot_rom_ot].outputs`.

The docstring pass followed, and was only writable once this landed. Three false
claims across fifteen files, the worst being "the signature path consults the
fuse bitmap BEFORE the digest table" — the argument for what slots 1-5 proved
rested on an order the ROM does not use.

## A5 per-test `tools` key — `fabfe9cba`

Followed `validate_item_bindings`: group/tag selections drop, explicit `--items`
errors, empty selection errors, drop announced and recorded as
`selection.skipped_wrong_tool`. Names validated against the DUT's own `tools`
list at catalog load.

Chose to drop unconditionally rather than behind a flag. An unimplemented
framework binding is a gap someone closes by adding the entry, so it is opt-in; a
tool restriction states where the stimulus can work at all, so there is nothing
to opt into and a flag would be permanent friction.

Two things the first pass got wrong:

- `as_str_list` flattens an absent key and `tools = []` both to `[]`, so empty
  means unrestricted like `tags`/`run_modes`, and an explicit empty list is
  rejected in `_test_from_dict` where the raw entry is still visible.
- the cross-check must skip scenarios with no binding for the selected
  framework. The `sep (uvm)` view declares only `vcs` and never runs this cocotb
  scenario, so gating it on a tool that view lacks rejected a valid testlist.

`--validate-configs`: 15/15 framework views OK. Nine new unit tests; the runlib
suite is 105 and green (`python3 -m unittest discover tools/dv/tests` — pytest is
not in the dv group, and these are not a CI gate).

## Where Class A stands

All 19 addressed. 18 by the fixture fixes, A5's one by selection. The ten revoke
members additionally needed `76fafa5e0` to reach a reachable verdict — the
fixture fix alone would have got them to the simulator and failed there.

Nothing has run in a simulator. Every check above is the fixtures' own logic
replayed against the packed images, plus config validation and unit tests. The
verdicts are still unproven until a real run.

## Still open

- **B**: `OCA_FAIL_SIGNATURE_CLASS_CONTROL` on the manifest class bits. Not
  started; root cause still unidentified, only localized.
- **C**: 4 timeouts parked at `RSA_EXEC`. Not started; hang vs 4h cap unresolved.
- 14 commits behind `origin/main`.
- `rom_fw.toml` still names the pre-OCA `boot_arguments.flag_args` (lines 466,
  1885, 2009, 2123, 2126, 2128); the OCA field is `demotion_control`.
- PAT secret name for `verilator-smoke (sep)`.
- PR #1590 `lint-vale`: the PCRV finding, Alessandro's.

---

# Class B decomposed

`0x00030024` was never the whole story — it is one test out of eleven. Decoding
every `MANIFEST_ERR` the slow failures printed (low byte = `oca_result_t`):

| code | `oca_result_t` |
|---|---|
| `0x02` | `OCA_FAIL_MAGIC` (2) — the deliberate primary failover trigger, expected |
| `0x0e` | `OCA_FAIL_SIGNATURE` (14) |
| `0x16` | `OCA_FAIL_ROOT_KEY_REVOKED` (22) |
| `0x17` | `OCA_FAIL_SECURITY_VERSION` (23) |
| `0x22` | `OCA_FAIL_CRYPTO_FIELD_SIZE` (34) |
| `0x23` | `OCA_FAIL_ROOT_KEY_UNAUTHORIZED` (35) |
| `0x24` | `OCA_FAIL_SIGNATURE_CLASS_CONTROL` (36) |

## B1 — a newer check fires before the one the test expects (6 tests)

| test | expects | gets |
|---|---|---|
| `backup_rom_key_index_invalid` | `0x0e` SIGNATURE | `0x23` ROOT_KEY_UNAUTHORIZED |
| `backup_invalid_public_key_selection` | `0x0e` | `0x23` |
| `backup_unpopulated_rom_key_slot` | `0x0e` | `0x23` |
| `primary_rom_key_index_invalid` | `0x0e` | `0x23` |
| `primary_invalid_signature_type` | `0x0e` | `0x22` CRYPTO_FIELD_SIZE |
| `backup_invalid_signature_type` | `PUBK_ALGO_UNSUPPORTED` | `0x22` |

**Resolved — `15c6a8fbe`.** The verdicts are correct for what each test plants;
the expectations predate the checks.

`plat_is_key_authorized()` returns `OCA_FAIL_ROOT_KEY_UNAUTHORIZED` from *every*
arm — slot reserved, selector ambiguous or empty, slot unprovisioned, algorithm
or encoding unsupported, digest mismatch. The code means "this key is not
authorized"; the console marker says which arm. So the four authorization members
take a new `MANIFEST_ERR_KEY_UNAUTHORIZED` and keep the markers they already
declared. The failing runs printed exactly those markers followed by
`0x00030023`.

The signature-type pair moved further than the code. `signature_type = 0`
disagrees with the declared field sizes, so `oca_check_crypto_field_sizes()`
refuses it **structurally, before `plat_is_key_authorized()` is called at all**.
That makes `PUBK_ALGO_UNSUPPORTED` — which both members *required* — unreachable,
since it is an arm of a callback the refusal precedes. The runs confirm it:
`0x00030022` with no `PUBK_*` token for the bad slot. Those two now expect
`MANIFEST_ERR_SIG_TYPE_INVALID`, take the error code as their own defect marker
(no console token exists for a structural refusal — the pattern
`primary_invalid_security_version` already uses, which the B2 inclusive-bound fix
enabled), and **forbid** `PUBK_ALGO_UNSUPPORTED` to pin the stronger ordering.

Their docstrings argued at length that the error code *could not* discriminate
them from their signature-VALUE siblings. That has inverted — `0x00030022` vs
`0x0003000e` separates them outright — so both were rewritten, along with a
broken concatenation (`PUBK_ALGO_UNSUPPORTED0x00000000`) found in one.

Verified against each failing run's own output: all six newly expected codes
appear in their logs, as do the declared markers;
`PUBK_ALGO_UNSUPPORTED` appears zero times in the two runs that now forbid it.

## B2 — correct verdict, secondary assertion fails (4 tests)

| test | verdict | what failed |
|---|---|---|
| `primary_pubkey_rom_0_revoked_key` | `0x16` correct | `cold_scratch[1]` never held `0x0f010016` |
| `backup_pubkey_rom_0_revoked_key` | `0x16` correct | `cold_scratch[1]` never held `0x0f010016` |
| `backup_invalid_security_version` | `0x17` correct | `cold_scratch[1]` never held `0x0f010017` |
| `primary_invalid_security_version` | `0x17` correct | ordering: the err does not sit between the two slot reads |

**Resolved — `417b9a49c`. No ROM bug.** Both were test bugs.

The three status-ring failures: `sep_backup_manifest_fail_base` built its
expectation as `0x0F01_0000 | (expected_error & 0xFFFF)`. The console carries
`OCA_BOOT_ERR_BASE | oca_result_t`; the ring carries `STATUS_ENCODE(type,
SEP_MSG_*)`. So a revoked key was asserted as `0x0f010016` (oca_result 22) while
the ROM wrote `0x0f01000c` (`SEP_MSG_REVOKED_KEY`), and a rolled-back version as
`0x0f010017` instead of `0x0f010008`. Both of the ROM's words are present in the
observed ring of the failing runs — the ROM reported correctly throughout.

`mm.rom_status_for_result()` already parses `status_for_result()` for exactly
this, and its docstring already names the mistake: "masking the console code and
calling the low half a status is how a test ends up asserting on a value the ROM
never reports". `sep_bl1_image_invalid_base` and
`sep_decryption_failure_terminal_test` both use it; this base was the one never
converted.

Why it survived: the two spaces collide on the most common expected error.
`OCA_FAIL_SIGNATURE` is 14 and `SEP_MSG_INVALID_SIGNATURE` is `0x0e`, so every
member expecting a signature failure asserted the right word by accident.

The ordering failure: `CHK-DEFECT-ATTRIBUTION` required the defect marker to sit
strictly before the primary's error, but a member with a DEDICATED `MANIFEST_ERR`
declares that code as its own defect marker — so `primary_defect_marker` and
`slot_err` are the same string on one console line, `i_defect == i_perr`, which
no strict bound admits. Upper bound is now inclusive; a distinct token cannot
share a line with the error, so only the degenerate case is admitted.

Verified against each failing run's own data: the old expected word is absent
from the observed ring and the new one present, in all three; and the recorded
indices (psrc=55, defect=62, perr=62) fail the old predicate and satisfy the new.

## B3 — `sep_firmware_cntl_secure_boot_flow_test`

**Resolved — `8cc7b0322`. No ROM bug.** The run graded as a failure is the
correct fail-closed rejection; the test required `RSA_EXEC`, `RSA_VERIFY_OK` and
`MANIFEST_OK` from a manifest carrying no signature, so it could never pass.

Chain, all from source and confirmed empirically:

1. Clearing the enforced bit obliges the whole crypto set to be zero — with
   secure boot off the parser refuses any populated signature, public key,
   key-select or type/encoding byte (`OCA_FAIL_SECURE_BOOT_INVARIANT`,
   `parser.c:180-208`). So `clear_secure_boot` necessarily yields a legally
   UNSIGNED manifest.
2. Both class bits share the byte with the enforced bit. Shipped slots carry
   `secure_boot_control = 0x03` (enforced + `secure_boot_classic`); the mutation
   leaves `0x00`.
3. PROD puts secure boot in force through `secure_boot_decide()`'s **third**
   input (the device's `is_secure_boot_active()`), nothing names a signature
   family, and `secure_boot.c:226` refuses — `0x00030024` on both slots, then
   `MANIFEST_ALL_FAILED`.

A verified boot is not expressible. The enforced bit is inside the TBS (182 vs a
signed region ending at 3172) and the invariant keys on that bit **alone**, so a
manifest cannot disclaim secure boot while carrying a verifiable signature even
with a class bit still set. The format closed the hole structurally.

The refusal still proves the precedence, because it is lifecycle-dependent: the
same image boots non-secure in TEST_DEV where the manifest's request is honoured.
`SBOOT_OFF` stays forbidden — the sharpest form of the claim.

Rebased onto `sep_backup_manifest_fail_base`, since `sep_rom_ot_dma_boot_test`
requires `MANIFEST_OK`/`PAYLOAD_OK` and gates on `fw_pass`. That also brings the
status-ring assertion for free via the B2 fix:
`STATUS_ENCODE(ERROR, SEP_MSG_MANIFEST_SECURE_BOOT)` = `0x0f01008d`, which
`oca_boot.c:474` re-reports once every slot is gone. `PUBK_SEL=` is forbidden on
both slots, placing the rejection ahead of key selection;
`check_defect_attribution` is overridden because both slots carry the same
defect.

Verified against the failing run's console: marker at lines 58 and 63 around the
backup read at 60, `LC=PROD` and `MANIFEST_ALL_FAILED` present, all nine
forbidden markers absent. The ring word is the one assertion not visible in that
log (the old test never dumped the ring); the ROM emits it, and a sibling run
shows consecutive ERROR writes both captured by the sampler.

Upstream doc nit written up separately in `OCA_CLASS_CONTROL_DOC_TICKET.md`.

## Shape of the work

- **B1** is mechanical once accepted: six expected-verdict updates, same
  reasoning as A4, each independently checkable.
- **B2** needs investigation first — the verdict is right, so this is a status
  reporting path, and it is the one sub-class where a real ROM bug is still live.
- **B3** needs a decision on what the test should now assert.

## Open: three tests in the testlist but not in the `rom_fw` group

**Deliberately NOT fixed — user's call, 2026-09-14.** Recorded here so it does not
disappear again; it is invisible by construction, because a test that is never
selected produces no failure to notice.

`rom_fw.toml` and the `rom_fw` group in `all.toml` are maintained separately, and
`--items rom_fw` selects the GROUP. These three are in the testlist and have never
been in the group, so they have never run in a `rom_fw` regression:

```
sep_rom_oca_encrypted_boot_test
sep_rom_oca_otp_key_boot_test
sep_rom_oca_tamper_test
```

Provenance: added to `rom_fw.toml` by `1f1ba343d` (2026-08-27, "dv/sep: Add
encrypted, OTP-key and tamper ROM boot tests"). `git log -S` over `all.toml`
returns nothing for any of the three, so that file has never referenced them. The
group was 67 members at `e27ae7901`, the branch tip before this work began.

How it surfaced: a dry run selected 66 items where the testlist held 70. One of
the four was `sep_failover_sram_clear_assertion_test`, correctly skipped as
verilator-only by the per-test `tools` key. The other three were this.

Why it matters rather than being bookkeeping — all three ran for the first time on
2026-09-14, passed on the command line, and one of them was broken:

| test | first-ever run | now |
|---|---|---|
| `sep_rom_oca_encrypted_boot_test` | PASS 8406 s | PASS |
| `sep_rom_oca_otp_key_boot_test` | PASS 8272 s | PASS |
| `sep_rom_oca_tamper_test` | FAIL at 0.00 ns, `ValueError: embedded null byte` | fixed `411f6e1eb`, PASS 3989 s |

`sep_rom_oca_tamper_test` had rebound `self.flash_image` to raw bytes where the
base opens it as a path. That defect sat undetected from August precisely because
the group never ran it.

To close it later: three lines in the `rom_fw` group in `all.toml`. All three pass
today, so the risk is schedule rather than correctness — two are ~8300 s, so a
full group run grows by roughly 4.5 h.

Note `sep_decryption_failure_failover_test` (added 2026-09-14) WAS put in both
files, so it does not extend this gap.
