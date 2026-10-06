# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Local peakrdl c-header exporter that emits the RDL ``desc`` property.

Upstream peakrdl-cheader 1.1.0 comments a register, memory, or struct with its
hierarchical path only and never reads ``desc``, so a generated header carries no
description of the bitfields it defines. This subclasses that exporter's
HeaderGenerator and adds the description as a plain ``//`` comment on each
register, field, memory, and struct.

peakrdl-cheader has no ``--template`` hook the way peakrdl-rawheader does, so the
local behaviour is a peakrdl exporter plugin instead of a template. It is
registered as ``c-header-desc`` from hw/common/regs/peakrdl.toml, which rules.mk
passes with ``--peakrdl-cfg``. Drop both once the descriptions land upstream.
"""

from __future__ import annotations

from typing import Optional

from peakrdl_cheader import exporter as cheader_exporter
from peakrdl_cheader.__peakrdl__ import Exporter as CHeaderExporter
from peakrdl_cheader.header_generator import HeaderGenerator
from peakrdl_cheader.identifier_filter import kw_filter as kwf
from systemrdl.node import AddressableNode, FieldNode, Node, RegNode
from systemrdl.walker import WalkerAction


def desc_lines(node: Node) -> list[str]:
    """The node's RDL ``desc`` split into stripped lines, or none when it has none."""
    desc = node.get_property("desc", default="") or ""
    return [line.strip() for line in desc.splitlines() if line.strip()]


class DescribedHeaderGenerator(HeaderGenerator):
    def __init__(self, ds) -> None:
        super().__init__(ds)
        # The description waiting to follow the next line the stock generator
        # writes that starts with one of the markers.
        self._desc_lines: list[str] = []
        self._desc_markers: tuple[str, ...] = ()

    def write(self, s: str) -> None:
        super().write(s)
        if self._desc_lines and s.startswith(self._desc_markers):
            # Clear first: the comment lines go back through this method.
            lines = self._desc_lines
            self._desc_lines = []
            for line in lines:
                self.write(f"// {line}\n")

    def _describe(self, node: Node) -> None:
        """Emit the node's description right after the path comment it belongs to.

        The stock generator writes that comment through ``write``, and the header
        is opened write-only, so the description is injected as the comment goes
        out rather than spliced into the file afterwards.
        """
        self._desc_lines = desc_lines(node)
        self._desc_markers = (f"\n// {self.get_friendly_name(node)}\n",)

    def enter_Field(self, node: FieldNode) -> None:
        # A field has no comment of its own. Its description belongs above the
        # field's first macro and, where bitfield structs are generated, above
        # its struct member. Both are the next matching line written.
        lines = desc_lines(node)
        if lines:
            self._desc_lines = lines
            prefix = self.get_node_prefix(node.parent).upper()
            self._desc_markers = (
                f"#define {prefix}__{node.inst_name.upper()}_bm ",
                f"uint{node.parent.get_property('regwidth')}_t {kwf(node.inst_name)} :",
            )

    def enter_Reg(self, node: RegNode) -> Optional[WalkerAction]:
        # enter_Reg runs before the register's fields are walked, so the
        # register's description is in place before a field sets its own.
        self._describe(node)
        return super().enter_Reg(node)

    def enter_AddressableComponent(self, node: AddressableNode) -> None:
        # Registers describe themselves in enter_Reg; this covers the structs
        # and memories, whose path comment the stock generator writes on the way
        # out. One such comment is pending at a time.
        if not isinstance(node, RegNode):
            self._describe(node)


class Exporter(CHeaderExporter):
    """The stock c-header command, with descriptions in the generated header."""

    def do_export(self, top_node, options) -> None:
        # HeaderGenerator is a module global the stock exporter instantiates
        # directly, with no constructor argument to override it.
        cheader_exporter.HeaderGenerator = DescribedHeaderGenerator  # type: ignore[misc]
        try:
            super().do_export(top_node, options)
        finally:
            cheader_exporter.HeaderGenerator = HeaderGenerator  # type: ignore[misc]
