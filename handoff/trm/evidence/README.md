<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Independent evidence at 4200cc97a

These artifacts were produced by independent review on 11 September 2026 from
`4200cc97a48933163fd56f4ae290474471a7d972`. They are evidence of the submitted
state, which remains unaccepted. The source artifacts are copied byte-for-byte;
JSON path strings are normalized for portability where needed.

- [DTP at 1280 px](dtp-1280.png), [PTAP at 1280 px](ptap-1280.png)
- PDF physical pages [21](p21.png) and [31](p31.png)
- [TRM browser metrics](browser.json), [IG browser metrics](integrator/browser.json)
- [Native PDF text/font measurements](pdf-labels.json)
- [Build commands, environment modes and exit codes](build-commands.json)
- [Source scope/preservation checks and full PDF checksum](verification.json)
- [Incremental source diff](https://github.com/tenstorrent/tt-oca-harness/compare/14da264164ef7570fba2b2a78317e12cb4634fdd...4200cc97a48933163fd56f4ae290474471a7d972), [cumulative 004j source diff](https://github.com/tenstorrent/tt-oca-harness/compare/a0c6b15d11d379fbc640e05a621dbe0fa0e519bb...4200cc97a48933163fd56f4ae290474471a7d972)
- [Author geometry result](author/geom-submitted.log)
- [File checksums](SHA256SUMS)

The build records all report exit 0. Both Antora logs were empty. The PDF has
635 pages; the matching full PDF/site are reproducible from source using
[VALIDATION.md](../VALIDATION.md). This compact Git handoff deliberately carries
only the affected rendered pages, not generated books or environment caches.
