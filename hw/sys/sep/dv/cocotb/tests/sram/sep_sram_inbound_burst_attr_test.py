# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""INCR bursts into SRAM from the SMN-inbound master keep their data under any
request attribute the inbound filter admits.

``hw/sys/sep/doc/fabric.adoc``: the SRAM target serves INCR bursts of every
length, and the System Interface is the one crossbar initiator that may issue
bursts. The inbound filter decides on the address, ``prot[1]``, ``user[3:0]``
and ``AxLEN`` only (``hw/ip/axi_filter/doc/index.adoc``). Two entries over the
same 16 KiB SRAM window, one per ``allow_ns`` value, with ``src_id = 0`` and
``allow_burst = 1``, admit every access this test draws. The other request
fields are not decision inputs, and the SEP documents give them no effect on
an SRAM access, so none of them may change the data.

Each case is one seeded INCR burst write (1 to 256 beats; 1, 256 and two
exclusive-shaped short bursts on every seed, one read with ARLOCK set) of
walking-one, walking-zero or random words, then a short unaligned
overlay write whose first and last beats carry partial strobes, then two
CPU-LSU word writes into the same span, then a burst read of the whole span.
Every inbound access draws AxID (non-zero), AxPROT, AxCACHE, AxQOS, AxREGION,
AxUSER and WUSER, and the read draws ARLOCK when the burst meets the AXI4
exclusive-access rules. AWLOCK of the cases stays 0: an exclusive write that a slave
refuses leaves memory unchanged, so its data result is not defined.

CTRL-SRAM-IN-STIM: each AW / AR handshake on the m_axi port carries the drawn
ID, address, AxLEN, AxSIZE, AxBURST, AxLOCK, AxCACHE, AxPROT, AxQOS, AxREGION
and AxUSER, and every W beat of a write carries the drawn WUSER, so the
verdicts below are about the attributes the log names.

CHK-SRAM-IN-WRITE: every inbound write answers OKAY with BID equal to AWID.

CHK-SRAM-IN-READ: every beat of the burst read answers OKAY (EXOKAY allowed
on an exclusive read) and RLAST falls on the last beat and on no other (both
sampled per beat on the m_axi R channel), RID equals ARID, and every beat
equals the byte model.

CHK-SRAM-IN-STRB: on the overlay's first and last beats, the strobed bytes
hold the overlay and the unstrobed bytes keep the burst data (AXI4 A3.4.3).

CHK-SRAM-IN-XPATH: the CPU-LSU master reads the burst's first, last and two
seeded beats back equal to the model, so the inbound writes landed at the
addresses they named; and the inbound burst read returns the words the CPU-LSU
master wrote, so the read path returns SRAM, not a copy of its own writes.

A data mismatch does not stop the run: every case still runs, and the test
then fails once, naming each of CHK-SRAM-IN-READ, CHK-SRAM-IN-STRB and
CHK-SRAM-IN-XPATH that saw a mismatch, with its count and first mismatch. A
fault in one byte lane then shows on every data checker it reaches.

CHK-SRAM-XMASTER: after the cases, one SRAM word in the window is written by
one master and read by another, for each of the 6 ordered (writer, reader)
pairs of the System Interface (SI), the CPU-LSU master and the DMA, in a seeded
order on every seed. Each read returns the value the writer of that leg wrote,
a fresh non-zero value that differs from every other value the legs write. The
SEP AXI4 connectivity figure (``hw/sys/sep/doc/fabric.adoc``,
``assets/sep_axi_connectivity.svg``, row ``sram``) connects the lsu, dma and
ext initiators to SRAM. The DMA writes the word as an 8-byte copy from a second
word that the CPU-LSU master filled, and reads it as an 8-byte copy to a third
word that the CPU-LSU master then reads. Every leg runs, and the test then
fails once, naming each failing leg.

CTRL-SRAM-XMASTER-PRE: before the write of a leg, the CPU-LSU master reads the
shared word back equal to the previous leg's value (or the initial fill), and,
for a DMA reader, the copy destination back equal to a sentinel written for
that leg, so neither already holds the value of the leg.
CTRL-SRAM-XMASTER-DMA: each DMA copy ends with STATUS.DONE set and
STATUS.ERROR and STATUS.ABORTED clear within the poll bound of ``SepDmaOps``
(``vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/secure_dma.rdl``,
STATUS.DONE). The DMA uses address-space ID 0x7, the
internal host port (``hw/sys/sep/doc/dma.adoc``).

After CHK-SRAM-XMASTER passes for a leg, the test writes its pair to the pass
label of ``sep_sram_access_cg.cp_xmaster_pair`` (``set_sram_access_pass``).

