#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate the DFD SystemRDL from the vendored tt_hw_debug MMR spec.

Emits one RDL per MMR block from rtl/mmr/spec/<blk>_mmrs.yml, plus the smc_cla
composite that instantiates the blocks smc_dfd_wrap builds. --check exits 1 on
any drift; --write regenerates in place.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

SPEC_DIR = ROOT / "vendor/tenstorrent/tt-hw-debug/upstream/rtl/mmr/spec"
MMR_DIR = ROOT / "vendor/tenstorrent/tt-hw-debug/upstream/rtl/mmr"
BLOCK_RDL_DIR = ROOT / "vendor/tenstorrent/tt-hw-debug/overlay/regs/dfd/regs/include"
COMPOSITE_RDL = ROOT / "hw/ip/dfd/regs/smc_cla.rdl"
OVERRIDES = Path(__file__).with_name("dfd_mmr_overrides.yml")

# svh_prefix is the localparam namespace; struct_prefix names the packed structs.
# regwidth defaults are the spec's own documented defaults for the size key.
BLOCKS = {
    "dst_sink": dict(
        size_key="DST_SINK_MMR_SIZE",
        size_default=32,
        svh_prefix="DST_SINK",
        struct_prefix="DstSink",
    ),
    "funnel": dict(
        size_key="FUNNEL_MMR_SIZE", size_default=32, svh_prefix="FUNNEL", struct_prefix="Funnel"
    ),
    "cla": dict(size_key="CL_MMR_SIZE", size_default=64, svh_prefix="CLA", struct_prefix="Cla"),
    "dst": dict(size_key="DST_MMR_SIZE", size_default=32, svh_prefix="DST", struct_prefix="Dst"),
    "ntr": dict(size_key="NTR_MMR_SIZE", size_default=32, svh_prefix="NTR", struct_prefix="Ntr"),
    "ntr_sink": dict(
        size_key="NTR_SINK_MMR_SIZE",
        size_default=32,
        svh_prefix="NTR_SINK",
        struct_prefix="NtrSink",
    ),
}

# Blocks the composite maps, in mmrs.sv block order. NUM_NTRACE_INST is a
# localparam 0 in dfd_top_cla_dst_apb, so ntr/ntr_sink are built as RDL but never
# instantiated here.
COMPOSITE_BLOCKS = ["dst_sink", "funnel", "cla", "dst"]

SPDX = (
    "// SPDX-License-Identifier: Apache-2.0\n// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc."
)


WARNINGS: list[str] = []


class Drift(Exception):
    """A stale override entry or a spec/RTL disagreement."""


def norm(name: str) -> str:
    """Join key across the spec yaml, the svh localparams and the RTL identifiers."""
    return name.upper().replace("_", "")


# ---------------------------------------------------------------------------
# Vendor inputs
# ---------------------------------------------------------------------------


def load_spec(blk: str) -> dict:
    # BaseLoader keeps every scalar a string. safe_load would read an unquoted
    # FIELDS_RANGE such as 63:0 as YAML 1.1 sexagesimal (3780); the drops seen so
    # far quote the at-risk ranges, but nothing guarantees the next one does.
    with open(SPEC_DIR / f"{blk}_mmrs.yml") as f:
        return yaml.load(f, Loader=yaml.BaseLoader)


