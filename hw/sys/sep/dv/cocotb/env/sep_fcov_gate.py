# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Graded-window gate of the Phase 2 FCOV sampler (docs/SEP_FCOV.adoc).

The sampler ``u_sep_fcov`` (cov/sv/sep_fcov.sv) samples a Phase 2 bin only
while its variable ``graded_owner`` holds the code of an owning test. A leaf
writes its own code at the first step of its graded stimulus and 0 before a
control leg, a bring-up or clean-up step, a reset that is not graded, and at
the end of the leaf.

The codes come from one table, ``tb/sep_fcov_owner_codes.svh``, which the
sampler includes. This module reads the same file, so the leaf and the sampler
cannot disagree on a code.

``u_sep_fcov`` exists only on VCS. On Verilator every call here is a no-op and
returns False; a check of a leaf never depends on the gate.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import cocotb

_CODES_SVH = Path(__file__).resolve().parents[2] / "tb" / "sep_fcov_owner_codes.svh"
_LINE = re.compile(r"^\s*localparam\s+int\s+unsigned\s+FCOV_OWN_(\w+)\s*=\s*(\d+)\s*;", re.M)


@lru_cache(maxsize=1)
def owner_codes() -> dict[str, int]:
    """Map test name (lower case) to its owner code; ``none`` maps to 0."""
    text = _CODES_SVH.read_text()
    codes = {name.lower(): int(code) for name, code in _LINE.findall(text)}
    if codes.get("none") != 0:
        raise RuntimeError(f"{_CODES_SVH}: FCOV_OWN_NONE must be 0")
    if len(set(codes.values())) != len(codes):
        raise RuntimeError(f"{_CODES_SVH}: an owner code is used twice")
    return codes


def owner_code(test_name: str) -> int:
    """The owner code of ``test_name``. A missing name is a testbench error."""
    try:
        return owner_codes()[test_name.lower()]
    except KeyError as exc:
        raise KeyError(
            f"{test_name} has no FCOV_OWN_ line in {_CODES_SVH.name}; add one before it opens a window"
        ) from exc


def _gate_handle():
    dut = cocotb.top
    if not hasattr(dut, "u_sep_fcov"):
        return None
    fcov = dut.u_sep_fcov
    return fcov.graded_owner if hasattr(fcov, "graded_owner") else None


def fcov_present() -> bool:
    """True when the build carries the sampler (VCS)."""
    return _gate_handle() is not None


def open_graded_window(test_name: str, log=None) -> bool:
    """Write the owner code of ``test_name``. Returns True when written."""
    code = owner_code(test_name)
    gate = _gate_handle()
    if gate is None:
        return False
    gate.value = code
    if log is not None:
        log.info("FCOV-GATE open owner=%s code=%d", test_name, code)
    return True


def close_graded_window(log=None) -> bool:
    """Write 0 (no window open). Returns True when written."""
    gate = _gate_handle()
    if gate is None:
        return False
    gate.value = 0
    if log is not None:
        log.info("FCOV-GATE closed")
    return True
