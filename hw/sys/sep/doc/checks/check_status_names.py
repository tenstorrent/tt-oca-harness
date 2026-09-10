# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[5]
rom = (root / "hw/sys/sep/bootrom/prod/doc/rom.adoc").read_text()
srcs = []
for pat in [
    "hw/sys/sep/bootrom/prod/include/*.h",
    "hw/sys/sep/bootrom/prod/src/*.c",
    "hw/sys/sep/bootrom/prod/tools/tt-oca-manifest/validators/oca/lib/*.h",
]:
    srcs += list(root.glob(pat))
blob = "\n".join(f.read_text(errors="replace") for f in srcs)
defined = set(re.findall(r"\b([A-Z][A-Z0-9_]{3,})\b", blob))

# bare ALL_CAPS tokens in backticks, excluding ones already prefixed
cited = {}
for m in re.finditer(r"`([A-Z][A-Z0-9_]{3,})`", rom):
    tok = m.group(1)
    if tok.startswith(("OCA_", "SEP_MSG_", "MANIFEST_ERR_")):
        continue
    cited.setdefault(tok, []).append(rom[: m.start()].count("\n") + 1)
missing = []
for tok, lines in sorted(cited.items()):
    if tok in defined:
        continue
    if "SEP_MSG_" + tok in defined:
        continue
    if "ROM_" + tok in defined:
        continue
    missing.append((tok, lines))
print(f"{len(cited)} bare ALL_CAPS tokens cited; {len(missing)} unresolved\n")
for tok, lines in missing:
    print(f"  {tok:<38} lines {lines[:6]}")
