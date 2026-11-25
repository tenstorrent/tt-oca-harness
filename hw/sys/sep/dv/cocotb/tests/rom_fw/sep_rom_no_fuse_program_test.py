# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ROM burns no fuse on a boot whose manifest carries a flag the fuses lack.

rom.adoc, Secure Boot, Anti-Rollback:

    [SEP-ROM-SB-080] Device security-state *commit* (OR-ing the manifest's revocation bitmap and
    security-version flags into the fuses, unless suppressed by `manifest_security_control`)
    shall follow the authenticate-before-update rule: it may only happen after full validation
    succeeds. The division of labor is architectural, not a staging decision: *the ROM burns no
    fuses*. BL0 performs read-only validation and records the commit directive in `bl0_state`;
    SEP BL1 -- the firmware BL0 has just authenticated -- owns the fuse programming. BL0
    therefore has no fuse-programming path by design, and one should not be added to it.

rom.adoc, Implementation Status:

    |Device security-state commit |*by design* |Not a gap. The ROM burns no fuses at all: BL0
    performs read-only validation and records the commit directive in `bl0_state`, and SEP BL1
    owns the fuse programming.

Stimulus: both slots carry the device flags of `sep_firmware_bl1_ver_test` plus flag 127, which
the fuses lack, with `manifest_security_control` 0, so a security-version commit is due and
nothing suppresses it. The extra flag sits above the low word, so the inherited `FUSE_VER=` /
`MFST_VER=` echo checks still hold.

The OTP bank is `otp_bank_probe_o`, the 256 words SEP reaches. Fuse commands are the post-guard
shim tap `efuse_shim_cmd_*_o`, which carries every fuse-sense read and any program. Reset is the
first clock with `rst_ni` 1 after the cold-reset pulse that loads the image; hand-off is the first
clock after the hand-off `mret` retires; the end is after the BL1 verdict.

* CHK-NO-OTP-CHANGE: the bank at hand-off and at the end equals the bank at reset, word for word.
* CHK-NO-PROGRAM-CMD: no PROGRAM or PROGRAM_READ_BACK command on the shim tap from the monitor
  start (the first clock, before reset release) to the end. The BL1 of this image
  (`bl1_pass_test`) only reads fuses.
* CTRL-OTP-SNAPSHOT-LIVE: the bank at reset equals the image this test wrote.
* CTRL-SHIM-CMD-LIVE: the tap records READ commands between the monitor start and hand-off.
* CTRL-NEWER-VERSION-BOOTED: the primary manifest bytes the flash served carry a strict superset
  of the fuse flags at reset and `manifest_security_control` bit 0 clear, and control reached the
  BL1 entry of that manifest, which then reported PASS.

Partial coverage. Not graded: "records the commit directive in `bl0_state`", because
tbl:bl0_state defines no field for it; a commit due from the revocation bitmap; the order of a
commit after validation, which belongs to BL1; a program start that the program interface
rejects, which raises only `program_done` / `program_error` and not the request valid or busy
that OBS-PROGRAM-IF logs, so rejected starts are not observed. The leaf runs
`sep_firmware_bl1_ver_test` and keeps its checks.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepEfuseBank, SepShimCmdMonitor, bank_diff, diff_log
from env.sep_efuse_image import SepEfuseImage
from env.sep_rom_observer import SepRomObserver
from rom_fw.sep_firmware_bl1_ver_test import _DEVICE_FLAGS
from rom_fw.sep_firmware_bl1_ver_test import sep_firmware_bl1_ver_test as _Base

_NEWER_FLAG = 1 << 127
_MANIFEST_FLAGS = _DEVICE_FLAGS | _NEWER_FLAG
# The platform reads the low 16 bytes of BL1_VERSION.
_BL1_VERSION_WORD = SepEfuseImage.field("BL1_VERSION").word
_VERSION_WORDS = 4
_OFF_SECURITY_CONTROL = mm.K.OFF_MANIFEST_SECURITY_CONTROL
_SECURITY_VERSION_UPDATE_DISABLE = 1 << 0
_PROGRAM_IF = ("efuse_program_cmd_req_valid_o", "efuse_program_busy_o")


def _ps(t: int | None) -> int:
    return -1 if t is None else int(t)


