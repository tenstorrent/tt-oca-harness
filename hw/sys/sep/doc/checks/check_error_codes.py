# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[5]
rom = (root / "hw/sys/sep/bootrom/prod/doc/rom.adoc").read_text()

# gather all defined identifiers from ROM + validator sources
srcs = []
for pat in [
    "hw/sys/sep/bootrom/prod/include/*.h",
    "hw/sys/sep/bootrom/prod/src/*.c",
    "hw/sys/sep/bootrom/prod/tools/tt-oca-manifest/validators/oca/lib/*.h",
    "hw/sys/sep/bootrom/prod/tools/tt-oca-manifest/validators/oca/lib/*.c",
]:
    srcs += list(root.glob(pat))
defined = set()
for f in srcs:
    defined |= set(
        re.findall(
            r"\b(OCA_FAIL_[A-Z0-9_]+|SEP_MSG_[A-Z0-9_]+|MANIFEST_ERR_[A-Z0-9_]+|OCA_[A-Z0-9_]+)\b",
            f.read_text(errors="replace"),
        )
    )
print(f"{len(defined)} identifiers defined across {len(srcs)} source files")

cited = {}
for m in re.finditer(r"`(OCA_FAIL_[A-Z0-9_]+|SEP_MSG_[A-Z0-9_]+|MANIFEST_ERR_[A-Z0-9_]+)`", rom):
    cited.setdefault(m.group(1), []).append(rom[: m.start()].count("\n") + 1)
print(f"{len(cited)} distinct error/status codes cited in rom.adoc\n")
bad = {k: v for k, v in cited.items() if k not in defined}
if not bad:
    print("ALL cited codes exist in the sources")
for k in sorted(bad):
    print(f"  MISSING: {k}   (rom.adoc lines {bad[k]})")
