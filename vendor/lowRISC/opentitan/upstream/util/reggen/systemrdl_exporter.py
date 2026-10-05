# Copyright lowRISC contributors (OpenTitan project).
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0
#

"""Generate a SystemRDL description of the block"""

from dataclasses import dataclass
from typing import TextIO

from reggen.ip_block import IpBlock
from reggen.reg_block import RegBlock
from reggen.register import Register
from reggen.multi_register import MultiRegister
from reggen.window import Window
from reggen.field import Field
from reggen.access import SWAccess, HWAccess, HwAccess
from reggen.exporter import Exporter
from reggen.systemrdl.udp import register_udps

import systemrdl.component
from systemrdl import RDLCompiler  # type: ignore[attr-defined]
from systemrdl.messages import FileSourceRef  # type: ignore[attr-defined]
from systemrdl.importer import RDLImporter
from systemrdl.component import Addrmap
from systemrdl.rdltypes import AccessType, OnReadType, OnWriteType  # type: ignore[attr-defined]
from peakrdl_systemrdl import exporter


@dataclass
class HWAccess2Systemrdl:
    inner: HWAccess

    # Maps reggen hardware access property to SystemRDL properties. Each line in this table is
    # a set of RDL properties where:
    #    hw: Hardware read and write access
    MAP = {
        HwAccess.HRO: {"hw": AccessType.r},
        HwAccess.HRW: {"hw": AccessType.rw},
        HwAccess.HWO: {"hw": AccessType.w},
        HwAccess.NONE: {"hw": AccessType.na},
    }

    def export(self) -> dict[str, object]:
        return self.MAP[self.inner.value[1]]


@dataclass
class SWAccess2Systemrdl:
    inner: SWAccess

    # Maps reggen software access property to SystemRDL properties. Each line in this table is
    # a set of RDL properties where:
    #   sw: Software read and write access.
    #   onread: Side effect when software reads.
    #   onwrite: Side effect when software writes.
    MAP = {
        "ro": {"sw": AccessType.r},
        "rw": {"sw": AccessType.rw},
        "wo": {"sw": AccessType.w},
        "rc": {"sw": AccessType.rw, "onread": OnReadType.rclr},
        "r0w1c": {"sw": AccessType.w, "onwrite": OnWriteType.woclr},
        "rw1c": {"sw": AccessType.rw, "onwrite": OnWriteType.woclr},
        "rw0c": {"sw": AccessType.rw, "onwrite": OnWriteType.wzc},
        "rw1s": {"sw": AccessType.rw, "onwrite": OnWriteType.woset},
        "none": {"sw": AccessType.na},
    }

    def export(self) -> dict[str, object]:
        return self.MAP[self.inner.key]


@dataclass
class Field2Systemrdl:
    inner: Field
    importer: RDLImporter
    uppercase_name: bool = False
    name_override: str | None = None

    def _get_mubi_name(self) -> str:
        alignment = 4
        aligned_width = (self.inner.bits.width() + alignment - 1) & ~(alignment - 1)
        return f"MultiBitBool{aligned_width}"

    def export(self) -> systemrdl.component.Field:
        rdl_t = self.importer.create_field_definition(self.inner.name)
        name = self.name_override or self.inner.name
        name = name.upper() if self.uppercase_name else name
        field = self.importer.instantiate_field(
            rdl_t, name, self.inner.bits.lsb, self.inner.bits.width()
        )

        swaccess = SWAccess2Systemrdl(self.inner.swaccess).export()
        self.importer.assign_property(field, "sw", swaccess["sw"])
        if "onread" in swaccess:
            self.importer.assign_property(field, "onread", swaccess["onread"])
        if "onwrite" in swaccess:
            self.importer.assign_property(field, "onwrite", swaccess["onwrite"])

        hwaccess = HWAccess2Systemrdl(self.inner.hwaccess).export()
        self.importer.assign_property(field, "hw", hwaccess["hw"])

        if self.inner.resval is not None:
            self.importer.assign_property(field, "reset", self.inner.resval)

        if self.inner.hwqe:
            self.importer.assign_property(field, "swmod", self.inner.hwqe)

        if self.inner.desc:
            self.importer.assign_property(field, "desc", self.inner.desc)

        if self.inner.mubi:
            mubi_enum_name = self._get_mubi_name()
            enum = self.importer.compiler.namespace.lookup_type(mubi_enum_name)
            self.importer.assign_property(field, "encode", enum)

        return field