def load_svh(blk: str) -> dict:
    """Register offsets and field bounds from <blk>_mmr_pkg.svh.

    An oracle independent of the spec yaml: it comes from the same vendor drop but
    is emitted from the RTL side, so it catches registers the yaml omits.
    """
    prefix = BLOCKS[blk]["svh_prefix"]
    text = (MMR_DIR / f"{blk}_mmr_pkg.svh").read_text()

    regs = {}
    for m in re.finditer(
        rf"^localparam\s+{prefix}_(\w+)_REG_OFFSET\s*=\s*\d+'h([0-9A-Fa-f]+);",
        text,
        re.M,
    ):
        regs[m.group(1)] = {"offset": int(m.group(2), 16), "fields": {}}

    # <PREFIX>_<REG>_<FIELD>_LOW/_HIGH: both halves are underscore-free once
    # normalised, so split on the longest matching known register name.
    by_len = sorted(regs, key=len, reverse=True)
    for m in re.finditer(rf"^localparam\s+{prefix}_(\w+)_(LOW|HIGH)\s*=\s*(\d+);", text, re.M):
        tail, which, val = m.group(1), m.group(2), int(m.group(3))
        reg = next((r for r in by_len if tail.startswith(r + "_")), None)
        if reg is None:
            continue
        field = tail[len(reg) + 1 :]
        regs[reg]["fields"].setdefault(field, {})[which] = val

    for reg in regs.values():
        for name, b in list(reg["fields"].items()):
            if "LOW" not in b or "HIGH" not in b:
                del reg["fields"][name]
    return regs


def load_identifiers(blk: str) -> tuple[dict, dict]:
    """Canonical register and field spellings, keyed by norm().

    <blk>_mmr.sv spells both as MMR_<Reg>_F_<Field>. Two registers across the six
    blocks are emitted all-caps there; for those the packed struct in the svh
    carries the mixed-case spelling, so it is the fallback.
    """
    text = (MMR_DIR / f"{blk}_mmr.sv").read_text()
    regs: dict[str, str] = {}
    fields: dict[tuple[str, str], str] = {}
    for m in re.finditer(r"\bMMR_([A-Za-z0-9]+)_F_([A-Za-z0-9]+)\b", text):
        reg, field = m.group(1), m.group(2)
        regs.setdefault(norm(reg), reg)
        fields.setdefault((norm(reg), norm(field)), field)

    structs = load_struct_spellings(blk)
    for key, name in list(regs.items()):
        if name.isupper() and key in structs:
            regs[key] = structs[key]["reg"]
    for (rk, fk), name in list(fields.items()):
        if name.isupper() and rk in structs and fk in structs[rk]["fields"]:
            fields[(rk, fk)] = structs[rk]["fields"][fk]
    return regs, fields


def load_struct_spellings(blk: str) -> dict:
    """Mixed-case spellings from the packed structs in <blk>_mmr_pkg.svh."""
    sp = BLOCKS[blk]["struct_prefix"]
    text = (MMR_DIR / f"{blk}_mmr_pkg.svh").read_text()
    out = {}
    for m in re.finditer(rf"typedef struct packed \{{(.*?)\}}\s*{sp}(\w+)Mmr_s;", text, re.S):
        body, reg = m.group(1), m.group(2)
        members = {
            norm(fm.group(1)): fm.group(1)
            for fm in re.finditer(r"logic\s*\[[^\]]*\]\s*(\w+)\s*;", body)
        }
        out[norm(reg)] = {"reg": reg, "fields": members}
    return out


def load_wrap_params(rel: str, module: str) -> dict:
    """NUM_*_INST overrides from the smc_dfd_wrap instantiation of the DFD top."""
    text = (ROOT / rel).read_text()
    m = re.search(rf"\b{module}\s*#\((.*?)\)\s*\w+\s*\(", text, re.S)
    if not m:
        raise Drift(f"{rel}: no {module} instantiation found")
    return {
        p.group(1): int(p.group(2))
        for p in re.finditer(r"\.\s*(NUM_\w+)\s*\(\s*(\d+)\s*\)", m.group(1))
    }


# ---------------------------------------------------------------------------
# Field decoding
# ---------------------------------------------------------------------------


def eff(common: dict, field: dict, key: str) -> bool:
    """A spec attribute is per-field, falling back to the register's common_data."""
    val = field.get(key, common.get(key, ""))
    return bool(str(val).strip())


def sw_access(common: dict, field: dict) -> str | None:
    r, w = eff(common, field, "SW_READ"), eff(common, field, "SW_WRITE")
    if r and w:
        return "rw"
    return "r" if r else ("w" if w else None)


