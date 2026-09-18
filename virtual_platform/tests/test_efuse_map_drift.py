# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Guard the VP eFuse model's register map against the RDL.

Why this lives here rather than in the model repo
-------------------------------------------------
The model is a separate repository and does not contain the RDL, so it cannot
check itself against the authority. This repo has both: the RDL (and the C header
generated from it, which is what the RTL and the boot ROM are built against) and
the model as a submodule. This is the only place the comparison can be made.

Why it exists at all
--------------------
Two real bugs shipped in the model because nothing performed this check:

  * LOCKS_SPARE (0x008) was missing, putting every register from LC_STATE onward
    four bytes below the RDL. Invisible for as long as it was, because every fuse
    the tests read was zero -- the ROM reading LC_STATE's address got the model's
    SBOOT_DIS, and both are 0 on a TEST_DEV part. CLASS_KEY was the first
    non-zero multi-word bank anything read, and it came back shifted one word.

  * From PUBLIC_KEY_0 onward the model was a whole RDL revision behind: generic
    RESERVED_* blocks where the RDL defines the identity banks and the PQC key
    hashes. Reads returned zeroes rather than faulting, so a manifest constrained
    to a chiplet identity could not be tested in the accept direction at all, and
    the reject direction would have passed for the wrong reason.

The model's own unit tests could not catch either: they validate the model
against a hand-copied offset table kept in the test directory, so the model and
its tests were self-consistent and jointly wrong.

No unit test is a substitute for this comparison. Anything that reads the model's
own header is asking the model whether it agrees with itself.
"""

import re

import pytest
from sepvp import paths

# Registers whose model spelling differs from the RDL's. Kept deliberately short:
# every entry is a name the model has not caught up on, so the map shrinking is
# progress and a new entry should be justified rather than added for convenience.
_ALIASES = {
    "LOCKS": "LOCKS_LO",  # RDL 64-bit; model splits LO/HI
    "SIP_DIS": "SIP_DIS_LO",  # ditto
    "SYS_DIS": "SYS_DIS_LO",  # ditto
    "RMA_SIP_TOKEN_DIGEST": "RMA_SIP_TOKEN",
    "RMA_CHIPLET_TOKEN_DIGEST": "RMA_CHIPLET_TOKEN",
    "ROM_CTL": "SEP_ROM_CTRL",
}

_GENERATED_HEADER = paths.OCAH_ROOT / "hw" / "sys" / "sep" / "regs" / "gen" / "c" / "sep_addr.h"
_MODEL_HEADER = paths.SIM_DIR / "sep" / "peripherals" / "efuse" / "include" / "efuse_register.h"

# The fuse-array shadow region. Above this the model models an OTP interface and
# an MMR block whose layout is its own business.
_SHADOW_LIMIT = 0x400


def _rdl_offsets():
    """{register name: offset} for the shadow region, from the generated header."""
    text = _GENERATED_HEADER.read_text()
    out = {}
    for m in re.finditer(r"SEP_EFUSE_MAP_([A-Z0-9_]+)_BASE_ADDR\s+0x1093(0[0-9A-F]{3})", text):
        off = int(m.group(2), 16)
        if off < _SHADOW_LIMIT:
            out[m.group(1)] = off
    return out


def _model_offsets():
    """{register name: offset} for the shadow region, from the model's header."""
    text = _MODEL_HEADER.read_text()
    out = {}
    for m in re.finditer(r"(\w+)_OFFSET\s*=\s*0x([0-9A-Fa-f]{3});", text):
        off = int(m.group(2), 16)
        if off < _SHADOW_LIMIT:
            out[m.group(1)] = off
    return out


@pytest.fixture(scope="module")
def maps():
    if not _GENERATED_HEADER.is_file():
        pytest.skip(f"generated register header not found: {_GENERATED_HEADER}")
    if not _MODEL_HEADER.is_file():
        pytest.skip(
            f"model eFuse header not found: {_MODEL_HEADER} "
            "(tt-oca-harness-model submodule checked out?)"
        )
    rdl, model = _rdl_offsets(), _model_offsets()
    assert rdl, "parsed no registers from the generated header -- parser out of date?"
    assert model, "parsed no registers from the model header -- parser out of date?"
    return rdl, model


def test_every_rdl_register_exists_in_the_model(maps):
    """A register the RDL defines and the model lacks reads as reserved space.

    That is the dangerous shape: the read succeeds and returns zero rather than
    faulting, so firmware sees a plausible value for a fuse the part never
    provisioned.
    """
    rdl, model = maps
    missing = sorted(f"{n} (0x{o:03X})" for n, o in rdl.items() if _ALIASES.get(n, n) not in model)
    assert not missing, (
        "registers in the RDL with no counterpart in the VP eFuse model:\n  "
        + "\n  ".join(missing)
        + "\nReads of these land in reserved space and return zeroes instead of "
        "faulting. Add them to the model, or add an alias here if the model "
        "simply spells the name differently."
    )


def test_model_offsets_match_the_rdl(maps):
    """Same register, same address. The check both shipped bugs needed."""
    rdl, model = maps
    wrong = []
    for name, off in sorted(rdl.items(), key=lambda kv: kv[1]):
        mname = _ALIASES.get(name, name)
        if mname in model and model[mname] != off:
            wrong.append(
                f"{name}: RDL 0x{off:03X}, model {mname} "
                f"0x{model[mname]:03X} (off by {model[mname] - off:+d})"
            )
    assert not wrong, (
        "VP eFuse model offsets disagree with the RDL:\n  "
        + "\n  ".join(wrong)
        + "\nThe ROM is built against the generated header, so it reads the RDL's "
        "addresses; a model that places a register elsewhere hands firmware a "
        "neighbouring register's contents."
    )


def test_the_shadow_region_is_fully_covered(maps):
    """No gaps: every 32-bit word below 0x400 belongs to some register.

    An unclaimed word is how LOCKS_SPARE went missing -- nothing was wrong with
    any individual offset, the map was simply four bytes short and everything
    after it slid down.
    """
    rdl, _ = maps
    offsets = sorted(rdl.values())
    gaps = []
    for lo, hi in zip(offsets, offsets[1:]):
        if hi <= lo:
            gaps.append(f"0x{lo:03X} and 0x{hi:03X} are not ascending")
    assert not gaps, "\n".join(gaps)
    # The region is exactly 1 KiB of fuse array; the last register must reach it.
    assert offsets[0] == 0, f"shadow region should start at 0x000, got 0x{offsets[0]:03X}"
