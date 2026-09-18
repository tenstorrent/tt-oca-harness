# Agent Guide for tt-oca-harness

This guide helps AI agents navigate and work with the Open Chiplet Atlas
Harness (OCAH) repository. It covers environment setup, the container-based firmware
toolchain, running firmware-driven DV, and how to debug failures without chasing the wrong
layer. Machine- and site-specific values are left as placeholders; substitute your own.

## Editing this guide

A guide that is confidently wrong costs more than one that is silent, because a reader has no
reason to doubt it. Three rules keep it worth trusting.

- **Keep it current with the repository.** Any change that materially affects what is written
  here — a renamed target, a flow that gains a block, a moved directory, a fixed failure mode
  — should update this file in the same pull request. Verify claims against the tree rather
  than from memory, and prefer pointing at the authoritative file over restating it, since a
  pointer cannot drift.
- **Keep proprietary material out.** Nothing from `nonfree/` belongs here: not its internals,
  tool names, site paths or procedures. Note that the companion exists, say what a reader
  without it should arrange instead, and refer to its own scripts for the detail.
- **Keep it generic.** No personal paths, hostnames, usernames, tool versions or one-off
  workarounds. Use placeholders for anything machine- or site-specific, and write so the
  guidance still holds for someone with a bare clone and no site tooling.

## Read the repository documentation first

This repo documents itself well, and nearly every environment question below is answered
somewhere in it. Read these files properly rather than grepping them for keywords — a
partial read costs far more time than a full one.

| Document | What it answers |
|---|---|
| `README.md` | Repository layout, doc builds, register generation, DV firmware targets, vendoring |
| `CONTRIBUTING.md` | License headers, lint/format CI jobs and their local equivalents, issue/PR pointers |
| `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md` | Issue forms and PR body that GitHub and CI expect |
| `doc/starting/` | Getting Started/Contributing how-to (issues, PRs, and the rest of the guide) |
| `.github/issue-taxonomy.yml` | Allowed Workstream / Subsystem / Component (and optional Priority / Target release) values |
| `.github/ISSUE_CURATION.md` | Project curator; catalog weekly-issue-activity and discussion-task-miner (`automation.enabled`) and compile |
| `tools/docker/README.md` | Container images, `docker-run.sh` subcommands, which toolchain lives where |
| A testbench's own `README` — `hw/<ip\|sys>/<block>/dv/<tb dir>/README.md` or `.adoc` | Testbench usage, regression mechanics, log file locations |
| `hw/common/dv/fw/` | Shared firmware build engine (`compile.mk`), link modes, toolchain checks |
| `nonfree/setup_env.sh` | Environment setup — *proprietary companion, only present with access* |

`make doc-trm-serve` builds a TRM-first preview with the other documentation
products included, since the TRM links to their pages. Its Make dependencies
and container equivalent are defined in `doc/trm/doc.mk` and
`scripts/docker-run.sh`; `antora-trm-playbook.yml` selects the content.

## Environment Setup

The `nonfree/` companion is not part of the open repository. If you have it, it sets the
whole environment up for you; if you do not, arrange the same prerequisites yourself. Both
paths are supported, and everything else in this guide applies either way.

### With the `nonfree` companion

Source the setup script **once per terminal session**, from the repository's physical path:

```bash
cd "$(pwd -P)"            # from the repository root; see the note on symlinked checkouts
source nonfree/setup_env.sh
```

Read `nonfree/setup_env.sh` if you need to know what it sets up. Whatever it does, verify
afterwards that `bender`, `python3` and your simulator's executable all resolve:

```bash
for t in bender python3 <simulator>; do printf '%-12s %s\n' "$t" "$(command -v "$t" || echo MISSING)"; done
```

> **Do not pipe the `source` command.** `source nonfree/setup_env.sh | tail -20` runs the
> script in a subshell and silently discards every export — the script prints its success
> banner while your shell gets nothing. Redirect to a file instead:
> `source nonfree/setup_env.sh > "$TMPDIR/envsetup.log" 2>&1`.

A tool already on your `PATH` can take precedence over the version the script would otherwise
select, so record which versions you actually used when reporting a failure — and do not blame
the simulator without an A/B that shows it is the cause.

### Without it (open tree only)

Provide the equivalents yourself:

