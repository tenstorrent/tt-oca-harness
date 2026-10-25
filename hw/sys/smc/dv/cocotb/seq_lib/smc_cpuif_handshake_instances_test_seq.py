# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_008 ANCHOR: smc_cpuif_handshake_instances_test
# DV-TESTCASE-CONTRACT-REVISION: 5 RECORD-SHA256: 4d68d1879a666d752f86205bbe7816fd6beb72a0287f15da626741cf702c43c4
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 8 ENV: cocotb
"""The AXI-Lite front end of every generated register-block instance, pipelined and held.

`smc_cpuif_handshake_test` drives instance 0 of each register block. This
sequence drives every instance of the multi-instance families -- GPIO
interfaces 0..64, inbound and outbound filter entries 0..15, M-mode, Xvisor and
alias remaps 0..7, I2C 0..2, the UART/log wraps 0..3 (control, main UART,
divisor latch, log engine), telemetry receivers 0..2 and the cold and warm
scratch banks -- and instance 0 of every single-instance family: reset unit,
cpu_ctrl, the IRQEN register of each of the 64 mailbox apertures, AVSBus, I2C
control, OCTS, DFX, base configuration, eFuse interface control and shadow,
zeroer and iDMA control, I3C 0, the DFD/CLA sink, chip_config, ndm_reset and
the straps window. One instance at a time, through SEP_IN. The DTP CSR target
has no responder on this bench and is never accessed (SF-040).

Each instance has one reference register: on a pinned-map family a
side-effect-free read-write register whose fields the spec documents as inert
while the entry is disabled, else a plain read-write register written only
with the value it holds. Its first isolated read is the reference every later
read of that register is compared with.

On the pinned-map families (GPIO interface, filter entries, alias and output
remaps, reset unit, cpu_ctrl, mailbox IRQEN) the register also takes distinct
written values, chosen so that the entry stays disabled:

* GPIO ``ACCESS_FILTER``: only ``arprot_requirement`` / ``awprot_requirement``,
  with both filter enables held clear; the second register is ``DATA_CTRL``,
  where only ``interrupt_type`` moves while ``interrupt_enable`` reads clear.
* Filter ``START_ADDR`` / ``END_ADDR``: 4 KiB multiples (``END_ADDR`` keeps its
  low reset bits, the top of an 8-byte granule), so the granule rounding the
  spec describes leaves the written value unchanged; ``FILTER_CONFIG`` must read
  ``entry_enabled``, ``allow_burst`` and ``locked`` clear first.
* Alias ``region_start`` / ``region_end`` with ``region_attrs.valid`` clear.
* M-mode and Xvisor ``region_attrs``: only offset bits 55:20 move and ``valid``
  stays clear. Each instance has one register, so its second register is the
  next instance's ``region_attrs``.
* Reset unit: the two FLR counter value registers. cpu_ctrl: ``SCRATCH[15]``
  and ``SCRATCH[14]``.
* Mailbox ``IRQEN``, with ``IRQS`` of the aperture and of its neighbour reading
  clear first, so no enabled interrupt is pending; the second register is the
  next aperture's ``IRQEN``. The mailbox clock is enabled for the run and
  restored at the end.

Every access is driven through `SmcSysAxiGroupItem`, and a passive monitor on
the SEP_IN AXI port records every AW, W, AR, B and R handshake, the first VALID
cycle of each AW and W, and every cycle a response sits on a low ready. AXI
orders no read against writes on the write channel, so a read that overlaps a
write of its group may return either value. It is held to the last write whose B
preceded its AR, or to a write of the group whose AW handshake is at or before
the read's R and whose B is not before its AR; those matches are logged with
their AR, R, AW and B cycles (SF-010). Any other value fails.
BREADY and RREADY are held through the VIP's response sinks, released a fixed
number of cycles after the response's VALID is first seen; for a W-ahead write
the AW source is held and released so that AW VALID rises exactly the driven
number of cycles after W VALID, which the monitor measures.

One instance of each family in ``LONG_HOLD_FAMILIES`` then repeats the held
groups with the ready released 512 cycles after the first response VALID
instead of 16, and must hold the head response unchanged for all of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from .smc_addr_map import GPIO_INTF_NUM, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import DLL_OFFSET, LCR_DLAB, uart_base, uart_reg
from .smc_mailbox_data_error_test_seq import CLOCK_GATE_CONTROL, MAILBOX_CG_EN
from .smc_rdl_regmap import RdlReg, rdl_contract, rdl_register

RESP_OKAY = 0

# Each group wait is bounded below the driver's own 50 us per-access bound, so
# an expiry reports the outstanding count before the driver raises.
GROUP_BOUND_NS = 40_000
# Clocks a held ready waits for its response VALID before it gives up.
VALID_BOUND_CYCLES = 4_000
FUSE_SENSE_MAX_SMC_CYCLES = 200_000

# Fixed knobs from the contract.
PIPELINED_PAIRS = 4
PIPELINED_READS = 4
W_LEADS = (1, 2, 4)
WRITEBACK_LEAD = 2
HOLD_CYCLES = 16
HELD_DEPTH = 16
LONG_HOLD_CYCLES = 512
# One instance of each of these families takes the held groups again behind
# LONG_HOLD_CYCLES; a family missing from the instance set fails the run.
LONG_HOLD_FAMILIES = (
    "inbound_filter",
    "outbound_filter",
    "mmode_remap",
    "xvisor_remap",
    "alias_remap",
    "uart_log_engine_ctrl",
    "uart_16550_main",
    "uart_16550_dl",
    "log_engine",
    "telemetry_receiver",
    "gpio_intf",
    "chip_config",
    "ndm_reset",
    "scratch",
    "straps",
    "i2c_ctrl",
)
# Read-arrival offsets swept behind write-backs of the reference, as in the
# instance-0 leaf: which offset lines a read accept up with a write's
# acknowledge depends on the path in front of each instance.
SWEEP_OFFSETS = range(12)

# Output-remap offset bits the spec names as used for the SMC's 1 MiB regions.
_REMAP_OFFSET_LSB = 20
# Filter START/END and alias region values move in 4 KiB steps.
_PAGE_LSB = 12

TERMS = (
    "REFERENCE",
    "PIPELINED-RW",
    "PIPELINED-READ",
    "B2B-SAME",
    "B2B-DIFF",
    "W-AHEAD",
    "W-AHEAD-WB",
    "RREADY-HOLD",
    "BREADY-HOLD",
    "HELD-GROUP",
    "LONG-HOLD",
)
PINNED_ONLY_TERMS = frozenset({"PIPELINED-RW", "B2B-DIFF", "W-AHEAD", "BREADY-HOLD"})


class Ev(NamedTuple):
    """One monitor record. ``cycle`` is the clk_smc_i edge the handshake lands on."""

    kind: str
    cycle: int
    ident: int = 0
    resp: int = 0
    data: int = 0


class SepInMonitor:
    """Passive per-clock record of the SEP_IN AXI channels."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.events: list[Ev] = []
        self.cycle = 0
        self.stop = False
        self._pending = {"aw": False, "w": False}
        self._held: dict[str, tuple | None] = {"r": None, "b": None}

    def mark(self) -> int:
        return len(self.events)

    def since(self, mark: int) -> list[Ev]:
        return self.events[mark:]

    def _bit(self, name: str) -> int:
        sig = getattr(self.dut, f"s_axi_{name}")
        if not sig.value.is_resolvable:
            self.events.append(Ev("x", self.cycle, 0, 0, 0))
            return 0
        return int(sig.value)

    def _word(self, name: str) -> int | None:
        value = getattr(self.dut, f"s_axi_{name}").value
        return int(value) if value.is_resolvable else None

    def _payload(self, chan: str) -> tuple[int, int, int] | None:
        ident = self._word(f"{chan}id")
        resp = self._word(f"{chan}resp")
        data = self._word("rdata") if chan == "r" else 0
        if ident is None or resp is None or data is None:
            self.events.append(Ev("x", self.cycle, 0, 0, 0))
            return None
        return ident, resp, data

    def _response(self, chan: str) -> None:
        valid, ready = self._bit(f"{chan}valid"), self._bit(f"{chan}ready")
        held = self._held[chan]
        if not valid:
            if held is not None:
                self.events.append(Ev(f"{chan}drop", self.cycle, held[0], held[1], held[2]))
            self._held[chan] = None
            return
        payload = self._payload(chan)
        if payload is None:
            return
        if held is not None and payload != held:
            self.events.append(Ev(f"{chan}chg", self.cycle, *payload))
        if ready:
            self.events.append(Ev(chan, self.cycle, *payload))
            self._held[chan] = None
        else:
            self.events.append(Ev(f"{chan}held", self.cycle, *payload))
            self._held[chan] = payload

    def _request(self, chan: str, ident_name: str | None, addr_name: str | None) -> None:
        valid, ready = self._bit(f"{chan}valid"), self._bit(f"{chan}ready")
        if chan in self._pending:
            if valid and not self._pending[chan]:
                self.events.append(Ev(f"{chan}start", self.cycle))
            self._pending[chan] = bool(valid and not ready)
        if valid and ready:
            ident = self._word(ident_name) if ident_name else 0
            addr = self._word(addr_name) if addr_name else 0
            if ident is None or addr is None:
                self.events.append(Ev("x", self.cycle, 0, 0, 0))
                return
            self.events.append(Ev(chan, self.cycle, ident, 0, addr))

    async def run(self) -> None:
        clk = self.dut.clk_smc_i
        while not self.stop:
            await RisingEdge(clk)
            await ReadOnly()
            self.cycle += 1
            self._request("aw", "awid", "awaddr")
            self._request("w", None, None)
            self._request("ar", "arid", "araddr")
            self._response("b")
            self._response("r")


