# DV long runs and batches — draft for `hw/sys/sep/dv/README.md`

**Untracked on purpose.** Holds until `inmcm/sep_rom_oca_manifest` lands, so the
PR stays scoped to the ROM/DV work.

**To apply:** insert the section below into `hw/sys/sep/dv/README.md`
immediately before `## Code coverage`. That places it after "Results and
evidence" and before coverage, which is where the running/triage material
belongs. Nothing else in the README needs to change; `AGENTS.md` already defers
the *running* interface to each block's README ("Building and running
firmware-driven DV"), so this is the file an agent following that guide lands in.

Everything below is measured: the 20260911 `rom_fw` group (67 items,
`--sim-jobs 6`, 14.4 h, 56/66 with four members truncated), the four-test rerun
that followed it, and the 20260915 group that ran the same 67 items to
**67/67 PASS in 19.3 h** once those members' caps were raised. Replace the
run-ids with current ones if they have aged out of `build/runs/`.

---

## Long runs and batches

A group regression here is most of a day, not minutes: at `--sim-jobs 6` the
67-item `rom_fw` group took **19.3 h** to pass clean, and individual secure-boot
members run 2,600-16,600 s each. An earlier 14.4 h figure for the same group is
misleading -- that run ended `TIMEOUT` with four members cut off, so it measured
truncation rather than completion. Budget ~20 h. That changes how you should start
one, and how you should read it.

### Start it so it outlives your shell

A regression must survive the session that launched it. Write a wrapper and
`nohup` that, rather than backgrounding `run_dv.py` directly:

```bash
cat > /tmp/run_regress.sh <<'EOF'
#!/bin/bash -l
module load synopsys/vcs/<version> >/dev/null 2>&1
cd <repo>
export OCAH_TOOLCHAIN_ROOTFS=<rootfs>
exec <uv> run --project "$PWD" --locked --group dv \
  python "$PWD/tools/dv/run_dv.py" --dut sep --regress --tool vcs ...
EOF
chmod +x /tmp/run_regress.sh
nohup /tmp/run_regress.sh > build/regress.log 2>&1 &
echo $! > /tmp/regress.pid
```

The `-l` matters: `module` is a login-shell function, so a wrapper without it
loses the simulator. Keep the pid; `[ -d /proc/$PID ]` is how you check later
whether the run is alive rather than finished.

### Do not start one on a stale tree

Two separate staleness traps, and both waste the whole run:

- **The branch.** Check `git rev-list --count HEAD..origin/main` first. A result
  graded against a tree fifteen commits behind answers a question nobody asked.
- **The build artifacts.** Freshness is judged on mtime, not content, so a
  comment-only commit that rewrites a source file makes the ROM look stale even
  though the `.vmem` would be byte-identical:

```bash
find <rom>/src <rom>/include -newer <rom>/build_ot/boot_rom.elf | wc -l
```

If that is non-zero, do not pass `--stage sim` alone — let `c_compile` run. The
`[c_build.*].outputs` lists in `sep_sim_cfg.toml` exist so `--stage sim` fails
loudly on a stale image instead of simulating one, but only for the artifacts
they declare.

Check the host is actually free, too. Beware that `pgrep -f 'run_dv.py'` matches
its own command line through the shell that launched it; use a bracket to stop
that: `pgrep -f 'run_dv[.]py'`.

### The two environment variables, and the firmware trap behind them

A wrapper that loads only the simulator gets about ninety seconds into a run
before every `c_compile` fails. Both of these are required:

- `module load synopsys/vcs/<version>` — needs the `-l` login shell, above.
- `export OCAH_TOOLCHAIN_ROOTFS=<rootfs>` — routes the firmware build through
  bwrap. Without it `docker-run.sh` falls back to the container engine, which on
  this host dies with `runc create failed: ... permission denied: OCI permission
  denied`. Each `c_compile` then fails in about 2.7 s, so the run marches through
  the whole item list failing fast and looks superficially alive.

