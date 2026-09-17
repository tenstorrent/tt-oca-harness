# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[5]
f = root / "hw/sys/sep/bootrom/prod/doc/rom.adoc"
lines = f.read_text().split("\n")
i = 0
ntab = 0
problems = []
while i < len(lines):
    if lines[i].strip() == "|===":
        # look back for cols= spec and title/anchor
        cols = None
        title = None
        anchor = None
        for j in range(i - 1, max(-1, i - 8), -1):
            m = re.search(r'cols="([^"]+)"', lines[j])
            if m and cols is None:
                cols = m.group(1)
            m = re.match(r"^\.(\S.*)$", lines[j])
            if m and title is None:
                title = m.group(1)
            m = re.match(r"^\[\[([^\]]+)\]\]", lines[j])
            if m and anchor is None:
                anchor = m.group(1)
            if lines[j].strip() == "" and cols:
                break
        # gather body
        k = i + 1
        body = []
        while k < len(lines) and lines[k].strip() != "|===":
            body.append(lines[k])
            k += 1
        ntab += 1
        ncols = len(cols.split(",")) if cols else None
        pipes = sum(ln.count("|") for ln in body)
        label = anchor or title or f"table@line{i + 1}"
        if ncols:
            if pipes % ncols != 0:
                problems.append((i + 1, label, ncols, pipes, pipes / ncols))
        else:
            problems.append((i + 1, label, None, pipes, None))
        i = k + 1
        continue
    i += 1
print(f"{ntab} tables scanned")
if not problems:
    print("ALL TABLES: cell count divisible by column count")
for line, label, ncols, pipes, rows in problems:
    if ncols is None:
        print(f"  line {line}: {label}: NO cols= spec ({pipes} cells)")
    else:
        print(f"  line {line}: {label}: {pipes} cells / {ncols} cols = {rows:.2f} rows  <-- RAGGED")
