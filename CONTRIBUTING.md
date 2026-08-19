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
3. Open a pull request against `main`. The template is guidance only; CI does not require Summary or Test plan. Add `Fixes #N` when the PR closes an issue.
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

Generated register collateral under `hw/**/regs/gen/` is produced by the repository generation flows and may use a different header format.

### Vendored code

Third-party RTL and tools are vendored under `vendor/` via Bender `vendor_package` entries. Do not hand-edit files under `vendor/*/upstream/`; use `patches/` and local overlays instead. See the README for the full vendor workflow.

When adding a new vendored dependency, confirm its license is Apache-2.0 compatible and note the dependency, source, version, and license in the pull request description.

## Linting & CI

Naming: `<action>-<lang>[-<tool>]` for jobs/Make, with reviewdog checks matching the job
(plus `/<scope>` when one job covers multiple tops, e.g. `lint-sv-slang/smu`).

`.github/workflows/lint.yml` runs `lint-sv-slang`, `format-c`, and `lint-tcl` on every push/PR
(`lint-sv-verible` is temporarily disabled). A `setup-tools` job shares `bender` and `reviewdog`
artifacts; jobs report through `.github/actions/reviewdog-report`.

| CI job | Reviewdog check(s) | Local command |
|---|---|---|
| `lint-sv-slang` | `lint-sv-slang/smu`, `lint-sv-slang/aou` | `make lint-slang-all BLOCK=smu` / `BLOCK=aou-rtl` |
| `lint-sv-verible` (disabled in CI) | `lint-sv-verible` | `make lint-sv-verible` |
| `format-c` | `format-c` | `make format-c-check` |
| `lint-tcl` | `lint-tcl` | `make lint-tcl` and `make format-tcl-check` |

Local `make lint-slang` / `make lint-sv-verible` / `make format-sv` require the tools on
`PATH` (same as CI). If a tool is missing, Make prints an install hint and the matching
`./scripts/docker-run.sh eda-run make …` command. CI installs slang `v11.0` and verible
`v0.0-4080-ga0a8d8eb` natively via `setup-tools`.

## Submitting Changes

* Keep pull requests focused; unrelated changes belong in separate PRs.
* Write clear commit messages that explain why a change is made.
* Ensure relevant builds and checks pass before requesting review.

## Reporting Issues

Open a [new issue](https://github.com/tenstorrent/tt-oca-harness/issues/new/choose) and pick Bug, Task, or Feature. Choose Workstream, Subsystem, and Component from the lists. Priority and Target release are optional.

For security vulnerabilities, do not open a public issue. Follow the process in [SECURITY.md](SECURITY.md).

Thank you for contributing!
