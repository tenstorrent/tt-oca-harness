# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The committed Python headers and IP-XACT exports describe the same registers.

Both are generated from one RDL, through two exporters. A generic register walk
reads its access classification from the Python header, so every register the
IP-XACT export lists must have a header instance at the same address with the same
width and fields, every header instance must have an IP-XACT register, and every
field must carry the access, volatile, write and read side effects and reset that
PeakRDL's IP-XACT exporter derives from the same model.
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from pathlib import Path

from peakrdl_ipxact import typemaps
from systemrdl import rdltypes

from tools.regs.tests.pyhdr_support import ipxact_registers, load

ROOT = Path(__file__).resolve().parents[3]
BLOCKS = {
    "smc": ("hw/sys/smc/regs/gen/py/smc_reg.py", "hw/sys/smc/regs/gen/ipxact/smc.xml"),
    "sep": ("hw/sys/sep/regs/gen/py/sep_reg.py", "hw/sys/sep/regs/gen/ipxact/sep.xml"),
}


def header_field(record: tuple) -> dict:
    _name, lsb, msb, sw, _hw, onwrite, onread, _singlepulse, volatile, reset = record
    return {
        "lsb": lsb,
        "msb": msb,
        "access": typemaps.access_from_sw(rdltypes.AccessType[sw]),
        "volatile": volatile,
        "onwrite": typemaps.mwv_from_onwrite(rdltypes.OnWriteType[onwrite]) if onwrite else None,
        "onread": typemaps.readaction_from_onread(rdltypes.OnReadType[onread]) if onread else None,
        "reset": reset,
    }


def header_types(module) -> dict[str, tuple[int, dict]]:
    """Map every register type to (width, {field: props})."""
    types = {}
    for symbol, records in vars(module).items():
        if symbol.endswith("_REG_FIELDS"):
            reg_type = symbol[: -len("_REG_FIELDS")]
            width = getattr(module, f"{reg_type}_REG_WIDTH")
            types[reg_type] = (width, {rec[0]: header_field(rec) for rec in records})
    return types


def header_registers(module) -> dict[int, list[tuple[str, int, dict]]]:
    """Map every instance address to (instance, width, {field: props}) of its type."""
    types = header_types(module)
    by_addr: dict[int, list] = defaultdict(list)
    for symbol, addr in vars(module).items():
        if symbol.endswith("_REG_ADDR"):
            inst = symbol[: -len("_REG_ADDR")]
            width, fields = types[getattr(module, f"{inst}_REG_TYPE")]
            by_addr[addr].append((inst, width, fields))
    return by_addr


class PyHeaderIpxactContractTest(unittest.TestCase):
    def check(self, block: str) -> None:
        py, xml = (ROOT / rel for rel in BLOCKS[block])
        for path in (py, xml):
            self.assertTrue(
                path.exists(), f"{path.relative_to(ROOT)} is absent; run make regen-regs"
            )
        header = header_registers(load(py))
        ipxact = list(ipxact_registers(xml))
        self.assertGreater(len(ipxact), 0, f"{xml.relative_to(ROOT)} lists no registers")

        mismatches: list[str] = []
        for path, addr, width, fields in ipxact:
            matches = [
                (inst, hfields)
                for inst, hwidth, hfields in header.get(addr, [])
                if hwidth == width and hfields.keys() == fields.keys()
            ]
            if not matches:
                mismatches.append(f"{path} @0x{addr:X}: no header instance with these fields")
                continue
            for inst, hfields in matches:
                for name, want in fields.items():
                    if hfields[name] != want:
                        mismatches.append(
                            f"{path}.{name} ({inst}): header {hfields[name]} != ipxact {want}"
                        )
        for addr in sorted(header.keys() - {addr for _, addr, _, _ in ipxact}):
            insts = ", ".join(inst for inst, _, _ in header[addr])
            mismatches.append(f"{insts} @0x{addr:X}: no IP-XACT register at this address")

        self.assertEqual(
            mismatches[:20],
            [],
            f"{len(mismatches)} mismatch(es) over {len(ipxact)} IP-XACT and "
            f"{sum(map(len, header.values()))} header register(s)",
        )

    def test_smc(self):
        self.check("smc")

    def test_sep(self):
        self.check("sep")


if __name__ == "__main__":
    unittest.main()
