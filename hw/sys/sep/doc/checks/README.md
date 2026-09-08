<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->
# SEP doc consistency checks

Mechanical checks for `hw/sys/sep/doc/`. Each one cross-references the specification against
a generated or source-of-truth artifact, so it catches the failure the prose reviews miss.

Each script derives the repository root from its own location, so it runs from any checkout
and from any working directory.

| Script | Checks | Source of truth |
|---|---|---|
| `check_xrefs.py` | every `<<anchor>>` resolves | the whole TRM include tree (162 files) — **not** the SEP chapter alone, which produces false positives |
| `check_tables.py` | cell count divides evenly by the declared `cols=` | the table's own spec |
| `check_manifest_offsets.py` | inline `offset NNNN` citations in prose | `tools/tt-oca-manifest/src/oca/constants.py` |
| `check_reg_addresses.py` | register addresses in all SEP chapters, **and** that the generated header still matches the RDL | `regs/blocks/*/*.rdl` → `regs/gen/c/sep_addr.h` → docs |
| `check_error_codes.py` | every `OCA_FAIL_*` / `SEP_MSG_*` cited exists | bootrom `include/`, `src/`, validator lib |
| `check_status_names.py` | bare ALL_CAPS identifiers resolve | as above; expect legitimate misses (RDL field names, admonition labels) — read the list, do not gate on it |

## Running Checks

Run them all before publishing a doc change:

```sh
for f in hw/sys/sep/doc/checks/check_*.py; do echo "== $f"; python3 "$f"; done
```

`check_tables.py`, `check_manifest_offsets.py`, `check_reg_addresses.py` and
`check_error_codes.py` are clean-exit-on-success and are the ones worth gating CI on.