- A SystemVerilog simulator and `bender` on `PATH`. Each testbench README states what that
  testbench expects.
- Python 3 for cocotb and the register/DV tooling.
- A container engine — Docker or Podman — for the firmware toolchain image, which
  `scripts/docker-run.sh build` builds locally from `tools/docker/Dockerfile`.
- `TMPDIR` pointed at a large local scratch directory (see below).

Nothing here is exotic. `scripts/docker-run.sh` documents its own environment variables in its
header, and with the optional ones unset — notably `OCAH_DOCKER_CACHE_DIR` and
`OCAH_TOOLCHAIN_ROOTFS` — it builds and runs the image itself, which is the behaviour
`tools/docker/README.md` documents as the default. Doc builds, register generation, lint and
format targets need no site tooling at all.

### Work from the physical path if your checkout is reached through a symlink

`scripts/docker-run.sh run-here` bind-mounts the *resolved* repository path but takes the
container working directory from `$PWD`. If you reach the checkout through a symlink, the
two disagree and the container refuses to start:

```
Error: workdir "<symlinked path>" does not exist on container …
```

Use `cd -P` (or `pwd -P`) so both agree. Harmless if your checkout is not symlinked.

### Scratch/temp space: honour `$TMPDIR`, never `/tmp`

**Use the scratch directory the environment already defines, and do not invent your own.**
Shell setup files (`~/.bashrc`, `~/.profile`, a site profile script or equivalent) normally
export `TMPDIR` pointing at a large local filesystem. Honour it for every sim, build, log
and scratch file:

```bash
echo "${TMPDIR:-<unset>}"
```

If `TMPDIR` is unset, look for the intended location in those shell setup files rather than
guessing, and ask if it is still unclear. Do not fall back to `/tmp`: it is typically small
and shared across the host, so a runaway sim log can fill it and take the machine down with
it. `$HOME` is a poor substitute wherever it carries a quota, since a single container image
store will exhaust it.

If `TMPDIR` names a directory that does not exist, Make reports
`TMPDIR value …: No such file or directory` and silently falls back to `/tmp`, so create it
first (`mkdir -p "$TMPDIR"`). When redirecting logs, target `$TMPDIR` or the testbench's own
`sim/logs/`, never `/tmp`.

### Keep container storage off a small or quota'd `$HOME`

An image store accumulates tens of GB. Rootless Podman keeps it under
`~/.local/share/containers` by default, so wherever the home filesystem is small or quota'd
it runs out of space part-way through a pull or build:

```
open …/storage/overlay-layers/layers.lock: no space left on device
```

Relocate the store onto the same roomy filesystem you use for scratch by setting `graphroot`
in `~/.config/containers/storage.conf`. That file takes literal paths and does not expand
environment variables:

```ini
[storage]
driver = "overlay"
graphroot = "<scratch path>/containers/storage"
```

Leave `runroot` unset so per-boot state stays on the `$XDG_RUNTIME_DIR` tmpfs. Add whatever
`[storage.options.overlay]` settings your host requires — rootless overlay commonly needs
`ignore_chown_errors` and a `mount_program`. `scripts/docker-run.sh` passes its own overlay
options on the command line, so mirroring them in this file keeps plain `podman` behaving
like the wrapper. Confirm the result with `podman info | grep -i graphroot`.

Cleaning up Podman directories needs `podman unshare rm -rf …`; plain `rm -rf` fails with
permission errors because the files are user-namespace mapped.

## Containers and the firmware toolchain

The RISC-V DV firmware toolchain normally comes from the `ocah-toolchain` container image.
All subsystems compile with `--specs=picolibc.specs`, and a stock or site RISC-V toolchain
often lacks picolibc, so a native build fails with a message pointing you back at the
container. A host toolchain that does provide it works too — point `RISCV_TOOLCHAIN` at it.

That one image also carries the OCAH virtual platform's toolchain (g++, cmake, Boost,
OpenSSL, the runner's Python), so `make -C virtual_platform vp VP_CONTAINER=1` builds and
runs `sep-vp` in it. The `vp-*` subcommands are aliases onto the same image.

