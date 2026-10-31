# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each address-map row answers the cells that the generated memory map states.

Run mode: no_cpu (``lsu_stub_all_live``), real PROD fuse sense, the Key Manager
held in reset with no image. Randomization: every seed walks every cell of the
inventory; the seed draws the offset inside each cell, the row order, the SI
AxID (non-zero) and the burst start and AxLEN. The open-value legs draw from
their own stream (the seed XOR a leg salt), so the cell walk keeps its draws.

The expected cells come from ``hw/sys/sep/regs/gen/adoc/memory_map.adoc`` (Hole
in Extent and Past Extent columns, through ``env.sep_decode_resp``), the
``ocah_*`` annotations of ``hw/sys/sep/regs/include/sep_memory_map.rdl`` and the register
allocation of the generated IP-XACT (``seq_lib.sep_row_response_seq``). The
table states each cell for a 32-bit access at the inbound AXI port, so every
graded single beat uses AxSIZE 2 in both halves of the 64-bit data bus; an
AxSIZE 3 access is logged and not graded. The reset-control rows state what the
SEP CPU sees, so the reset-control cells are graded from the LSU.

Every SI access goes through inbound entry 0, which covers 0x1000_0000 to
0x1FFF_FFFF with read, write and burst allowed. The decoded registers answer
OKAY through that entry, so a DECERR in this leaf comes from the decode and not
from the filter.

CHK-ROW: response code and addressed data lane of every cell (Reserved, Past
Extent, Hole in Extent, live word), with X or Z in an error payload failing on
VCS. The SI live-word read uses the default SI attributes; the line logs the
attributes captured on the SI port. A hole write leaves its neighbour register unchanged; the in-extent write
of the same data to the neighbour changes it (control, run before the hole
writes of the unit).

CHK-SI-ID-ECHO: every SI access, OKAY and error rows alike, answers with the
drawn non-zero AxID on BID or RID, sampled from the m_axi response handshake.
Golden: a response carries the ID of its request (AMBA AXI IHI 0022), and the
SEP fabric "retains the AXI IDs needed for responses" across the AXI4-Lite
bridge (``hw/sys/sep/doc/fabric.adoc:22-23``).

CTRL-ROW-RAND: stimulus completeness. Every inventory cell was walked.

CHK-ROW-NOALIAS: a reset-control gap or tail write and an HMAC or KMAC hole
write leave the live reference register (``SW_RESET_N``, HMAC ``CFG``, a KMAC
``PREFIX`` word) unchanged; an in-extent write to the same register changes it
(control, run before the draws of that register).

CHK-ROW-CACHE: an OTBN register access answers OKAY with AxCACHE[1] = 0 and 1 on
both channels (``hw/sys/sep/doc/otbn.adoc``, OCAH Modifications). The AxCACHE of
each address handshake is captured on the LSU port and must equal the value of
the instance, so a request that does not carry the value fails the check.

CHK-ROW-KM: every Key Manager mailbox offset past its seven registers, and the
reserved span after it, answers DECERR with 0xBADCAB1E, and no baseline register
moves. The baseline control write of ``SEP_IRQ_ENABLE`` reads back.

CHK-ROW-BURST / CHK-ROW-BURST-CONTROL: an SI burst to the crypto region answers
DECERR on its single B response, or on every one of its AxLEN + 1 R beats
(no early burst termination, IHI 0022 A3.4.1; the RRESP of each beat comes
from the SI bus monitor in order), and lands no beat (``hw/sys/sep/doc/crypto.adoc``,
Single-Beat Access Only); a single beat at the same address answers its 32-bit
cell.

CHK-ROW-POOL-W / CHK-ROW-POOL-UNMAPPED: an SI 32-bit write to the entropy pool,
at a register word and at an unmapped offset, answers SLVERR; an SI 32-bit read
of an unmapped pool offset answers SLVERR with zero data on the addressed lane
(``hw/sys/sep/doc/entropy_pool.adoc``). Each line carries a positive probe: a
64-bit SI read of the pool ``STATUS`` answers OKAY just before the graded access.

CHK-ROW-SPI-BURST: an SI INCR burst of 32-bit beats that starts one or two beats
below the end of the 56-byte SPI host extent and crosses it in one 4 KB page.
The in-extent beats answer OKAY with the register values (staged values, or the
RDL reset of ``ERROR_STATUS``); every beat past the extent answers an error and
carries none of the staged non-zero register values. A write burst lands its
in-extent beats, answers a B response other than OKAY, and changes no other
stable SPI host register (``hw/sys/sep/doc/peripheral_subsystem.adoc``: the
error responder of ``sep_io`` answers only the beats past the extent). The
exact past-beat code and data are logged as ``OBS-ROW-SPI-BURST-CODE``.
CHK-ROW-SPI-BURST-CONTROL: the same burst shape wholly inside the extent answers
OKAY on every beat and lands every beat.

FCOV gate: the leaf opens its window (owner code 231) only around graded
accesses, and closes it on the first FAIL. The sampler holds each owned sample
and samples it only when the pass label ``row_pass`` rises after every check of
the instance passed; the leaf drops the held samples at the start of each graded
instance, so a logged or ungraded access fills no bin. The OTBN AxCACHE cells
sample only on the release of an OTBN cache instance, after CHK-ROW-CACHE.

CHK-ROW-FILTER-SRC: with inbound entry 0 set to a drawn non-zero ``src_id``,
an SI read of the inbound filter entry 1 ``START_ADDR`` word whose AxUSER
equals ``src_id`` answers OKAY with the LSU read-back, as the read through the
wildcard entry just before does, and a read whose AxUSER differs answers
DECERR. A foreign source ID
does not match the entry, no other inbound entry is enabled, and unmatched
inbound traffic is blocked with DECERR while SEP-scope debug is off
(``hw/ip/axi_filter/doc/index.adoc``, Match, Then Permit and Blocked
Transactions; the bring-up line records ``sep_debug=0``).

CHK-ROW-FABRIC-CSR: the SI read of the inbound filter ``START_ADDR`` word and of
the alias remap ``START`` word answers OKAY with the value the LSU staged, and
the SI read of both halves of ``FEAT_CTRL`` answers OKAY with the bring-up golden
(``hw/sys/sep/doc/fabric.adoc``, Fabric Topology: the inbound crossbar reaches
the system CSRs; ``hw/sys/sep/doc/memory_map.adoc``, Units Unreachable from the
Inbound Port). The AP and STEE remap ``ATTRS`` words are logged
(``OBS-ROW-FABRIC-CSR``).

CHK-REG-SUBWORD-WDT: an LSU AxSIZE 0 read at byte offset 1 and an AxSIZE 1 read
at byte offset 2 of the watchdog ``WKUP_THOLD_LO`` word answer OKAY, and the
writes of the same shapes answer SLVERR. "A narrow read inside a register
returns OKAY"; a partial write, "a byte strobe that misses a byte the register
owns", gets a TL-UL error and "the faulting access also received SLVERR
synchronously" (``hw/sys/sep/regs/blocks/sep_cpu_ctrl/sep_cpu_ctrl.rdl:388-393``;
the watchdog block is ``PERIPH_BUS_ERR_STATUS.wdt``, ``:442``). The word after the
write and the other sub-word targets are logged (``OBS-REG-SUBWORD``).

OBS-ROW-ATTR: after the graded window closes, SI accesses with attributes that
no specification gives a response for: each live word again with the AxPROT[2],
AxUSER, AxCACHE, AxQOS, AxREGION and AxLOCK drawn at its CHK-ROW cell; exclusive
reads with drawn attributes of the pool ``STATUS`` (one 64-bit access), an ABR
register, the SPI host ``CSID`` and the DMA live word; an SI write of ``CSID``
with drawn AW attributes and WUSER. The line logs the response, the read data or the LSU read-back, and
grades nothing. CTRL-ROW-ATTR: the SI address handshake (and the W beat) carried
the drawn attributes, address and size; every live row has its drawn read.

OBS-ROW-NARROW: 1- and 2-byte SI reads and writes to a drawn Reserved, Past
Extent and Hole in Extent cell; the table states the cells for 32-bit accesses
only. CTRL-ROW-NARROW: the SI address handshake carried AxSIZE 0 or 1 at the
drawn address.

