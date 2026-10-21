# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""What the RDL field contract lets a register walk do.

Every function here reads only the ``FieldSpec`` records of a ``RegInst``: the
software and hardware access, the write and read side effects, ``singlepulse``,
``volatile`` and the constant reset. Anything the RDL does not state -- a write
that re-routes the fabric, a FIFO behind a data port, a lock that freezes the
block -- is not derived here and stays a named entry in an ``ExclusionSet``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from enum import Enum

from .regmodel import FieldSpec, RegInst

# Reserved field names as the RDL sources spell them: rsvd, rsvd0, rsvd_0, Rsvd3116,
# reserved, RESERVED_7_3. A real field that merely contains the word, such as
# test_reserved, is not matched.
RESERVED_NAME = re.compile(r"^(?:rsvd|reserved)(?:_?\d+(?:_\d+)?)?$", re.IGNORECASE)

_WORD = 0xFFFF_FFFF
_NO_READBACK = "sw=w; a read does not return storage"


class FieldClass(Enum):
    """One property of a field's access contract; a field carries a set of them."""

    RO = "sw=r"
    RW = "sw=rw"
    WO = "sw=w"
    WRITE_ONCE = "write-once"
    W1C = "woclr"
    W1S = "woset"
    W0C = "wzc"
    W0S = "wzs"
    WSET = "wset"
    WCLR = "wclr"
    WOT = "wot"
    WZT = "wzt"
    WUSER = "wuser"
    RC = "rclr"
    RS = "rset"
    RUSER = "ruser"
    PULSE = "singlepulse"
    HW_DRIVEN = "volatile"
    UNRESET = "unreset"


_SW: dict[str, frozenset[FieldClass]] = {
    "rw": frozenset({FieldClass.RW}),
    "r": frozenset({FieldClass.RO}),
    "w": frozenset({FieldClass.WO}),
    "rw1": frozenset({FieldClass.RW, FieldClass.WRITE_ONCE}),
    "w1": frozenset({FieldClass.WO, FieldClass.WRITE_ONCE}),
    "na": frozenset(),
}
_ONWRITE = {
    c.value: c
    for c in (
        FieldClass.W1C,
        FieldClass.W1S,
        FieldClass.W0C,
        FieldClass.W0S,
        FieldClass.WSET,
        FieldClass.WCLR,
        FieldClass.WOT,
        FieldClass.WZT,
        FieldClass.WUSER,
    )
}
_ONREAD = {c.value: c for c in (FieldClass.RC, FieldClass.RS, FieldClass.RUSER)}


def classify_field(field: FieldSpec) -> frozenset[FieldClass]:
    """The access classes of one field; raises on an access value the RDL has no name for."""
    try:
        classes = set(_SW[field.sw])
        if field.onwrite:
            classes.add(_ONWRITE[field.onwrite])
        if field.onread:
            classes.add(_ONREAD[field.onread])
    except KeyError as exc:
        raise ValueError(f"field {field.name}: unknown access property {exc}") from exc
    if field.singlepulse:
        classes.add(FieldClass.PULSE)
    if field.volatile:
        classes.add(FieldClass.HW_DRIVEN)
    if field.reset is None:
        classes.add(FieldClass.UNRESET)
    return frozenset(classes)


def is_reserved(field: FieldSpec) -> bool:
    return RESERVED_NAME.match(field.name) is not None


def sw_readable(field: FieldSpec) -> bool:
    return field.sw in ("rw", "r", "rw1")


def sw_writable(field: FieldSpec) -> bool:
    return field.sw in ("rw", "w", "rw1", "w1")


def is_plain_rw(field: FieldSpec) -> bool:
    """Software-writable with a readback the contract pins to the written value."""
    return (
        field.sw == "rw"
        and not field.volatile
        and not field.onwrite
        and not field.onread
        and not field.singlepulse
    )


def has_static_reset(field: FieldSpec) -> bool:
    """Readable, with a constant reset that survives until software writes it."""
    return sw_readable(field) and not field.volatile and field.reset is not None


@dataclass(frozen=True)
class RegMasks:
    """Bit masks of one register, each the union of the fields with one property."""

    storage: int  # every field bit
    sw_usable: int  # storage minus reserved-named fields and fields with no software view
    plain_rw: int  # is_plain_rw fields
    static_reset: int  # has_static_reset fields
    unreset: int  # fields with no constant reset
    reserved: int  # storage outside sw_usable
    unimplemented: int  # bits of the register width that no field occupies
    write_destructive: int  # fields with an onwrite modifier: a write-back does not restore them
    read_destructive: int  # fields with an onread side effect


