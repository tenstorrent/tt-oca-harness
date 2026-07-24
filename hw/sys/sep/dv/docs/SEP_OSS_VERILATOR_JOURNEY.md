<!-- SPDX-License-Identifier: Apache-2.0 -->

# The SEP OSS Verilator Journey — a plain-English story

*Branch: `yenhenglai_2026-06-27_oss_sep_verilator_public_scope`*
*Written 2026-06-28*

This is the story of how we got the open-source SEP testbench running fast and
correctly on Verilator. It was not one fix — it was a chain of problems, each one
uncovered only after we'd cleared the one before it. This doc walks through that
chain in plain words: what we hit, what we tried, what happened, and *why* we
made the call we did at each fork. If you only read the headlines, here they are:

1. **The model wouldn't even run** (ICO blow-up) → fixed by scoping cocotb's
   public exposure to just the testbench top.
2. **The build was painfully slow** (lost `-j` parallelism) → fixed the job-count
   plumbing, then cleanly separated "build jobs" from "test jobs".
3. **We tried to make the model itself smaller/faster** (multiple build targets) →
   benchmarked it honestly, and *stepped back* from most of it because the data
   said it wasn't worth it.
4. **CPU firmware tests still couldn't run** → found and fixed the build-flow
   issues (multi-target filelist collision + the firmware compile path) that were
   blocking them.
5. **Where we are now.**

---

## Chapter 1 — "The simulation just hangs" (the ICO blow-up)

### The scenario
VCS and Xcelium ran the SEP tests fine. But on **Verilator**, the simulation
would start and then just... sit there. Zero-byte log files, a CPU core pinned at
~770%, and every test eventually killed by the 1800-second timeout. Nothing was
actually wrong with the test — the model was wedged before it could make progress.

### What we tried (and what was a dead end)
This one took real detective work, because the first few theories were wrong:

- **Theory: tie-able inputs.** Maybe some dangling control inputs (reset, boot,
  CPU-run requests) were creating churn. We tied them to constants. **No change.**
- **Theory: clock gating.** SEP has clock gates everywhere; maybe Verilator was
  choking on them. We wrote bypass shims to make the gates pass-through, confirmed
  they were active... and the wedge was *identical*. **Clock gating ruled out.**
- **Theory: the AXI fabric RTL needs cut/spill registers.** For a while we
  genuinely believed the problem was in the design's AXI fabric — that it had
  combinational ready/valid loops that needed RTL surgery. We even escalated this
  to the fabric owners. **This turned out to be wrong**, and it's important that
  we proved it wrong instead of shipping an RTL change on a hunch.

### The real root cause
The culprit was the **test runner, not the design.** cocotb's Verilator runner
unconditionally forces a flag called `--public-flat-rw`, which marks *every single
signal* in the design as publicly visible (so cocotb can poke any of them over
VPI). For a small design that's fine. For something as big as SEP it's poison:
when everything is public, Verilator is forbidden from optimizing the internal
structure, so it can no longer apply the `split_var` hints that are **already
present** in the AXI / common-cells RTL. With those optimizations disabled, the
false combinational loops in the AXI arbiters can't be broken, and Verilator ends
up scheduling a monstrous settle region.

The numbers tell it cleanly (same tree, A/B):

| metric | with the forced flag | scoped fix |
|---|---:|---:|
| combinational settle triggers | 2574 | ~27 |
| unique SCCs (cyclic blocks) | **951** | **61** |
| input-combinational region size | 3.2M | ~160K |
| smoke test | hangs @1800 s | **PASS ~130 s** |

### How we made the call
We couldn't just *delete* the flag — cocotb genuinely needs the top of the
testbench to be public (it talks to clocks, reset, and the AXI ports through it),
and removing it globally broke cocotb with "can't find root handle." So the fix
was to **replace** the global flag with a *scoped* one: expose only `sep_uvm_top`
(the testbench top), nothing inside the DUT. We did that with a tiny Verilator
config file plus a small monkeypatch in the runlib that strips the bad flag and
injects our scoped config.