The model builds three VP executables and the harness builds all three. `sep-vp` is the
default; `smc-vp` and `smu-vp` (the SMC+SEP integration, which runs both subsystems in
one process) are **opt-in**, because asking for either first builds the Whisper ISS into
`local/` — `make vp` never does, and needs no Whisper. They share a second build tree,
`vp/build_smc`, since `WHISPER_HOME` is read at configure time and decides whether those
platforms are generated at all. Their tests delegate to the model's own
`sw/{smc,smu}-vp-tests` runners rather than the SEP-specific `sepvp` package. The image
needs no extra packages for them.

```bash
make -C virtual_platform smc-vp smu-vp VP_CONTAINER=1
make -C virtual_platform smc-test VP_CONTAINER=1   # SMC_ARGS=<one-test>
make -C virtual_platform smu-test VP_CONTAINER=1   # SMU_ARGS=<one-test>
```

`smu-vp` has a companion artifact, `libsmc_cluster_smu.so`, built beside the target
rather than into `bin/`. `smu-vp` bakes that build-tree path into its RUNPATH, so it runs
in place — but a copy made without the `.so` binds silently to the build tree and then
fails once that tree is gone. Carry both, or source the generated
`setup_environment*.sh`, which puts its directory on `LD_LIBRARY_PATH`.

```bash
./scripts/docker-run.sh build     # build the image once
./scripts/docker-run.sh verify    # prints the compiler version and multilib list
./scripts/docker-run.sh vp-verify # the VP side: g++ and cmake versions
```

On a host with both podman and docker installed, `OCAH_ENGINE=docker` (or `podman`) pins
which one `docker-run.sh` uses instead of taking whichever it finds first.

With the companion's `OCAH_DOCKER_CACHE_DIR` set, `docker-run.sh` loads the image from that
shared cache instead of building it; otherwise it builds locally from the Dockerfile.

A testbench that builds firmware as part of its own flow dispatches those builds through
`scripts/docker-run.sh run-here`, so the container is used automatically while the simulator
runs natively on the host. Not every testbench does this — check its Makefile rather than
assuming.

When `OCAH_TOOLCHAIN_ROOTFS` points at an extracted toolchain rootfs and `bwrap` is
installed, `docker-run.sh` uses bubblewrap instead of a container engine. The rootfs must
come from the merged image: both `usr/bin/riscv64-unknown-elf-gcc` and `usr/bin/g++` are
probed, and a rootfs missing either is rejected up front with a warning and an automatic
fall back to the container engine. It is an opt-in either way: the companion sets it for
you, and anyone can set it by hand. That path fails
when the checkout sits on a filesystem whose mountpoint bwrap cannot create inside its
read-only rootfs, typically a networked or site-specific mount:

```
bwrap: Can't mkdir parents for <repository path>: Read-only file system
```

`unset OCAH_TOOLCHAIN_ROOTFS` to fall back to the container engine.

### Rebuilding the image invalidates existing firmware objects

Only the Dockerfile's base image is digest-pinned; the packages installed on top of it
float with its upstream distribution (`tools/docker/README.md` says so explicitly). A
rebuilt image can therefore carry a different compiler and C library than the image that
produced the objects already sitting in `hw/**/dv/fw/build/`.

Make tracks source timestamps, not toolchain identity, so unchanged drivers are **not**
recompiled and the link silently mixes old objects with the new C library. The resulting
images load into ROM but never execute. **After any `docker-run.sh build`, image cache
refresh, or toolchain change, clean the firmware explicitly:**

```bash
make -f ocah.mk ocah-dv-fw-clean TARGET=<block>
```

Simulation-side `clean` targets remove simulation artifacts only; none of them clear
`dv/fw/build/`, and some say so when they run. Because the firmware's *sources* are
unchanged, nothing downstream can tell the images are stale with respect to the toolchain —
a full regression included.

## Building and running firmware-driven DV

Building firmware images is repo-wide: every subsystem plugs into the shared engine in
`hw/common/dv/fw/`, driven through the same dispatcher targets.

```bash
make -f ocah.mk ocah-dv-fw-tests TARGET=<block>              # all test images for a block
make -f ocah.mk ocah-dv-fw-tests TARGET=<block> TEST=<name>  # one image
make -f ocah.mk ocah-dv-fw-clean TARGET=<block>              # clear that block's dv/fw/build/
```

