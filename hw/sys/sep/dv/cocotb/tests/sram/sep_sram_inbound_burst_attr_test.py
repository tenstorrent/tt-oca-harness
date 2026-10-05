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
exclusive-access rules. AWLOCK stays 0: an exclusive write that a slave
refuses leaves memory unchanged, so its data result is not defined.

CHK-SRAM-IN-STIM: each AW / AR handshake on the m_axi port carries the drawn
ID, address, AxLEN, AxSIZE, AxBURST, AxLOCK, AxCACHE, AxPROT, AxQOS, AxREGION
and AxUSER, so the verdicts below are about the attributes the log names.

CHK-SRAM-IN-WRITE: every inbound write answers OKAY with BID equal to AWID.

CHK-SRAM-IN-READ: every beat of the burst read answers OKAY (EXOKAY allowed
on an exclusive read), RLAST falls on the last beat and on no other (sampled
on the m_axi R channel), RID equals ARID, and every beat equals the byte model.

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

Run mode: no_cpu (CPU-LSU master) with the external SMN master, and
+skip_fuse_sense with no shadow preload. LC_STATE is then INVALID, FEAT_CTRL is
zero and the inbound filter is in the m_axi path, so the test programs the
filter window. The window, lengths, starts, data, overlay, CPU-LSU words and
every inbound request attribute come from SepSeededRng.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq, take_handshake
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
    SIZE_8B,
    WORD_BITS,
    SepSramByteModel,
    SepSramInboundCase,
    SepSramInboundCfg,
    capture_ax,
    capture_rlast,
)


def _w(v: int) -> str:
    s = f"{v:016x}"
    return f"0x{s[:8]}_{s[8:]}"


@pyuvm.test()
class sep_sram_inbound_burst_attr_test(sep_base_test):
    """Inbound INCR bursts with seeded attributes write and read SRAM exactly."""

    required_evidence = (
        "CHK-SRAM-IN-STIM",
        "CHK-SRAM-IN-WRITE",
        "CHK-SRAM-IN-READ",
        "CHK-SRAM-IN-STRB",
        "CHK-SRAM-IN-XPATH",
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
            "CHK-SRAM-IN-STIM PASS: %d AW/AR handshakes on m_axi carried the drawn "
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

        for entry in (0, 1):
            await filt.disable_entry(entry)

    def _attrs(
        self, *, write: bool, beats: int, lock_ok: bool, lock: int | None = None
    ) -> SepInboundAttrs:
        a = SepInboundAttrs(self.cfg_sram.rng, write=write, beats=beats, lock_ok=lock_ok, lock=lock)
        self.tally.add(a)
        return a

    def _grade_stim(self, hs, a: SepInboundAttrs, *, addr: int, beats: int, what: str) -> None:
        assert hs is not None, f"CHK-SRAM-IN-STIM FAIL: no {what} handshake seen on m_axi"
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
            f"CHK-SRAM-IN-STIM FAIL: {what} handshake differs from the draw "
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
        await self.start_ext_seq(seq)
        self._grade_stim(
            take_handshake(task), a, addr=addr, beats=beats, what=f"{what} @0x{addr:08x}"
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
        r_task = cocotb.start_soon(capture_rlast(a.axi_id))
        await self.start_ext_seq(seq)
        self._grade_stim(
            take_handshake(task), a, addr=c.start, beats=c.beats, what=f"case{c.idx} read"
        )
        if not r_task.done():
            # The tap samples the RLAST beat on the edge the read completes on.
            await RisingEdge(cocotb.top.clk_i)
        flags = take_handshake(r_task)
        assert flags is not None and flags == [0] * (c.beats - 1) + [1], (
            f"CHK-SRAM-IN-READ FAIL: case {c.idx} read of {c.beats} beats (RID "
            f"0x{a.axi_id:02x}): RLAST per beat on m_axi = {flags}, expected it on "
            f"beat {c.beats} only"
        )
        self.n["rlast"] += 1
        # resp_code folds the RRESP beats into one worst code, so grade each
        # beat from resp_list.
        resps = list(seq.resp_list)
        assert resps and all(r in a.ok_resps() for r in resps), (
            f"CHK-SRAM-IN-READ FAIL: case {c.idx} read ({a}) of {c.beats} beats answered "
            f"{sorted(set(resps))}, expected only {a.ok_resps()}"
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