def hw_access(common: dict, field: dict, sw: str) -> str:
    """hw= as the vendor RTL drives it, given the field's final sw=.

    A hardware-written field that software cannot write is a status field (hw=w);
    one software can also write is shared state (hw=rw).
    """
    r, w = eff(common, field, "HW_READ"), eff(common, field, "HW_WRITE")
    if w and sw == "r":
        return "w"
    if r and w:
        return "rw"
    if r:
        return "r"
    return "w" if w else "r"


def reset_value(raw) -> int:
    """RESET_VALUE is bare hex: '36' is 0x36, confirmed against 7'h36 in the RTL.

    PARAM means the reset comes from a module parameter; the RTL zeroes those in
    this build, and the committed RDL has always modelled them as 0.
    """
    s = str(raw).strip()
    if not s or s == "PARAM":
        return 0
    return int(s, 16)


def parse_range(raw) -> tuple[int, int]:
    hi, _, lo = str(raw).strip().partition(":")
    return int(hi), int(lo)


# ---------------------------------------------------------------------------
# Model building + override assertions
# ---------------------------------------------------------------------------


def build_block(blk: str, ov: dict) -> list[dict]:
    cfg = BLOCKS[blk]
    spec = load_spec(blk)
    svh = load_svh(blk)
    reg_names, field_names = load_identifiers(blk)

    excluded = list(ov.get("exclude", {}).get(blk, []) or [])
    extra = ov.get("extra_regs", {}).get(blk, {}) or {}
    owned = ov.get("hw_owned", {}).get(blk, {}) or {}

    # -- exclude: still specified, still not built -------------------------
    for name in excluded:
        if name not in spec:
            raise Drift(
                f"{blk}: exclude '{name}' is no longer in the spec yaml; "
                f"drop it from dfd_mmr_overrides.yml"
            )
        if norm(name) in svh:
            raise Drift(
                f"{blk}: exclude '{name}' is now built by "
                f"{blk}_mmr_pkg.svh; it must be mapped, not excluded"
            )

    # -- hw_owned: still present, still reported writable ------------------
    for reg, fields in owned.items():
        if reg not in spec:
            raise Drift(f"{blk}: hw_owned register '{reg}' is not in the spec yaml")
        for field in fields:
            if field not in spec[reg]:
                raise Drift(f"{blk}: hw_owned field '{reg}.{field}' is not in the spec yaml")
            if sw_access(spec[reg]["common_data"], spec[reg][field]) != "rw":
                raise Drift(
                    f"{blk}: hw_owned pin '{reg}.{field}' is redundant -- "
                    f"the spec no longer reports it sw-writable"
                )

    regs = []
    for name, body in spec.items():
        if name in excluded:
            continue
        common = body["common_data"]
        key = norm(name)
        if key not in svh:
            raise Drift(
                f"{blk}: spec register '{name}' is absent from "
                f"{blk}_mmr_pkg.svh; exclude it or bump the vendor drop"
            )

        offset = int(str(common["ADDRESS"]), 16)
        if offset != svh[key]["offset"]:
            raise Drift(f"{blk}: '{name}' at spec 0x{offset:X} but svh 0x{svh[key]['offset']:X}")

        fields = []
        for fname, fbody in body.items():
            if fname == "common_data":
                continue
            hi, lo = parse_range(fbody["FIELDS_RANGE"])
            fkey = norm(fname)
            bounds = svh[key]["fields"].get(fkey)
            if bounds and (bounds["HIGH"], bounds["LOW"]) != (hi, lo):
                raise Drift(
                    f"{blk}: '{name}.{fname}' spec [{hi}:{lo}] but svh "
                    f"[{bounds['HIGH']}:{bounds['LOW']}]"
                )
            # FIELDS_WIDTH is redundant with FIELDS_RANGE and not always in step
            # with it. The svh breaks the tie; only an uncorroborated range is
            # fatal, since that is the one that could mis-map a register.
            width = int(fbody["FIELDS_WIDTH"])
            if width != hi - lo + 1:
                if bounds is None:
                    raise Drift(
                        f"{blk}: '{name}.{fname}' width {width} contradicts "
                        f"range [{hi}:{lo}] and the svh does not cover it"
                    )
                WARNINGS.append(
                    f"{blk}: '{name}.{fname}' spec width {width} contradicts range "
                    f"[{hi}:{lo}]; using the range, which the svh corroborates"
                )

            sw = sw_access(common, fbody)
            if sw is None:
                continue
            if fname in owned.get(name, []):
                sw = "r"
            fields.append(
                {
                    "name": field_names.get((key, fkey), fname),
                    "hi": hi,
                    "lo": lo,
                    "sw": sw,
                    "hw": hw_access(common, fbody, sw),
                    "reset": reset_value(fbody.get("RESET_VALUE", 0)),
                    "desc": str(fbody.get("DESCRIPTION", "") or "").strip(),
                }
            )

        regs.append(
            {
                "name": reg_names.get(key, name),
                "offset": offset,
                "regwidth": int(common.get(cfg["size_key"], cfg["size_default"])),
                "desc": str(common.get("DESCRIPTION", "") or "").strip(),
                "fields": sorted(fields, key=lambda f: f["lo"]),
            }
        )

    # -- extra_regs: still unspecified, still built as described ------------
    for name, body in extra.items():
        if name in {norm(k): k for k in spec}.values() or norm(name) in {norm(k) for k in spec}:
            raise Drift(
                f"{blk}: extra_regs '{name}' is now in the spec yaml; "
                f"drop it from dfd_mmr_overrides.yml"
            )
        key = norm(name)
        if key not in svh:
            raise Drift(f"{blk}: extra_regs '{name}' is not built by {blk}_mmr_pkg.svh")
        if body["offset"] != svh[key]["offset"]:
            raise Drift(
                f"{blk}: extra_regs '{name}' at 0x{body['offset']:X} but "
                f"svh 0x{svh[key]['offset']:X}"
            )
        fields = []
        for fname, fbody in body["fields"].items():
            hi, lo = parse_range(fbody["bits"])
            bounds = svh[key]["fields"].get(norm(fname))
            if bounds and (bounds["HIGH"], bounds["LOW"]) != (hi, lo):
                raise Drift(
                    f"{blk}: extra_regs '{name}.{fname}' [{hi}:{lo}] but "
                    f"svh [{bounds['HIGH']}:{bounds['LOW']}]"
                )
            fields.append(
                {
                    "name": field_names.get((key, norm(fname)), fname),
                    "hi": hi,
                    "lo": lo,
                    "sw": fbody["sw"],
                    "hw": fbody["hw"],
                    "reset": int(str(fbody["reset"]), 0),
                    "desc": "",
                }
            )
        regs.append(
            {
                "name": reg_names.get(key, name),
                "offset": body["offset"],
                "regwidth": body["regwidth"],
                "desc": str(body.get("desc", "") or "").strip(),
                "fields": sorted(fields, key=lambda f: f["lo"]),
            }
        )

    regs.sort(key=lambda r: r["offset"])
    return regs


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


def quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_block(blk: str, regs: list[dict]) -> str:
    out = [
        SPDX,
        "",
        f"// {blk} MMR block, generated by tools/regs/dfd_yaml_rdl.py from",
        f"// rtl/mmr/spec/{blk}_mmrs.yml. Do not edit; run `make ocah-regen-dfd-rdl`.",
        "//",
        "// Addresses are block-relative: the composite that instantiates this",
        "// block places it at the offset mmrs.sv decodes.",
        "",
        f"`ifndef DFD_{blk.upper()}_RDL",
        f"`define DFD_{blk.upper()}_RDL",
        "",
        f"addrmap dfd_{blk} {{",
    ]
    for reg in regs:
        out.append("    reg {")
        if reg["desc"]:
            out.append(f"        desc = {quote(reg['desc'])};")
        out.append(f"        regwidth = {reg['regwidth']};")
        out.append("")
        for f in reg["fields"]:
            out.append("        field {")
            out.append(f"            sw = {f['sw']};")
            out.append(f"            hw = {f['hw']};")
            if f["desc"]:
                out.append(f"            desc = {quote(f['desc'])};")
            bits = f"[{f['hi']}:{f['lo']}]"
            out.append(f"        }} {f['name']}{bits} = 0x{f['reset']:X};")
        out.append(f"    }} {reg['name']} @ 0x{reg['offset']:X};")
    out += ["};", "", "`endif", ""]
    return "\n".join(out)