@dataclass(frozen=True)
class Inst:
    """One register-block instance and the registers its legs drive."""

    name: str
    family: str
    addr: int
    width: int
    pinned: bool
    free: int = 0
    ref_zero: int = 0
    b_addr: int = 0
    b_width: int = 0
    b_free: int = 0
    b_cmp: int = 0
    b_zero: int = 0
    pre: tuple[tuple[str, int, int, int], ...] = ()
    dlab_wrap: int | None = None


@dataclass
class Tally:
    instances: int = 0
    reads: int = 0
    strict: int = 0
    inflight: int = 0
    extra: dict = field(default_factory=dict)


def _mask(reg: RdlReg, *names: str) -> int:
    out = 0
    for name in names:
        fields = [f for f in reg.fields if f.name == name]
        assert len(fields) == 1, f"{reg.path} has no single field {name}"
        out |= fields[0].mask
    return out


def _check_probe(reg: RdlReg, *, written: bool) -> None:
    for f in reg.fields:
        assert not f.read_action, (
            f"{reg.path}: field {f.name} has read action {f.read_action}, so reading it "
            f"changes state"
        )
        if written:
            assert not f.modified_write, (
                f"{reg.path}: field {f.name} has modified-write {f.modified_write}"
            )
            assert f.access != "write-only", f"{reg.path}: write-only field {f.name}"


def _deposit(k: int, mask: int) -> int:
    out, m = 0, mask
    while k:
        assert m, f"value counter exceeds the free bits 0x{mask:x}"
        low = m & -m
        if k & 1:
            out |= low
        k >>= 1
        m ^= low
    return out


def _indexed(sym: str, path: str, idx: int) -> RdlReg:
    """Instance ``idx`` of ``path`` (a ``{}`` marks the index), held to both maps."""
    reg = rdl_contract(path.format(idx))
    base0 = smc_indexed_addr(sym, 0)
    offset = rdl_contract(path.format(0)).addr - base0
    addr = smc_indexed_addr(sym, idx) + offset
    assert addr == reg.addr, (
        f"{reg.path}: smc_addr.h places it at 0x{addr:x}, the IP-XACT map at 0x{reg.addr:x}"
    )
    return reg


