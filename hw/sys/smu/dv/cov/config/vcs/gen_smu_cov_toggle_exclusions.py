#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write smu_toggle_exclusions.el from urg's toggle template and the raw report.

The SMU scope grades every net of `smu`, `smu_wrapper` and `smu_axi_xbar`.
Some of those nets carry bits no SMU logic reads or
writes, and each class below states that fact and what would retire it:

* MEM-MACRO: the data words of the subsystem RAM, ROM and TCM interfaces. The
  SMU only routes them between the SMC and SEP ports and the macros in
  `hw/top/smc_ip_integration.sv` and `hw/top/sep_ip_integration.sv`.
* AXI-DATA, AXI-USER: write data, write strobe, read data and the user
  sideband of every AXI and AXI-Lite channel these units carry. The crossbar
  and the ID converters decode addresses and ids and pass these words
  through untouched.
* RTL-CONSTANT, UNION-ALIAS, SEP-OWNED: the facts
  `smu_wrapper_toggle_exclusions.el` states for the wrapper's ports, where
  the same nets recur as ports of `smu`.
* LC-SIGINT-ENCODED: the lifecycle integrity error, which the SEP eFuse shadow
  registers make unreachable by re-encoding the word they export; its
  condition rows in `smu.sv` go with it.
* ATOP-DISABLED: AWATOP, which the crossbar is built not to carry.
* FIXED-OUTBOUND-ATTRIBUTES: the AXI attributes on the SMC's outbound path,
  up to the crossbar port only the SMC feeds, that both SMC masters a bench
  can drive hold constant. Past that port the channel also carries SEP
  traffic, so it stays graded.
* APERTURE-ALIGNMENT: the SMC aperture bits no programmable setting reaches.
* REGISTER-WIDTH: the SEP region-size bits above the register field.

The SEP aperture and the SEP's outbound channels take no class: the SEP
firmware images program the region size, `smu_dtp_sep_dm_sba_test` programs
the base and sends a read and a write out through the crossbar, and
`smu_sep_bidirect_test` drives the dedicated SMC channel, so a hole there is a
stimulus gap.

Apart from those last five classes, whose facts name them, no class takes an
address, id, length, size, burst, cache, protection, QoS, region, lock or
atomic field, nor a valid, ready or enable: those are decode and handshake,
and a hole in one is a stimulus gap.

An entry names only what the raw report marks uncovered. A field every bit of
which is uncovered in both directions is excluded whole; otherwise each
uncovered range is excluded, in the direction the report marks missing. A
multi-dimensional range that is only partly uncovered stays graded, because
the exclusion format addresses one dimension.

A condition row or branch arm is taken only where the raw report marks it
Not Covered.

The inputs are the templates urg writes for the merged database and the raw
report the runner writes beside it::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl+cond+branch -report <dir>
    python3 gen_smu_cov_toggle_exclusions.py fullexclude_module.tgl \\
        <run dir>/cov/report_raw/modinfo.txt \\
        --cond fullexclude_module.cond --branch fullexclude_module.branch [--check]

The templates land in urg's working directory. They carry each module
checksum and every signature, so no field name, expression or signature below
is typed by hand. `--check` exits 1 when the committed file is
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
MODULES = ("smu", "smu_wrapper", "smu_axi_xbar")

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