The trap behind them is subtler. `c_compile` builds the ROM INSIDE the sandbox,
then runs `make oca-images` on the HOST, because the packer needs `uv` and the
toolchain rootfs has none. That host-side make also rebuilds
`hw/sys/sep/dv/fw/tests/bl1_pass_test`, and it decides to do so on MTIME — so a
comment-only sweep across `dv/fw/drivers/*.h` is enough to trigger it. The host
has no RISC-V gcc, so it stops at:

```
make[1]: riscv64-unknown-elf-gcc: Command not found
```

You cannot fix this by putting the rootfs compiler on `PATH`: it is a Debian
binary and the host glibc is older (`GLIBC_2.34/2.35/2.38 not found`). Build that
one directory inside the sandbox instead, then let the flow run untouched:

```bash
env -u RISCV_TOOLCHAIN -u RISCV_PREFIX -u MAKEFLAGS -u MFLAGS \
  ./scripts/docker-run.sh run-here \
  make -C hw/sys/sep/dv/fw/tests/bl1_pass_test GCC_PREFIX=riscv64-unknown-elf
```

`bl1_pass_test` is the only DV firmware directory with a Makefile, so that is the
whole fix. There are host `riscv-gnu-toolchain/*-rhel-8.10` modules, but loading
one changes the compiler that builds the ROM, which is not a like-for-like
substitute when the point of the run is to compare against an earlier pass count.

Prove it with one cheap item before committing hours:

```bash
run_dv.py --dut sep --tool vcs --items <one_test> --stage c_compile   # ~13 s
```

### Telling a hang from a slow test

**Measure the rate of simulated time, not the wall clock.** A hung test stops
advancing sim time; a slow one keeps advancing at a normal rate and simply runs
out of budget. Take the last timestamp in the per-test log against the age of its
`simv`:

```bash
grep -oE '^ *[0-9]+\.[0-9]+ns' <log> | tail -1      # simulated time reached
ps -p <simv pid> -o etimes=                          # wall seconds
```

Compare the resulting ns/s against members that passed in the same run. In the
20260911 `rom_fw` group the four TIMEOUTs were running at 1,389-3,334 ns/s
against a passing band of 2,145-7,545 — inside it, so none was hung. Each had
been cut off inside its *second* RSA-3072 verify, 94-99% of the way through,
needing 14-42 more minutes apiece.

The corollary: a test parked on the same console marker for hours is not
evidence of a hang by itself. `ROM> RSA_EXEC` is the last thing printed before a
multi-million-cycle modexp.

### Never compare simulated time BETWEEN runs — compare cycles

The rate check above works because it compares a test against members of the
**same** run. Across runs it is invalid, and the trap is easy to fall into
because the numbers look directly comparable and are not.

`sys_clk_period` is randomised per run. The same testcase, twice:

| run | `sys_clk_period` | cycles to verdict | simulated ns |
|---|---|---|---|
| `20260915_004442` | 20 ns | 4,750,000 | 95.8 Mns |
| `20260915_094641` | 7 ns | ~4,750,000 | ~33.5 Mns |

Same work, same verdict, and a **2.9x** difference in simulated ns. So "the last
run reached 96 Mns, this one is at 25 Mns, it is a third of the way" is wrong --
in cycles it was nearly nine tenths done.

This cost a healthy run in this session. A failover member was projected against
a prior run's 96 Mns, judged unable to finish inside its cap, and killed --
discarding ~4.3 h. Measured in cycles it was at 4.25 M of ~4.75 M, **89% complete
with ~26 minutes left**, and the rerun then finished inside the cap with 1.5 h to
spare.

Use the cycle counter, which the failover polls print and which is invariant:

```bash
grep -oE 'cyc=[0-9]+' <log> | tail -1                     # cycles reached
grep -oE 'sys_clk_period=[0-9]+ns' <log> | head -1        # this run's period
```

Divide cycles by the `simv` wall age for cyc/s, and compare that against the same
testcase's cycle count in a previous run. `hw/sys/sep/dv/testlists/rom_fw.toml`
already says this in the `sep_failover_sram_clear_assertion_test` entry -- "compare
in CYCLES ... the cycle count is what is invariant" -- and it is worth believing
the first time rather than the second.

The same caution applies to *wall* seconds: host contention from other users moves
them by 30-40% with no change to the test. Cycles are the only figure that is
about the testcase rather than about the machine it ran on.

