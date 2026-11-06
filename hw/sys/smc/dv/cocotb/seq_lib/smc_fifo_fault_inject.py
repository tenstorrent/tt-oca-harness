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
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge

SMC_PERIPH = "u_dut.u_smc.u_smc_peripherals"


def hier(path: str):
    """The handle of ``path`` below the bench top, or an assertion naming the failure."""
    try:
        return cocotb.top[path]
    except (KeyError, AttributeError) as exc:
        raise AssertionError(f"{path}: not reachable from {cocotb.top._path}: {exc}") from exc


def read_int(handle) -> int:
    value = handle.value
    assert value.is_resolvable, f"{handle._path} is X/Z"
    return int(value)


async def flip_bit(handle, bit: int, label: str) -> tuple[int, int]:
    """Flip ``bit`` of ``handle`` on a clock edge and prove the flip landed.

    Returns ``(before, after)`` as integers of the whole register.
    """
    clk = cocotb.top.clk_periph
    await RisingEdge(clk)
    before = read_int(handle)
    handle.value = before ^ (1 << bit)
    await RisingEdge(clk)
    await ReadOnly()
    after = read_int(handle)
    await RisingEdge(clk)
    assert ((before ^ after) >> bit) & 1 == 1 and (before ^ after) == (1 << bit), (
        f"{label}: deposit on {handle._path} bit {bit} did not land "
        f"(before=0x{before:x} after=0x{after:x})"
    )
    cocotb.log.info(
        "%s: flipped %s bit %d: 0x%x -> 0x%x (read back after the next clk_periph edge)",
        label,
        handle._path,
        bit,
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
