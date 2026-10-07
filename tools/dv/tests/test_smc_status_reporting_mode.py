# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every SMC test whose controller firmware asks for status names its reporting mode.

On the dual-SMC bench the target's STATUS_RPT_DISABLE strap decides whether the
production ROM answers the GET_STATUS family or rejects it with
`OCCP_UNSUPPORTED_STATUS`. `smc_dual_base_test` draws that strap per seed unless
the entry passes one of the `STATUS_REPORTING_MODES` plusargs from
`smc_occp_dual_defs.py`, so a status-dependent test enrolled without one passes
or fails on the seed.

A controller image is status-dependent when its own sources, under
`fw/tests/<image>/`, name a GET_STATUS-family command, `OCCP_UNSUPPORTED_STATUS`,
or an OCCP library function that sends a GET_STATUS-family command. The command
set is read from `occp_encode_header_word()` in `occp_test_common.h`: the
commands whose header carries `OCCP_BASE_MSG_GET_STATUS`. A library function in
`fw/common/occp/*.c` sends one when it passes such a command as a call argument
or names another function that does. Nothing here lists tests or functions by
hand, so a new firmware test or helper is classified from its source.

A testlist entry's controller images are its `firmware` name and the stem of its
`+bfm_rom_hex=` argument. An entry with a status-dependent image carries exactly
one mode plusarg.

Run from the repository root:

    python3 -m unittest tools/dv/tests/test_smc_status_reporting_mode.py
