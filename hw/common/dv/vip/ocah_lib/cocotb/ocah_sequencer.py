# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequencer base mirroring ``uvm_sequencer``.

Typed by a VIP item it is the parent a VIP master sequencer adopts; with the
default item type it is the parent of every ``<Dut>VirtualSequencer``, which
adds one typed handle per agent sequencer and one per responder sequence and
nothing else. The SV-UVM twin is ``ocah_sequencer``.
"""

from __future__ import annotations

from pyuvm import uvm_sequencer

__all__ = ["OcahSequencer"]


class OcahSequencer(uvm_sequencer):
    """Base of every VIP master sequencer and of the bench virtual sequencer."""
