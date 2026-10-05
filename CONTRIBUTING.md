# Contributing to tt-oca-harness

Thank you for your interest in contributing to [tt-oca-harness](https://github.com/tenstorrent/tt-oca-harness) (Open Chiplet Atlas Harness, OCAH). This document describes how to get set up, the conventions we follow, and the process for submitting changes.

By contributing to this project, you agree that code contributions are licensed
under the [Apache License, Version 2.0](LICENSE), while documentation and image
contributions are licensed under
[Creative Commons Attribution 4.0 International](LICENSE-DOCS).

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.adoc). By participating, you are expected to uphold this code.

## Getting Started

For detailed documentation, please refer to the GitHub pages site generated as a
deployment of this repository: [tenstorrent.github.io/tt-oca-harness/](https://tenstorrent.github.io/tt-oca-harness/)

The Getting Started and Contributing Guide, in particular, can be found [here](https://tenstorrent.github.io/tt-oca-harness/ocah-starting/latest/index.html).

## Development Workflow

1. Create a topic branch off `main` for your change.
2. Make focused commits that compile and pass relevant checks where possible.
3. Open a pull request against `main`. The template is guidance only; CI does not require Summary or Test plan, but the daily curator will normalize the title to `scope: summary` format and repair any missing template sections. Add `Fixes #N` when the PR closes an issue.
4. In your first pull request, add yourself to [`CONTRIBUTORS`](CONTRIBUTORS).
5. Be responsive to review feedback.

Pull requests are reviewed on a weekly basis. The full how-to is in [`doc/starting/`](doc/starting/).

## Reporting Issues

Open a [new issue](https://github.com/tenstorrent/tt-oca-harness/issues/new/choose) and pick Bug, Task, or Feature. All fields — Workstream, Subsystem, Component, Priority, and Target release — are required. If you target the current release (v0.5.0), the milestone is set automatically.

For security vulnerabilities, do not open a public issue. Follow the process in [SECURITY.md](SECURITY.md).

Thank you for contributing!
