#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write the SMC VCS coverage exclusion files from urg's exclusion templates.

Two structural facts of the compiled design leave coverage points that no
access from this bench can reach, and SEP records the same facts in
`hw/sys/sep/dv/cov/config/vcs/sep_regblock_exclusions.el`:

* A1 NO-STALL: a PeakRDL register block whose cpuif has no external
  registers hardwires `cpuif_req_stall_rd` and `cpuif_req_stall_wr` to zero,
  so the AXI-Lite handshake can never see valid without ready and the stall
  branches of the request path never execute.
* A2 NO-ERROR: a PeakRDL register block generated without an address or
  access check ("No valid address check" in the generated source) never sets
  `decoded_err`, `cpuif_wr_err` or `cpuif_rd_err`, so its error branches and
  the SLVERR values of `bresp`/`rresp` never occur.

A third fact is not a register block's: a CRC or parity network is an XOR
reduction, and condition coverage enumerates 2^n input combinations of it.
The X1 XOR-NETWORK class names those expressions.

Three FSM facts follow from the source rather than from any access. urg's FSM
score counts transitions, and the extractor lists every assignment to the
state variable as a transition:

* F1 LOOPVAR: `telemetry_receiver.block_index` is the loop variable of the
  message decoder, extracted as an FSM because it is a state-shaped register;
  its settled value is fixed by `NUM_BLOCKS_PER_PACKET`.
* F2 DEFAULT: `avsbus_controller.cur_state` has `next_state = AVS_IDLE` as the
  always_comb default, which the extractor reads as an edge from every state
  to AVS_IDLE; every case arm assigns next_state, so the default never fires.
* F3 TIEOFF: `trace_axi_master.state` never leaves RESET_VALUE because
  `smc_dfd_wrap` ties every `m_trc_axi_*` response input to zero.
* F4 PARAM-OFF: `efuse_interface_controller.efuse_reg_select` reaches
  EFUSE_MMR_REG_MAP only when the instance has lifecycle state, and
  `smc_efuse_wrapper` instantiates it with `HAS_LC_STATE = 0`, so the decode
  arm that selects the state is not elaborated.

Input is the set of templates urg writes for the merged database::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions cond+branch+fsm -report <dir>

which leaves fullexclude_module.{cond,branch,fsm} in the working directory.
Every checksum and entry text below comes from those templates.

Only rows and branches the merged report marks uncovered are written, so a
reachable row is never hidden by a pattern. The report has to be the one urg
wrote without an exclusion file: the runner keeps it as
`<run dir>/cov/report_raw/modinfo.txt` beside the effective report, and a row
the effective report already shows as `Excluded` would otherwise drop out of
the regenerated file.

    python3 gen_smc_cov_exclusions.py <template dir> <run dir>/cov/report_raw/modinfo.txt
    python3 gen_smc_cov_exclusions.py <template dir> <modinfo.txt> --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
REGBLOCK_OUT = HERE / "smc_regblock_exclusions.el"
XOR_OUT = HERE / "smc_xor_network_exclusions.el"
FSM_OUT = HERE / "smc_fsm_exclusions.el"

CHECKSUM_RE = re.compile(r"^// CHECKSUM: (\"[^\"]*\")")
MODULE_RE = re.compile(r"^// MODULE: (\S+)")
FILE_RE = re.compile(r'^// ANNOTATION: "FileName: (\S+), LineNumber: (\d+)"')
ENTRY_RE = re.compile(r"^// ((?:Condition|Block|Branch|Line|Fsm|State|Transition) .*)$")
FSM_ENTRY_RE = re.compile(r'^(State|Transition) (\S+?)(?:->(\S+))? "[^"]*"$')
HANDSHAKE_RE = re.compile(
    r"\((s_axil_\w*valid)\s*&&\s*(s_axil_\w*ready)\)\s+1\s+-1\"\s+\(\d+ \"10\"\)"
)
STALL_RE = re.compile(r"cpuif_req_stall")
ERROR_RE = re.compile(r"decoded_err|cpuif_wr_err|cpuif_rd_err|readback_err|axil_resp_buffer_err")
XOR_TERM_RE = re.compile(r"^\((?:[A-Za-z_][\w\[\]\.:]*\s*\^\s*){3,}[A-Za-z_][\w\[\]\.:]*\)")
COND_ROW_RE = re.compile(r'^(Condition \d+ "\d+" "(.*) 1 -1") \((\d+) "([01]+)"\)$')
BRANCH_ROW_RE = re.compile(r'^(Branch \d+ "\d+" "(.*)") \((\d+)\) "(.*) (1|0)"$')

