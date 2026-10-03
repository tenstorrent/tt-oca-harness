# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plan the SMC toggle exclusions whose fact is stated for a whole signal or a bit window.

A class whose fact is about the signal itself -- a union view that aliases flops
another view already counts, a port that carries another graded signal
unchanged, a constant, a tie-off, or a net inside a unit graded on its ports --
names the signal whole: every bit, both directions. A class whose fact names
some bits of a signal names those bits, both directions. That is the pattern;
the rows written follow the graded run: only the bit-directions the run's raw
report leaves uncovered are written, so nothing a leaf covers leaves the score.
A row takes the whole signal where every bit-direction is uncovered and bit or
part selects with their direction otherwise. The rows belong to one graded run
and are regenerated from each; `--check` compares them against the run it is
given. The review classes of smc_reviewed_exclusions.toml are report-gated the
same way and are written by the other generators.

A row is written at MODULE scope when it holds for every instance of the
module and urg takes a toggle exclusion on the module's section, and at
INSTANCE scope otherwise: a fact about one instance, a module elaborated per
parameter set (urg takes no toggle exclusion on such a section), or a module
some of whose instances the fact does not reach. A module row keeps what the
module's report section, the union of its instances, leaves uncovered, and an
instance that leaves more uncovered gets the rest on an instance row. A signal
is owned by the first class that names it, in the order T1, the manifest's
units, then FACT_ORDER.

