# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[5]
c = (root / "hw/sys/sep/bootrom/prod/tools/tt-oca-manifest/src/oca/constants.py").read_text()
off = {}
for m in re.finditer(r"^OFF_([A-Z0-9_]+)\s*=\s*(\d+)", c, re.M):
    off[m.group(1).lower()] = int(m.group(2))
# alias doc names -> constants names
alias = {
    "encryption_key_derivation_function": "encryption_kdf",
    "boot_manifest_magic": "boot_manifest_magic",
}
rom = (root / "hw/sys/sep/bootrom/prod/doc/rom.adoc").read_text()
lines = rom.split("\n")
print("Inline 'offset NNNN' citations in rom.adoc:\n")
hits = 0
for i, ln in enumerate(lines, 1):
    # Find 'offset NNNN' and look for a field name nearby (same or previous line).
    for m in re.finditer(r"offsets?\s+(\d{2,4})", ln):
        val = int(m.group(1))
        ctx = (lines[i - 2] if i >= 2 else "") + " " + ln
        names = re.findall(r"`([a-z_]{4,})`", ctx)
        cand = [n for n in names if n in off or alias.get(n) in off]
        hits += 1
        verdict = "?"
        detail = ""
        for n in cand:
            key = alias.get(n, n)
            if key in off:
                exp = off[key]
                if exp == val:
                    verdict, detail = "OK", f"{n}=={val}"
                    break
                else:
                    verdict, detail = "MISMATCH", f"{n}: doc {val}, actual {exp}"
        print(f"  line {i:>5}  offset {val:<5} {verdict:<9} {detail}")
        if verdict == "?":
            print(f"           ctx: {ln.strip()[:100]}")
print(f"\n{hits} citations")
