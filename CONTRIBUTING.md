# Contributing to tt-oca-harness

Thank you for your interest in contributing to [tt-oca-harness](https://github.com/tenstorrent/tt-oca-harness) (Open Chiplet Atlas Harness, OCAH). This document describes how to get set up, the conventions we follow, and the process for submitting changes.

By contributing to this project, you agree that your contributions will be licensed under the [Apache License, Version 2.0](LICENSE).

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

Clone the repository and inspect the available build targets:

```bash
git clone https://github.com/tenstorrent/tt-oca-harness.git
cd tt-oca-harness
make help
```

See the [README](README.md) for vendor import conventions, register-generation flows, and other repository-specific guidance.

## Development Workflow

1. Create a topic branch off `main` for your change.
2. Make focused commits that compile and pass relevant checks where possible.
3. Open a pull request against `main`. The template is guidance only; CI does not require Summary or Test plan, but the daily curator will normalize the title to `scope: summary` format and repair any missing template sections. Add `Fixes #N` when the PR closes an issue.
4. Be responsive to review feedback.

Pull requests are reviewed on a weekly basis. The full how-to is in [`doc/contributing/`](doc/contributing/).

## Coding Conventions

### License headers

Every hand-authored source file must carry an SPDX license header. Use the form appropriate to the file's comment syntax.

For SystemVerilog (`.sv`, `.svh`, `.v`, `.vh`) and SystemRDL (`.rdl`):

```systemverilog
// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
```

For Python, shell, Makefile, and YAML files:

```makefile
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
```

For C and C++ (`.c`, `.h`, `.cpp`, `.hpp`):

```c
/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
```

For AsciiDoc (`.adoc`), use line comments:

```asciidoc
// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
```

For shell and Python scripts that begin with a `#!` shebang line, place the header immediately after the shebang. Keep the year current for new files; do not edit the year on files you only modify.

Generated register collateral under `hw/**/regs/gen/` is produced by the
repository generation flows and carries the same SPDX Apache-2.0 header as
hand-authored files (emitted by the generators / `tools/regs/stamp_spdx.py`).

### Vendored code

Third-party RTL and tools are vendored under `vendor/` via Bender `vendor_package` entries. Do not hand-edit files under `vendor/*/upstream/`; use `patches/` and local overlays instead. See the README for the full vendor workflow.

When adding a new vendored dependency, confirm its license is Apache-2.0 compatible and note the dependency, source, version, and license in the pull request description.

## Linting & CI

Naming: `<action>-<lang>[-<tool>]` for jobs/Make, with reviewdog checks matching the job
(plus `/<scope>` when one job covers multiple tops, e.g. `lint-sv-slang/smu`).

`.github/workflows/lint.yml` runs `lint-sv-slang`, `lint-sv-verilator`,
`lint-sv-verible`, `lint-python`, `lint-python-mypy`, `format-c`, `lint-tcl`,
`lint-spelling`, `lint-yaml`, `lint-toml`, `lint-markdown`, `lint-make`,
`lint-shell`, and `regen-regs` on pull requests and pushes to `main`. Setup
jobs share `bender`, Verilator, and reviewdog artifacts; jobs report through
`.github/actions/reviewdog-report`.

Documentation-only diffs (every changed path is under `doc/`, an Antora playbook,
or a `.md` / `.adoc` / image) skip lint, Verilator smoke, and the nonfree GitLab
child. The required `verilator-smoke (dtp)` / `(sep)` and GitLab checks still
report success. `scripts/ci/diff_class.py --self-test` checks the classifier.
Scheduled and manually dispatched pipelines always run in full.

| CI job | Reviewdog check(s) | Local command |
|---|---|---|
| `lint-sv-slang` | `lint-sv-slang/smu`, `lint-sv-slang/aou` | `make lint-slang-all BLOCK=smu` / `BLOCK=aou-rtl` |
| `lint-sv-verilator` | `lint-sv-verilator/<block>` for `aou-rtl`, `dtp`, `sep`, `smc`, and `smu` | `make lint-verilator-all [BLOCK=<block>]` |
| `lint-sv-verible` | `lint-sv-verible` (report-only) | `make lint-sv-verible` and `make format-sv-check` |
| `lint-python` | `lint-python` | `make lint-python` and `make format-python-check` |
| `lint-python-mypy` | `lint-python-mypy` (report-only) | `make ocah-lint-python-mypy` |
| `format-c` | `format-c` | `make format-c-check` |
| `lint-tcl` | `lint-tcl` | `make lint-tcl` and `make format-tcl-check` |
| `lint-spelling` | `lint-spelling` | `make ocah-lint-spelling` and `make ocah-lint-spelling-fix` |
| `lint-vale` | `lint-vale` | `make ocah-lint-vale` |
| `lint-yaml` | `lint-yaml` | `make ocah-lint-yaml` |
| `lint-toml` | `lint-toml` | `make ocah-lint-toml` |
| `lint-markdown` | `lint-markdown` | `make ocah-lint-markdown` and `make ocah-lint-markdown-fix` |
| `lint-make` | `lint-make` (report-only) | `make ocah-lint-make` |
| `lint-shell` | `lint-shell` | `make ocah-lint-shell`, `make ocah-format-shell`, and `make ocah-format-shell-check` |
| `regen-regs` | — (job fails on a dirty tree) | `make regen-regs regen-regs-adoc regen-regs-html` |

The `regen-regs` gate regenerates every register block's collateral from the RDLs
and fails if the working tree changes, so the committed `**/regs/gen/` outputs
(SystemVerilog, C headers, Python, RAL, IP-XACT, AsciiDoc, HTML) always match a
fresh run. It is peakrdl-only (no bender or `nonfree/`), so a plain checkout
reproduces it. To fix a failure, run the local command above and commit the
result:

```
make regen-regs regen-regs-adoc regen-regs-html
git status --porcelain   # expect no output
```

Local `make lint-slang` / `make lint-sv-verible` / `make format-sv` require the tools on
`PATH` (same as CI). If a tool is missing, Make prints an install hint and the matching
`./scripts/docker-run.sh eda-run make …` command. CI installs slang `v11.0` and verible
`v0.0-4080-ga0a8d8eb` natively in their jobs.

Verible lint and format share the first-party, hand-maintained SystemVerilog
inventory defined in `flows/lint/verible.mk`. That inventory includes `hw/**`
and hand-authored `vendor/**/overlay/**` files, but excludes generated output,
materialized `vendor/<org>/<repo>/upstream/**` sources, and files that the
pinned single-file parser demonstrably cannot process. Do not patch upstream
vendor code for style findings. A proven integrated correctness defect still
follows the Bender patch or upstream-revision workflow described above.

Run `make format-sv` to apply the committed two-space, 100-column formatter
profile and `make format-sv-check` for a non-modifying check. Formatter-safe
whitespace and wrapping findings may be fixed mechanically after reviewing the
diff. Treat storage types, range direction, procedural assignments, task
lifetime, case completeness, and hierarchy-affecting labels as manual lint
findings because changing them can change behavior. Parameter-name style is
deferred to [issue #1051](https://github.com/tenstorrent/tt-oca-harness/issues/1051)
and is omitted from this lint pass.

Prefer fixing an actionable finding. A demonstrated Verible limitation may be
handled by the narrowest rule/path waiver, keyed to the exact rule and stable
location pattern with a constraint-focused rationale and an upstream Verible
bug link. Reserve `OCAH_VERIBLE_SINGLE_FILE_EXCLUDES` for parser,
preprocessor, or convergence failures that prevent any reliable single-file
result; document each excluded file there. `lint-sv-verible` remains
report-only (`level: warning`, `fail-level: none`) while this classified legacy
backlog remains.

Ruff checks first-party Python under `tools/`, `scripts/`, `hw/`, and
`.github/`. Generated register models, vendored sources, submodules,
`nonfree/`, and build output are excluded. Run `make lint-python-fix` to apply
safe lint fixes and `make format-python` to format files in place; CI uses only
the non-modifying `lint-python` and `format-python-check` commands.

`lint-python-mypy` and `lint-make` (checkmake) report findings on every pull
request but never fail CI (`fail-level: none`): mypy starts from a lenient
`[tool.mypy]` config with hundreds of pre-existing findings across the tree,
and checkmake's `maxbodylength`/`phonydeclared`/`uniquetargets` rules have
false-positive modes against conventions this repo relies on deliberately
(long multi-step recipe bodies, the deferred `OCAH_PHONY +=` accumulator, and
legitimate pattern-rule/`ifeq` target overloads) -- see `checkmake.ini` and
`flows/lint/checkmake.mk`. Treat both as read-and-judge, not fix-on-sight.

`lint-spelling` (codespell) and `lint-markdown` (markdownlint) both offer
autofix commands (`-fix` suffix); review the diff before committing, since
either can rewrite a deliberate domain term (see `[tool.codespell]`'s
`ignore-words-list` in `pyproject.toml`) or mangle non-prose content such as
math notation or bit-range syntax that only looks like Markdown.

`lint-toml` (tomllint) checks TOML syntax only -- it carries no style rules
and no autofix, unlike yamllint/markdownlint. It mainly guards the DV
testlists and sim configs under `hw/**/dv/**/*.toml`, catching a malformed
file before the runner that reads it fails with a less legible error.
`hw/ip/scrambler/dv/lint/scrambler.toml` is excluded: despite the extension,
`slang-tidy` parses it with its own `Checks:`/`CheckConfigs:` grammar, not
TOML.

`lint-vale` (Vale) checks `.adoc`/`.md` prose against `styles/OCAH/Acronyms.yml`,
a small substitution list of acronym expansions this repo has actually seen
drift to a wrong one -- most plausibly an AI assistant free-associating a
plausible-sounding phrase for a three/four-letter acronym it was never told
the meaning of (an early instance: DFD written out as "Debug Forensics
Dump" in a couple of places instead of the "Design-for-Debug" that
`hw/sys/smc/doc/dfd.adoc` actually defines it as). Each entry's correct side
is a direct quote from somewhere in-tree, not a guess -- see that file's own
header comment before adding to it. It has no autofix; a substitution
finding carries its suggested replacement in the CLI output, but applying it
is a manual edit, same as `lint-toml`. Vale's built-in case-exact vocabulary
check (`Vale.Terms`) was tried and dropped for now: this repo casually
lowercases these acronyms inside test/config names and running prose often
enough that it flagged over a hundred non-issues against ~5 real ones, which
isn't the low-noise bar the rest of this table holds to.

### Optional pre-commit checks

The repository provides optional, check-only hooks for staged Python, C/C++,
Tcl, YAML, TOML, and shell files, plus a repo-wide spelling check. They run
Ruff, clang-format, tclfmt, tclint, codespell, yamllint, tomllint, shellcheck,
and shfmt from the locked uv environment, plus Git's whitespace/conflict-marker
check. The hooks do not modify or stage files. `mypy`, `markdownlint`,
`checkmake`, and `vale` are deliberately left out of this bundle -- they are
slow, need a separate Node.js toolchain, or ship as a standalone binary
rather than a uv-managed package -- and stay CI-only; see the CI job table
above for their local commands.

```bash
make hooks-install    # explicit opt-in for this clone
make hooks-run        # check currently staged files without installing
make hooks-run-all    # check every eligible tracked file
make hooks-uninstall
```

Installation uses pre-commit's standard local `.git/hooks/pre-commit`
launcher. It does not change `core.hooksPath`, and no setup or checkout command
installs it automatically. CI remains authoritative whether or not a
contributor enables the hook.

## Submitting Changes

* Keep pull requests focused; unrelated changes belong in separate PRs.
* Write clear commit messages that explain why a change is made.
* Ensure relevant builds and checks pass before requesting review.

## Reporting Issues

Open a [new issue](https://github.com/tenstorrent/tt-oca-harness/issues/new/choose) and pick Bug, Task, or Feature. All fields — Workstream, Subsystem, Component, Priority, and Target release — are required. If you target the current release (v0.5.0), the milestone is set automatically.

For security vulnerabilities, do not open a public issue. Follow the process in [SECURITY.md](SECURITY.md).

Thank you for contributing!