The ports-only units are planned here from the manifest's `[[unit]]` entries:
a unit root keeps the ports the run's report lists under Port Details, and its
other nets and every net of every instance beneath it are excluded while
uncovered.
"""

from __future__ import annotations

import re
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import smc_reviewed_exclusions as reviewed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
MODULE_OUT = HERE / "smc_toggle_module_exclusions.el"
INSTANCE_OUT = HERE / "smc_toggle_instance_exclusions.el"

Bit = reviewed.Bit


@dataclass(frozen=True)
class ToggleClass:
    """One class: its fact, its scope (design or bench) and what retires it."""

    id: str
    kind: str
    granularity: str
    summary: str
    fact: str
    retired_by: str


# T1 OPENTITAN-PORTS-ONLY: module -> the source the build compiles it from. The
# copyright line of each is checked at generation time and quoted in the file.
T1_UNITS: tuple[tuple[str, str], ...] = (
    ("i2c", "hw/ip/i2c/rtl/i2c.sv"),
    ("i2c_core", "hw/ip/i2c/rtl/i2c_core.sv"),
    ("i2c_controller_fsm", "hw/ip/i2c/rtl/i2c_controller_fsm.sv"),
    ("i2c_target_fsm", "hw/ip/i2c/rtl/i2c_target_fsm.sv"),
    ("i2c_bus_monitor", "hw/ip/i2c/rtl/i2c_bus_monitor.sv"),
    ("uart_16550", "hw/ip/uart/uart_16550/rtl/uart_16550.sv"),
    ("uart_core", "hw/ip/uart/uart_16550/rtl/uart_core.sv"),
    ("uart_rx", "hw/ip/uart/uart_16550/rtl/uart_rx.sv"),
    ("uart_tx", "hw/ip/uart/uart_16550/rtl/uart_tx.sv"),
    ("prim_clock_mux2", "hw/common/ocah_prim_generic/rtl/prim_clock_mux2.sv"),
)

# EFUSE-IMAGE-COPY: (module, prefix) whose `prefix.values` carries an image signal
# graded elsewhere unchanged. `efuse_shadow_regs.sv:766` assigns `shadow_efuse_o`
# from `shadow_efuse_masked`; `efuse_interface_controller.sv:771` and `:856` connect
# that port to the controller's `shadow_regs` and to `efuse_guard.shadow_regs_i`;
# `smc_efuse_wrapper.sv:273`, `smc_peripherals.sv:1061`, `smc.sv:861` and
# `smc_wrapper.sv:271` carry the controller's `shadow_regs_o` up unchanged.
IMAGE_COPIES: frozenset[tuple[str, str]] = frozenset(
    {
        ("efuse_shadow_regs", "shadow_efuse_o"),
        ("efuse_interface_controller", "shadow_regs"),
        ("efuse_guard", "shadow_regs_i"),
        ("smc_efuse_wrapper", "shadow_regs_o"),
        ("smc_peripherals", "shadow_regs_o"),
        ("smc", "shadow_regs_o"),
        ("smc_wrapper", "shadow_regs_o"),
    }
)

# EFUSE-FIELD-MAP-CONST: the modules `smc_efuse_wrapper.sv:268` passes
# `smc_efuse_pkg::EfuseFieldMap` to, directly or through the controller
# (`efuse_interface_controller.sv:757`, `:838`).
FIELD_MAP_MODULES = frozenset(
    {
        "efuse_interface_controller",
        "efuse_shadow_regs",
        "efuse_guard",
        "efuse_shadow_reg_access_control",
    }
)
FIELD_MAP = re.compile(r"^efuse_field_map_i\[\d+\]\.")

# VERSION-ID-CONST: the nets `smc_version_id_wrap.sv` drives from `prim_rev_cell`
# instances whose sources are tied to 1'b0 and 1'b1, and their copies into the
# chip_config register block (`smc_misc_wrap.sv:180-219`).
VERSION_NETS: frozenset[tuple[str, str]] = frozenset(
    {
        ("smc_version_id_wrap", "low"),
        ("smc_version_id_wrap", "high"),
        ("smc_version_id_wrap", "version_id_o"),
        ("smc_misc_wrap", "version_id"),
        ("smc_misc_wrap", "hwif_in.VERSION_LO.version_lo.next"),
        ("smc_misc_wrap", "hwif_in.VERSION_HI.version_hi.next"),
        ("chip_config_reg", "hwif_in.VERSION_LO.version_lo.next"),
        ("chip_config_reg", "hwif_in.VERSION_HI.version_hi.next"),
    }
)

ATOP = re.compile(r"(?:^|\.)aw\.atop$|(?:^|[._])aw_?atop(?:_[io])?$")

# EXT-IRQ-TIED: the nets that carry external interrupt sources 17 and up, which
# `tb_top.sv` ties to zero (`{(NumExtInterrupts-17){1'b0}}`), by (module,
# signal), and the per-bit cells of the synchronizer `smc_base.sv:351-358` passes
# them through, whose data nets carry nothing else.
EXT_IRQ_FIRST = 17
EXT_IRQ_LAST = 255
EXT_IRQ_NETS: frozenset[tuple[str, str]] = frozenset(
    {
        ("smc_wrapper", "smc_ext_interrupts_i"),
        ("smc", "smc_ext_interrupts_i"),
        ("smc_base", "ext_interrupts_i"),
        ("smc_base", "ext_interrupts_smc_clk"),
        ("smc_base", "cpu_interrupts_o"),
        ("smc", "cpu_interrupts"),
        ("smc_cpu_wrapper", "interrupts_i"),
        ("smc_4core_cpu", "interrupts_i"),
    }
)
# ERR-SLV-CONST: the nets that carry an axi_err_slv response unchanged
# (`axi_filter_wrap.sv:287-299`, `smc_input_fabric.sv:506-518`, `:566-578`); the
# error slave itself is a library cell the scope drops.
ERR_SLV_RESPONSES: frozenset[tuple[str, str]] = frozenset(
    {
        ("axi_filter_wrap", "err_slv_resp"),
        ("smc_input_fabric", "sys_err_slv_resp"),
        ("smc_input_fabric", "sep_err_slv_resp"),
    }
)
ERR_SLV_MEMBERS = ("b.user", "r.user", "r.data")
CLOCK_RESET = re.compile(r"^(?:clk|rst)\w*$")
EXT_IRQ_SYNC = re.compile(r"\.u_smc_base\.u_ext_interrupts_sync3\.u_sync3\[(\d+)\]$")

CLASSES: dict[str, ToggleClass] = {
    c.id: c
    for c in (
        ToggleClass(
            "T1-OPENTITAN-PORTS-ONLY",
            "design",
            "whole signal",
            "a unit of OpenTitan origin is graded on its ports; the nets it declares inside are excluded while uncovered",
            "this unit comes from OpenTitan, whose own verification covers its internals, so the "
            "package grades it on its ports and excludes the nets it declares inside while the "
            "run leaves them uncovered. Every unit "
            "that is not from OpenTitan keeps all of its nets in the toggle score. The source's "
            "copyright line is quoted in the block.",
            "the unit's source losing its OpenTitan origin, or the package grading OpenTitan "
            "internals",
        ),
        ToggleClass(
            "UNION-ALIAS",
            "design",
            "whole signal",
            "the fields and locks views of the packed union efuse_map_t alias the flops its values view counts",
            "efuse_map_t is a packed union (smc_efuse_pkg.sv:171-175), so urg lists the same 8192 "
            "flops under the values, fields and locks views; the fields and locks views of every "
            "efuse_map_t net are left out while uncovered and values carries each bit once.",
            "efuse_map_t ceasing to be a union",
        ),
        ToggleClass(
            "EFUSE-IMAGE-COPY",
            "design",
            "whole signal",
            "this port carries a shadow-image net, graded at its source, unchanged",
            "this port carries a shadow-image net unchanged: efuse_shadow_regs.sv:766 assigns "
            "shadow_efuse_o from shadow_efuse_masked, efuse_interface_controller.sv:771 and :856 "
            "connect it to shadow_regs and efuse_guard.shadow_regs_i, and smc_efuse_wrapper.sv:273, "
            "smc_peripherals.sv:1061, smc.sv:861 and smc_wrapper.sv:271 carry the controller's "
            "shadow_regs_o up without logic. The image stays graded on shadow_efuse_values, "
            "shadow_efuse.values, shadow_efuse_masked.values and the controller's shadow_regs_o.",
            "logic between a copy and its source, such as a mask or a gate added on the path",
        ),
        ToggleClass(
            "EFUSE-FIELD-MAP-CONST",
            "design",
            "whole signal",
            "efuse_field_map_i is the localparam EfuseFieldMap passed through ports and never changes",
            "smc_efuse_wrapper.sv:268 connects efuse_field_map_i to the localparam "
            "smc_efuse_pkg::EfuseFieldMap (smc_efuse_pkg.sv:246), and the controller passes it on "
            "unchanged (efuse_interface_controller.sv:757, :838); -cm_noconst does not prune a "
            "struct constant passed through ports, so the field map is listed while it never "
            "changes.",
            "a field map that is programmable or loaded from fuses",
        ),
        ToggleClass(
            "VERSION-ID-CONST",
            "design",
            "whole signal",
            "the version identifier comes from revision cells tied to constants",
            "smc_version_id_wrap.sv builds the version identifier from prim_rev_cell instances "
            "whose src_low_i and src_high_i are tied to 1'b0 and 1'b1 (prim_rev_cell.sv:13-17 "
            "copies them to lo_o and hi_o), and smc_misc_wrap.sv:180-219 copies it into the "
            "chip_config register block's hardware inputs; the scope drops prim_rev_cell, so the "
            "constant is not pruned.",
            "a version identifier driven from anything other than tied revision cells",
        ),
        ToggleClass(
            "ATOP-ZERO",
            "bench",
            "whole signal",
            "bench scope: no initiator of this bench issues an atomic, so AWATOP stays zero",
            "bench scope for the inbound ports: no AXI initiator in this bench issues an atomic. "
            "hw/sys/smc/dv/tb/tb_top.sv ties AWATOP to zero on the SEP, system and JTAG ports "
            "(:858, :911, :964), the CPU MMIO port ties it (smc_4core_cpu.sv:517), the iDMA "
            "legalizer (idma_generated.sv:4025), the zeroer (zeroer.sv:454) and the log engine's "
            "axi_lite_to_axi (axi_lite_to_axi.sv:40-47, default zero) issue none, and every SMC "
            "fabric is built with ATOPs or AtopSupport at zero (smc_local_xbar.sv:179, "
            "smc_input_fabric.sv:317, smc_output_fabric.sv:233).",
            "an initiator that issues atomics, or a bench port that drives AWATOP",
        ),
        ToggleClass(
            "EXT-IRQ-TIED",
            "bench",
            "bit window",
            "bench scope: tb_top.sv ties external interrupt sources 17 to 255 to zero",
            "bench scope: hw/sys/smc/dv/tb/tb_top.sv:1294 drives smc_ext_interrupts_i[255:17] "
            "with {(NumExtInterrupts-17){1'b0}}, so external interrupt sources 17 to 255 are "
            "zero; smc_base.sv:351-364 synchronizes them through u_ext_interrupts_sync3 into "
            "cpu_interrupts_o[255:0], which reaches the CPU unchanged. Bits [255:17] of those "
            "nets and the data nets of the synchronizer cells for those bits are left out; their "
            "clocks and resets, and sources 2 to 16, which have a bench pin, stay graded.",
            "bench pins on external interrupt sources 17 and up",
        ),
        ToggleClass(
            "PARTIAL-VECTOR",
            "bench",
            "per bit, report-gated",
            "bench scope: the vector toggles on this bench; its untoggled bits wait on data values "
            "no enrolled leaf drives",
            "bench and stimulus scope: at least one bit-direction of this multi-bit payload vector "
            "toggles in the graded run, which shows the net is driven and observed on this bench; "
            "its remaining bit-directions depend on the address, data or user values the enrolled "
            "leaves happen to drive, so they are a stimulus-value gap, not a connectivity or logic "
            "gap. Single-bit nets, vectors with no covered bit-direction, vectors whose bit "
            "identity carries meaning (handshakes, enables, strobes and masks, selects, interrupt "
            "and error vectors, response and attribute codes, IDs, FSM state) and the eFuse image "
            "stay graded. Reviewer: DE + DV peer.",
            "a leaf that drives those values, or the vector becoming fully covered",
        ),
        ToggleClass(
            "ERR-SLV-CONST",
            "design",
            "whole signal",
            "an axi_err_slv response carries a zero user and a constant read data",
            "axi_err_slv.sv:143-146 and :194-202 assign err_resp.b and err_resp.r '0 and then set "
            "only id, resp, data (the RespData parameter, 64'hCA11AB1EBADCAB1E by default, which "
            "no SMC instance overrides), last and valid, so b.user and r.user are zero and r.data "
            "is a constant on every net that carries the response unchanged: err_slv_resp in "
            "axi_filter_wrap (axi_filter_wrap.sv:287-299) and sys_err_slv_resp and "
            "sep_err_slv_resp in smc_input_fabric (smc_input_fabric.sv:506-518, :566-578). id, "
            "resp, last and valid stay graded. Reviewer: DE.",
            "an error slave that passes user or data through, or a RespData chosen per transaction",
        ),
    )
}

# PARTIAL-VECTOR: a vector whose leaf name carries one of these tokens has bit
# identity that means something -- a handshake, enable, strobe or mask lane, a
# select, an interrupt or error source, a response or attribute code, an ID or
# an FSM state -- so its untoggled bits are not a payload value gap.
MEANINGFUL = frozenset(
    "valid vld ready rdy en ena enable enables we re wen ren wr rd strb strobe wmask mask be "
    "biten sel select gnt grant req ack irq intr interrupt interrupts err error errors resp "
    "status state st fsm onehot lock locks cmd opcode op mode prot cache burst size len qos "
    "region atop id last clk rst reset hit pass".split()
)
# PeakRDL and register-struct members name the field above them.
FIELD_MEMBER = frozenset({"next", "value", "d", "q"})
SUFFIX = re.compile(r"_(?:i|o|q|d|n|ni|no|r|reg|nxt|next|value)$")
# The eFuse image stays graded: a leaf that senses a patterned preload toggles it.
IMAGE_VECTOR = re.compile(r"(?:^|\.)values$|^shadow_efuse_values")


def meaningful(signal: str) -> bool:
    """Whether a vector's leaf name says its bit identity carries meaning."""
    parts = [re.sub(r"\[\d+\]", "", c) for c in signal.split(".")]
    while len(parts) > 1 and parts[-1] in FIELD_MEMBER:
        parts.pop()
    leaf = parts[-1]
    while SUFFIX.search(leaf):
        leaf = SUFFIX.sub("", leaf)
    return bool(set(leaf.lower().split("_")) & MEANINGFUL)


