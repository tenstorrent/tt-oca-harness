# Uprev the VP branch onto main, in parallel with PR #1590

**Audience:** an agent working `inmcm/integrate_oca_boot_manifest_clean` (the VP branch) in
`/localdev/cmccoy/dev/tt-oca-harness`, while a second agent finishes
`inmcm/sep_rom_oca_manifest` (the ROM/DV/doc branch, PR #1590) in
`/localdev/cmccoy/dev/tt-oca-harness-main`.

**Written:** 2026-09-14. Everything below marked *measured* was derived from the repo on that
date and the command is given so you can re-derive it rather than trust it. The branches move;
re-measure before acting.

> **`git fetch origin --prune` FIRST, every time.** The first draft of this document was
> measured against a stale `origin/feature/sep_virtual_platform` and got the head wrong by one
> commit, which inverted a containment claim (§1). A `git rev-parse origin/<branch>` on an
> unfetched ref is not evidence.

This supersedes the "## The VP branch — don't rebase it" section of `MAIN_REBASE_PLAN.md`
(line ~496) on one point only — the delivery route — and keeps the rest of its reasoning,
which is still correct and still load-bearing.

---

## 1. Why the plan changed

`MAIN_REBASE_PLAN.md` proposed: ROM/DV/doc → main, then merge main into
`feature/sep_virtual_platform`, then rebuild `_clean`'s VP-only commits on the new feature
tip, and let PR #1028 carry the feature branch to main.

The user's call on 2026-09-14: the feature-branch hop is redundant, because `_clean` already
carries essentially all of the feature branch.

Measured *after fetching* (an earlier draft got this wrong off a stale ref):

```bash
git fetch origin --prune
git merge-base --is-ancestor origin/feature/sep_virtual_platform \
                             origin/inmcm/integrate_oca_boot_manifest_clean \
  && echo contained || echo "not contained"
git rev-list --left-right --count origin/feature/sep_virtual_platform...origin/inmcm/integrate_oca_boot_manifest_clean
```

→ **not contained, by exactly one commit: `1  33`.**

`_clean` forked from the feature branch at its then-tip `d14133828` and added 33 commits. The
feature branch has since advanced by a single commit:

```
c3682138d  2026-09-09  vp: Enable Full VP Build Targets (#1586)
```

So the conclusion stands — there is no body of VP work hiding on the feature branch — but the
route is "`_clean` plus one commit", not "`_clean` is a superset". **`c3682138d` must be picked
up**, or the VP delivery silently drops PR #1586. It is 32 files: mostly `virtual_platform/`,
plus 8 shared ones (`.github/workflows/vp.yml`, `AGENTS.md`, `flows/lint/ruff.mk`, `help.mk`,
`pyproject.toml`, `scripts/docker-run.sh`, `tools/docker/Dockerfile`, `tools/docker/README.md`)
and a `tt-oca-harness-model` submodule bump.

Check before you start whether the feature branch has moved again beyond `c3682138d`.

So `_clean` is the delivery branch. It goes to main *after* #1590 lands, and PR #1028 becomes
redundant — it is currently titled *"work in progress, do not merge"*, so nothing is lost, but
**someone must close it or repoint it deliberately.** Do not leave two open PRs claiming to
deliver the VP.

> **DONE 2026-09-15** — #1028 closed by hand (closed, not merged; nothing was lost).
>
> **But there is a third PR this document never recorded: #1588**, a *draft* of
> `inmcm/integrate_oca_boot_manifest_clean → feature/sep_virtual_platform`, opened 2026-09-05
> under the old `MAIN_REBASE_PLAN.md` route where `_clean` fed the feature branch and #1028
> carried it onward. With #1028 closed, **#1588's base branch has no route to main**, so as it
> stands it delivers nothing.
>
> It is also the natural delivery PR — it already comes *from* the delivery branch — so the
> cheap fix is to repoint it rather than open a fourth:
>
> ```bash
> gh pr edit 1588 --base main          # then retitle; it still says "to VP feature branch"
> ```
>
> Do that **after** #1590 lands and the main-merge is done, or the PR will show `_clean`'s 25
> superseded ROM/DV/doc commits as if they were part of the VP delivery. Until then leaving it
> as a draft against the feature branch is harmless.

What does NOT change from the old plan:

- **Never rebase or force-push `feature/sep_virtual_platform`.** It is shared, carries 4 merge
  commits from PRs #1309/#1440/#1444, and has PR #1028 open against it. It also contains a
  criss-cross merge — an 18-commit patch-identical duplicate block — so any linearisation
  replays all 18 twice. The old plan hit exactly that and stalled on a `uv.lock` conflict.
- **`_clean`'s ROM/DV/doc commits are redundant once main has #1590.** Same reasoning, larger
  numbers now. See §4.

---

## 2. Ground truth (measured 2026-09-14)

| Branch | vs `origin/main` (behind / ahead) | Tip |
|---|---|---|
| `origin/main` | — | `1523a8fe5` (2026-09-14) |
| `origin/inmcm/sep_rom_oca_manifest` | **40 / 142** | `e54c47e47` (2026-09-14) |
| `origin/inmcm/integrate_oca_boot_manifest_clean` | 276 / 75 | `8f8c34d21` (2026-09-05) |
| `origin/feature/sep_virtual_platform` | 276 / 43 | `c3682138d` (2026-09-09) |

Main moves fast — it took 40 commits in a single day while this was being written. Treat every
row as a reading, not a constant.

```bash
for b in origin/inmcm/sep_rom_oca_manifest \
         origin/inmcm/integrate_oca_boot_manifest_clean \
         origin/feature/sep_virtual_platform; do
  printf '%-52s %s\n' "$b" "$(git rev-list --left-right --count origin/main...$b)"
done
```

**PRs:** #1590 `inmcm/sep_rom_oca_manifest → main` (open, lands first; `MERGEABLE` but
`BLOCKED` on 2026-09-15, with changes requested and `verilator-smoke (sep)` + `lint-vale`
failing).
#1028 `feature/sep_virtual_platform → main` — **closed 2026-09-15**, not merged.
#1588 `inmcm/integrate_oca_boot_manifest_clean → feature/sep_virtual_platform` (open, draft) —
the old route's PR; repoint it at `main` or close it, see §1.

