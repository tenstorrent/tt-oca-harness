# Agent Guide for tt-oca-harness

This guide helps AI agents navigate and work with the Tenstorrent Open Chiplet Atlas
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
| `CONTRIBUTING.md` | License headers, lint/format CI jobs and their local equivalents |
| `tools/docker/README.md` | Container images, `docker-run.sh` subcommands, which toolchain lives where |
| A testbench's own `README` — `hw/<ip\|sys>/<block>/dv/<tb dir>/README.md` or `.adoc` | Testbench usage, regression mechanics, log file locations |
| `hw/common/dv/fw/` | Shared firmware build engine (`compile.mk`), link modes, toolchain checks |
| `nonfree/setup_env.sh` | Environment setup — *proprietary companion, only present with access* |

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

```bash
./scripts/docker-run.sh build     # build the image once
./scripts/docker-run.sh verify    # prints the compiler version and multilib list
```

With the companion's `OCAH_DOCKER_CACHE_DIR` set, `docker-run.sh` loads the image from that
shared cache instead of building it; otherwise it builds locally from the Dockerfile.

A testbench that builds firmware as part of its own flow dispatches those builds through
`scripts/docker-run.sh run-here`, so the container is used automatically while the simulator
runs natively on the host. Not every testbench does this — check its Makefile rather than
assuming.

When `OCAH_TOOLCHAIN_ROOTFS` points at an extracted toolchain rootfs and `bwrap` is
installed, `docker-run.sh` uses bubblewrap instead of a container engine. It is an opt-in
either way: the companion sets it for you, and anyone can set it by hand. That path fails
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
| `hw/common/` | Shared RTL and infrastructure: `och_prim*` primitives, `tlul/`, `axi/`, assertions, packages, `regs/` register flow, `dv/fw/` firmware build engine |
| `hw/ip/` | Reusable IP blocks, grouped by family where applicable (`cross_trigger/`, `jtag/`, `uart/` hold sub-blocks) |
| `hw/sys/` | Subsystems: `smc`, `sep`, `smu`, `dtp` |
| `hw/top/` | Top-level integration and wrapper sources |
| `dv/` | Verification that sits outside a single block's tree |
| `doc/` | AsciiDoc products: `trm`, `integrator`, `programmer`, `user`, `appnotes`, `contributing` |
| `flows/` | Lint, format and synthesis flow makefiles |
| `vendor/` | Vendored packages as `<Org>/<Repo>/upstream/`; never hand-edit those. Modify upstream files through the sibling `patches/`, and keep TT-owned additions in `overlay/`, which `bender vendor init` leaves alone |
| `tools/` | Register, doc, DV and container tooling |
| `scripts/` | `docker-run.sh` container front door, CI helpers |
| `nonfree/` | Proprietary companion repository, present only for those with access |

## Code and Register Generation

Register collateral is generated from per-block SystemRDL under `hw/**/<block>/regs/`;
committed output always corresponds to the RDL sources.

```bash
make regen-regs
```

## Commit Conventions

Follow the existing history: a path-like scope, then an imperative summary, with the PR
number appended when one exists.

```
dv: add the SEP smoke regression list and wire sep into CI (#243)
tools/dv: Guarantee per-leaf JUnit XML across frameworks (#283)
doc: Regenerate stale uart and smc reset_unit register collaterals (#282)
```

- Explain *why* in the body, not just what changed.
- Keep pull requests focused; unrelated changes belong in separate PRs.
- Every hand-authored file needs an SPDX header — see `CONTRIBUTING.md` for the exact form
  per file type.

## Linting and Formatting

| Check | Local command |
|---|---|
| SystemVerilog lint (slang) | `make lint-slang-all` lints every block carrying a `flow.mk`, which `flows/common.mk` discovers under `hw/sys/*`, `hw/ip/*` and vendored IP overlays; add `BLOCK=<block…>` to restrict it. `make lint-slang` from a block's own flow lints that block alone |
| SystemVerilog lint (verible) | `make lint-sv-verible` |
| SystemVerilog formatting | `make format-sv`, `make format-sv-check` |
| C formatting | `make format-c`, `make format-c-check` |
| TCL | `make lint-tcl`, `make format-tcl`, `make format-tcl-check` |

Each of these is an auto-generated alias for the `ocah-`-prefixed target of the same name, so
either form works. They prefer tools on `PATH` and, when one is missing, print an install hint
plus the matching `./scripts/docker-run.sh eda-run make …` command. CI runs only a subset of
them; `CONTRIBUTING.md` maps the jobs and their reviewdog checks to these commands.
