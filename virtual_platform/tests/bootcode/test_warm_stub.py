# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import shutil

import gen_warm_stub
import pytest
from preloaded_test_programs import PROGRAMS

pytestmark = pytest.mark.hostonly


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in gen_warm_stub.TOOLS),
    reason="RISC-V toolchain is required to verify generated warm-handler words",
)
def test_warm_handler_words_match_source():
    assert gen_warm_stub.verify(), (
        "warm_handler_words.py is stale; run tests/bootcode/gen_warm_stub.py"
    )


def test_preloaded_program_registry():
    assert PROGRAMS["warm_jump_relocated"].load_address == 0xC0038000
    assert PROGRAMS["warm_jump_relocated"].words == PROGRAMS["warm_jump"].words
    assert PROGRAMS["warm_fault"].load_address == 0xC0030000
    assert PROGRAMS["warm_fault"].words[17] == 0x00000000


def test_generator_covers_every_assembly_source():
    assert {spec.source.name for spec in gen_warm_stub.SPECS} == {
        "warm_handler_stub.S",
        "warm_fault_stub.S",
    }
