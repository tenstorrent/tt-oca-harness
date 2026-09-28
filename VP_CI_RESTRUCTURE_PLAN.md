# Restructure VP CI: cheap pull requests, heavy verification post-merge

**Status:** proposed
**Area:** `.github/workflows/vp.yml`, `virtual_platform/sepvp/pytest_plugin.py`, `virtual_platform/tests/`
**Raised:** 2026-09-22, from VP CI debugging on PR #2065
**Decisions taken:** GitHub-hosted runners assumed (`VP_CI_RUNNER` not available soon); heavy legs move to post-merge + nightly

## Context

`vp.yml` currently costs ~8 runner-hours per push and routinely fails on
infrastructure rather than on the VP. Measured across six runs:

| step | observed |
|---|---|
| **Provision toolchain image** | **1h42m – 2h09m** (11 of 12 observations) |
| Build smc-vp + smu-vp | 2m28s – 14m40s |
| Build sep-vp | 3m28s – 8m28s |
| Run the pytest suites | ~2m20s |
| SMC / SMU firmware suites | ~2m / ~2.5m |

The VP work is ~10–25 min. Provisioning is 85–90% of wall-clock, and three jobs
build the *same* image concurrently. It has never once been served from cache.

Root causes, all confirmed this session:

1. **The "native" legs are not native — but not because picolibc is missing.**
   The existing "Check toolchains" step records
   `picolibc: riscv64-unknown-elf-gcc works on the runner; firmware builds there`
   on every native run, so the apt toolchain is fine and
   `_native_fw_toolchain()` passes. The container dispatch happens one level
   lower: `hw/sys/sep/bootrom/prod/Makefile:32` defaults `RISCV_TOOLCHAIN ?=`
   empty, and its `toolchain-images` recipe branches on that variable, not on
   the Python probe — so with it unset the recipe sends the build to
   `docker-run.sh run-here` regardless. Inside the container `ocah_deps.nix:27`
   sets `RISCV_TOOLCHAIN` to the nix toolchain, which is why a "native" job's
   log carries 354 `/nix/store/...-riscv-toolchain/bin/riscv64-unknown-elf-ld`
   lines and why that job builds a 2h image it otherwise never uses. It is also
   where the venv clobber happened: inside that container, `uv run` rebuilt the
   bind-mounted `.venv` with default groups.
   (The `[bootrom] RISCV_TOOLCHAIN is unset` banner that would have shown this
   sits near the start of the make's stdout, which `res.stdout[-2000:]` in
   `pytest_plugin._make` truncates away — it is not absent, just unlogged.)
2. **The image cache key drifts from the image identity.** The key hashes
   `flake.nix/flake.lock/ocah_deps.nix/nix/**`, but `nix/packages/whisper.nix:13`
   and `nix/packages/openssl-merged.nix:13` also read
   `virtual_platform/tt-oca-harness-model/.github/workflows/ci-rhel8.yml` for
   `WHISPER_REV`/`OPENSSL3_VERSION`. Re-pinning the model changes the image hash
   but not the key: the restore "hits", the tarball name doesn't match, it
   rebuilds, and `actions/cache` then *declines the save as a duplicate key* —
   a permanent cache miss until something in the hashed list changes.
3. **Saves only happen on job success.** Every red test run discarded a 2h build.

Decisions taken: assume GitHub-hosted runners (`VP_CI_RUNNER` not soon); heavy
legs move to post-merge + nightly.

Outcome intended: PRs run 23 host-only tests in ~2 min with no nix, no
container, no toolchain. Post-merge runs full coverage, with the image built at
most once per change to nix inputs.

## Changes

### 1. Make the native legs genuinely native — `.github/workflows/vp.yml`

Point the bootrom at the toolchain the job already installs, so its
`toolchain-images` recipe stops dispatching to the container:

- on the native leg only, export `RISCV_TOOLCHAIN=/usr/bin` (a *bin dir*, per
  the Makefile's own comment). `RISCV_PREFIX` then auto-detects
  `riscv64-unknown-elf-` via its `$(wildcard $(RISCV_TOOLCHAIN)/riscv64-unknown-elf-gcc)`
  test, and `GCC_PREFIX` resolves to `/usr/bin/riscv64-unknown-elf`.
- set it from a step gated on `matrix.mode == 'native'` writing to `$GITHUB_ENV`,
  mirroring the existing "Point the image cache at the runner temp dir" step, so
  it never leaks into the container leg.
- extend the existing "Check toolchains" step to **assert** on the native leg
  rather than only report, matching the `smc-smu-vp` job's house pattern
  ("Assert rather than just print").

Then gate `Provision toolchain image` on `matrix.mode == 'container'`, matching
the `smc-smu-vp` job which already does exactly this (line 630 vs line 295).

Effect: native firmware builds run against the host `.venv`, which carries the vp
group — so the venv-clobber path disappears for native legs, and they never touch
nix or docker.

### 2. Split the triggers — `.github/workflows/vp.yml`

- New job `vp-host-tests`: checkout, private submodules when the token exists,
  `astral-sh/setup-uv`, `make -C virtual_platform vp-py-deps`, then
  `pytest tests -m hostonly`. No nix, no container, no toolchain.
- Gate `sep-vp` and `smc-smu-vp` with `if: github.event_name != 'pull_request'`.
- Keep the existing `paths:` filters, `concurrency` block and
  `timeout-minutes: 180`.

`push: branches:[main]`, `schedule` and `workflow_dispatch` already exist and
need no change — this only removes the heavy legs from `pull_request`.

### 3. Mark the host-only tests — `virtual_platform/sepvp/pytest_plugin.py` + 2 test files

No marker currently selects the pure bucket, and `-m` cannot express it
(`test_bootcode_oca_rom_keys.py` has no `pytestmark`), so a path list would be
brittle. Register `hostonly` in the plugin's existing `_MARKERS` list and add
`pytestmark = pytest.mark.hostonly` to:

- `virtual_platform/tests/test_fuses.py` (20 tests)
- `virtual_platform/tests/test_efuse_map_drift.py` (3 tests)

New host-only tests then opt in by marker rather than by editing CI.

Adjust the existing "Gate on tests having run" logic for this job: it must still
fail when everything skips, but the expected non-skipped count is now 23 (20 if
the model submodule is absent, since `test_efuse_map_drift.py` skips on a missing
model header).

### 4. Fix the image cache for the container legs — `.github/workflows/vp.yml`

- **Key on the image identity, not a file list.** Add a step that computes
  `nix eval .#containerHashes.<variant>` (exactly what `docker-run.sh`'s
  `image_hash()` already does) into `$GITHUB_OUTPUT`, and use it as the cache
  key. This closes the model-submodule drift gap in cause 2 and removes the
  hand-maintained `hashFiles` list, including the `-uv` suffix added in
  `f4d5cddf8`.
- **Split restore from save.** Replace `actions/cache` with
  `actions/cache/restore` before provisioning and `actions/cache/save`
  immediately after it, so a red test run still banks the image.
- **Provision once — deferred, not implemented.** A precursor job that both
  container legs `needs:` would stop them building the same image twice on a
  cold run. It was left out: GitHub Actions has no YAML anchors, so it would
  duplicate checkout, submodules, nix install, disk reclaim and store
  relocation, and it adds a serialisation point to *every* run (including warm
  ones) to save ~2 runner-hours only on the rare runs where nix inputs changed.
  Revisit if cold post-merge runs become a problem.

Because the heavy jobs now run only on `main`/schedule, saves are main-scoped —
so there is one image in the 10 GB budget, inheritable by every branch, with no
cross-PR thrash.

### 5. Keep, and explicitly do not do

Keep: `OCAH_IMAGE_WITH_UV=true` (`0391641a6`) — the container legs still need the
uv variant for `PYTHON`/`OTBN_PYTHON`/`VP_PYTHON`/`UV_NO_SYNC`; the
`PYTHON`/`OTBN_PYTHON` override in `_make`; the nix-store relocation step.

### The devShell suggestion, and why change 1 supersedes it

Review feedback proposed `nix develop` instead of building the container, on the
grounds that it is several GB smaller. That is correct on its own terms, and the
enabling detail checks out: `nix/container.nix` computes `hash` from
`passthru.imageTag`, which is eval-only, so entering the shell does **not** build
an image. It avoids image layering, the ~3 GB tarball and `docker load` — real
disk, given a runner has already died with `No space left on device`.

What it does not avoid is the closure. The devShell needs all 48 locally-built
derivations (`gcc-riscv64-unknown-elf` ~24m, `openssl-merged` ~24m, `picolibc`
~18m, `systemc` ~9m, plus whisper and boost). In the measured 126-minute step,
builds spanned ~92 min; layering, tarball and load are the remaining ~34 min. So
the shell saves roughly a quarter of the time and the tarball's disk, and leaves
~1h30m of closure build in place.

**Under this plan it has nothing left to do.** Its purpose was to put a
picolibc-capable toolchain on the *native* legs so they stop falling back to a
container. Change 1 does that from apt — already installed by the job — in
seconds rather than ~1h30m. The *container* legs exist precisely to exercise
`docker-run.sh run-here`, so they need a real image by definition and cannot use
the shell. Native legs no longer need nix; container legs cannot use the shell.

**It is therefore plan B for change 1, not dead.** If Ubuntu's gcc cannot resolve
`picolibc.specs` after the symlink, converting the native legs to
`nix develop .#with_uv_deps` is the fallback: it pays the closure build but
avoids the image and its disk. Also worth revisiting if `VP_CI_RUNNER` ever
points at persistent runners, where a warm store makes the closure cost vanish
and the shell becomes strictly better than the image.

Note this reverses the earlier "both together in this PR" decision, which had
endorsed doing the devShell conversion alongside the trigger split. The
measurements above are what changed the case; overrule if you would still rather
have it in this change.

## Validating the full matrix before merging

`workflow_dispatch` is already a trigger, and gating the heavy jobs on
`github.event_name != 'pull_request'` means a manual dispatch runs **exactly**
the post-merge job set. A dispatch also runs the workflow definition *from the
selected ref*, so the branch's own `vp.yml` is what executes:

```bash
gh workflow run vp.yml --ref inmcm/integrate_virtual_platform
gh run list --workflow vp.yml --branch inmcm/integrate_virtual_platform --limit 1
```

So the full sep-vp and smc/smu matrices, both native and container, can be run
against the PR branch before merging. Three things to know:

- The dispatch runs the **branch ref**, not the PR's merge ref. To make it
  equivalent to post-merge, merge `main` into the branch first — otherwise it
  tests the branch as-is, which is not what will land if `main` has moved.
- `concurrency` keys on `github.event_name`, and `cancel-in-progress` is true
  only for `pull_request`, so a dispatched run will not be cancelled by further
  pushes to the PR. It also cannot cancel an in-flight nightly.
- Caches written by the dispatch are scoped to `refs/heads/<branch>`, so repeat
  dispatches on the same branch get a warm image, but the first post-merge run
  on `main` is still cold and pays the ~2h once to populate the main-scoped
  entry that all later branches inherit.

## Verification

1. Local, no build: `uv run --project . --group vp --locked python3 -m pytest virtual_platform/tests -m hostonly`
   → expect **23 passed**, nothing built, seconds.
2. Confirm the marker selects exactly the intended set:
   `... -m hostonly --collect-only -q` → 23; `... -m "not hostonly" --collect-only -q` → 63.
3. Push the branch → the PR run shows **only** `vp-host-tests`, ~2 min, and no
   `Provision toolchain image` step anywhere.
4. `workflow_dispatch` → full matrix. Check in the native leg's log that
   `Provision toolchain image` is skipped and that the bootcode build's
   `riscv64-unknown-elf-*` paths are **not** under `/nix/store` (that is the
   signal it built natively rather than falling back).
5. Dispatch a second time with no nix changes → provisioning should log
   `docker-run: loading ... from cache` and take ~1–2 min.
6. `gh api repos/tenstorrent/tt-oca-harness/actions/cache/usage` → total stays
   well under 10 GB with a single `ocah-image-*` entry.

## Risks

- **Change 1 cannot be rehearsed locally** (no RISC-V toolchain on this host),
  but its premise is now evidence-backed rather than inferred: the probe verdict
  is in the logs, and the Makefile branch causing the dispatch is explicit at
  `hw/sys/sep/bootrom/prod/Makefile:32-34`. The residual risk is only whether
  `/usr/bin` is the right bin dir on the runner image; the assert added to "Check
  toolchains" turns a wrong value into a fast, clear failure rather than a silent
  2h image build.
- A PR that changes nix inputs gets no container-leg signal until merge. That is
  the accepted trade of moving heavy legs post-merge.
- GitLab pipelines are currently red on both #2065 and #2184 for unrelated
  reasons; they are not a dependable gate today either way.