# Class order: the first class that names a signal owns it. The unit classes
# from the manifest are inserted after T1.
FACT_ORDER = (
    "UNION-ALIAS",
    "EFUSE-IMAGE-COPY",
    "EFUSE-FIELD-MAP-CONST",
    "VERSION-ID-CONST",
    "ATOP-ZERO",
    "EXT-IRQ-TIED",
    "ERR-SLV-CONST",
)

COPYRIGHT = re.compile(r"^\s*//\s*Copyright.*?(lowRISC|OpenTitan).*$", re.I | re.M)
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
PORT_NAME = re.compile(r"([A-Za-z_][A-Za-z_0-9$]*)\s*(?:\[[^\]]*\]\s*)*(?:=[^,]*)?$")


def copyright_line(path: Path) -> str:
    """The lowRISC or OpenTitan copyright line of a source, or stop."""
    head = "\n".join(path.read_text(errors="replace").splitlines()[:12])
    m = COPYRIGHT.search(head)
    if m is None:
        raise SystemExit(f"{path} carries no lowRISC or OpenTitan copyright line")
    return m.group(0).strip().lstrip("/").strip()


def _close(text: str, start: int) -> int:
    depth, j = 0, start
    while j < len(text):
        depth += text[j] == "("
        depth -= text[j] == ")"
        if depth == 0:
            return j
        j += 1
    return j


