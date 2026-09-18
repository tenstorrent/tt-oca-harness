# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[5]
start = root / "doc/trm/src/index.adoc"

seen = set()
files = []


def walk(p):
    p = p.resolve()
    if p in seen or not p.exists():
        return
    seen.add(p)
    files.append(p)
    t = p.read_text(errors="replace")
    for m in re.finditer(r"^include::([^\[\]]+)\[", t, re.M):
        inc = m.group(1).strip()
        if "$" in inc or "{" in inc:  # antora resource id / attribute
            # try to resolve {ocah_root} style
            inc2 = re.sub(r"\{[^}]+\}", "", inc).lstrip("/")
            cand = root / inc2
            if cand.exists():
                walk(cand)
            continue
        walk(p.parent / inc)


walk(start)
print(f"{len(files)} files in TRM include tree")

anchors = set()
for f in files:
    t = f.read_text(errors="replace")
    anchors |= set(re.findall(r"\[\[([^\],]+?)(?:,[^\]]*)?\]\]", t))
    anchors |= set(re.findall(r"^\[#([^\],]+)", t, re.M))
print(f"{len(anchors)} anchors")


def strip_delimited(text):
    """Blank the inside of listing/literal blocks, keeping line numbering.

    `<<...>>` inside a diagram or code block is not a cross-reference: PlantUML
    uses it for stereotype colours and C uses `>>` to shift. Scanning raw text
    reports both as unresolved xrefs.
    """
    out, fence = [], None
    for line in text.split("\n"):
        bare = line.rstrip()
        if fence is None and bare in ("----", "...."):
            fence = bare
            out.append(line)
            continue
        if fence is not None:
            out.append(line if bare == fence else "")
            if bare == fence:
                fence = None
            continue
        out.append(line)
    return "\n".join(out)


bad = {}
for f in files:
    t = strip_delimited(f.read_text(errors="replace"))
    for m in re.finditer(r"<<([^<>,]+?)(?:,([^<>]*))?>>", t):
        tgt = m.group(1).strip()
        if tgt.startswith("http") or ".adoc" in tgt:
            continue
        if tgt not in anchors:
            bad.setdefault(str(f.relative_to(root)), []).append(
                (t[: m.start()].count("\n") + 1, tgt)
            )
if not bad:
    print("ALL XREFS RESOLVE across TRM book")
for fn, items in sorted(bad.items()):
    print(f"\n{fn}:")
    for line, tgt in items:
        print(f"  line {line}: <<{tgt}>>")
