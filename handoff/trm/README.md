<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Supporting handoff records

Start with [TRM-HANDOFF.md](../../TRM-HANDOFF.md). These are coordinator-owned
transfer records, not published TRM content. The incoming coordinator may maintain
them in this transferred workspace. Repository-level agent instructions are unchanged.

- [Current independent review](CURRENT-REVIEW.md)
- [Main/IG conflict assessment](MAIN-INTEGRATION.md)
- [Working agreement](WORKING-AGREEMENT.md)
- [Validation contract and portable commands](VALIDATION.md)
- [Queued 004k](briefs/004k.md), [queued 004l](briefs/004l.md)
- [Evidence index](evidence/README.md)
- [GitHub state at transfer preparation](github-state.json)

The source implementation revision is `4200cc97a48933163fd56f4ae290474471a7d972`.
The handoff-only commits do not change that implementation. Original machine-local
paths in diagnostic records are normalized to placeholders; do not execute them
as portable scripts. Use VALIDATION.md to rebuild in the recipient's environment.

Full historical review checkouts, tool caches, untracked images, Git bundles and
generated HTML/PDF are not committed here. The sender retains a durable local
source bundle and the matching full rendered review artifacts. This package's
small screenshots and measurements establish the remaining findings; source and
portable build instructions allow fresh reproduction without those caches.
