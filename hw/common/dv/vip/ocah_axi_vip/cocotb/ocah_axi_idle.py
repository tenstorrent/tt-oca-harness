# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Deterministic idle-drive for cocotbext-axi source channels.

cocotbext-axi initializes every source-channel payload signal to all-X at
construction (``StreamSource._init_x``) and drives real values only from the
first transaction. On a 2-state simulator the X-init degenerates to zeros,
but on 4-state and VPI paths it propagates X into the DUT until the first
beat. Each OCAH driver calls :func:`drive_source_idle` on its own source
channels right after backend construction, overriding the X-init with an
all-zero idle at the same simulation time — a per-instance guarantee, with
no process-global backend state touched. Handshake signals stay owned by
the backend (a source already drives its valid low at construction).
"""

from __future__ import annotations

__all__ = ["drive_source_idle"]


def drive_source_idle(*channels) -> None:
    """Drive every payload signal of the given source channels to 0.

    ``channels`` are cocotbext-axi stream sources: AW/W/AR on a master
    connection, B/R on a responder. The channel's valid/ready handshake
    signals are left untouched.
    """
    for channel in channels:
        handshake = {id(channel.valid), id(channel.ready)}
        for handle in channel.bus._signals.values():
            if id(handle) not in handshake:
                handle.setimmediatevalue(0)
