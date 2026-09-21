#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write smu_wrapper_toggle_exclusions.el from urg's toggle exclusion template.

urg grades `smu_wrapper` toggle per port field: a field counts covered only
when every bit of it toggled in both directions. Some fields on the wrapper
can never meet that on this bench, and grading them here attributes another
owner's coverage to the wrapper. This script names those fields, with the
reason for each class, in the exclusion file `-elfile` consumes at report
time.

The input is the template urg writes for the merged database::

    urg -dir <run dir>/cov/merged.vdb -dump full_exclusions tgl -report <dir>

which leaves `fullexclude_module.tgl` in the working directory. The template
carries the module checksum urg requires and one commented `Toggle` line per
field, so the field names and signatures below are never typed by hand.

    python3 gen_smu_wrapper_toggle_exclusions.py <fullexclude_module.tgl>
    python3 gen_smu_wrapper_toggle_exclusions.py <fullexclude_module.tgl> --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "smu_wrapper_toggle_exclusions.el"
MODULE = "smu_wrapper"

# (class name, matcher over the field name, reason). The first match wins.
CLASSES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "AXI-USER",
        re.compile(r"^smu_axi_(in|out)_(req|resp)_[io]\.(aw|ar|w|r|b)\.user$"),
        "AXI user sideband words on the crossbar's inbound and outbound ports. The SMU "
        "neither reads nor writes them; the crossbar carries them beside the channel "
        "unchanged, so their bits toggle only when a master or the bench varies a field "
        "nothing in the SMU consumes.",
    ),
    (
        "AXI-DATA",
        re.compile(r"^smu_axi_(in|out)_(req|resp)_[io]\.(w\.data|w\.strb|r\.data)$"),
        "AXI write data, write strobe and read data words. The crossbar decodes addresses "
        "and converts ids but passes the data path through untouched, so per-bit toggle "
        "of these words measures the payload the SMC, SEP and bench masters chose, which "
        "their own benches grade. Address and id words stay graded: the SMU decodes the "
        "one and remaps the other.",
    ),
    (
        "ATB-PAYLOAD",
        re.compile(r"^telemetry_(atdata|atid)_i$"),
        "ATB data and id words of the telemetry receivers. The receivers are SMC "
        "peripherals graded on the SMC bench; the wrapper passes the words through.",
    ),
    (
        "DFT",
        re.compile(r"^(test_en_i|scan_rst_ni)$"),
        "DFT pins. Functional simulation holds them at their functional value; scan "
        "insertion and scan-mode reset bypass are not exercised on this bench.",
    ),
    (
        "RTL-CONSTANT",
        re.compile(r"^(lcc_demote_state_[12]_o|lsio_interface_select_o)$"),
        "outputs the SMU drives from a constant in this composition: the lifecycle demote "
        "states are tied low and the LSIO interface select follows a fixed SPI enable. No "
        "stimulus can move them; -cm_noconst does not drop them because the constant is "
        "assigned inside the SMU rather than at the port.",
    ),
    (
        "SEP-OWNED",
        re.compile(
            r"^(sep_io_spi_req_o|sep_cpu_trace_o|sep_lockstep_ctrl_i|sep_lockstep_status_o|"
            r"sep_global_base_o|sep_region_size_o|sep_ext_interrupts_i|"
            r"entropy_rosc_sample_clk_i|lc_sigint_err_o)(\.|\[|$)"
        ),
        "SEP passthroughs with no wrapper-level observable on this bench: the SEP SPI host "
        "and CPU trace need SEP firmware, the lockstep pair is inert without "
        "RV_LOCKSTEP_ENABLE, the SEP aperture CSRs sit behind the reset aperture, the SEP "
        "external interrupts and entropy sample clock terminate inside the SEP, and the "
        "lifecycle signal-integrity error needs a fault injected inside it. The SEP bench "
        "grades each of them.",
    ),
]

# Fields excluded on a bit range rather than whole: (field, "[msb:lsb]", reason).
PARTIAL: list[tuple[str, str, str]] = [
    (
        "timer_count_o",
        "[63:20]",
        "the OCTS system timer counts reference clocks; bit k first rises after 2^k cycles, "
        "and no leaf runs the 2^20 cycles bit 20 needs. Bits [19:0] stay graded.",
    ),
]

TOGGLE_RE = re.compile(r'^// Toggle (\S+) "(.*)"$')


def wrapper_section(template: Path) -> tuple[str, list[tuple[str, str]]]:
    """Return the module checksum line and the (field, signature) pairs for MODULE."""
    lines = template.read_text().splitlines()
    marker = f"// MODULE: {MODULE}"
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == marker)
    except StopIteration:
        sys.exit(f"{template}: no `{marker}` section")
    checksum = next(
        (lines[i] for i in range(start, -1, -1) if lines[i].startswith("// CHECKSUM: ")),
        None,
    )
    if checksum is None:
        sys.exit(f"{template}: no CHECKSUM line above `{marker}`")
    fields: list[tuple[str, str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("// MODULE: "):
            break
        match = TOGGLE_RE.match(line)
        if match:
            fields.append((match.group(1), match.group(2)))
    return checksum[3:], fields


def render(checksum: str, fields: list[tuple[str, str]]) -> str:
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
        "//==================================================",
        f"// {MODULE} VCS toggle exclusions, applied with -elfile at report time.",
        "// Format Version: 2",
        "// ExclMode: default",
        "//",
        "// Generated by gen_smu_wrapper_toggle_exclusions.py from urg's",
        "// `-dump full_exclusions tgl` template of the merged database; regenerate",
        "// rather than edit. README.md beside this file states what each class",
        "// drops and why; the ANNOTATION before each class repeats the reason.",
        "//==================================================",
        "",
        checksum,
        f"MODULE: {MODULE}",
    ]
    by_class: dict[str, list[tuple[str, str]]] = {name: [] for name, _, _ in CLASSES}
    signatures = dict(fields)
    for field, signature in fields:
        for name, pattern, _ in CLASSES:
            if pattern.match(field):
                by_class[name].append((field, signature))
                break
    for name, _, reason in CLASSES:
        rows = by_class[name]
        if not rows:
            sys.exit(f"class {name} matched no field; the template or the rules moved")
        out += ["", f'ANNOTATION: "SMU-WRAPPER-TGL-{name}: {reason}"']
        out += [f'Toggle {field} "{signature}"' for field, signature in rows]
    for field, part, reason in PARTIAL:
        if field not in signatures:
            sys.exit(f"partial exclusion names `{field}`, which the template does not list")
        out += [
            "",
            f'ANNOTATION: "SMU-WRAPPER-TGL-PARTIAL: {reason}"',
            f'Toggle {field} {part} "{signatures[field]}"',
        ]
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("template", type=Path, help="urg fullexclude_module.tgl")
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args()
    checksum, fields = wrapper_section(args.template)
    text = render(checksum, fields)
    if args.check:
        if OUTPUT.read_text() != text:
            print(f"{OUTPUT} is stale; rerun without --check", file=sys.stderr)
            return 1
        print(f"{OUTPUT} is current")
        return 0
    OUTPUT.write_text(text)
    excluded = sum(1 for line in text.splitlines() if line.startswith("Toggle "))
    print(f"wrote {OUTPUT}: {excluded} exclusion lines from {len(fields)} fields")
    return 0


if __name__ == "__main__":
    sys.exit(main())