Logged, not graded: after the cross-master legs, one SRAM word in the window takes an
exclusive read and then a write with AWLOCK 1 and the same ID and address. No
SEP document states the result. CTRL-SRAM-IN-ATTR: the AR handshake of the
read and the AW handshake of the write on the m_axi port carried lock 1, the
drawn ID and the word address. OBS-SRAM-IN-EXCL-WR logs the response of each
access and the word before and after, read by the CPU-LSU master. The
cross-master legs and this leg run in the coverage window of this leaf.

CHK-SRAM-CONC-DATA: after the coverage window closes, one inbound INCR burst
write (16 to 256 beats inside one 4 KiB page of the window, every strobe
high) and 8 CPU-LSU word writes to other words of the window start together,
every word a fresh non-zero value that differs from every other word of the
leg. The connectivity figure above connects both masters to SRAM.
After both finish, the CPU-LSU master reads every word of both sets, and the
inbound master reads the burst span in one INCR burst and each CPU-LSU word
on its own. Every write and every read answers OKAY, and every word read
equals the byte model. Every access runs, and the test then fails once with
the failure count and the first failures. Arbitration order, latency and the
response IDs are not graded.

CTRL-SRAM-CONC-OVERLAP: sampled on every clock at the TB ports, the inbound
write is outstanding from its first ``m_axi_awvalid`` to its B handshake, and
each CPU-LSU write from its first ``s_axi_awvalid`` to its B handshake. At
least one clock has both outstanding; with none the test fails. A window
opens at AW valid, not at the AW handshake, so the control does not depend on
the order the crossbar grants the two masters.

The cross-master, AWLOCK and concurrent legs each draw on a seeded stream of
their own, so the case draws keep their values.

Run mode: no_cpu (CPU-LSU master) with the external SMN master, and
+skip_fuse_sense with no shadow preload. LC_STATE is then INVALID, FEAT_CTRL is
zero and the inbound filter is in the m_axi path, so the test programs the
filter window. The window, lengths, starts, data, overlay, CPU-LSU words and
every inbound request attribute come from SepSeededRng.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, Event, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_common import resp_name
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_open_value_leg_pass,
    set_sram_access_pass,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq, take_handshake
from seq_lib.sep_dma_ops import OP_COPY, SepDmaOps
from seq_lib.sep_inbound_attr_seq import (
    BURST_INCR,
    RESP_OKAY,
    SepInboundAttrs,
    SepInboundAttrTally,
    exclusive_legal,
)
from seq_lib.sep_inbound_filter_rule_seq import SepInboundFilter, SepInboundFilterCfg
from seq_lib.sep_sram_inbound_burst_seq import (
    BEAT_BYTES,
    MASK64,
    MAX_BEATS,
    PAGE_BYTES,
    SIZE_8B,
    WINDOW_PAGES,
    WORD_BITS,
    SepSramByteModel,
    SepSramInboundCase,
    SepSramInboundCfg,
    capture_ax,
    capture_r_beats,
    capture_wuser,
)

TEST = "sep_sram_inbound_burst_attr_test"
# Seeded stream of the AWLOCK leg.
_ATTR_SALT = 0x5352_4154
# Seeded stream of the cross-master leg.
_XMASTER_SALT = 0x5352_584D
# Masters of the cross-master leg; the index is the FCOV cell code.
SI, LSU, DMA = 0, 1, 2
MASTER_NAME = ("SI", "LSU", "DMA")
XMASTER_PAIRS = tuple((w, r) for w in (SI, LSU, DMA) for r in (SI, LSU, DMA) if w != r)
# Address-space ID of the DMA internal host port (hw/sys/sep/doc/dma.adoc,
# address-space ID 0x7).
DMA_ASID = 0x7
# Seeded stream of the concurrent leg.
_CONC_SALT = 0x5352_434E
# The inbound burst of the concurrent leg is at least this long, so its W
# phase lasts long enough for the CPU-LSU writes started with it to be issued
# while it is outstanding.
CONC_MIN_BEATS = 16
CONC_LSU_WRITES = 8
# TB ports of the inbound (SI) and the CPU-LSU masters.
BUSES = ("m_axi", "s_axi")


def _w(v: int) -> str:
    s = f"{v:016x}"
    return f"0x{s[:8]}_{s[8:]}"


def _fresh(rng: SepSeededRng, used: set[int]) -> int:
    """A non-zero 64-bit draw that is not in ``used``; adds it to ``used``."""
    v = 0
    while v == 0 or v in used:
        v = rng.getrandbits(WORD_BITS)
    used.add(v)
    return v


def _hi(bus: str, name: str) -> bool:
    v = getattr(cocotb.top, f"{bus}_{name}").value
    return v.is_resolvable and int(v) == 1


