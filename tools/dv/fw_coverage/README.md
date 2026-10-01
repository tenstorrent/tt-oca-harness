<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SEP Boot ROM firmware coverage

This tool converts VeeR EL2 retired-PC traces from a SEP `rom_fw` simulation
into separate Coverview reports for the `boot_rom`, `boot_rom_ot`, and
`boot_rom_ot_pio` firmware variants. Each variant is retraced with the exact
`boot_rom.elf` staged into its passing simulation leaves; PCs from different
ELFs are never merged.

## Generate a report

Run the ROM firmware tests with trace collection explicitly enabled:

```bash
RUN_DIR="${TMPDIR:?TMPDIR must name the scratch area}/sep-rom-fw-coverage"

python3 tools/dv/run_dv.py --dut sep --items rom_fw --regress \
  --tool verilator --sim-jobs 8 --build-jobs 24 \
  --plusarg +sep_rom_fw_coverage \
  --run-dir "$RUN_DIR"
```

Generate reports from that completed run:

```bash
uv run --python 3.11 \
  python tools/dv/fw_coverage/gen_sep_rom_coverage.py --run-dir "$RUN_DIR"
```

The landing page is
`tools/dv/fw_coverage/output/<run-directory-name>/index.html`. Only complete
traces from passing final leaves contribute. Skipped failed, corrupt, empty,
or non-ROM leaves are listed on stderr and in `manifest.json`. The `output/`
tree is gitignored; pass `--output-dir` to place one report elsewhere.

The first report invocation installs these pinned upstream components under
`$TMPDIR/ocah-fw-coverage-tools`:

- Renode execution tracer `v1.16.1`
- `info-process` revision `4c661cd`
- Coverview revision `15386d3`

That setup needs `git`, `npm`, network access, and Python virtual-environment
support. Pass `--tools-dir` to select another reusable scratch cache.