Not graded: the Forwarded and adopter-defined rows; the response of a burst to
a register region outside the crypto region and the SPI host extent (the
specification states none); any AxSIZE 3 access except the pool ``STATUS``
probe.
"""

from __future__ import annotations

from collections import Counter

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_decode_resp import logical_region
from env.sep_fabric_common import RESP_DECERR, RESP_OKAY, RESP_SLVERR
from env.sep_fabric_common import RESP_NAME as _RN
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_open_value_leg_pass,
    set_row_pass,
)
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LC_PROD, LCC_FEAT_CTRL, feat_ctrl_expected
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC, OTBN, sep_reg
from seq_lib import sep_row_response_seq as rr
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq, capture_addr_handshake, take_handshake
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_BASE,
    ALIAS_START,
    ALIAS_START_MASK,
    ALIAS_STRIDE,
    AP_BASE,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    REMAP_ATTRS,
    REMAP_OFFSET_LO_MASK,
    REMAP_STRIDE,
    STEE_BASE,
)
from seq_lib.sep_fabric_deadspace_seq import in_crypto_region
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq
from seq_lib.sep_wdt_aon_seq import WDT_CDC_CLKS

_TEST = "sep_fabric_row_response_matrix_test"
_MAX_SENSE_CYCLES = 20_000
# Pass label u_sep_fcov.row_pass: 1 releases the held samples of an instance
# whose checks passed, 2 drops them, 3 releases them with the OTBN AxCACHE
# cells (written only by the OTBN cache leg after CHK-ROW-CACHE passed). The
# leaf holds each value this many clk_i edges so the sampler sees it.
ROW_PASS_RELEASE = 1
ROW_PASS_DROP = 2
ROW_PASS_RELEASE_CACHE = 3
_LABEL_CLOCKS = 2

# Entropy pool (hw/sys/sep/doc/entropy_pool.adoc). :38-39 "A write to any offset
# terminates with BRESP=SLVERR"; :47-48 "An access to an unmapped offset within
# the aperture likewise returns SLVERR with zero data"; :34 and :40-41 STATUS is a
# non-destructive read taken with a single 64-bit access.
POOL_BASE = sep_reg.ENTROPY_POOL_REG_MAP_BASE_ADDR
POOL_EXTENT = sep_reg.ENTROPY_POOL_REG_MAP_SIZE
POOL_STATUS = sep_reg.ENTROPY_POOL_STATUS_REG_ADDR
POOL_REGS = (
    sep_reg.ENTROPY_POOL_STATUS_REG_ADDR,
    sep_reg.ENTROPY_POOL_IRQ_CAUSE_REG_ADDR,
    sep_reg.ENTROPY_POOL_DATA_REG_ADDR,
)
POOL_WRITE_RESP = RESP_SLVERR
POOL_UNMAPPED_RESP = RESP_SLVERR
POOL_UNMAPPED_RDATA = 0x0

# SPI host (hw/sys/sep/doc/peripheral_subsystem.adoc:43-46): the local crossbar
# sends only the SPI host register extent to sep_io, and the error responder of
# sep_io answers only the beats of a burst that run past the extent. The extent
# is the generated register map size (56 B, regs/gen/adoc/memory_map.adoc:81).
SPI_BASE = sep_reg.SPI_CONTROLLER_REG_MAP_BASE_ADDR
SPI_END = SPI_BASE + sep_reg.SPI_CONTROLLER_REG_MAP_SIZE
SPI_CSID = sep_reg.SPI_CONTROLLER_CSID_REG_ADDR
SPI_ERROR_ENABLE = sep_reg.SPI_CONTROLLER_ERROR_ENABLE_REG_ADDR
SPI_ERROR_STATUS = sep_reg.SPI_CONTROLLER_ERROR_STATUS_REG_ADDR
SPI_EVENT_ENABLE = sep_reg.SPI_CONTROLLER_EVENT_ENABLE_REG_ADDR
# The crossing bursts start two beats and one beat below the extent end; the
# control burst starts at ERROR_ENABLE and ends on the last byte of the extent.
# No register these bursts touch has a read side effect (checked at run time).
SPI_CROSS_STARTS = (SPI_ERROR_STATUS, SPI_EVENT_ENABLE)
SPI_INSIDE_START = SPI_ERROR_ENABLE
SPI_MAX_PAST_BEATS = 8
AXI_SIZE_32 = 2
# A pinned PROD image whose SIP_DIS and SYS_DIS keep the inbound filter active.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
# AxPROT of every SI request: data, non-secure, unprivileged. Entry 0 sets
# allow_ns to AxPROT[1].
SI_PROT = 0b010
OKAY, DECERR, SLVERR = RESP_OKAY, RESP_DECERR, RESP_SLVERR
AXI_INCR = 1
# Request attributes of an SI address handshake that the attribute legs draw.
# AxPROT[1] stays at SI_PROT[1], so inbound entry 0 admits every draw.
AX_ATTRS = ("prot", "user", "cache", "qos", "region", "lock")
# Separates the stream of the open-value legs from the cell walk of the same seed.
_ATTR_SALT = 0x524F_5741
# The inbound entry admits the whole SEP Local region of the CPU logical map.
_SEP_LOCAL = logical_region("logical:sep_local")
# Last register word of the rows whose 2-beat SI burst runs one beat past the extent.
BURST_PAST_ROWS = (
    ("dma", rr.ROW_BASE["dma"]),
    ("wdt", rr.ROW_BASE["wdt"]),
    ("cpu_ctrl", sep_reg.SEP_CPU_CTRL_REG_MAP_BASE_ADDR),
)
# Sub-word LSU targets: (name, word address, whether a changed value is written
# and the word restored after). A target without restore takes its own value.
SUBWORD_TARGETS = (
    ("scratch", sep_reg.SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR, True),
    ("wdt_wkup_thold_lo", sep_reg.WDT_TIMER_WKUP_THOLD_LO_REG_ADDR, True),
    ("cpu_ctrl_nmi_vec", sep_reg.SEP_CPU_CTRL_SEP_NMI_VEC_REG_ADDR, True),
    ("spi_csid", sep_reg.SPI_CONTROLLER_CSID_REG_ADDR, True),
    ("spi_configopts", sep_reg.SPI_CONTROLLER_CONFIGOPTS_REG_ADDR, True),
    ("km_mbox_irq_enable", rr.KM_IRQ_ENABLE, True),
    ("otbn_imem", sep_reg.OTBN_IMEM_MEM_BASE_ADDR, True),
    ("efuse_shadow", sep_reg.SEP_EFUSE_MAP_REG_MAP_BASE_ADDR, False),
    ("efuse_program_ctrl", sep_reg.EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_REG_ADDR, False),
    ("sw_reset_n", rr.SW_RESET_N, False),
)
# A narrow read inside a peripheral register answers OKAY and a partial write
# answers SLVERR (hw/sys/sep/regs/blocks/sep_cpu_ctrl/sep_cpu_ctrl.rdl:388-393;
# the watchdog block is PERIPH_BUS_ERR_STATUS.wdt, :442).
SUBWORD_GRADED = "wdt_wkup_thold_lo"


def _kmac_prefix_count() -> int:
    """Number of KMAC PREFIX registers in the generated register map."""
    n = 0
    while True:
        try:
            KMAC.addr(f"PREFIX_{n}_")
        except KeyError:
            return n
        n += 1


_HMAC_POLL = 200

# Hole neighbours: a stable register of the same unit with no read side effect.
HOLE_NEIGHBOUR_NAME = {
    "otbn": "INTR_ENABLE",
    "esrc": "MIN_ENTROPY_H",
    "abr": "INTR_BLOCK_RF_NOTIF_INTR_EN_R",
}


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:x}"


async def _capture_axcache(channel: str) -> int:
    """AxCACHE of the next ``channel`` (``ar`` or ``aw``) handshake on the LSU port.

    ``s_axi_*`` is the bus that drives the DUT LSU request, so the value is the
    AxCACHE the DUT receives, not the value the leaf asked for.
    """
    dut = cocotb.top
    valid = getattr(dut, f"s_axi_{channel}valid")
    ready = getattr(dut, f"s_axi_{channel}ready")
    cache = getattr(dut, f"s_axi_{channel}cache")
    while True:
        await RisingEdge(dut.clk_i)
        if valid.value == 1 and ready.value == 1:
            return int(cache.value)


async def _capture_si(channel: str, fields: tuple[str, ...]) -> dict[str, int]:
    """``fields`` of the next ``channel`` handshake (``ar``, ``aw`` or ``w``) on the SI port.

    ``m_axi_*`` is the bus that drives the SEP inbound request, and the handshake
    completes only when the DUT raises READY, so the values are the request the
    DUT accepted.
    """
    dut = cocotb.top
    valid = getattr(dut, f"m_axi_{channel}valid")
    ready = getattr(dut, f"m_axi_{channel}ready")
    sig = {f: getattr(dut, f"m_axi_{channel}{f}") for f in fields}
    while True:
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        if valid.value == 1 and ready.value == 1:
            return {f: int(v.value) for f, v in sig.items()}


def _attr_txt(attrs: dict[str, int | None] | None) -> str:
    if attrs is None:
        return "none"
    return " ".join(f"{k}={_hex(v)}" for k, v in attrs.items())


def _reg_named(key: str, name: str) -> rr.Reg:
    return next(r for r in rr.row_regs(key) if r.name == name)


@pyuvm.test()
class sep_fabric_row_response_matrix_test(sep_base_test):
    """Every graded address-map row cell, the OTBN AxCACHE cells and the crypto burst rule."""

    required_evidence = (
        "CHK-ROW",
        "CHK-ROW-NOALIAS",
        "CHK-ROW-CACHE",
        "CHK-ROW-KM",
        "CHK-ROW-BURST",
        "CHK-ROW-BURST-CONTROL",
        "CHK-ROW-POOL-W",
        "CHK-ROW-POOL-UNMAPPED",
        "CHK-ROW-SPI-BURST",
        "CHK-ROW-SPI-BURST-CONTROL",
        "CHK-SI-ID-ECHO",
        "CHK-ROW-FILTER-SRC",
        "CHK-ROW-FABRIC-CSR",
    )

    # ------------------------------------------------------------------ access
    async def _lsu(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        size: int = 2,
        wdata: int = 0,
        cache: int | None = None,
        expect: str = "ok",
    ) -> tuple[int, int]:
        """One LSU access. ``expect``: ``ok`` (OKAY required), ``err`` (graded
        error; the caller checks the code), ``any`` (logged only)."""
        length = 1 << size
        mon = self.env.axi_monitor
        kw = {}
        if expect == "err":
            kw["expect_error"] = True
            kw["allow_unverified_write_resp"] = op is SepAxiOp.WRITE
        elif expect == "any":
            if op is SepAxiOp.READ:
                kw["allow_ungraded_read_resp"] = True
            else:
                kw["allow_unverified_write_resp"] = True
        if expect != "ok":
            mon.arm_expected_decerr(1)
            if op is SepAxiOp.READ:
                mon.open_error_rdata_window()
        seq = SepAxiAccessSeq(
            f"row_lsu_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata & ((1 << (8 * length)) - 1),
            length=length,
            size=size,
            attrs=None if cache is None else {"cache": cache},
            **kw,
        )
        try:
            await self.start_seq(seq)
        finally:
            if expect != "ok" and op is SepAxiOp.READ:
                mon.close_error_rdata_window()
        if expect != "ok" and seq.resp_code != DECERR:
            mon.release_expected_decerr(1)
        if expect == "ok" and not seq.resp_ok:
            raise AssertionError(f"LSU {op.value} 0x{addr:08x} answered {_RN.get(seq.resp_code)}")
        return seq.resp_code, seq.rdata

    async def _si(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        size: int = 2,
        wdata: int = 0,
        length: int | None = None,
        burst: int | None = None,
        prot: int = SI_PROT,
        user: int = 0,
        attrs: dict[str, int] | None = None,
        rng: SepSeededRng | None = None,
    ) -> SepAxiAccessSeq:
        """One SI access through inbound entry 0 with a non-zero AxID drawn from
        ``rng`` (the cell-walk stream when None)."""
        length = (1 << size) if length is None else length
        mon = self.env.ext_axi_monitor
        if op is SepAxiOp.READ:
            mon.open_error_rdata_window()
        axi_id = (rng or self.rng).randrange(1, 64)
        seq = SepAxiAccessSeq(
            f"row_si_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata & ((1 << (8 * length)) - 1),
            length=length,
            size=size,
            burst=burst,
            prot=prot,
            user=user,
            attrs=attrs,
            axi_id=axi_id,
            allow_unverified_write_resp=op is SepAxiOp.WRITE,
        )
        try:
            await self.start_ext_seq(seq)
        finally:
            if op is SepAxiOp.READ:
                mon.close_error_rdata_window()
        assert not seq.timed_out, f"SI {op.value} 0x{addr:08x} timed out"
        if seq.resp_id == axi_id:
            self.si_id_ok += 1
        else:
            self.si_id_bad += 1
            self._fail(
                "CHK-SI-ID-ECHO",
                f"SI {op.value} 0x{addr:08x} resp={_RN.get(seq.resp_code)} "
                f"{'RID' if op is SepAxiOp.READ else 'BID'}={seq.resp_id} expected {axi_id}",
            )
        return seq

    # ------------------------------------------------------------- bookkeeping
    def _walk(self, row: str, kind: str, d: str, init: str) -> None:
        self.walked.add((row, kind, d, init))

    def _fail(self, chk: str, line: str) -> None:
        """Record a FAIL: close the window and drop every held sample first."""
        close_graded_window(self.logger)
        set_row_pass(ROW_PASS_DROP, self.logger)
        self.logger.error("%s FAIL: %s", chk, line)
        self.fails.append(f"{chk}: {line}")

    def _ctrl(self, name: str, ok: bool, line: str) -> bool:
        """Log one control; a missing control is a recorded failure."""
        if ok:
            self.logger.info("CTRL-%s LOG: seed=%d %s", name, self.random_seed(), line)
        else:
            close_graded_window(self.logger)
            set_row_pass(ROW_PASS_DROP, self.logger)
            self.logger.error("CTRL-MISSING %s: seed=%d %s", name, self.random_seed(), line)
            self.fails.append(f"CTRL-MISSING {name}: {line}")
        return ok

    def _abort(self, chk: str, line: str) -> None:
        """A FAIL that ends the leaf."""
        self._fail(chk, line)
        raise AssertionError(f"{chk} FAIL: {line}")

    # --------------------------------------------------------------- FCOV gate
    def _open(self) -> None:
        """Open the window of this leaf; never again after a FAIL."""
        if not self.fails:
            open_graded_window(_TEST, self.logger)

    def _close(self) -> None:
        close_graded_window(self.logger)

    async def _label(self, value: int) -> None:
        set_row_pass(value)
        await ClockCycles(cocotb.top.clk_i, _LABEL_CLOCKS)
        set_row_pass(0)
        await ClockCycles(cocotb.top.clk_i, _LABEL_CLOCKS)

    async def _begin(self) -> None:
        """Start a graded instance: drop every sample held since the last release."""
        if not self.fails:
            await self._label(ROW_PASS_DROP)

    async def _release(self, *, cache: bool = False) -> None:
        """Release the held samples of an instance after all its checks passed.

        ``cache``: the instance is one of the OTBN cache leg, so its OTBN
        AxCACHE cells sample too; every other release drops them."""
        if not self.fails:
            await self._label(ROW_PASS_RELEASE_CACHE if cache else ROW_PASS_RELEASE)
            self.released += 1

    def _row_line(self, ok: bool, line: str) -> None:
        if ok:
            self.logger.info("CHK-ROW PASS: %s", line)
        else:
            self._fail("CHK-ROW", line)

    def _grade_cell(
        self, row: str, kind: str, init: str, op: SepAxiOp, addr: int, resp: int, rdata: int, wdata
    ) -> None:
        exp = rr.expected_cell(addr, "r" if op is SepAxiOp.READ else "w")
        d = "R" if op is SepAxiOp.READ else "W"
        got = rdata & 0xFFFF_FFFF
        ok = resp == exp.resp and (exp.rdata is None or got == exp.rdata)
        self._row_line(
            ok,
            f"row={row} kind={kind} init={init} dir={d} size=2 addr=0x{addr:08x} "
            f"wdata={'na' if wdata is None else f'0x{wdata:08x}'} resp={_RN.get(resp)} "
            f"rdata=0x{got:08x} expect={_RN[exp.resp]}/"
            f"{'na' if exp.rdata is None else f'0x{exp.rdata:08x}'}",
        )
        self._walk(row, kind, d, init)

    def _log_size3(self, row: str, kind: str, resp: int, rdata: int, d: str) -> None:
        self.logger.info(
            "OBS-ROW-SIZE3 LOG: row=%s kind=%s dir=%s size=3 resp=%s rdata=0x%016x graded=0",
            row,
            kind,
            d,
            _RN.get(resp),
            rdata,
        )

    def _expect_reg(self, addr: int) -> int:
        return self.regval.get(addr, rr.word_reset(addr))

    async def _lsu_write_reg(self, addr: int, wdata: int, tag: str) -> tuple[int, int, int]:
        """In-extent LSU write and read-back; returns (read, expected, mask)."""
        await self._lsu(SepAxiOp.WRITE, addr, wdata=wdata)
        exp, mask = rr.write_readback(addr, self._expect_reg(addr), wdata)
        _r, got = await self._lsu(SepAxiOp.READ, addr)
        self.regval[addr] = exp
        if (got & mask) != (exp & mask):
            raise AssertionError(
                f"{tag}: 0x{addr:08x} read 0x{got & mask:08x} after a write of 0x{wdata:08x}, "
                f"expected 0x{exp & mask:08x} (field_mask=0x{mask:08x})"
            )
        return got, exp, mask

    # --------------------------------------------------------------- bring-up
    async def _bring_up(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        # The image carries no SEC_DIS token, so the golden takes SEC_DIS 0 from
        # the image, not from the DUT.
        feat = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        self.feat_golden = feat
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        self.logger.info(
            "INFO-ROW-BRINGUP LOG: feat_ctrl=0x%016x golden=0x%016x sep_debug=%d",
            ctl.feat_ctrl,
            feat,
            ctl.sep_debug,
        )

    async def _program_entry(self, src_id: int = 0) -> None:
        bank = SepFilterBank(self, "in")
        await bank.program(
            0,
            FilterEntry(
                start=_SEP_LOCAL[0],
                end=_SEP_LOCAL[1],
                enabled=True,
                read_allowed=True,
                write_allowed=True,
                allow_ns=bool((SI_PROT >> 1) & 1),
                allow_burst=True,
                src_id=src_id,
            ),
        )

    # ---------------------------------------------------------------- inventory
    def _inventory(self) -> set[tuple[str, str, str, str]]:
        inv: set[tuple[str, str, str, str]] = set()
        for d in ("R", "W"):
            inv.add(("reset_ctrl", "past", d, "LSU"))
            inv.add((f"rsvd_{rr.past_bounds('reset_ctrl')[2]:08x}", "reserved", d, "LSU"))
            for base in rr.RESERVED_BASES:
                rr.reserved_row(base)
                inv.add((f"rsvd_{base:08x}", "reserved", d, "SI"))
            for k in rr.HOLE_ROWS:
                inv.add((k, "hole", d, "SI"))
            for k in rr.PAST_ROWS:
                inv.add((k, "past", d, "SI"))
            inv.add(("km_mbox", "past", d, "SI"))
            for k in rr.BURST_ROWS:
                for kind in ("reg", "hole"):
                    inv.add((k, f"burst_{kind}", d, "SI"))
        inv.add(("reset_ctrl", "live", "R", "LSU"))
        for k in rr.LIVE_SI_ROWS:
            inv.add((k, "live", "R", "SI"))
        inv.add(("pool", "write", "W", "SI"))
        inv.add(("pool", "past", "R", "SI"))
        for d in ("R", "W"):
            inv.add(("spi_host", "burst_cross", d, "SI"))
        return inv

    # -------------------------------------------------------------------- legs
    async def _reset_ctrl_leg(self) -> None:
        """Steps 4 to 6: reset-control cells, the control and the no-alias draws."""
        await self._begin()
        resp, ref = await self._lsu(SepAxiOp.READ, rr.SW_RESET_N)
        got = ref & rr.SW_RESET_N_FIELDS
        self._row_line(
            resp == OKAY and got == rr.SW_RESET_N_REF,
            f"row=reset_ctrl kind=live init=LSU dir=R size=2 addr=0x{rr.SW_RESET_N:08x} "
            f"wdata=na resp={_RN.get(resp, resp)} rdata=0x{ref & 0xFFFF_FFFF:08x} expect=OKAY/0x{rr.SW_RESET_N_REF:02x} "
            f"field_mask=0x{rr.SW_RESET_N_FIELDS:02x} lsu_before=na lsu_after=na "
            f"rsvd=0x{ref & ~rr.SW_RESET_N_FIELDS & 0xFFFF_FFFF:08x}",
        )
        self._walk("reset_ctrl", "live", "R", "LSU")
        await self._release()
        first, last, nxt = rr.past_bounds("reset_ctrl")
        rr.reserved_row(nxt)
        drawn = (first + 8) + 8 * self.rng.randrange(0, ((last - 8) - (first + 8)) // 8 + 1)
        pairs = (first, drawn, last, nxt)
        self.logger.info("INFO-ROW-RAND LOG: reset_ctrl drawn pair 0x%08x", drawn)
        for op in (SepAxiOp.READ, SepAxiOp.WRITE):
            d = "R" if op is SepAxiOp.READ else "W"
            for word in pairs:
                row = "reset_ctrl" if word < nxt else f"rsvd_{nxt:08x}"
                kind = "past" if word < nxt else "reserved"
                for a in (word, word + 4):
                    wd = ((self.rng.getrandbits(25) << 7) | 0x01) if op is SepAxiOp.WRITE else None
                    await self._begin()
                    resp, rdata = await self._lsu(op, a, wdata=wd or 0, expect="err")
                    self._grade_cell(row, kind, "LSU", op, a, resp, rdata, wd)
                    await self._release()
                # Logged only: the next _begin() drops its samples.
                resp, rdata = await self._lsu(
                    op, word, size=3, wdata=self.rng.getrandbits(64), expect="any"
                )
                self._log_size3(row, kind, resp, rdata, d)
        # Step 5: the reset-control control, before the no-alias draws, so a
        # reference that cannot change fails before any no-alias sample is held.
        # In-extent writes change the read.
        for value in (0x76, rr.SW_RESET_N_REF):
            await self._begin()
            await self._lsu(SepAxiOp.WRITE, rr.SW_RESET_N, wdata=value)
            _r, back = await self._lsu(SepAxiOp.READ, rr.SW_RESET_N)
            if back & rr.SW_RESET_N_FIELDS != value:
                self._abort(
                    "CHK-ROW-NOALIAS",
                    f"control write of SW_RESET_N=0x{value:02x} read back "
                    f"0x{back & rr.SW_RESET_N_FIELDS:02x}; the reference cannot show an alias",
                )
            self.logger.info(
                "CTRL-ROW-NOALIAS LOG: unit=reset_ctrl wrote=0x%02x read=0x%02x",
                value,
                back & rr.SW_RESET_N_FIELDS,
            )
            await self._release()
        self.noalias_ctl.add("reset_ctrl")
        # Step 6: no-alias draws in the gap at AxSIZE 0, 1, 2 and 3.
        for size in (0, 1, 2, 3):
            for _ in range(2):
                n = 1 << size
                # AxSIZE 0 and 1 draw 4-byte-aligned addresses, so the data
                # lies on the byte lanes of SW_RESET_N[6:0].
                step = max(n, 4)
                lo = (first + step - 1) & ~(step - 1)
                a = lo + step * self.rng.randrange(0, (nxt - lo) // step)
                wd = (self.rng.getrandbits(8 * n - 7) << 7) | 0x01
                expect = "err" if size == 2 else "any"
                await self._begin()
                resp, rdata = await self._lsu(SepAxiOp.WRITE, a, size=size, wdata=wd, expect=expect)
                if size == 2:
                    self._grade_cell("reset_ctrl", "past", "LSU", SepAxiOp.WRITE, a, resp, 0, wd)
                else:
                    self.logger.info(
                        "OBS-ROW-NOALIAS-DRAW LOG: addr=0x%08x size=%d resp=%s graded=0",
                        a,
                        size,
                        _RN.get(resp),
                    )
                _r, after = await self._lsu(SepAxiOp.READ, rr.SW_RESET_N)
                self._noalias(
                    "reset_ctrl",
                    a - rr.SW_RESET_N,
                    rr.SW_RESET_N,
                    rr.SW_RESET_N_REF,
                    after & rr.SW_RESET_N_FIELDS,
                    wd,
                )
                # Only an AxSIZE 2 draw has its write response graded, so only
                # it releases its samples; the next _begin() drops the others.
                if size == 2:
                    await self._release()

    def _noalias(self, unit: str, off: int, live: int, before: int, after: int, wd: int) -> None:
        line = (
            f"unit={unit} off=0x{off & 0xFFFF_FFFF:x} live=0x{live:08x} before=0x{before:x} "
            f"after=0x{after:x} wdata=0x{wd:x}"
        )
        if after == before:
            self.logger.info("CHK-ROW-NOALIAS PASS: %s", line)
        else:
            self._fail("CHK-ROW-NOALIAS", line)
        self.noalias_draws[unit] += 1

    async def _wait_hmac(self) -> None:
        """Step 7: HMAC CFG answers OKAY again after the HMAC domain reset."""
        for i in range(_HMAC_POLL):
            resp, _d = await self._lsu(SepAxiOp.READ, rr.HMAC_CFG, expect="any")
            if resp == OKAY:
                self.logger.info("INFO-ROW-HMAC-READY LOG: CFG OKAY after %d read(s)", i + 1)
                return
            await ClockCycles(cocotb.top.clk_i, 20)
        raise AssertionError(f"HMAC CFG did not answer OKAY in {_HMAC_POLL} reads")

    async def _program_refs(self) -> None:
        """Step 8: the HMAC CFG and KMAC PREFIX references."""
        _r, cur = await self._lsu(SepAxiOp.READ, rr.HMAC_CFG)
        self.regval[rr.HMAC_CFG] = cur & 0xFFFF_FFFF
        hval = rr.hmac_cfg_reference(self.rng)
        await self._lsu_write_reg(rr.HMAC_CFG, hval, "HMAC CFG reference")
        k = self.rng.randrange(0, _kmac_prefix_count())
        self.kmac_ref = KMAC.addr(f"PREFIX_{k}_")
        kval = self.rng.randrange(1, 1 << 32)
        await self._lsu_write_reg(self.kmac_ref, kval, "KMAC PREFIX reference")
        self.logger.info(
            "INFO-ROW-REF LOG: hmac_cfg=0x%08x kmac_prefix[%d]@0x%08x=0x%08x",
            self.regval[rr.HMAC_CFG],
            k,
            self.kmac_ref,
            self.regval[self.kmac_ref],
        )

    async def _lsu_cache(
        self, op: SepAxiOp, addr: int, cache: int, *, wdata: int = 0
    ) -> tuple[int, int, int | None]:
        """One OKAY LSU access with AxCACHE ``cache``; also returns the AxCACHE
        of its address handshake on the LSU port (None when none was seen)."""
        hs = cocotb.start_soon(_capture_axcache("aw" if op is SepAxiOp.WRITE else "ar"))
        resp, data = await self._lsu(op, addr, wdata=wdata, cache=cache)
        return resp, data, take_handshake(hs)

    async def _otbn_cache_leg(self) -> None:
        """Step 9: OTBN register access with AxCACHE 0x0, 0x2, 0x3 and 0xF."""
        ie = OTBN.addr("INTR_ENABLE")
        done = OTBN.field_mask("INTR_ENABLE", "done")
        st = OTBN.addr("STATUS")
        for c in (0x0, 0x2, 0x3, 0xF):
            # Every access below answers OKAY or _lsu raises; the read-back
            # check and the AxCACHE seen on the bus release the instance.
            await self._begin()
            rresp, v, ar0 = await self._lsu_cache(SepAxiOp.READ, ie, c)
            w = (~v) & done
            bresp, _, aw = await self._lsu_cache(SepAxiOp.WRITE, ie, c, wdata=w)
            _r, back, ar1 = await self._lsu_cache(SepAxiOp.READ, ie, c)
            _s, _sv, ar2 = await self._lsu_cache(SepAxiOp.READ, st, c)
            self.regval[ie] = w
            bus = (ar0, aw, ar1, ar2)
            line = (
                f"init=LSU cache=0x{c:x} bus arcache={[_hex(x) for x in (ar0, ar1, ar2)]} "
                f"awcache={_hex(aw)} rresp={_RN[rresp]} bresp={_RN[bresp]} "
                f"readback=0x{back & done:x}"
            )
            if (back & done) == w and all(x == c for x in bus):
                self.logger.info("CHK-ROW-CACHE PASS: %s", line)
                await self._release(cache=True)
            else:
                self._fail("CHK-ROW-CACHE", line + f" written=0x{w:x}")

    async def _reserved_leg(self) -> None:
        """Step 10: the 8 Reserved rows from SI."""
        bases = list(rr.RESERVED_BASES)
        self.rng.shuffle(bases)
        for base in bases:
            row = rr.map_row(base)
            mid = base + 8 + 8 * self.rng.randrange(0, (row.end - 15 - base - 8) // 8 + 1)
            words = (base, row.end - 7, mid)
            self.logger.info("INFO-ROW-RAND LOG: rsvd_%08x words %s", base, [hex(w) for w in words])
            for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                d = "R" if op is SepAxiOp.READ else "W"
                for word in words:
                    for a in (word, word + 4):
                        wd = self.rng.getrandbits(32) if op is SepAxiOp.WRITE else None
                        await self._begin()
                        s = await self._si(op, a, wdata=wd or 0)
                        self._grade_cell(
                            f"rsvd_{base:08x}", "reserved", "SI", op, a, s.resp_code, s.rdata, wd
                        )
                        await self._release()
                    s = await self._si(op, word, size=3, wdata=self.rng.getrandbits(64))
                    self._log_size3(f"rsvd_{base:08x}", "reserved", s.resp_code, s.rdata, d)

    async def _hole_leg(self) -> None:
        """Steps 11 and 12: the hole-write control, then the hole cells from SI with the neighbour compare."""
        units = list(rr.HOLE_ROWS)
        self.rng.shuffle(units)
        for unit in units:
            word = self.rng.choice(rr.hole_words(unit))
            if unit == "hmac":
                nb = rr.HMAC_CFG
            elif unit == "kmac":
                nb = self.kmac_ref
            else:
                nb = _reg_named(unit, HOLE_NEIGHBOUR_NAME[unit]).addr
            # Entry read of the neighbour, outside the window.
            self._close()
            _r, before = await self._lsu(SepAxiOp.READ, nb)
            reg = rr.reg_by_word()[nb]
            mask = reg.word_mask(nb)
            exp_nb = self._expect_reg(nb)
            if (before & mask) != (exp_nb & mask):
                self._abort(
                    "CHK-ROW",
                    f"{unit} neighbour 0x{nb:08x} read 0x{before & mask:x} before "
                    f"the hole access, model 0x{exp_nb & mask:x}",
                )
            comp = (~before) & 0xFFFF_FFFF
            self.logger.info(
                "INFO-ROW-RAND LOG: %s hole word 0x%08x neighbour 0x%08x", unit, word, nb
            )
            # Step 11: the hole-write control on the same neighbour, window
            # closed, before the hole writes: a neighbour whose read cannot
            # change fails before any hole sample is held. The restore puts
            # the entry value back for the compare of step 12.
            got, exp, _m = await self._lsu_write_reg(nb, comp, f"{unit} hole-write control")
            if (got & mask) == (before & mask):
                self._abort(
                    "CHK-ROW",
                    f"{unit} control write of 0x{comp:08x} to 0x{nb:08x} did not "
                    f"change its read (0x{got & mask:x}); a landed hole write would not show",
                )
            self.logger.info(
                "CTRL-ROW-HOLE LOG: unit=%s neighbour=0x%08x wrote=0x%08x read=0x%x before=0x%x",
                unit,
                nb,
                comp,
                got & mask,
                before & mask,
            )
            if unit in ("hmac", "kmac"):
                self.noalias_ctl.add(unit)
            await self._lsu_write_reg(nb, before, f"{unit} neighbour restore")
            # Step 12: the hole cells, with the neighbour compare after each write.
            self._open()
            for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                d = "R" if op is SepAxiOp.READ else "W"
                for a in (word, word + 4):
                    await self._begin()
                    s = await self._si(op, a, wdata=comp)
                    self._grade_cell(
                        unit,
                        "hole",
                        "SI",
                        op,
                        a,
                        s.resp_code,
                        s.rdata,
                        comp if op is SepAxiOp.WRITE else None,
                    )
                    if op is SepAxiOp.WRITE:
                        _r, after = await self._lsu(SepAxiOp.READ, nb)
                        same = (after & mask) == (before & mask)
                        line = (
                            f"row={unit} kind=hole_neighbour init=LSU addr=0x{nb:08x} "
                            f"hole=0x{a:08x} before=0x{before & mask:x} after=0x{after & mask:x} "
                            f"wdata=0x{comp:08x} field_mask=0x{mask:x}"
                        )
                        self._row_line(same, line)
                        if unit in ("hmac", "kmac"):
                            self._noalias(unit, a - nb, nb, before & mask, after & mask, comp)
                    await self._release()
                s = await self._si(op, word, size=3, wdata=(comp << 32) | comp)
                self._log_size3(unit, "hole", s.resp_code, s.rdata, d)
            self._close()
            if unit == "abr":
                # ABR has no stable register with a non-zero reset, so its live
                # word is graded at the control value, written again here with
                # the window closed and restored after the read.
                await self._lsu_write_reg(nb, comp, "abr live-word value")
                self._open()
                await self._begin()
                if await self._live_word("abr", _reg_named("abr", HOLE_NEIGHBOUR_NAME["abr"])):
                    await self._release()
                self._close()
                await self._lsu_write_reg(nb, before, "abr neighbour restore")

    async def _past_leg(self) -> None:
        """Step 13: past-extent cells from SI."""
        rows = list(rr.PAST_ROWS)
        self.rng.shuffle(rows)
        for key in rows:
            row = rr.map_row(key)
            e = row.base + row.extent
            lo = (e + 8 + 7) & ~7
            drawn = lo + 8 * self.rng.randrange(0, (row.end - 7 - lo) // 8 + 1)
            self.logger.info("INFO-ROW-RAND LOG: %s past E=0x%08x drawn 0x%08x", key, e, drawn)
            for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                d = "R" if op is SepAxiOp.READ else "W"
                for a in (e, e + 4, drawn, drawn + 4):
                    wd = self.rng.getrandbits(32) if op is SepAxiOp.WRITE else None
                    await self._begin()
                    s = await self._si(op, a, wdata=wd or 0)
                    self._grade_cell(key, "past", "SI", op, a, s.resp_code, s.rdata, wd)
                    await self._release()
                for w8 in ((e + 7) & ~7, drawn):
                    s = await self._si(op, w8, size=3, wdata=self.rng.getrandbits(64))
                    self._log_size3(key, "past", s.resp_code, s.rdata, d)

    async def _live_word(self, key: str, reg: rr.Reg) -> bool:
        """SI read of a live word between two LSU reads; True when CHK-ROW passed."""
        a = reg.addr
        mask = reg.word_mask(a)
        exp = self._expect_reg(a)
        _r, lsu_b = await self._lsu(SepAxiOp.READ, a)
        # Attributes of the drawn-attribute read of this word (_attr_read_leg).
        drawn = {
            "prot": SI_PROT | (self.rng.getrandbits(1) << 2),
            "user": self.rng.getrandbits(12),
            "cache": self.rng.getrandbits(4),
            "qos": self.rng.getrandbits(4),
            "region": self.rng.getrandbits(4),
            "lock": self.rng.getrandbits(1),
        }
        hs = cocotb.start_soon(_capture_si("ar", AX_ATTRS))
        s = await self._si(SepAxiOp.READ, a)
        default = take_handshake(hs)
        _r, lsu_a = await self._lsu(SepAxiOp.READ, a)
        if drawn == default:
            # The drawn read differs from this read on at least one attribute.
            drawn["prot"] ^= 1 << 2
        self.live_draw[key] = (reg, drawn)
        got = s.rdata & 0xFFFF_FFFF
        pre_ok = (lsu_b & mask) == (exp & mask) and (lsu_a & mask) == (exp & mask)
        nonzero_ok = key not in rr.NONZERO_LIVE or (exp & mask) != 0
        ok = s.resp_code == OKAY and (got & mask) == (exp & mask) and pre_ok and nonzero_ok
        self._row_line(
            ok,
            f"row={key} kind=live init=SI dir=R size=2 addr=0x{a:08x} wdata=na "
            f"resp={_RN.get(s.resp_code)} rdata=0x{got & mask:08x} expect=OKAY/0x{exp & mask:08x} "
            f"field_mask=0x{mask:08x} lsu_before=0x{lsu_b & mask:08x} "
            f"lsu_after=0x{lsu_a & mask:08x} rsvd=0x{got & ~mask & 0xFFFF_FFFF:08x} reg={reg.name} "
            f"attrs=[{_attr_txt(default)}]",
        )
        self._walk(key, "live", "R", "SI")
        return ok

    async def _live_leg(self) -> None:
        """Step 14: the live word of each row except reset control and ABR."""
        rows = [k for k in rr.LIVE_SI_ROWS if k != "abr"]
        self.rng.shuffle(rows)
        for key in rows:
            await self._begin()
            if await self._live_word(key, rr.live_word(key)):
                await self._release()

    async def _km_leg(self) -> None:
        """Step 15: Key Manager mailbox window from SI with KM held in reset."""
        base = rr.ROW_BASE["km_mbox"]
        names = ("SEP_STATUS", "SEP_IRQ_STATUS", "SEP_CTRL", "SEP_IRQ_ENABLE")
        # One instance: the CHK-ROW-KM lines pass only after the baseline
        # control, so the release follows that control.
        await self._begin()
        baseline = {}
        for a in rr.KM_BASELINE:
            s = await self._si(SepAxiOp.READ, a)
            if s.resp_code != OKAY:
                self._abort("CHK-ROW-KM", f"baseline 0x{a:08x} answered {_RN.get(s.resp_code)}")
            baseline[a] = s.rdata & rr.reg_by_word()[a].word_mask(a)
        s = await self._si(SepAxiOp.READ, rr.KM_SEPARATOR)
        if s.resp_code != OKAY:
            self._abort("CHK-ROW-KM", f"separator answered {_RN.get(s.resp_code)}")
        self.logger.info(
            "INFO-ROW-KM LOG: baseline %s separator=0x%08x",
            " ".join(f"{n}=0x{baseline[a]:x}" for n, a in zip(names, rr.KM_BASELINE)),
            s.rdata & 0xFFFF_FFFF,
        )
        first, last, nxt = rr.past_bounds("km_mbox")
        rsvd_last = rr.reserved_row(nxt).end + 1 - 8
        lo1 = ((first + 7) & ~7) - base
        d1 = lo1 + 8 * self.rng.randrange(0, ((last - 8 - base) - lo1) // 8 + 1)
        d2 = nxt + 8 * self.rng.randrange(0, (rsvd_last - nxt) // 8 + 1)
        pairs = (first, last, base + d1, d2)
        self.logger.info("INFO-ROW-RAND LOG: km pairs %s", [hex(p) for p in pairs])
        lines = []
        for op in (SepAxiOp.READ, SepAxiOp.WRITE):
            d = "R" if op is SepAxiOp.READ else "W"
            for p in pairs:
                for a in (p, p + 4):
                    wd = self.rng.getrandbits(32) if op is SepAxiOp.WRITE else None
                    s = await self._si(op, a, wdata=wd or 0)
                    exp = rr.expected_cell(a, "r" if op is SepAxiOp.READ else "w")
                    got = s.rdata & 0xFFFF_FFFF
                    same = True
                    for b in rr.KM_BASELINE:
                        sb = await self._si(SepAxiOp.READ, b)
                        v = sb.rdata & rr.reg_by_word()[b].word_mask(b)
                        same = same and sb.resp_code == OKAY and v == baseline[b]
                    ok = (
                        s.resp_code == DECERR
                        and exp.resp == DECERR
                        and (exp.rdata is None or got == exp.rdata)
                        and same
                    )
                    row = "km_mbox" if a < nxt else f"rsvd_{nxt:08x}"
                    kind = "past" if a < nxt else "reserved"
                    self._walk(row, kind, d, "SI")
                    line = (
                        f"off=0x{a - base:x} dir={d} resp={_RN.get(s.resp_code)} "
                        f"rdata=0x{got if op is SepAxiOp.READ else 0:08x} "
                        f"baseline_same={int(same)}"
                    )
                    if ok:
                        lines.append(line)
                    else:
                        self._fail("CHK-ROW-KM", line)
        self._close()
        for v in (rr.KM_IRQ_ENABLE_CTL, 0):
            s = await self._si(SepAxiOp.WRITE, rr.KM_IRQ_ENABLE, wdata=v)
            r = await self._si(SepAxiOp.READ, rr.KM_IRQ_ENABLE)
            if s.resp_code != OKAY or r.resp_code != OKAY or (r.rdata & 0xFFFF_FFFF) != v:
                self._abort(
                    "CHK-ROW-KM",
                    f"baseline control SEP_IRQ_ENABLE write 0x{v:x} answered "
                    f"{_RN.get(s.resp_code)}, read back 0x{r.rdata & 0xFFFF_FFFF:x} "
                    f"({_RN.get(r.resp_code)})",
                )
        self.regval[rr.KM_IRQ_ENABLE] = 0
        for line in lines:
            self.logger.info("CHK-ROW-KM PASS: %s baseline_ctl=0x%x", line, rr.KM_IRQ_ENABLE_CTL)
        await self._release()

    async def _snapshot(self, key: str) -> dict[int, tuple[int, int]]:
        snap = {}
        for reg in rr.snapshot_regs(key):
            for a in reg.words:
                _r, v = await self._lsu(SepAxiOp.READ, a)
                snap[a] = (v & 0xFFFF_FFFF, reg.word_mask(a))
        return snap

    async def _burst_leg(self) -> None:
        """Steps 16 to 19: SI INCR bursts to the crypto windows, with single-beat control."""
        mon = self.env.ext_axi_monitor
        for key in rr.BURST_ROWS:
            row = rr.map_row(key)
            for kind in ("reg", "hole"):
                for op in (SepAxiOp.WRITE, SepAxiOp.READ):
                    d = "R" if op is SepAxiOp.READ else "W"
                    # A start with room for two beats before its 4 KB page ends.
                    starts = (
                        [r.addr for r in rr.burst_start_regs(key)]
                        if kind == "reg"
                        else list(rr.hole_words(key))
                    )
                    start = self.rng.choice([a for a in starts if (a & 0xFFF) <= 0xFF0])
                    page_end = (start & ~0xFFF) + 0x1000
                    max_len = min(255, (page_end - start) // 8 - 1)
                    axlen = self.rng.randrange(1, max_len + 1)
                    nbeats = axlen + 1
                    assert in_crypto_region(start) and row.base <= start <= row.end
                    snap = await self._snapshot(key)
                    wdata = 0
                    for i in range(2 * nbeats):
                        a = start + 4 * i
                        w = (~snap[a][0]) & 0xFFFF_FFFF if a in snap else self.rng.getrandbits(32)
                        wdata |= w << (32 * i)
                    self._open()
                    await self._begin()
                    ch = "ar" if op is SepAxiOp.READ else "aw"
                    hs = cocotb.start_soon(capture_addr_handshake(ch, prefix="m_axi"))
                    if op is SepAxiOp.READ:
                        mon.start_beat_capture()
                    s = await self._si(
                        op, start, size=3, wdata=wdata, length=8 * nbeats, burst=AXI_INCR
                    )
                    beats = mon.take_beat_capture() if op is SepAxiOp.READ else []
                    ax = take_handshake(hs)
                    self._close()
                    changed = []
                    if op is SepAxiOp.WRITE:
                        after = await self._snapshot(key)
                        changed = [
                            f"0x{a:08x}:0x{v & m:x}->0x{after[a][0] & m:x}"
                            for a, (v, m) in snap.items()
                            if (after[a][0] & m) != (v & m)
                        ]
                        # A write burst has one B response, so the DECERR on B
                        # carries the write claim.
                        resp_ok = s.resp_code == DECERR
                        n_dec = 1 if resp_ok else 0
                    else:
                        resp_ok = len(beats) == nbeats and all(b == DECERR for b in beats)
                        n_dec = sum(1 for b in beats if b == DECERR)
                    one_burst = ax is not None and ax["len"] == axlen and ax["addr"] == start
                    line = (
                        f"init=SI addr=0x{start:08x} kind={kind} len={axlen} dir={d} "
                        f"resp={_RN.get(s.resp_code)} beats_decerr={n_dec} "
                        f"wdata={'0x%x' % (wdata & 0xFFFF_FFFF_FFFF_FFFF) if op is SepAxiOp.WRITE else 'na'} "
                        f"regs_compared={len(snap) if op is SepAxiOp.WRITE else 0} "
                        f"changed={len(changed)} window={key} ax={ax}"
                    )
                    if resp_ok and not changed and one_burst:
                        self.logger.info("CHK-ROW-BURST PASS: %s", line)
                    else:
                        self._fail("CHK-ROW-BURST", f"{line} beats={beats} changed={changed[:4]}")
                    self._walk(key, f"burst_{kind}", d, "SI")
                    # The single-beat control runs with the window closed; the
                    # burst cell is released only after it passes too.
                    if await self._burst_control(key, kind, start, snap):
                        await self._release()

    async def _burst_control(self, key, kind, start, snap) -> bool:
        """Step 19: the single beat at the burst start through the same entry."""
        if kind == "reg":
            cur, m = snap[start]
            comp = (~cur) & 0xFFFF_FFFF
            exp, mask = rr.write_readback(start, cur, comp)
            w = await self._si(SepAxiOp.WRITE, start, wdata=comp)
            r = await self._si(SepAxiOp.READ, start)
            ok = (
                w.resp_code == OKAY
                and r.resp_code == OKAY
                and (r.rdata & mask) == (exp & mask)
                and (exp & mask) != (cur & mask)
            )
            rst = await self._si(SepAxiOp.WRITE, start, wdata=cur)
            back = await self._si(SepAxiOp.READ, start)
            assert rst.resp_code == OKAY and (back.rdata & m) == (cur & m), (
                f"burst control restore of 0x{start:08x} read 0x{back.rdata & m:x}, "
                f"snapshot 0x{cur & m:x}"
            )
            line = (
                f"init=SI addr=0x{start:08x} size=2 kind=reg single_resp={_RN.get(r.resp_code)} "
                f"single_rdata=0x{r.rdata & 0xFFFF_FFFF:08x} wrote=0x{comp:08x} "
                f"expect=0x{exp & mask:x} field_mask=0x{mask:x} window={key}"
            )
        else:
            r = await self._si(SepAxiOp.READ, start)
            w = await self._si(SepAxiOp.WRITE, start, wdata=self.rng.getrandbits(32))
            er = rr.expected_cell(start, "r")
            ew = rr.expected_cell(start, "w")
            ok = (
                r.resp_code == er.resp
                and (r.rdata & 0xFFFF_FFFF) == er.rdata
                and w.resp_code == ew.resp
                and er.resp != DECERR
            )
            line = (
                f"init=SI addr=0x{start:08x} size=2 kind=hole single_resp={_RN.get(r.resp_code)} "
                f"single_rdata=0x{r.rdata & 0xFFFF_FFFF:08x} write_resp={_RN.get(w.resp_code)} "
                f"expect={_RN[er.resp]}/0x{er.rdata:08x} window={key}"
            )
        if ok:
            self.logger.info("CHK-ROW-BURST-CONTROL PASS: %s", line)
        else:
            self._fail("CHK-ROW-BURST-CONTROL", line)
        return ok

    # ------------------------------------------------------------ entropy pool
    async def _pool_probe(self) -> tuple[bool, str]:
        """Positive probe: the pool STATUS answers OKAY to one 64-bit SI read."""
        s = await self._si(SepAxiOp.READ, POOL_STATUS, size=3)
        ok = s.resp_code == OKAY
        return ok, f"probe_status_resp={_RN.get(s.resp_code)} probe_status=0x{s.rdata:016x}"

    async def _pool_leg(self) -> None:
        """SI write to the pool (register word and unmapped word) and SI read of an unmapped word."""
        row = rr.map_row(POOL_BASE)
        lo = POOL_BASE + POOL_EXTENT
        um = lo + 8 * self.rng.randrange(0, (row.end + 1 - 8 - lo) // 8 + 1)
        reg_word = self.rng.choice(POOL_REGS) + 4 * self.rng.randrange(0, 2)
        self.logger.info(
            "INFO-ROW-RAND LOG: pool extent=0x%x register word 0x%08x unmapped word 0x%08x",
            POOL_EXTENT,
            reg_word,
            um,
        )
        self._open()
        for a, kind in ((reg_word, "register"), (um, "unmapped")):
            wd = self.rng.getrandbits(32)
            await self._begin()
            pok, probe = await self._pool_probe()
            s = await self._si(SepAxiOp.WRITE, a, wdata=wd) if pok else None
            resp = s.resp_code if s is not None else -1
            line = (
                f"init=SI dir=W size=2 addr=0x{a:08x} off=0x{a - POOL_BASE:x} kind={kind} "
                f"wdata=0x{wd:08x} bresp={_RN.get(resp)} expect={_RN[POOL_WRITE_RESP]} {probe}"
            )
            if pok and resp == POOL_WRITE_RESP:
                self.logger.info("CHK-ROW-POOL-W PASS: %s", line)
                await self._release()
            else:
                self._fail("CHK-ROW-POOL-W", line)
        self._walk("pool", "write", "W", "SI")
        for a in (um, um + 4):
            await self._begin()
            pok, probe = await self._pool_probe()
            s = await self._si(SepAxiOp.READ, a) if pok else None
            resp = s.resp_code if s is not None else -1
            lane = (s.rdata & 0xFFFF_FFFF) if s is not None else 0
            line = (
                f"init=SI dir=R size=2 addr=0x{a:08x} off=0x{a - POOL_BASE:x} "
                f"rresp={_RN.get(resp)} rdata=0x{lane:08x} "
                f"expect={_RN[POOL_UNMAPPED_RESP]}/0x{POOL_UNMAPPED_RDATA:08x} {probe}"
            )
            if pok and resp == POOL_UNMAPPED_RESP and lane == POOL_UNMAPPED_RDATA:
                self.logger.info("CHK-ROW-POOL-UNMAPPED PASS: %s", line)
                await self._release()
            else:
                self._fail("CHK-ROW-POOL-UNMAPPED", line)
        self._walk("pool", "past", "R", "SI")
        self._close()

    # ---------------------------------------------------------- SPI host burst
    def _spi_regs(self) -> list[rr.Reg]:
        """Stable SPI host registers of the extent (the no-change compare set)."""
        return [r for r in rr.all_regs() if SPI_BASE <= r.addr < SPI_END and r.stable]

    def _spi_live_set(self) -> dict[int, int]:
        """The staged non-zero words a past beat must not carry."""
        return {a: self._expect_reg(a) for a in (SPI_CSID, SPI_ERROR_ENABLE, SPI_EVENT_ENABLE)}

    async def _spi_stage(self) -> None:
        """Window closed: stage non-zero values in CSID, ERROR_ENABLE and EVENT_ENABLE."""
        for a in (SPI_ERROR_STATUS, SPI_EVENT_ENABLE, SPI_ERROR_ENABLE, SPI_CSID):
            reg = rr.reg_by_word()[a]
            if not reg.readable or reg.width != 32:
                raise AssertionError(f"SPI host 0x{a:08x} ({reg.name}) is not a plain 32-bit read")
        assert SPI_EVENT_ENABLE + 4 == SPI_END, "EVENT_ENABLE is not the last word of the extent"
        # CSID odd and non-zero, so it is neither 0 nor 0xBADCAB1E.
        csid = (self.rng.getrandbits(31) << 1) | 1
        erren = self.rng.randrange(1, 0x1F)
        evten = self.rng.randrange(1, 0x40)
        for a, v, tag in (
            (SPI_CSID, csid, "CSID"),
            (SPI_ERROR_ENABLE, erren, "ERROR_ENABLE"),
            (SPI_EVENT_ENABLE, evten, "EVENT_ENABLE"),
        ):
            await self._lsu_write_reg(a, v, f"SPI {tag} stage")
        self.logger.info(
            "INFO-ROW-SPI-STAGE LOG: csid=0x%08x error_enable=0x%02x event_enable=0x%02x",
            self.regval[SPI_CSID],
            self.regval[SPI_ERROR_ENABLE],
            self.regval[SPI_EVENT_ENABLE],
        )

    def _new_value(self, addr: int) -> int:
        """A non-zero field value of an enable register that differs from its model."""
        mask = rr.reg_by_word()[addr].word_mask(addr)
        width = mask.bit_length()
        top = (1 << width) - 1
        assert mask == top and width > 1, (
            f"0x{addr:08x}: field mask 0x{mask:x} is not 0..{width - 1}"
        )
        cur = self._expect_reg(addr) & top
        # Values 1..top other than cur, drawn without rejection.
        v = self.rng.randrange(1, top)
        return v + 1 if v >= cur and cur != 0 else v

    async def _spi_burst(
        self, op: SepAxiOp, start: int, nbeats: int, words: list[int]
    ) -> tuple[SepAxiAccessSeq, list, dict | None]:
        mon = self.env.ext_axi_monitor
        ch = "ar" if op is SepAxiOp.READ else "aw"
        hs = cocotb.start_soon(capture_addr_handshake(ch, prefix="m_axi"))
        if op is SepAxiOp.READ:
            mon.start_beat_capture()
        wdata = 0
        for i, w in enumerate(words):
            wdata |= (w & 0xFFFF_FFFF) << (32 * i)
        s = await self._si(
            op, start, size=AXI_SIZE_32, wdata=wdata, length=4 * nbeats, burst=AXI_INCR
        )
        beats = mon.take_beat_capture() if op is SepAxiOp.READ else []
        return s, beats, take_handshake(hs)

    @staticmethod
    def _shape_ok(ax, start: int, nbeats: int) -> bool:
        return ax is not None and (ax["addr"], ax["len"], ax["size"], ax["burst"]) == (
            start,
            nbeats - 1,
            AXI_SIZE_32,
            AXI_INCR,
        )

    async def _spi_after(self) -> tuple[bool, list[str]]:
        """LSU read of every stable register and ERROR_STATUS against the model."""
        diff = []
        for a in [r.addr for r in self._spi_regs()] + [SPI_ERROR_STATUS]:
            m = rr.reg_by_word()[a].word_mask(a)
            _r, v = await self._lsu(SepAxiOp.READ, a)
            if (v & m) != (self._expect_reg(a) & m):
                diff.append(f"0x{a:08x}:0x{v & m:x}!=0x{self._expect_reg(a) & m:x}")
        return not diff, diff

    async def _spi_control(self) -> None:
        """CHK-ROW-SPI-BURST-CONTROL: the burst wholly inside the extent (window closed)."""
        start = SPI_INSIDE_START
        nbeats = (SPI_END - start) // 4
        addrs = [start + 4 * i for i in range(nbeats)]
        s, beats, ax = await self._spi_burst(SepAxiOp.READ, start, nbeats, [0] * nbeats)
        got = [(s.rdata >> (32 * i)) & 0xFFFF_FFFF for i in range(nbeats)]
        masks = [rr.reg_by_word()[a].word_mask(a) for a in addrs]
        exp = [self._expect_reg(a) for a in addrs]
        ok = (
            self._shape_ok(ax, start, nbeats)
            and beats == [OKAY] * nbeats
            and all((g & m) == (e & m) for g, e, m in zip(got, exp, masks))
        )
        line = (
            f"init=SI dir=R start=0x{start:08x} size=2 len={nbeats - 1} beats={beats} "
            f"rdata={[hex(g & m) for g, m in zip(got, masks)]} "
            f"rsvd={[hex(g & ~m & 0xFFFF_FFFF) for g, m in zip(got, masks)]} "
            f"expect={[hex(e & m) for e, m in zip(exp, masks)]} ax={ax}"
        )
        if ok:
            self.logger.info("CHK-ROW-SPI-BURST-CONTROL PASS: %s", line)
        else:
            self._fail("CHK-ROW-SPI-BURST-CONTROL", line)
        # Write burst: new values in both enables, 0 to ERROR_STATUS (W1C).
        words = []
        for a in addrs:
            words.append(0 if a == SPI_ERROR_STATUS else self._new_value(a))
        s, _b, ax = await self._spi_burst(SepAxiOp.WRITE, start, nbeats, words)
        for a, w in zip(addrs, words):
            self.regval[a] = rr.write_readback(a, self._expect_reg(a), w)[0]
        same, diff = await self._spi_after()
        ok = self._shape_ok(ax, start, nbeats) and s.resp_code == OKAY and same
        line = (
            f"init=SI dir=W start=0x{start:08x} size=2 len={nbeats - 1} "
            f"bresp={_RN.get(s.resp_code)} wdata={[hex(w) for w in words]} "
            f"landed={int(same)} diff={diff} ax={ax}"
        )
        if ok:
            self.logger.info("CHK-ROW-SPI-BURST-CONTROL PASS: %s", line)
        else:
            self._fail("CHK-ROW-SPI-BURST-CONTROL", line)

    async def _spi_cross(self, op: SepAxiOp, start: int) -> None:
        """CHK-ROW-SPI-BURST: one INCR burst of 32-bit beats across the extent end."""
        d = "R" if op is SepAxiOp.READ else "W"
        n_in = (SPI_END - start) // 4
        nbeats = n_in + self.rng.randrange(1, SPI_MAX_PAST_BEATS + 1)
        addrs = [start + 4 * i for i in range(nbeats)]
        assert (start & ~0xFFF) == ((addrs[-1] + 3) & ~0xFFF), "burst crosses a 4 KB page"
        live = self._spi_live_set()
        live_words = [live[a] for a in sorted(live)]
        words = []
        if op is SepAxiOp.WRITE:
            for i, a in enumerate(addrs):
                if i >= n_in:
                    words.append((~live_words[(i - n_in) % len(live_words)]) & 0xFFFF_FFFF)
                elif a == SPI_ERROR_STATUS:
                    words.append(0)
                else:
                    words.append(self._new_value(a))
        else:
            words = [0] * nbeats
        self.logger.info(
            "INFO-ROW-RAND LOG: spi cross dir=%s start=0x%08x in_beats=%d len=%d",
            d,
            start,
            n_in,
            nbeats - 1,
        )
        self._open()
        await self._begin()
        s, beats, ax = await self._spi_burst(op, start, nbeats, words)
        self._close()
        shape = self._shape_ok(ax, start, nbeats)
        if op is SepAxiOp.READ:
            got = [(s.rdata >> (32 * i)) & 0xFFFF_FFFF for i in range(nbeats)]
            in_ok = len(beats) == nbeats
            in_cells = []
            for i in range(n_in):
                a = addrs[i]
                m = rr.reg_by_word()[a].word_mask(a)
                e = self._expect_reg(a)
                in_ok = in_ok and beats[i] == OKAY and (got[i] & m) == (e & m)
                in_cells.append(
                    f"0x{a:08x}:{_RN.get(beats[i]) if i < len(beats) else 'none'}/"
                    f"0x{got[i] & m:x}/exp=0x{e & m:x}/rsvd=0x{got[i] & ~m & 0xFFFF_FFFF:x}"
                )
            past_resp = beats[n_in:]
            past_data = got[n_in:]
            live_vals = set(live.values())
            past_ok = (
                len(past_resp) == nbeats - n_in
                and all(r is not None and r != OKAY for r in past_resp)
                and not (set(past_data) & live_vals)
            )
            ok = shape and in_ok and past_ok
            line = (
                f"init=SI dir=R start=0x{start:08x} size=2 len={nbeats - 1} beats={len(beats)} "
                f"in={in_cells} past_not_okay={int(all(r is not None and r != OKAY for r in past_resp))} "
                f"past_live_hit={sorted(hex(v) for v in set(past_data) & live_vals)} "
                f"live_set={[hex(v) for v in live_words]} ax={ax}"
            )
            self.logger.info(
                "OBS-ROW-SPI-BURST-CODE: dir=R start=0x%08x past_resp=%s past_data=%s",
                start,
                [_RN.get(r, r) for r in past_resp],
                [hex(v) for v in past_data],
            )
        else:
            for i in range(n_in):
                a = addrs[i]
                self.regval[a] = rr.write_readback(a, self._expect_reg(a), words[i])[0]
            same, diff = await self._spi_after()
            not_okay = s.resp_code in (SLVERR, DECERR)
            ok = shape and not_okay and same
            line = (
                f"init=SI dir=W start=0x{start:08x} size=2 len={nbeats - 1} "
                f"b_not_okay={int(not_okay)} in_wdata={[hex(w) for w in words[:n_in]]} "
                f"past_wdata={[hex(w) for w in words[n_in:]]} landed_and_unchanged={int(same)} "
                f"diff={diff} ax={ax}"
            )
            self.logger.info(
                "OBS-ROW-SPI-BURST-CODE: dir=W start=0x%08x bresp=%s",
                start,
                _RN.get(s.resp_code, s.resp_code),
            )
        self._walk("spi_host", "burst_cross", d, "SI")
        if ok:
            self.logger.info("CHK-ROW-SPI-BURST PASS: %s", line)
            await self._release()
        else:
            self._fail("CHK-ROW-SPI-BURST", line)

    async def _spi_leg(self) -> None:
        """SPI host extent: staging and control with the window closed, then the crossing bursts."""
        await self._spi_stage()
        await self._spi_control()
        starts = list(SPI_CROSS_STARTS)
        self.rng.shuffle(starts)
        for op in (SepAxiOp.READ, SepAxiOp.WRITE):
            for start in starts:
                await self._spi_cross(op, start)

    # -------------------------------------------------------- open-value legs
    def _draw_attrs(self, *, lock: int | None = None) -> dict[str, int]:
        """SI attributes off the default: AxPROT[0] and [2], a non-zero AxUSER,
        AxCACHE, AxQOS, AxREGION, and AxLOCK unless ``lock`` fixes it."""
        r = self.leg_rng
        return {
            "prot": SI_PROT | (r.getrandbits(1) << 2) | r.getrandbits(1),
            "user": r.randrange(1, 1 << 12),
            "cache": r.getrandbits(4),
            "qos": r.getrandbits(4),
            "region": r.getrandbits(4),
            "lock": r.getrandbits(1) if lock is None else lock,
        }

    async def _si_attrs(
        self,
        op: SepAxiOp,
        addr: int,
        drawn: dict[str, int],
        *,
        size: int = 2,
        wdata: int = 0,
        wuser: int | None = None,
    ) -> tuple[SepAxiAccessSeq, dict[str, int] | None]:
        """One SI access with ``drawn`` attributes; also returns what the SI port
        carried on its address handshake (with the WUSER of the W beat when
        given), or None when no handshake was seen."""
        ch = "ar" if op is SepAxiOp.READ else "aw"
        fields = AX_ATTRS + ("addr", "size")
        hs = cocotb.start_soon(_capture_si(ch, fields))
        ws = cocotb.start_soon(_capture_si("w", ("user",))) if wuser is not None else None
        attrs = {k: drawn[k] for k in ("cache", "qos", "region", "lock")}
        if wuser is not None:
            attrs["wuser"] = wuser
        s = await self._si(
            op,
            addr,
            size=size,
            wdata=wdata,
            prot=drawn["prot"],
            user=drawn["user"],
            attrs=attrs,
            rng=self.leg_rng,
        )
        seen = take_handshake(hs)
        if seen is not None and ws is not None:
            w = take_handshake(ws)
            seen["wuser"] = None if w is None else w["user"]
        return s, seen

    def _attr_ctrl(self, row: str, d: str, want: dict, seen: dict | None) -> bool:
        """CTRL-ROW-ATTR: the SI port carried the drawn request to the cell."""
        ok = seen is not None and all(seen.get(k) == v for k, v in want.items())
        return self._ctrl(
            "ROW-ATTR",
            ok,
            f"row={row} dir={d} seen=[{_attr_txt(seen)}] drawn=[{_attr_txt(want)}]",
        )

    async def _leg_cov(self, leg: str, ok: bool) -> None:
        """Pass label of an open-value leg whose controls all passed."""
        if ok:
            set_open_value_leg_pass(leg)
            await ClockCycles(cocotb.top.clk_i, _LABEL_CLOCKS)
            set_open_value_leg_pass(None)

    async def _attr_read(
        self, row: str, reg: rr.Reg | None, drawn: dict[str, int], *, addr: int = 0
    ) -> bool:
        """SI read of a register word with ``drawn`` attributes between two LSU reads.

        ``reg`` None: one 64-bit SI read of the pool ``STATUS`` at ``addr``, the
        only pool access shape the pool states, with no LSU reads (``fifo_level``
        moves while the pool fills)."""
        if reg is None:
            a, size, mask = addr, 3, (1 << 64) - 1
            lsu_b = lsu_a = None
        else:
            a, size, mask = reg.addr, 2, reg.word_mask(reg.addr)
            lsu_b = (await self._lsu(SepAxiOp.READ, a))[1] & mask
        s, seen = await self._si_attrs(SepAxiOp.READ, a, drawn, size=size)
        if reg is not None:
            lsu_a = (await self._lsu(SepAxiOp.READ, a))[1] & mask
        self.logger.info(
            "OBS-ROW-ATTR LOG: row=%s dir=R size=%d addr=0x%08x attrs=[%s] resp=%s "
            "rdata=0x%x lsu_before=%s lsu_after=%s field_mask=0x%x graded=0",
            row,
            size,
            a,
            _attr_txt(drawn),
            _RN.get(s.resp_code),
            s.rdata & mask,
            _hex(lsu_b),
            _hex(lsu_a),
            mask,
        )
        return self._attr_ctrl(row, "R", {**drawn, "addr": a, "size": size}, seen)

    async def _attr_read_leg(self) -> None:
        """Each live SI word read again with the attributes drawn at its CHK-ROW cell."""
        missing = sorted(set(rr.LIVE_SI_ROWS) - set(self.live_draw))
        ok = self._ctrl(
            "ROW-ATTR",
            not missing,
            f"rows={len(self.live_draw)} live_rows={len(rr.LIVE_SI_ROWS)} missing={missing}",
        )
        for key, (reg, drawn) in self.live_draw.items():
            ok = await self._attr_read(key, reg, drawn) and ok
        await self._leg_cov("row_attr_drawn_read", ok)

    async def _attr_cell_leg(self) -> None:
        """Exclusive reads with drawn attributes: the pool STATUS (one 64-bit
        access) and an ABR register, then the SPI host CSID and the DMA live word."""
        cells = (
            ("pool", None),
            ("abr", _reg_named("abr", HOLE_NEIGHBOUR_NAME["abr"])),
            ("spi_host", rr.reg_by_word()[SPI_CSID]),
            ("dma", rr.live_word("dma")),
        )
        oks = [
            await self._attr_read(row, reg, self._draw_attrs(lock=1), addr=POOL_STATUS)
            for row, reg in cells
        ]
        await self._leg_cov("row_attr_pool_cell", all(oks[:2]))
        await self._leg_cov("row_attr_spi_dma_cell", all(oks[2:]))

    async def _attr_write(self, drawn: dict[str, int], *, wuser: int) -> bool:
        """SI write of the complement of ``CSID`` with ``drawn`` attributes, read
        back and restored from the LSU."""
        before = self._expect_reg(SPI_CSID)
        wd = (~before) & 0xFFFF_FFFF
        s, seen = await self._si_attrs(SepAxiOp.WRITE, SPI_CSID, drawn, wdata=wd, wuser=wuser)
        _r, back = await self._lsu(SepAxiOp.READ, SPI_CSID)
        self.logger.info(
            "OBS-ROW-ATTR LOG: row=spi_host dir=W size=2 addr=0x%08x reg=CSID attrs=[%s] "
            "wuser=%s bresp=%s wdata=0x%08x before=0x%08x readback=0x%08x graded=0",
            SPI_CSID,
            _attr_txt(drawn),
            _hex(wuser),
            _RN.get(s.resp_code),
            wd,
            before,
            back & 0xFFFF_FFFF,
        )
        self.regval[SPI_CSID] = back & 0xFFFF_FFFF
        await self._lsu_write_reg(SPI_CSID, before, "SPI CSID restore")
        want = {**drawn, "addr": SPI_CSID, "size": 2, "wuser": wuser}
        return self._attr_ctrl("spi_host", "W", want, seen)

    async def _attr_write_leg(self) -> None:
        """A write with drawn AW attributes and WUSER."""
        wuser = self.leg_rng.getrandbits(len(cocotb.top.m_axi_wuser))
        ok = await self._attr_write(self._draw_attrs(), wuser=wuser)
        await self._leg_cov("row_attr_drawn_write", ok)

    async def _narrow_leg(self) -> None:
        """1- and 2-byte SI reads and writes to a Reserved, a Past Extent and a Hole cell."""
        r = self.leg_rng
        rsvd = r.choice(rr.RESERVED_BASES)
        past = r.choice(rr.PAST_ROWS)
        hole = r.choice(rr.HOLE_ROWS)
        prow = rr.map_row(past)
        cells = (
            (f"rsvd_{rsvd:08x}", "reserved", rsvd),
            (past, "past", prow.base + prow.extent),
            (hole, "hole", r.choice(rr.hole_words(hole))),
        )
        ok = True
        for row, kind, word in cells:
            for size in (0, 1):
                n = 1 << size
                for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                    d = "R" if op is SepAxiOp.READ else "W"
                    a = word + n * r.randrange(0, 4 // n)
                    wd = r.getrandbits(8 * n) if op is SepAxiOp.WRITE else None
                    hs = cocotb.start_soon(
                        _capture_si("ar" if wd is None else "aw", ("addr", "size"))
                    )
                    s = await self._si(op, a, size=size, wdata=wd or 0, rng=r)
                    seen = take_handshake(hs)
                    self.logger.info(
                        "OBS-ROW-NARROW LOG: cell=%s kind=%s dir=%s size=%d addr=0x%08x resp=%s "
                        "rdata=%s wdata=%s graded=0",
                        row,
                        kind,
                        d,
                        size,
                        a,
                        _RN.get(s.resp_code),
                        _hex(s.rdata & ((1 << (8 * n)) - 1)) if wd is None else "na",
                        _hex(wd),
                    )
                    reached = seen is not None and (seen["addr"], seen["size"]) == (a, size)
                    ok = (
                        self._ctrl(
                            "ROW-NARROW",
                            reached,
                            f"cell={row} kind={kind} dir={d} addr=0x{a:08x} "
                            f"axsize={_hex(None if seen is None else seen['size'])} expect={size}",
                        )
                        and ok
                    )
        await self._leg_cov("row_narrow_unbacked", ok)

    async def _open_value_legs(self) -> None:
        """Window closed: the attribute and narrow legs, whose results no
        specification states, log OBS lines behind their CTRL lines."""
        await self._attr_read_leg()
        await self._attr_cell_leg()
        await self._attr_write_leg()
        await self._narrow_leg()

    # ---------------------------------------------------------------- scenario
    # ------------------------------------------------------------ logged legs
    async def _burst_past_leg(self) -> None:
        """A 2-beat SI INCR burst from the last register word of a non-crypto row."""
        mon = self.env.ext_axi_monitor
        for name, base in BURST_PAST_ROWS:
            row = rr.map_row(base)
            last = row.base + row.extent - 4
            _r, before = await self._lsu(SepAxiOp.READ, last)
            mon.start_beat_capture()
            r = await self._si(SepAxiOp.READ, last, length=8, burst=AXI_INCR)
            mon.take_beat_capture()
            detail = mon.last_beat_detail
            wd = (before & 0xFFFF_FFFF) | (self.rng.getrandbits(32) << 32)
            w = await self._si(SepAxiOp.WRITE, last, wdata=wd, length=8, burst=AXI_INCR)
            # The read-back of a watchdog register waits for the previous write to
            # land in the clk_wdt_i domain.
            saved = self.cfg.axi_timeout_ns
            self.cfg.axi_timeout_ns = max(saved, WDT_CDC_CLKS * self.cfg.wdt_clk_period_ns)
            try:
                _r, after = await self._lsu(SepAxiOp.READ, last)
            finally:
                self.cfg.axi_timeout_ns = saved
            self.logger.info(
                "OBS-ROW-BURST row=%s start=0x%08x len=1 rresp=%s rresp_resp=%s bresp=%s "
                "rdata=0x%016x lsu_before=0x%08x lsu_after=0x%08x",
                name,
                last,
                ",".join(_RN.get(b[0], "X") for b in detail) or "none",
                _RN.get(r.resp_code),
                _RN.get(w.resp_code),
                r.rdata,
                before & 0xFFFF_FFFF,
                after & 0xFFFF_FFFF,
            )

    async def _subword_leg(self) -> None:
        """LSU AxSIZE 0 and 1 reads and writes to registers and memories."""
        for name, addr, restore in SUBWORD_TARGETS:
            if name == "otbn_imem":
                # A memory word holds a written value before its first read.
                await self._lsu(SepAxiOp.WRITE, addr, wdata=self.rng.getrandbits(32))
            _r, cur = await self._lsu(SepAxiOp.READ, addr)
            cur &= 0xFFFF_FFFF
            for size, off in ((0, 1), (1, 2)):
                mask = (1 << (8 << size)) - 1
                old = (cur >> (8 * off)) & mask
                wv = (~old & mask) if restore else old
                rd_resp, rdata = await self._lsu(SepAxiOp.READ, addr + off, size=size, expect="any")
                wr_resp, _w = await self._lsu(
                    SepAxiOp.WRITE, addr + off, size=size, wdata=wv, expect="any"
                )
                _r, rb = await self._lsu(SepAxiOp.READ, addr)
                self.logger.info(
                    "OBS-REG-SUBWORD target=%s addr=0x%08x size=%d rd_resp=%s rdata=0x%x "
                    "wr_resp=%s wdata=0x%x word_before=0x%08x word_after=0x%08x",
                    name,
                    addr + off,
                    size,
                    _RN.get(rd_resp),
                    rdata & mask,
                    _RN.get(wr_resp),
                    wv,
                    cur,
                    rb & 0xFFFF_FFFF,
                )
                if name == SUBWORD_GRADED:
                    line = (
                        f"target={name} addr=0x{addr + off:08x} size={size} "
                        f"rd_resp={_RN.get(rd_resp)} wr_resp={_RN.get(wr_resp)} "
                        f"expect=OKAY/SLVERR"
                    )
                    if (rd_resp, wr_resp) == (OKAY, SLVERR):
                        self.logger.info("CHK-REG-SUBWORD-WDT PASS: %s", line)
                    else:
                        self._fail("CHK-REG-SUBWORD-WDT", line)
                if restore:
                    await self._lsu(SepAxiOp.WRITE, addr, wdata=cur)

    async def _fabric_csr_leg(self) -> None:
        """SI reads of fabric CSRs that the LSU staged, and of FEAT_CTRL.

        CHK-ROW-FABRIC-CSR: the inbound crossbar reaches the system CSRs, which
        program the inbound filter entries and the remaps (``fabric.adoc``, Fabric
        Topology), and forwards the other addresses below ``0x4000_0000`` to the
        local crossbar (``memory_map.adoc``, Units Unreachable from the Inbound
        Port), so an SI read of the inbound filter START word, of the alias remap
        START word and of ``FEAT_CTRL`` answers OKAY with the staged value or the
        bring-up golden. The AP and STEE remap words are logged
        (``OBS-ROW-FABRIC-CSR``): ``memory_map.adoc`` lists the AP/STEE remap
        regions as unreachable from the inbound port.
        """
        targets = (
            ("infilt_start", INFILT_BASE + FILTER_STRIDE + FILTER_START_ADDR, 0xFFFF_FFF8),
            ("alias_start", ALIAS_BASE + ALIAS_STRIDE + ALIAS_START, ALIAS_START_MASK),
            ("ap_attrs", AP_BASE + REMAP_STRIDE + REMAP_ATTRS, REMAP_OFFSET_LO_MASK),
            ("stee_attrs", STEE_BASE + REMAP_ATTRS, REMAP_OFFSET_LO_MASK),
        )
        src_addr = targets[0][1]
        for name, addr, mask in targets:
            _r, cur = await self._lsu(SepAxiOp.READ, addr)
            staged = self.rng.getrandbits(32) & mask
            await self._lsu(SepAxiOp.WRITE, addr, wdata=staged)
            _r, lsu_rb = await self._lsu(SepAxiOp.READ, addr)
            s = await self._si(SepAxiOp.READ, addr)
            line = (
                f"target={name} addr=0x{addr:08x} staged=0x{staged:08x} "
                f"lsu_rb=0x{lsu_rb & 0xFFFF_FFFF:08x} si_resp={_RN.get(s.resp_code)} "
                f"si_rdata=0x{s.rdata & 0xFFFF_FFFF:08x}"
            )
            if name in ("ap_attrs", "stee_attrs"):
                self.logger.info("OBS-ROW-FABRIC-CSR %s", line)
            elif s.resp_code == RESP_OKAY and (s.rdata & 0xFFFF_FFFF) == staged:
                self.logger.info("CHK-ROW-FABRIC-CSR PASS: %s expect=OKAY/staged", line)
            else:
                self._fail("CHK-ROW-FABRIC-CSR", f"{line} expect=OKAY/staged")
            if name == "stee_attrs":
                src = self.rng.randrange(1, 16)
                miss = self.rng.choice([u for u in range(16) if u != src])
                # Probed on the inbound filter START word of entry 1, which the SI
                # reaches; entry 0 (the probe's entry) leaves it unchanged.
                _r, ref = await self._lsu(SepAxiOp.READ, src_addr)
                ref &= 0xFFFF_FFFF
                w = await self._si(SepAxiOp.READ, src_addr)
                await self._program_entry(src_id=src)
                got = {}
                for kind, u in (("src_match", src), ("src_mismatch", miss)):
                    t = await self._si(SepAxiOp.READ, src_addr, user=u)
                    got[kind] = (t.resp_code, t.rdata & 0xFFFF_FFFF)
                await self._program_entry()
                wild = (w.resp_code, w.rdata & 0xFFFF_FFFF)
                line = (
                    f"target=infilt_start entry_src_id={src} axuser_match=0x{src:x} "
                    f"axuser_mismatch=0x{miss:x} wildcard={_RN.get(wild[0])}/0x{wild[1]:08x} "
                    f"match={_RN.get(got['src_match'][0])}/0x{got['src_match'][1]:08x} "
                    f"mismatch={_RN.get(got['src_mismatch'][0])}/0x{got['src_mismatch'][1]:08x} "
                    f"expect=OKAY/0x{ref:08x},OKAY/0x{ref:08x},DECERR"
                )
                if (
                    wild == (RESP_OKAY, ref)
                    and got["src_match"] == wild
                    and got["src_mismatch"][0] == RESP_DECERR
                ):
                    self.logger.info("CHK-ROW-FILTER-SRC PASS: %s", line)
                else:
                    self._fail("CHK-ROW-FILTER-SRC", line)
            await self._lsu(SepAxiOp.WRITE, addr, wdata=cur)
        _r, lsu_v = await self._lsu(SepAxiOp.READ, LCC_FEAT_CTRL)
        lo = await self._si(SepAxiOp.READ, LCC_FEAT_CTRL)
        hi = await self._si(SepAxiOp.READ, LCC_FEAT_CTRL + 4)
        got = ((hi.rdata & 0xFFFF_FFFF) << 32) | (lo.rdata & 0xFFFF_FFFF)
        line = (
            f"target=lc_feat_ctrl addr=0x{LCC_FEAT_CTRL:08x} lsu_rb=0x{lsu_v & 0xFFFF_FFFF:08x} "
            f"si_resp={_RN.get(lo.resp_code)},{_RN.get(hi.resp_code)} si_rdata=0x{got:016x} "
            f"expect=OKAY/0x{self.feat_golden:016x}"
        )
        if lo.resp_code == hi.resp_code == RESP_OKAY and got == self.feat_golden:
            self.logger.info("CHK-ROW-FABRIC-CSR PASS: %s", line)
        else:
            self._fail("CHK-ROW-FABRIC-CSR", line)

    async def _graded_legs(self) -> None:
        """Every graded leg; each opens the window only around its graded accesses."""
        self._open()
        await self._reset_ctrl_leg()
        self._close()
        await self._wait_hmac()
        await self._program_refs()
        self._open()
        await self._otbn_cache_leg()
        await self._reserved_leg()
        await self._hole_leg()
        self._open()
        await self._past_leg()
        await self._live_leg()
        await self._km_leg()
        await self._burst_leg()
        await self._pool_leg()
        await self._spi_leg()
        self._close()
        await self._open_value_legs()
        await self._burst_past_leg()
        await self._fabric_csr_leg()
        await self._subword_leg()

    async def run_scenario(self) -> None:
        self.rng = SepSeededRng(self.random_seed())
        self.walked: set[tuple[str, str, str, str]] = set()
        self.fails: list[str] = []
        self.released = 0
        self.si_id_ok = 0
        self.si_id_bad = 0
        self.regval: dict[int, int] = {}
        self.noalias_draws: Counter = Counter()
        self.noalias_ctl: set[str] = set()
        self.live_draw: dict[str, tuple[rr.Reg, dict[str, int]]] = {}
        self.leg_rng = SepSeededRng(self.random_seed() ^ _ATTR_SALT)
        inventory = self._inventory()
        self.logger.info(
            "INFO-ROW-INVENTORY LOG: seed=%d cells=%d live=%s",
            self.random_seed(),
            len(inventory),
            " ".join(
                f"{k}=0x{rr.live_word(k).addr:08x}({rr.live_word(k).name})"
                for k in rr.ROW_BASE
                if rr.live_word(k) is not None
            ),
        )
        assert rr.live_word("abr") is None, (
            "ABR has a non-zero-reset stable register; the leaf has no ABR live cell"
        )

        await self._bring_up()
        await self._program_entry()

        try:
            await self._graded_legs()
        except BaseException:
            # Any raise ends the leaf: close the window and drop the held samples.
            close_graded_window(self.logger)
            set_row_pass(ROW_PASS_DROP, self.logger)
            raise
        self.logger.info("INFO-ROW-PASS LOG: releases=%d fails=%d", self.released, len(self.fails))
        if self.si_id_ok == 0:
            self._fail("CHK-SI-ID-ECHO", "no SI access answered, nothing graded")
        elif not self.si_id_bad:
            self.logger.info(
                "CHK-SI-ID-ECHO PASS: %d SI accesses answered BID/RID equal to the drawn AxID",
                self.si_id_ok,
            )

        # The no-alias control must have changed each reference.
        missing_ctl = {"reset_ctrl", "hmac", "kmac"} - self.noalias_ctl
        assert not missing_ctl, f"CHK-ROW-NOALIAS FAIL: no control for {sorted(missing_ctl)}"

        # Step 20: stimulus completeness.
        kinds = Counter(k for _r, k, _d, _i in self.walked)
        line = (
            f"seed={self.random_seed()} walked={len(self.walked & inventory)} "
            f"inventory={len(inventory)} rows={len({r for r, *_ in self.walked})} "
            f"reserved={kinds['reserved']} past={kinds['past']} hole={kinds['hole']} "
            f"live={kinds['live']} si={sum(1 for *_x, i in self.walked if i == 'SI')} "
            f"burst={kinds['burst_reg'] + kinds['burst_hole']}"
        )
        missing = sorted(inventory - self.walked)
        extra = sorted(self.walked - inventory)
        if missing or extra:
            self._fail("CTRL-ROW-RAND", f"{line} missing={missing} extra={extra}")
        else:
            self.logger.info("CTRL-ROW-RAND LOG: %s", line)

        if self.fails:
            raise AssertionError(f"{len(self.fails)} check failure(s); first: {self.fails[0]}")