def module_ports(path: Path, module: str) -> set[str]:
    """The names in a module's ANSI port list."""
    text = COMMENTS.sub("", path.read_text(errors="replace"))
    m = re.search(r"\bmodule\s+(?:automatic\s+)?" + re.escape(module) + r"\b", text)
    if m is None:
        raise SystemExit(f"{path} declares no module {module}")
    hash_pos, start = text.find("#", m.end()), text.find("(", m.end())
    if hash_pos != -1 and hash_pos < start:
        start = text.find("(", _close(text, text.find("(", hash_pos)) + 1)
    end = _close(text, start)
    ports: set[str] = set()
    depth, cur = 0, ""
    for c in text[start + 1 : end] + ",":
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            name = PORT_NAME.search(cur.strip())
            if name:
                ports.add(name.group(1))
            cur = ""
            continue
        cur += c
    return ports


def head_name(signal: str) -> str:
    """The declared name a toggle point belongs to: `a.b[3].c` -> `a`."""
    return signal.split(".")[0].split("[")[0]


def union_view(signal: str, signals: dict[str, str]) -> bool:
    """Whether a point sits under the fields or locks view of a net that also has values."""
    parts = signal.split(".")
    for i in range(1, len(parts)):
        if parts[i] in ("fields", "locks") and ".".join(parts[:i]) + ".values" in signals:
            return True
    return False