def _flags(words: tuple[int, ...] | None) -> int | None:
    """The 128 device security-version flags held in a bank image."""
    if words is None:
        return None
    lo = words[_BL1_VERSION_WORD : _BL1_VERSION_WORD + _VERSION_WORDS]
    return sum(w << (32 * i) for i, w in enumerate(lo))


def _served(rds: list, addr: int, n: int) -> bytes | None:
    """The bytes the flash device returned for [addr, addr + n), from the first read of each."""
    out = bytearray()
    for a in range(addr, addr + n):
        hit = ev.covering_read(rds, a)
        if hit is None:
            return None
        out += ev.bytes_at(hit[1], a, 1)
    return bytes(out)


def _cmd(c) -> str:
    return "none" if c is None else f"{c.name}@0x{c.address:x}/clk{c.clk}"


@pyuvm.test()
class sep_rom_no_fuse_program_test(_Base):
    required_evidence = ("CHK-NO-OTP-CHANGE", "CHK-NO-PROGRAM-CMD", "CHK-ROM-PATH")

    def build_efuse_image(self):
        self._efuse = super().build_efuse_image()
        return self._efuse

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            # A re-seal reproduces a valid slot only from a sealed slot the local signer reproduces.
            pm.verify_sealed(buf, slot)
            mm.verify_public_key(buf, slot)
            pm.verify_signing_key(buf, slot)
            mm.set_security_version(buf, slot, _MANIFEST_FLAGS)
            pm.reseal(buf, slot)
            pm.verify_sealed(buf, slot)
            self.chk.obs("STIMULUS", slot=slot, manifest=mm.describe(buf, slot))
        self._loaded = bytes(buf)
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        rds = ev.reads(flash.get_transactions())
        base = mm.PRIMARY_MANIFEST_OFFSET
        self._served_version = _served(rds, base + mm.OFF_SECURITY_VERSION, mm.SECURITY_VERSION_LEN)
        self._served_control = _served(rds, base + _OFF_SECURITY_CONTROL, 2)
        super().check_transport(console, flash)

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self._efuse = None
        self._loaded = None
        self._served_version = self._served_control = None
        dut = cocotb.top
        bank = SepEfuseBank(dut)
        shim = SepShimCmdMonitor(dut).start()
        m_start = shim.mark()
        obs = SepRomObserver(self, keep=lambda _insn: False, tracker=False, watch=_PROGRAM_IF)
        obs.start()
        snaps: dict = {}
        marks: dict = {}
        snapper = cocotb.start_soon(self._snap(bank, shim, obs, snaps, marks))
        try:
            await super().run_scenario()
        finally:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            snaps["end"] = (int(get_sim_time("ps")), bank.read())
            m_end = shim.mark()
            snapper.cancel()
            await obs.stop()
            await shim.stop()
            self._grade(obs, shim, snaps, marks, m_start, m_end)
        self.chk.finish()

    async def _snap(self, bank, shim, obs, snaps: dict, marks: dict) -> None:
        """Bank image and shim mark at reset release and at the first clock after hand-off."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.rst_ni, allow_unknown=True):
                break
        snaps["reset"] = (int(get_sim_time("ps")), bank.read())
        marks["reset"] = shim.mark()
        while not obs.pre_mret:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
        snaps["handoff"] = (int(get_sim_time("ps")), bank.read())
        marks["handoff"] = shim.mark()

    def _grade(self, obs, shim, snaps: dict, marks: dict, m_start, m_end) -> None:
        chk = self.chk
        t_rst, s_rst = snaps.get("reset", (None, None))
        t_ho, s_ho = snaps.get("handoff", (None, None))
        t_end, s_end = snaps.get("end", (None, None))
        image = tuple(self._efuse.words) if self._efuse is not None else None
        fuse = _flags(s_rst)
        chk.ctrl(
            "OTP-SNAPSHOT-LIVE",
            s_rst is not None and s_rst == image and fuse == _DEVICE_FLAGS,
            reset_ps=_ps(t_rst),
            nonzero_words=0 if s_rst is None else sum(1 for w in s_rst if w),
            vs_image="none" if None in (s_rst, image) else diff_log(bank_diff(image, s_rst)),
            fuse_flags="none" if fuse is None else f"0x{fuse:032x}",
        )
        d_ho = None if None in (s_rst, s_ho) else bank_diff(s_rst, s_ho)
        d_end = None if None in (s_rst, s_end) else bank_diff(s_rst, s_end)
        chk.ok(
            "NO-OTP-CHANGE",
            d_ho == [] and d_end == [],
            reset_ps=_ps(t_rst),
            handoff_ps=_ps(t_ho),
            end_ps=_ps(t_end),
            handoff_diff="none" if d_ho is None else diff_log(d_ho),
            end_diff="none" if d_end is None else diff_log(d_end),
        )

        m_rst, m_ho = marks.get("reset"), marks.get("handoff")
        err = "none"
        cmds: list = []
        # A dead or idle monitor fails the checks below instead of ending the grade.
        try:
            cmds = shim.commands_since(m_start)
        except AssertionError as exc:
            err = f"{type(exc).__name__}: {exc}"
        ho_clk = m_ho.clk if m_ho is not None else m_end.clk
        rom = [c for c in cmds if c.clk <= ho_clk]
        rom_reads = [c for c in rom if c.is_read]
        progs = [c for c in cmds if c.is_program]
        chk.ctrl(
            "SHIM-CMD-LIVE",
            err == "none" and None not in (m_rst, m_ho) and bool(rom_reads),
            reset_clk=-1 if m_rst is None else m_rst.clk,
            handoff_clk=-1 if m_ho is None else m_ho.clk,
            reads_to_handoff=len(rom_reads),
            first_read=_cmd(rom_reads[0] if rom_reads else None),
            monitor_error=err,
        )
        chk.ok(
            "NO-PROGRAM-CMD",
            err == "none" and m_ho is not None and not progs,
            sampled_clks=m_end.clk - m_start.clk,
            commands=len(cmds),
            reads=sum(1 for c in cmds if c.is_read),
            other=sum(1 for c in cmds if not (c.is_read or c.is_program)),
            programs_to_handoff=sum(1 for c in progs if c.clk <= ho_clk),
            programs_after_handoff=sum(1 for c in progs if c.clk > ho_clk),
            first_program=_cmd(progs[0] if progs else None),
            monitor_error=err,
        )
        chk.obs(
            "PROGRAM-IF",
            **{n: sum(1 for _t, v in obs.watched[n] if v) for n in _PROGRAM_IF},
        )

        loaded = self._loaded
        mv = mm.security_version(loaded, "primary") if loaded is not None else None
        base = mm.PRIMARY_MANIFEST_OFFSET + _OFF_SECURITY_CONTROL
        ctl = int.from_bytes(loaded[base : base + 2], "little") if loaded is not None else None
        sv = self._served_version
        sc = self._served_control
        served_v = int.from_bytes(sv, "little") if sv is not None else None
        served_c = int.from_bytes(sc, "little") if sc is not None else None
        entry = None
        if loaded is not None:
            entry = (
                pm.bl1_field(loaded, "primary", pm.E_LOAD_ADDR)
                + pm.bl1_field(loaded, "primary", pm.E_ENTRY_POINT)
            ) & 0xFFFF_FFFF
        post = obs.post_mret
        t_mret = obs.pre_mret[-1].t_ps if obs.pre_mret else None
        t_verdict = obs.verdict[-1][0] if obs.verdict else None
        verdict = obs.verdict_pass()
        chk.ctrl(
            "NEWER-VERSION-BOOTED",
            None not in (mv, fuse, ctl, entry, post, t_mret, t_verdict)
            and served_v == mv
            and served_c == ctl
            and mv & fuse == fuse
            and mv != fuse
            and not ctl & _SECURITY_VERSION_UPDATE_DISABLE
            and post.pc == entry
            and verdict is True
            and t_verdict > t_mret
            and bool(self.sb.fw_done and self.sb.fw_pass),
            manifest_flags="none" if mv is None else f"0x{mv:032x}",
            served_flags="none" if served_v is None else f"0x{served_v:032x}",
            fuse_flags="none" if fuse is None else f"0x{fuse:032x}",
            flags_not_in_fuse="none" if None in (mv, fuse) else f"0x{mv & ~fuse:032x}",
            security_control="none" if ctl is None else f"0x{ctl:04x}",
            served_security_control="none" if served_c is None else f"0x{served_c:04x}",
            bl1_entry="none" if entry is None else f"0x{entry:08x}",
            post_mret_pc="none" if post is None else f"0x{post.pc:08x}",
            mret_ps=_ps(t_mret),
            verdict_ps=_ps(t_verdict),
            verdict_pass=-1 if verdict is None else int(verdict),
        )