def reg_masks(reg: RegInst) -> RegMasks:
    storage = sw_usable = plain_rw = static = unreset = wdest = rdest = 0
    for field in reg.fields:
        storage |= field.mask
        if not is_reserved(field) and field.sw != "na":
            sw_usable |= field.mask
        if is_plain_rw(field):
            plain_rw |= field.mask
        if has_static_reset(field):
            static |= field.mask
        if field.reset is None:
            unreset |= field.mask
        if field.onwrite:
            wdest |= field.mask
        if field.onread:
            rdest |= field.mask
    full = (1 << reg.width) - 1
    return RegMasks(
        storage=storage,
        sw_usable=sw_usable,
        plain_rw=plain_rw,
        static_reset=static,
        unreset=unreset,
        reserved=storage & ~sw_usable,
        unimplemented=full & ~storage,
        write_destructive=wdest,
        read_destructive=rdest,
    )


@dataclass(frozen=True)
class WordView:
    """One 32-bit word of a register: its bus address, reset value and masks."""

    addr: int
    index: int
    reset: int
    masks: RegMasks


def word_view(reg: RegInst, word: int = 0) -> WordView:
    """The 32-bit word ``word`` of ``reg``; a 32-bit register is its own word 0."""
    if not 0 <= word < reg.words:
        raise IndexError(f"{reg.symbol} spans {reg.words} word(s); word {word} does not exist")
    shift = 32 * word
    masks = reg_masks(reg)
    sliced = {f.name: (getattr(masks, f.name) >> shift) & _WORD for f in fields(RegMasks)}
    return WordView(reg.addr + 4 * word, word, (reg.reset >> shift) & _WORD, RegMasks(**sliced))


def reset_reason(reg: RegInst) -> str | None:
    """Why a reset read-compare on ``reg`` proves nothing, or None when it is a real row.

    Every arm is derived from the field contract: a register software cannot read
    returns no storage; a read-only register with no declared reset is driven by
    hardware; a register whose every storage bit lacks a constant reset has only
    placeholder zeros to compare against. A volatile field is not an arm: its
    reset value is still the value a read returns before hardware moves it, and
    ``reg_masks(reg).static_reset`` names the bits a walk may pin without that
    reservation.
    """
    if not any(sw_readable(f) for f in reg.fields):
        return _NO_READBACK
    if all(f.sw == "r" for f in reg.fields) and all(f.reset is None for f in reg.fields):
        return "sw=r with no declared reset; hardware drives the value"
    masks = reg_masks(reg)
    if masks.storage & ~masks.unreset == 0:
        return "no field with an RDL reset; the default is a placeholder"
    return None


def write_reason(
    reg: RegInst, mask: int | None = None, *, require_reset: bool = True
) -> str | None:
    """Why a write of ``mask`` bits and a readback of them proves nothing, or None.

    ``mask`` defaults to the software-usable bits. A walk that writes only
    ``reg_masks(reg).plain_rw`` passes that mask and gets None wherever the
    register has plain storage at all. The arms, in order: the reset arms; no
    software-usable bit; no writable field under the mask; then the first field
    under the mask that is read-only, write-modified, read-modified, singlepulse
    or volatile, because the written value does not come back from such a bit.

    With ``require_reset`` the reset arms apply, so plain storage with no
    declared reset is refused along with its reset compare. A walk that proves
    write/readback on such storage (the SMC field sweep does) passes
    ``require_reset=False``; only the no-readable-field arm then remains, since
    without a read there is no readback.
    """
    why = reset_reason(reg)
    if why is not None and (require_reset or why == _NO_READBACK):
        return why
    masks = reg_masks(reg)
    if mask is None:
        mask = masks.sw_usable
    if mask == 0:
        return "no software-usable field"
    under = [f for f in reg.fields if f.mask & mask]
    if not any(sw_writable(f) for f in under):
        return "sw=r; a write does not reach storage"
    for predicate, why in (
        (
            lambda f: not sw_writable(f),
            "sw=r field inside the mask; the written value does not land",
        ),
        (lambda f: bool(f.onwrite), "{} field inside the mask; a write does not land as written"),
        (lambda f: bool(f.onread), "{} field inside the mask; a read changes the value"),
        (
            lambda f: f.singlepulse,
            "singlepulse field inside the mask; the written value self-clears",
        ),
        (lambda f: f.volatile, "volatile field inside the mask; hardware may change the value"),
    ):
        for field in under:
            if predicate(field):
                return why.format(field.onwrite or field.onread)
    return None
