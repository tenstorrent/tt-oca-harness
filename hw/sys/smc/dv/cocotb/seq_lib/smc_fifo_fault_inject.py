# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Single-bit fault injection into a published DUT register.

The SMC public scope (`tb/smc_public_scope.vlt`) publishes the entry array of
`prim_fifo_sync_parity` and the register of `prim_flop`, so a sequence can
reach a queued FIFO entry's stored parity bit or one copy of a hardened
pointer by hierarchical path. A fault is one bit flipped by a deposit on a
rising edge of `clk_periph`, the clock of the peripheral cells; the register
is read back after the next edge of that clock and the flip must be visible
there, so a poke the simulator refused, optimised away or let the cell
overwrite fails the leg instead of leaving the error report ungraded. The
waits and holds count `clk_periph` cycles for the same reason.

`storage` has no reset, so on a four-state simulator every slot that was
never written reads X. The sequences therefore read only the slot they
queued (`read_field`), and `flip_bit` compares the register as a bit string:
the flipped bit must have been 0 or 1 before the deposit and must be the only
position that changed, while an X elsewhere is left alone. The two leaves are
still Verilator-only (`tools = ["verilator"]` in their testlist entries): the
deposit path is the Verilator public scope (`tb/smc_public_scope.vlt`).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.types import LogicArray

SMC_PERIPH = "u_dut.u_smc.u_smc_peripherals"


def hier(path: str):
    """The handle of ``path`` below the bench top, or an assertion naming the failure."""
    try:
        return cocotb.top[path]
    except (KeyError, AttributeError) as exc:
        raise AssertionError(f"{path}: not reachable from {cocotb.top._path}: {exc}") from exc


def read_int(handle) -> int:
    """The whole register as an integer; every bit must be 0 or 1."""
    value = handle.value
    assert value.is_resolvable, f"{handle._path} is X/Z"
    return int(value)


def _bits(handle) -> str:
    """The register as a bit string, most significant bit first, X and Z kept."""
    return str(handle.value).upper()


def _field_of(bits: str, path: str, lo: int, width: int) -> int:
    """Bits ``[lo + width - 1 : lo]`` of ``bits`` as an integer; that slice must be 0/1."""
    n = len(bits)
    assert 0 <= lo and lo + width <= n, f"{path}[{lo + width - 1}:{lo}] is outside {n} bits"
    field = bits[n - lo - width : n - lo]
    assert set(field) <= {"0", "1"}, f"{path}[{lo + width - 1}:{lo}] is X/Z ({field})"
    return int(field, 2)


def read_field(handle, lo: int, width: int) -> int:
    """Bits ``[lo + width - 1 : lo]`` of ``handle`` as an integer.

    Only that slice must be resolvable: the entry array of a FIFO has no reset,
    so a slot never written reads X on a four-state simulator and must not
    fail a read of the slot that was.
    """
    return _field_of(_bits(handle), handle._path, lo, width)


async def flip_bit(
    handle, bit: int, label: str, field: tuple[int, int] | None = None
) -> tuple[int, int]:
    """Flip ``bit`` of ``handle`` on a clock edge and prove the flip landed.

    ``bit`` must read 0 or 1 before the deposit and must be the only position
    of the register that differs after it; a bit elsewhere that reads X stays
    X. Returns ``(before, after)`` as integers of ``field`` (``(lo, width)``),
    or of the whole register when ``field`` is None.
    """
    clk = cocotb.top.clk_periph
    await RisingEdge(clk)
    before_bits = _bits(handle)
    n = len(before_bits)
    assert 0 <= bit < n, f"{label}: bit {bit} is outside the {n} bits of {handle._path}"
    idx = n - 1 - bit
    assert before_bits[idx] in "01", (
        f"{label}: {handle._path} bit {bit} reads {before_bits[idx]} before the deposit"
    )
    flipped = before_bits[:idx] + ("1" if before_bits[idx] == "0" else "0") + before_bits[idx + 1 :]
    if set(flipped) <= {"0", "1"}:
        handle.value = int(flipped, 2)
    else:
        handle.value = LogicArray(flipped)
    await RisingEdge(clk)
    await ReadOnly()
    after_bits = _bits(handle)
    await RisingEdge(clk)
    changed = [n - 1 - i for i, (a, b) in enumerate(zip(before_bits, after_bits)) if a != b]
    assert changed == [bit], (
        f"{label}: deposit on {handle._path} bit {bit} did not land as one flipped bit "
        f"(changed bits {changed}; before={before_bits} after={after_bits})"
    )
    lo, width = field if field is not None else (0, n)
    before = _field_of(before_bits, handle._path, lo, width)
    after = _field_of(after_bits, handle._path, lo, width)
    cocotb.log.info(
        "%s: flipped %s bit %d: [%d:%d] 0x%x -> 0x%x (read back after the next clk_periph edge)",
        label,
        handle._path,
        bit,
        lo + width - 1,
        lo,
        before,
        after,
    )
    return before, after


async def wait_level(read, want: int, bound: int, label: str) -> int:
    """Poll ``read()`` once per clk_periph cycle until it returns ``want``; expiry fails."""
    clk = cocotb.top.clk_periph
    got = read()
    for _ in range(bound):
        got = read()
        if got == want:
            return got
        await RisingEdge(clk)
    raise AssertionError(f"{label}: still {got}, expected {want}, after {bound} clk_periph cycles")


async def hold_level(read, want: int, cycles: int, label: str) -> None:
    """``read()`` must return ``want`` on every one of ``cycles`` clk_periph cycles."""
    clk = cocotb.top.clk_periph
    for cycle in range(cycles):
        got = read()
        assert got == want, (
            f"{label}: left {want} after {cycle} of {cycles} hold cycles (read {got})"
        )
        await RisingEdge(clk)