*Running* those images is the testbench's job, and that interface is per-block. Target names,
parallelism knobs, firmware-print switches and waveform flags are defined by each
`dv/tb*/Makefile` and are not shared, nor does every block with firmware offer a full
regression target. Read the testbench directory's README — and `make help` where it exists —
before running anything, and do not assume a target you used on one block exists on another.

Whatever the testbench, these hold:

- **Check the existing logs before rerunning.** Testbenches typically record complete
  per-test output — simulation stdout, testbench messages, firmware output, compile logs,
  JUnit XML — under a per-test directory such as `sim/logs/<test>/`. Read those rather than
  rerunning to see something you already captured.
- **Judge a regression by diffing its summary against your last known-good run**, not against
  an absolute pass count or wall time. Both drift as tests are added, and one long test
  usually sets the floor for total runtime.
- **Waveform dumping may be refused during a full regression** where parallel jobs share one
  simulation binary and dump path. Rerun the single test you care about with waves enabled.
- **Check that a previous run has actually finished before starting another.** Interrupting a
  wait, or closing a terminal, does not necessarily kill the process tree; two concurrent runs
  of one testbench overwrite each other's build and per-test logs, which invalidates both.

## Debugging test failures

1. **Do not add delays, settle cycles, or NOPs.** The cause is almost never "not enough
   settling time." Look for the real bug: protocol ordering, wrong register or value, a
   TB/DUT race, or a broken handshake. Fix the logic, not the clock count.

2. **Compare against a known-good run before theorising.** Keep each run's summary under
   `$TMPDIR` so diffing the pass/fail lists of two runs is trivial.

3. **Mass failures are environmental, not RTL.** If tests your change never touched are
   failing — especially the block's simplest smoke tests — suspect the build and toolchain
   first, then the state of your tree, and only then the RTL or simulator.

4. **Read the failure signatures before anything else.** Counting them across a run separates
   many independent bugs from one systemic cause. From the testbench's per-test log root:

   ```bash
   for d in */; do rg -o -i -m1 'timeout|unrecoverable|fatal|error' "$d"/*.log 2>/dev/null | head -1; \
     done | sort | uniq -c | sort -rn
   ```

5. **A test that times out having produced no firmware output never executed at all.** The
   loader still reports the image loaded and the testbench keeps counting cycles, so the
   simulation looks alive while the CPU is doing nothing. Enable the testbench's
   firmware-print option to confirm the output really is empty, then suspect the firmware
   build — stale objects above are the usual cause — rather than the simulator.

6. **Bisect with one fast test in a throwaway worktree.** A single smoke test usually costs
   under a minute including compile, so walking several commits takes minutes rather than
   hours:

   ```bash
   git worktree add "$TMPDIR/bisect" <commit>
   cd "$TMPDIR/bisect/hw/<ip|sys>/<block>/dv/<tb dir>"
   # then the testbench's own single-test target
   ```

   A fresh worktree also has no stale build artifacts, so if it passes where your main tree
   fails, the problem is the tree's state rather than any commit.

7. **Give experiments their own build directory** so a compile does not disturb a run already
   in flight; cocotb-based testbenches expose `SIM_BUILD` for this. Copy any log you care
   about out of the per-test log directory before rerunning that test, since the rerun
   overwrites it.

## Repository Structure

| Path | Contents |
|---|---|
| `hw/common/` | Shared RTL and infrastructure: `och_prim*` primitives, `tlul/`, `axi/`, `ot_chip_cfg/`, assertions, packages, `regs/` register flow, `dv/fw/` firmware build engine |
| `hw/ip/` | Reusable IP blocks, grouped by family where applicable (`cross_trigger/`, `jtag/`, `uart/` hold sub-blocks) |
| `hw/sys/` | Subsystems: `smc`, `sep`, `smu`, `dtp` |
| `hw/top/` | Top-level integration and wrapper sources |
| `doc/` | AsciiDoc products: `trm`, `integrator`, `programmer`, `user`, `appnotes`, `starting` |
| `integration/` | Generated, grouped symlink indexes for integrator-facing RDL, IP-XACT and timing constraints |
| `flows/` | Lint, format and synthesis flow makefiles |
| `vendor/` | Vendored packages as `<Org>/<Repo>/upstream/`; never hand-edit those. Modify upstream files through the sibling `patches/`, and keep TT-owned additions in `overlay/`, which `bender vendor init` leaves alone. GitHub CI runs `bender vendor diff --err_on_diff` so committed `upstream/` trees match the pinned remotes plus patches |
| `tools/` | Register, doc, DV and container tooling |
| `scripts/` | `docker-run.sh` container front door, CI helpers |
| `nonfree/` | Proprietary companion repository, present only for those with access |