A1 = (
    "SMC-REGBLOCK-A1-NOSTALL: the PeakRDL cpuif of this block hardwires "
    "cpuif_req_stall_rd and cpuif_req_stall_wr to zero, so an AXI-Lite request is "
    "accepted the cycle it is valid and the stall branches of the request path never "
    "execute; the valid-without-ready row of each handshake condition has no access "
    "that can produce it."
)
A2 = (
    "SMC-REGBLOCK-A2-NOERROR: the block is generated without an address or access "
    "check, so decoded_err, cpuif_wr_err and cpuif_rd_err hold zero and bresp/rresp "
    "never leave OKAY; the error branches have no access that can enter them. The "
    "fabric's own SLVERR and DECERR paths are graded on their modules, not here."
)
X1 = (
    "SMC-X1-XOR-NETWORK: a CRC or parity network is an XOR reduction of its inputs, and "
    "condition coverage of it enumerates every combination of the terms; the network's "
    "function is one value per input vector and is proven by the data the block "
    "produces, which the tests compare."
)
F1 = (
    "SMC-FSM-F1-LOOPVAR: block_index is the loop variable of the message decoder, a "
    "state-shaped register the extractor reports as an FSM; its settled value is fixed "
    "by NUM_BLOCKS_PER_PACKET and no ATB stimulus moves it."
)
F2 = (
    "SMC-FSM-F2-DEFAULT: next_state = AVS_IDLE is the always_comb default of the protocol "
    "FSM, which the extractor lists as a transition from every state; every case arm "
    "assigns next_state, so no state reaches AVS_IDLE through the default."
)
F3 = (
    "SMC-FSM-F3-TIEOFF: smc_dfd_wrap ties every m_trc_axi_* response input to zero, so "
    "the trace write master never sees a handshake and its state register cannot leave "
    "RESET_VALUE."
)
F4 = (
    "SMC-FSM-F4-PARAM-OFF: the MMR register map exists only when the eFuse instance has "
    "lifecycle state, and smc_efuse_wrapper instantiates the controller with HAS_LC_STATE "
    "= 0, so the decode arm selecting EFUSE_MMR_REG_MAP is not elaborated and no access "
    "reaches the state or its edges."
)

# (module, fsm) -> (class, selector). Selector None takes every point of the FSM;
# ("to", S) takes the uncovered transitions into S; ("state", S) takes S and the
# uncovered transitions that leave or enter it.
FSM_FACTS: dict[tuple[str, str], tuple[str, tuple[str, str] | None]] = {
    ("telemetry_receiver", "block_index"): (F1, None),
    ("avsbus_controller", "cur_state"): (F2, ("to", "AVS_IDLE")),
    ("trace_axi_master", "state"): (F3, None),
    ("efuse_interface_controller", "efuse_reg_select"): (F4, ("state", "EFUSE_MMR_REG_MAP")),
}


def uncovered_rows(modinfo: Path) -> dict[tuple[str, str], set[str]]:
    """(module, expression) -> set of term vectors the report marks Not Covered."""
    rows: dict[tuple[str, str], set[str]] = {}
    module = ""
    expr = ""
    terms: list[str] = []
    in_cond = False
    for line in modinfo.read_text(errors="replace").splitlines():
        m = re.match(r"^(\w+) Coverage for Module : (\S+)", line)
        if m:
            in_cond = m.group(1) == "Cond"
            module = m.group(2).split("(")[0]
            continue
        if not in_cond:
            continue
        m = re.match(r"^\s*EXPRESSION\s*(.*)$", line)
        if m:
            expr = m.group(1).strip()
            terms = []
            continue
        # A long XOR network is listed one term per row under "Number  Term".
        m = re.match(r"^\s*\d+\s+(\S+)\s*(\^?)\s*$", line)
        if m and not expr:
            terms.append(m.group(1).rstrip(")"))
            if not m.group(2):
                expr = "(" + " ^ ".join(terms) + ")"
            continue
        m = re.match(r"^\s*((?:[01]\s+)+)Not Covered", line)
        if m and expr:
            rows.setdefault((module, expr), set()).add(m.group(1).replace(" ", ""))
    return rows


class Section:
    def __init__(self, checksum: str, module: str) -> None:
        self.checksum = checksum
        self.module = module
        self.entries: list[tuple[str, str]] = []  # (source line annotation, entry)


