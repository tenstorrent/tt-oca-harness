# Contributing to tt-oca

Thank you for your interest in contributing to tt-oca (Open Chiplet Atlas Harness). This document describes how to get set up, the conventions we follow, and the process for submitting changes.

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
3. Open a pull request against `main` with a clear description of the change and its motivation.
4. Be responsive to review feedback.

Pull requests are reviewed on a weekly basis.

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

## Submitting Changes

* Keep pull requests focused; unrelated changes belong in separate PRs.
* Write clear commit messages that explain why a change is made.
* Ensure relevant builds and checks pass before requesting review.

## Reporting Issues

For functional bugs and feature requests, open a GitHub issue with enough detail to reproduce or understand the request.

For security vulnerabilities, do not open a public issue. Follow the process in [SECURITY.md](SECURITY.md).

Thank you for contributing!