`sep_rom_oca_manifest` was 0 behind main when main was merged into it on 2026-09-13
(`cfb46736e`); it is **40 behind again** by 2026-09-14. It will take at least one more main
merge before it lands, so its final shape is not frozen — see §7. Plan against "main plus
~142", not against a fixed hash.

**The 142 commits:** 218 files, overwhelmingly `hw/sys/sep/dv/**` (~110 files) and
`hw/sys/sep/bootrom/prod/**` (~84), plus `hw/sys/sep/doc/**`, `tools/dv/**`, `pyproject.toml`.
Nothing under `virtual_platform/`.

---

## 3. The conflict surface — two numbers, don't mix them

> **Corrected 2026-09-15.** This section used to be headed *"the conflict surface is small — 4
> files"* without saying *whose* four. There are two different measurements below, and only (b)
> describes the merge step 2 actually runs. The hand-merge set really is 4 files; the conflict
> list is ~94 long.

**(a) The feature branch's footprint.** The VP work proper touches **15 files outside
`virtual_platform/`**, of which this branch touches **4**. (It was 13 before `c3682138d` added
`flows/lint/ruff.mk` and `help.mk`; neither collides.) This is the number the rest of §3
describes, and it is the right one for reasoning about the *VP payload*.

```bash
MB=$(git merge-base origin/main origin/feature/sep_virtual_platform)
git diff --name-only $MB origin/feature/sep_virtual_platform -- . ':!virtual_platform' | sort > /tmp/vp
git diff --name-only origin/main origin/inmcm/sep_rom_oca_manifest | sort > /tmp/rom
comm -12 /tmp/vp /tmp/rom
```

**(b) `_clean`'s footprint — the one step 2 faces.** `_clean` also carries the 25 ROM/DV/doc
commits (§4), so its own footprint outside `virtual_platform/` is **113 files** and its overlap
with the ROM branch is **94**, not 4. Measured 2026-09-15:

