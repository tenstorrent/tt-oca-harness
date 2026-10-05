# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""File-path plusarg guard: the one place a path-valued plusarg is checked.

A bench base test calls ``require_file_plusargs`` first thing in ``build_phase``
with every plusarg name the bench and its models consume as a path, so a
``+<name>=<path>`` whose file cannot be opened fails the run at time 0 with one
line naming the plusarg, before any clock or image load. An absent plusarg is
not an error, nor is a bare ``+<name>``: only a present value is opened. The
SV twin ``ocah_require_file_plusargs`` (``uvm/ocah_path_plusargs.svh``) reports
the same line from the testbench top.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import cocotb

__all__ = ["OcahPathPlusargError", "require_file_plusargs"]


class OcahPathPlusargError(FileNotFoundError):
    """Raised when a file-path plusarg names a file that cannot be opened."""


def require_file_plusargs(
    names: Iterable[str],
    *,
    exclude: Iterable[str] = (),
    plusargs: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    """Open every present plusarg in ``names`` for reading; raise on the first failure.

    ``exclude`` names plusargs the calling test writes during the run before
    anything reads them. Returns the names that were present and readable.
    """
    if plusargs is None:
        plusargs = cocotb.plusargs
    skipped = set(exclude)
    checked: list[str] = []
    for name in names:
        if name in skipped:
            continue
        value = plusargs.get(name)
        if value is None or value is True:
            continue
        path = str(value)
        try:
            with open(path, "rb"):
                pass
        except OSError as exc:
            raise OcahPathPlusargError(
                f"[ocah_path_plusargs] +{name}={path} is not a readable file ({exc.strerror})"
            ) from exc
        checked.append(name)
    return tuple(checked)
