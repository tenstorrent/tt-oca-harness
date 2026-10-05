# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each SMC cocotb leaf must require the evidence its SMC_VPLAN card declares.

`smc_base_test` fails a run that never emits a `CHK-<ID>:` line named in the
leaf's `required_evidence`. That gate only means something if the tuple is the
plan's list, so this test reads every "Test Procedures" card in SMC_VPLAN.adoc,
imports every leaf the `all` group runs, and compares the two in both
directions: nothing required that the plan does not declare, and nothing the
plan declares that the leaf does not require, except the entries listed in
`PLAN_CODE_MISMATCH` with the reason each one is still open. That list is held
to `PLAN_CODE_MISMATCH_CEILING`, so it can only shrink.

Rows the plan marks "SV-UVM shape only" are the UVM shape's checkers and are
not expected from cocotb. A declared name is read the way the run's recorder
reads a log line, up to the first character outside `[A-Za-z0-9_-]`, so
`CHK-RESET-LOCK-ARM[<pair>]` is the name `CHK-RESET-LOCK-ARM`. A `<placeholder>`
inside the name makes it a template (`CHK-NDM-REQ-<bit>`) that concrete required
names instantiate.

A plain cocotb leaf over `SmcDualHarness` is gated by the `dual_test`
decorator, which builds the harness from the leaf's `REQUIRED_EVIDENCE` and
runs the gate when the leaf returns, so each one must be registered through it
and neither build a harness nor call the gate itself.

Importing the leaves needs the `dv` dependency group (cocotb, pyuvm). Run from
the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import ast
import importlib
import inspect
import re
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SMC_DV = REPO_ROOT / "hw" / "sys" / "smc" / "dv"
COCOTB_ROOT = SMC_DV / "cocotb"
VPLAN = SMC_DV / "docs" / "SMC_VPLAN.adoc"
TESTLIST = SMC_DV / "testlists" / "all.toml"
GROUP = "all"

UVM_ONLY_MARK = "SV-UVM shape only"
RECORDED_NAME = re.compile(r"^CHK-(?:[A-Za-z0-9_-]|<[^>]+>)+")
CARD_HEADING = re.compile(r"^===== \d+ `([^`]+)`")
CHECKER_ROW = re.compile(r"^\|`(CHK-[^`]+)`\s*\|(.*)$")
PLACEHOLDER = re.compile(r"<[^>]+>")

# Tokens a card declares that the leaf's cocotb shape never emits, with the
# reason. An entry is removed when the card or the leaf is corrected; the test
# fails if an entry stops being declared or starts being required.
PLAN_CODE_MISMATCH: dict[str, dict[str, str]] = {}

# Every `PLAN_CODE_MISMATCH` entry must be in this set, which never grows:
# a new mismatch is fixed on the card or in the leaf.
PLAN_CODE_MISMATCH_CEILING = frozenset(
    {
        ("smc_input_output_fabric_wr_rd_test", "CHK-ALIAS-REMAP-RESET-DEFAULT"),
    }
)

try:
    import cocotb  # noqa: F401
    import pyuvm  # noqa: F401
except ImportError:  # pragma: no cover - environment without the dv group
    DV_DEPS = False
else:
    DV_DEPS = True


def load_group(testlist: Path, group: str) -> dict[str, str]:
    """Return test name -> cocotb module for the members of `group`."""
    tests: dict[str, dict] = {}
    groups: dict[str, dict] = {}

    def load(path: Path) -> None:
        data = tomllib.loads(path.read_text())
        for include in data.get("includes", []):
            load(path.parent / include)
        for test in data.get("tests", []):
            tests[test["name"]] = test
        for entry in data.get("groups", []):
            groups[entry["name"]] = entry

    load(testlist)
    members = {}
    for name in groups[group]["tests"]:
        module = tests[name]["module"]
        members[name] = module["cocotb"] if isinstance(module, dict) else module
    return members


def load_vplan_cards(vplan: Path) -> dict[str, dict[str, bool]]:
    """Return test name -> {declared token: is_uvm_only} from the Test Procedures cards."""
    cards: dict[str, dict[str, bool]] = {}
    current = None
    for line in vplan.read_text().splitlines():
        heading = CARD_HEADING.match(line)
        if heading:
            current = heading.group(1)
            cards[current] = {}
            continue
        row = CHECKER_ROW.match(line)
        if row and current is not None:
            cards[current][row.group(1)] = UVM_ONLY_MARK in row.group(2)
    return cards


def recorded_name(declared: str) -> str:
    """The ID the run's recorder reads from a line starting with `declared`."""
    match = RECORDED_NAME.match(declared)
    if match is None:
        raise ValueError(f"not a CHK name: {declared!r}")
    return match.group(0)


def template_regex(declared: str) -> re.Pattern[str] | None:
    if not PLACEHOLDER.search(declared):
        return None
    parts = [re.escape(part) for part in PLACEHOLDER.split(declared)]
    return re.compile("^" + "[A-Za-z0-9_]+".join(parts) + "$")


def declared_for(
    cards: dict[str, dict[str, bool]], name: str
) -> tuple[set[str], list[re.Pattern[str]]]:
    """Cocotb-declared concrete tokens and template patterns of one card."""
    concrete: set[str] = set()
    templates: list[re.Pattern[str]] = []
    for declared, uvm_only in cards.get(name, {}).items():
        if uvm_only:
            continue
        token = recorded_name(declared)
        pattern = template_regex(token)
        if pattern is None:
            concrete.add(token)
        else:
            templates.append(pattern)
    return concrete, templates


