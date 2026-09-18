# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Agent base for the DUT-local agent a one-consumer protocol gets.

The same item, sequencer, driver, monitor structure as a shared VIP agent, so
the day the protocol gains a second consumer the agent moves to the VIP root
unchanged. The SV-UVM twin is ``ocah_agent``.
"""

from __future__ import annotations

from pyuvm import uvm_agent

__all__ = ["OcahAgent"]


class OcahAgent(uvm_agent):
    """Base of a DUT-local agent: item, sequencer, driver, monitor."""