The decisive point: **this was a DV-toolchain fix, not an RTL fix.** Three config
files, zero changes to the design or the fabric. We were glad we didn't ship the
RTL cut/spill change we'd been about to escalate.

### What it cost us (the trade)
This fix isn't free — we gained a buildable, fast model and gave up a few things.
In plain words:

- **We lost cocotb's free peek-anywhere access.** With everything public, a Python
  test could read or poke *any* signal deep inside the design by name. Now only the
  testbench top is public, so a test can only see the top's ports and probes. The
  cost: if a test needs to look at something *inside* the design, we now have to
  bring that signal out as an explicit `tb_top` probe port and rebuild — instead of
  just adding one line of Python. More friction, but honestly a cleaner habit (the
  observation points are now explicit and reviewable, not reaching into random
  internals).
- **The build cache can't see edits to the `.vlt`.** Because we inject the config
  through a runlib wrapper rather than cocotb's normal build settings, cocotb
  doesn't notice when you change `sep_public_scope.vlt` — it'll happily reuse a
  stale model. So if you edit that file, you must clean the build dir by hand.
- **It leans on a cocotb internal.** The wrapper hooks a private cocotb function to
  strip the bad flag. If cocotb is upgraded and that function changes, the wrapper
  could quietly stop working and the hang could come back. It's pinned to the
  current cocotb version, so it's safe today, but it's coupled to code we don't own.

None of this touches the design or VCS/Xcelium — those never read the `.vlt`. So
the ledger is: we bought a ~4-minute build and a ~130-second smoke test, and we
paid with **less ad-hoc internal visibility** (now routed through explicit probes)
plus **two small maintenance hazards** (a cache blind spot and a cocotb-internal
hook). For a flow that gates regression, that's a good trade.

### The cleaner fix, for later
The override works and is correct, but it's the least durable option. More
principled directions, roughly best-to-pragmatic: (1) get cocotb to stop forcing
the flag upstream so we can pass our config the supported way; (2) have the runlib
drive the Verilator build itself instead of going through cocotb's runner (matches
our own "config is the interface, no magic" rule); or (3) keep today's wrapper but
*harden* it — fold the `.vlt` into the build fingerprint so edits trigger a
rebuild, and make it fail loudly if a cocotb upgrade ever breaks the hook. The
near-term plan is (3); the long-term aim is (2), with (1) filed in parallel.

*(Committed: `6f79c800d`, root-cause doc corrected in `69f8ab5f9`. Full detail in
`SEP_OSS_VERILATOR_ICO_BLOWUP.md`.)*

---

## Chapter 2 — "Why does the build take all night?" (the -j32 / -j4 saga)

### The scenario
Now that the model could run, the next pain was the **build**. A cold rebuild
(which happens any time you touch `tb_top.sv`) was taking something like **8 hours**
instead of the ~35 minutes it should. The C++ compile was crawling along nearly
one file at a time.

### The root cause
cocotb hardcodes the C++ compile step to `make -j4` (really `min(4, cpu)`). The
SEP config *had* a `build_jobs = 16` knob — but that only sped up Verilator's
*code generation*, not the g++ step that actually dominates the wall-clock. The
old flow used to compensate by exporting `MAKEFLAGS=-j16` so make would ignore
cocotb's cap... and **that export got silently dropped** during a rewrite of the
runlib config system. So the parallelism quietly vanished and nobody noticed until
a cold rebuild took all night.

### What we tried first (and the over-engineering we backed out of)
- **Quick workaround:** just prepend `MAKEFLAGS=-j16` to the run. Worked
  immediately — back to tens of minutes with 16 parallel compilers.