def parse(template: Path) -> dict[str, Section]:
    sections: dict[str, Section] = {}
    checksum = ""
    current: Section | None = None
    src = ""
    for line in template.read_text(errors="replace").splitlines():
        m = CHECKSUM_RE.match(line)
        if m:
            checksum = m.group(1)
            continue
        m = MODULE_RE.match(line)
        if m:
            current = sections.setdefault(m.group(1), Section(checksum, m.group(1)))
            continue
        m = FILE_RE.match(line)
        if m:
            src = f"{m.group(1)}:{m.group(2)}"
            continue
        m = ENTRY_RE.match(line)
        if m and current is not None:
            current.entries.append((src, m.group(1)))
    return sections


def regblock_facts(module: str, source: str) -> tuple[bool, bool]:
    """(stall hardwired, no error decode) for a generated register block source."""
    path = Path(source.split(":")[0])
    if "/regs/gen/sv/" not in str(path) or not path.is_file():
        return (False, False)
    text = path.read_text(errors="replace")
    stall0 = bool(re.search(r"assign cpuif_req_stall_rd = '0", text))
    noerr = "No valid address check" in text
    return (stall0, noerr)


def select_regblock(entry: str, stall0: bool, noerr: bool, uncovered: set[str]) -> str | None:
    """Return the class an entry belongs to, or None when it stays graded."""
    m = COND_ROW_RE.match(entry)
    if m:
        expr, vec = m.group(2), m.group(4)
        if vec not in uncovered:
            return None
        if stall0 and (HANDSHAKE_RE.search(entry) or STALL_RE.search(expr)):
            return A1
        if noerr and ERROR_RE.search(expr):
            return A2
        return None
    m = BRANCH_ROW_RE.match(entry)
    if m:
        cond, direction = m.group(2), m.group(5)
        if direction != "1":
            return None
        if stall0 and STALL_RE.search(cond):
            return A1
        if noerr and ERROR_RE.search(cond):
            return A2
    return None


def render_regblock(
    templates: dict[str, dict[str, Section]], uncovered: dict[tuple[str, str], set[str]]
) -> tuple[str, int]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- PeakRDL regblock structural facts.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_cov_exclusions.py from urg's exclusion templates and",
        "// the merged report; regenerate rather than edit. Only rows and branch",
        "// directions the report marks uncovered are listed. The generator's",
        "// docstring and the ANNOTATION before each block state the two facts",
        "// (A1 NO-STALL, A2 NO-ERROR) and which blocks each applies to.",
        "//==================================================",
    ]
    modules = sorted({m for t in templates.values() for m in t})
    count = 0
    for module in modules:
        block: list[tuple[str, str]] = []
        facts_cache: dict[str, tuple[bool, bool]] = {}
        checksum = ""
        for metric in ("cond", "branch"):
            section = templates[metric].get(module)
            if section is None:
                continue
            checksum = section.checksum
            for src, entry in section.entries:
                stall0, noerr = facts_cache.setdefault(
                    src.split(":")[0], regblock_facts(module, src)
                )
                if not (stall0 or noerr):
                    continue
                m = COND_ROW_RE.match(entry)
                rows = uncovered.get((module, m.group(2)), set()) if m else set()
                reason = select_regblock(entry, stall0, noerr, rows)
                if reason:
                    block.append((reason, entry))
        if not block:
            continue
        out += ["", f"CHECKSUM: {checksum}"]
        for reason in (A1, A2):
            if any(r == reason for r, _ in block):
                out.append(f'ANNOTATION: "{reason}"')
        out.append(f"MODULE: {module}")
        out += [e for _, e in block]
        count += len(block)
    return "\n".join(out) + "\n", count


def render_xor(
    templates: dict[str, dict[str, Section]], uncovered: dict[tuple[str, str], set[str]]
) -> tuple[str, int]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- XOR reduction networks (CRC, parity).",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_cov_exclusions.py from urg's condition template and",
        "// the merged report; regenerate rather than edit. Only conditions that are",
        "// an XOR of four or more terms are listed, and only their uncovered rows;",
        "// the network's output is what the tests compare.",
        "//==================================================",
    ]
    count = 0
    for module, section in sorted(templates["cond"].items()):
        rows = []
        for _, entry in section.entries:
            m = COND_ROW_RE.match(entry)
            if m is None:
                continue
            expr, vec = m.group(2), m.group(4)
            if XOR_TERM_RE.match(expr) and vec in uncovered.get((module, expr), set()):
                rows.append(entry)
        if rows:
            out += ["", f"CHECKSUM: {section.checksum}", f'ANNOTATION: "{X1}"', f"MODULE: {module}"]
            out += rows
            count += len(rows)
    return "\n".join(out) + "\n", count