def is_declared(token: str, concrete: set[str], templates: list[re.Pattern[str]]) -> bool:
    return token in concrete or any(pattern.match(token) for pattern in templates)


class PlanCodeMismatchListTest(unittest.TestCase):
    def test_plan_code_mismatch_only_shrinks(self) -> None:
        listed = {(leaf, token) for leaf, tokens in PLAN_CODE_MISMATCH.items() for token in tokens}
        self.assertEqual(
            sorted(listed - PLAN_CODE_MISMATCH_CEILING),
            [],
            "PLAN_CODE_MISMATCH grew: correct the card or the leaf instead of listing it",
        )


@unittest.skipUnless(DV_DEPS, "importing the SMC leaves needs the dv dependency group")
class SmcRequiredEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        for path in (COCOTB_ROOT, COCOTB_ROOT / "tests"):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        base = importlib.import_module("smc_base_test")
        cls.exempt = set(base._EvidenceRecorder.NO_OWN_EVIDENCE)
        cls.cards = load_vplan_cards(VPLAN)
        cls.members = load_group(TESTLIST, GROUP)
        cls.leaves: dict[str, tuple[tuple[str, ...], int | None]] = {}
        for name, module_name in cls.members.items():
            module = importlib.import_module(module_name)
            leaf = getattr(module, name)
            if isinstance(leaf, type):
                cls.leaves[name] = (tuple(leaf.required_evidence), int(leaf.min_evidence))
            else:  # a plain cocotb test over SmcDualHarness
                cls.leaves[name] = (tuple(module.REQUIRED_EVIDENCE), None)

    def test_every_member_has_a_card(self) -> None:
        missing = sorted(set(self.members) - set(self.cards))
        self.assertEqual(missing, [], f"{GROUP} members without a Test Procedures card")

    def test_required_evidence_is_a_sorted_tuple_of_tokens(self) -> None:
        for name, (required, _) in self.leaves.items():
            with self.subTest(leaf=name):
                self.assertEqual(list(required), sorted(set(required)), "sorted, no duplicates")
                for token in required:
                    self.assertRegex(token, r"^CHK-[A-Za-z0-9][A-Za-z0-9_-]*$")

    def test_exempt_leaves_declare_and_require_nothing(self) -> None:
        for name in sorted(self.exempt & set(self.leaves)):
            required, min_evidence = self.leaves[name]
            concrete, templates = declared_for(self.cards, name)
            with self.subTest(leaf=name):
                self.assertEqual(required, (), "an exempt leaf requires nothing")
                self.assertEqual(min_evidence, 0, "an exempt leaf has no floor")
                self.assertEqual(
                    (concrete, templates),
                    (set(), []),
                    "the card declares cocotb evidence: the exemption is stale",
                )

    def test_required_evidence_is_declared_by_the_card(self) -> None:
        for name, (required, _) in self.leaves.items():
            concrete, templates = declared_for(self.cards, name)
            with self.subTest(leaf=name):
                undeclared = [t for t in required if not is_declared(t, concrete, templates)]
                self.assertEqual(undeclared, [], "required but not in the card")

    def test_declared_evidence_is_required_or_listed(self) -> None:
        for name, (required, _) in self.leaves.items():
            if name in self.exempt:
                continue
            concrete, templates = declared_for(self.cards, name)
            listed = PLAN_CODE_MISMATCH.get(name, {})
            with self.subTest(leaf=name):
                unrequired = sorted(concrete - set(required) - set(listed))
                self.assertEqual(unrequired, [], "declared but neither required nor listed")
                for token in listed:
                    self.assertIn(token, concrete, "listed mismatch no longer declared: drop it")
                    self.assertNotIn(token, required, "listed mismatch is required: drop it")
                for pattern in templates:
                    self.assertTrue(
                        any(pattern.match(t) for t in required),
                        f"template {pattern.pattern} has no required instance",
                    )

    def test_unlisted_leaf_is_gated(self) -> None:
        for name, (required, min_evidence) in self.leaves.items():
            if name in self.exempt or min_evidence is None:
                continue
            concrete, _ = declared_for(self.cards, name)
            own = [t for t in required if not t.startswith("CHK-PROBE-")]
            with self.subTest(leaf=name):
                if required:
                    self.assertTrue(0 < min_evidence <= len(own), "floor inside the required set")
                else:
                    self.assertEqual(concrete, set(), "the card declares tokens: require them")
                    self.assertGreater(min_evidence, 0, "no required evidence and no floor")

    def test_dual_leaf_hands_its_tokens_to_the_gate(self) -> None:
        for name, (required, min_evidence) in self.leaves.items():
            if min_evidence is not None:
                continue
            module = importlib.import_module(self.members[name])
            tree = ast.parse(inspect.getsource(module))
            leaf = next(
                node
                for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == name
            )
            decorators = [ast.unparse(node) for node in leaf.decorator_list]
            called = {
                ast.unparse(node.func) for node in ast.walk(leaf) if isinstance(node, ast.Call)
            }
            with self.subTest(leaf=name):
                self.assertNotEqual(required, (), "a dual leaf requires nothing")
                self.assertEqual(
                    decorators,
                    ["dual_test(REQUIRED_EVIDENCE)"],
                    "the leaf is registered through dual_test with its REQUIRED_EVIDENCE",
                )
                self.assertNotIn("SmcDualHarness", called, "the decorator builds the harness")
                self.assertNotIn("harness.finalize_evidence", called, "the decorator runs the gate")


if __name__ == "__main__":
    unittest.main()