def window(lo: int, hi: int) -> str:
    return f" [{hi}:{lo}]"


@dataclass
class Row:
    """One toggle row: the owning class, the select (empty for the whole signal)."""

    cls: str
    select: str


@dataclass
class TogglePlan:
    """Whole-signal and bit-window rows by scope, and the bits each takes."""

    db: reviewed.Database
    rows: dict[tuple[str, str], dict[str, Row]] = field(default_factory=lambda: defaultdict(dict))

    def owned(self, kind: str, scope: str, sc: reviewed.Scope, signal: str) -> bool:
        if signal in self.rows.get((kind, scope), {}):
            return True
        if kind == "INSTANCE":
            up = self.db.module_scope(sc, "tgl")
            return up is not None and signal in self.rows.get(("MODULE", up), {})
        return False

    def add(self, kind: str, scope: str, signal: str, cls: str, select: str = "") -> None:
        """Write a row at MODULE scope where urg takes it, on each instance otherwise.

        A module row is not written where every instance already owns the signal.
        """
        sc = (self.db.modules if kind == "MODULE" else self.db.instances)[scope]
        if signal not in sc.signals:
            return
        if kind == "MODULE":
            members = self.db.members(scope, "tgl")
            if members and all(self.owned(k, s, i, signal) for k, s, i in members):
                return
        for k, s, inst in self.db.split(kind, scope, "tgl"):
            if not self.owned(k, s, inst, signal):
                self.rows[(k, s)][signal] = Row(cls, select)

    def bits(self, kind: str, scope: str, sc: reviewed.Scope, signal: str) -> set[Bit]:
        """The bits of one signal the plan takes at this scope, its module's included."""
        out: set[Bit] = set()
        scopes = [(kind, scope)]
        if kind == "INSTANCE":
            up = self.db.module_scope(sc, "tgl")
            if up is not None:
                scopes.append(("MODULE", up))
        dims = reviewed.declared(signal, sc.signals.get(signal, ""))
        for key in scopes:
            row = self.rows.get(key, {}).get(signal)
            if row is not None:
                out |= reviewed.bits_of(dims, row.select) or set()
        return out

    def taken(self, kind: str, scope: str, sc: reviewed.Scope, signal: str) -> set[Bit]:
        """Bits a report-gated class must leave alone: the plan's, or every member's."""
        out = self.bits(kind, scope, sc, signal)
        if kind == "MODULE":
            members = self.db.members(scope, "tgl")
            if members:
                common = None
                for _, path, inst in members:
                    b = self.bits("INSTANCE", path, inst, signal)
                    common = b if common is None else common & b
                out |= common or set()
        return out