```bash
MB=$(git merge-base origin/main HEAD)
git diff --name-only $MB HEAD -- . ':!virtual_platform' | sort > /tmp/vp2
git diff --name-only origin/main origin/inmcm/sep_rom_oca_manifest | sort > /tmp/rom2
comm -12 /tmp/vp2 /tmp/rom2 | wc -l                                               # 94
comm -12 /tmp/vp2 /tmp/rom2 | grep -cE '^hw/sys/sep/(bootrom|dv|doc)/|^tools/dv/'  # 91
```

The split is what keeps the job small: **91 of the 94 fall under §5's "take main's wholesale"
rule** — they are the superseded 25 commits — leaving the same **4 hand-merge files** listed
below. So the work is small, but the conflict list is not short. Do not plan step 2 expecting to
see four conflicted files.

> **Measured 2026-09-17, by dry-running the merge:** the 94 above is a *file-overlap* estimate;
> the real three-way merge auto-resolves part of it and stops on **67 conflicted files**. Use 67
> as the expectation, and prefer this method over counting overlaps — it is the only number that
> reflects what git will actually hand you:
>
> ```bash
> git merge --no-commit --no-ff origin/main >/dev/null 2>&1
> git diff --name-only --diff-filter=U | wc -l
> git merge --abort
> ```

**Both sides change these — hand-merge:**

| File | What each side wants |
|---|---|
| `.gitmodules` | see §3.1 — the important one |
| `hw/sys/sep/bootrom/prod/Makefile` | VP adds header dependency tracking; ROM branch reworked `oca-images` / `toolchain-images-build`. Union, not either/or. |
| `pyproject.toml` | dependency sets; union |
| `.gitignore` | union |

**VP touches, this branch does not — should merge clean:** `.github/workflows/vp.yml`,
`AGENTS.md`, `flows/lint/ruff.mk`, `help.mk`, `hw/common/dv/fw/compile.mk`,
`hw/ip/key_manager/dv/tb/Makefile`, `ocah.mk`, `scripts/docker-run.sh`,
`tools/docker/Dockerfile`, `tools/docker/README.md`, `uv.lock`.

### 3.1 Submodules — read this before you merge anything

| Branch | `.gitmodules` contains |
|---|---|
| `origin/main` today | `tt-boot-manifest` |
| `feature/sep_virtual_platform` | `tt-boot-manifest`, `tt-oca-harness-model` |
| `inmcm/sep_rom_oca_manifest` | `tt-oca-manifest` **only** |
| `inmcm/integrate_oca_boot_manifest_clean` | `tt-oca-harness-model`, `tt-oca-manifest` |

The ROM branch **replaces** `tt-boot-manifest` with `tt-oca-manifest` (different repo, not a
rename in place). After #1590 lands, main has `tt-oca-manifest` and no
`tt-oca-harness-model`.

`_clean`'s `.gitmodules` is **already the correct end state** — it is the union, with
`tt-boot-manifest` gone. Commit `1ea6abd07` *"vp: Point manifest tooling paths at
tt-oca-manifest"* is what did it. So on this file, **keep `_clean`'s version**; do not let a
merge reintroduce `tt-boot-manifest`.

`tt-oca-manifest` is an **internal** repo the user maintains. Fixes that belong to it do not
go in this tree — write them up separately (`OCA_CLASS_CONTROL_DOC_TICKET.md` in the other
worktree is an example of that convention).

### 3.2 Files main deliberately removed — added 2026-09-17

Same shape as the `tt-boot-manifest` rule above, pointing the other way: some files exist on
`_clean` **because it is old**, and main has since removed them on purpose. Merging must let
those deletions through.

**`.gitlab-ci.yml` — removed for security. Do not reintroduce it.** Main dropped it in
`6629df4dd` *"ci: Move GitLab parent configuration out of mirror (#1955)"*; the GitLab parent
configuration now lives outside this mirror. `_clean` still carries the file only because it
forked before that.

Verified 2026-09-17 by dry-running the merge: `_clean` has not touched `.gitlab-ci.yml` since
the fork, so git applies main's deletion **with no conflict** and the file simply goes. There
is no "keep `_clean`'s" decision point to get wrong. The risk is only in the §5 *fallback*
route (branch fresh off main, carry the VP payload across) or a careless `checkout --ours`
batch — either could hand it back.