## Code and Register Generation

Register collateral is generated from per-block SystemRDL under `hw/**/<block>/regs/`;
committed output always corresponds to the RDL sources.

```bash
make regen-regs
```

After adding or moving integration collateral, regenerate the grouped symlink indexes with
`python3 scripts/collect_integration.py`.

The RDL is the register specification: it describes the address map and the registers'
behaviour, not the RTL that implements them. Naming a module, a package or an address slice in
an RDL comment ties the specification to one implementation of it; leave those details to the
RTL.

## Coding Guidance

These rules hold for every language in the tree. Where the file being edited already has a
convention — a comment style, a case for constants — follow it rather than one carried in from
elsewhere.

### Comments

Write a comment only to tell the reader something the code cannot: a constraint, an ordering
that matters, a hardware behaviour a maintainer would otherwise have to rediscover. State it in
the present tense, as something that is true of the code, not as an account of what changed.

Three kinds of comment are not worth their space.

- **Narration.** Restating the line below it costs reading time and returns nothing.
- **Breadcrumbs.** Why a change was made, what it replaced, or which review asked for it belongs
  in the commit message, which stays accurate; a comment recording it is wrong after the next
  edit.
- **Justification.** Arguing that a change is correct addresses a reviewer who is gone once the
  pull request merges.

Present tense does not save a breadcrumb. A comment that lists side effects the new
control flow no longer has is still a breadcrumb. A plan that asks for that comment
does not override this section. After adding a comment, re-read it against these bans
and delete it if it fails.

Where a test can carry the constraint instead, prefer the test: it fails when the constraint is
broken, and a comment does not.

### Names

A name is held to the same rule as a comment. An identifier that describes what changed — a
field named for the size a region used to have, a constant named after a mode that was
replaced — dates as quickly as a breadcrumb, and it forces a comment to explain a concept the
code no longer has. Name what exists.

## Commit Conventions

Follow the existing history: a lowercase path-like scope (one to three
segments, or a filename when that file is the change), a colon, a space,
then an imperative sentence-case summary, with the PR number appended when
one exists. A change that spans several trees uses `treewide`. This is not
Conventional Commits: do not use `feat`, `fix`, `chore`, or `feat(scope):`.
Do not use an issue taxonomy prefix (`[RTL/SMC]`) on a commit or PR title.

```
dv: Add the SEP smoke regression list and wire sep into CI (#243)
hw/smc: Reject unmapped register accesses instead of aliasing live registers
tools/dv: Guarantee per-leaf JUnit XML across frameworks (#283)
doc: Regenerate stale uart and smc reset_unit register collaterals (#282)
```

- Explain *why* in the body, not just what changed.
- Keep pull requests focused; unrelated changes belong in separate PRs.
- Every hand-authored file needs an SPDX header — see `CONTRIBUTING.md` for the exact form
  per file type.

## Issues and pull requests

When you open an issue or pull request on behalf of the user — `gh issue create`,
`gh pr create`, or the GitHub API — follow the same templates humans get in the UI.
Do not invent a free-form body. Blank issues are off; security reports are not public
issues (see `SECURITY.md`).

Read `.github/ISSUE_TEMPLATE/` and `.github/PULL_REQUEST_TEMPLATE.md` rather than
restating them. Allowed taxonomy values live in `.github/issue-taxonomy.yml`.

### Issues

Pick one form: Bug, Task, or Feature (`gh issue create --type Bug|Task|Feature`).
`--template` is interactive, so in a non-interactive session pass `--body` that still
uses the form headings ingest parses (`### Workstream`, and so on).

Write a plain imperative title. Do not put `[Bug]:` or `[Task]:` in it, and do
not invent the taxonomy prefix. Ingest prefixes from the form picks:
`[WORKSTREAM/SUBSYSTEM]` when Component is General, or
`[WORKSTREAM/SUBSYSTEM-COMPONENT]` otherwise. `[RTL/OCAH]` below is one
example of that pattern, not a fixed string.

