#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write smu_toggle_exclusions.el from urg's toggle template and the raw report.

The SMU scope grades every net of `smu`, `smu_wrapper`, `smu_axi_xbar` and
`axi_window_remap`. Some of those nets carry bits no SMU logic reads or
writes, and each class below states that fact and what would retire it:

* MEM-MACRO: the data words of the subsystem RAM, ROM and TCM interfaces. The
  SMU only routes them between the SMC and SEP ports and the macros in
  `hw/top/smc_ip_integration.sv` and `hw/top/sep_ip_integration.sv`.
* AXI-DATA, AXI-USER: write data, write strobe, read data and the user
  sideband of every AXI and AXI-Lite channel these units carry. The crossbar,
  the ID converters and the alias remap decode addresses and ids and pass
  these words through untouched.
* RTL-CONSTANT, UNION-ALIAS, SEP-OWNED: the facts
  `smu_wrapper_toggle_exclusions.el` states for the wrapper's ports, where
  the same nets recur as ports of `smu`.

No class takes an address, id, length, size, burst, cache, protection, QoS,
region, lock or atomic field, nor a valid, ready or enable: those are decode
and handshake, and a hole in one is a stimulus gap.

An entry names only what the raw report marks uncovered. A field every bit of
which is uncovered in both directions is excluded whole; otherwise each
uncovered range is excluded, in the direction the report marks missing. A
multi-dimensional range that is only partly uncovered stays graded, because
the exclusion format addresses one dimension.

The inputs are the template urg writes for the merged database and the raw
report the runner writes beside it::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl -report <dir>
    python3 gen_smu_cov_toggle_exclusions.py <dir>/../fullexclude_module.tgl \\
        <run dir>/cov/report_raw/modinfo.txt [--check]

The template leaves `fullexclude_module.tgl` in urg's working directory. It
carries each module checksum and one signature per field, so no field name or
signature below is typed by hand. `--check` exits 1 when the committed file is
out of date instead of rewriting it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "smu_toggle_exclusions.el"
WRAPPER_FILE = HERE / "smu_wrapper_toggle_exclusions.el"
MODULES = ("smu", "smu_wrapper", "smu_axi_xbar", "axi_window_remap")

MEM_IF = (
    r"(smc_scratch_ram_intf|smc_l1_[id]cache_(tag|data)_intf|smc_rom_intf|trace_mem|"
    r"i3c_(dat|dct|rlt)_mem|sep_(sram|km_sram_mem|km_rom_mem|crypto_pka_[id]mem_sram|"
    r"boot_rom|cpu_tcm)|abr_mem)_(req|rsp|resp|sink|src)(_[io])?(\[\d+\])?"
)
MEM_DATA = (
    r"([a-z0-9_]*_)?(wdata|rdata|wmask|wstrobe|strb|be|wparity|rparity|parity|"
    r"mem_wr_data|mem_rd_data|wr_data_bank|wr_ecc_bank|bank_wr_data|bank_wr_ecc|"
    r"bank_dout|bank_ecc)"
)

# (class, matcher over the full field name, fact, what would retire it).
CLASSES: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "MEM-MACRO",
        re.compile(rf"^{MEM_IF}\.({MEM_DATA}|[a-z0-9_]+\.{MEM_DATA})$"),
        "data, mask, strobe, parity and ECC words of the SMC and SEP RAM, ROM and TCM "
        "interfaces. smu.sv connects each such port of u_smc and u_sep straight to its "
        "own port, smu_wrapper.sv connects that to hw/top/smc_ip_integration.sv or "
        "hw/top/sep_ip_integration.sv, where the macros are, and no SMU logic reads or "
        "writes the words; the SMC and SEP benches grade the memories. Address, enable "
        "and write-enable fields stay graded.",
        "an SMU process that reads or drives these words, or the macros moving under u_smu",
    ),
    (
        "AXI-USER",
        re.compile(r"\.(aw|ar|w|r|b)\.user$"),
        "AXI user sideband words. The pulp crossbar, the ID converters and "
        "axi_window_remap copy them beside the channel, and no SMU logic reads them.",
        "an SMU decode or remap that reads the user field",
    ),
    (
        "AXI-DATA",
        re.compile(r"\.(w\.data|w\.strb|r\.data)$"),
        "AXI and AXI-Lite write data, write strobe and read data words. The SMU decodes "
        "addresses and converts ids but passes the data path through untouched, so the "
        "bits measure the payload the SMC, SEP, DTP and bench masters chose, which "
        "their benches grade.",
        "an SMU unit that inspects or rewrites data or strobe",
    ),
    (
        "RTL-CONSTANT",
        re.compile(r"^(lcc_demote_state_[12]_o|lsio_interface_select_o)$"),
        "outputs smu.sv drives from a constant in this composition: the lifecycle demote "
        "states are tied low and the LSIO interface select follows the SPI enable, "
        "which smu.sv assigns 1 when SEP is present.",
        "the demote states or the SPI enable becoming programmable",
    ),
    (
        "UNION-ALIAS",
        re.compile(r"^smc_shadow_regs_o\.(locks|fields)(\.|\[|$)"),
        "the `locks` and `fields` views of the eFuse shadow map. efuse_map_t is a packed "
        "union, so urg lists the same flops three times; the `values` view stays graded "
        "and carries every bit once.",
        "efuse_map_t ceasing to be a union",
    ),
    (
        "SEP-OWNED",
        re.compile(
            r"^(sep_io_spi_req_o|sep_cpu_trace_o|sep_lockstep_ctrl_i|"
            r"sep_lockstep_status_o|sep_ext_interrupts_i|entropy_rosc_sample_clk_i)(\.|\[|$)"
        ),
        "SEP passthroughs smu.sv only routes: the SEP SPI host and CPU trace need SEP "
        "firmware, the lockstep pair is inert without RV_LOCKSTEP_ENABLE, and the SEP "
        "external interrupts and entropy sample clock terminate inside the SEP. The "
        "SEP bench grades each of them. The SEP aperture base and size feed the "
        "crossbar address map and stay graded, as does the lifecycle integrity error, "
        "which smu.sv ORs with the SMC eFuse one.",
        "SMU logic consuming one of these nets",
    ),
]

