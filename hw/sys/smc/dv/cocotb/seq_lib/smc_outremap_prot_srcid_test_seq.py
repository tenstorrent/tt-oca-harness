# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AxPROT through the output remaps and the AxUSER source ID of each outbound path.

Spec sources: fabric.adoc Output Remapping, Protection Bit Pass-Through, Outbound Traffic Flow
and the table "SMC Source ID by Traffic Path"; output_remap.rdl; alias_remap.rdl.

JTAG accesses carry each AxPROT value 0..7. The output interface is sampled passively at every
AW and AR handshake; the AxPROT must equal the driven value and the address must be the remapped
landing. The source-ID legs drive AxUSER 0xFFF, require it at the JTAG ingress handshake, and
require the whole 12-bit AWUSER and ARUSER at the output to equal the path's source ID (`SMC_ID` 0x3 direct, `OTHER_ID` 0x0 through the Xvisor
remap, `MMODE_ID` 0xC through the M-mode remap), so bits [11:4] leave as zero; an access through a
clear M-mode region keeps its address and still leaves with `MMODE_ID`.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, reg_reset_word, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    RESPONDER_OBS_TIMEOUT_CYCLES,
    check_output_responder_delta,
    output_responder_counts,
)

_REMAP_H = _REPO / "hw" / "ip" / "output_remap" / "regs" / "gen" / "c" / "output_remap.h"
_ALIAS_H = _REPO / "hw" / "ip" / "axi_alias_remap" / "regs" / "gen" / "c" / "alias_remap.h"
_REMAP_RESET = reg_reset_word(_REMAP_H, "OUTPUT_REMAP", "OUTPUT_REMAP_REGION__REGION_ATTRS")
_ALIAS_RESET = {
    reg: reg_reset_word(_ALIAS_H, "ALIAS_REMAP", f"REMAP_REGION__REGION_{reg}")
    for reg in ("START", "END", "ATTRS")
}


def _remap_reg(bank: str, entry: int) -> int:
    sym = f"SMC_TOP_SMC_{bank}_REMAP_WRAP_OUTPUT_REMAP_REGION_REGION_ATTRS_BASE_ADDR"
    return smc_indexed_addr(sym, entry)


def _alias_reg(reg: str) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_{reg}_BASE_ADDR", 6
    )


# Register words (output_remap.rdl REGION_ATTRS offset[55:0], valid[63]; alias region 6).
_M1_ATTRS = 0x8000_0000_0250_0000
_M4_ATTRS = 0x0000_0000_02B0_0000
_X1_ATTRS = 0x8000_0000_02A0_0000
_ALIAS = {"START": 0x0203_0000, "END": 0x0203_1000, "ATTRS": 0x8000_0000_0010_0000}
_PROGRAM = (
    ("M1", _remap_reg("MMODE", 1), _M1_ATTRS, _REMAP_RESET),
    ("M4", _remap_reg("MMODE", 4), _M4_ATTRS, _REMAP_RESET),
    ("X1", _remap_reg("XVISOR", 1), _X1_ATTRS, _REMAP_RESET),
    ("ALIAS6_START", _alias_reg("START"), _ALIAS["START"], _ALIAS_RESET["START"]),
    ("ALIAS6_END", _alias_reg("END"), _ALIAS["END"], _ALIAS_RESET["END"]),
    ("ALIAS6_ATTRS", _alias_reg("ATTRS"), _ALIAS["ATTRS"], _ALIAS_RESET["ATTRS"]),
)