@dataclass
class Window2Systemrdl:
    inner: Window
    importer: RDLImporter
    arrayed: bool = False

    def export(self) -> systemrdl.component.Mem:
        rdl_mem_t = self.importer.create_mem_definition(self.inner.name)
        bytes_per_entry = self.inner.size_in_bytes // self.inner.items
        self.importer.assign_property(rdl_mem_t, "memwidth", bytes_per_entry * 8)
        if self.arrayed:
            return self.importer.instantiate_mem(
                rdl_mem_t, self.inner.name, self.inner.offset, [self.inner.items]
            )
        self.importer.assign_property(rdl_mem_t, "mementries", self.inner.items)
        return self.importer.instantiate_mem(rdl_mem_t, self.inner.name, self.inner.offset, None)


class Register2Systemrdl:
    inner: Register
    importer: RDLImporter
    stride: int | None = None
    count: int | None = None
    reg_name: str | None = None
    uppercase_fields: bool
    field_name_override: str | None

    def __init__(
        self,
        reg: MultiRegister | Register,
        importer: RDLImporter,
        base_multireg_name: bool,
        base_multireg_field_names: bool,
        uppercase_fields: bool,
        field_name_override: str | None = None,
    ):
        self.importer = importer
        self.uppercase_fields = uppercase_fields
        self.field_name_override = field_name_override
        if isinstance(reg, Register):
            self.inner = reg
        elif isinstance(reg, MultiRegister):
            self.inner = reg.cregs[0]
            self.stride = reg.stride
            self.count = len(reg.cregs)
            self.reg_name = reg.name if base_multireg_name else self.inner.name
            if base_multireg_field_names and len(self.inner.fields) == 1:
                self.field_name_override = reg.name

    def export(self) -> systemrdl.component.Reg:
        name = self.reg_name or self.inner.name
        reg_type = self.importer.create_reg_definition(name)
        for rfield in self.inner.fields:
            self.importer.add_child(
                reg_type,
                Field2Systemrdl(
                    rfield,
                    self.importer,
                    self.uppercase_fields,
                    self.field_name_override,
                ).export(),
            )

        reg_type.external = self.inner.hwext

        if self.inner.hwre:
            self.importer.assign_property(reg_type, "hwre", self.inner.hwre)

        if self.inner.shadowed:
            self.importer.assign_property(reg_type, "shadowed", self.inner.shadowed)

        reg = self.importer.instantiate_reg(
            reg_type,
            name,
            self.inner.offset,
            [self.count] if self.count else None,
            self.stride if self.stride else None,
        )
        return reg


@dataclass
class RegBlock2Systemrdl:
    inner: RegBlock
    importer: RDLImporter
    base_multireg_names: bool
    base_multireg_field_names: bool
    flatten_multiregs: bool
    uppercase_fields: bool
    arrayed_windows: bool

    def export(self, target: Addrmap | None = None) -> Addrmap | None:
        # An unnamed interface has no architectural hierarchy level of its
        # own; when the caller provides a target addrmap, populate it
        # directly instead of wrapping the registers in an inner addrmap
        # instance (which would otherwise be named "none").
        if target is not None:
            rdl_addrmap = target
        else:
            name = self.inner.name or "none"
            rdl_addrmap_t = self.importer.create_addrmap_definition(name)
            rdl_addrmap = self.importer.instantiate_addrmap(rdl_addrmap_t, name, 0)

        # registers and multiregs
        for reg in self.inner.registers:
            self.importer.add_child(
                rdl_addrmap,
                Register2Systemrdl(
                    reg,
                    self.importer,
                    self.base_multireg_names,
                    self.base_multireg_field_names,
                    self.uppercase_fields,
                ).export(),
            )

        # multiregs
        for mreg in self.inner.multiregs:
            regs = mreg.cregs if self.flatten_multiregs else [mreg]
            for reg in regs:
                field_name_override = None
                if self.flatten_multiregs and len(mreg.cregs[0].fields) == 1:
                    field_name_override = mreg.cregs[0].fields[0].name
                self.importer.add_child(
                    rdl_addrmap,
                    Register2Systemrdl(
                        reg,
                        self.importer,
                        self.base_multireg_names,
                        self.base_multireg_field_names,
                        self.uppercase_fields,
                        field_name_override,
                    ).export(),
                )

        # windows
        for window in self.inner.windows:
            self.importer.add_child(
                rdl_addrmap,
                Window2Systemrdl(window, self.importer, self.arrayed_windows).export(),
            )

        nonempty = bool(
            len(self.inner.registers) + len(self.inner.multiregs) + len(self.inner.windows)
        )
        return rdl_addrmap if nonempty else None