- **An "auto" tuning engine.** We then built a fancy resource-aware system
  (PR #3182) that auto-detected cores and memory and picked job counts and
  sim-thread counts *inside the shared runlib*. The runlib owner pushed back, and
  the pushback was right. His charter for the runlib is "a thin pass-through with
  no hidden behavior," and an auto engine baked into it broke two things: it made
  the build **non-deterministic** (the compiled model's identity would depend on
  how many cores happened to be free at the time), and it put "a layer between
  config and behavior" — so a clone of the repo wouldn't necessarily reproduce
  what CI built. **We closed the PR.** The lesson stuck: resource *smarts* are fine,
  but they belong in the personal launcher, not in the shared tool everyone clones.

### What we actually changed, and why
The owner asked for a smaller first step, in his words: *"swap the hardcoded 16 for
a `--jobs` passthrough, add `--threads` as a static arg where we want it, and
revisit full auto later."* That's essentially what we shipped, with one deliberate
refinement:

1. **Dropped the hardcoded `build_jobs = 16` from the config.** SEP's config no
   longer pins a job count — it's simply *unset*, so the build follows whatever
   the invoker passes. This is the heart of the owner's ask: off its home machine
   the hardcoded 16 was just wrong, and removing it keeps the runlib a pure
   pass-through. *(Landed on main as `094db75d0`.)*
2. **Added a `--build-jobs` flag that defaults to `--jobs`.** This is the one place
   we went slightly beyond "just use `--jobs`." The reason: build-parallelism and
   test-fan-out are genuinely different axes — in a regression you want, say, 8
   tests running at once but each *build* using all 32 cores. Folding both onto a
   single `--jobs` would force one to compromise the other. So `--build-jobs` lets
   you set them independently — but it **defaults to `--jobs`**, so it stays a thin,
   explicit, no-magic pass-through (the runlib still just forwards an integer; it
   never decides anything on its own).
3. **Moved all host-awareness into the personal `run.sh` (gitignored), not the
   runlib.** This is the direct answer to the owner's determinism worry. The shared
   runlib does **zero** host probing — give it explicit numbers and it builds the
   same model every time, so a clone matches CI exactly. The "detect the machine
   and pick good numbers" logic lives only in *my* launcher, which simply computes
   concrete integers and passes them through (`--build-jobs` = capped host cores,
   `--jobs` = a sensible regression fan-out). Auto-scaling without sacrificing
   reproducibility, because the non-determinism never enters the shared layer.

So: **does it meet the owner's bar? Yes.** The hardcoded 16 is gone, the runlib is
a deterministic pass-through, and the only "auto" lives in a personal, non-shared
launcher. The single deviation — a separate `--build-jobs` flag — still honors the
"no hidden behavior" rule because it defaults to `--jobs` and only ever forwards an
explicit value.

### A side-quest: sim threading
While we were here, we tested whether Verilator's `--threads` (multi-threaded
*simulation*) was worth it. We benchmarked it carefully on a long CPU-bound test:
`--threads 8` gave about **1.2x** speedup (~17% faster) on a single long test —
but it's useless in a regression (it oversubscribes the cores you're already using
to run tests in parallel), useless on short tests, and it makes *every* rebuild of
that model much heavier.

The owner's suggestion here was to expose it as a static config arg
(`[build.verilator] extra_args = ["--threads", "8"]`) — no new plumbing, and it
already feeds the build fingerprint. We went one notch further and made it a
**per-test opt-in `--sim-threads` flag in `run.sh`, off by default** (and we
removed the earlier env-var shim entirely). The reason for not baking it into the
config: a config-wide `--threads` would tax *every* rebuild of the model with the
heavier threaded build, to buy a speedup that only helps a lone long test. So
opt-in-per-test is the better fit — same conclusion as the owner (don't make it the
default), just enforced at the launcher instead of the config. **A small, honest
win in a narrow case is not worth taxing every build.**

---

## Chapter 3 — "Can we make the model itself smaller?" (the build-model study)

### The scenario
The model ran and built at a reasonable speed, but Verilator simulation is still
slow in absolute terms (~370 ns of sim per wall-second), and we have a per-test
timeout. So the natural next question: can we build *leaner* models for tests that
don't need the whole design? Two ideas:

1. **Gate off the external master ports** (the SMN-inbound and JTAG-AXIL ports we
   brought out for tests #17 and #20) when a test doesn't use them.
2. **Stub out the CPU.** Most "no_cpu" tests drive the design through a forced AXI
   splice and never actually need the VeeR RISC-V core to execute. So build a
   compile-time CPU stub that keeps the LSU AXI plumbing byte-identical but drops
   the whole RISC-V core.

We set up four/five build targets and ran a real benchmark — cold ccache, fresh
per-build, the same smoke test on every model, plus a longer test for sim-rate.

### What the benchmark actually said
This is the part where we let the data overrule the plan:

- **The external-master gating was worth almost nothing.** "Everything live"
  vs. "ports gated off" came out within noise on both build *and* sim time. Why?
  Because the scoped-`.vlt` fix from Chapter 1 had *already* kept those fabric
  cones out of the expensive region. The gating was solving a problem we'd already
  solved. → **We stepped back from justifying targets on this basis.**
- **The CPU stub does *not* meaningfully speed up the build.** Only ~12% fewer
  files and ~12% less generated C++; the actual compile wall-time was flat, lost
  in run-to-run noise. The reason is structural: VeeR is only ~10% of the compiled
  RTL, and it's a *pipelined* core (mostly flops). The giant slow-to-compile files
  are the AXI fabric, crypto, and i3c cones — and the stub removes *none* of those.
- **The CPU stub *does* speed up the simulation — by ~1.66x.** Same workload,
  26 ns/s vs 15.5 ns/s; on a real test, 466 s vs 773 s for the identical run.
  Removing the whole CPU pipeline cuts the per-cycle evaluation cost, which is a
  *sim-time* win even though it's not a *build-time* win.

### How we made the call
We collapsed the sprawling 4–5 target plan down to **two models that earn their
keep**:
- `default` — full VeeR CPU, for every CPU test;
- a CPU-stub model — for the ~23 no_cpu tests, purely for the ~1.66x sim speedup.

Both external masters are just left *always live*, because gating them costs
nothing. We kept the two live-master targets that exist (#17, #20) **only because
those tests functionally need those ports** — not for any speed reason.

And critically, we wrote down two honest caveats: (a) the speedup only matters
once the regression flow actually builds the right model — which it *didn't* yet
(see Chapter 4), and (b) the stub's byte-identical-LSU claim is proven only on the
smoke test so far; the full no_cpu parity sweep is still owed.

*(Full study with all five rows of data: `SEP_OSS_BUILD_MODEL_OPTIMIZATION.md`.)*

---

## Chapter 4 — "Why is the fast model not actually being used?" (the build-flow bugs that blocked CPU tests)

### The scenario
With the two-model plan in hand, we went to actually run the broader suite —
including the **CPU firmware tests** — and hit two more issues that had been hiding
underneath everything else.

### Issue A: the multi-target regression was silently building the wrong model
When you run the whole regression with multiple targets, all the SEP targets
shared one build directory and derived the *same* on-disk filelist path. The flist
step writes that file per target, so it was **last-writer-wins**: whichever target
generated its filelist last won, and its source set was used for *everyone*. In
practice that meant the CPU-stub model was being compiled with the **real VeeR
CPU** — the stub was never actually reached in regression. The fast model existed
on paper but never ran.

**The fix:** key the generated filelist path on the *target name*, so each target
gets its own filelist and they stop clobbering each other. We also made
`exclude_files` additive per-target (so a target can drop the real `sep_cpu.sv`
and substitute the stub cleanly). Now a multi-target regression actually builds
what each target asked for.

### Issue B: the CPU firmware compile path wasn't wired in
The CPU tests need RISC-V firmware (ITCM/DTCM hex images) compiled before they can
run, and the runlib's `c_compile` stage had no template to do it for SEP — it
would just error out. We stood up the firmware build path (`[c_build.default]` in
the config + the supporting stages.py work), pointed it at the RISC-V toolchain,
and wired the wrapper so firmware gets rebuilt automatically when it's stale. With
that in place, **the CPU tests can finally move forward** on this flow — the
firmware builds, the model builds, the test runs.

### How we made the call
Both of these were *plumbing* bugs, not design or test bugs — exactly the kind of
thing that stays invisible until you push the flow end-to-end. The principle we
stuck to throughout: fix it in the build/config layer, keep the design and the
tests untouched, and make the behavior *predictable* (per-target filelists, an
explicit firmware stage) rather than relying on lucky ordering.

### What we touched in the *shared* runlib, and why it's safe
Three of the files we changed are not SEP's — they're the **shared** runlib
(`cli.py`, `config.py`, `stages.py`) that smc and dtp also use. Touching those is
sensitive, so here is every change and its blast radius, plainest terms:

1. **The `--build-jobs` flag** (Chapter 2). Adds a knob and threads it through the
   build-arg builders. It *defaults to `--jobs`*, so any DUT that doesn't pass it
   behaves exactly as before. **Safe — purely additive.**
2. **The Verilator scoped-public plumbing** (Chapter 1). The wrapper that strips
   the bad flag, the `.vlt`-into-the-build-fingerprint hardening, and the
   existence/"did it actually patch" guards. Every line is gated behind "tool is
   Verilator *and* `public_scope` is set in config" — only SEP sets that, so smc
   and dtp see nothing. **Safe — gated to SEP.**
3. **Graceful firmware-skip in `c_compile`** (Chapter 4). A test with no firmware
   now records a SKIP instead of erroring. Strictly *more* lenient — it can't break
   a flow that already passed. **Safe.**
4. **The per-target filelist / build-dir fix** (Chapter 4, the collision bug). This
   one moves on-disk paths (`filelists/<target_name>/`, `vcs/<target_name>/`), but
   only fires for a target that actually selects its own sources. Single-target
   DUTs are untouched. **Mostly safe — but needs a quick "does smc/dtp run
   multi-target?" check before landing.**
5. **The `run_subprocess` rewrite** — this is the one that needs the owner's eyes.
   We replaced Python's simple "run with a timeout" with a manual process launch
   that (a) starts each tool in its own session and kills the *whole* process tree
   on timeout/Ctrl-C, and (b) streams the log live instead of buffering it to the
   end. Both came straight out of the Chapter 1 debugging: the old code only killed
   the direct child, so a wedged Verilator left grandchildren spinning at ~770%
   CPU, and it buffered output so a hung run produced the infamous **0-byte log**.
   The fix is a genuine improvement everyone benefits from — but it is **not gated**;
   it changes how every subprocess for every DUT is launched and reaped. **This is
   the change that needs explicit owner sign-off.**

The honest framing for the owner: items 2–5 are **SEP-driven needs that had to land
in shared code because the runlib has no SEP-only hook.** That's the same tension as
the Chapter 2 auto-engine. The clean long-term answer is either a DUT-scoped
extension point, or upstreaming the parts that are genuinely general — and the
process-tree cleanup in item 5 *is* general, so it's probably wanted by everyone
rather than something to hide behind a flag.

---

## Where we are now

- **Chapter 1 (ICO blow-up): DONE and committed.** The model runs on Verilator;
  smoke passes in ~130 s instead of hanging. Root cause correctly attributed to
  the test runner, not the RTL.
- **Chapter 2 (build parallelism): DONE.** `-j` is back; `--jobs` and
  `--build-jobs` are cleanly separated; the auto-tuning over-engineering was
  deliberately dropped; sim-threading is opt-in only.
- **Chapter 3 (build-model study): DECIDED.** Two models — full-CPU `default` and
  a CPU-stub for no_cpu tests (~1.66x sim win). External-master gating dropped as
  a perf lever (it bought nothing). Study written up.
- **Chapter 4 (CPU-test unblock): IN PROGRESS.** The multi-target filelist-
  collision fix and the firmware-compile path are in place (currently uncommitted
  on this branch), and a CPU regression is running on Verilator to confirm it
  end-to-end. Still owed: the full no_cpu parity sweep for the CPU stub, and
  committing/PR-ing the remaining build-flow fixes.

### The throughline
Every single one of these problems lived in the **DV toolchain and build flow**,
not in the SEP design. Twice we were one step away from "fixing" the RTL — the AXI
fabric cut/spill in Chapter 1, and the over-clever auto-tuner in Chapter 2 — and
both times the right move was to *step back*, get the evidence, and fix the
plumbing instead. The benchmark in Chapter 3 is the clearest example: it talked us
out of most of the optimization we'd planned and kept only the one piece that the
data actually supported. That's the real lesson of this branch — measure first,
keep the design clean, and let the numbers decide what's worth keeping.