# (class, matcher over the full field name, fact, what would retire it,
#  modules the class applies to or None for all four, bit windows (lo, hi) a
#  range must fall in or None for any bit).
CLASSES: list[tuple[str, re.Pattern[str], str, str, tuple[str, ...] | None, tuple | None]] = [
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
        None,
        None,
    ),
    (
        "AXI-USER",
        re.compile(r"\.(aw|ar|w|r|b)\.user$"),
        "AXI user sideband words. The pulp crossbar and the ID converters copy them "
        "beside the channel, and no SMU logic reads them.",
        "an SMU decode or remap that reads the user field",
        None,
        None,
    ),
    (
        "AXI-DATA",
        re.compile(r"\.(w\.data|w\.strb|r\.data)$"),
        "AXI and AXI-Lite write data, write strobe and read data words. The SMU decodes "
        "addresses and converts ids but passes the data path through untouched, so the "
        "bits measure the payload the SMC, SEP, DTP and bench masters chose, which "
        "their benches grade.",
        "an SMU unit that inspects or rewrites data or strobe",
        None,
        None,
    ),
    (
        "RTL-CONSTANT",
        re.compile(r"^lsio_interface_select_o$"),
        "an output smu.sv drives from a constant in this composition: the LSIO interface "
        "select follows the SPI enable, which smu.sv assigns 1 when SEP is present.",
        "the SPI enable becoming programmable",
        None,
        None,
    ),
    (
        "UNION-ALIAS",
        re.compile(r"^smc_shadow_regs_o\.(locks|fields)(\.|\[|$)"),
        "the `locks` and `fields` views of the eFuse shadow map. efuse_map_t is a packed "
        "union, so urg lists the same flops three times; the `values` view stays graded "
        "and carries every bit once.",
        "efuse_map_t ceasing to be a union",
        None,
        None,
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
        "SEP bench grades each of them.",
        "SMU logic consuming one of these nets",
        None,
        None,
    ),
    (
        "LC-SIGINT-ENCODED",
        re.compile(r"^(lc_sigint_err_o|sep_lc_sigint_err|efuse_lc_sigint_err)$"),
        "the lifecycle signal-integrity error. efuse_shadow_regs.sv (282-285, 350) keeps "
        "the raw 4-bit LC_STATE and re-encodes it with prim_diff_encode_multi, so the "
        "word the SEP exports is always a valid differential pair and the decoders in "
        "sep_lifecycle_ctrl.sv and smc_efuse_wrapper.sv fire only on corruption in flight.",
        "a fault-injection bench that corrupts the exported pair",
        ("smu",),
        None,
    ),
    (
        "ATOP-DISABLED",
        re.compile(r"\.aw\.atop$"),
        "AXI atomic operations. smu_axi_xbar.sv (131) builds the crossbar with ATOPs(1'b0), "
        "and tb_wrapper_top.sv ties the inbound AWATOP to 0.",
        "a crossbar built with ATOPs enabled",
        None,
        None,
    ),
    (
        "FIXED-OUTBOUND-ATTRIBUTES",
        re.compile(
            r"^(smc_output_axi_req|gen_sep\.smc_out_xbar_req|smc_out_req_i|xbar_slv_req\[1\])"
            r"\.(aw|ar)\.(cache|prot|qos|region|lock|burst)$"
        ),
        "AxCACHE, AxPROT, AxQOS, AxREGION, AxLOCK and AxBURST on the SMC's outbound path "
        "up to the crossbar's smc_out port. The two SMC masters a toolchain-free leaf "
        "drives hold them constant: jtag2axi.sv (1184-1216) and the iDMA register "
        "frontend (idma_reg.sv.tpl, 155-159). The crossbar's ext_out side also carries "
        "SEP traffic and stays graded.",
        "outbound traffic from the SMC CPU",
        None,
        None,
    ),
    (
        "APERTURE-ALIGNMENT",
        re.compile(
            r"^(addr_map\[1\]\.(start|end)_addr|smc_end|smc_global_base_addr_i|smc_global_base_o)$"
        ),
        "SMC aperture bits no programmable setting reaches. smc_base_config.rdl (38) "
        "requires GLOBAL_BASE and LOCAL_BASE to be aligned to REGION_SIZE; JTAG2AXI "
        "reaches BASE_CONFIG through the local window, so no size below 128 KiB can be "
        "followed by another setting and base and end bits [16:0] stay 0; LOCAL_BASE is "
        "fixed at 0xC000_0000, so REGION_SIZE[31] is never legal.",
        "a programmable LOCAL_BASE or a BASE_CONFIG path outside the local window",
        None,
        ((0, 16),),
    ),
    (
        "APERTURE-ALIGNMENT",
        re.compile(r"^(smc_region_size_i|smc_region_size_o)$"),
        "SMC aperture bits no programmable setting reaches. smc_base_config.rdl (38) "
        "requires GLOBAL_BASE and LOCAL_BASE to be aligned to REGION_SIZE; JTAG2AXI "
        "reaches BASE_CONFIG through the local window, so no size below 128 KiB can be "
        "followed by another setting and base and end bits [16:0] stay 0; LOCAL_BASE is "
        "fixed at 0xC000_0000, so REGION_SIZE[31] is never legal.",
        "a programmable LOCAL_BASE or a BASE_CONFIG path outside the local window",
        None,
        ((0, 16), (31, 31)),
    ),
    (
        "REGISTER-WIDTH",
        re.compile(r"^sep_region_size_o$"),
        "SEP region-size bits above the register field. sep_cpu_ctrl SEP_REGION_SIZE "
        "carries its size in bits [31:0] and reserves [63:32] (the generated register "
        "description), so the 56-bit port is that field zero-extended and bits [55:32] "
        "cannot move; smu.sv hands the crossbar only [31:0].",
        "SEP_REGION_SIZE.size widening past bit 31",
        ("smu",),
        ((32, 55),),
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


def _span(rng: str, sig: str) -> tuple[int, int] | None:
    """(lo, hi) bits of a one-dimensional row, or of the whole field when rng is empty."""
    m = re.fullmatch(r"\[(\d+)(?::(\d+))?\]", rng)
    if m:
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        return min(a, b), max(a, b)
    if rng:
        return None
    m = re.search(r"\[(\d+):(\d+)\]\"?$", sig.strip('"'))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return min(a, b), max(a, b)
    return 0, 0


def _clip(span: tuple[int, int], bits) -> list[tuple[int, int]]:
    if bits is None:
        return [span]
    out = []
    for lo, hi in bits:
        a, b = max(lo, span[0]), min(hi, span[1])
        if a <= b:
            out.append((a, b))
    return out


def entries(field: str, sig: str, rows: list[tuple[str, str, str]], bits=None) -> list[str]:
    """Exclusion lines for the uncovered part of one field, inside ``bits`` if given."""
    if not rows or all(r[1] == "Yes" and r[2] == "Yes" for r in rows):
        return []
    if bits is None and all(r[1] == "No" and r[2] == "No" for r in rows):
        return [f'Toggle {field} "{sig}"']
    out = []
    for name, t10, t01 in rows:
        if t10 == "Yes" and t01 == "Yes":
            continue
        rng = name[len(field) :]
        if rng.count("[") > 1:
            continue
        if bits is None:
            sels = [f" {rng}" if rng else ""]
        else:
            span = _span(rng, sig)
            if span is None:
                continue
            whole = not rng and span == (0, 0) and "[" not in sig
            sels = [
                "" if whole else (f" [{hi}:{lo}]" if hi != lo else f" [{lo}]")
                for lo, hi in _clip(span, bits)
            ]
        for sel in sels:
            if t10 == "No" and t01 == "No":
                out.append(f'Toggle {field}{sel} "{sig}"')
            else:
                direction = "0to1" if t01 == "No" else "1to0"
                out.append(f'Toggle {direction} {field}{sel} "{sig}"')
    return out


# Condition rows and branch arms, by class: (class, module, source lines or None).
# The fact and the retiring condition are the toggle class's of the same name.
SMU_SV = HERE.parents[3] / "rtl" / "smu.sv"


def _lines_assigning(path: Path, target: str) -> frozenset[int]:
    """Source lines of ``path`` whose continuous assignment drives ``target``."""
    pattern = re.compile(rf"^\s*assign\s+{re.escape(target)}\s*=")
    lines = frozenset(
        n for n, text in enumerate(path.read_text().splitlines(), 1) if pattern.match(text)
    )
    if not lines:
        sys.exit(f"{path}: no assignment to {target}")
    return lines


POINT_CLASSES: list[tuple[str, str, frozenset[int] | None]] = [
    ("LC-SIGINT-ENCODED", "smu", _lines_assigning(SMU_SV, "lc_sigint_err_o")),
]
POINT_RE = re.compile(r"^// (Condition|Branch) ")
LINE_RE = re.compile(r"LineNumber: (\d+)")


def _point_template(path: Path) -> dict[str, tuple[str, list[tuple[int, str]]]]:
    """{module: (checksum line, [(source line, point line)])} for one metric template."""
    out: dict[str, tuple[str, list[tuple[int, str]]]] = {}
    checksum, module, line_no = "", None, 0
    for line in path.read_text().splitlines():
        if line.startswith("// CHECKSUM: "):
            checksum = line[3:]
        elif line.startswith("// MODULE: "):
            module = line[len("// MODULE: ") :].strip()
            out[module] = (checksum, [])
        elif module and (m := LINE_RE.search(line)):
            line_no = int(m.group(1))
        elif module and POINT_RE.match(line):
            out[module][1].append((line_no, line[3:]))
    return out


def _module_section(modinfo: str, module: str, metric: str) -> str:
    for sec in re.split(r"\n=+\nModule : ", "\n" + modinfo)[1:]:
        if sec.split("\n", 1)[0].strip() == module and f"{metric} Coverage for Module" in sec:
            body = sec.split(f"{metric} Coverage for Module", 1)[1]
            return body.split("\n-------", 1)[0]
    return ""


def uncovered_conditions(modinfo: str, module: str) -> set[tuple[int, str]]:
    """(source line, row values) the raw report marks Not Covered."""
    out, line_no = set(), 0
    for line in _module_section(modinfo, module, "Cond").splitlines():
        if m := re.match(r"\s*LINE\s+(\d+)", line):
            line_no = int(m.group(1))
        elif m := re.match(r"^\s*([01](?:\s+[01])*)\s+Not Covered", line):
            out.add((line_no, "".join(m.group(1).split())))
    return out


def uncovered_branches(modinfo: str, module: str) -> set[tuple[int, str]]:
    """(source line, arm value) the raw report marks Not Covered."""
    out, line_no = set(), 0
    for line in _module_section(modinfo, module, "Branch").splitlines():
        if m := re.match(r"^(\d+)\s+\S", line):
            line_no = int(m.group(1))
        elif m := re.match(r"^([01])\s+Not Covered", line):
            out.add((line_no, m.group(1)))
    return out


def point_blocks(cond: Path | None, branch: Path | None, modinfo: Path, counts) -> list[str]:
    text = modinfo.read_text()
    facts = {name: (fact, retire) for name, _, fact, retire, _, _ in CLASSES}
    out: list[str] = []
    for path, kind in ((cond, "Condition"), (branch, "Branch")):
        if path is None:
            continue
        template = _point_template(path)
        for cls, module, lines in POINT_CLASSES:
            if module not in template:
                continue
            checksum, points = template[module]
            holes = (
                uncovered_conditions(text, module)
                if kind == "Condition"
                else uncovered_branches(text, module)
            )
            picked = []
            for line_no, point in points:
                if lines is not None and line_no not in lines:
                    continue
                if kind == "Condition":
                    m = re.search(r'\(\d+ "([01]+)"\)$', point)
                    key = m.group(1) if m else None
                else:
                    m = re.search(r'\(\d+\) "\S+ ([01])"$', point)
                    key = m.group(1) if m else None
                if key is not None and (line_no, key) in holes:
                    picked.append(point)
            if picked:
                fact, retire = facts[cls]
                counts[cls] += len(picked)
                out += ["", checksum, f"MODULE: {module}", ""]
                out.append(f'ANNOTATION: "SMU-{kind.upper()}-{cls}: {fact} Retired by {retire}."')
                out += picked
    return out


def render(
    template: Path, modinfo: Path, cond: Path | None = None, branch: Path | None = None
) -> tuple[str, dict[str, int]]:
    sections = template_sections(template)
    reports = report_rows(modinfo)
    skip = {"smu_wrapper": wrapper_excluded()}
    counts: dict[str, int] = {c[0]: 0 for c in CLASSES}
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMU VCS exclusions, applied with -elfile at report time.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smu_cov_toggle_exclusions.py from urg's",
        "// `-dump full_exclusions tgl+cond+branch` templates of the merged database",
        "// and the raw report; regenerate rather than edit. README.md beside this",
        "// file states each class's fact; the ANNOTATION before each class repeats it.",
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
        applicable = [c for c in CLASSES if c[4] is None or module in c[4]]
        claimed: dict[str, tuple] = {}
        for field, _ in fields:
            if field in skip.get(module, set()):
                continue
            for c in applicable:
                if c[1].search(field):
                    claimed[field] = c
                    break
        block: list[str] = []
        emitted: set[tuple[str, str]] = set()
        for c in applicable:
            cls, _, fact, retire, _, bits = c
            lines: list[str] = []
            for field, sig in fields:
                if claimed.get(field) is c:
                    lines += entries(field, sig, by_field[field], bits)
            if lines:
                counts[cls] += len(lines)
                if (cls, fact) not in emitted:
                    block += ["", f'ANNOTATION: "SMU-TGL-{cls}: {fact} Retired by {retire}."']
                    emitted.add((cls, fact))
                block += lines
        if block:
            out += ["", checksum, f"MODULE: {module}", *block]
    out += point_blocks(cond, branch, modinfo, counts)
    return "\n".join(out) + "\n", counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template", type=Path, help="urg fullexclude_module.tgl")
    ap.add_argument("modinfo", type=Path, help="the run's cov/report_raw/modinfo.txt")
    ap.add_argument("--cond", type=Path, help="urg fullexclude_module.cond")
    ap.add_argument("--branch", type=Path, help="urg fullexclude_module.branch")
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args()
    text, counts = render(args.template, args.modinfo, args.cond, args.branch)
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