async def _write_windows(stop: Event) -> dict:
    """Per-clock outstanding-write samples of the m_axi and s_axi TB ports, until ``stop``.

    A bus has a write outstanding from the first sample with AWVALID high up to
    and including the sample with BVALID and BREADY high. Returns, per bus, the
    first and last outstanding sample and the AW handshake samples, and the
    count and first of the samples where both buses have one outstanding."""
    clk = cocotb.top.clk_i
    wins = {bus: {"open": False, "first": None, "last": None, "aw_hs": []} for bus in BUSES}
    both, first_both, cyc = 0, None, 0
    while True:
        await RisingEdge(clk)
        if stop.is_set():
            return {"wins": wins, "both": both, "first_both": first_both}
        await ReadOnly()
        inside = 0
        for bus, w in wins.items():
            if _hi(bus, "awvalid"):
                w["open"] = True
                if _hi(bus, "awready"):
                    w["aw_hs"].append(cyc)
            if w["open"]:
                inside += 1
                if w["first"] is None:
                    w["first"] = cyc
                w["last"] = cyc
                if _hi(bus, "bvalid") and _hi(bus, "bready"):
                    w["open"] = False
        if inside == len(wins):
            both += 1
            if first_both is None:
                first_both = cyc
        cyc += 1


@pyuvm.test()
class sep_sram_inbound_burst_attr_test(sep_base_test):
    """Inbound INCR bursts with seeded attributes write and read SRAM exactly."""

    required_evidence = (
        "CHK-SRAM-IN-WRITE",
        "CHK-SRAM-IN-READ",
        "CHK-SRAM-IN-STRB",
        "CHK-SRAM-IN-XPATH",
        "CHK-SRAM-XMASTER",
        "CHK-SRAM-CONC-DATA",
    )

    async def run_scenario(self) -> None:
        cfg = SepSramInboundCfg(self.random_seed())
        self.cfg_sram = cfg
        self.logger.info("SRAM inbound burst config: %s", cfg.summary())
        for c in cfg.cases:
            self.logger.info("  %s", c.summary())

        await self.bring_up_no_cpu()

        filt = SepInboundFilter(self)
        await filt.disable_all()
        for entry, ns in ((0, True), (1, False)):
            rule = SepInboundFilterCfg(entry=entry, allow_addr=cfg.win_base)
            await filt.program_rule(
                rule,
                read_allowed=True,
                write_allowed=True,
                allow_burst=True,
                end_addr=cfg.win_end,
                allow_ns=ns,
            )
        self.logger.info(
            "inbound filter entries 0 (ns) and 1 (secure) allow SRAM 0x%08x..0x%08x "
            "r+w, bursts allowed, any source ID",
            cfg.win_base,
            cfg.win_end,
        )

        self.model = SepSramByteModel()
        self.tally = SepInboundAttrTally()
        self.n = {
            "stim": 0,
            "wr": 0,
            "rd_beats": 0,
            "rlast": 0,
            "strb": 0,
            "xpath": 0,
            "excl": 0,
        }
        self.excl_resps: set[int] = set()
        self.mismatch: dict[str, list[str]] = {}
        for c in cfg.cases:
            await self._case(c)
        assert not self.mismatch, " | ".join(
            f"{chk} FAIL: {len(msgs)} mismatch(es); first: {msgs[0]}"
            for chk, msgs in self.mismatch.items()
        )

        self.logger.info(
            "CTRL-SRAM-IN-STIM LOG: %d AW/AR handshakes on m_axi carried the drawn "
            "ID, address, AxLEN, AxSIZE, AxBURST, AxLOCK, AxCACHE, AxPROT, AxQOS, "
            "AxREGION and AxUSER; %s",
            self.n["stim"],
            self.tally.summary(),
        )
        self.logger.info(
            "CHK-SRAM-IN-WRITE PASS: %d inbound writes (%d bursts + %d overlays) "
            "answered OKAY with BID equal to AWID",
            self.n["wr"],
            len(cfg.cases),
            len(cfg.cases),
        )
        self.logger.info(
            "CHK-SRAM-IN-READ PASS: %d inbound burst reads (%d beats, %d exclusive, "
            "answered %s) answered OKAY/EXOKAY on every beat with RID equal to ARID, "
            "every beat equal to the model; RLAST seen on the last beat only in %d of "
            "%d bursts (%d R beats sampled on m_axi)",
            len(cfg.cases),
            self.n["rd_beats"],
            self.n["excl"],
            sorted(self.excl_resps),
            self.n["rlast"],
            len(cfg.cases),
            self.n["rd_beats"],
        )
        self.logger.info(
            "CHK-SRAM-IN-STRB PASS: %d partial-strobe overlay beats kept the "
            "unstrobed bytes and took the strobed ones",
            self.n["strb"],
        )
        self.logger.info(
            "CHK-SRAM-IN-XPATH PASS: %d CPU-LSU spot reads matched the inbound "
            "writes, and every inbound read returned the %d CPU-LSU-written words",
            self.n["xpath"],
            sum(len(c.pokes) for c in cfg.cases),
        )

        open_graded_window(TEST, self.logger)
        try:
            await self._xmaster(cfg)
            await self._attr_leg(cfg)
        finally:
            close_graded_window(self.logger)
        await self._conc_leg(cfg)

        for entry in (0, 1):
            await filt.disable_entry(entry)

    async def _ext(
        self, op: SepAxiOp, addr: int, axi_id: int, length: int = BEAT_BYTES, **kw
    ) -> SepAxiAccessSeq:
        """One inbound INCR access of 8-byte beats that tolerates any response."""
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = True
        else:
            kw["allow_unverified_write_resp"] = True
        seq = SepAxiAccessSeq(
            f"sram_in_attr_{op.value}",
            op=op,
            addr=addr,
            length=length,
            size=SIZE_8B,
            burst=BURST_INCR,
            axi_id=axi_id,
            **kw,
        )
        await self.start_ext_seq(seq)
        return seq

    async def _si_access(self, op: SepAxiOp, addr: int, axi_id: int, word: int = 0) -> int:
        """One 8-byte inbound access that must answer OKAY; returns the read word."""
        seq = SepAxiAccessSeq(
            f"sram_xm_si_{op.value}",
            op=op,
            addr=addr,
            wdata=word,
            length=BEAT_BYTES,
            size=SIZE_8B,
            burst=BURST_INCR,
            axi_id=axi_id,
        )
        await self.start_ext_seq(seq)
        assert seq.resp_code == RESP_OKAY, (
            f"SI {op.value} @0x{addr:08x} answered resp={seq.resp_code}, expected OKAY"
        )
        return seq.rdata & MASK64

    async def _dma_copy(self, src: int, dst: int, tag: str) -> str | None:
        """One 8-byte DMA copy; returns None when STATUS reached DONE, else the failure."""
        ops = self.dma
        await ops.clean_state()
        await ops.program_transfer(src=src, dst=dst, total=BEAT_BYTES, chunk=BEAT_BYTES)
        await ops.go(opcode=OP_COPY, initial=1)
        res = await ops.run_to_done(BEAT_BYTES, tag=f" {tag}")
        st = res.status
        line = f"{tag} copy 0x{src:08x}->0x{dst:08x} polls={res.polls} {st.fmt()}"
        if not st.done or st.error or st.aborted:
            msg = f"CTRL-MISSING SRAM-XMASTER-DMA: {line}"
            self.logger.error(msg)
            return msg
        self.logger.info("CTRL-SRAM-XMASTER-DMA seen: %s", line)
        return None

    async def _xmaster_leg(
        self, i: int, writer: int, reader: int, prev: int, value: int, sentinel: int, xm: dict
    ) -> str | None:
        """One (writer, reader) leg at the shared word; returns None when CHK-SRAM-XMASTER passed."""
        word, src, dst, si_id = xm["word"], xm["src"], xm["dst"], xm["si_id"]
        tag = f"leg={i} pair=({MASTER_NAME[writer]},{MASTER_NAME[reader]})"
        pre = {"word": (word, prev, await self._lsu_read(word))}
        if reader == DMA:
            await self._lsu_write(dst, sentinel)
            pre["dst"] = (dst, sentinel, await self._lsu_read(dst))
        pre_line = f"{tag} " + " ".join(
            f"{k}@0x{a:08x}={_w(g)} expect={_w(e)}" for k, (a, e, g) in pre.items()
        )
        if any(g != e for _a, e, g in pre.values()):
            msg = f"CTRL-MISSING SRAM-XMASTER-PRE: {pre_line}"
            self.logger.error(msg)
            return msg
        self.logger.info("CTRL-SRAM-XMASTER-PRE seen: %s", pre_line)

        if writer == SI:
            await self._si_access(SepAxiOp.WRITE, word, si_id, value)
        elif writer == LSU:
            await self._lsu_write(word, value)
        else:
            await self._lsu_write(src, value)
            fail = await self._dma_copy(src, word, f"{tag} write")
            if fail:
                return fail

        if reader == SI:
            got = await self._si_access(SepAxiOp.READ, word, si_id)
        elif reader == LSU:
            got = await self._lsu_read(word)
        else:
            fail = await self._dma_copy(word, dst, f"{tag} read")
            if fail:
                return fail
            got = await self._lsu_read(dst)

        line = f"{tag} @0x{word:08x} written={_w(value)} read={_w(got)} previous={_w(prev)}"
        if got != value:
            msg = f"CHK-SRAM-XMASTER FAIL: {line} xor={_w(got ^ value)}"
            self.logger.error(msg)
            return msg
        self.logger.info("CHK-SRAM-XMASTER PASS: %s", line)
        return None

    async def _xmaster(self, cfg: SepSramInboundCfg) -> None:
        """Every ordered (writer, reader) pair of SI, CPU-LSU and DMA at one SRAM word."""
        rng = SepSeededRng(self.random_seed() ^ _XMASTER_SALT)
        word, src, dst = rng.sample(range(cfg.win_base, cfg.win_end + 1, BEAT_BYTES), 3)
        xm = {"word": word, "src": src, "dst": dst, "si_id": rng.randrange(1, 16)}
        order = list(XMASTER_PAIRS)
        rng.shuffle(order)
        used: set[int] = set()
        init = _fresh(rng, used)
        legs = [(w, r, _fresh(rng, used), _fresh(rng, used)) for w, r in order]
        self.logger.info(
            "DRAW xmaster word=0x%08x dma_src=0x%08x dma_dst=0x%08x si_id=%d init=%s order=%s",
            word,
            src,
            dst,
            xm["si_id"],
            _w(init),
            ",".join(f"{MASTER_NAME[w]}->{MASTER_NAME[r]}" for w, r, _v, _s in legs),
        )

        self.dma = SepDmaOps(self)
        await self.dma.program_range(cfg.win_base, cfg.win_end)
        await self.dma.set_asid(DMA_ASID, DMA_ASID)
        await self._lsu_write(word, init)

        fails: list[str] = []
        prev = init
        clk = cocotb.top.clk_i
        for i, (w, r, value, sentinel) in enumerate(legs):
            fail = await self._xmaster_leg(i, w, r, prev, value, sentinel, xm)
            if fail is not None:
                fails.append(fail)
                # The next leg reads back the word as it stands.
                prev = await self._lsu_read(word)
                continue
            prev = value
            await RisingEdge(clk)
            set_sram_access_pass(2, w * 4 + r, self.logger)
            await ClockCycles(clk, 2)
            set_sram_access_pass(0, log=self.logger)
        if fails:
            raise AssertionError(
                f"CHK-SRAM-XMASTER FAIL: {len(fails)} of {len(legs)} legs: " + " | ".join(fails)
            )
        self.logger.info(
            "CHK-SRAM-XMASTER PASS: pairs=%d order=%s @0x%08x",
            len(legs),
            ",".join(f"{MASTER_NAME[w]}->{MASTER_NAME[r]}" for w, r, _v, _s in legs),
            word,
        )

    async def _attr_leg(self, cfg: SepSramInboundCfg) -> None:
        """AWLOCK 1 after an exclusive read, on an SRAM word."""
        rng = SepSeededRng(self.random_seed() ^ _ATTR_SALT)
        word = rng.choice(range(cfg.win_base, cfg.win_end + 1, BEAT_BYTES))
        axi_id = rng.randrange(1, 16)
        data = rng.getrandbits(64)
        before = await self._lsu_read(word)

        task = cocotb.start_soon(capture_ax("ar"))
        rd = await self._ext(SepAxiOp.READ, word, axi_id, attrs={"lock": 1})
        ar_hs = take_handshake(task)
        task = cocotb.start_soon(capture_ax("aw"))
        wr = await self._ext(SepAxiOp.WRITE, word, axi_id, wdata=data, attrs={"lock": 1})
        aw_hs = take_handshake(task)
        after = await self._lsu_read(word)

        want = {"lock": 1, "id": axi_id, "addr": word}
        seen = {
            ch: None if hs is None else {k: hs[k] for k in want}
            for ch, hs in (("ar", ar_hs), ("aw", aw_hs))
        }
        line = f"ar_seen={seen['ar']} aw_seen={seen['aw']} expect={want}"
        assert seen["ar"] == want and seen["aw"] == want, f"CTRL-SRAM-IN-ATTR FAIL: {line}"
        self.logger.info("CTRL-SRAM-IN-ATTR LOG: %s", line)
        set_open_value_leg_pass("sram_in_excl_write", self.logger)
        await ClockCycles(cocotb.top.clk_i, 2)
        set_open_value_leg_pass(None, self.logger)
        self.logger.info(
            "OBS-SRAM-IN-EXCL-WR addr=0x%08x id=0x%x excl_read_resp=%s rdata=%s "
            "write_resp=%s bid=%s wdata=%s before=%s after=%s",
            word,
            axi_id,
            resp_name(rd.resp_code),
            _w(rd.rdata & MASK64),
            resp_name(wr.resp_code),
            wr.resp_id,
            _w(data),
            _w(before),
            _w(after),
        )

    async def _lsu(self, op: SepAxiOp, addr: int, word: int = 0) -> SepAxiAccessSeq:
        """One 8-byte CPU-LSU access that tolerates any response."""
        tolerate = (
            "allow_ungraded_read_resp" if op is SepAxiOp.READ else "allow_unverified_write_resp"
        )
        seq = SepAxiAccessSeq(
            f"sram_conc_lsu_{op.value}",
            op=op,
            addr=addr,
            wdata=word,
            length=BEAT_BYTES,
            size=SIZE_8B,
            **{tolerate: True},
        )
        await self.start_seq(seq)
        return seq

    async def _conc_leg(self, cfg: SepSramInboundCfg) -> None:
        """An inbound burst write and CPU-LSU word writes at once, read back by both masters."""
        rng = SepSeededRng(self.random_seed() ^ _CONC_SALT)
        beats = rng.randrange(CONC_MIN_BEATS, MAX_BEATS + 1)
        page = cfg.win_base + rng.randrange(WINDOW_PAGES) * PAGE_BYTES
        start = page + rng.randrange(0, PAGE_BYTES // BEAT_BYTES - beats + 1) * BEAT_BYTES
        span = range(start, start + beats * BEAT_BYTES, BEAT_BYTES)
        used: set[int] = set()
        payload = b"".join(_fresh(rng, used).to_bytes(BEAT_BYTES, "little") for _ in span)
        si_id = rng.randrange(1, 16)
        free = [a for a in range(cfg.win_base, cfg.win_end + 1, BEAT_BYTES) if a not in span]
        lsu = {a: _fresh(rng, used) for a in rng.sample(free, CONC_LSU_WRITES)}
        self.logger.info(
            "DRAW conc burst=0x%08x beats=%d si_id=%d lsu_words=%s",
            start,
            beats,
            si_id,
            ",".join(f"0x{a:08x}" for a in lsu),
        )

        async def lsu_writes() -> list[SepAxiAccessSeq]:
            return [await self._lsu(SepAxiOp.WRITE, a, v) for a, v in lsu.items()]

        stop = Event()
        tap = cocotb.start_soon(_write_windows(stop))
        si_task = cocotb.start_soon(
            self._ext(
                SepAxiOp.WRITE,
                start,
                si_id,
                length=len(payload),
                wdata=int.from_bytes(payload, "little"),
            )
        )
        lsu_task = cocotb.start_soon(lsu_writes())
        si_wr = await si_task
        lsu_wr = await lsu_task
        stop.set()
        win = await tap
        self.model.write(start, payload)
        for a, v in lsu.items():
            self.model.write_word(a, v)

        m, s = (win["wins"][bus] for bus in BUSES)
        line = (
            f"beats={beats} overlap_clocks={win['both']} first_overlap={win['first_both']} "
            f"m_axi={m['first']}..{m['last']} aw_hs={m['aw_hs']} "
            f"s_axi={s['first']}..{s['last']} aw_hs={s['aw_hs']}"
        )
        if not win["both"]:
            msg = f"CTRL-MISSING SRAM-CONC-OVERLAP: {line}"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info("CTRL-SRAM-CONC-OVERLAP PASS: %s", line)

        bad: list[str] = []
        words = 0

        def grade(what: str, seq: SepAxiAccessSeq, addrs) -> None:
            nonlocal words
            if seq.resp_code != RESP_OKAY:
                bad.append(f"{what} answered {resp_name(seq.resp_code)}, expected OKAY")
            for i, addr in enumerate(addrs):
                got = (seq.rdata >> (WORD_BITS * i)) & MASK64
                exp = self.model.word(addr)
                words += 1
                if got != exp:
                    bad.append(
                        f"{what} word @0x{addr:08x} = {_w(got)}, expected {_w(exp)}; "
                        f"xor={_w(got ^ exp)}"
                    )

        grade(f"inbound burst write @0x{start:08x}", si_wr, ())
        for a, seq in zip(lsu, lsu_wr):
            grade(f"CPU-LSU write @0x{a:08x}", seq, ())
        for a in (*span, *lsu):
            grade(f"CPU-LSU read @0x{a:08x}", await self._lsu(SepAxiOp.READ, a), (a,))
        rd = await self._ext(SepAxiOp.READ, start, si_id, length=len(payload))
        grade(f"inbound burst read @0x{start:08x}", rd, span)
        for a in lsu:
            grade(f"inbound read @0x{a:08x}", await self._ext(SepAxiOp.READ, a, si_id), (a,))
        first = " | ".join(bad[:4])
        assert not bad, f"CHK-SRAM-CONC-DATA FAIL: {len(bad)} failure(s); first: {first}"
        self.logger.info(
            "CHK-SRAM-CONC-DATA PASS: 1 inbound burst write of %d beats and %d CPU-LSU "
            "writes answered OKAY; %d CPU-LSU reads, 1 inbound burst read and %d inbound "
            "reads answered OKAY, and all %d words read equal the model",
            beats,
            len(lsu),
            beats + len(lsu),
            len(lsu),
            words,
        )

    def _attrs(
        self, *, write: bool, beats: int, lock_ok: bool, lock: int | None = None
    ) -> SepInboundAttrs:
        a = SepInboundAttrs(self.cfg_sram.rng, write=write, beats=beats, lock_ok=lock_ok, lock=lock)
        self.tally.add(a)
        return a

    def _grade_stim(self, hs, a: SepInboundAttrs, *, addr: int, beats: int, what: str) -> None:
        assert hs is not None, f"CTRL-SRAM-IN-STIM FAIL: no {what} handshake seen on m_axi"
        want = {
            "id": a.axi_id,
            "addr": addr,
            "len": beats - 1,
            "size": SIZE_8B,
            "burst": BURST_INCR,
            "lock": a.attrs["lock"],
            "cache": a.attrs["cache"],
            "prot": a.prot,
            "qos": a.attrs["qos"],
            "region": a.attrs["region"],
            "user": a.user,
        }
        bad = {k: (hs[k], v) for k, v in want.items() if hs[k] != v}
        assert not bad, (
            f"CTRL-SRAM-IN-STIM FAIL: {what} handshake differs from the draw "
            f"(field: (port, drawn)) {bad}"
        )
        self.n["stim"] += 1

    async def _ext_write(self, addr: int, data: bytes, beats: int, what: str) -> None:
        a = self._attrs(write=True, beats=beats, lock_ok=False)
        seq = SepAxiAccessSeq(
            f"sram_in_{what}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=int.from_bytes(data, "little"),
            length=len(data),
            size=SIZE_8B,
            burst=BURST_INCR,
            allow_unverified_write_resp=True,
            **a.kwargs(),
        )
        task = cocotb.start_soon(capture_ax("aw"))
        w_task = cocotb.start_soon(capture_wuser())
        await self.start_ext_seq(seq)
        self._grade_stim(
            take_handshake(task), a, addr=addr, beats=beats, what=f"{what} @0x{addr:08x}"
        )
        wusers = take_handshake(w_task)
        assert wusers == [a.attrs["wuser"]] * beats, (
            f"CTRL-SRAM-IN-STIM FAIL: {what} @0x{addr:08x} W beats wuser={wusers} "
            f"expected {beats} x 0x{a.attrs['wuser']:03x}"
        )
        assert seq.resp_code == RESP_OKAY and seq.resp_id == a.axi_id, (
            f"CHK-SRAM-IN-WRITE FAIL: {what} @0x{addr:08x} {len(data)} B ({a}) answered "
            f"resp={seq.resp_code} BID={seq.resp_id}, expected OKAY and BID 0x{a.axi_id:02x}"
        )
        self.n["wr"] += 1
        self.model.write(addr, data)

    async def _lsu_write(self, addr: int, word: int) -> None:
        seq = SepAxiAccessSeq(
            "sram_in_lsu_poke",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=word,
            length=BEAT_BYTES,
            size=SIZE_8B,
        )
        await self.start_seq(seq)
        assert seq.resp_code == RESP_OKAY, (
            f"CPU-LSU write @0x{addr:08x} answered resp={seq.resp_code}, expected OKAY"
        )
        self.model.write_word(addr, word)

    async def _lsu_read(self, addr: int) -> int:
        seq = SepAxiAccessSeq(
            "sram_in_lsu_spot",
            op=SepAxiOp.READ,
            addr=addr,
            length=BEAT_BYTES,
            size=SIZE_8B,
        )
        await self.start_seq(seq)
        assert seq.resp_code == RESP_OKAY, (
            f"CPU-LSU read @0x{addr:08x} answered resp={seq.resp_code}, expected OKAY"
        )
        return seq.rdata & MASK64

    async def _case(self, c: SepSramInboundCase) -> None:
        # Burst write of the case's words.
        payload = c.payload().to_bytes(c.nbytes, "little")
        await self._ext_write(c.start, payload, c.beats, f"case{c.idx}_burst")
        # Unaligned overlay: partial strobes on its first and last beats.
        before = {b: self.model.word(b) for b in c.ov_beats()}
        await self._ext_write(c.ov_addr, c.ov_data, len(c.ov_beats()), f"case{c.idx}_overlay")
        # CPU-LSU words into the same span.
        for addr, word in c.pokes:
            await self._lsu_write(addr, word)
        poked = {addr for addr, _ in c.pokes}

        # Burst read of the whole span.
        a = self._attrs(
            write=False,
            beats=c.beats,
            lock_ok=exclusive_legal(c.start, c.nbytes, c.beats),
            lock=c.read_lock,
        )
        seq = SepAxiAccessSeq(
            f"sram_in_case{c.idx}_read",
            op=SepAxiOp.READ,
            addr=c.start,
            length=c.nbytes,
            size=SIZE_8B,
            burst=BURST_INCR,
            allow_ungraded_read_resp=True,
            **a.kwargs(),
        )
        task = cocotb.start_soon(capture_ax("ar"))
        r_task = cocotb.start_soon(capture_r_beats(a.axi_id))
        await self.start_ext_seq(seq)
        self._grade_stim(
            take_handshake(task), a, addr=c.start, beats=c.beats, what=f"case{c.idx} read"
        )
        if not r_task.done():
            # The tap samples the RLAST beat on the edge the read completes on.
            await RisingEdge(cocotb.top.clk_i)
        r_beats = take_handshake(r_task)
        flags = None if r_beats is None else [last for _resp, last in r_beats]
        assert flags is not None and flags == [0] * (c.beats - 1) + [1], (
            f"CHK-SRAM-IN-READ FAIL: case {c.idx} read of {c.beats} beats (RID "
            f"0x{a.axi_id:02x}): RLAST per beat on m_axi = {flags}, expected it on "
            f"beat {c.beats} only"
        )
        self.n["rlast"] += 1
        resps = [resp for resp, _last in r_beats]
        bad_beats = [(i, r) for i, r in enumerate(resps) if r not in a.ok_resps()]
        assert not bad_beats, (
            f"CHK-SRAM-IN-READ FAIL: case {c.idx} read ({a}) of {c.beats} beats: RRESP "
            f"(beat, code) on m_axi {bad_beats[:4]}, expected only {a.ok_resps()} on every beat"
        )
        assert seq.resp_id == a.axi_id, (
            f"CHK-SRAM-IN-READ FAIL: case {c.idx} read issued ARID 0x{a.axi_id:02x} and "
            f"the response carried RID {seq.resp_id}"
        )
        if a.locked:
            self.n["excl"] += 1
            self.excl_resps.update(resps)
        got = [(seq.rdata >> (WORD_BITS * i)) & MASK64 for i in range(c.beats)]
        beat_addr = [c.start + i * BEAT_BYTES for i in range(c.beats)]

        # Strobe overlay, graded on its first and last beat before the full compare.
        bad = 0
        ov_end = c.ov_addr + len(c.ov_data)
        for b in {c.ov_beats()[0], c.ov_beats()[-1]}:
            lanes = [b + i for i in range(BEAT_BYTES)]
            if all(c.ov_addr <= x < ov_end for x in lanes):
                continue
            exp = self.model.word(b)
            g = got[(b - c.start) // BEAT_BYTES]
            if g != exp:
                bad += self._miss(
                    "CHK-SRAM-IN-STRB",
                    f"case {c.idx} overlay beat @0x{b:08x} read {_w(g)}, expected "
                    f"{_w(exp)} (burst data {_w(before[b])}, overlay "
                    f"0x{c.ov_addr:08x}+{len(c.ov_data)} B); xor={_w(g ^ exp)}",
                )
            self.n["strb"] += 1

        for i, (addr, g) in enumerate(zip(beat_addr, got)):
            exp = self.model.word(addr)
            src = "CPU-LSU word" if addr in poked else "inbound data"
            chk = "CHK-SRAM-IN-XPATH" if addr in poked else "CHK-SRAM-IN-READ"
            if g != exp:
                bad += self._miss(
                    chk,
                    f"case {c.idx} read beat {i} @0x{addr:08x} = {_w(g)}, expected "
                    f"{_w(exp)} ({src}); xor={_w(g ^ exp)}",
                )
        self.n["rd_beats"] += c.beats

        # CPU-LSU spot reads of what the inbound master wrote.
        for addr in c.spots:
            g = await self._lsu_read(addr)
            exp = self.model.word(addr)
            if g != exp:
                bad += self._miss(
                    "CHK-SRAM-IN-XPATH",
                    f"case {c.idx} CPU-LSU read @0x{addr:08x} = {_w(g)}, expected "
                    f"{_w(exp)}; xor={_w(g ^ exp)}",
                )
            self.n["xpath"] += 1
        self.logger.info(
            "case %d: %d-beat burst + overlay + %d CPU-LSU words: %d data mismatch(es) (read %s)",
            c.idx,
            c.beats,
            len(c.pokes),
            bad,
            a,
        )

    def _miss(self, chk: str, msg: str) -> int:
        """Record one data mismatch against ``chk``; the run fails after the
        last case with every checker that recorded one."""
        self.mismatch.setdefault(chk, []).append(msg)
        return 1
