# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Local peakrdl regblock exporter: an out-of-range-only address error, and the window's width.

Stock ``--err-if-bad-addr`` answers SLVERR for every address that misses a
register, so the gaps between registers error too. ``--err-if-out-of-range``
answers SLVERR only at or past the block's size, so a gap reads 0 and drops its
write with OKAY.

``--windows`` names the file tools/regs/rdlwindows.py writes. A block it lists
under ``addr_widths`` gets that address width, as ``--addr-width`` would give it.

The stock module template has no hook for the decode, so the exporter patches
its source as it loads and fails if the anchor it patches is gone. Registered as
``regblock-range`` from hw/common/regs/peakrdl.toml.in.
"""

from __future__ import annotations

import json
from pathlib import Path

import jinja2 as jj
import peakrdl_regblock
from common.windows import type_name
from peakrdl_regblock import __peakrdl__ as regblock_plugin
from peakrdl_regblock.__peakrdl__ import Exporter as RegblockPlugin
from peakrdl_regblock.exporter import RegblockExporter

_TEMPLATE = "module_tmpl.sv"
_ANCHOR = "{{address_decode.get_implementation()|indent(8)}}"
# Overwrites the per-register hits the stock decode ORs into is_valid_addr.
_RANGE_CHECK = """
    {%- if ds.top_node.size < 2 ** ds.addr_width %}
        is_valid_addr = cpuif_addr < {{SVInt(ds.top_node.size, ds.addr_width)}};
    {%- else %}
        is_valid_addr = '1;
    {%- endif %}"""


def _range_checked_module(name: str) -> str | None:
    if name != _TEMPLATE:
        return None
    source = (Path(peakrdl_regblock.__file__).parent / _TEMPLATE).read_text()
    if source.count(_ANCHOR) != 1:
        raise RuntimeError(
            f"peakrdl-regblock {_TEMPLATE} no longer has exactly one '{_ANCHOR}';"
            " update tools/regs/regblock_range.py for this release"
        )
    return source.replace(_ANCHOR, _ANCHOR + _RANGE_CHECK)


class RangeCheckedRegblockExporter(RegblockExporter):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.jj_env.loader = jj.ChoiceLoader(
            [jj.FunctionLoader(_range_checked_module), self.jj_env.loader]
        )


class Exporter(RegblockPlugin):
    """The stock regblock command, plus --err-if-out-of-range and --windows."""

    def add_exporter_arguments(self, arg_group) -> None:
        super().add_exporter_arguments(arg_group)
        arg_group.add_argument(
            "--err-if-out-of-range",
            action="store_true",
            default=False,
            help="""Generate CPUIF error response only for an address at or past
            the end of the block; gaps between registers answer OKAY.""",
        )
        arg_group.add_argument(
            "--windows",
            metavar="FILE",
            help="""Take the address width from the windows file rdlwindows.py
            writes, unless --addr-width gives one.""",
        )

    def do_export(self, top_node, options) -> None:
        if options.windows and options.addr_width is None:
            record = json.loads(Path(options.windows).read_text(encoding="utf-8"))
            options.addr_width = record["addr_widths"].get(type_name(top_node))
        if not options.err_if_out_of_range:
            super().do_export(top_node, options)
            return
        if options.err_if_bad_addr or options.err_if_bad_rw:
            raise ValueError("--err-if-out-of-range excludes --err-if-bad-addr and --err-if-bad-rw")
        options.err_if_bad_addr = True
        # The stock plugin instantiates this module global directly.
        regblock_plugin.RegblockExporter = RangeCheckedRegblockExporter  # type: ignore[misc]
        try:
            super().do_export(top_node, options)
        finally:
            regblock_plugin.RegblockExporter = RegblockExporter  # type: ignore[misc]