def build_instances() -> tuple[Inst, ...]:
    out: list[Inst] = []
    assert GPIO_INTF_NUM == 65, f"GPIO_INTF_NUM is {GPIO_INTF_NUM}, the contract names 0..64"
    for i in range(GPIO_INTF_NUM):
        sym = "SMC_TOP_GPIO_INTF_BASE_ADDR"
        a = _indexed(sym, "gpio_intf[{}]/ACCESS_FILTER", i)
        b = _indexed(sym, "gpio_intf[{}]/DATA_CTRL", i)
        _check_probe(a, written=True)
        _check_probe(b, written=True)
        out.append(
            Inst(
                f"gpio_intf[{i}]",
                "gpio_intf",
                a.addr,
                a.width_bytes,
                True,
                free=_mask(a, "arprot_requirement", "awprot_requirement"),
                ref_zero=_mask(a, "write_filter_enable", "read_filter_enable"),
                b_addr=b.addr,
                b_width=b.width_bytes,
                b_free=_mask(b, "interrupt_type"),
                b_cmp=b.rw_mask,
                b_zero=_mask(b, "interrupt_enable"),
            )
        )
    for bank in ("inbound", "outbound"):
        sym = f"SMC_TOP_SMC_{bank.upper()}_FILTER_CTRL_BASE_ADDR"
        for i in range(16):
            path = f"smc_{bank}_filter_ctrl[{{}}]/"
            cfg = _indexed(sym, path + "FILTER_CONFIG", i)
            a = _indexed(sym, path + "START_ADDR", i)
            b = _indexed(sym, path + "END_ADDR", i)
            _check_probe(cfg, written=False)
            _check_probe(a, written=True)
            _check_probe(b, written=True)
            page = ~((1 << _PAGE_LSB) - 1)
            out.append(
                Inst(
                    f"{bank}_filter[{i}]",
                    f"{bank}_filter",
                    a.addr,
                    a.width_bytes,
                    True,
                    free=a.declared_mask & page,
                    b_addr=b.addr,
                    b_width=b.width_bytes,
                    b_free=b.declared_mask & page,
                    b_cmp=b.declared_mask,
                    pre=(
                        (
                            "FILTER_CONFIG",
                            cfg.addr,
                            cfg.width_bytes,
                            _mask(cfg, "entry_enabled", "allow_burst", "locked"),
                        ),
                    ),
                )
            )
    for fam in ("mmode", "xvisor"):
        sym = f"SMC_TOP_SMC_{fam.upper()}_REMAP_BASE_ADDR"
        regs = [_indexed(sym, f"smc_{fam}_remap[{{}}]/REGION/region_attrs", i) for i in range(8)]
        for i, a in enumerate(regs):
            b = regs[(i + 1) % len(regs)]
            _check_probe(a, written=True)
            offset = _mask(a, "offset") & ~((1 << _REMAP_OFFSET_LSB) - 1)
            out.append(
                Inst(
                    f"{fam}_remap[{i}]",
                    f"{fam}_remap",
                    a.addr,
                    a.width_bytes,
                    True,
                    free=offset,
                    ref_zero=_mask(a, "valid"),
                    b_addr=b.addr,
                    b_width=b.width_bytes,
                    b_free=offset,
                    b_cmp=b.declared_mask,
                    b_zero=_mask(b, "valid"),
                )
            )
    sym = "SMC_TOP_SMC_ALIAS_REMAP_BASE_ADDR"
    for i in range(8):
        a = _indexed(sym, "smc_alias_remap[{}]/REGION/region_start", i)
        b = _indexed(sym, "smc_alias_remap[{}]/REGION/region_end", i)
        attrs = _indexed(sym, "smc_alias_remap[{}]/REGION/region_attrs", i)
        for reg in (a, b, attrs):
            _check_probe(reg, written=reg is not attrs)
        out.append(
            Inst(
                f"alias_remap[{i}]",
                "alias_remap",
                a.addr,
                a.width_bytes,
                True,
                free=_mask(a, "start_addr"),
                b_addr=b.addr,
                b_width=b.width_bytes,
                b_free=_mask(b, "end_addr"),
                b_cmp=b.declared_mask,
                pre=(("region_attrs", attrs.addr, attrs.width_bytes, _mask(attrs, "valid")),),
            )
        )

    def plain(name: str, family: str, reg: RdlReg) -> Inst:
        _check_probe(reg, written=True)
        assert reg.rw_mask == reg.declared_mask, (
            f"{reg.path} has a field that is not plain read-write, so a write-back of its "
            f"value is not known to be a no-op"
        )
        return Inst(name, family, reg.addr, reg.width_bytes, False)

    sym = "SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR"
    for i in range(3):
        reg = _indexed(sym, "smc_i2c_wrap/i2c[{}]/HOST_FIFO_CONFIG", i)
        out.append(plain(f"i2c[{i}]", "i2c", reg))
    wrap = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_"
    wpath = "smc_uart_wrap/uart_log_engine_wrap[{}]/"
    for w in range(4):
        ctrl = _indexed(
            f"{wrap}UART_LOG_ENGINE_CTRL_BASE_ADDR", wpath + "uart_log_engine_ctrl/CTRL", w
        )
        main = _indexed(f"{wrap}UART_BASE_ADDR", wpath + "uart/SCR", w)
        log = _indexed(f"{wrap}LOG_ENGINE_BASE_ADDR", wpath + "log_engine/LOG_REGION_SIZE", w)
        out.append(plain(f"uart_log_engine_ctrl[{w}]", "uart_log_engine_ctrl", ctrl))
        out.append(plain(f"uart_16550_main[{w}]", "uart_16550_main", main))
        out.append(
            Inst(
                f"uart_16550_dl[{w}]",
                "uart_16550_dl",
                uart_base(w) + DLL_OFFSET,
                4,
                False,
                dlab_wrap=w,
            )
        )
        out.append(plain(f"log_engine[{w}]", "log_engine", log))
    sym = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_BASE_ADDR"
    for i in range(3):
        reg = _indexed(sym, "smc_telemetry_receiver_wrap/telemetry_receiver[{}]/INTR_ENABLE", i)
        out.append(plain(f"telemetry_receiver[{i}]", "telemetry_receiver", reg))
    out.append(
        plain("scratch_cold", "scratch", rdl_register("smc_misc_wrap/scratch_cold/SCRATCH[0]"))
    )
    out.append(
        plain(
            "scratch_cold_warm",
            "scratch",
            rdl_register("smc_misc_wrap/scratch_cold_warm/SCRATCH[0]"),
        )
    )

    def read_only(name: str, family: str, reg: RdlReg) -> Inst:
        _check_probe(reg, written=True)
        assert all(f.access == "read-only" for f in reg.fields), f"{reg.path} is not read-only"
        return Inst(name, family, reg.addr, reg.width_bytes, False)

    # Instance 0 of the single-instance families; the probes are the ones the
    # instance-0 leaf and the attribute sweep hold against the generated contract.
    for name, path in (
        ("avsbus_controller", "smc_avsbus_controller/AVS_CFG_0"),
        ("i2c_ctrl", "smc_i2c_wrap/i2c_ctrl_regs/I2C_CTRL[0]"),
        ("system_timer_octs", "smc_system_timer_octs/TIMER_PRESET_LO"),
        ("dfx_ctrl_status", "dfx_ctrl/DEBUG_BUS_MUX"),
        ("smc_base_config", "smc_base_config/HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD"),
        ("efuse_interface_ctrl", "efuse_interface_ctrl/EFUSE_READ_REQ_TIMEOUT"),
        ("efuse_shadow", "smc_efuse_map/I2C_I3C_ID[0]"),
        ("zeroer_ctrl", "zeroer_ctrl/DEST_ADDR"),
        ("idma_ctrl", "dma_ctrl/DST_ADDRESS_LO"),
        ("i3c_csr[0]", "oca_i3c_wrap/i3c_csr[0]/I3CBase/DEV_CTX_BASE_LO"),
        ("dfd_cla", "smc_cla/dst_sink/ScratchLo"),
    ):
        out.append(plain(name, name, rdl_contract(path)))
    for name, path in (
        ("chip_config", "smc_misc_wrap/chip_config/VERSION_LO"),
        ("ndm_reset", "smc_misc_wrap/ndm_reset/NDMRESET_CLUSTER_COUNT"),
    ):
        out.append(read_only(name, name, rdl_register(path)))
    # straps.rdl makes STRAPS_LO sw = r; it is reached by address in the adopter window.
    out.append(
        Inst(
            "straps",
            "straps",
            smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_LO_BASE_ADDR"),
            4,
            False,
        )
    )

    a = rdl_register("smc_cpu_ctrl/SCRATCH[15]")
    b = rdl_register("smc_cpu_ctrl/SCRATCH[14]")
    for reg in (a, b):
        _check_probe(reg, written=True)
        assert reg.rw_mask == reg.declared_mask, f"{reg.path} is not plain read-write"
    out.append(
        Inst(
            "cpu_ctrl",
            "cpu_ctrl",
            a.addr,
            a.width_bytes,
            True,
            free=a.rw_mask,
            b_addr=b.addr,
            b_width=b.width_bytes,
            b_free=b.rw_mask,
            b_cmp=b.declared_mask,
        )
    )
    a = rdl_register("smc_reset_unit/ISOLATE_REQ_FLR_COUNTER_VALUE")
    b = rdl_register("smc_reset_unit/ISOLATE_REQ_FLR_RESET_COUNTER_VALUE")
    for reg in (a, b):
        _check_probe(reg, written=True)
        assert reg.rw_mask == reg.declared_mask, f"{reg.path} is not plain read-write"
    out.append(
        Inst(
            "reset_unit",
            "reset_unit",
            a.addr,
            a.width_bytes,
            True,
            free=a.rw_mask,
            b_addr=b.addr,
            b_width=b.width_bytes,
            b_free=b.rw_mask,
            b_cmp=b.declared_mask,
        )
    )

    # Mailbox IRQEN of every aperture. IRQP is IRQS gated by IRQEN, so with IRQS
    # reading clear on both apertures a leg touches no interrupt reaches the CPU.
    apertures = [f"inbound_mailbox_{i}" for i in range(32)] + [
        f"outbound_mailbox_{i}" for i in range(32)
    ]
    irqen = [rdl_contract(f"smc_mailbox/{ap}/IRQEN") for ap in apertures]
    irqs = [rdl_contract(f"smc_mailbox/{ap}/IRQS") for ap in apertures]
    for i, ap in enumerate(apertures):
        a, b = irqen[i], irqen[(i + 1) % len(apertures)]
        sa, sb = irqs[i], irqs[(i + 1) % len(apertures)]
        _check_probe(a, written=True)
        assert a.rw_mask == a.declared_mask, f"{a.path} is not plain read-write"
        out.append(
            Inst(
                f"mailbox_{ap}",
                "mailbox",
                a.addr,
                a.width_bytes,
                True,
                free=a.rw_mask,
                b_addr=b.addr,
                b_width=b.width_bytes,
                b_free=b.rw_mask,
                b_cmp=b.declared_mask,
                pre=(
                    (f"IRQS_{i}", sa.addr, sa.width_bytes, sa.declared_mask),
                    (f"IRQS_{(i + 1) % len(apertures)}", sb.addr, sb.width_bytes, sb.declared_mask),
                ),
            )
        )

    addrs = [x.addr for x in out]
    assert len(set(addrs)) == len(addrs), "two instances resolve to the same reference address"
    return tuple(out)


