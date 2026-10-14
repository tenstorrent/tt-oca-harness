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
registered as ``c-header-desc`` from hw/common/regs/peakrdl.toml.in, which rules.mk
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
    """The stock generator, with each node's description beside the line naming it.

    Before calling the stock method that names a node, the line it will write is
    recorded with the node's description; ``write`` emits the description when
    that exact line goes out. A path comment is followed by its description, and
    a field macro or struct member is preceded by its field's.
    """

    def __init__(self, ds) -> None:
        super().__init__(ds)
        self._annotated: dict[str, list[str]] = {}

    def write(self, s: str) -> None:
        lines = [f"// {line}\n" for line in self._annotated.pop(s, [])]
        after = s.startswith("\n// ")
        for out in [s, *lines] if after else [*lines, s]:
            super().write(out)

    def _annotate(self, line: str, node: Node) -> None:
        if lines := desc_lines(node):
            self._annotated[line] = lines

    def _annotate_path(self, node: Node) -> None:
        self._annotate(f"\n// {self.get_friendly_name(node)}\n", node)

    def enter_Reg(self, node: RegNode) -> Optional[WalkerAction]:
        self._annotate_path(node)
        prefix = self.get_node_prefix(node).upper()
        for field in node.fields():
            mask = ((1 << field.width) - 1) << field.low
            self._annotate(f"#define {prefix}__{field.inst_name.upper()}_bm {mask:#x}\n", field)
        return super().enter_Reg(node)

    def write_bitfields(self, grp_name: str, regwidth: int, fields: list[FieldNode]) -> None:
        for field in fields:
            self._annotate(f"uint{regwidth}_t {kwf(field.inst_name)} :{field.width:d};\n", field)
        super().write_bitfields(grp_name, regwidth, fields)

    def write_block(self, node: AddressableNode) -> None:
        self._annotate_path(node)
        super().write_block(node)

    def exit_Mem(self, node) -> None:
        self._annotate_path(node)
        super().exit_Mem(node)


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