class Planner:
    """Resolves the toggle classes against urg's templates and the run's port lists."""

    def __init__(
        self, db: reviewed.Database, report: reviewed.Report, manifest: reviewed.Manifest
    ) -> None:
        self.db, self.report, self.manifest = db, report, manifest
        self.plan = TogglePlan(db)
        self.copyright: dict[str, str] = {}
        self.absent: list[str] = []
        self.order = ["T1-OPENTITAN-PORTS-ONLY"]
        self.order += [c for c in manifest.classes if c.startswith("T")]
        self.order += list(FACT_ORDER)
        self.t1()
        self.units()
        self.facts()
        self.written = self.gate()

    def modules(self) -> list[tuple[str, reviewed.Scope]]:
        return [(s, sc) for s, sc in sorted(self.db.modules.items()) if "tgl" in sc.checksum]

    def t1(self) -> None:
        for module, relative in T1_UNITS:
            scopes = [
                s for s in self.db.by_name.get(module, []) if "tgl" in self.db.modules[s].checksum
            ]
            if not scopes:
                self.absent.append(module)
                continue
            source = ROOT / relative
            ports = module_ports(source, module)
            self.copyright[module] = copyright_line(source)
            for scope in scopes:
                for signal in self.db.modules[scope].signals:
                    if head_name(signal) not in ports:
                        self.plan.add("MODULE", scope, signal, "T1-OPENTITAN-PORTS-ONLY")

    def units(self) -> None:
        """Every net inside a ports-only unit; the root's reported ports stay graded."""
        db, report = self.db, self.report
        roots: dict[str, str] = {}
        for entry in self.manifest.units:
            rx = reviewed.glob(entry["instance"])
            for path in sorted(p for p in db.instances if rx.match(p)):
                roots.setdefault(path, entry["class"])
        owner: dict[str, tuple[str, bool]] = {}
        for path in db.instances:
            outer = [r for r in roots if path.startswith(r + ".")]
            if outer:
                owner[path] = (roots[min(outer, key=len)], True)
            elif path in roots:
                owner[path] = (roots[path], False)
        inner_by_module: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for path, (cls, inner) in owner.items():
            sc = db.instances[path]
            if inner and "tgl" in sc.checksum:
                up = db.module_scope(sc, "tgl")
                if up is not None:
                    inner_by_module[up][cls].append(path)
        whole_modules: dict[str, str] = {}
        for up, by_cls in inner_by_module.items():
            members = db.members(up, "tgl")
            if len(by_cls) == 1 and members:
                ((cls, paths),) = by_cls.items()
                if {p for _, p, _ in members} == set(paths):
                    whole_modules[up] = cls
        for up, cls in sorted(whole_modules.items()):
            for signal in db.modules[up].signals:
                self.plan.add("MODULE", up, signal, cls)
        for path, (cls, inner) in sorted(owner.items()):
            sc = db.instances[path]
            if "tgl" not in sc.checksum:
                continue
            kept = set() if inner else report.ports("INSTANCE", path, sc, db)
            for signal in sc.signals:
                if signal not in kept:
                    self.plan.add("INSTANCE", path, signal, cls)

    def facts(self) -> None:
        plan = self.plan
        for scope, sc in self.modules():
            module = sc.module or ""
            for signal in sc.signals:
                if union_view(signal, sc.signals):
                    plan.add("MODULE", scope, signal, "UNION-ALIAS")
            for m, prefix in IMAGE_COPIES:
                if m == module:
                    plan.add("MODULE", scope, prefix + ".values", "EFUSE-IMAGE-COPY")
            if module in FIELD_MAP_MODULES:
                for signal in sc.signals:
                    if FIELD_MAP.match(signal):
                        plan.add("MODULE", scope, signal, "EFUSE-FIELD-MAP-CONST")
            for m, signal in VERSION_NETS:
                if m == module:
                    plan.add("MODULE", scope, signal, "VERSION-ID-CONST")
            for signal in sc.signals:
                if ATOP.search(signal):
                    plan.add("MODULE", scope, signal, "ATOP-ZERO")
        for scope, sc in self.modules():
            for m, net in ERR_SLV_RESPONSES:
                if m == sc.module:
                    for member in ERR_SLV_MEMBERS:
                        plan.add("MODULE", scope, f"{net}.{member}", "ERR-SLV-CONST")
        tied = window(EXT_IRQ_FIRST, EXT_IRQ_LAST)
        for scope, sc in self.modules():
            for m, signal in EXT_IRQ_NETS:
                if m == sc.module:
                    plan.add("MODULE", scope, signal, "EXT-IRQ-TIED", tied)
        for path, sc in sorted(self.db.instances.items()):
            if "tgl" not in sc.checksum:
                continue
            m = EXT_IRQ_SYNC.search(path)
            if m and EXT_IRQ_FIRST <= int(m.group(1)) <= EXT_IRQ_LAST:
                for signal in sc.signals:
                    if not CLOCK_RESET.match(signal):
                        plan.add("INSTANCE", path, signal, "EXT-IRQ-TIED")

    def partial(self, review: reviewed.Plan) -> None:
        """PARTIAL-VECTOR: the uncovered rest of a payload vector that toggles somewhere.

        Decided per instance; a module row holds what every instance leaves, and an
        instance row the rest.
        """
        db, report = self.db, self.report
        cls = "PARTIAL-VECTOR"
        self.order.append(cls)

        def owned(path: str, inst: reviewed.Scope, signal: str) -> set[tuple[Bit, str]]:
            out: set[tuple[Bit, str]] = set()
            up = db.module_scope(inst, "tgl")
            for key in (("INSTANCE", path), ("MODULE", up)):
                out |= set(review.toggles.get(key, {}).get(signal, {}))
                got = self.written.get(key, {}).get(signal)
                if got:
                    out |= {(b, d) for b, ds in got[1].items() for d in ds}
            out |= {
                (b, d)
                for b in self.plan.taken("INSTANCE", path, inst, signal)
                for d in reviewed.DIRECTIONS
            }
            return out

        def rest(path: str, inst: reviewed.Scope) -> dict[str, set[tuple[Bit, str]]]:
            toggled = report.toggled("INSTANCE", path, inst, db)
            out = {}
            for signal, bits in report.toggles("INSTANCE", path, inst, db).items():
                if signal not in toggled or meaningful(signal) or IMAGE_VECTOR.search(signal):
                    continue
                dims = reviewed.declared(signal, inst.signals[signal])
                if len(reviewed.bits_of(dims, "") or ()) < 2:
                    continue
                left = {(b, d) for b, ds in bits.items() for d in ds} - owned(path, inst, signal)
                if left:
                    out[signal] = left
            return out

        def put(key: tuple[str, str], signal: str, pairs: set[tuple[Bit, str]]) -> None:
            bits: dict[Bit, set[str]] = defaultdict(set)
            for b, d in pairs:
                bits[b].add(d)
            self.written[key][signal] = (cls, dict(bits))

        done: set[str] = set()
        for scope, sc in sorted(db.modules.items()):
            if "tgl" not in sc.checksum:
                continue
            members = db.members(scope, "tgl")
            if not members:
                continue
            per = {path: rest(path, inst) for _, path, inst in members}
            done |= set(per)
            common = set.intersection(*(set(r) for r in per.values()))
            for signal in sorted(common):
                shared = set.intersection(*(r[signal] for r in per.values()))
                if shared:
                    put(("MODULE", scope), signal, shared)
                    for r in per.values():
                        r[signal] -= shared
            for path, r in per.items():
                for signal, pairs in r.items():
                    if pairs:
                        put(("INSTANCE", path), signal, pairs)
        for path, inst in sorted(db.instances.items()):
            if path not in done and "tgl" in inst.checksum:
                for signal, pairs in rest(path, inst).items():
                    put(("INSTANCE", path), signal, pairs)

    def describe(self, cls: str) -> tuple[str, str, str]:
        """A class's one-line fact, its full fact and its retiring condition."""
        if cls in CLASSES:
            c = CLASSES[cls]
            return c.summary, c.fact, c.retired_by
        entry = self.manifest.classes[cls]
        unit = entry["fact"].split(" is graded on its ports", 1)[0]
        summary = (
            f"{unit} is graded on its ports, as design engineering reviewed; the nets inside it "
            "and beneath it are excluded while uncovered"
        )
        full = f"{entry['fact']} {reviewed.REVIEWED}"
        return summary, full, "design engineering withdrawing the review of the unit"

    def annotation(self, cls: str) -> str:
        summary, _, retired = self.describe(cls)
        return f'ANNOTATION: "SMC-{cls}: {summary}. Retired by {retired}."'

    def legend(self, classes: list[str]) -> list[str]:
        """Header comment lines stating each class's full fact once."""
        out: list[str] = []
        for cls in classes:
            _, full, retired = self.describe(cls)
            kind = CLASSES[cls].kind if cls in CLASSES else "design review"
            grain = CLASSES[cls].granularity if cls in CLASSES else "whole signal"
            body = f"{cls} ({kind}, {grain}): {full} Retired by {retired}."
            out += ["//", *("// " + line for line in textwrap.wrap(body, 96))]
        return out

    def gate(self) -> dict[tuple[str, str], dict[str, tuple[str, dict[Bit, set[str]]]]]:
        """The planned bits the run's raw report leaves uncovered, by scope and signal.

        A module row keeps the bit-directions its module section, the union of its
        instances, marks uncovered; an instance of it that leaves more uncovered gets
        those on an instance row.
        """
        db, report = self.db, self.report
        out: dict = defaultdict(dict)

        def keep(kind, scope, sc, signal, row, minus=None):
            dims = reviewed.declared(signal, sc.signals[signal])
            picked = reviewed.bits_of(dims, row.select) or set()
            have = report.toggles(kind, scope, sc, db).get(signal, {})
            owned = {}
            for b in picked:
                dirs = set(have.get(b, ())) - (minus or {}).get(b, set())
                if dirs:
                    owned[b] = dirs
            return owned

        for (kind, scope), signals in self.plan.rows.items():
            sc = (db.modules if kind == "MODULE" else db.instances)[scope]
            for signal, row in signals.items():
                owned = keep(kind, scope, sc, signal, row)
                if owned:
                    out[(kind, scope)][signal] = (row.cls, owned)
                if kind != "MODULE":
                    continue
                for _, path, inst in db.members(scope, "tgl"):
                    if signal in self.plan.rows.get(("INSTANCE", path), {}):
                        continue
                    extra = keep("INSTANCE", path, inst, signal, row, owned)
                    if extra:
                        out[("INSTANCE", path)][signal] = (row.cls, extra)
        return out

    def render(self, kind: str) -> tuple[list[str], Counter]:
        """The `.el` blocks of one scope kind, in template order."""
        db = self.db
        rank = {c: i for i, c in enumerate(self.order)}
        counts: Counter = Counter()
        out: list[str] = []
        for (k, scope), signals in sorted(self.written.items(), key=lambda t: t[0][1]):
            if k != kind or not signals:
                continue
            sc = (db.modules if k == "MODULE" else db.instances)[scope]
            order = {}
            for item, i in sc.order["tgl"].items():
                m = reviewed.TOGGLE.match(item)
                if m:
                    order.setdefault(m.group(2), i)
            out += ["", f"CHECKSUM: {sc.checksum['tgl']}"]
            if k == "INSTANCE":
                out.append(f'ANNOTATION: "ModuleName: {sc.module}"')
            out.append(f"{k}: {scope}")
            by_cls: dict[str, list[str]] = defaultdict(list)
            for signal in sorted(signals, key=lambda s: (order.get(s, 1 << 30), s)):
                cls, owned = signals[signal]
                by_cls[cls] += reviewed.toggle_rows(signal, sc.signals[signal], owned)
            for cls in sorted(by_cls, key=lambda c: rank.get(c, len(rank))):
                out.append(self.annotation(cls))
                if cls == "T1-OPENTITAN-PORTS-ONLY" and sc.module in self.copyright:
                    out.append(f'ANNOTATION: "{sc.module}: {self.copyright[sc.module]}"')
                out += by_cls[cls]
                counts[cls] += len(by_cls[cls])
        return out, counts


