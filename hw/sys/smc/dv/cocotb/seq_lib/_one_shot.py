# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared one-shot sequence helper used by cross-agent test sequences."""

from __future__ import annotations

from pyuvm import uvm_sequence


class _OneShot(uvm_sequence):
    """Single-item wrapper sequence so a parent seq can hop sequencers."""

    def __init__(self, item, name: str = "one_shot") -> None:
        super().__init__(name)
        self._item = item

    async def body(self) -> None:
        await self.start_item(self._item)
        await self.finish_item(self._item)
