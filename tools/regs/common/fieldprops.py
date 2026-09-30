# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Neutral field-property extraction shared by every register exporter.

SystemRDL states a field's access side effects two ways: the explicit
``onwrite``/``onread`` enums, or the shorthand boolean properties (``woset``,
``woclr``, ``rset``, ``rclr``) that a compiler resolves to the same enums. Each
exporter used to re-derive this, and only ``rdljson`` guarded the illegal
``woset``+``woclr`` / ``rset``+``rclr`` pairing. ``extract_field_props`` resolves
it once and guards it for every caller.

The result carries the raw model values (enum names, integers, the reset object)
with no formatting, so JSON, SV, Python-header and doc exporters each render it
their own way.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FieldProps:
    sw: str  # software access enum name, e.g. "rw", "r", "w"
    onwrite: str  # "woset"/"woclr"/... enum name, or "" when the field has none
    onread: str  # "rclr"/"rset"/... enum name, or "" when the field has none
    singlepulse: bool
    woclr: bool  # raw woclr shorthand, reported standalone by the JSON model
    reset: object  # int, SignalNode, or None
    lsb: int
    msb: int


def extract_field_props(node) -> FieldProps:
    on_write = node.get_property("onwrite", default=None)
    if on_write is None:
        woset = node.get_property("woset")
        woclr = node.get_property("woclr")
        if woset and woclr:
            raise RuntimeError(f"field {node.inst_name} sets both woset and woclr")
        onwrite = "woset" if woset else ("woclr" if woclr else "")
    else:
        onwrite = on_write.name

    on_read = node.get_property("onread", default=None)
    if on_read is None:
        rset = node.get_property("rset")
        rclr = node.get_property("rclr")
        if rset and rclr:
            raise RuntimeError(f"field {node.inst_name} sets both rset and rclr")
        onread = "rset" if rset else ("rclr" if rclr else "")
    else:
        onread = on_read.name

    return FieldProps(
        sw=node.get_property("sw").name,
        onwrite=onwrite,
        onread=onread,
        singlepulse=bool(node.get_property("singlepulse")),
        woclr=bool(node.get_property("woclr")),
        reset=node.get_property("reset"),
        lsb=node.lsb,
        msb=node.msb,
    )