class smc_cpuif_handshake_instances_test_seq(SmcCsrSeq):
    """Pipeline, skew and hold the front end of every register-block instance."""

    def __init__(self, name: str = "smc_cpuif_handshake_instances_test_seq") -> None:
        super().__init__(name)
        self.instances = build_instances()
        self.long_hold: dict[str, str] = {}
        for fam in LONG_HOLD_FAMILIES:
            names = [x.name for x in self.instances if x.family == fam]
            assert names, f"long-hold family {fam} has no instance in the set"
            self.long_hold[names[0]] = fam
        self.long_families: list[str] = []
        self.long_waits = 0
        self.waits = 0
        self.mon: SepInMonitor | None = None
        self.tally = {name: Tally() for name in TERMS}
        self.stamps: dict[str, list[int]] = {name: [] for name in TERMS}
        self.leads: dict[int, list[int]] = {lead: [] for lead in (*W_LEADS, WRITEBACK_LEAD)}
        self.b2b_gaps: list[int] = []
        self.logged_writeback: list[str] = []
        self.sweep = {"compared": 0, "logged": 0, "logged_equal": 0}
        self.spread = 0
        self.b2b_diff_gaps: list[int] = []

    # -- primitives ------------------------------------------------------

    @staticmethod
    def _item(
        label: str, op: SmcSysAxiOp, addr: int, width: int, ident: int, **kw
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = width
        item.axi_id = ident
        item.wdata = kw.get("wdata", 0)
        item.expected = kw.get("expected")
        return item

    def _rd(self, x: Inst, tag: str, ident: int = 1, *, addr=None, width=None, expected=None):
        return self._item(
            f"{x.name}_{tag}",
            SmcSysAxiOp.READ,
            x.addr if addr is None else addr,
            x.width if width is None else width,
            ident,
            expected=expected,
        )

    def _wr(self, x: Inst, tag: str, value: int, ident: int = 1, *, addr=None, width=None):
        return self._item(
            f"{x.name}_{tag}",
            SmcSysAxiOp.WRITE,
            x.addr if addr is None else addr,
            x.width if width is None else width,
            ident,
            wdata=value,
        )

    def _sink(self, chan: str):
        driver = self.env.sys_axi_agent.driver.axi.driver
        return driver.channels[{"r": "r_ready_delay", "b": "b_ready_delay"}[chan]]

    async def _release_after_valid(
        self, chan: str, label: str, state: dict, cycles: int = HOLD_CYCLES
    ) -> None:
        sink = self._sink(chan)
        valid = getattr(cocotb.top, f"s_axi_{chan}valid")
        clk = cocotb.top.clk_smc_i
        for _ in range(VALID_BOUND_CYCLES):
            await RisingEdge(clk)
            await ReadOnly()
            if valid.value.is_resolvable and int(valid.value):
                break
        else:
            await RisingEdge(clk)
            sink.pause = False
            state["expired"] = (
                f"{label}: {chan.upper()}VALID never rose within {VALID_BOUND_CYCLES} "
                f"clk_smc_i cycles of the held {chan.upper()}READY (last {chan}valid="
                f"{valid.value})"
            )
            return
        for _ in range(cycles):
            await RisingEdge(clk)
        sink.pause = False

    async def _release_aw(self, lead: int, label: str, state: dict) -> None:
        """Release the held AW so its VALID rises ``lead`` cycles after W VALID."""
        aw = self.env.sys_axi_agent.driver.axi.driver.channels["aw_delay"]
        wvalid = cocotb.top.s_axi_wvalid
        clk = cocotb.top.clk_smc_i
        for _ in range(VALID_BOUND_CYCLES):
            await RisingEdge(clk)
            await ReadOnly()
            if wvalid.value.is_resolvable and int(wvalid.value):
                break
        else:
            aw.pause = False
            state["expired"] = (
                f"{label}: WVALID never rose within {VALID_BOUND_CYCLES} clk_smc_i cycles "
                f"of the held AW (last wvalid={wvalid.value})"
            )
            return
        for _ in range(lead - 1):
            await RisingEdge(clk)
            await ReadOnly()
        aw.pause = False

    async def _issue(self, group: SmcSysAxiGroupItem) -> None:
        await self.start_item(group)
        await self.finish_item(group)

    async def _run(
        self,
        label: str,
        items: list[SmcSysAxiItem],
        *,
        timing: AxiTimingProfile | None = None,
        hold: tuple[str, ...] = (),
        hold_cycles: int = HOLD_CYCLES,
        w_lead: int | None = None,
    ) -> list[Ev]:
        """Drive ``items`` outstanding together; return the monitor records of the group."""
        assert self.mon is not None
        mark = self.mon.mark()
        state: dict = {}
        tasks = []
        for chan in hold:
            self._sink(chan).pause = True
            tasks.append(
                cocotb.start_soon(self._release_after_valid(chan, label, state, hold_cycles))
            )
        aw_chan = None
        if w_lead is not None:
            aw_chan = self.env.sys_axi_agent.driver.axi.driver.channels["aw_delay"]
            aw_chan.pause = True
            tasks.append(cocotb.start_soon(self._release_aw(w_lead, label, state)))
        group = SmcSysAxiGroupItem(label, items, timing=timing)
        try:
            await with_timeout(self._issue(group), GROUP_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            evs = self.mon.since(mark)
            done = sum(1 for e in evs if e.kind in ("r", "b"))
            last = evs[-1] if evs else None
            raise AssertionError(
                f"{label}: {len(items) - done} of {len(items)} accesses still outstanding "
                f"after {GROUP_BOUND_NS} ns; last SEP_IN record {last}"
            ) from exc
        finally:
            for task in tasks:
                task.cancel()
            for chan in hold:
                self._sink(chan).pause = False
            if aw_chan is not None:
                aw_chan.pause = False
        assert "expired" not in state, state.get("expired")
        self.waits += 1 + len(hold) + (w_lead is not None)
        self.accesses += len(items)
        evs = self.mon.since(mark)
        self._settle(label, items, evs)
        return evs

    def _settle(self, label: str, items: list[SmcSysAxiItem], evs: list[Ev]) -> None:
        """One request and one response per access, nothing else, no X, no drop, no change."""
        bad = [e for e in evs if e.kind in ("x", "rdrop", "bdrop", "rchg", "bchg")]
        assert not bad, f"{label}: SEP_IN protocol records {bad[:4]}"
        for req, rsp, op in (("ar", "r", SmcSysAxiOp.READ), ("aw", "b", SmcSysAxiOp.WRITE)):
            want = [i.axi_id for i in items if i.op is op]
            got_req = [e.ident for e in evs if e.kind == req]
            got_rsp = [e.ident for e in evs if e.kind == rsp]
            assert sorted(got_req) == sorted(want), (
                f"{label}: {req.upper()} handshakes carried IDs {got_req}, the group issued {want}"
            )
            assert sorted(got_rsp) == sorted(want), (
                f"{label}: {rsp.upper()} handshakes carried IDs {got_rsp} for requests {want}: "
                f"a response was lost or duplicated"
            )
        for item in items:
            assert item.resp_code == RESP_OKAY, (
                f"{label}: {item} answered resp={item.resp_code}, not OKAY"
            )

    @staticmethod
    def _cycles(items: list[SmcSysAxiItem], evs: list[Ev]) -> dict[int, tuple[int, int]]:
        """Request and response cycle of each item, the n-th of an ID taking the n-th beat."""
        out: dict[int, tuple[int, int]] = {}
        for op, req, rsp in ((SmcSysAxiOp.READ, "ar", "r"), (SmcSysAxiOp.WRITE, "aw", "b")):
            seen: dict[int, int] = {}
            for item in items:
                if item.op is not op:
                    continue
                n = seen.get(item.axi_id, 0)
                seen[item.axi_id] = n + 1
                reqs = [e.cycle for e in evs if e.kind == req and e.ident == item.axi_id]
                rsps = [e.cycle for e in evs if e.kind == rsp and e.ident == item.axi_id]
                out[id(item)] = (reqs[n], rsps[n])
        return out

    def _in_order(self, label: str, evs: list[Ev]) -> None:
        for req, rsp in (("ar", "r"), ("aw", "b")):
            issued = [e.ident for e in evs if e.kind == req]
            answered = [e.ident for e in evs if e.kind == rsp]
            assert answered == issued, (
                f"{label}: {rsp.upper()} IDs answered in order {answered}, issued {issued}"
            )

    def _reads_vs_writes(
        self, label: str, items: list[SmcSysAxiItem], evs: list[Ev], prior: int
    ) -> tuple[int, int]:
        """Hold each read to the last acknowledged write or a write overlapping it."""
        cyc = self._cycles(items, evs)
        writes = [(w.wdata, *cyc[id(w)]) for w in items if w.op is SmcSysAxiOp.WRITE]
        strict = inflight = 0
        for rd in (i for i in items if i.op is SmcSysAxiOp.READ):
            ar, r = cyc[id(rd)]
            acked = [w for w in writes if w[2] < ar]
            last = max(acked, key=lambda w: w[2])[0] if acked else prior
            open_ = [w for w in writes if w[1] <= r and w[2] >= ar]
            if rd.rdata == last:
                strict += 1
                continue
            match = [w for w in open_ if w[0] == rd.rdata]
            assert match, (
                f"{label}: read ID {rd.axi_id} (AR handshake cycle {ar}, R {r}) returned "
                f"0x{rd.rdata:x}; the last write acknowledged before its AR left 0x{last:x} and "
                f"the writes with AW at or before its R and B not before its AR (AW/B cycles) were "
                f"{[(hex(w[0]), w[1], w[2]) for w in open_]}; all writes (value, AW, B): "
                f"{[(hex(w[0]), w[1], w[2]) for w in writes]}"
            )
            inflight += 1
            cocotb.log.info(
                "MEASURE %s: read ID %d AR cycle %d R cycle %d returned overlapping write 0x%x "
                "(AW cycle %d <= R, B cycle %d >= AR), last acknowledged 0x%x (SF-010)",
                label,
                rd.axi_id,
                ar,
                r,
                rd.rdata,
                match[0][1],
                match[0][2],
                last,
            )
        return strict, inflight

    def _stamp(self, x: Inst, term: str, times: dict[str, int]) -> None:
        now = int(get_sim_time("ps"))
        times[term] = now
        self.stamps[term].append(now)

    def _values(self, x: Inst, ref: int):
        """Distinct values in the free bits; a narrow field space repeats from the start."""
        width = bin(x.free).count("1")
        assert width >= 2, f"{x.name}: free bits 0x{x.free:x} hold fewer than two values"
        k = 0
        while True:
            k = k + 1 if width >= 32 or k + 1 < (1 << width) else 1
            v = (ref & ~x.free) | _deposit(k, x.free)
            if v != ref:
                yield v

    async def _read(self, x: Inst, tag: str, *, expected=None, addr=None, width=None) -> int:
        item = self._rd(x, tag, addr=addr, width=width, expected=expected)
        await self._run(f"{x.name}_{tag}", [item])
        return item.rdata

    async def _write(self, x: Inst, tag: str, value: int, *, addr=None, width=None) -> None:
        await self._run(f"{x.name}_{tag}", [self._wr(x, tag, value, addr=addr, width=width)])

    async def _restore(self, x: Inst, ref: int, tag: str) -> None:
        await self._write(x, f"{tag}_restore", ref)
        got = await self._read(x, f"{tag}_restore_rb", expected=ref)
        assert got == ref, f"{x.name}: restore read 0x{got:x}, reference 0x{ref:x}"

    # -- steps -----------------------------------------------------------

    async def _reference(self, x: Inst) -> int:
        for label, addr, width, mask in x.pre:
            word = await self._read(x, f"pre_{label}", addr=addr, width=width)
            assert word & mask == 0, (
                f"{x.name}: {label} reads 0x{word:x} with 0x{word & mask:x} under 0x{mask:x}; "
                f"the entry must be disabled and unlocked before its registers take values"
            )
        ref = await self._read(x, "reference")
        assert ref & x.ref_zero == 0, (
            f"{x.name}: reference 0x{ref:x} has an enable set under 0x{x.ref_zero:x}"
        )
        return ref

    def _depth(self, label: str, evs: list[Ev], term: str) -> int:
        """Requests accepted before the first response of the group; at least 2 required."""
        first = min(e.cycle for e in evs if e.kind in ("r", "b"))
        depth = sum(1 for e in evs if e.kind in ("ar", "aw") and e.cycle < first)
        for chan in ("ar", "aw"):
            n = sum(1 for e in evs if e.kind == chan and e.cycle < first)
            self.tally[term].extra.setdefault(f"depth_{chan}", []).append(n)
        assert depth >= 2, (
            f"{label}: {depth} request(s) accepted before the first response at cycle {first}; "
            f"the group needs at least 2 outstanding"
        )
        self.tally[term].extra.setdefault("depth", []).append(depth)
        cocotb.log.info("MEASURE %s: outstanding depth %d", label, depth)
        return depth

    async def _pipelined_rw(self, x: Inst, ref: int, values) -> None:
        items = []
        for k in range(1, PIPELINED_PAIRS + 1):
            items.append(self._wr(x, f"prw_wr{k}", next(values), k))
            items.append(self._rd(x, f"prw_rd{k}", k))
        evs = await self._run(f"{x.name}_pipelined_rw", items)
        self._depth(f"{x.name}_pipelined_rw", evs, "PIPELINED-RW")
        strict, inflight = self._reads_vs_writes(f"{x.name}_pipelined_rw", items, evs, ref)
        t = self.tally["PIPELINED-RW"]
        t.instances += 1
        t.reads += PIPELINED_PAIRS
        t.strict += strict
        t.inflight += inflight
        await self._restore(x, ref, "prw")

    async def _pipelined_read(self, x: Inst, ref: int) -> None:
        items = [self._rd(x, f"pr_rd{k}", k, expected=ref) for k in range(1, PIPELINED_READS + 1)]
        evs = await self._run(f"{x.name}_pipelined_read", items)
        self._depth(f"{x.name}_pipelined_read", evs, "PIPELINED-READ")
        for item in items:
            assert item.rdata == ref, f"{x.name}: pipelined read 0x{item.rdata:x} != 0x{ref:x}"
        t = self.tally["PIPELINED-READ"]
        t.instances += 1
        t.reads += len(items)

    async def _b2b_same(self, x: Inst, ref: int) -> None:
        items = [self._rd(x, f"b2b_rd{k}", k, expected=ref) for k in (1, 2)]
        evs = await self._run(f"{x.name}_b2b_same", items)
        ars = [e.cycle for e in evs if e.kind == "ar"]
        self.b2b_gaps.append(ars[1] - ars[0])
        for item in items:
            assert item.rdata == ref, f"{x.name}: back-to-back read 0x{item.rdata:x} != 0x{ref:x}"
        t = self.tally["B2B-SAME"]
        t.instances += 1
        t.reads += 2

    async def _b2b_diff(self, x: Inst, ref: int, values) -> None:
        bx = Inst(x.name + "_B", x.family, x.b_addr, x.b_width, True, free=x.b_free)
        ref_b = await self._read(x, "b2b_ref_b", addr=x.b_addr, width=x.b_width)
        assert ref_b & x.b_zero == 0, (
            f"{x.name}: second register reads 0x{ref_b:x} with 0x{ref_b & x.b_zero:x} set "
            f"under 0x{x.b_zero:x}"
        )
        wa = next(values)
        wb = next(v for v in self._values(bx, ref_b) if v != wa)
        await self._write(x, "b2b_wa", wa)
        await self._write(x, "b2b_wb", wb, addr=x.b_addr, width=x.b_width)
        ra = self._rd(x, "b2b_ra", 1)
        rb = self._rd(x, "b2b_rb", 2, addr=x.b_addr, width=x.b_width)
        evs = await self._run(f"{x.name}_b2b_diff", [ra, rb])
        ars = [e.cycle for e in evs if e.kind == "ar"]
        self.b2b_diff_gaps.append(ars[1] - ars[0])
        assert ra.rdata == wa, f"{x.name}: readA 0x{ra.rdata:x}, wrote 0x{wa:x}"
        assert rb.rdata & x.b_cmp == wb & x.b_cmp, (
            f"{x.name}: readB 0x{rb.rdata:x}, wrote 0x{wb:x} (compared under 0x{x.b_cmp:x})"
        )
        await self._write(x, "b2b_b_restore", ref_b, addr=x.b_addr, width=x.b_width)
        got = await self._read(x, "b2b_b_restore_rb", addr=x.b_addr, width=x.b_width)
        assert got & x.b_cmp == ref_b & x.b_cmp, (
            f"{x.name}: second register restore read 0x{got:x}, reference 0x{ref_b:x}"
        )
        await self._restore(x, ref, "b2b")
        self.tally["B2B-DIFF"].instances += 1

    def _lead(self, label: str, evs: list[Ev], want: int) -> int:
        w = [e.cycle for e in evs if e.kind == "wstart"]
        aw = [e.cycle for e in evs if e.kind == "awstart"]
        assert len(w) == 1 and len(aw) == 1, f"{label}: W starts {w}, AW starts {aw}"
        lead = aw[0] - w[0]
        assert lead == want, (
            f"{label}: W VALID rose at cycle {w[0]} and AW VALID at {aw[0]}, a lead of {lead} "
            f"cycles where {want} was driven"
        )
        return lead

    async def _w_ahead(self, x: Inst, ref: int, values) -> None:
        for lead in W_LEADS:
            v = next(values)
            label = f"{x.name}_w_ahead{lead}"
            evs = await self._run(label, [self._wr(x, f"wa{lead}", v)], w_lead=lead)
            self.leads[lead].append(self._lead(label, evs, lead))
            got = await self._read(x, f"wa{lead}_rb", expected=v)
            assert got == v, f"{label}: readback 0x{got:x}, wrote 0x{v:x}"
        await self._restore(x, ref, "wa")
        self.tally["W-AHEAD"].instances += 1

    async def _w_ahead_writeback(self, x: Inst, ref: int) -> None:
        compared = x.pinned
        first = await self._read(x, "wb_rd", expected=ref if compared else None)
        label = f"{x.name}_w_ahead_wb"
        evs = await self._run(
            label,
            [self._wr(x, "wb_wr", first)],
            w_lead=WRITEBACK_LEAD,
        )
        self.leads[WRITEBACK_LEAD].append(self._lead(label, evs, WRITEBACK_LEAD))
        bresp = [e.resp for e in evs if e.kind == "b"]
        after = await self._read(x, "wb_after", expected=ref if compared else None)
        t = self.tally["W-AHEAD-WB"]
        if compared:
            assert first == ref and after == ref, (
                f"{label}: read 0x{first:x}, wrote it back, read 0x{after:x}; reference 0x{ref:x}"
            )
            t.instances += 1
        else:
            t.extra[x.name] = (first, bresp, after)
            self.logged_writeback.append(x.name)
            cocotb.log.info(
                "MEASURE %s: read 0x%x, write-back BRESP %s, following read 0x%x "
                "(check set open, SF-001/SF-009)",
                label,
                first,
                bresp,
                after,
            )
        await self._writeback_sweep(x, ref, first, compared)

    async def _writeback_sweep(self, x: Inst, ref: int, value: int, compared: bool) -> None:
        """Write-backs of ``value`` with a read whose AR trails by each sweep offset."""
        expected = ref if compared else None
        reads = []
        for offset in SWEEP_OFFSETS:
            for tag, n_writes in (("wwr", 2), ("wr", 1)):
                items = [
                    self._wr(x, f"sw_{tag}{offset}_w{k}", value, k) for k in range(1, n_writes + 1)
                ]
                rd = self._rd(x, f"sw_{tag}{offset}_r", 1, expected=expected)
                await self._run(
                    f"{x.name}_sweep_{tag}{offset}",
                    [*items, rd],
                    timing=AxiTimingProfile(ar_delay=offset),
                )
                reads.append(rd)
        if compared:
            for rd in reads:
                assert rd.rdata == ref, (
                    f"{x.name}: sweep read 0x{rd.rdata:x} after write-backs, reference 0x{ref:x}"
                )
            self.sweep["compared"] += len(reads)
        else:
            equal = sum(1 for rd in reads if rd.rdata == value)
            self.sweep["logged"] += len(reads)
            self.sweep["logged_equal"] += equal
            cocotb.log.info(
                "MEASURE %s: %d sweep reads after write-backs of 0x%x, %d equal to it "
                "(check set open, SF-001/SF-009)",
                x.name,
                len(reads),
                value,
                equal,
            )

    def _held(self, label: str, evs: list[Ev], chan: str, cycles: int = HOLD_CYCLES) -> int:
        held = [e for e in evs if e.kind == f"{chan}held"]
        assert len(held) >= cycles, (
            f"{label}: {chan.upper()}VALID sat on a low ready for {len(held)} cycles, "
            f"the hold is {cycles}"
        )
        return len(held)

    def _long_head(self, label: str, evs: list[Ev], hold: tuple[str, ...]) -> None:
        """The head response stays VALID and unchanged for the whole long hold."""
        t = self.tally["LONG-HOLD"]
        for chan in hold:
            n = self._held(label, evs, chan, LONG_HOLD_CYCLES)
            head = next(e for e in evs if e.kind == chan)
            before = [e for e in evs if e.kind == f"{chan}held" and e.cycle < head.cycle]
            assert len(before) >= LONG_HOLD_CYCLES and all(e[2:] == head[2:] for e in before), (
                f"{label}: head {chan.upper()} response {head} held {len(before)} cycles "
                f"before its handshake, payloads {sorted({e[2:] for e in before})}"
            )
            t.extra.setdefault(f"held_{chan}", []).append(n)
        self.long_waits += 1 + len(hold)

    async def _rready_hold(self, x: Inst, ref: int) -> None:
        label = f"{x.name}_rready_hold"
        item = self._rd(x, "rh_rd", expected=ref)
        evs = await self._run(label, [item], hold=("r",))
        n = self._held(label, evs, "r")
        beats = [e for e in evs if e.kind == "r"]
        held = [e for e in evs if e.kind == "rheld"]
        assert all((h.ident, h.resp, h.data) == beats[0][2:] for h in held), (
            f"{label}: RID/RRESP/RDATA moved while held"
        )
        assert item.rdata == ref, f"{label}: RDATA 0x{item.rdata:x}, reference 0x{ref:x}"
        t = self.tally["RREADY-HOLD"]
        t.instances += 1
        t.extra.setdefault("held", []).append(n)

    async def _bready_hold(self, x: Inst, ref: int, values) -> None:
        label = f"{x.name}_bready_hold"
        v = next(values)
        evs = await self._run(label, [self._wr(x, "bh_wr", v)], hold=("b",))
        n = self._held(label, evs, "b")
        beats = [e for e in evs if e.kind == "b"]
        held = [e for e in evs if e.kind == "bheld"]
        assert all((h.ident, h.resp) == (beats[0].ident, beats[0].resp) for h in held), (
            f"{label}: BID/BRESP moved while held"
        )
        got = await self._read(x, "bh_rb", expected=v)
        assert got == v, f"{label}: readback 0x{got:x}, wrote 0x{v:x}"
        await self._restore(x, ref, "bh")
        t = self.tally["BREADY-HOLD"]
        t.instances += 1
        t.extra.setdefault("held", []).append(n)

    async def _held_group(
        self, x: Inst, ref: int, values, *, cycles: int = HOLD_CYCLES, term: str = "HELD-GROUP"
    ) -> None:
        t = self.tally[term]
        long = term == "LONG-HOLD"
        pfx = "lh" if long else "hg"
        label = f"{x.name}_{pfx}_held_reads"
        # One ID per channel, so AXI requires the responses in issue order.
        reads = [self._rd(x, f"{pfx}_rd{k}", 1, expected=ref) for k in range(1, HELD_DEPTH + 1)]
        evs = await self._run(label, reads, hold=("r",), hold_cycles=cycles)
        self._in_order(label, evs)
        if long:
            self._long_head(label, evs, ("r",))
        for item in reads:
            assert item.rdata == ref, f"{label}: read 0x{item.rdata:x} != 0x{ref:x}"
        t.reads += HELD_DEPTH
        t.strict += HELD_DEPTH

        label = f"{x.name}_{pfx}_held_mixed"
        mixed = []
        for k in range(1, HELD_DEPTH // 2 + 1):
            v = next(values) if x.pinned else ref
            mixed.append(self._wr(x, f"{pfx}_mwr{k}", v, 1))
            mixed.append(self._rd(x, f"{pfx}_mrd{k}", 1, expected=None if x.pinned else ref))
        evs = await self._run(label, mixed, hold=("b", "r"), hold_cycles=cycles)
        self._in_order(label, evs)
        if long:
            self._long_head(label, evs, ("b", "r"))
        if x.pinned:
            strict, inflight = self._reads_vs_writes(label, mixed, evs, ref)
            t.strict += strict
            t.inflight += inflight
        else:
            for item in mixed:
                if item.op is SmcSysAxiOp.READ:
                    assert item.rdata == ref, f"{label}: read 0x{item.rdata:x} != 0x{ref:x}"
            t.strict += HELD_DEPTH // 2
        t.reads += HELD_DEPTH // 2
        if x.pinned:
            await self._restore(x, ref, f"{pfx}_mixed")

        label = f"{x.name}_{pfx}_held_writes"
        wvals = [next(values) if x.pinned else ref for _ in range(HELD_DEPTH)]
        writes = [self._wr(x, f"{pfx}_wr{k + 1}", v, 1) for k, v in enumerate(wvals)]
        evs = await self._run(label, writes, hold=("b",), hold_cycles=cycles)
        self._in_order(label, evs)
        if long:
            self._long_head(label, evs, ("b",))
        last = wvals[-1]
        got = await self._read(x, f"{pfx}_wr_rb", expected=last)
        assert got == last, f"{label}: readback 0x{got:x}, last write 0x{last:x}"
        if x.pinned:
            await self._restore(x, ref, pfx)
        await self._held_spread(x, ref, cycles=cycles, pfx=pfx)
        t.instances += 1

    async def _held_spread(
        self, x: Inst, ref: int, *, cycles: int = HOLD_CYCLES, pfx: str = "hg"
    ) -> None:
        """16 reads and 16 write-backs of the reference, one ID each, behind a held ready.

        Requests with distinct IDs reach the block together where a same-ID group is
        serialised in front of it, so these groups back the held responses up to the
        block itself. AXI leaves their response order free, so only each value, the
        count and the readback are held.
        """
        long = pfx == "lh"
        tag = f"{pfx}_sp" if long else "sp"
        label = f"{x.name}_{tag}_reads"
        reads = [self._rd(x, f"{tag}_rd{k}", k, expected=ref) for k in range(1, HELD_DEPTH + 1)]
        evs = await self._run(label, reads, hold=("r",), hold_cycles=cycles)
        if long:
            self._long_head(label, evs, ("r",))
        for item in reads:
            assert item.rdata == ref, f"{label}: read 0x{item.rdata:x} != 0x{ref:x}"
        label = f"{x.name}_{tag}_writes"
        writes = [self._wr(x, f"{tag}_wr{k}", ref, k) for k in range(1, HELD_DEPTH + 1)]
        evs = await self._run(label, writes, hold=("b",), hold_cycles=cycles)
        if long:
            self._long_head(label, evs, ("b",))
        got = await self._read(x, f"{tag}_wr_rb", expected=ref)
        assert got == ref, f"{label}: readback 0x{got:x}, reference 0x{ref:x}"
        if long:
            self.tally["LONG-HOLD"].extra["spread"] = (
                self.tally["LONG-HOLD"].extra.get("spread", 0) + 2 * HELD_DEPTH
            )
        else:
            self.spread += 2 * HELD_DEPTH

    # -- body ------------------------------------------------------------

    async def _instance(self, x: Inst) -> dict[str, int]:
        times: dict[str, int] = {}
        saved_lcr = None
        if x.dlab_wrap is not None:
            lcr = uart_reg(x.dlab_wrap, "LCR")
            item = self._rd(x, "lcr_saved", addr=lcr, width=4)
            await self._run(f"{x.name}_lcr_saved", [item])
            saved_lcr = item.rdata
            await self._write(x, "lcr_dlab", saved_lcr | LCR_DLAB, addr=lcr, width=4)
        values = None

        cocotb.log.info("STEP S1: %s reference read of 0x%x", x.name, x.addr)
        ref = await self._reference(x)
        self._stamp(x, "REFERENCE", times)
        self.tally["REFERENCE"].instances += 1
        if x.pinned:
            values = self._values(x, ref)
            cocotb.log.info("STEP S2: %s pipelined %d writes / %d reads", x.name, 4, 4)
            await self._pipelined_rw(x, ref, values)
            self._stamp(x, "PIPELINED-RW", times)
        cocotb.log.info("STEP S3: %s %d pipelined reads", x.name, PIPELINED_READS)
        await self._pipelined_read(x, ref)
        self._stamp(x, "PIPELINED-READ", times)
        cocotb.log.info("STEP S4: %s two back-to-back reads", x.name)
        await self._b2b_same(x, ref)
        self._stamp(x, "B2B-SAME", times)
        if x.pinned:
            cocotb.log.info("STEP S5: %s back-to-back reads of two written registers", x.name)
            await self._b2b_diff(x, ref, values)
            self._stamp(x, "B2B-DIFF", times)
            cocotb.log.info("STEP S6: %s writes with W leading AW by %s", x.name, W_LEADS)
            await self._w_ahead(x, ref, values)
            self._stamp(x, "W-AHEAD", times)
        cocotb.log.info("STEP S7: %s write-back with W leading by %d", x.name, WRITEBACK_LEAD)
        await self._w_ahead_writeback(x, ref)
        self._stamp(x, "W-AHEAD-WB", times)
        cocotb.log.info("STEP S8: %s read with RREADY held %d cycles", x.name, HOLD_CYCLES)
        await self._rready_hold(x, ref)
        self._stamp(x, "RREADY-HOLD", times)
        if x.pinned:
            cocotb.log.info("STEP S9: %s write with BREADY held %d cycles", x.name, HOLD_CYCLES)
            await self._bready_hold(x, ref, values)
            self._stamp(x, "BREADY-HOLD", times)
        cocotb.log.info("STEP S10: %s held groups of %d", x.name, HELD_DEPTH)
        await self._held_group(x, ref, values)
        self._stamp(x, "HELD-GROUP", times)
        if x.name in self.long_hold:
            cocotb.log.info(
                "STEP S12: %s (family %s) held groups of %d behind a %d-cycle hold",
                x.name,
                self.long_hold[x.name],
                HELD_DEPTH,
                LONG_HOLD_CYCLES,
            )
            await self._held_group(x, ref, values, cycles=LONG_HOLD_CYCLES, term="LONG-HOLD")
            self._stamp(x, "LONG-HOLD", times)
            self.long_families.append(self.long_hold[x.name])

        if saved_lcr is not None:
            lcr = uart_reg(x.dlab_wrap, "LCR")
            await self._write(x, "lcr_restore", saved_lcr, addr=lcr, width=4)
            got = await self._read(x, "lcr_restore_rb", addr=lcr, width=4, expected=saved_lcr)
            assert got == saved_lcr, f"{x.name}: LCR restore read 0x{got:x}, saved 0x{saved_lcr:x}"
        return times

    def _fence(self, x: Inst, times: dict[str, int]) -> None:
        order = [
            t
            for t in TERMS
            if (x.pinned or t not in PINNED_ONLY_TERMS)
            and (t != "LONG-HOLD" or x.name in self.long_hold)
        ]
        assert list(times) == order, f"{x.name}: terms ran as {list(times)}, fence {order}"
        stamps = [times[t] for t in order]
        assert all(a < b for a, b in zip(stamps, stamps[1:])), (
            f"{x.name}: fence times {dict(zip(order, stamps))} are not strictly increasing"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_SMC_CYCLES)
        self.waits += 1
        self.mon = SepInMonitor(cocotb.top)
        mon_task = cocotb.start_soon(self.mon.run())
        try:
            # The mailbox apertures answer only with their clock enabled.
            cg = Inst("clock_gate_control", "smc_base_config", CLOCK_GATE_CONTROL, 8, False)
            saved_cg = await self._read(cg, "saved")
            await self._write(cg, "mailbox_on", saved_cg | MAILBOX_CG_EN)
            await self._read(cg, "mailbox_on_rb", expected=saved_cg | MAILBOX_CG_EN)
            for x in self.instances:
                times = await self._instance(x)
                self._fence(x, times)
            await self._write(cg, "restore", saved_cg)
            await self._read(cg, "restore_rb", expected=saved_cg)
        finally:
            self.mon.stop = True
            mon_task.cancel()

        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked only {sb.sys_axi_checks_seen} SEP_IN AXI item(s) but "
            f"this sequence issued {self.accesses}"
        )
        self._evidence()

    def _evidence(self) -> None:
        n_all = len(self.instances)
        n_pin = sum(1 for x in self.instances if x.pinned)
        t = self.tally
        assert t["REFERENCE"].instances == n_all
        assert sorted(self.long_families) == sorted(LONG_HOLD_FAMILIES), (
            f"long-hold legs ran on families {self.long_families}, the contract lists "
            f"{LONG_HOLD_FAMILIES}"
        )
        for term in TERMS:
            want = n_pin if term in PINNED_ONLY_TERMS else n_all
            if term == "LONG-HOLD":
                want = len(LONG_HOLD_FAMILIES)
            if term == "W-AHEAD-WB":
                assert t[term].instances + len(self.logged_writeback) == n_all
                continue
            assert t[term].instances == want, f"{term}: {t[term].instances} of {want} instances"

        prw = t["PIPELINED-RW"]
        prd = t["PIPELINED-READ"]
        hg = t["HELD-GROUP"]
        lh = t["LONG-HOLD"]
        assert prw.strict + prw.inflight == prw.reads == 4 * prw.instances
        assert hg.strict + hg.inflight == hg.reads
        assert lh.strict + lh.inflight == lh.reads
        rw_depth, rd_depth = prw.extra["depth"], prd.extra["depth"]
        rh, bh = t["RREADY-HOLD"].extra["held"], t["BREADY-HOLD"].extra["held"]
        for lead in (*W_LEADS, WRITEBACK_LEAD):
            assert set(self.leads[lead]) == {lead}, (
                f"W lead {lead}: measured {set(self.leads[lead])}"
            )
        cocotb.log.info(
            "MEASURE back-to-back AR handshake gaps (cycles) same min=%d max=%d, different "
            "registers min=%d max=%d; W-VALID-to-AW-VALID "
            "leads measured lead1=%s lead2=%s lead4=%s write-back=%s; held cycles RREADY "
            "min=%d max=%d BREADY min=%d max=%d; logged-only write-back instances %s; AR-offset "
            "write-back sweep 0..%d compared reads==reference %d/%d, logged-only reads %d (%d "
            "equal to the written-back value); distinct-ID held groups %d accesses, every read "
            "and readback == reference",
            min(self.b2b_gaps),
            max(self.b2b_gaps),
            min(self.b2b_diff_gaps),
            max(self.b2b_diff_gaps),
            sorted(set(self.leads[1])),
            sorted(set(self.leads[2])),
            sorted(set(self.leads[4])),
            sorted(set(self.leads[WRITEBACK_LEAD])),
            min(rh),
            max(rh),
            min(bh),
            max(bh),
            ",".join(self.logged_writeback),
            SWEEP_OFFSETS[-1],
            self.sweep["compared"],
            self.sweep["compared"],
            self.sweep["logged"],
            self.sweep["logged_equal"],
            self.spread,
        )
        cocotb.log.info(
            "CHK-CPUIF-PIPELINED-RW: %d instances x 8 txns, OKAY, depth min/max=%d/%d (>=2), "
            "reads==last-acked-write %d, reads==overlapping-write %d (SF-010, logged; per match "
            "AR/R/AW/B cycles), reads==no-write-of-group 0, a+b=%d; per-channel depth AR min/max=%d/%d AW min/max=%d/%d",
            prw.instances,
            min(rw_depth),
            max(rw_depth),
            prw.strict,
            prw.inflight,
            prw.strict + prw.inflight,
            min(prw.extra["depth_ar"]),
            max(prw.extra["depth_ar"]),
            min(prw.extra["depth_aw"]),
            max(prw.extra["depth_aw"]),
        )
        cocotb.log.info(
            "CHK-CPUIF-PIPELINED-READ: %d instances x 4 reads == reference, depth min/max=%d/%d "
            "(>=2)",
            prd.instances,
            min(rd_depth),
            max(rd_depth),
        )
        cocotb.log.info(
            "CHK-CPUIF-B2B-SAME: %d instances, 2/2 reads == reference, OKAY",
            t["B2B-SAME"].instances,
        )
        cocotb.log.info(
            "CHK-CPUIF-B2B-DIFF: %d instances, readA==wA readB==wB",
            t["B2B-DIFF"].instances,
        )
        cocotb.log.info(
            "CHK-CPUIF-W-AHEAD: %d instances x leads {1,2,4}, BRESP OKAY, readback==written",
            t["W-AHEAD"].instances,
        )
        cocotb.log.info(
            "CHK-CPUIF-W-AHEAD-WRITEBACK: %d compared instances read==reference, %d logged-only",
            t["W-AHEAD-WB"].instances,
            len(self.logged_writeback),
        )
        cocotb.log.info(
            "CHK-CPUIF-RREADY-HOLD: %d instances, 16/16 cycles stable, 1 completion, "
            "data==reference",
            t["RREADY-HOLD"].instances,
        )
        cocotb.log.info(
            "CHK-CPUIF-BREADY-HOLD: %d instances, 16/16 cycles stable, 1 B, readback==written",
            t["BREADY-HOLD"].instances,
        )
        cocotb.log.info(
            "CHK-CPUIF-HELD-GROUP: %d instances x 16, 16/16 in order, 0 lost, 0 duplicated, "
            "reads==reference-or-last-acked-write %d, reads==overlapping-write %d (SF-010, "
            "logged; per match AR/R/AW/B cycles), reads==no-write-of-group 0",
            hg.instances,
            hg.strict,
            hg.inflight,
        )
        cocotb.log.info(
            "CHK-CPUIF-LONG-HOLD: %d families x %d behind a %d-cycle hold, %d/%d in order, "
            "0 lost, 0 duplicated; reads==reference-or-last-acked-write %d, "
            "reads==overlapping-write %d (SF-010, logged; per match AR/R/AW/B cycles), "
            "reads==no-write-of-group 0; head held cycles RREADY min/max=%d/%d BREADY "
            "min/max=%d/%d, head unchanged while held; distinct-ID groups %d accesses; "
            "instances %s",
            lh.instances,
            HELD_DEPTH,
            LONG_HOLD_CYCLES,
            HELD_DEPTH,
            HELD_DEPTH,
            lh.strict,
            lh.inflight,
            min(lh.extra["held_r"]),
            max(lh.extra["held_r"]),
            min(lh.extra["held_b"]),
            max(lh.extra["held_b"]),
            lh.extra["spread"],
            ",".join(f"{fam}={name}" for name, fam in self.long_hold.items()),
        )
        counts = ", ".join(
            f"{term}: n={len(self.stamps[term])} first={self.stamps[term][0]}ps "
            f"last={self.stamps[term][-1]}ps"
            for term in TERMS
        )
        cocotb.log.info(
            "CHK-NONVAC: %s (per instance) (counts and times per term: %s; %d instances, %d "
            "pinned-map, %d SEP_IN accesses)",
            " < ".join(TERMS),
            counts,
            n_all,
            n_pin,
            self.accesses,
        )
        cocotb.log.info(
            "MEASURE bounds: group wait %d ns (expiry reports the outstanding count and the last "
            "SEP_IN record), held-ready and held-AW VALID wait %d clk_smc_i cycles (expiry reports "
            "the last VALID level), fuse sense %d cycles, driver 50 us per access",
            GROUP_BOUND_NS,
            VALID_BOUND_CYCLES,
            FUSE_SENSE_MAX_SMC_CYCLES,
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, 0 expired; "
            "S12 long-hold waits %d (group %d ns and held-ready VALID %d clk_smc_i cycles, "
            "expiry reports the outstanding count)",
            self.waits,
            self.long_waits,
            GROUP_BOUND_NS,
            VALID_BOUND_CYCLES,
        )