### Sizing `timeout_sec`

Cost the work, do not guess. Measured on this testbench: one passing RSA-3072
verify is ~2.3 Mns of simulated time; a failing slot is ~5.0 Mns from `RSA_EXEC`
through to its terminal verdict. Members that exercise **both** slots pay it
twice, and those are the ones that overrun — `--sim-jobs 6` contention roughly
halves the ns/s, so the same test that fits at 4-up does not at 6-up.

Which means: **a targeted rerun does not validate a cap for the group.** Rerunning
four tests alone on an idle host gave 2,844-6,906 ns/s, 1.9-5x the rates the same
tests showed inside the group. It proves they complete; it does not prove the cap
holds under full load.

There is no scheduler-level budget. A run's `status=TIMEOUT` / `exit_code=124` is
aggregated from per-test `timeout_sec` expiries, so raising the members that
overran is the whole fix.

**Outcome (2026-09-16).** With five members raised from 14400 to 21600 the full
`rom_fw` group ran **67/67 PASS in 19.3 h** at `--sim-jobs 6`, `exit_code=0`, and
the longest single item took 16,614 s -- inside the raised cap with room, and
above the old one. Compare the 2026-09-11 baseline: 56/66 with four members
truncated at 14400. The group costs about 5 h more than the old figure suggests
and completes rather than truncating, so budget ~20 h, not ~14.

### Read `result.json`, not just the console

`build/runs/<run-id>/result.json` is the machine-readable verdict and the fastest
way to triage a large group:

```python
d = json.load(open('.../result.json'))
d['status'], d['exit_code'], d['tests']        # aggregate
[(s['item'], s['status'], s['duration_sec'])   # per item, with wall time
 for s in d['stages'] if s['name'] == 'sim']
```

Sort the failures by `duration_sec`. That one column splits a failure list in
two, and the halves have completely different causes:

- **Seconds.** The Python stimulus raised before the simulator advanced; sim time
  is still `0.00ns`. A fixture bug — a helper signature drift, a stale digest, an
  assertion whose precondition the stimulus itself destroyed.
- **Thousands of seconds.** The scenario really ran. Now the verdict is the
  question.

`tool_version` can read `Error-[VCS_COM_UNE] Cannot find VCS compiler` on a run
whose sims were fine; it is an end-of-run probe taken without the module loaded.
Check whether `hdl_compile` passed before believing it.

### Verify fixture fixes without a simulator

A stimulus that fails at `0.00ns` costs a scheduled slot and grades as a testcase
failure, but it is also the cheapest class to fix, because **you can replay it on
the host**. Import the env modules against the packed images and run the
fixture's own sequence:

```bash
PYTHONPATH=hw/sys/sep/dv/cocotb python3 -c "
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
buf = bytearray(open('<rom>/build/oca_secure_boot.bin','rb').read())
mm.<the call the fixture makes>(buf, 'primary')
mm.verify_layout(buf, 'primary'); pm.verify_sealed(buf, 'primary')
"
```

Eighteen of nineteen such failures were confirmed fixed this way in seconds
rather than by a 14 h rerun. The remaining one was a scenario that only resolves
under Verilator, which is what the per-test `tools` key now expresses.

When a fix changes an expected verdict, check it against the failing run's own
console before rerunning: the console list is recorded verbatim in the
`AssertionError` in the log, so you can confirm the marker you now expect is
present and the markers you now forbid are absent, without a simulator.

### Two error spaces, and they do not interchange

A triage trap worth knowing. The console `MANIFEST_ERR=` carries
`OCA_BOOT_ERR_BASE | oca_result_t`; the status ring (`cold_scratch[1]`) carries
`STATUS_ENCODE(type, SEP_MSG_*)`. `status_for_result()` in `oca_boot.c` is the
only bridge, and `sep_manifest_mutate.rom_status_for_result()` parses it so a test
does not mirror the table. Masking the console code and calling the low half a
status asserts on a value the ROM never writes — and it survives review easily,
because the two spaces happen to agree on `OCA_FAIL_SIGNATURE` (14 / `0x0e`).