```bash
git log --oneline --diff-filter=D -1 origin/main -- .gitlab-ci.yml   # 6629df4dd
```

Related: commit `4b62e18d8` on the retired `inmcm/sep_rom_oca_manifest_int` adds
`ocah-submodules-init` to **both** `ocah.mk` and `.gitlab-ci.yml`. The `ocah.mk` half is
already in main and arrives with the merge; **the `.gitlab-ci.yml` half must be dropped, not
cherry-picked.**

**Do not confuse this with `.github/workflows/vp.yml`.** That file is also absent from main,
but for the opposite reason — it is VP payload that arrived with `c3682138d` (PR #1586) and
main has never seen it. It is *kept*. Both sit in the same "main does not have this file"
bucket and want opposite treatment, so decide by *why* main lacks the file, never by the fact
that it does.

---

## 4. The 25 redundant commits

Of `_clean`'s 33 commits beyond the feature branch: **8 VP-only, 25 ROM/DV/doc, zero mixed.**

```bash
git rev-list --no-merges origin/feature/sep_virtual_platform..origin/inmcm/integrate_oca_boot_manifest_clean |
while read c; do
  p=$(git show --name-only --format="" $c | grep -v '^$')
  v=$(echo "$p" | grep -c '^virtual_platform/'); t=$(echo "$p" | wc -l)
  [ "$v" -eq "$t" ] && echo VP-only || { [ "$v" -eq 0 ] && echo ROM/DV/doc || echo MIXED; }
done | sort | uniq -c
```

The 8 VP-only commits (these, plus `c3682138d` from §1, are the payload that must survive):

```
5742e3e22  vp: Provision CLASS_KEY for encrypted boot and uprev the harness model
b502c47ad  vp: Add OCA boot coverage and an eFuse map drift guard
c79344b1b  vp: Expect the library's signature-class refusal for unsigned images
308dec0d0  vp: Add per-slot ROM key use, revoke and isolate coverage
da159b3e7  vp: Drop the Grendel signed-image target and fixture
24019521f  vp: Fingerprint status-table contents in the VP config signature
1ea6abd07  vp: Point manifest tooling paths at tt-oca-manifest
0960d2908  vp: Uprev tt-oca-harness-model to main for the entropy-source work
```

The 25 ROM/DV/doc commits are **earlier variants** of work the ROM branch has since redone and
refined. `_clean` is not an ancestor of `sep_rom_oca_manifest` — they are siblings off
`99bb553c2` sharing 27 commit subjects. So main's versions supersede `_clean`'s, and you
resolve in main's favour rather than trying to reconcile them line by line.

---

## 5. Recommended route

**Step 0 — pick up `c3682138d` first** (§1), independently of #1590. Merging
`origin/feature/sep_virtual_platform` into `_clean` brings it as one commit and keeps `_clean`
a true superset of the feature branch again, which is what the rest of this plan assumes. Do
this now; it does not depend on main. Re-check first that the feature branch has not moved
further.

> **DONE 2026-09-15** — merge commit `7831b7973`, local only, not yet pushed. Five conflicts, not
> the zero the "one commit" framing suggests: `c3682138d` is the *"Enable Full VP Build Targets"*
> rework. Kept `test_bootcode_ot_negative.py` deleted (`b502c47ad` replaced it) and
> `pytest_plugin.py` ours (the feature side's edit is AST-identical to the base — formatting
> only); unioned `config.py` and `pyproject.toml`; took the feature branch's `help.mk` docblocks
> and smc/smu/whisper targets in `virtual_platform/Makefile` while keeping our OCA prose and the
> deleted `boot-secure-image`. `tt-oca-harness-model` fast-forwarded `416200e` → `37474d5` (ours
> was an ancestor, so the entropy uprev survives); its dropped nested `csml` submodule needed its
> orphaned worktree cleared by hand. `c3682138d` also switches on the ruff gate over
> `virtual_platform/`, which this branch's OCA test files predated — fixed (1 unused import, 4
> import sorts, reflow; no behavioural change). §8's containment gate now passes.

**Then wait for #1590 to land on main, and merge `origin/main` into `_clean`** — do not
rebase, for the same reasons the old plan gave.

