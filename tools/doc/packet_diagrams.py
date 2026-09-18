#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Render 32-bit packet layouts as standalone, accessible SVGs."""

import argparse
import json
import re
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

WIDTH = 544
MARGIN = 16
BIT_WIDTH = 16
BOX_HEIGHT = 66


def validate(packet):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", packet["id"]):
        raise ValueError(f"Invalid packet id: {packet['id']}")
    if not packet["words"] or not any("fields" in word for word in packet["words"]):
        raise ValueError(f"{packet['id']}: packet has no fields")
    for word in packet["words"]:
        if word.get("ellipsis"):
            continue
        expected = 31
        for field in word["fields"]:
            high, low = field["bits"]
            if not 0 <= low <= high <= 31 or high != expected:
                raise ValueError(f"{packet['id']}: gaps or overlaps in word {word['word']}")
            if not field["name"]:
                raise ValueError(f"{packet['id']}: field has no name")
            expected = low - 1
        if expected != -1:
            raise ValueError(f"{packet['id']}: incomplete word {word['word']}")


def description(packet):
    words = []
    for word in packet["words"]:
        if word.get("ellipsis"):
            words.append("Intermediate words omitted.")
            continue
        fields = []
        for field in word["fields"]:
            high, low = field["bits"]
            bits = f"bits {high} to {low}" if high != low else f"bit {high}"
            optional = " (optional)" if field.get("optional") else ""
            fields.append(f"{bits}: {field['name']}{optional}")
        words.append(f"Word {word['word']}: {'; '.join(fields)}.")
    return " ".join(words)


def label_lines(name, width):
    limit = max(1, int((width - 14) / 10.8))
    pieces = re.findall(r"[^_ ]+_?| +", name)
    lines = []
    line = ""
    for piece in pieces:
        if len(line + piece) > limit and line:
            lines.extend(textwrap.wrap(line, limit, break_on_hyphens=False))
            line = ""
        line += piece
    if line:
        lines.extend(textwrap.wrap(line, limit, break_on_hyphens=False))
    if len(lines) > 3:
        raise ValueError(f"Field label does not fit: {name}")
    return lines


def render(packet):
    validate(packet)
    elements = []

    def text(x, y, value, size=18, anchor="middle", transform=None, color="#173b2c"):
        extra = f' transform="{transform}"' if transform else ""
        elements.append(
            f'<text x="{x:g}" y="{y:g}" font-family="monospace" '
            f'font-size="{size}" text-anchor="{anchor}" fill="{color}"{extra}>'
            f"{escape(value)}</text>"
        )

    multiple = len(packet["words"]) > 1
    y = 8
    for word in packet["words"]:
        if word.get("ellipsis"):
            text(WIDTH / 2, y + 14, "…", 22)
            y += 32
            continue
        if multiple:
            text(MARGIN, y + 16, f"Word {word['word']}", 16, "start")
            y += 26
        top = y + 24
        narrow_reserved = []
        for field in word["fields"]:
            high, low = field["bits"]
            x = MARGIN + (31 - high) * BIT_WIDTH
            width = (high - low + 1) * BIT_WIDTH
            reserved = field["name"] == "RESERVED"
            fill = "#f0f1f2" if reserved else "#e5f0ea"
            elements.append(
                f'<rect x="{x}" y="{top}" width="{width}" height="{BOX_HEIGHT}" '
                f'fill="{fill}" stroke="#49685a" stroke-width="1"/>'
            )
            if high == low:
                text(x + width / 2, top - 7, str(high), 12)
            else:
                text(x + 4, top - 7, str(high), 12, "start")
                text(x + width - 4, top - 7, str(low), 12, "end")
            cx, cy = x + width / 2, top + BOX_HEIGHT / 2
            if width < 64:
                if reserved:
                    text(cx, cy + 5, "R", 14)
                    bit_range = str(high) if high == low else f"{high}:{low}"
                    narrow_reserved.append(f"R = {field['name']} [{bit_range}]")
                else:
                    text(cx, cy + 4, field["name"], 12, transform=f"rotate(-90 {cx:g} {cy:g})")
            else:
                lines = label_lines(field["name"], width)
                for i, line in enumerate(lines):
                    text(cx, cy + 6 + (i - (len(lines) - 1) / 2) * 21, line)
        y = top + BOX_HEIGHT + 12
        if narrow_reserved:
            text(MARGIN, y + 13, "; ".join(narrow_reserved), 14, "start")
            y += 27
        if any(field.get("optional") for field in word["fields"]):
            names = ", ".join(f["name"] for f in word["fields"] if f.get("optional"))
            text(MARGIN, y + 13, f"Optional: {names}", 14, "start")
            y += 27
        y += 8
    height = y + 4
    return "\n".join(
        [
            "<!-- SPDX-License-Identifier: CC-BY-4.0 -->",
            "<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->",
            "<!-- Generated by tools/doc/packet_diagrams.py; edit packets.json. -->",
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
            f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(packet["title"])}</title>',
            f'<desc id="desc">{escape(description(packet))}</desc>',
            f'<rect width="{WIDTH}" height="{height}" fill="white"/>',
            *elements,
            "</svg>\n",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check", action="store_true", help="Check committed SVGs without writing")
    args = parser.parse_args()
    output = args.output_dir or args.source.parent / "assets"
    packets = json.loads(args.source.read_text())["packets"]
    ids = [p["id"] for p in packets]
    if len(ids) != len(set(ids)):
        parser.error("Duplicate packet ids")
    rendered = [(output / f"{p['id']}.svg", render(p)) for p in packets]
    if args.check:
        stale = [
            str(path) for path, svg in rendered if not path.exists() or path.read_text() != svg
        ]
        if stale:
            parser.error("Stale packet diagrams: " + ", ".join(stale))
    else:
        output.mkdir(parents=True, exist_ok=True)
        for path, svg in rendered:
            path.write_text(svg)


if __name__ == "__main__":
    main()