"""

from __future__ import annotations

import ast
import re
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SMC_DV = REPO_ROOT / "hw" / "sys" / "smc" / "dv"
FW_TESTS = SMC_DV / "fw" / "tests"
OCCP_LIB = SMC_DV / "fw" / "common" / "occp"
OCCP_HEADER = OCCP_LIB / "occp_test_common.h"
TESTLIST = SMC_DV / "testlists" / "all.toml"
DUAL_DEFS = SMC_DV / "cocotb" / "tests" / "smc_occp_dual_defs.py"
DUAL_BASE = SMC_DV / "cocotb" / "tests" / "smc_dual_base_test.py"

GET_STATUS_MSG = "OCCP_BASE_MSG_GET_STATUS"
UNSUPPORTED_STATUS = "OCCP_UNSUPPORTED_STATUS"
BFM_ROM_HEX = re.compile(r"^\+bfm_rom_hex=(?P<stem>[^.]+)\.rom\.hex$")

IDENT = re.compile(r"\b[A-Za-z_]\w*\b")
C_NOISE = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
FUNC_HEAD = re.compile(r"^[A-Za-z_][\w \t\*]*?\b(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{", re.M)


def strip_c(text: str) -> str:
    """C source with comments and string/char literals blanked out."""
    return C_NOISE.sub(" ", text)


def function_bodies(text: str) -> dict[str, str]:
    """Top-level function name -> body text of one stripped C source."""
    bodies: dict[str, str] = {}
    for head in FUNC_HEAD.finditer(text):
        depth = 0
        for pos in range(head.end() - 1, len(text)):
            if text[pos] == "{":
                depth += 1
            elif text[pos] == "}":
                depth -= 1
                if depth == 0:
                    bodies[head.group("name")] = text[head.end() : pos]
                    break
    return bodies


def status_commands(header: str) -> set[str]:
    """Commands whose request header `occp_encode_header_word()` encodes as GET_STATUS."""
    body = function_bodies(strip_c(header))["occp_encode_header_word"]
    commands: set[str] = set()
    pending: list[str] = []
    for match in re.finditer(r"case\s+(\w+)\s*:|msg_id\s*=\s*(\w+)|\bbreak\b", body):
        label, msg = match.groups()
        if label:
            pending.append(label)
        elif msg:
            if msg == GET_STATUS_MSG:
                commands.update(pending)
        else:
            pending = []
    return commands


def status_senders(sources: list[str], commands: set[str]) -> set[str]:
    """Library functions that send, directly or through another, a GET_STATUS command."""
    bodies: dict[str, str] = {}
    for source in sources:
        bodies.update(function_bodies(strip_c(source)))
    passes = re.compile(r"[(,]\s*(" + "|".join(sorted(commands)) + r")\b")
    senders = {name for name, body in bodies.items() if passes.search(body)}
    while True:
        grown = {
            name
            for name, body in bodies.items()
            if name not in senders and (set(IDENT.findall(body)) - {name}) & senders
        }
        if not grown:
            return senders
        senders |= grown


def image_status_symbols(image_dir: Path, symbols: set[str]) -> set[str]:
    """The status symbols the sources of one firmware test name."""
    named: set[str] = set()
    for path in sorted(image_dir.iterdir()):
        if path.suffix in {".c", ".h"}:
            named |= set(IDENT.findall(strip_c(path.read_text()))) & symbols
    return named


def load_testlist(testlist: Path) -> dict[str, dict]:
    """Every test entry reachable from `testlist` through its includes."""
    tests: dict[str, dict] = {}

    def load(path: Path) -> None:
        data = tomllib.loads(path.read_text())
        for include in data.get("includes", []):
            load(path.parent / include)
        for test in data.get("tests", []):
            tests[test["name"]] = test

    load(testlist)
    return tests


def controller_images(test: dict) -> set[str]:
    """The DV firmware images an entry builds or loads into the controller."""
    images: set[str] = set()
    firmware = test.get("firmware")
    if isinstance(firmware, dict):
        images.add(firmware["name"])
    elif isinstance(firmware, str):
        images.add(firmware)
    for arg in test.get("args", []):
        match = BFM_ROM_HEX.match(arg)
        if match:
            images.add(match.group("stem"))
    return images


def reporting_modes() -> tuple[str, ...]:
    tree = ast.parse(DUAL_DEFS.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "STATUS_REPORTING_MODES" for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{DUAL_DEFS} defines no STATUS_REPORTING_MODES")


def mode_violations(
    tests: dict[str, dict], dependent: dict[str, set[str]], modes: tuple[str, ...]
) -> list[str]:
    """One message per entry with a status-dependent image and not exactly one mode."""
    violations = []
    for name, test in sorted(tests.items()):
        images = sorted(image for image in controller_images(test) if dependent.get(image))
        if not images:
            continue
        given = [arg for arg in test.get("args", []) if arg.lstrip("+") in modes]
        if len(given) != 1:
            symbols = sorted(set().union(*(dependent[image] for image in images)))
            violations.append(
                f"{name}: {', '.join(images)} names {', '.join(symbols)}; "
                f"pass exactly one of {', '.join('+' + m for m in modes)} "
                f"(found {given or 'none'})"
            )
    return violations


class StatusReportingModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.commands = status_commands(OCCP_HEADER.read_text())
        lib = [path.read_text() for path in sorted(OCCP_LIB.glob("*.c"))]
        cls.senders = status_senders(lib, cls.commands)
        symbols = cls.commands | cls.senders | {UNSUPPORTED_STATUS}
        cls.dependent = {
            image.name: image_status_symbols(image, symbols)
            for image in sorted(FW_TESTS.iterdir())
            if image.is_dir()
        }
        cls.modes = reporting_modes()
        cls.tests = load_testlist(TESTLIST)

    def test_rule_reads_the_status_commands_and_their_senders(self) -> None:
        self.assertTrue(self.commands, "no GET_STATUS-family command in occp_encode_header_word")
        self.assertTrue(self.senders, "no OCCP library function sends a GET_STATUS command")
        self.assertNotIn("occp_send_generic_get_command", self.senders, "dispatcher, not sender")

    def test_rule_separates_dependent_from_independent_images(self) -> None:
        enrolled = set().union(*(controller_images(t) for t in self.tests.values()))
        occp = {image for image in enrolled if image in self.dependent}
        self.assertTrue({i for i in occp if self.dependent[i]}, "no enrolled image depends")
        self.assertTrue({i for i in occp if not self.dependent[i]}, "every enrolled image depends")

    def test_every_bfm_image_has_sources(self) -> None:
        for name, test in sorted(self.tests.items()):
            for arg in test.get("args", []):
                match = BFM_ROM_HEX.match(arg)
                if match:
                    with self.subTest(test=name):
                        self.assertIn(match.group("stem"), self.dependent, "no fw/tests source")

    def test_dual_harness_reads_the_modes(self) -> None:
        tree = ast.parse(DUAL_BASE.read_text())
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertIn("STATUS_REPORTING_MODES", names)
        self.assertIn("STATUS_RPT_DISABLE", self.modes)

    def test_status_dependent_entries_name_one_mode(self) -> None:
        self.assertEqual(mode_violations(self.tests, self.dependent, self.modes), [])

    def test_missing_mode_is_reported(self) -> None:
        image = next(i for i, symbols in sorted(self.dependent.items()) if symbols)
        entry = {"firmware": {"name": image, "mode": "occp_rom_only"}, "args": ["+BOOT_I3C"]}
        self.assertEqual(len(mode_violations({"probe": entry}, self.dependent, self.modes)), 1)
        both = dict(entry, args=[f"+{self.modes[0]}", f"+{self.modes[1]}"])
        self.assertEqual(len(mode_violations({"probe": both}, self.dependent, self.modes)), 1)
        one = dict(entry, args=[f"+{self.modes[0]}"])
        self.assertEqual(mode_violations({"probe": one}, self.dependent, self.modes), [])


if __name__ == "__main__":
    unittest.main()