Resolution rule, applied by path:

| Path | Resolution |
|---|---|
| `virtual_platform/**` | **keep `_clean`'s** — main has none of it |
| `hw/sys/sep/bootrom/**`, `hw/sys/sep/dv/**`, `hw/sys/sep/doc/**`, `tools/dv/**` | **take main's wholesale** — these are the 25 superseded commits — *except the files in the last two rows* |
| `.gitmodules` | **keep `_clean`'s** (§3.1) |
| `hw/sys/sep/bootrom/prod/Makefile`, `pyproject.toml`, `.gitignore` | **hand-merge, union** |

**Two rows overlap on exactly one file, and the order you apply them in decides the outcome.**
`hw/sys/sep/bootrom/prod/Makefile` is the only entry in the last two rows that row 2's
`hw/sys/sep/bootrom/**` glob *also* matches (`.gitmodules`, `pyproject.toml` and `.gitignore` sit
outside it and are never at risk). Applied mechanically by path, row 2 wins on that one file and
silently discards the VP's changes to it — `SHELL := /usr/bin/env` with
`.SHELLFLAGS := bash -ec`, and the rewrite that swapped the tt-boot-manifest packer prose for
tt-oca-manifest and `OCA_IMAGES`. **Treat that Makefile as an exception carved out of row 2:
resolve it by hand after row 2, and exclude it from any scripted pass over row 2's glob.** This
is §6.2 with a specific filename attached. Verified 2026-09-15:

```bash
git diff 99bb553c2 HEAD -- hw/sys/sep/bootrom/prod/Makefile   # what a wholesale take would lose
```

`git checkout --ours/--theirs` by path is the fast way, but note that trap and the ones in §6.

If the conflict volume is worse than that rule predicts, the fallback is the old plan's shape:
branch fresh off main and bring across only the VP payload (the `virtual_platform/` tree plus
the VP-specific deltas in the 15 files). Smaller and more reviewable, at the cost of `_clean`'s
commit granularity. Decide by measurement, not preference.

---

## 6. Gotchas from the ROM/DV branch that will bite you

These cost real time on the other branch in the last 24 h. Every one is measured.

1. **`git checkout --ours -- <many paths>` aborts the whole batch** if any one path lacks an
   "ours" side (deleted-by-us). It leaves *nothing* restored, and a following `git add` will
   happily stage files that still contain conflict markers. Resolve **per file**, and grep for
   `^<<<<<<< ` before every `git add`.

2. **Taking a file wholesale from one side discards the other side's cleanly auto-merged hunks
   too.** After any `git show HEAD:path > path`, re-check whether you dropped changes that had
   merged without conflict.

3. **Verify "prose-only" claims with the AST, not by eye.** To decide whether a Python conflict
   is really just docstrings, parse both sides, strip docstrings, and compare
   `ast.dump`. On the ROM branch that turned 37 conflicted files into "main changed no
   executable line in any of them", which made the resolution mechanical and safe.

4. **Console markers differ between the old ROM and the OCA ROM.** The OCA ROM prints
   `PUBK_ALGO_UNSUPPORTED`, `RSA_EXEC`, `RSA_VERIFY_OK`, `MANIFEST_OK`. Main's older ROM prints
   `BAD_SIG_TYPE`, `SIG_FAILED`, `PLD_HASH_MISMATCH`, `RSA_VERIFY_START`, `SIG_VALID`,
   `CRYPTO_VALIDATE_OK`. Taking main's *prose* wholesale reintroduces names the OCA ROM never
   emits. Grep `hw/sys/sep/bootrom/prod/src` before trusting any doc string.

5. **Stage labels were renumbered `[CNN]` → `[SNN]`** by `2761fc6b1`, deliberately, so a stale
   C-label stays obviously stale. Main still uses `[C15]`; the ROM branch uses `[S25]`. If you
   pull text from main, translate it.

