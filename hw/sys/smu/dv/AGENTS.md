<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMU DV — agent notes

No SMU-specific agent rules yet. Use, in order:

1. `README.md` in this directory — layout, run modes, and the `run_dv.py`
   invocations for this DUT.
2. The repository root `AGENTS.md` — OSS hygiene, `/localdev` scratch policy,
   log-before-rerun, debugging discipline, commit conventions, SV style.
3. `tools/dv/doc/run-dv.adoc` — the shared DV runner and config schema.

`hw/sys/sep/dv/AGENTS.md` is the most developed set of DV working rules in the
repo. Much of it (verification-quality rules, bounded waits, evidence-backed
checkers, config-is-the-user-interface) is DUT-agnostic and worth reading, but it
is **written for SEP** and contains SEP-specific layout and policy decisions —
including deliberate divergences from the SMU conventions. Do not apply it
here wholesale; when this env grows its own rules, record them in this file.
