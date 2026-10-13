# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Graded-window gate of the FCOV sampler (docs/SEP_FCOV.adoc).

The sampler ``u_sep_fcov`` (cov/sv/sep_fcov.sv) samples a graded bin only
while its variable ``graded_owner`` holds the code of an owning test. A leaf
writes its own code at the first step of its graded stimulus and 0 before a
control leg, a bring-up or clean-up step, a reset that is not graded, and at
the end of the leaf.

The codes come from one table, ``tb/sep_fcov_owner_codes.svh``, which the
sampler includes. This module reads the same file, so the leaf and the sampler
cannot disagree on a code.

``u_sep_fcov`` exists on every simulator except Verilator (``tb/tb_top.sv``
instantiates it under ``ifndef VERILATOR``). On Verilator every call here is a
no-op and returns False; a check of a leaf never depends on the gate. On any
other simulator a missing sampler or ``graded_owner`` is a testbench error, so a
build that lost the sampler fails instead of leaving the owner-gated bins empty.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import cocotb

_CODES_SVH = Path(__file__).resolve().parents[2] / "tb" / "sep_fcov_owner_codes.svh"
_LINE = re.compile(r"^\s*localparam\s+int\s+unsigned\s+FcovOwn(\w+)\s*=\s*(\d+)\s*;", re.M)
_CAMEL_BREAK = re.compile(r"(?<!^)(?=[A-Z])")


@lru_cache(maxsize=1)
def owner_codes() -> dict[str, int]:
    """Map test name (lower case) to its owner code; ``none`` maps to 0."""
    text = _CODES_SVH.read_text()
    codes = {_CAMEL_BREAK.sub("_", name).lower(): int(code) for name, code in _LINE.findall(text)}
    if codes.get("none") != 0:
        raise RuntimeError(f"{_CODES_SVH}: FcovOwnNone must be 0")
    if len(set(codes.values())) != len(codes):
        raise RuntimeError(f"{_CODES_SVH}: an owner code is used twice")
    return codes


def owner_code(test_name: str) -> int:
    """The owner code of ``test_name``. A missing name is a testbench error."""
    try:
        return owner_codes()[test_name.lower()]
    except KeyError as exc:
        raise KeyError(
            f"{test_name} has no FcovOwn line in {_CODES_SVH.name}; add one before it opens a window"
        ) from exc


def _sampler_expected() -> bool:
    return "verilator" not in str(getattr(cocotb, "SIM_NAME", "") or "").lower()


def _gate_handle():
    if not _sampler_expected():
        return None
    dut = cocotb.top
    if not hasattr(dut, "u_sep_fcov"):
        raise AttributeError(
            f"{cocotb.SIM_NAME}: tb_top has no u_sep_fcov; the FCOV sampler must exist on "
            "every simulator except Verilator (tb/tb_top.sv, cov/sv/sep_fcov.sv)"
        )
    fcov = dut.u_sep_fcov
    if not hasattr(fcov, "graded_owner"):
        raise AttributeError("u_sep_fcov has no graded_owner variable (cov/sv/sep_fcov.sv)")
    return fcov.graded_owner


def fcov_present() -> bool:
    """True when the build carries the sampler (every simulator except Verilator)."""
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


def set_quiet_window(on: bool, log=None) -> bool:
    """Write ``u_sep_fcov.quiet_win`` (1 inside a quiet window, else 0).

    The mailbox leaf sets it at the end of the settle wait of a check cycle and
    clears it before the next access to the mailbox unit (docs/SEP_FCOV.adoc,
    mailbox, IRQ and PIC sampling rules). Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the
    variable is a testbench error.
    """
    if _gate_handle() is None:
        return False
    fcov = cocotb.top.u_sep_fcov
    if not hasattr(fcov, "quiet_win"):
        raise AttributeError("u_sep_fcov has no quiet_win variable (cov/sv/sep_fcov.sv)")
    fcov.quiet_win.value = 1 if on else 0
    if log is not None:
        log.info("FCOV-QUIET %s", "open" if on else "closed")
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