TOGGLE_RE = re.compile(r'^// Toggle (\S+) "(.*)"$')
RANGES = re.compile(r"((?:\[[^\]]*\])+)$")


def template_sections(path: Path) -> dict[str, tuple[str, list[tuple[str, str]]]]:
    """Return {module: (checksum line, [(field, signature)])} for MODULES."""
    out: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    checksum = ""
    module = None
    for line in path.read_text().splitlines():
        if line.startswith("// CHECKSUM: "):
            checksum = line[3:]
        elif line.startswith("// MODULE: "):
            name = line[len("// MODULE: ") :].strip()
            module = name if name in MODULES else None
            if module:
                out[module] = (checksum, [])
        elif module:
            m = TOGGLE_RE.match(line)
            if m:
                out[module][1].append((m.group(1), m.group(2)))
    missing = [m for m in MODULES if m not in out]
    if missing:
        sys.exit(f"{path}: no template section for {', '.join(missing)}")
    return out


def report_rows(path: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Return {module: [(row name, 1->0, 0->1)]} from the raw report's toggle details."""
    text = "\n" + path.read_text()
    out: dict[str, list[tuple[str, str, str]]] = {}
    for sec in re.split(r"\n=+\nModule : ", text)[1:]:
        name = sec.split("\n", 1)[0].strip()
        if name not in MODULES or "Toggle Coverage for Module" not in sec:
            continue
        body = sec.split("Toggle Coverage for Module", 1)[1].split("\n-----", 1)[0]
        rows = out.setdefault(name, [])
        for line in body.splitlines():
            p = line.split()
            if len(p) >= 4 and p[1] in ("Yes", "No"):
                rows.append((p[0], p[2], p[3]))
    return out


def wrapper_excluded() -> set[str]:
    return {
        line.split()[1]
        for line in WRAPPER_FILE.read_text().splitlines()
        if line.startswith("Toggle ")
    }


def entries(field: str, sig: str, rows: list[tuple[str, str, str]]) -> list[str]:
    """Exclusion lines for the uncovered part of one field."""
    if not rows or all(r[1] == "Yes" and r[2] == "Yes" for r in rows):
        return []
    if all(r[1] == "No" and r[2] == "No" for r in rows):
        return [f'Toggle {field} "{sig}"']
    out = []
    for name, t10, t01 in rows:
        if t10 == "Yes" and t01 == "Yes":
            continue
        rng = name[len(field) :]
        if rng.count("[") > 1:
            continue
        sel = f" {rng}" if rng else ""
        if t10 == "No" and t01 == "No":
            out.append(f'Toggle {field}{sel} "{sig}"')
        else:
            direction = "0to1" if t01 == "No" else "1to0"
            out.append(f'Toggle {direction} {field}{sel} "{sig}"')
    return out


def render(template: Path, modinfo: Path) -> tuple[str, dict[str, int]]:
    sections = template_sections(template)
    reports = report_rows(modinfo)
    skip = {"smu_wrapper": wrapper_excluded()}
    counts: dict[str, int] = {name: 0 for name, _, _, _ in CLASSES}
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMU VCS toggle exclusions, applied with -elfile at report time.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smu_cov_toggle_exclusions.py from urg's",
        "// `-dump full_exclusions tgl` template of the merged database and the raw",
        "// report; regenerate rather than edit. README.md beside this file states",
        "// each class's fact; the ANNOTATION before each class repeats it.",
        "//==================================================",
    ]
    for module in MODULES:
        checksum, fields = sections[module]
        rows = reports.get(module, [])
        by_field: dict[str, list[tuple[str, str, str]]] = {f: [] for f, _ in fields}
        for row in rows:
            name = row[0]
            while name not in by_field:
                m = RANGES.search(name)
                if not m:
                    break
                name = name[: m.start()]
            if name in by_field:
                by_field[name].append(row)
        block: list[str] = []
        for cls, pattern, fact, retire in CLASSES:
            lines: list[str] = []
            for field, sig in fields:
                if field in skip.get(module, set()) or not pattern.search(field):
                    continue
                if any(
                    p.search(field)
                    for c, p, _, _ in CLASSES[: CLASSES.index((cls, pattern, fact, retire))]
                ):
                    continue
                lines += entries(field, sig, by_field[field])
            if lines:
                counts[cls] += len(lines)
                block += ["", f'ANNOTATION: "SMU-TGL-{cls}: {fact} Retired by {retire}."']
                block += lines
        if block:
            out += ["", checksum, f"MODULE: {module}", *block]
    return "\n".join(out) + "\n", counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template", type=Path, help="urg fullexclude_module.tgl")
    ap.add_argument("modinfo", type=Path, help="the run's cov/report_raw/modinfo.txt")
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args()
    text, counts = render(args.template, args.modinfo)
    if args.check:
        if OUTPUT.read_text() != text:
            print(f"{OUTPUT} is stale; rerun without --check", file=sys.stderr)
            return 1
        print(f"{OUTPUT} is current")
        return 0
    OUTPUT.write_text(text)
    print(f"wrote {OUTPUT}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
