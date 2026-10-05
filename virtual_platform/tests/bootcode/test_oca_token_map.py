# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import re
from pathlib import Path

import dv_env
import pytest
from sepvp import paths

pytestmark = pytest.mark.hostonly

_MAP = Path(__file__).parent / "reference" / "oca_rom_tokens.md"
_ROM_SRC = paths.BOOTCODE_DIR / "src"
_TICKED = re.compile(r"`([^`]+)`")


def _tables() -> list[list[list[str]]]:
    """Each markdown table in the map, as rows of cells, header and separator dropped."""
    tables, current = [], []
    for line in _MAP.read_text().splitlines():
        if line.startswith("|"):
            current.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif current:
            tables.append(current[2:])
            current = []
    if current:
        tables.append(current[2:])
    return tables


def _column(table_index: int, column: int) -> list[str]:
    return [row[column] for row in _tables()[table_index]]


def _rom_boot_err(name: str) -> int:
    # oca_boot.h continues some defines onto a second line, which the DV header parser skips.
    header = (paths.BOOTCODE_DIR / "include" / "oca_boot.h").read_text().replace("\\\n", " ")
    match = re.search(rf"^#define\s+{name}\s+(0[xX][0-9a-fA-F]+)u?\b", header, re.M)
    assert match, f"oca_boot.h does not define {name}"
    return int(match.group(1), 16)


def _assembly_strings() -> str:
    return "\n".join(path.read_text() for path in sorted(_ROM_SRC.glob("*.S")))


def test_the_map_says_it_is_not_an_expected_value_source():
    lines = _MAP.read_text().splitlines()
    first = next(line for line in lines if line.strip() and not line.startswith("<!--"))
    assert "not a source of expected values" in first


def test_the_map_has_three_tables():
    assert len(_tables()) == 3


@pytest.mark.parametrize("cell", _column(0, 0))
def test_every_oca_token_is_printed_by_the_rom_or_bl1(cell):
    console = dv_env.load("sep_oca_console")
    tokens = _TICKED.findall(cell)
    assert tokens, f"token cell {cell!r} names nothing"
    assembly = _assembly_strings()
    unknown = [t for t in tokens if not console._printed(t) and t not in assembly]
    assert not unknown, f"the OCA ROM and BL1 never print {unknown}"


@pytest.mark.parametrize("code, name", list(zip(_column(1, 0), _column(1, 1))))
def test_every_oca_result_name_has_the_listed_code(code, name):
    mm = dv_env.load("sep_manifest_mutate")
    (listed,) = [int(c, 16) for c in _TICKED.findall(code)]
    (name,) = _TICKED.findall(name)
    value = _rom_boot_err(name) if name.startswith("OCA_BOOT_ERR_") else mm.boot_err(name)
    assert value == listed, f"{name} is 0x{value:08x}, the map says 0x{listed:08x}"
