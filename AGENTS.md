<!-- SPDX-License-Identifier: Apache-2.0 -->
# Agent Guide — tt-oca-harness (OCAH)

Orientation for AI agents working in the Tenstorrent Open Chiplet Atlas Harness
repository. This is an **open-source** repo: assume everything you add is public.

Read first: `README.md` (project overview, build entry points) and
`CONTRIBUTING.md` (license headers, coding conventions, PR process). This file
only covers what those two do not.

Subsystem-specific rules live in nested `AGENTS.md` files and take precedence
within their tree — notably `hw/sys/sep/dv/AGENTS.md` for SEP OSS DV.

## Repository map

| Path | What it is |
|------|------------|
| `hw/common/` | Shared RTL (`prim`, libs, packages) and shared DV Python (`hw/common/dv/`, VIPs under `dv/vip/`) |
| `hw/ip/` | Individual IP blocks (AES, key_manager, entropy_source, drbg, efuse, SPI, OTBN, …) |
| `hw/sys/` | Subsystems: `sep/` (Security Processor), `smc/` (System Management Controller) |
| `hw/top/` | Top-level wrappers (`sep_wrapper.sv`, `sep_ip_integration.sv`) |
| `tools/dv/` | DV runner (`run_dv.py`, `runlib/`), dashboard, `check_no_vendor_paths.py` |
| `flows/` | Lint (slang, verible, tclint, clang-format) and synth (yosys) flows |
| `doc/`, `hw/*/doc/` | AsciiDoc architecture docs — the spec source of truth |
| `vendor/` | Vendored third-party sources (VeeR EL2, picorv32, …) |
| `nonfree/` | Optional non-open-source clone (`make ocah-nonfree-init`); gitignored |

`make help` lists the available targets (`ocah.mk` and the flow makefiles it
includes).

## Ground rules

1. **Open-source hygiene.** No licensed/proprietary IP, vendor/foundry paths, or
   internal NFS paths in committed files or filelists. For SEP DV builds, verify
   with `tools/dv/check_no_vendor_paths.py`. Every hand-authored file needs an
   SPDX header (see `CONTRIBUTING.md`).

2. **Scratch/temp space: use `/localdev/$USER`, never `/tmp`.** `/tmp` is small
   and shared across the host; a runaway sim log can fill it and take the whole
   machine down. Before any simulation or long-running job:

   ```bash
   export TMPDIR=/localdev/$USER/TMPDIR
   mkdir -p "$TMPDIR"
   ```

   Never redirect large logs to `/tmp`; target `/localdev/$USER` or the
   testbench's own run/output directory.

3. **Check for existing logs before rerunning a test.** Runs keep full stdout —
   for SEP DV under `hw/sys/sep/dv/build/runs/<run-id>/<test>/logs/`. Grepping a
   kept log is minutes cheaper than a rerun. Re-run only when you need *new*
   stimulus, not a different view of the same output.

4. **Debugging test failures: do not add delays, settle cycles, or NOPs.** The
   cause is almost never "not enough settling time." Look for the real bug —
   protocol ordering (reading a value before it is written), wrong
   register/value, a race between TB and DUT, a broken handshake. Fix the
   protocol or the logic, not the clock count.

5. **Generated files.** Register RTL/headers are generated from SystemRDL
   (`hw/*/regs/`, `make` targets in `hw/common/regs/regs.mk`) and templates under
   `templates/` produce RTL. Edit the source, regenerate — never hand-patch a
   generated artifact.

6. **Bender owns the filelists.** A new design file must be added to `Bender.yml`
   under the right target before any flow will see it.

7. **Prefer existing common cells.** For CDC, clock gating, FIFOs, and other
   standard functions, use `hw/common/prim/` and the vendored AXI/APB libraries
   before writing a custom implementation.

8. **Commit messages: `area: imperative description`**, lower-case area prefix
   matching the tree touched (`sep/dv:`, `hw/smc:`, `ci:`, `docs:`, `treewide:`).
   Explain *why* in the body when it is not obvious. Commit or push only when
   asked.

## SystemVerilog style (lowRISC/OpenTitan with OCAH modifications)

* **Indentation**: 4 spaces (not 2). **Line length**: 100 characters.
* **Naming**: `lower_snake_case` for modules/signals, `ALL_CAPS` for parameters.
* **Reset**: active-low asynchronous (`rst_ni`). **Clocks**: `clk_` prefix.
* **Ports**: `input logic` / `output logic` — `logic` as the data type, no
  redundant `wire` net type.
* **Instances**: prefix with `u_` (`u_decorrelator`). **Generate blocks**: prefix
  with `g_` (`g_ecmplx`).