def uncovered_fsm(modinfo: Path) -> dict[tuple[str, str], set[str]]:
    """(module, fsm) -> states and "a->b" transitions the report marks Not Covered."""
    out: dict[tuple[str, str], set[str]] = {}
    module = fsm = ""
    in_fsm = False
    for line in modinfo.read_text(errors="replace").splitlines():
        m = re.match(r"^(\w+) Coverage for (Module|Instance) : (\S+)", line)
        if m:
            in_fsm = m.group(1) == "FSM" and m.group(2) == "Module"
            module = m.group(3).split("(")[0]
            continue
        if not in_fsm:
            continue
        m = re.match(r"^Summary for FSM :: (\S+)", line)
        if m:
            fsm = m.group(1)
            continue
        m = re.match(r"^(\S+)\s+\S+\s+Not Covered", line)
        if m and fsm:
            out.setdefault((module, fsm), set()).add(m.group(1))
    return out


def render_fsm(
    templates: dict[str, dict[str, Section]], uncovered: dict[tuple[str, str], set[str]]
) -> tuple[str, int]:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        "// SMC VCS coverage exclusions -- FSM extraction facts.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smc_cov_exclusions.py from urg's FSM template and the",
        "// merged report; regenerate rather than edit. F1 and F3 take every point of",
        "// a state variable that is not a reachable control FSM; F2 takes only the",
        "// uncovered edges the always_comb default contributes; F4 takes a state whose",
        "// decode arm a parameter leaves unelaborated. The generator's docstring and",
        "// the ANNOTATION before each block state the facts.",
        "//==================================================",
    ]
    count = 0
    for module, section in sorted(templates["fsm"].items()):
        fsm = ""
        block: list[tuple[str, str]] = []
        for _, entry in section.entries:
            if entry.startswith("Fsm "):
                fsm = entry.split()[1]
                if (module, fsm) in FSM_FACTS:
                    block.append(("", entry))
                continue
            fact = FSM_FACTS.get((module, fsm))
            m = FSM_ENTRY_RE.match(entry)
            if fact is None or m is None:
                continue
            reason, selector = fact
            kind, src, dst = m.group(1), m.group(2), m.group(3)
            if selector is None:
                block.append((reason, entry))
                continue
            mode, state = selector
            missing = uncovered.get((module, fsm), set())
            if kind == "State":
                if mode == "state" and src == state:
                    block.append((reason, entry))
            elif f"{src}->{dst}" in missing:
                if (mode == "to" and dst == state) or (mode == "state" and state in (src, dst)):
                    block.append((reason, entry))
        if not any(r for r, _ in block):
            continue
        out += ["", f"CHECKSUM: {section.checksum}"]
        for reason in (F1, F2, F3, F4):
            if any(r == reason for r, _ in block):
                out.append(f'ANNOTATION: "{reason}"')
        out.append(f"MODULE: {module}")
        out += [e for _, e in block]
        count += sum(1 for r, _ in block if r)
    return "\n".join(out) + "\n", count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template_dir", type=Path, help="holds fullexclude_module.{cond,branch,fsm}")
    ap.add_argument("modinfo", type=Path, help="the run's cov/report/modinfo.txt")
    ap.add_argument("--check", action="store_true", help="fail if the committed files are stale")
    args = ap.parse_args()
    templates = {
        m: parse(args.template_dir / f"fullexclude_module.{m}") for m in ("cond", "branch", "fsm")
    }
    uncovered = uncovered_rows(args.modinfo)
    reg_text, reg_n = render_regblock(templates, uncovered)
    xor_text, xor_n = render_xor(templates, uncovered)
    fsm_text, fsm_n = render_fsm(templates, uncovered_fsm(args.modinfo))
    outputs = ((REGBLOCK_OUT, reg_text), (XOR_OUT, xor_text), (FSM_OUT, fsm_text))
    if args.check:
        stale = [p for p, t in outputs if not p.is_file() or p.read_text() != t]
        for p in stale:
            print(f"{p} is stale; rerun without --check", file=sys.stderr)
        return 1 if stale else 0
    for p, t in outputs:
        p.write_text(t)
    print(
        f"wrote {REGBLOCK_OUT.name}: {reg_n} entries; {XOR_OUT.name}: {xor_n} entries; "
        f"{FSM_OUT.name}: {fsm_n} entries"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
