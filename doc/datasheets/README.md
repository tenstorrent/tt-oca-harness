<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# OCAH datasheets

These are short product summaries for SoC and chiplet integrators. They are not
substitutes for the Integrator Guide or Technical Reference Manual. Each sheet
uses a common two-page structure derived from the way mature commercial IP
datasheets expose highlights, architecture, stable specifications, features,
integration dependencies, verification status, and deliverables.

The OCAH structure deliberately replaces procurement-oriented “Target
Applications” and process-oriented “Technologies” panels with “System role”
and “Integration dependencies”. Each sheet uses the same system-context visual
grammar: external equipment on the left, the OCAH chiplet and subsystem
internals in the center, and peer chiplets on the right. Claims must
distinguish:

- an architectural capability evidenced by RTL;
- a value in the checked-in reference configuration;
- an implementation result that depends on process and physical design; and
- a verification or compliance claim that requires explicit evidence.

Copy `template.adoc` when starting a product. Retain its section markers, set
the status to `Beta`, cite evidence in `content-readiness.md`, and do not put
unresolved placeholders in a release source. Keep the rendered result to at most
four US Letter pages.

Use `Feature` and `Description` as the column headings in **At a Glance** tables,
and `Feature` and `Integration options` in **Interfaces and configuration**
tables. State the reference configuration in the accompanying text.

Define non-universal acronyms on first use and list the specialized ones in a
**Terms** section, using the canonical expansion from the acronym registry
(`styles/config/scripts/AcronymDefinitions.tengo`). Include a blank
**Document control** revision table for completion at release.

Build and validate all available sheets from the repository root:

```console
make ocah-doc-datasheets-pdf
# or, without a host Ruby installation:
./scripts/docker-run.sh doc-pdf datasheets
```

The PDFs are written to `doc/datasheets/dist/` and staged into the website's
`downloads/` directory by the normal GitHub Pages staging targets.