def emit_composite(params: dict) -> str:
    """The composite aperture: an OCAH integration fact, not a vendor one."""
    return "\n".join(
        [
            SPDX,
            "",
            "// DFD MMR aperture as smc_dfd_wrap builds it. Generated by",
            "// tools/regs/dfd_yaml_rdl.py; do not edit.",
            "//",
            "// mmrs.sv assigns one 4 KiB block per present unit and decodes it from",
            "// paddr[22:12]. The block order below is that decode order, and the DST",
            "// base slides with NUM_CLA_INST exactly as DST_START_IDX does.",
            "//",
            "// The parameter defaults track the smc_dfd_wrap instantiation and are",
            "// asserted against it on every regen. NUM_NTRACE_INST is a localparam 0",
            "// in dfd_top_cla_dst_apb, so no ntrace block is mapped -- and it must not",
            "// be: this map is the model of what the RTL implements, and every register",
            "// in it reaches DV, the C headers and the docs as a register firmware may",
            "// use. A block the build does not instantiate answers nothing.",
            "",
            '`include "dfd_dst_sink.rdl"',
            '`include "dfd_funnel.rdl"',
            '`include "dfd_cla.rdl"',
            '`include "dfd_dst.rdl"',
            "",
            "addrmap smc_cla #(",
            f"    longint unsigned NUM_CLA_INST = {params['NUM_CLA_INST']},",
            f"    longint unsigned NUM_DST_INST = {params['NUM_DST_INST']}",
            ") {",
            "    dfd_dst_sink dst_sink @ 0x0;",
            "    dfd_funnel   funnel   @ 0x1000;",
            "    dfd_cla      cla[NUM_CLA_INST] @ 0x2000 += 0x1000;",
            "    dfd_dst      dst[NUM_DST_INST] @ 0x2000 + 0x1000 * NUM_CLA_INST += 0x1000;",
            "};",
            "",
        ]
    )


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", default=True, help="report drift and exit 1 (default)"
    )
    mode.add_argument("--write", action="store_true", help="regenerate the RDL in place")
    args = ap.parse_args()

    with open(OVERRIDES) as f:
        ov = yaml.safe_load(f)

    bm = ov["block_map"]
    wrap = load_wrap_params(bm["assert_from"], bm["assert_module"])
    params = {"NUM_CLA_INST": bm["num_cla_inst"], "NUM_DST_INST": bm["num_dst_inst"]}
    for key, want in params.items():
        got = wrap.get(key)
        if got is None:
            raise Drift(
                f"{bm['assert_from']}: {key} is no longer overridden on {bm['assert_module']}"
            )
        if got != want:
            raise Drift(
                f"block map stale: {bm['assert_from']} says {key}={got}, "
                f"dfd_mmr_overrides.yml says {want}"
            )

    outputs = {
        BLOCK_RDL_DIR / f"dfd_{blk}.rdl": emit_block(blk, build_block(blk, ov)) for blk in BLOCKS
    }
    outputs[COMPOSITE_RDL] = emit_composite(params)

    stale = []
    for path, text in outputs.items():
        current = path.read_text() if path.exists() else None
        if current == text:
            continue
        stale.append(path)
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    for w in WARNINGS:
        print(f"warning: {w}", file=sys.stderr)

    rel = [str(p.relative_to(ROOT)) for p in stale]
    if args.write:
        print(f"regenerated {len(rel)} file(s)" if rel else "already up to date")
        for r in rel:
            print(f"  {r}")
        return 0

    if rel:
        print("RDL is stale with respect to the vendor MMR spec:", file=sys.stderr)
        for r in rel:
            print(f"  {r}", file=sys.stderr)
        print("\nrun `make ocah-regen-dfd-rdl` to regenerate", file=sys.stderr)
        return 1
    print("RDL matches the vendor MMR spec")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Drift as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
