# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Every console token a testcase names must be one the OCA ROM or BL1 can print."""

import dataclasses

import dv_env
import pytest
from preloaded_test_programs import PROGRAMS
from sepvp import paths
from test_sep_rom_testlist import TESTCASES
from testlist_loader import MEASUREMENT_DIGEST_TOKEN

pytestmark = pytest.mark.hostonly

_CONSOLE = dv_env.load("sep_oca_console")
_ASM = "\n".join(p.read_text() for p in (paths.BOOTCODE_DIR / "src").glob("*.S"))
_VP_LINES = ("[VP] SIMULATION OF THE TEST PASSED", "[VP] SIMULATION OF THE TEST FAILED")
_BANNED = (
    "MANIFEST_HASH_OK",
    "SIG_VALID",
    "CRYPTO_VALIDATE_OK",
    "PLD_HASH_OK",
    "RSA_VERIFY_START",
)


def _stub_tokens(case):
    """Tokens printed by the preloaded stubs the case deposits, not by the ROM."""
    printed = set()
    for name in case.preloaded_test_programs:
        printed |= PROGRAMS[name].printed_tokens()
    return printed


def _named_tokens(case):
    tokens = [*case.expect, *case.forbid, *case.expect_counts]
    if case.terminal_token:
        tokens.append(case.terminal_token)
    stub = _stub_tokens(case)
    return [
        t
        for t in tokens
        if t not in _VP_LINES and t != MEASUREMENT_DIGEST_TOKEN and t not in _ASM and t not in stub
    ]


@pytest.mark.parametrize(
    "case", [c for c in TESTCASES if c.classification != "retired"], ids=lambda c: c.name
)
def test_tokens_are_printed_by_the_oca_rom(case):
    assert not set(case.expect) & set(_BANNED), f"{case.name} expects a legacy-ROM token"
    _CONSOLE.assert_known(_named_tokens(case), case.name)


def test_stub_token_is_exempt_only_for_a_case_that_preloads_the_stub():
    case = next(c for c in TESTCASES if "warm_jump" in c.preloaded_test_programs)
    assert "WARM_JUMP_OK" in case.expect
    assert "WARM_JUMP_OK" not in _named_tokens(case)
    bare = dataclasses.replace(case, preloaded_test_programs=())
    assert "WARM_JUMP_OK" in _named_tokens(bare)
    with pytest.raises(AssertionError, match="WARM_JUMP_OK"):
        _CONSOLE.assert_known(_named_tokens(bare), bare.name)


def test_stub_tokens_are_decoded_from_the_stub_source():
    assert PROGRAMS["warm_jump"].printed_tokens() == {"WARM_JUMP_OK"}
    assert PROGRAMS["warm_jump_relocated"].printed_tokens() == {"WARM_JUMP_OK"}
    assert PROGRAMS["warm_fault"].printed_tokens() == {"WARM_JUMP_OK", "PST"}
