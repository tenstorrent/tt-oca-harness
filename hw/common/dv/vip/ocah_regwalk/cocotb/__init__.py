# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Public API of ocah_regwalk.

regmodel    ``load_model`` reads a generated ``<top>_reg.py`` into a ``RegModel``
            of windows, ``RegInst`` instances and ``FieldSpec`` records.
access      ``classify_field``, ``reg_masks``, ``word_view``, ``reset_reason``
            and ``write_reason`` derive what a walk may do from the RDL contract.
exclusions  ``ExclusionSet`` keeps the hand-named exclusions a walk still needs,
            each with a reason, and accounts for every register it is given.
"""

from .access import (
    RESERVED_NAME,
    FieldClass,
    RegMasks,
    WordView,
    classify_field,
    has_static_reset,
    is_plain_rw,
    is_reserved,
    reg_masks,
    reset_reason,
    sw_readable,
    sw_writable,
    word_view,
    write_reason,
)
from .exclusions import ExclusionSet, Partition
from .regmodel import FieldSpec, RegInst, RegModel, Window, load_model

__all__ = [
    "RESERVED_NAME",
    "ExclusionSet",
    "FieldClass",
    "FieldSpec",
    "Partition",
    "RegInst",
    "RegMasks",
    "RegModel",
    "Window",
    "WordView",
    "classify_field",
    "has_static_reset",
    "is_plain_rw",
    "is_reserved",
    "load_model",
    "reg_masks",
    "reset_reason",
    "sw_readable",
    "sw_writable",
    "word_view",
    "write_reason",
]