```bash
gh issue create --type Bug --title "<plain imperative title>" --body "$(cat <<'EOF'
### Workstream

RTL

### Subsystem

OCAH

### Component

General

### Priority

P2

### Target release

Future

### What happened

<what broke, where, what you expected>
EOF
)"
```

Required: **Workstream**, **Subsystem**, **Component** (use `General` if unsure),
**Priority** (P2 if unsure), and **Target release** (`Future` if unscheduled).
Do not set a GitHub milestone. Description heading is **What happened** (Bug),
**Goal** (Task), or **What and why** (Feature); it is optional.

Do not add labels, assignees, or a milestone. Ingest copies those form picks
onto empty Project 291 fields, applies matching labels, and prefixes the
title. The curator fills leftover fields, assigns, copy-edits titles
and bodies, nudges approved PRs that are still open after 3 days, and
reminds assignees 3 days before a milestone or issue due date on its
05:00 and 16:00 PDT runs and on dispatch. The weekly
issue-activity and discussion-miner workflows are in
`.github/ISSUE_CURATION.md`.

### Pull requests

`gh pr create --body` replaces the template, so include the headings yourself.
Summary and Test plan are optional guidance; CI does not fail on them.
Add `## Closes` with `Fixes #N` only when `N` is a real issue; omit the
section if nothing closes. Never leave a bare `Fixes #`. Delete **Notes** if unused.

The title is the same path-like form as a commit: `scope: imperative summary`
(`hw:`, `hw/smc:`, `dv/sep:`, `github:`, `tools/dv:`). A PR that spans
several trees uses `treewide:`. Ingest does not prefix PR titles. Do not
put `[WORKSTREAM/SUBSYSTEM]` or `feat(scope):` on a PR.

```bash
gh pr create --title "hw/smc: Reject unmapped register accesses" --body "$(cat <<'EOF'
## Summary
<what changed and why>

## Test plan
<optional command, or N/A>
EOF
)"
```

Do not put Workstream / Subsystem / Component or labels on the PR.
Ingest assigns the opener when Assignees is empty. It requests a reviewer
from GitHub suggestions, then a linked-issue assignee, then recent committers
on the touched paths, then the reviewer pool in `.github/issue-taxonomy.yml`.
The curator rewrites a PR title only when it is not already this form.

### Paired pull requests with the `nonfree` companion

A change that needs both trees is two pull requests, and **the `nonfree` one merges first.**
Nothing in the open tree records which companion commit to use: `ocah-nonfree-init` clones
the companion's default branch, and `nonfree/` is ignored rather than tracked, so there is
no ref to bump and nothing to `git add`. Every pipeline — the open `main`, and every other
contributor's in-flight PR — picks up whatever the companion's default branch holds at the
moment that pipeline runs. Merging the open half first breaks CI for everyone until the
companion catches up, and it breaks it for people whose work has nothing to do with yours.

Work the pair in this order:

1. Open both PRs, and say in each body that the other exists.
2. Expect the open-tree PR's CI to fail while the companion PR is unmerged. A local branch
   proves the pair works on your machine, but no pipeline can see it and there is no pin to
   point at it.
3. Merge the companion PR, only when the user asks to merge it.
4. Re-run the open-tree PR's pipeline, and merge it only when the user asks and it is
   green — not on the strength of a run that predates step 3.

Two further things follow from the same unpinned clone:

- **Keep the companion half backwards compatible with the open `main`** wherever the change
  admits it — an added driver, an overridden weak stub, a new variable with a default — so
  that step 3 does not break the tree on its own. When it genuinely cannot be, do steps 3
  and 4 back to back and tell the user, so they can warn whoever's pipelines will fail in
  between.
- **Never paper over an unmerged companion change from the open side.** Copying companion
  material into the open tree crosses the boundary the split exists to maintain, and
  stubbing, skipping or disabling the failing check discards the signal this ordering
  protects.

If the user asks you to merge the open half first, or to merge it while the companion PR is
still open, say once — briefly, and without lecturing — what it breaks and whose work it
breaks, and offer the order above instead. **The user decides.** They may know something you
do not: that the companion change has already landed, that the tree is quiet, or that they
are accepting the breakage deliberately. So raise it once, then do as they ask and note in
the PR that the companion side is still pending. Repeating the objection, or refusing the
work, is worse than the ordering mistake.