6. **`public_key_select_classic` is a 128-bit BITMAP under OCA, not a packed nibble.**
   `get_public_key_sel()` returns a **slot number**. The pre-OCA `(selection & 0x7) << 4`
   formula coincides with the bitmap only at slot 16, which is why bugs here hide until you hit
   `CHIPLET_PUBK_HASH1` (slot 17). ROM slot map lives in `oca_platform.c` and is documented in
   `rom.adoc` `tbl:key_slots` — **the ROM code is the authority**, not the RDL, whose bit map
   lives only in a `desc =` prose string.

7. **Slots `[7:6]` and `[15:14]` are now RESERVED** (commit `dddde5829`, 2026-09-14). The
   classical ROM band is `[5:0]` and the PQC band is `[13:8]`. `PUBK_SLOT_UNPROVISIONED` is now
   unreachable by any manifest. If VP tests select slot 6 or 7 expecting "unprovisioned", they
   need updating to expect `PUBK_SLOT_RESERVED`.

8. **The VP got CLASS_KEY right and the DV side did not.** `virtual_platform/tests/fuse_maps/
   oca_encrypted.yaml` already carries the correct secret (`0x03020100 … 0x1f1e1d1c`, the 32
   bytes `00 01 … 1f`) with a comment explaining the word order. The DV eFuse preloads carried
   a stale 16-byte AES-128-era key and were corrected on 2026-09-14 (`e54c47e47`) to match the
   VP's value. **Do not "fix" the VP map toward the DV one** — the VP was the reference.

9. **Simulation environment.** A VCS run needs `module load synopsys/vcs/V-2023.12-SP2-9` in a
   `#!/bin/bash -l` wrapper *and* `export OCAH_TOOLCHAIN_ROOTFS=/localdev/cmccoy/
   ocah-toolchain-rootfs`. Without the rootfs, `docker-run.sh` falls back to podman and every
   `c_compile` dies on `runc create failed: ... permission denied`. See the other worktree's
   `DV_LONG_RUNS_GUIDE.md`, which is untracked on purpose until #1590 lands and then goes into
   `hw/sys/sep/dv/README.md`.

10. **Build freshness is judged on mtime, not content.** A comment-only sweep across
    `dv/fw/drivers/*.h` makes the DV firmware look stale; the host-side `make oca-images` then
    tries to rebuild `bl1_pass_test` with a RISC-V gcc the host does not have. Fix by building
    that one directory inside the sandbox — the recipe is in `DV_LONG_RUNS_GUIDE.md`.

---

## 7. Staying in sync while #1590 is still moving

#1590 is **not frozen.** As of 2026-09-14 its tip is `e54c47e47` and work is ongoing: nine
DV fixes have landed in the last day and one test
(`sep_decryption_failure_terminal_test`) is still under investigation.

Practical protocol:

- ~~**Do not start the main-merge until #1590 lands.**~~ **#1590 MERGED 2026-09-17**
  (`e65e3a57f`), so this no longer gates anything. It was **squash-merged**: main holds the ROM
  work as one commit and none of the branch's own SHAs. That does not change the plan — §4
  already treats `_clean` and the ROM branch as siblings off `99bb553c2`, so the merge base is
  unchanged and "take main's wholesale" still applies — but it does mean
  `git merge-base --is-ancestor <any ROM branch commit> origin/main` answers *no*, which is not
  evidence the work is missing. Compare file contents, not SHAs.
- **Re-measure before you act.** Every number here has a command; run it.
- **Watch these paths for changes that will reach you:** `hw/sys/sep/bootrom/prod/src/
  oca_platform.c` (the key slot model), `hw/sys/sep/bootrom/prod/doc/rom.adoc`,
  `hw/sys/sep/dv/tb/efuse_preloads/**` (fuse values the VP mirrors), and
  `hw/sys/sep/bootrom/prod/configs/*.yaml` (what the packer encrypts/signs with).
- **The two agents share one repo but not one worktree.** They share `.git`, so a `git fetch`
  in either is visible to both — but **never check out the other agent's branch** in your
  worktree, and never `git gc`/prune while the other is mid-merge.
  **The roles swapped on 2026-09-17:** `_clean` now lives in
  `/localdev/cmccoy/dev/tt-oca-harness-main`, and `/localdev/cmccoy/dev/tt-oca-harness` moved to
  unrelated work (`rom/sep-build-type-flag`). The plan docs are untracked, so they were copied
  across by hand rather than travelling with the branch — if you land in a worktree without
  them, that is why.
