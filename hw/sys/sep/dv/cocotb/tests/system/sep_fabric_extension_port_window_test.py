# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The AXI Extension port serves its window for the LSU and the System Interface; the eFuse shim window stays off it.

Contract (``hw/sys/sep/doc/fabric.adoc``, "Top Level AXI4" and "Fabric
Topology", local fabric; ``hw/sys/sep/doc/memory_map.adoc``, "External Window
Reference Model"; ``hw/sys/sep/doc/port_table.adoc``):

* The extension port serves ``0x2000_0000`` to ``0x3FFF_FFFF`` except the first
  ``EFUSE_SHIM_SIZE`` bytes (default ``0x4``), for the LSU and for the System
  Interface (SI). The shim window goes to the eFuse controller, not to the port.
* The SI may issue bursts.
* A request that leaves on the port gets the response that the port returns. The
  port table ties an unused port to DECERR, and the bench port answers DECERR.
* A burst that the inbound filter refuses answers DECERR and never reaches the
  local crossbar (``hw/ip/axi_filter/doc/index.adoc``, "Blocked Transactions").

Checks:

* CHK-EXT-REACH: each SI single beat shows one PR-XEXT handshake with the issued
  address, and the SI receives the port DECERR. PR-XEXT is the anchor, because
  the fabric also answers DECERR for its own errors.
* CHK-EXT-PORT: each LSU and SI single beat leaves on PR-EXT once, with the
  issued address, AxSIZE, AxLEN 0, strobe and write data, and the port returns
  exactly one reply beat (PR-EXT B or R), DECERR, before the initiator's
  response. So the DECERR the initiator receives is the port's reply.
* CHK-EXT-SHIM: the first and last byte of the shim window give no PR-EXT
  capture for either initiator and direction. Control: the first word above the
  shim gives a capture in the same leaf. The shim responses are logged only.
* CHK-EXT-BURST: an SI INCR write burst (AxLEN 3) and read burst (AxLEN 7)
  through an entry with ``allow_burst`` 1 reach PR-XEXT and PR-EXT with the
  issued AxLEN, AxSIZE and write beats; with the entry disabled each answers
  DECERR with PR-XEXT silent.

Run mode: no_cpu, ``lsu_stub_all_live``, real PROD fuse sense (the inbound filter
is active). RAND-REP: the seed draws the middle word, the AxSIZE of each single
beat, the write data and the burst page offsets; the initiators, directions and
address classes are fixed loops.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_common import RESP_DECERR, RESP_NAME
from env.sep_fabric_tap import start_taps, stop_taps
from env.sep_fcov_gate import close_graded_window, fcov_present, open_graded_window
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LC_PROD, LCC_FEAT_CTRL, feat_ctrl_expected
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq, capture_resp_handshake, take_handshake
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank

TEST = "sep_fabric_extension_port_window_test"

AXI_BURST_INCR = 1

EXT_BASE = sym("SEP_EXTERNAL_REG_MAP_BASE_ADDR")
EXT_END = EXT_BASE + sym("SEP_EXTERNAL_REG_MAP_SIZE") - 1
EFUSE_SHIM_SIZE = sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_SIZE")
SHIM_LAST = EXT_BASE + EFUSE_SHIM_SIZE - 1
FIRST_ABOVE_SHIM = EXT_BASE + EFUSE_SHIM_SIZE
LAST_WORD = EXT_END + 1 - 8
MID_LO, MID_HI = EXT_BASE + 8, EXT_END - 8
# Reset bytes of the shim register (EFUSE_BANK_INIT_TIME): byte 0 and byte 3.
_SHIM_RESET = sym("EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME_REG_DEFAULT")
SHIM_RESET_BYTE = {EXT_BASE: _SHIM_RESET & 0xFF, SHIM_LAST: (_SHIM_RESET >> 24) & 0xFF}
BURST_PAGE = EXT_BASE + 0x1000
PAGE = 0x1000
# SI requests are non-secure data accesses; the entry takes allow_ns = AxPROT[1].
SI_PROT = 0b010
BUS_BYTES = 8

# Pinned PROD image: DBG_1 bit 0 clear in both disable vectors, SEC_DIS 0.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0E
_SYS_DIS = 0x00FF_00FF_00FF_00FE
_MAX_SENSE_CYCLES = 20_000


class _Csr(SepAxiRegDriver):
    _DRIVER_TAG = "EXTWIN"


def _strb(addr: int, size: int) -> int:
    n = 1 << size
    return ((1 << n) - 1) << (addr % BUS_BYTES)


def _lane_data(addr: int, size: int, data: int) -> int:
    """The issued write data placed on its byte lanes of the 64-bit bus."""
    return (data & ((1 << (8 << size)) - 1)) << (8 * (addr % BUS_BYTES))


@pyuvm.test()
class sep_fabric_extension_port_window_test(sep_base_test):
    """LSU and SI reach the extension window; the shim window stays off the port."""

    required_evidence = ("CHK-EXT-REACH", "CHK-EXT-PORT", "CHK-EXT-SHIM", "CHK-EXT-BURST")

    async def _access(
        self,
        init: str,
        op: SepAxiOp,
        addr: int,
        size: int,
        *,
        data: int = 0,
        nbeats: int = 1,
        expect_decerr: bool = True,
        ungraded: bool = False,
    ) -> SepAxiAccessSeq:
        kw: dict = {}
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = ungraded
        else:
            kw["allow_unverified_write_resp"] = True
        if nbeats > 1:
            kw["burst"] = AXI_BURST_INCR
        seq = SepAxiAccessSeq(
            f"extwin_{init.lower()}_{op.value}",
            op=op,
            addr=addr,
            wdata=data,
            length=(1 << size) * nbeats,
            size=size,
            expect_error=expect_decerr and not ungraded,
            prot=SI_PROT if init == "SI" else None,
            **kw,
        )
        if init == "SI":
            await self.start_ext_seq(seq)
            return seq
        # The s_axi monitor fails an unannounced DECERR beat; a probe that
        # expects or logs one announces it and returns an unused credit.
        self.env.axi_monitor.arm_expected_decerr(1)
        await self.start_seq(seq)
        if seq.resp_code != RESP_DECERR:
            self.env.axi_monitor.release_expected_decerr(1)
        return seq

    async def _timed(self, init: str, op: SepAxiOp, *args, **kw) -> tuple[SepAxiAccessSeq, int]:
        """One access and the time its initiator port accepted the B or the last R beat."""
        ch = "b" if op is SepAxiOp.WRITE else "r"
        prefix = "m_axi" if init == "SI" else "s_axi"
        hs = cocotb.start_soon(capture_resp_handshake(ch, prefix=prefix))
        seq = await self._access(init, op, *args, **kw)
        t = take_handshake(hs)
        assert t is not None, (
            f"CHK-EXT-PORT FAIL: init={init} dir={ch}: no response handshake seen on {prefix}"
        )
        return seq, t

    def _mark(self) -> dict[str, int]:
        return {n: t.mark() for n, t in self.taps.items()}

    def _since(self, m: dict[str, int], tap: str, ch: str | None = None):
        return self.taps[tap].since(m[tap], ch)

    async def _single(
        self, init: str, op: SepAxiOp, cls: str, addr: int, size: int, data: int
    ) -> dict:
        m = self._mark()
        seq, t_init = await self._timed(init, op, addr, size, data=data)
        ch = "aw" if op is SepAxiOp.WRITE else "ar"
        return {
            "init": init,
            "op": op,
            "cls": cls,
            "addr": addr,
            "size": size,
            "data": data,
            "resp": seq.resp_code,
            "resp_list": seq.resp_list,
            "xext": [b.addr for b in self._since(m, "PR-XEXT", ch)],
            "ext": self._since(m, "PR-EXT", ch),
            "ext_w": self._since(m, "PR-EXT", "w"),
            "ext_all": self._since(m, "PR-EXT"),
            "reply": self._since(m, "PR-EXT-RSP", "b" if op is SepAxiOp.WRITE else "r"),
            "t_init": t_init,
        }

    def _check_port(self, c: dict) -> None:
        d = "W" if c["op"] is SepAxiOp.WRITE else "R"
        tag = f"init={c['init']} dir={d} class={c['cls']} issued=0x{c['addr']:08x}"
        assert c["resp"] == RESP_DECERR, (
            f"CHK-EXT-PORT FAIL: {tag} init_resp={RESP_NAME.get(c['resp'], c['resp'])}, expected "
            "DECERR, the response of the bench port"
        )
        assert len(c["ext"]) == 1, (
            f"CHK-EXT-PORT FAIL: {tag} PR-EXT {d} captures={len(c['ext'])}, expected 1: "
            + "; ".join(b.fmt() for b in c["ext_all"])
        )
        b = c["ext"][0]
        assert not b.has_unknown(), f"CHK-EXT-PORT FAIL: {tag} X/Z on PR-EXT: {b.fmt()}"
        assert b.addr == c["addr"] and b.size == c["size"] and b.len == 0, (
            f"CHK-EXT-PORT FAIL: {tag} PR-EXT {b.fmt()}; expected addr=0x{c['addr']:x} "
            f"size={c['size']} len=0"
        )
        # The DECERR the initiator receives is the port's reply: exactly one
        # reply beat on the port, DECERR, before the initiator's response.
        rep = c["reply"]
        assert len(rep) == 1, (
            f"CHK-EXT-PORT FAIL: {tag} PR-EXT reply beats={len(rep)}, expected 1: "
            + "; ".join(r.fmt() for r in rep)
        )
        r = rep[0]
        assert r.resp == RESP_DECERR and r.t_ps < c["t_init"], (
            f"CHK-EXT-PORT FAIL: {tag} port_resp={RESP_NAME.get(r.resp, 'X')} "
            f"t_port={r.t_ps}ps t_init={c['t_init']}ps; expected a DECERR port reply "
            "before the initiator response"
        )
        strb = _strb(c["addr"], c["size"])
        data_ok = "na"
        seen_strb = "na"
        if c["op"] is SepAxiOp.WRITE:
            assert len(c["ext_w"]) == 1, (
                f"CHK-EXT-PORT FAIL: {tag} PR-EXT W beats={len(c['ext_w'])}, expected 1"
            )
            w = c["ext_w"][0]
            assert not w.has_unknown(), f"CHK-EXT-PORT FAIL: {tag} X/Z on PR-EXT W: {w.fmt()}"
            lanes = 0
            for i in range(BUS_BYTES):
                if (strb >> i) & 1:
                    lanes |= 0xFF << (8 * i)
            want = _lane_data(c["addr"], c["size"], c["data"])
            ok = w.strb == strb and (w.data & lanes) == want and w.last == 1
            assert ok, (
                f"CHK-EXT-PORT FAIL: {tag} PR-EXT W strb=0x{w.strb:02x} data=0x{w.data:016x} "
                f"last={w.last}; expected strb=0x{strb:02x} data_on_lanes=0x{want:016x} last=1"
            )
            data_ok = "1"
            seen_strb = f"0x{w.strb:02x}"
        self.logger.info(
            "CHK-EXT-PORT PASS: init=%s dir=%s issued=0x%08X seen=0x%08X size=%d len=0 strb=%s "
            "data_ok=%s port_resp=DECERR t_port=%dps t_init=%dps init_resp=DECERR",
            c["init"],
            d,
            c["addr"],
            b.addr,
            b.size,
            seen_strb,
            data_ok,
            r.t_ps,
            c["t_init"],
        )

    def _check_reach(self, c: dict) -> None:
        d = "W" if c["op"] is SepAxiOp.WRITE else "R"
        tag = f"dir={d} class={c['cls']} issued=0x{c['addr']:08x}"
        assert c["xext"] == [c["addr"]], (
            f"CHK-EXT-REACH FAIL: {tag} PR-XEXT {d} handshakes "
            f"{[('X' if a is None else hex(a)) for a in c['xext']]}, expected exactly [0x{c['addr']:x}]"
        )
        assert c["resp"] == RESP_DECERR, (
            f"CHK-EXT-REACH FAIL: {tag} init_resp={RESP_NAME.get(c['resp'], c['resp'])}, expected "
            "DECERR, the response of the bench port"
        )
        self.logger.info(
            "CHK-EXT-REACH PASS: dir=%s class=%s issued=0x%08X xbar_seen=0x%08X init_resp=DECERR",
            d,
            c["cls"],
            c["addr"],
            c["xext"][0],
        )

    async def _bring_up(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        golden = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        feat = await self.csr._rd(LCC_FEAT_CTRL) | (await self.csr._rd(LCC_FEAT_CTRL + 4) << 32)
        self.logger.info(
            "CTL-EXT-FILTER-ACTIVE LOG: feat_ctrl=0x%016x golden=0x%016x sep_dbg=%d fcov=%d",
            feat,
            golden,
            feat & 1,
            int(fcov_present()),
        )
        assert feat == golden and (golden & 1) == 0, (
            f"CTL-EXT-FILTER-ACTIVE FAIL: feat_ctrl=0x{feat:016x} golden=0x{golden:016x}; "
            "the bring-up does not leave the inbound filter active"
        )

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        close_graded_window()
        self.csr = _Csr(self)
        await self._bring_up()
        self.inf = SepFilterBank(self, "in")
        self.taps = start_taps("PR-EXT", "PR-EXT-RSP", "PR-XEXT")

        # Step 2: inbound entry 0 over the whole window, bursts allowed.
        await self.inf.program(
            0,
            FilterEntry(
                start=EXT_BASE,
                end=EXT_END,
                enabled=True,
                read_allowed=True,
                write_allowed=True,
                allow_ns=bool((SI_PROT >> 1) & 1),
                allow_burst=True,
                src_id=0,
            ),
        )

        # Step 3: draws. Every single-beat address is aligned to its AxSIZE.
        mid_raw = rng.randrange(MID_LO, MID_HI + 1)
        probes: list[tuple[str, SepAxiOp, int, int, int]] = []
        for cls in ("first", "mid", "last"):
            for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                if cls == "first":
                    size = rng.randrange(0, 3)
                    addr = FIRST_ABOVE_SHIM
                elif cls == "mid":
                    size = rng.randrange(0, 4)
                    addr = mid_raw & ~((1 << size) - 1)
                else:
                    size = rng.randrange(0, 4)
                    addr = LAST_WORD
                data = rng.getrandbits(8 << size) if op is SepAxiOp.WRITE else 0
                probes.append((cls, op, addr, size, data))
        wr_off = rng.randrange(0, (PAGE - 4 * BUS_BYTES) // BUS_BYTES + 1) * BUS_BYTES
        rd_off = rng.randrange(0, (PAGE - 8 * BUS_BYTES) // BUS_BYTES + 1) * BUS_BYTES
        wr_burst_addr, rd_burst_addr = BURST_PAGE + wr_off, BURST_PAGE + rd_off
        wr_burst_data = rng.getrandbits(4 * 64)
        self.logger.info(
            "DRAW LOG: mid_raw=0x%08x probes=%s wr_burst=0x%08x rd_burst=0x%08x",
            mid_raw,
            [f"{c}/{o.value}/0x{a:08x}/size{s}" for c, o, a, s, _ in probes],
            wr_burst_addr,
            rd_burst_addr,
        )

        open_graded_window(TEST, self.logger)
        # Step 4: SI single beats.
        si_cells = [await self._single("SI", op, cls, a, s, d) for cls, op, a, s, d in probes]
        # Step 5: LSU single beats to the same classes.
        lsu_cells = [await self._single("LSU", op, cls, a, s, d) for cls, op, a, s, d in probes]

        # Step 6: shim window, both initiators and directions. Responses logged.
        shim = []
        for init in ("LSU", "SI"):
            for addr in (EXT_BASE, SHIM_LAST):
                for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                    m = self._mark()
                    try:
                        seq = await self._access(
                            init, op, addr, 0, data=SHIM_RESET_BYTE[addr], ungraded=True
                        )
                    except Exception as exc:
                        raise AssertionError(
                            f"CHK-EXT-SHIM FAIL: init={init} addr=0x{addr:08x} op={op.value}: no "
                            f"response within the bound ({exc})"
                        ) from exc
                    ext = self._since(m, "PR-EXT")
                    self.logger.info(
                        "SHIM LOG: init=%s dir=%s addr=0x%08x resp=%s rdata=0x%x ext_seen=%d",
                        init,
                        "W" if op is SepAxiOp.WRITE else "R",
                        addr,
                        RESP_NAME.get(seq.resp_code, seq.resp_code),
                        seq.rdata if op is SepAxiOp.READ else 0,
                        len(ext),
                    )
                    shim.append((init, op, addr, len(ext)))

        # Steps 7 and 8: admitted SI bursts.
        m = self._mark()
        wb, wb_t = await self._timed(
            "SI", SepAxiOp.WRITE, wr_burst_addr, 3, data=wr_burst_data, nbeats=4
        )
        wb_rep = self._since(m, "PR-EXT-RSP", "b")
        wb_x = [b.addr for b in self._since(m, "PR-XEXT", "aw")]
        wb_aw = self._since(m, "PR-EXT", "aw")
        wb_w = self._since(m, "PR-EXT", "w")
        m = self._mark()
        self.env.ext_axi_monitor.start_beat_capture()
        rb, rb_t = await self._timed("SI", SepAxiOp.READ, rd_burst_addr, 3, nbeats=8)
        rb_beats = self.env.ext_axi_monitor.take_beat_capture()
        rb_rep = self._since(m, "PR-EXT-RSP", "r")
        rb_x = [b.addr for b in self._since(m, "PR-XEXT", "ar")]
        rb_ar = self._since(m, "PR-EXT", "ar")
        close_graded_window(self.logger)

        # Step 9: disable the covering entry.
        await self.inf.set_enabled(0, False)

        # Steps 10 and 11: the same bursts, refused by the filter.
        open_graded_window(TEST, self.logger)
        m = self._mark()
        wd = await self._access(
            "SI", SepAxiOp.WRITE, wr_burst_addr, 3, data=wr_burst_data, nbeats=4
        )
        wd_x = self._since(m, "PR-XEXT")
        wd_ext = self._since(m, "PR-EXT")
        m = self._mark()
        # The AXI master collapses a burst to one response; the ordered RRESP
        # of every beat comes from the m_axi bus monitor.
        self.env.ext_axi_monitor.start_beat_capture()
        await self._access("SI", SepAxiOp.READ, rd_burst_addr, 3, nbeats=8)
        rd_beats = self.env.ext_axi_monitor.take_beat_capture()
        rd_x = self._since(m, "PR-XEXT")
        rd_ext = self._since(m, "PR-EXT")
        close_graded_window(self.logger)
        await stop_taps(self.taps)

        # CHK-EXT-REACH and CHK-EXT-PORT.
        for c in si_cells:
            self._check_reach(c)
        for c in si_cells + lsu_cells:
            self._check_port(c)

        # CHK-EXT-SHIM.
        next_word_seen = sum(len(c["ext"]) for c in si_cells + lsu_cells if c["cls"] == "first")
        leaks = [(i, o.value, hex(a), n) for i, o, a, n in shim if n != 0]
        assert not leaks, f"CHK-EXT-SHIM FAIL: shim window requests left on PR-EXT: {leaks}"
        assert next_word_seen > 0, (
            "CHK-EXT-SHIM FAIL: the first word above the shim gave no PR-EXT capture; the "
            "control is dead"
        )
        self.logger.info(
            "CHK-EXT-SHIM PASS: first=0x%08X last=0x%08X seen=%d next_word_seen=%d requests=%d",
            EXT_BASE,
            SHIM_LAST,
            sum(n for _i, _o, _a, n in shim),
            next_word_seen,
            len(shim),
        )

        # CHK-EXT-BURST, write.
        want_beats = [(wr_burst_data >> (64 * i)) & ((1 << 64) - 1) for i in range(4)]
        w_ok = (
            len(wb_w) == 4
            and all(not b.has_unknown() for b in wb_w)
            and [b.data for b in wb_w] == want_beats
            and all(b.strb == 0xFF for b in wb_w)
            and [b.last for b in wb_w] == [0, 0, 0, 1]
        )
        assert wb.resp_code == RESP_DECERR and wb_x == [wr_burst_addr], (
            f"CHK-EXT-BURST FAIL: dir=W admitted resp={RESP_NAME.get(wb.resp_code)} "
            f"xbar={[hex(a) for a in wb_x if a is not None]}, expected DECERR and one PR-XEXT AW "
            f"at 0x{wr_burst_addr:08x}"
        )
        assert (
            len(wb_aw) == 1
            and wb_aw[0].addr == wr_burst_addr
            and wb_aw[0].len == 3
            and wb_aw[0].size == 3
            and w_ok
        ), (
            "CHK-EXT-BURST FAIL: dir=W PR-EXT "
            + "; ".join(b.fmt() for b in wb_aw + wb_w)
            + f"; expected AW addr=0x{wr_burst_addr:x} len=3 size=3 and beats "
            + ",".join(f"0x{v:016x}" for v in want_beats)
        )
        # The DECERR the initiator receives is the port's reply: one B on the
        # port, DECERR, before the initiator's response.
        assert len(wb_rep) == 1 and wb_rep[0].resp == RESP_DECERR and wb_rep[0].t_ps < wb_t, (
            "CHK-EXT-BURST FAIL: dir=W admitted port reply "
            + "; ".join(r.fmt() for r in wb_rep)
            + f" t_init={wb_t}ps; expected one DECERR B on PR-EXT before the initiator response"
        )
        assert wd.resp_code == RESP_DECERR and not wd_x, (
            f"CHK-EXT-BURST FAIL: dir=W denied resp={RESP_NAME.get(wd.resp_code)} "
            f"xbar_seen={len(wd_x)}; expected DECERR with PR-XEXT silent"
        )
        assert not wd_ext, (
            f"CHK-EXT-BURST FAIL: dir=W denied burst left {len(wd_ext)} PR-EXT capture(s); "
            "a refused burst never reaches the port"
        )
        self.logger.info(
            "CHK-EXT-BURST PASS: dir=W len=3 xbar_seen=%d init_resp=DECERR denied_resp=DECERR "
            "denied_xbar_seen=0 beats_seen=%d data_ok=1 denied_ext_seen=0 port_reply=DECERR "
            "port_reply_beats=%d",
            len(wb_x),
            len(wb_w),
            len(wb_rep),
        )

        # CHK-EXT-BURST, read.
        assert len(rb_beats) == 8 and all(r == RESP_DECERR for r in rb_beats), (
            f"CHK-EXT-BURST FAIL: dir=R admitted R beats {rb_beats}, expected 8, DECERR on every beat"
        )
        # The DECERR is the port's reply: eight R beats on the port, all
        # DECERR, RLAST on the eighth only, before the initiator's response.
        assert (
            len(rb_rep) == 8
            and all(r.resp == RESP_DECERR for r in rb_rep)
            and [r.last for r in rb_rep] == [0] * 7 + [1]
            and all(r.t_ps < rb_t for r in rb_rep)
        ), (
            "CHK-EXT-BURST FAIL: dir=R admitted port reply "
            + "; ".join(r.fmt() for r in rb_rep)
            + f" t_init={rb_t}ps; expected 8 DECERR R beats on PR-EXT, RLAST on beat 8, before "
            "the initiator response"
        )
        assert rb.resp_code == RESP_DECERR and rb_x == [rd_burst_addr], (
            f"CHK-EXT-BURST FAIL: dir=R admitted resp={RESP_NAME.get(rb.resp_code)} "
            f"xbar={[hex(a) for a in rb_x if a is not None]}, expected DECERR and one PR-XEXT AR "
            f"at 0x{rd_burst_addr:08x}"
        )
        assert (
            len(rb_ar) == 1
            and rb_ar[0].addr == rd_burst_addr
            and rb_ar[0].len == 7
            and rb_ar[0].size == 3
        ), (
            "CHK-EXT-BURST FAIL: dir=R PR-EXT "
            + "; ".join(b.fmt() for b in rb_ar)
            + f"; expected AR addr=0x{rd_burst_addr:x} len=7 size=3"
        )
        denied_r = rd_beats
        assert len(denied_r) == 8 and all(r == RESP_DECERR for r in denied_r) and not rd_x, (
            f"CHK-EXT-BURST FAIL: dir=R denied R beats={denied_r} xbar_seen={len(rd_x)}; "
            "expected 8 R beats, DECERR on every beat, with PR-XEXT silent"
        )
        assert not rd_ext, (
            f"CHK-EXT-BURST FAIL: dir=R denied burst left {len(rd_ext)} PR-EXT capture(s); "
            "a refused burst never reaches the port"
        )
        self.logger.info(
            "CHK-EXT-BURST PASS: dir=R len=7 xbar_seen=%d init_resp=DECERR denied_resp=DECERR "
            "denied_xbar_seen=0 beats_seen=na data_ok=na admitted_beats=%d denied_beats=%d "
            "denied_ext_seen=0 port_reply=DECERR port_reply_beats=%d",
            len(rb_x),
            len(rb_beats),
            len(denied_r),
            len(rb_rep),
        )
