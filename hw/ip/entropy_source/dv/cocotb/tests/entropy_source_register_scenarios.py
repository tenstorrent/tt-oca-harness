# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register metadata helpers derived from the generated Python collateral."""

from __future__ import annotations

from dataclasses import dataclass

import entropy_source_reg as reg


@dataclass(frozen=True)
class RegisterSpec:
    name: str
    addr: int
    default: int
    readable: bool
    writable_mask: int
    readback_mask: int
    write_one_clear: bool


def register_specs() -> list[RegisterSpec]:
    specs = []
    for symbol, addr in vars(reg).items():
        if symbol.startswith("ENTROPY_SOURCE_") or not symbol.endswith("_REG_ADDR"):
            continue
        name = symbol.removesuffix("_REG_ADDR")
        access = getattr(reg, f"ENTROPY_SOURCE_{name}_REG_FIELD_ACCESS")
        default = getattr(reg, f"ENTROPY_SOURCE_{name}_REG_DEFAULT")
        union_type = getattr(reg, f"ENTROPY_SOURCE_{name}_reg_u")
        value = union_type()
        value.val = 0
        readable = False
        write_one_clear = False
        readback = union_type()
        readback.val = 0
        for field_name, sw, side_effect, _unused, _pulse in access:
            readable |= "r" in sw
            if "w" not in sw:
                continue
            write_one_clear |= side_effect == "woclr"
            field = field_name.lower()
            width = next(bits for member, _ctype, bits in value.f._fields_ if member == field)
            setattr(value.f, field, (1 << width) - 1)
            if "r" in sw:
                setattr(readback.f, field, (1 << width) - 1)
        specs.append(
            RegisterSpec(
                name=name,
                addr=addr,
                default=default,
                readable=readable,
                writable_mask=int(value.val),
                readback_mask=int(readback.val),
                write_one_clear=write_one_clear,
            )
        )
    return sorted(specs, key=lambda spec: spec.addr)