@dataclass
class IpBlock2Systemrdl:
    inner: IpBlock
    importer: RDLImporter
    base_multireg_names: bool
    base_multireg_field_names: bool
    flatten_multiregs: bool
    uppercase_fields: bool
    arrayed_windows: bool
    include_metadata: bool

    def export(self) -> Addrmap | None:
        num_children = 0

        rdl_addrmap = self.importer.create_addrmap_definition(self.inner.name)
        if self.include_metadata and self.inner.human_name:
            self.importer.assign_property(rdl_addrmap, "name", self.inner.human_name)
        if self.include_metadata and self.inner.one_line_desc:
            self.importer.assign_property(rdl_addrmap, "desc", self.inner.one_line_desc)

        for rb in self.inner.reg_blocks.values():
            # Flatten the unnamed interface into the block addrmap; named
            # interfaces keep their own addrmap level.
            target = rdl_addrmap if not rb.name else None
            rdl_rb = RegBlock2Systemrdl(
                rb,
                self.importer,
                self.base_multireg_names,
                self.base_multireg_field_names,
                self.flatten_multiregs,
                self.uppercase_fields,
                self.arrayed_windows,
            ).export(target)

            # Skip empty interfaces
            if rdl_rb is None:
                continue

            if target is None:
                self.importer.add_child(rdl_addrmap, rdl_rb)
            num_children += 1

        if num_children > 1:
            rdl_addrmap.properties["bridge"] = True

        return rdl_addrmap if num_children else None


class SystemrdlExporter(Exporter):
    def __init__(
        self,
        block: IpBlock,
        *,
        base_multireg_names: bool = True,
        base_multireg_field_names: bool = False,
        flatten_multiregs: bool = False,
        uppercase_fields: bool = False,
        arrayed_windows: bool = False,
        include_metadata: bool = True,
        include_guard: bool = True,
        include_udp: bool = True,
    ):
        super().__init__(block)
        self.base_multireg_names = base_multireg_names
        self.base_multireg_field_names = base_multireg_field_names
        self.flatten_multiregs = flatten_multiregs
        self.uppercase_fields = uppercase_fields
        self.arrayed_windows = arrayed_windows
        self.include_metadata = include_metadata
        self.include_guard = include_guard
        self.include_udp = include_udp

    def export(self, outfile: TextIO) -> int:
        comp = RDLCompiler()
        register_udps(comp)

        imp = RDLImporter(comp)
        imp.default_src_ref = FileSourceRef(outfile.name)

        rdl_addrmap = IpBlock2Systemrdl(
            self.block,
            imp,
            self.base_multireg_names,
            self.base_multireg_field_names,
            self.flatten_multiregs,
            self.uppercase_fields,
            self.arrayed_windows,
            self.include_metadata,
        ).export()
        if rdl_addrmap is None:
            raise RuntimeError("Block has no registers or windows.")

        imp.register_root_component(rdl_addrmap)

        # At this point, we actually have to close outfile and then pass its path
        # to exp.export (which expects a path rather than a stream).
        outfile.close()

        exporter.SystemRDLExporter().export(comp.elaborate(), outfile.name)

        if not self.include_guard and not self.include_udp:
            return 0

        guard_name = f"_{self.block.name.upper()}_RDL_DEFINED"
        with open(outfile.name, encoding="utf-8") as handle:
            content = handle.read()
        with open(outfile.name, "w", encoding="utf-8") as handle:
            if self.include_guard:
                handle.write(f"`ifndef {guard_name}\n")
                handle.write(f"`define {guard_name}\n\n")
            if self.include_udp:
                handle.write('`include "opentitan_udps.rdl"\n\n')
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
            if self.include_guard:
                handle.write(f"\n`endif // {guard_name}\n")

        return 0
