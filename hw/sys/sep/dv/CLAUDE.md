# SEP OSS DV — Claude working rules

The full working rules live in @AGENTS.md. Read it before changing anything in
this tree. This file exists to keep the review gates that are easiest to violate
in front of you.

## Hard gates before any commit under `hw/sys/sep/dv/`

**OSS hygiene** (AGENTS.md §1)
- No licensed/proprietary IP in the build; bender targets are
  `["sep", "sep_el2", "sep_wrapper"]` only, never `"simulation"`.
- `python3 tools/dv/check_no_vendor_paths.py --filelist <sep.flist>` exits 0.
- No OCAH-internal IDs (`TC_*`, `TEST N.N`, `edge E12`, `TOP-10 #9`, `P3`) and no
  local VPLAN rep IDs (`CRY-12`, `FAB-7`, …) in any user-facing surface. Cite
  provenance by OCAH **test name** + behaviour.

**Driver/comment boundary** (AGENTS.md §1.1 — from the PR #1041 review)
- An open-tree C driver may only control hardware inside the OCAH hierarchy
  (`smu.sv`). Hardware that exists only in a nonfree wrapper → the driver lives
  in nonfree, and `fw.mk` links against it.
- Decide by **which hierarchy the register is in**, not by "is it a mux?" The
  TRNG mux is inside OCAH, so its driver is legitimately open. The SPI pad mux
  is in a nonfree wrapper, so its driver is not in this tree.
- Never name a proprietary IP, even to exclude it. Say "Excluded for OSS
  hygiene: proprietary IPs in nonfree."
- No breadcrumb comments — present-tense contract only, no edit history.
- Verify every path a comment cites actually resolves.
- No GitHub issue links in `testlists/*.toml`; no planning/roadmap docs in the
  shipped tree.

**Verification honesty** (AGENTS.md §7)
- A comment and a kept log must name a contract the DUT can **fail**.
- PASS/FAIL needs positive evidence from `results.xml`; a clean simulator exit is
  not evidence.
- A checker that only inspects the golden or the inject request can pass with the
  simulator off — anchor on a DUT probe or a real readback.
- Never mask a spec-vs-RTL gap as an `expect_fail`/XFAIL.

**Stimulus randomness** (AGENTS.md §5.1)
- Randomized stimulus must be a pure function of the seed — `--stage sim --seed N`
  replays a failing leaf. `secrets` / `SystemRandom` are unseedable and are not
  alternatives.
- Use `env/sep_seeded_rng.py` (`SepSeededRng`, SHA-256 counter mode), not
  `random.Random`: stable across hosts and Python versions, and it does not trip
  the SAST weak-PRNG rule.
- **It is not a CSPRNG.** The stream is predictable from the seed by design.
  Never use it for a key, token, nonce, or anything leaving the simulation.
- Converting a call site changes its seed→value mapping, so recorded repro seeds
  go stale. Never quote a per-seed value as VPLAN evidence.

## Running

Canonical: `python3 tools/dv/run_dv.py --dut sep …` (see README.md).
`sim/run.sh` is a personal, git-ignored convenience wrapper — not the canonical
entry point, and not something to document as one.