- **Long simulations outlive sessions.** Before launching anything heavy, check the host is not
  already busy: `pgrep -f 'run_dv[.]py'` (the bracket matters — it stops the pattern matching
  its own command line).

---

## 8. Verification gates for the VP branch

Before proposing the merge to main:

- `git rev-list --count HEAD..origin/main` is **0**.
- No conflict markers anywhere: `grep -rn '^<<<<<<< ' --include='*' . | grep -v '^\./\.git/'`.
- Submodules resolve: `.gitmodules` has `tt-oca-manifest` and `tt-oca-harness-model`, and no
  `tt-boot-manifest`; `git submodule status` is clean.
- **The feature branch is fully contained**, which it was not on 2026-09-14:
  `git merge-base --is-ancestor origin/feature/sep_virtual_platform HEAD` succeeds. This is the
  check that catches a silently dropped PR #1586.
- **No file from main was lost.** `comm -23 <(git ls-tree -r --name-only origin/main | sort)
  <(git ls-files | sort)` should list only files the VP branch deliberately deletes — and you
  should be able to name the commit that deleted each one.
- ROM builds, and the DV flow's own config validation passes:
  `run_dv.py --dut sep --validate-configs`.
- VP suite runs — see `VP_PORT_PLAN.md` §"Verification (end-to-end, in order)" and
  `VP_PORTABILITY_PLAN.md` for the container/ambient-toolchain matrix.
- The DV side's gate, if you touched `hw/sys/sep/dv/**`: every rom_fw leaf must reach a
  PASS-form `CHK-<ID>` record (the `#1783` evidence gate; see issue #1780 for its history).

---

## 9. Do not

- Rebase or force-push `feature/sep_virtual_platform` (§1).
- Rewrite `_clean` in place if you choose the rebuild fallback — build beside it.
- Reintroduce `tt-boot-manifest` (§3.1).
- Reintroduce `.gitlab-ci.yml`. Main removed it deliberately, for security (§3.2). The merge
  deletes it cleanly; do not hand it back via the fallback route or a `checkout --ours` batch.
- Fix `tt-oca-manifest` content in this tree — it is a separate internal repo (§3.1).
- Leave two PRs open claiming to deliver the VP (§1). #1028 is closed as of 2026-09-15; #1588
  is still open against `feature/sep_virtual_platform` and needs repointing or closing.
- Ship without `c3682138d` (PR #1586). `_clean` predates it, so nothing will conflict or
  complain — the work just quietly disappears (§1, §8).
- Repoint #1588 at `main` before the main-merge is done — it would advertise `_clean`'s 25
  superseded ROM/DV/doc commits as VP work (§1, §4).
- Trust any number in this document without re-running its command. It was true on
  2026-09-14, partly re-measured 2026-09-15, and the branches move.

---

## 10. Reference docs in this worktree

| Doc | What it holds |
|---|---|
| `MAIN_REBASE_PLAN.md` | the ROM/DV/doc → main plan; §"The VP branch" is superseded only on the delivery route |
| `BRANCH_CLEANUP_PLAN.md` | how `_clean` was split out of `inmcm/integrate_oca_boot_manifest` in the first place; the commit map |
| `VP_PORT_PLAN.md` | how the VP was ported from `tt-oca-hw`; target layout, verification order |
| `VP_PORTABILITY_PLAN.md` | removing internal tooling paths; container vs ambient toolchain |
| `OCA_MANIFEST_PLAN.md` | the OCA manifest format work |
| `SEP_ROM_DOC_PLAN.md`, `SEP_ROM_PLAN.md` | ROM documentation and ROM work plans |

In the other worktree (`/localdev/cmccoy/dev/tt-oca-harness-main`), all untracked on purpose:
`DV_LONG_RUNS_GUIDE.md` (simulation playbook), `ROM_FW_REGRESSION_TRIAGE.md` (failure triage),
`EVIDENCE_GATE_ROM_FW_TICKET.md` (issue #1780 background),
`OCA_CLASS_CONTROL_DOC_TICKET.md` (a fix owed to `tt-oca-manifest`).
