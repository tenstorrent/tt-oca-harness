# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Load generated Python register headers and walk IP-XACT exports for the tests."""

from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"i": "http://www.accellera.org/XMLSchema/IPXACT/1685-2014"}


def load(path: Path):
    """Import a generated Python header from its file path."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def num(text: str) -> int:
    text = text.strip()
    return int(text[2:], 16) if text.startswith("'h") else int(text, 0)


def ipxact_field(el: ET.Element) -> dict:
    def text(tag: str) -> str | None:
        found = el.find(f"i:{tag}", NS)
        return None if found is None else found.text

    reset = el.find("i:resets/i:reset/i:value", NS)
    lsb = int(text("bitOffset"))
    return {
        "lsb": lsb,
        "msb": lsb + int(text("bitWidth")) - 1,
        "access": text("access"),
        "volatile": text("volatile") == "true",
        "onwrite": text("modifiedWriteValue"),
        "onread": text("readAction"),
        "reset": None if reset is None else num(reset.text),
    }


def ipxact_registers(xml: Path):
    """Yield (path, address, width, {field: props}) for every register element."""

    def walk(node: ET.Element, path: str, base: int):
        for sub in node.findall("i:registerFile", NS):
            name = sub.find("i:name", NS).text
            origin = base + num(sub.find("i:addressOffset", NS).text)
            dim = sub.find("i:dim", NS)
            if dim is None:
                yield from walk(sub, f"{path}.{name}", origin)
                continue
            stride = num(sub.find("i:range", NS).text)
            for i in range(int(dim.text)):
                yield from walk(sub, f"{path}.{name}[{i}]", origin + i * stride)
        for reg in node.findall("i:register", NS):
            name = reg.find("i:name", NS).text
            addr = base + num(reg.find("i:addressOffset", NS).text)
            width = int(reg.find("i:size", NS).text)
            fields = {
                f.find("i:name", NS).text: ipxact_field(f) for f in reg.findall("i:field", NS)
            }
            dim = reg.find("i:dim", NS)
            for i in range(1 if dim is None else int(dim.text)):
                yield f"{path}.{name}[{i}]", addr + i * width // 8, width, fields

    for block in ET.parse(xml).getroot().iter(f"{{{NS['i']}}}addressBlock"):
        name = block.find("i:name", NS).text
        yield from walk(block, name, num(block.find("i:baseAddress", NS).text))