_MMODE_WIN, _MMODE_LAND = 0xC110_0000, 0x0250_0000
_XVISOR_WIN, _XVISOR_LAND = 0xC190_0000, 0x02A0_0000
_DIRECT = 0x0200_0000
_ALIAS_ADDR, _ALIAS_LAND, _ALIAS_PROT = 0x0203_0040, 0x0213_0040, 0b101
_M4_ADDR = 0xC140_0100
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
# fabric.adoc, "SMC Source ID by Traffic Path": SMC_ID 0x3, OTHER_ID 0x0, MMODE_ID 0xC.
SMC_ID = 0x3
OTHER_ID = 0x0
MMODE_ID = 0xC
_USER_WIDTH = 12
_USER_ALL = (1 << _USER_WIDTH) - 1
_PATH_REQUESTS = 3
_AXI_BOUND_NS = 50_000
_FUSE_BOUND = 200_000
_FLOOR = 81
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
_TERMS = (
    "REGIONS_PROGRAMMED<PROT_MMODE<PROT_XVISOR<PROT_DIRECT<PROT_AFTER_ALIAS<SRCID_SAMPLES"
    "<VALID0_SAMPLE"
)
_CHECKERS = (
    ("CHK-PROT-MMODE", "S2"),
    ("CHK-PROT-XVISOR", "S3"),
    ("CHK-PROT-DIRECT", "S4"),
    ("CHK-PROT-AFTER-REMAPS", "S5"),
    ("CHK-SRCID-DIRECT-0X3", "S6"),
    ("CHK-SRCID-MMODE-0XC", "S6"),
    ("CHK-SRCID-XVISOR-0X0", "S6"),
    ("CHK-VALID0-SRCID-MMODE-0XC", "S7"),
)


