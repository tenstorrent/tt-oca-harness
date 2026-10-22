# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_007 ANCHOR: smc_axil_endpoint_prot_sweep_test
# DV-TESTCASE-CONTRACT-REVISION: 3 RECORD-SHA256: dc47a2b61b4edb0599729c5ce139a1ec08ebd24ae4262a16e3f82a5fb86c790c
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 3 ENV: cocotb
"""Request attributes carried from SEP_IN to every AXI-Lite register endpoint.

``fabric.adoc`` (Protection Bit Pass-Through) passes every protection bit
through the fabric unmodified, and ``memory_map.adoc`` gives each endpoint its
window and response. So an endpoint must answer a request the same whatever
AxPROT, AxUSER, AxREGION, AxQOS, AxLOCK, AxCACHE, AxLEN or AxID it carries.

The check set holds one register per endpoint: every internal-crossbar target
but the DTP CSR port, which has no responder below the SMU (SF-040),
each of the 32 filter entries, one mailbox port, every peripheral-crossbar
target, the data-accelerator control windows and the DFD/CLA window. Each probe
is a plain read-write register, checked against the generated contract before
any access, so a write of the value it holds changes nothing.

Each endpoint first takes a reference read with every attribute zero. Then, per
attribute value, it takes a read with that value, a write-back of the reference
with the same value and a zero-attribute read. On a compared endpoint the read
and the zero-attribute read must answer OKAY with the reference and the write
OKAY. A measure-and-log endpoint logs every response and word and compares
nothing; these are the endpoints whose content or reach is open
(data-accelerator control, DFD), the two eFuse windows on the AxPROT leg, and
the response code of every AxLOCK = 1 access. AxLEN > 0 is driven only on the
burst set the contract names, whose footprint lies in side-effect-free
read-write registers; there each beat and the footprint are logged.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr
from .smc_axi_port_response_recorder import SmcAxiPortResponseRecorder
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_mailbox_data_error_test_seq import CLOCK_GATE_CONTROL, MAILBOX_CG_EN
from .smc_rdl_regmap import rdl_contract

BASE = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")
RESP_OKAY = 0
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}

# Bound on every response wait the sequence takes; the driver's own bound sits
# behind it.
RESP_BOUND_NS = 20_000
FUSE_SENSE_MAX_SMC_CYCLES = 200_000
# Clocks the passive response recorder is given to log a beat the driver has
# already completed.
RECORDER_BOUND_CYCLES = 16

SEED_PATTERN = 0x9E37_79B9_7F4A_7C15
# The reset-unit probe, which the debug manager also reads.
RESET_UNIT_PROBE = "smc_reset_unit/ISOLATE_REQ_FLR_COUNTER_VALUE"

PROT_VALUES = (0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x0)
# Which AxUSER bits carry the source ID is open (SF-005), so the sweep walks a
# one over all twelve.
USER_VALUES = (0xFFF, *(1 << bit for bit in range(12)), 0x000)
REGION_VALUES = (0x1, 0x2, 0x4, 0x8, 0xF, 0x0)
QOS_VALUES = (0x1, 0x2, 0x4, 0x8, 0xF, 0x0)
LOCK_VALUES = (1, 0)
CACHE_VALUES = (0x1, 0x2, 0x3, 0x6, 0x7, 0xA, 0xB, 0xE, 0xF, 0x0)
ID_VALUES = (0x01, 0x15, 0x2A, 0x3F, 0x00)
OUTSTANDING_IDS = (0x01, 0x02, 0x03, 0x04)
DEBUG_PROTS = (0x3, 0x0)

TERMS = (
    "REFERENCE",
    "PROT",
    "DEBUG-MGR",
    "USER",
    "REGION",
    "QOS",
    "LOCK",
    "CACHE",
    "LEN",
    "ID",
    "OUTSTANDING",
)


@dataclass(frozen=True)
class Endpoint:
    """One register of the check set."""

    name: str
    cls: str
    addr: int
    width: int
    logged: bool = False
    efuse: bool = False
    # Bits the seed word may set; 0 leaves the probe at the value it holds.
    seed_mask: int = 0
    # Every seeded bit is a plain read-write field, so the reference must
    # read back the seed exactly.
    seed_exact: bool = False


# Seed every read-write field of the probe.
RW = -1
# The offset field of an output-remap region; `valid` stays clear, so the
# region never translates.
REMAP_OFFSET = (1 << 56) - 1


def _probe(
    name: str,
    cls: str,
    path: str,
    *,
    logged: bool = False,
    efuse: bool = False,
    seed: int = 0,
):
    reg = rdl_contract(path)
    for field in reg.fields:
        assert not field.read_action, f"{name}: {path}.{field.name} has a read action"
        assert not field.modified_write, f"{name}: {path}.{field.name} has a modified write"
        assert field.access != "write-only", f"{name}: {path}.{field.name} is write-only"
    writable = 0
    for field in reg.fields:
        if field.access == "read-write":
            writable |= field.mask
    mask = writable if seed == RW else seed
    assert mask & ~writable == 0, f"{name}: seed mask 0x{mask:x} reaches a non-writable bit"
    exact = mask & ~reg.rw_mask == 0
    return Endpoint(name, cls, reg.addr, reg.width_bytes, logged, efuse, mask, exact)


def check_set() -> tuple[Endpoint, ...]:
    eps = [
        _probe(
            "reset_unit",
            "periph-ctrl",
            RESET_UNIT_PROBE,
            seed=RW,
        ),
        _probe("misc", "periph-ctrl", "smc_misc_wrap/scratch_cold/SCRATCH[0]", seed=RW),
        _probe("avsbus", "periph-ctrl", "smc_avsbus_controller/AVS_CFG_0"),
        *(
            _probe(f"i2c{i}", "periph-ctrl", f"smc_i2c_wrap/i2c[{i}]/HOST_FIFO_CONFIG", seed=RW)
            for i in range(3)
        ),
        _probe("uart", "periph-ctrl", "smc_uart_wrap/uart_log_engine_wrap[0]/uart/SCR", seed=RW),
        *(
            _probe(
                f"log_engine{i}",
                "periph-ctrl",
                f"smc_uart_wrap/uart_log_engine_wrap[{i}]/log_engine/LOG_REGION_SIZE",
                seed=RW,
            )
            for i in range(4)
        ),
        _probe(
            "telemetry",
            "periph-ctrl",
            "smc_telemetry_receiver_wrap/telemetry_receiver[0]/INTR_ENABLE",
            seed=0x1,
        ),
        _probe("octs", "periph-ctrl", "smc_system_timer_octs/TIMER_PRESET_LO", seed=RW),
        _probe("i3c", "periph-ctrl", "oca_i3c_wrap/i3c_csr[0]/I3CBase/DEV_CTX_BASE_LO", seed=RW),
        _probe("efuse_map", "efuse", "smc_efuse_map/I2C_I3C_ID[0]", efuse=True, seed=RW),
        _probe("efuse_intf", "efuse", "efuse_interface_ctrl/EFUSE_READ_REQ_TIMEOUT", efuse=True),
        _probe("gpio", "internal-regs", "gpio_intf[0]/ACCESS_FILTER"),
        _probe("dfx", "internal-regs", "dfx_ctrl/DEBUG_BUS_MUX", seed=0xFF00),
        _probe(
            "base_config", "internal-regs", "smc_base_config/HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD"
        ),
        _probe("cpu_ctrl", "internal-regs", "smc_cpu_ctrl/SCRATCH[15]", seed=RW),
        _probe("alias_remap", "remap-ctrl", "smc_alias_remap[0]/REGION/region_start", seed=RW),
        _probe(
            "mmode_remap",
            "remap-ctrl",
            "smc_mmode_remap[0]/REGION/region_attrs",
            seed=REMAP_OFFSET,
        ),
        _probe(
            "xvisor_remap",
            "remap-ctrl",
            "smc_xvisor_remap[0]/REGION/region_attrs",
            seed=REMAP_OFFSET,
        ),
        *(
            _probe(
                f"in_filter{i}", "filter-entry", f"smc_inbound_filter_ctrl[{i}]/START_ADDR", seed=RW
            )
            for i in range(16)
        ),
        *(
            _probe(
                f"out_filter{i}",
                "filter-entry",
                f"smc_outbound_filter_ctrl[{i}]/START_ADDR",
                seed=RW,
            )
            for i in range(16)
        ),
        # WIRQT reduces a value at or above the mailbox depth to depth - 1
        # (axil_mailbox.adoc), so the seed stays at 1, which every depth keeps.
        _probe("mailbox", "mailbox", "smc_mailbox/inbound_mailbox_0/WIRQT", seed=0x1),
        _probe("zeroer_ctrl", "dacc-ctrl", "zeroer_ctrl/DEST_ADDR", logged=True),
        _probe("dma_ctrl", "dacc-ctrl", "dma_ctrl/DST_ADDRESS_LO", logged=True),
        _probe("cla", "dfd-window", "smc_cla/dst_sink/ScratchLo", logged=True),
    ]
    assert len({ep.addr for ep in eps}) == len(eps), "two endpoints share an address"
    return tuple(eps)


CLASS_ORDER = (
    "internal-regs",
    "filter-entry",
    "remap-ctrl",
    "mailbox",
    "periph-ctrl",
    "efuse",
    "dacc-ctrl",
    "dfd-window",
)


class SmcArWatch:
    """Record the sim time of every AR handshake on one flat AXI port."""

    def __init__(self, dut, prefix: str) -> None:
        self.dut = dut
        self.prefix = prefix
        self.stop = False
        self.times: list[int] = []

    def mark(self) -> int:
        return len(self.times)

    def since(self, mark: int) -> list[int]:
        return self.times[mark:]

    async def run(self) -> None:
        valid = getattr(self.dut, f"{self.prefix}_arvalid")
        ready = getattr(self.dut, f"{self.prefix}_arready")
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            assert valid.value.is_resolvable and ready.value.is_resolvable, (
                f"{self.prefix} AR handshake is X/Z: valid={valid.value} ready={ready.value}"
            )
            if int(valid.value) and int(ready.value):
                self.times.append(int(get_sim_time("ps")))


def seed_word(index: int, mask: int) -> int:
    """A distinctive word per endpoint inside `mask`, never zero."""
    word = (SEED_PATTERN * (index + 1)) & ((1 << 64) - 1) & mask
    return word if word else mask & -mask


@dataclass(frozen=True)
class Burst:
    """One AxLEN > 0 leg: `beats` 8-byte beats over a footprint of `regs`."""

    label: str
    regs: tuple[str, ...]
    beats: int


BURST_SET = (
    *(
        Burst(
            f"out-remap-mmode len{n - 1}",
            tuple(f"smc_mmode_remap[{i}]/REGION/region_attrs" for i in range(n)),
            n,
        )
        for n in (2, 4, 8)
    ),
    *(
        Burst(
            f"out-remap-xvisor len{n - 1}",
            tuple(f"smc_xvisor_remap[{i}]/REGION/region_attrs" for i in range(n)),
            n,
        )
        for n in (2, 4, 8)
    ),
    Burst(
        "alias-remap len1",
        ("smc_alias_remap[0]/REGION/region_start", "smc_alias_remap[0]/REGION/region_end"),
        2,
    ),
    Burst(
        "reset-unit len1",
        (
            "smc_reset_unit/SS_CONFIG_HOLD",
            "smc_reset_unit/SS_SRAM_HOLD",
            "smc_reset_unit/SS_CRITICAL_HOLD",
            "smc_reset_unit/SS_DEBUG_HOLD",
        ),
        2,
    ),
)


@dataclass(frozen=True)
class Attrs:
    prot: int = 0
    user: int = 0
    region: int = 0
    qos: int = 0
    lock: int = 0
    cache: int = 0
    axi_id: int = 0

    def __str__(self) -> str:
        return (
            f"prot=0x{self.prot:x} user=0x{self.user:03x} region=0x{self.region:x} "
            f"qos=0x{self.qos:x} lock={self.lock} cache=0x{self.cache:x} id=0x{self.axi_id:02x}"
        )


ZERO = Attrs()


@dataclass
class LegTally:
    endpoints: int = 0
    values: int = 0
    reads_ok: int = 0
    reads: int = 0
    writebacks: int = 0
    logged: int = 0


def _resp(code: int | None) -> str:
    return _RESP_NAME.get(code, str(code))


class smc_axil_endpoint_prot_sweep_test_seq(SmcCsrSeq):
    """Sweep each request attribute over every AXI-Lite endpoint of the check set."""

    def __init__(self, name: str = "smc_axil_endpoint_prot_sweep_test_seq") -> None:
        super().__init__(name)
        self.endpoints: tuple[Endpoint, ...] = ()
        self.reference: dict[str, tuple[int | None, int]] = {}
        self.stamps: list[tuple[str, int, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.waits = 0
        self.jtag_accesses = 0
        self.last = "none"
        self.recorder: SmcAxiPortResponseRecorder | None = None
        self.measured: list[str] = []
        self.lock1_resps: set[str] = set()
        self.preseed: dict[str, int] = {}
        self.debug_reg = RESET_UNIT_PROBE.rsplit("/", 1)[1]
        self.ar_watch: SmcArWatch | None = None
        self.seeds: dict[str, int] = {}

    # -- primitives ------------------------------------------------------

    def _stamp(self, term: str, count: int) -> None:
        assert count > 0, f"term {term} ran no access"
        self.stamps.append((term, count, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _item(
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        width: int,
        attrs: Attrs,
        *,
        wdata: int = 0,
        expected: int | None = None,
        tolerate: bool = False,
        beats: int = 1,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(label)
        item.op = op
        item.addr = addr
        item.length = width
        item.beats = beats
        item.wdata = wdata
        item.expected = expected
        item.allow_error = tolerate
        item.prot = attrs.prot
        item.axi_user = attrs.user
        item.axi_region = attrs.region
        item.axi_qos = attrs.qos
        item.axi_lock = attrs.lock
        item.axi_cache = attrs.cache
        item.axi_id = attrs.axi_id
        return item

    async def _drive(self, what, desc: str, *, jtag: bool = False) -> None:
        """Run one item or group under the response bound, failing with the request list."""
        self.last = desc
        try:
            if jtag:
                await with_timeout(
                    _OneShot(what, f"{what.get_name()}_os").start(
                        self.env.jtag_axi_agent.sequencer
                    ),
                    RESP_BOUND_NS,
                    "ns",
                )
            else:
                await self.start_item(what)
                await with_timeout(self.finish_item(what), RESP_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"no response within {RESP_BOUND_NS} ns; outstanding: {desc}"
            ) from exc
        self.waits += 1
        members = what.items if isinstance(what, SmcSysAxiGroupItem) else [what]
        if jtag:
            self.jtag_accesses += len(members)
        else:
            self.accesses += len(members)

    async def _access(
        self,
        label: str,
        op: SmcSysAxiOp,
        ep: Endpoint,
        attrs: Attrs,
        *,
        wdata: int = 0,
        expected: int | None = None,
        tolerate: bool = False,
        capture: bool = False,
    ) -> SmcSysAxiItem:
        item = self._item(
            label, op, ep.addr, ep.width, attrs, wdata=wdata, expected=expected, tolerate=tolerate
        )
        item.capture_resp_id = capture
        await self._drive(item, f"{op.value} {ep.name} 0x{ep.addr:08x} {attrs}")
        assert not item.timed_out, f"{label}: {ep.name} timed out"
        return item

    def _measure(self, text: str) -> None:
        cocotb.log.info("MEASURE %s", text)
        self.measured.append(text)

    def _mask(self, ep: Endpoint) -> int:
        return (1 << (8 * ep.width)) - 1

    # -- one attribute value on one endpoint -------------------------------

    async def _probe_value(
        self,
        leg: str,
        ep: Endpoint,
        attrs: Attrs,
        tally: LegTally,
        *,
        logged: bool,
        resp_logged: bool = False,
        check_ids: bool = False,
    ) -> None:
        ref_resp, ref = self.reference[ep.name]
        mask = self._mask(ep)
        tag = f"{leg}_{ep.name}_{attrs.prot:x}{attrs.user:03x}{attrs.region:x}{attrs.qos:x}"
        tag += f"{attrs.lock:x}{attrs.cache:x}{attrs.axi_id:02x}"
        tolerate = logged or resp_logged
        rd = await self._access(
            f"rd_{tag}",
            SmcSysAxiOp.READ,
            ep,
            attrs,
            expected=None if logged else ref,
            tolerate=tolerate,
            capture=check_ids,
        )
        wr = await self._access(
            f"wr_{tag}",
            SmcSysAxiOp.WRITE,
            ep,
            attrs,
            wdata=ref,
            tolerate=tolerate,
            capture=check_ids,
        )
        after = await self._access(
            f"chk_{tag}",
            SmcSysAxiOp.READ,
            ep,
            ZERO,
            expected=None if logged else ref,
            tolerate=logged,
        )
        tally.reads += 1
        if logged:
            tally.logged += 1
            self._measure(
                f"{leg} {ep.name} 0x{ep.addr:08x} {attrs}: rresp={_resp(rd.resp_code)} "
                f"rdata=0x{rd.rdata & mask:x} bresp={_resp(wr.resp_code)} "
                f"after rresp={_resp(after.resp_code)} rdata=0x{after.rdata & mask:x} "
                f"(reference rresp={_resp(ref_resp)} 0x{ref:x})"
            )
            return
        if resp_logged:
            self.lock1_resps.update({f"R:{_resp(rd.resp_code)}", f"B:{_resp(wr.resp_code)}"})
            self._measure(
                f"{leg} {ep.name} 0x{ep.addr:08x} {attrs}: rresp={_resp(rd.resp_code)} "
                f"bresp={_resp(wr.resp_code)}"
            )
        else:
            assert rd.resp_code == RESP_OKAY, (
                f"{leg}: {ep.name} read with {attrs} answered {_resp(rd.resp_code)}"
            )
            assert wr.resp_code == RESP_OKAY, (
                f"{leg}: {ep.name} write-back with {attrs} answered {_resp(wr.resp_code)}"
            )
        assert rd.rdata & mask == ref, (
            f"{leg}: {ep.name} read with {attrs} returned 0x{rd.rdata & mask:x}, "
            f"reference 0x{ref:x}"
        )
        assert after.resp_code == RESP_OKAY and after.rdata & mask == ref, (
            f"{leg}: after the write-back with {attrs}, {ep.name} answered "
            f"{_resp(after.resp_code)} 0x{after.rdata & mask:x}, reference 0x{ref:x}"
        )
        if check_ids:
            assert rd.rid == attrs.axi_id, (
                f"{leg}: {ep.name} read with AxID 0x{attrs.axi_id:02x} answered RID {rd.rid}"
            )
            assert wr.bid == attrs.axi_id, (
                f"{leg}: {ep.name} write with AxID 0x{attrs.axi_id:02x} answered BID {wr.bid}"
            )
        tally.reads_ok += 1
        tally.writebacks += 1

    async def _leg(
        self, leg: str, values: tuple[int, ...], make, *, check_ids: bool = False
    ) -> LegTally:
        tally = LegTally(values=len(values))
        for ep in self.endpoints:
            for value in values:
                attrs = make(value)
                logged = ep.logged or (leg == "PROT" and ep.efuse)
                await self._probe_value(
                    leg,
                    ep,
                    attrs,
                    tally,
                    logged=logged,
                    resp_logged=attrs.lock == 1,
                    check_ids=check_ids,
                )
        tally.endpoints = sum(
            1 for ep in self.endpoints if not (ep.logged or (leg == "PROT" and ep.efuse))
        )
        compared = tally.endpoints * tally.values
        assert tally.reads_ok == compared, (
            f"{leg}: {tally.reads_ok} compared reads held, expected {compared}"
        )
        return tally

    def _leg_line(self, tally: LegTally, leg: str = "") -> str:
        n, m = tally.endpoints, tally.values
        logged_eps = tally.logged // m if m else 0
        nonzero = sum(
            1
            for ep in self.endpoints
            if not (ep.logged or (leg == "PROT" and ep.efuse)) and self.reference[ep.name][1]
        )
        return (
            f"{n} endpoints x {m} values, reads==reference {tally.reads_ok}/{n * m}, "
            f"write-backs unchanged, logged-only={logged_eps}, "
            f"nonzero-reference={nonzero}/{n} ({len(self.seeds)} seeded)"
        )

    # -- recorder ----------------------------------------------------------

    async def _beats_since(self, mark: int, chan: str, count: int, what: str):
        rec = self.recorder
        assert rec is not None, "the response recorder is not running"
        for _ in range(RECORDER_BOUND_CYCLES):
            got = [e for e in rec.since(mark) if e.chan == chan]
            if len(got) >= count:
                self.waits += 1
                return got
            await RisingEdge(cocotb.top.clk_smc_i)
        got = [e for e in rec.since(mark) if e.chan == chan]
        raise AssertionError(
            f"{what}: the recorder saw {len(got)} {chan.upper()} beat(s) of {count} within "
            f"{RECORDER_BOUND_CYCLES} clk_smc_i after the driver completed; last {got[-1:]}"
        )

    # -- legs --------------------------------------------------------------

    async def _seed(self) -> int:
        """Write a distinctive non-reset word into every seeded probe."""
        for index, ep in enumerate(self.endpoints):
            if not ep.seed_mask:
                continue
            pre = await self._access(f"preseed_{ep.name}", SmcSysAxiOp.READ, ep, ZERO)
            assert pre.resp_code == RESP_OKAY, (
                f"pre-seed read of {ep.name} answered {_resp(pre.resp_code)}"
            )
            held = pre.rdata & self._mask(ep)
            value = (held & ~ep.seed_mask) | seed_word(index, ep.seed_mask)
            assert value != held, f"{ep.name}: the seed 0x{value:x} equals the held word"
            wr = await self._access(f"seed_{ep.name}", SmcSysAxiOp.WRITE, ep, ZERO, wdata=value)
            assert wr.resp_code == RESP_OKAY, (
                f"seed write of {ep.name} answered {_resp(wr.resp_code)}"
            )
            self.preseed[ep.name] = held
            self.seeds[ep.name] = value
        return len(self.seeds)

    async def _unseed(self) -> None:
        for ep in self.endpoints:
            if ep.name not in self.preseed:
                continue
            held = self.preseed[ep.name]
            await self._access(f"unseed_{ep.name}", SmcSysAxiOp.WRITE, ep, ZERO, wdata=held)
            await self._access(f"unseed_rb_{ep.name}", SmcSysAxiOp.READ, ep, ZERO, expected=held)

    async def _reference(self) -> int:
        for ep in self.endpoints:
            item = await self._access(
                f"ref_{ep.name}", SmcSysAxiOp.READ, ep, ZERO, tolerate=ep.logged
            )
            data = item.rdata & self._mask(ep)
            if not ep.logged:
                assert item.resp_code == RESP_OKAY, (
                    f"reference read of {ep.name} answered {_resp(item.resp_code)}"
                )
                assert data != 0, (
                    f"the reference of {ep.name} is 0x0, the word an in-extent hole "
                    f"answers, so its data compare could not tell the two apart"
                )
            if ep.name in self.seeds and ep.seed_exact:
                assert data == self.seeds[ep.name], (
                    f"{ep.name} reads 0x{data:x} after the seed write of 0x{self.seeds[ep.name]:x}"
                )
            self.reference[ep.name] = (item.resp_code, data)
            cocotb.log.info(
                "REFERENCE %s %s 0x%08x: rresp=%s rdata=0x%x%s%s",
                ep.cls,
                ep.name,
                ep.addr,
                _resp(item.resp_code),
                data,
                f" seeded=0x{self.seeds[ep.name]:x}" if ep.name in self.seeds else " unseeded",
                " (measure-and-log)" if ep.logged else "",
            )
        return len(self.endpoints)

    async def _prot(self) -> LegTally:
        tally = await self._leg("PROT", PROT_VALUES, lambda v: Attrs(prot=v))
        for ep in self.endpoints:
            ref_resp, ref = self.reference[ep.name]
            logged = ep.logged or ep.efuse
            item = await self._access(
                f"prot_final_{ep.name}",
                SmcSysAxiOp.READ,
                ep,
                ZERO,
                expected=None if logged else ref,
                tolerate=logged,
            )
            data = item.rdata & self._mask(ep)
            if logged:
                self._measure(
                    f"PROT final {ep.name}: rresp={_resp(item.resp_code)} rdata=0x{data:x} "
                    f"(reference {_resp(ref_resp)} 0x{ref:x})"
                )
            else:
                assert item.resp_code == RESP_OKAY and data == ref, (
                    f"PROT: closing read of {ep.name} answered {_resp(item.resp_code)} "
                    f"0x{data:x}, reference 0x{ref:x}"
                )
        return tally

    async def _debug_manager(self) -> list[tuple[int, int | None, int]]:
        ep = next(e for e in self.endpoints if e.name == "reset_unit")
        _ref_resp, ref = self.reference[ep.name]
        seen = []
        for prot in DEBUG_PROTS:
            item = self._item(
                f"jtag_rd_reset_unit_prot{prot}",
                SmcSysAxiOp.READ,
                ep.addr,
                ep.width,
                Attrs(prot=prot),
                expected=ref,
                tolerate=True,
            )
            item.axi_id = None
            await self._drive(
                item, f"JTAG read {ep.name} 0x{ep.addr:08x} prot=0x{prot:x}", jtag=True
            )
            data = item.rdata & self._mask(ep)
            assert not item.timed_out, f"JTAG read of {ep.name} with prot 0x{prot:x} timed out"
            assert data == ref, (
                f"JTAG read of {ep.name} with prot 0x{prot:x} returned 0x{data:x}, "
                f"SEP_IN reference 0x{ref:x}"
            )
            seen.append((prot, item.resp_code, data))
        return seen

    async def _bursts(self) -> list[str]:
        """The named burst set: log each beat and the footprint before and after."""
        notes = []
        monitor = getattr(self.env, "axi_monitor", None)
        burst_addrs: set[int] = set()
        for burst in BURST_SET:
            regs = [rdl_contract(path) for path in burst.regs]
            addrs = [r.addr for r in regs]
            assert all(b == a + r.width_bytes for a, b, r in zip(addrs, addrs[1:], regs)), (
                f"{burst.label}: footprint {[hex(a) for a in addrs]} is not contiguous"
            )
            assert sum(r.width_bytes for r in regs) == 8 * burst.beats, (
                f"{burst.label}: footprint is not {burst.beats} beats of 8 bytes"
            )
            if monitor is not None:
                monitor.expected_decerr_addrs.add(addrs[0])
                burst_addrs.add(addrs[0])
            before = []
            for reg in regs:
                ep = Endpoint(reg.path, "burst", reg.addr, reg.width_bytes)
                item = await self._access(f"burst_pre_{reg.path}", SmcSysAxiOp.READ, ep, ZERO)
                assert item.resp_code == RESP_OKAY, (
                    f"{burst.label}: footprint read of {reg.path} answered {_resp(item.resp_code)}"
                )
                before.append(item.rdata & self._mask(ep))
            payload = 0
            shift = 0
            for reg, value in zip(regs, before):
                payload |= value << shift
                shift += 8 * reg.width_bytes

            mark = self.recorder.mark()
            rd = self._item(
                f"burst_rd_{burst.label}",
                SmcSysAxiOp.READ,
                addrs[0],
                8,
                ZERO,
                tolerate=True,
                beats=burst.beats,
            )
            await self._drive(rd, f"burst read {burst.label} 0x{addrs[0]:08x} x{burst.beats}")
            rbeats = await self._beats_since(mark, "r", burst.beats, burst.label)
            mark = self.recorder.mark()
            wr = self._item(
                f"burst_wr_{burst.label}",
                SmcSysAxiOp.WRITE,
                addrs[0],
                8,
                ZERO,
                wdata=payload,
                tolerate=True,
                beats=burst.beats,
            )
            await self._drive(wr, f"burst write {burst.label} 0x{addrs[0]:08x} x{burst.beats}")
            bbeats = await self._beats_since(mark, "b", 1, burst.label)

            after = []
            for reg in regs:
                ep = Endpoint(reg.path, "burst", reg.addr, reg.width_bytes)
                item = await self._access(
                    f"burst_post_{reg.path}", SmcSysAxiOp.READ, ep, ZERO, tolerate=True
                )
                after.append((item.resp_code, item.rdata & self._mask(ep)))
            restored = 0
            for reg, value, (_code, got) in zip(regs, before, after):
                if got != value:
                    ep = Endpoint(reg.path, "burst", reg.addr, reg.width_bytes)
                    await self._access(
                        f"burst_restore_{reg.path}", SmcSysAxiOp.WRITE, ep, ZERO, wdata=value
                    )
                    await self._access(
                        f"burst_restore_rb_{reg.path}",
                        SmcSysAxiOp.READ,
                        ep,
                        ZERO,
                        expected=value,
                    )
                    restored += 1
            beat_text = ",".join(
                f"{_resp(e.resp)}:0x{e.data:x}" if e.data is not None else f"{_resp(e.resp)}:X"
                for e in rbeats[: burst.beats]
            )
            note = (
                f"{burst.label} @0x{addrs[0] - BASE:x} beats={burst.beats} "
                f"read_data==footprint={(rd.rdata == payload)} rbeats=[{beat_text}] "
                f"bresp={_resp(bbeats[0].resp)} "
                f"footprint_after={[f'{_resp(c)}:0x{v:x}' for c, v in after]} "
                f"footprint_before={[f'0x{v:x}' for v in before]} restored={restored}"
            )
            self._measure(f"LEN burst {note}")
            notes.append(note)
        if monitor is not None:
            monitor.expected_decerr_addrs.difference_update(burst_addrs)
        return notes

    async def _outstanding(self) -> list[str]:
        notes = []
        for cls in CLASS_ORDER:
            ep = next(e for e in self.endpoints if e.cls == cls)
            ref_resp, ref = self.reference[ep.name]
            items = [
                self._item(
                    f"out_{ep.name}_id{axi_id}",
                    SmcSysAxiOp.READ,
                    ep.addr,
                    ep.width,
                    Attrs(axi_id=axi_id),
                    expected=None if ep.logged else ref,
                    tolerate=ep.logged,
                )
                for axi_id in OUTSTANDING_IDS
            ]
            mark = self.recorder.mark()
            ar_mark = self.ar_watch.mark()
            group = SmcSysAxiGroupItem(f"out_{ep.name}", items)
            await self._drive(
                group,
                f"{len(items)} outstanding reads of {ep.name} 0x{ep.addr:08x} "
                f"ids {[hex(i) for i in OUTSTANDING_IDS]}",
            )
            beats = await self._beats_since(mark, "r", len(items), f"outstanding {ep.name}")
            rids = sorted(e.ident for e in beats)
            assert rids == list(OUTSTANDING_IDS), (
                f"outstanding reads of {ep.name}: RIDs {rids}, issued {list(OUTSTANDING_IDS)}"
            )
            mask = self._mask(ep)
            for item in items:
                assert not item.timed_out, f"{item.get_name()} timed out"
                if not ep.logged:
                    assert item.resp_code == RESP_OKAY and item.rdata & mask == ref, (
                        f"outstanding read {item.get_name()} answered {_resp(item.resp_code)} "
                        f"0x{item.rdata & mask:x}, reference 0x{ref:x}"
                    )
            stalls = [e.time_ps for e in beats]
            ars = self.ar_watch.since(ar_mark)
            depth = sum(1 for t in ars if t <= min(stalls))
            note = (
                f"{cls}:{ep.name} rids={[hex(r) for r in rids]} "
                f"resp={[_resp(i.resp_code) for i in items]} "
                f"ar-accepted-before-first-r={depth} ar-handshakes={len(ars)} "
                f"r-beat times(ps)={stalls}"
            )
            self._measure(f"OUTSTANDING depth {cls}:{ep.name} {depth} of {len(ars)} ARs")
            if ep.logged:
                note += (
                    f" logged data={[hex(i.rdata & mask) for i in items]} "
                    f"(reference {_resp(ref_resp)} 0x{ref:x})"
                )
                self._measure(f"OUTSTANDING {note}")
            notes.append(note)
        return notes

    # -- body --------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_SMC_CYCLES)
        self.endpoints = check_set()
        monitor = getattr(self.env, "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update(ep.addr for ep in self.endpoints if ep.logged)

        clock_gate = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, length=8)
        await self.csr_write(
            "CLOCK_GATE_CONTROL_MAILBOX", CLOCK_GATE_CONTROL, clock_gate | MAILBOX_CG_EN, length=8
        )
        await self.csr_read(
            "CLOCK_GATE_CONTROL_MAILBOX_RB",
            CLOCK_GATE_CONTROL,
            expected=clock_gate | MAILBOX_CG_EN,
            length=8,
        )

        cocotb.log.info("STEP S1: seed and reference read of %d endpoints", len(self.endpoints))
        seeded = await self._seed()
        self._stamp("REFERENCE", await self._reference())
        cocotb.log.info("STEP S1: %d endpoints seeded before the reference", seeded)

        cocotb.log.info("STEP S2: AxPROT %s", [hex(v) for v in PROT_VALUES])
        efuse_addrs = {ep.addr for ep in self.endpoints if ep.efuse}
        if monitor is not None:
            monitor.expected_decerr_addrs.update(efuse_addrs)
        prot = await self._prot()
        if monitor is not None:
            monitor.expected_decerr_addrs.difference_update(efuse_addrs)
        self._stamp("PROT", prot.reads)
        efuse = sorted(ep.addr - BASE & ~0xFFF for ep in self.endpoints if ep.efuse)
        self._chk(
            "CHK-ATTR-PROT",
            f"{self._leg_line(prot, 'PROT')} logged-only-efuse=[{', '.join(f'0x{a:x}' for a in efuse)}]",
        )

        cocotb.log.info("STEP S3: debug manager (JTAG AXI) read with AxPROT 0x3 then 0x0")
        dbg = await self._debug_manager()
        self._stamp("DEBUG-MGR", len(dbg))
        self._chk(
            "CHK-ATTR-DEBUG-MANAGER",
            f"reg={self.debug_reg} reference=0x{self.reference['reset_unit'][1]:x} "
            + ", ".join(f"prot0x{p:x} data==reference(0x{d:x}) resp={_resp(c)}" for p, c, d in dbg),
        )

        cocotb.log.info("STEP S4: AxUSER %s", [hex(v) for v in USER_VALUES])
        user = await self._leg("USER", USER_VALUES, lambda v: Attrs(user=v))
        self._stamp("USER", user.reads)
        self._chk("CHK-ATTR-USER", self._leg_line(user))

        cocotb.log.info("STEP S5: AxREGION %s", [hex(v) for v in REGION_VALUES])
        region = await self._leg("REGION", REGION_VALUES, lambda v: Attrs(region=v))
        self._stamp("REGION", region.reads)
        self._chk("CHK-ATTR-REGION", self._leg_line(region))

        cocotb.log.info("STEP S6: AxQOS %s", [hex(v) for v in QOS_VALUES])
        qos = await self._leg("QOS", QOS_VALUES, lambda v: Attrs(qos=v))
        self._stamp("QOS", qos.reads)
        self._chk("CHK-ATTR-QOS", self._leg_line(qos))

        cocotb.log.info("STEP S7: AxLOCK %s", list(LOCK_VALUES))
        lock = await self._leg("LOCK", LOCK_VALUES, lambda v: Attrs(lock=v))
        self._stamp("LOCK", lock.reads)
        self._chk(
            "CHK-ATTR-LOCK",
            f"{self._leg_line(lock)} lock1-responses-observed={sorted(self.lock1_resps)}",
        )

        cocotb.log.info("STEP S8: AxCACHE %s", [hex(v) for v in CACHE_VALUES])
        cache = await self._leg("CACHE", CACHE_VALUES, lambda v: Attrs(cache=v))
        self._stamp("CACHE", cache.reads)
        self._chk("CHK-ATTR-CACHE", self._leg_line(cache))

        cocotb.log.info("STEP S9: AxLEN burst set, then AxLEN 0 on every endpoint")
        self.recorder = SmcAxiPortResponseRecorder(cocotb.top, "s_axi")
        recorder_task = cocotb.start_soon(self.recorder.run())
        self.ar_watch = SmcArWatch(cocotb.top, "s_axi")
        ar_task = cocotb.start_soon(self.ar_watch.run())
        bursts = await self._bursts()
        length = await self._leg("LEN", (0,), lambda _v: Attrs())
        self._stamp("LEN", length.reads + len(bursts))
        self._chk(
            "CHK-ATTR-LEN",
            f"{self._leg_line(length)} burst-set=[out-remap-mmode len1/3/7, "
            f"out-remap-xvisor len1/3/7, alias-remap len1, reset-unit len1] "
            f"burst-measured=[{'; '.join(bursts)}]",
        )

        cocotb.log.info("STEP S10: AxID %s", [hex(v) for v in ID_VALUES])
        ids = await self._leg("ID", ID_VALUES, lambda v: Attrs(axi_id=v), check_ids=True)
        self._stamp("ID", ids.reads)
        self._chk("CHK-ATTR-ID", f"{self._leg_line(ids)} RID/BID==AxID on every compared access")

        cocotb.log.info("STEP S11: 4 outstanding reads per endpoint class")
        outstanding = await self._outstanding()
        self._stamp("OUTSTANDING", 4 * len(outstanding))
        self._chk(
            "CHK-ATTR-ID-OUTSTANDING",
            f"{len(outstanding)} classes x 4 reads, RID set=={{0x01,0x02,0x03,0x04}}, "
            f"data==reference; {' | '.join(outstanding)}",
        )
        self.recorder.stop = True
        self.ar_watch.stop = True
        await recorder_task
        await ar_task
        await self._unseed()

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, clock_gate, length=8)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RESTORED", CLOCK_GATE_CONTROL, expected=clock_gate, length=8
        )

        sb = self.env.scoreboard
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked {sb.sys_axi_checks_seen} items, the sequence issued "
            f"{self.accesses} SEP_IN accesses"
        )
        jtag_done = sb.axi_accesses_by_bus.get("JTAG AXI", 0)
        assert jtag_done == len(DEBUG_PROTS), (
            f"the scoreboard booked {jtag_done} JTAG AXI accesses, expected {len(DEBUG_PROTS)}"
        )
        self._nonvac()

    def _nonvac(self) -> None:
        terms = tuple(t for t, _c, _w in self.stamps)
        assert terms == TERMS, f"terms {terms}, expected {TERMS}"
        times = [w for _t, _c, w in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"term times not increasing: {times}"
        chk_times = [w for _c, w in self.chk_marks]
        assert chk_times == sorted(chk_times), f"checker lines out of order: {self.chk_marks}"
        cocotb.log.info(
            "CHK-NONVAC: %s (counts and times per term: %s); checker lines %s",
            " < ".join(TERMS),
            ", ".join(f"{t}={c}@{w}ps" for t, c, w in self.stamps),
            ",".join(c for c, _w in self.chk_marks),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait: SEP_IN and JTAG "
            "response waits bound=%d ns each (driver backstop %d ns), expiry raises with the "
            "outstanding request list; recorder beat waits bound=%d clk_smc_i, expiry raises "
            "with the beats seen; wait_fuse_sense_done bound=%d clk_smc_i; last wait '%s'; "
            "0 expired",
            self.waits,
            RESP_BOUND_NS,
            self.cfg.axi_timeout_ns,
            RECORDER_BOUND_CYCLES,
            FUSE_SENSE_MAX_SMC_CYCLES,
            self.last,
        )