Without companion access you can only do the open half. Say so and stop, rather than editing
open files to compensate.

## Linting and Formatting

| Check | Local command |
|---|---|
| SystemVerilog lint (slang) | `make lint-slang-all` lints every block carrying a `flow.mk`, which `flows/common.mk` discovers under `hw/sys/*`, `hw/ip/*` and vendored IP overlays; add `BLOCK=<block…>` to restrict it. `make lint-slang` from a block's own flow lints that block alone |
| SystemVerilog lint (Verilator) | `make lint-verilator-all` lints every discovered block as its own top; add `BLOCK=<block…>` to restrict it |
| SystemVerilog lint (verible) | `make lint-sv-verible`; report-only in CI while the classified legacy style backlog remains |
| SystemVerilog formatting | `make format-sv`, `make format-sv-check`; both use the same inventory as Verible lint |
| C formatting | `make format-c`, `make format-c-check` |
| Python | `make lint-python`, `make lint-python-fix`, `make format-python`, `make format-python-check` |
| TCL | `make lint-tcl`, `make format-tcl`, `make format-tcl-check` |

Each of these is an auto-generated alias for the `ocah-`-prefixed target of the same name, so
either form works. They prefer tools on `PATH` and, when one is missing, print an install hint
plus the matching `./scripts/docker-run.sh eda-run make …` command. CI runs only a subset of
them; `CONTRIBUTING.md` maps the jobs and their reviewdog checks to these commands.
The internal GitLab mirror loads its parent pipeline from a separately access-controlled
configuration project rather than from this repository, so a pull request cannot replace the
bootstrap that obtains the optional companion. Change the trusted configuration through its own
review path. That parent executes the `main` revision of `scripts/ci/diff_class.py`, rather than
the revision under test, when deciding whether a documentation-only change can skip the nonfree
child.

Verible lint and format cover hand-maintained `hw/**` sources and OCAH-owned vendor overlays.
They share the same base inventory but use separate exclusions, so a formatter limitation does
not hide findings from lint. Generated output and `vendor/<org>/<repo>/upstream/**` stay out;
never patch upstream code for a style-only finding. Fix formatter-safe whitespace and wrapping
after reviewing the diff, but treat types, range direction, assignment semantics, task
lifetime, case completeness and hierarchy labels as manual changes requiring owner review.
Parameter naming remains deferred to issue #1051 and is disabled in this pass.

Fix actionable findings rather than hiding them. Owner-local waivers belong under the source
owner's `lint/` directory: `*.verible.waiver` and `*.verilator.vlt`. Central Makefiles only
discover or pass those files, and each block `flow.mk` declares the Verilator waivers relevant
to its elaborated top. Use the narrowest diagnostic/path/hierarchy/source match and a
constraint-focused rationale. The CI-pinned Slang v11.0 has no native external-waiver support;
keep its findings visible rather than substituting whole-file suppression until a release with
TOML `--waiver-file` support is pinned.

The register generator owns `hw/common/regs/lint/peakrdl.verilator.vlt`, which the shared
Verilator flow loads for every block. Its exact path and message matches cover only PeakRDL's
`field_combo` / `field_storage` aggregate `MULTIDRIVEN` reports, including block register
modules and the copied SPI register module. They must never expand to member names or to
`WIDTHEXPAND` / `WIDTHTRUNC`. Before changing the exception, run the unwaived integrated-SMU
zero-overlap audit documented in `CONTRIBUTING.md`; its non-aggregate search must remain empty,
and the hand-authored findings must remain in the output.

`OCAH_VERIBLE_LINT_EXCLUDES` and `OCAH_VERIBLE_FORMAT_EXCLUDES` are only for documented parser,
preprocessor or formatter failures. Verible can scope by `LINT_PATH`; Slang and Verilator need
a complete block filelist, though their top can be overridden within that filelist for
diagnosis. The full scope and vendor policy are authoritative in `flows/lint/verible.mk` and
`CONTRIBUTING.md`.

Optional staged-file checks are documented in `CONTRIBUTING.md`. Agents may
run `make hooks-run` or the underlying lint/format checks without installing a
hook. `make hooks-install` modifies local Git metadata and must never be run
unless the user explicitly requests installation; setup and checkout flows
must not activate hooks automatically.