HEADER = (
    "// SPDX-License-Identifier: Apache-2.0",
    "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.",
    "//==================================================",
    "// SMC VCS toggle exclusions, {scope} scope.",
    "// Format Version: 2",
    "// ExclMode: default",
    "//",
    "// Generated by gen_smc_toggle_exclusions.py from urg's templates and the run's",
    "// raw report; regenerate from each graded run rather than edit. A class names",
    "// whole signals or a bit window; only the bit-directions the run leaves",
    "// uncovered are written, so covered points stay graded. {what}",
    "// Each block names its class; the classes below state their facts and",
    "// retiring conditions, and README.md gives every class's granularity.",
    "//==================================================",
)
WHAT = {
    "MODULE": "Each block holds for every instance of its module.",
    "INSTANCE": "Each block holds for one instance.",
}


def text(planner: Planner, kind: str) -> tuple[str, Counter]:
    rows, counts = planner.render(kind)
    head = [h.format(scope=kind.lower(), what=WHAT[kind]) for h in HEADER]
    used = [c for c in planner.order if c in counts]
    head[-1:-1] = planner.legend(used)
    return "\n".join([*head, *rows]) + "\n", counts


def plan(template_dir: Path, modinfo: Path) -> tuple[Planner, reviewed.Planner]:
    """The toggle plan and the report-gated plan that leaves its bits alone.

    PARTIAL-VECTOR is planned last and takes only what neither leaves uncovered.
    """
    db = reviewed.Database(template_dir)
    report = reviewed.Report(modinfo)
    manifest = reviewed.Manifest()
    toggles = Planner(db, report, manifest)
    review = reviewed.Planner(db, report, manifest, toggles.plan.taken)
    toggles.partial(review.plan)
    return toggles, review