class _Sampler:
    """Passive sampler of AW and AR handshakes on the output interface and at the JTAG ingress.

    An output event is ``(ch, addr, prot, user)``; a JTAG ingress event is ``("j" + ch, addr, 0,
    user)`` with the AxUSER the JTAG manager presented.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, int, int, int]] = []

    @staticmethod
    def _bit(sig, name: str) -> int:
        assert sig.value.is_resolvable, f"{name} is X/Z ({sig.value})"
        return int(sig.value)

    async def run(self) -> None:
        top = cocotb.top
        ifc = top.u_output_axi_if
        while True:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for ch in ("aw", "ar"):
                valid = self._bit(getattr(ifc, f"{ch}valid"), f"{ch}valid")
                ready = self._bit(getattr(ifc, f"{ch}ready"), f"{ch}ready")
                if valid and ready:
                    vals = [
                        self._bit(getattr(ifc, f"{ch}{n}"), f"{ch}{n}")
                        for n in ("addr", "prot", "user")
                    ]
                    self.events.append((ch, *vals))
                jvalid = self._bit(getattr(top, f"jtag_axi_{ch}valid"), f"jtag {ch}valid")
                jready = self._bit(getattr(top, f"jtag_axi_{ch}ready"), f"jtag {ch}ready")
                if jvalid and jready:
                    jaddr = self._bit(getattr(top, f"jtag_axi_{ch}addr"), f"jtag {ch}addr")
                    juser = self._bit(getattr(top, f"jtag_axi_{ch}user"), f"jtag {ch}user")
                    self.events.append((f"j{ch}", jaddr, 0, juser))


class smc_outremap_prot_srcid_test_seq(SmcCsrSeq):
    """Drive JTAG traffic with every AxPROT through the remaps and sample the output."""

    def __init__(self, name: str = "smc_outremap_prot_srcid_test_seq") -> None:
        super().__init__(name)
        self.jtag_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._sampler = _Sampler()
        self._counts = [0, 0]

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _program(self, entries, final: bool) -> None:
        for label, addr, program, reset in entries:
            want = reset if final else program
            await self.csr_write(f"{label}_{'RESTORE' if final else 'SET'}", addr, want, length=8)
            await self.csr_read(f"{label}_RB", addr, expected=want, length=8)

    async def _access(self, op, addr, prot, land, word, user=0):
        """One JTAG access; returns (awprot-or-arprot, user) sampled at its handshake."""
        kind = "aw" if op is SmcSysAxiOp.WRITE else "ar"
        seen = len(self._sampler.events)
        item = SmcSysAxiItem(f"{op.value}_0x{addr:x}_p{prot}")
        item.op, item.addr, item.length, item.prot = op, addr, 8, prot
        item.axi_user, item.axi_wuser = user, user
        if kind == "aw":
            item.wdata = word
        else:
            item.expected = word
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"JTAG {op.value} 0x{addr:x} prot {prot} resp {item.resp_code}"
        await check_output_responder_delta(
            start_writes=self._counts[0],
            start_reads=self._counts[1],
            write_delta=kind == "aw",
            read_delta=kind == "ar",
            last_addr=land if kind == "aw" else None,
            last_wdata=word if kind == "aw" else None,
        )
        self._counts[0 if kind == "aw" else 1] += 1
        got = [e for e in self._sampler.events[seen:] if e[0] == kind]
        assert len(got) == 1, f"{op.value} 0x{addr:x}: {len(got)} {kind} handshakes: {got}"
        _, haddr, hprot, huser = got[0]
        assert haddr == land, f"{op.value} 0x{addr:x}: {kind}addr 0x{haddr:x}, want 0x{land:x}"
        ingress = [e for e in self._sampler.events[seen:] if e[0] == f"j{kind}"]
        assert len(ingress) == 1, f"{op.value} 0x{addr:x}: {len(ingress)} JTAG {kind} handshakes"
        assert ingress[0][1] == addr and ingress[0][3] == user, (
            f"{op.value} 0x{addr:x}: JTAG ingress {kind}addr 0x{ingress[0][1]:x} {kind}user "
            f"0x{ingress[0][3]:03x}, driven 0x{addr:x} / 0x{user:03x}"
        )
        if kind == "ar":
            assert item.rdata == word, f"read 0x{addr:x} gave 0x{item.rdata:x}, want 0x{word:x}"
        return hprot, huser

    async def _write_leg(self, addr, prot, land, word, window=True, user=0):
        responder = self.cfg.sys_out_mem
        responder.write_int(land, _SENTINEL, 8)
        hprot, huser = await self._access(SmcSysAxiOp.WRITE, addr, prot, land, word, user)
        landed = responder.read_int(land, 8)
        assert landed == word, f"write 0x{addr:x} left 0x{landed:016x} at 0x{land:x}, want {word:x}"
        if window and addr != land:
            other = responder.read_int(addr, 8)
            assert other != word, f"write 0x{addr:x} also reached its unremapped address"
        assert hprot == prot, f"write 0x{addr:x}: awprot {hprot}, want {prot}"
        return hprot, huser

    async def _read_leg(self, addr, prot, land, word, user=0):
        self.cfg.sys_out_mem.write_int(land, word, 8)
        hprot, huser = await self._access(SmcSysAxiOp.READ, addr, prot, land, word, user)
        assert hprot == prot, f"read 0x{addr:x}: arprot {hprot}, want {prot}"
        return hprot, huser

    async def _sweep(self, base: int, land: int, tag: int) -> list[int]:
        out = []
        for p in range(8):
            word = 0xA000_0000_0000_0000 | (tag << 32) | (p << 8) | 0x40
            hprot, _ = await self._write_leg(base + 0x40 + 8 * p, p, land + 0x40 + 8 * p, word)
            out.append(hprot)
        return out

    async def _path(self, base: int, land: int, tag: int):
        """Three writes and three reads with AxUSER 0xFFF; the output AWUSER/ARUSER per request."""
        users = {"aw": [], "ar": []}
        for n in range(_PATH_REQUESTS):
            word = 0xB000_0000_0000_0000 | (tag << 32) | n
            got = await self._write_leg(base + 0x100, 0, land + 0x100, word, user=_USER_ALL)
            users["aw"].append(got[1])
        for n in range(_PATH_REQUESTS):
            word = 0xB000_0000_0000_0000 | (tag << 32) | n
            got = await self._read_leg(base + 0x100, 0, land + 0x100, word, user=_USER_ALL)
            users["ar"].append(got[1])
        return users

    @staticmethod
    def _source_id(chk: str, path: str, users, want: int) -> tuple[int, int]:
        """Every captured AWUSER and ARUSER of ``path`` equals ``want`` over all 12 bits."""
        for ch in ("aw", "ar"):
            got = users[ch]
            assert len(got) == _PATH_REQUESTS, f"{chk}: {path} {ch} captured {len(got)} requests"
            assert all(u == want for u in got), (
                f"{chk}: {path} path {ch}user {[hex(u) for u in got]} with AxUSER 0x{_USER_ALL:x} "
                f"driven, want 0x{want:03x} on every request (fabric.adoc Output Remapping: the "
                f"path replaces the whole AWUSER and ARUSER with its source ID, bits [11:4] zero)"
            )
        return users["aw"][0], users["ar"][0]

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        top = cocotb.top
        fuse = []
        for sig in (top.tb_fuse_sense_done, top.tb_fuse_reset_n, top.tb_rst_warm_smc_clk_n):
            assert sig.value.is_resolvable, f"{sig._name} is X/Z ({sig.value})"
            fuse.append(int(sig.value))
        self._waits.append(
            f"tb_fuse_sense_done bound {_FUSE_BOUND} clk_smc_i last {fuse[0]}; tb_fuse_reset_n "
            f"bound {_FUSE_BOUND} last {fuse[1]}; tb_rst_warm_smc_clk_n bound {_FUSE_BOUND} "
            f"last {fuse[2]}"
        )
        sampler_task = cocotb.start_soon(self._sampler.run())

        # S1: the regions start at their reset words, then take the programmed words.
        for label, addr, _program, reset in (_PROGRAM[0], _PROGRAM[1], _PROGRAM[2], _PROGRAM[5]):
            await self.csr_read(f"{label}_RESET", addr, expected=reset, length=8)
        await self._program(_PROGRAM, final=False)
        self._counts = list(output_responder_counts())
        self._mark_step("S1")

        # S2 and S3: both output remaps keep AxPROT.
        mmode = await self._sweep(_MMODE_WIN, _MMODE_LAND, 2)
        self._mark_step("S2")
        self._log_chk(
            "CHK-PROT-MMODE",
            f"8 writes at 0x{_MMODE_WIN + 0x40:x}+8p landed at 0x{_MMODE_LAND + 0x40:x}+8p with "
            f"awprot {mmode} == p; spec source fabric.adoc Privilege-Controlled Remapping",
        )
        xvisor = await self._sweep(_XVISOR_WIN, _XVISOR_LAND, 3)
        self._mark_step("S3")
        self._log_chk(
            "CHK-PROT-XVISOR",
            f"8 writes at 0x{_XVISOR_WIN + 0x40:x}+8p landed at 0x{_XVISOR_LAND + 0x40:x}+8p "
            f"with awprot {xvisor} == p; spec source fabric.adoc Privilege-Controlled "
            "Remapping",
        )

        # S4: outside the windows nothing is remapped and AxPROT is unchanged.
        wprot, rprot = [], []
        for p in range(8):
            word = 0xC000_0000_0000_0000 | (p << 8)
            wprot.append(
                (
                    await self._write_leg(
                        _DIRECT + 0x40 + 8 * p, p, _DIRECT + 0x40 + 8 * p, word, window=False
                    )
                )[0]
            )
        for p in range(8):
            addr = _DIRECT + 0x140 + 8 * p
            rprot.append((await self._read_leg(addr, p, addr, 0xD000_0000_0000_0000 | p))[0])
        self._mark_step("S4")
        self._log_chk(
            "CHK-PROT-DIRECT",
            f"8 writes at 0x{_DIRECT + 0x40:x}+8p and 8 reads at 0x{_DIRECT + 0x140:x}+8p landed "
            f"unremapped with awprot {wprot} and arprot {rprot} == p; seeded read words returned",
        )

        # S5: alias remap hit.
        hprot, _ = await self._write_leg(
            _ALIAS_ADDR, _ALIAS_PROT, _ALIAS_LAND, 0xE000_0000_0000_0005
        )
        self._mark_step("S5")
        self._log_chk(
            "CHK-PROT-AFTER-REMAPS",
            f"alias region 6 write prot 0b{_ALIAS_PROT:03b} at 0x{_ALIAS_ADDR:x} landed at "
            f"0x{_ALIAS_LAND:x} with awprot 0b{hprot:03b}; output remap hits kept awprot == p "
            f"for all eight values (M-mode {mmode}, Xvisor {xvisor})",
        )

        # S6: the source ID of each path (fabric.adoc "SMC Source ID by Traffic Path").
        paths = (
            ("CHK-SRCID-DIRECT-0X3", "direct", _DIRECT, _DIRECT, 6, SMC_ID),
            ("CHK-SRCID-MMODE-0XC", "M-mode", _MMODE_WIN, _MMODE_LAND, 7, MMODE_ID),
            ("CHK-SRCID-XVISOR-0X0", "Xvisor", _XVISOR_WIN, _XVISOR_LAND, 8, OTHER_ID),
        )
        ids = {}
        for chk, path, win, land, tag, want in paths:
            ids[path] = self._source_id(chk, path, await self._path(win, land, tag), want)
        assert len({SMC_ID, MMODE_ID, OTHER_ID}) == 3
        self._mark_step("S6")
        for chk, path, win, _land, _tag, want in paths:
            aw, ar = ids[path]
            self._log_chk(
                chk,
                f"{path} path at 0x{win + 0x100:x} with AxUSER 0x{_USER_ALL:x} driven and seen "
                f"at the JTAG ingress: "
                f"awuser=0x{aw:03x} aruser=0x{ar:03x} == 0x{want:03x} on {_PATH_REQUESTS} writes "
                f"and {_PATH_REQUESTS} reads, bits [11:4] zero; the other two paths carry "
                + ", ".join(f"0x{v:03x}" for v in sorted({SMC_ID, MMODE_ID, OTHER_ID} - {want})),
            )

        # S7: a clear M-mode region keeps the address and still leaves with MMODE_ID.
        word = 0xF000_0000_0000_0004
        _, aw = await self._write_leg(_M4_ADDR, 0, _M4_ADDR, word, window=False, user=_USER_ALL)
        _, ar = await self._read_leg(_M4_ADDR, 0, _M4_ADDR, word, user=_USER_ALL)
        assert aw == MMODE_ID and ar == MMODE_ID, (
            f"CHK-VALID0-SRCID-MMODE-0XC: M-mode region 4 (valid clear) at 0x{_M4_ADDR:x}: "
            f"awuser 0x{aw:03x} aruser 0x{ar:03x}, want 0x{MMODE_ID:03x} (fabric.adoc Output "
            f"Remapping: a request to a remap window leaves with the window's source ID)"
        )
        self._mark_step("S7")
        self._log_chk(
            "CHK-VALID0-SRCID-MMODE-0XC",
            f"M-mode region 4 (valid clear) at 0x{_M4_ADDR:x} landed at its own address with "
            f"AxUSER 0x{_USER_ALL:x} driven: awuser=0x{aw:03x} aruser=0x{ar:03x} == "
            f"0x{MMODE_ID:03x}, bits [11:4] zero; direct path carried 0x{ids['direct'][0]:03x}",
        )

        # S8: restore every programmed register to its reset word.
        await self._program(_PROGRAM, final=True)
        self._mark_step("S8")
        sampler_task.cancel()

        self._waits += [
            f"SEP_IN and JTAG AXI accesses bound {_AXI_BOUND_NS} ns, allow_timeout False, "
            f"{self.accesses} SEP_IN and {self.jtag_accesses} JTAG completed",
            f"check_output_responder_delta bound {RESPONDER_OBS_TIMEOUT_CYCLES} clk_smc_i per "
            f"JTAG access, last write/read counts {self._counts}",
            "passive AW/AR handshake sampler on output_axi and the JTAG ingress: no wait, one "
            f"sample per clk_smc_i rise, {len(self._sampler.events)} handshakes recorded",
        ]
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        assert tuple(c for c, _ in self._chk_marks) == tuple(c for c, _ in _CHECKERS)
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        total = self.accesses + self.jtag_accesses
        assert total >= _FLOOR, f"{total} accesses, floor {_FLOOR}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d (%d SEP_IN + %d JTAG) "
            "vs floor %d; stamps %s",
            _TERMS,
            ",".join(c for c, _ in self._chk_marks),
            total,
            self.accesses,
            self.jtag_accesses,
            _FLOOR,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
        cocotb.log.info("CHK-TIMEOUT-PATHS: %s", " | ".join(self._waits))
