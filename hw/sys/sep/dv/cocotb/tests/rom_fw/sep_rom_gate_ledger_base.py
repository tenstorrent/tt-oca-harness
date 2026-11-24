# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base of the leaves that grade the Boot ROM pre-hand-off gate ledger and self-check.

rom.adoc, Pre-Hand-off Self-Check (Gate Ledger):

* "Four acceptance gates each record a bit in a `gate_ok` word *and* clear the same bit in a
  complement word `gate_inv` as they pass: `BOOT_GATE_MANIFEST` (bit 0, `0x1` ...),
  `BOOT_GATE_CRYPTO` (bit 1, `0x2` ...), `BOOT_GATE_HASH` (bit 2, `0x4` ...),
  `BOOT_GATE_FUSELOCK` (bit 3, `0x8` ...). `BOOT_GATE_EXPECT` is `0xF`, all four bits, in
  every boot mode."
* SEP-ROM-HOFF-040: "At [S29], after the BL1 copy and before the `EXEC_IMAGE` and
  `STARTING_BL1` reports and the PMP release, the ROM shall require
  `gate_ok == BOOT_GATE_EXPECT` *and* `gate_inv == ~BOOT_GATE_EXPECT` (`0xFFFF_FFF0`)."
* SEP-ROM-HOFF-050: "Any shortfall or disagreement is fatal
  (`ROM_ERR_HANDOFF_SELFCHECK_FAILED`, `0xF004`)."

A leaf injects one fault at run time through the boot ROM bit-flip hook (an instruction
replaced after the [S17] self-hash, which covers the whole image) or the TCM bit-flip hook
(a DCCM word changed with an ECC-consistent mask), shows the fault took effect, and grades
the halt: the 0xF004 ERROR status, no STARTING_BL1, no PMP write after the cold rule set, no
retirement outside the Boot ROM, and the self-check branch that raised it.

Flip targets come from the image the run loads (+sep_boot_rom_hex) and the symbol list the
ROM build writes beside it, decoded here; nothing is a hand-typed address.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env import sep_rv32_asm as asm
from env.sep_esrc_noise import esrc_noise_task
from env.sep_rom_image import ROM_BYTES, rom_flip
from env.sep_rom_observer import Retire, SepRomObserver, load_rom_syms
from env.sep_rv32_trace_decode import (
    CSR_PMPCFG0,
    OP_AUIPC,
    OP_JAL,
    OP_JALR,
    OP_LOAD,
    OP_LUI,
    OP_OP_IMM,
    OP_STORE,
    decode_csr,
    funct3,
    imm_i,
    imm_s,
    opcode,
    rd_of,
    rs1_of,
    writes_rd,
)
from env.sep_tcm_flip import DCCM_BASE, tcm_flip
from rom_fw.sep_rom_observe_base import ROM_BASE, sep_rom_observe_base

ROM_HI = ROM_BASE + ROM_BYTES
OP_BRANCH = 0x63
INSN_NOP = asm.addi(asm.ZERO, asm.ZERO, 0)
_WORD = 0xFFFF_FFFF

# STATUS_ENCODE(type, BL0 1, code) from errors.h; codes from status_values.h.
STATUS_HALT_F004 = 0x0F01_F004
STATUS_STARTING_BL1 = 0x0101_0043
STATUS_EXEC_IMAGE = 0x0101_0054
STATUS_PRESTART_DONE = 0x8001_0056
STATUS_START_PAYLOAD_VALIDATION = 0x8001_0052
STATUS_PAYLOAD_VALIDATED = 0x0101_0055
SCRATCH_STATUS = 0x1080_2008
BOOT_GATE_EXPECT = 0xF
GATES = ("manifest", "crypto", "hash", "fuselock")
GATE_BIT = {g: 1 << i for i, g in enumerate(GATES)}
CHECKS = (
    "check_ledger",
    "check_locus_first",
    "check_locus_second",
    "check_locks_first",
    "check_locks_second",
)
# Console line of [S20], which runs after the [S17] self-hash and before [S23].
AFTER_S17_LINE = "DMA_INIT_OK"
# Console line of [S27], after [S23] recorded the manifest and before [S29].
AFTER_S23_LINE = "MEAS_BOOT_STATE_OK"


def _sext(v: int, bits: int) -> int:
    return v - (1 << bits) if v >> (bits - 1) & 1 else v


def imm_b(insn: int) -> int:
    v = (
        ((insn >> 31) & 1) << 12
        | ((insn >> 7) & 1) << 11
        | ((insn >> 25) & 0x3F) << 5
        | ((insn >> 8) & 0xF) << 1
    )
    return _sext(v, 13)


def imm_j(insn: int) -> int:
    v = (
        ((insn >> 31) & 1) << 20
        | ((insn >> 12) & 0xFF) << 12
        | ((insn >> 20) & 1) << 11
        | ((insn >> 21) & 0x3FF) << 1
    )
    return _sext(v, 21)


def jump(src: int, dst: int) -> int:
    """jal x0 from src to dst."""
    return asm.jal(asm.ZERO, dst - src)


def rvecc(data: int) -> int:
    """The 7 ECC bits VeeR EL2 stores beside a 32-bit TCM word (rvecc_encode)."""
    d = [(data >> i) & 1 for i in range(32)]
    groups = (
        (0, 1, 3, 4, 6, 8, 10, 11, 13, 15, 17, 19, 21, 23, 25, 26, 28, 30),
        (0, 2, 3, 5, 6, 9, 10, 12, 13, 16, 17, 20, 21, 24, 25, 27, 28, 31),
        (1, 2, 3, 7, 8, 9, 10, 14, 15, 16, 17, 22, 23, 24, 25, 29, 30, 31),
        (4, 5, 6, 7, 8, 9, 10, 18, 19, 20, 21, 22, 23, 24, 25),
        (11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25),
        (26, 27, 28, 29, 30, 31),
    )
    ecc = 0
    for i, g in enumerate(groups):
        bit = 0
        for b in g:
            bit ^= d[b]
        ecc |= bit << i
    overall = bin(data & _WORD).count("1") ^ bin(ecc).count("1")
    return ecc | (overall & 1) << 6


def ecc_consistent_mask(data_mask: int) -> int:
    """39-bit stored-word mask that changes the data by data_mask and keeps the ECC valid.

    rvecc_encode is XOR-linear, so the ECC of (d ^ m) is ecc(d) ^ ecc(m).
    """
    return (data_mask & _WORD) | rvecc(data_mask) << 32


def dccm_stored(addr: int) -> int:
    """The 39-bit stored word (data and ECC) of the DCCM word at addr."""
    off = addr - DCCM_BASE
    ipi = cocotb.top.u_dut.u_sep_ip_integration
    bank = ipi.u_sep_tcm_wrapper.gen_dccm.gen_bank[(off >> 2) & 1]
    return int(bank.gen_dccm_ram.u_ram.ram_core[(off >> 3) & 0x3FFF].value)


def dccm_word(addr: int) -> int:
    return dccm_stored(addr) & _WORD


@dataclass(frozen=True)
class Insn:
    pc: int
    word: int
    mem: int | None  # load/store address when the base register is a known constant
    target: int | None  # direct or auipc+jalr call/jump target
    value: int | None  # stored value when its register is a known constant
    arg0: int | None = None  # a0 at a jalr, when a known constant


class RomImage:
    """The loaded Boot ROM image and its symbols, decoded for flip targets."""

    def __init__(self, vmem: str | Path) -> None:
        self.path = Path(vmem)
        self.words: dict[int, int] = {}
        index = 0
        for line in self.path.read_text().split():
            if line.startswith("@"):
                index = int(line[1:], 16)
                continue
            self.words[index] = int(line, 16)
            index += 1
        self.syms = load_rom_syms(self.path.with_suffix(".sym"))
        # A static function defined in several files (simputs) has one address per file.
        self.all: dict[str, set[int]] = {}
        for line in self.path.with_suffix(".sym").read_text().splitlines():
            parts = line.split()
            if len(parts) == 3:
                self.all.setdefault(parts[2], set()).add(int(parts[0], 16))
        self._text = sorted(
            {a for addrs in self.all.values() for a in addrs if ROM_BASE <= a < ROM_HI}
        )

    def insn(self, pc: int) -> int:
        word = self.words.get((pc - ROM_BASE) // 8, 0)
        return (word >> (32 * ((pc - ROM_BASE) // 4 % 2))) & _WORD

    def find_bytes(self, needle: bytes) -> int | None:
        blob = bytearray()
        for i in range(max(self.words) + 1):
            blob += self.words.get(i, 0).to_bytes(8, "little")
        off = blob.find(needle)
        return None if off < 0 else ROM_BASE + off

    def has(self, name: str) -> bool:
        return name in self.syms

    def func(self, name: str) -> tuple[int, int]:
        lo = self.syms[name]
        hi = next((a for a in self._text if a > lo), ROM_HI)
        return lo, hi

    def scan(self, name: str) -> list[Insn]:
        """Instructions of a function with constant-tracked addresses and call targets."""
        lo, hi = self.func(name)
        return self.scan_range(lo, hi)

    def scan_range(self, lo: int, hi: int) -> list[Insn]:
        regs: dict[int, int] = {0: 0}
        out: list[Insn] = []
        for pc in range(lo, hi, 4):
            w = self.insn(pc)
            op = opcode(w)
            mem = target = value = None
            if op == OP_STORE:
                value = regs.get((w >> 20) & 0x1F)
            if op in (OP_LOAD, OP_STORE) and rs1_of(w) in regs:
                imm = imm_s(w) if op == OP_STORE else imm_i(w)
                mem = (regs[rs1_of(w)] + imm) & _WORD
            elif op == OP_JALR and rs1_of(w) in regs:
                target = (regs[rs1_of(w)] + imm_i(w)) & _WORD
            elif op == OP_JAL:
                target = (pc + imm_j(w)) & _WORD
            elif op == OP_BRANCH:
                target = (pc + imm_b(w)) & _WORD
            arg0 = regs.get(asm.A0) if op == OP_JALR else None
            out.append(Insn(pc, w, mem, target, value, arg0))
            dest = writes_rd(w)
            if op == OP_LUI:
                regs[rd_of(w)] = w & 0xFFFF_F000
            elif op == OP_AUIPC:
                regs[rd_of(w)] = (pc + (w & 0xFFFF_F000)) & _WORD
            elif op == OP_OP_IMM and funct3(w) == 0 and rs1_of(w) in regs:
                regs[rd_of(w)] = (regs[rs1_of(w)] + imm_i(w)) & _WORD
            elif dest is not None:
                regs.pop(dest, None)
            if op == OP_JALR and rd_of(w) == asm.RA:
                # A call clobbers every caller-saved register.
                for r in (1, 5, 6, 7, *range(10, 18), *range(28, 32)):
                    regs.pop(r, None)
            regs[0] = 0
        return out

    def calls(self, callee: str) -> list[int]:
        """PCs of every jalr in the image that calls callee."""
        dst = self.all[callee]
        sites = []
        bounds = self._text + [ROM_HI]
        for lo, hi in zip(bounds, bounds[1:]):
            for i in self.scan_range(lo, hi):
                if opcode(i.word) == OP_JALR and rd_of(i.word) == asm.RA and i.target in dst:
                    sites.append(i.pc)
        return sorted(set(sites))

    def stores_to(self, name: str, addr: int) -> list[int]:
        return [i.pc for i in self.scan(name) if opcode(i.word) == OP_STORE and i.mem == addr]

    def func_pcs(self, *names: str) -> set[int]:
        pcs: set[int] = set()
        for name in names:
            if self.has(name):
                lo, hi = self.func(name)
                pcs.update(range(lo, hi, 4))
        return pcs

    def owner(self, pc: int) -> str:
        best = max((a for a in self._text if a <= pc), default=None)
        return next((n for n, addrs in self.all.items() if best in addrs), "?")


def hash_bypass(img: RomImage) -> tuple[int, int]:
    """(source, target) of the jump that skips the whole HASH acceptance block.

    The source follows the START_PAYLOAD_VALIDATION status store; the target follows the
    call that prints PAYLOAD_OK. Both are found the same way in any build of oca_boot.c.
    """
    body = img.scan("rom_manifest_boot")
    text = img.find_bytes(b"PAYLOAD_OK\n\x00")
    src = [
        i.pc + 4
        for i in body
        if opcode(i.word) == OP_STORE
        and i.mem == SCRATCH_STATUS
        and i.value == STATUS_START_PAYLOAD_VALIDATION
    ]
    dst = [
        i.pc + 4
        for i in body
        if opcode(i.word) == OP_JALR and i.target in img.all["simputs"] and i.arg0 == text
    ]
    assert len(src) == 1 and len(dst) == 1, (
        f"HASH block bounds not unique in rom_manifest_boot: after the START_PAYLOAD_VALIDATION "
        f"store {[hex(p) for p in src]}, after the PAYLOAD_OK print {[hex(p) for p in dst]}"
    )
    return src[0], dst[0]


@dataclass(frozen=True)
class SelfcheckMap:
    """Branches of rom_handoff_selfcheck, found from its structure."""

    fail_block: int  # auipc of the call to selfcheck_fail
    loop_top: int
    eval_call: int  # jalr through the check table
    eval_branch: int
    seen_store: int
    compare_start: int
    counter_branch: int | None
    back_edge: int
    tally_branches: tuple[int, ...]


def selfcheck_map(img: RomImage) -> SelfcheckMap:
    body = img.scan("rom_handoff_selfcheck")
    fail_dst = img.syms["selfcheck_fail"]
    fail_jalr = next(i for i in body if opcode(i.word) == OP_JALR and i.target == fail_dst)
    fail_block = fail_jalr.pc - 4
    seen = img.syms["g_selfcheck_seen"]

    def after(pc: int) -> list[Insn]:
        return [i for i in body if i.pc > pc]

    eval_call = next(
        i
        for i in body
        if opcode(i.word) == OP_JALR
        and rd_of(i.word) == asm.RA
        and rs1_of(i.word) != asm.RA
        and i.target is None
    )
    eval_branch = next(i for i in after(eval_call.pc) if opcode(i.word) == OP_BRANCH)
    seen_store = next(
        i for i in after(eval_branch.pc) if opcode(i.word) == OP_STORE and i.mem == seen
    )
    counter = next(
        (i for i in after(seen_store.pc) if opcode(i.word) == OP_BRANCH and i.target == fail_block),
        None,
    )
    back = next(
        i
        for i in after(seen_store.pc)
        if opcode(i.word) == OP_BRANCH
        and i.target is not None
        and i.target < i.pc
        and i.target != fail_block
    )
    tally = tuple(
        i.pc for i in after(back.pc) if opcode(i.word) == OP_BRANCH and i.target == fail_block
    )
    return SelfcheckMap(
        fail_block=fail_block,
        loop_top=back.target,
        eval_call=eval_call.pc,
        eval_branch=eval_branch.pc,
        seen_store=seen_store.pc,
        compare_start=seen_store.pc + 4,
        counter_branch=counter.pc if counter is not None and counter.pc < back.pc else None,
        back_edge=back.pc,
        tally_branches=tally,
    )


class LedgerObserver(SepRomObserver):
    """SepRomObserver that also keeps every retirement at a watched PC, with its word."""

    def __init__(self, test, watch: set[int], **kwargs) -> None:
        super().__init__(test, pc_watch=frozenset(watch), **kwargs)
        self.hits: list[Retire] = []

    def record(self, t, pc, insn, exc, ecause, interrupt) -> Retire:
        r = super().record(t, pc, insn, exc, ecause, interrupt)
        if pc in self._pc_watch:
            self.hits.append(r)
        return r

    def at(self, pc: int) -> list[Retire]:
        return [r for r in self.hits if r.pc == pc]


class sep_rom_gate_ledger_base(sep_rom_observe_base):
    """Bring-up, flip helpers and halt grading for the gate-ledger leaves.

    A leaf sets ``flash_image`` to boot from SPI (else the SMC-SRAM manifest path), adds the
    PCs it needs to ``extra_watch()``, applies its fault in ``inject()`` and grades in
    ``grade()``.
    """

    flash_image: str | None = None
    efuse_from_preload = False
    max_run_cycles = 24_000_000
    observer_kwargs = {"pc_window": (ROM_BASE, ROM_HI)}

    # -- set-up ----------------------------------------------------------------

    def build_efuse_image(self):
        if self.efuse_from_preload:
            return self.select_efuse_image()
        return super().build_efuse_image()

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        return buf

    def extra_watch(self) -> set[int]:
        return set()

    async def inject(self, obs: LedgerObserver) -> None:
        """The leaf's fault; runs from bring-up and waits on the record before it acts."""

    def watch_set(self) -> set[int]:
        img = self.img
        names = [f"gate_stamp_{g}" for g in GATES] + list(CHECKS)
        names += ["gate_ledger_reset", "rom_handoff_selfcheck", "selfcheck_fail"]
        pcs = img.func_pcs(*names)
        if img.has("rom_err_fail_ext"):
            pcs.add(img.syms["rom_err_fail_ext"])
        return pcs | self.extra_watch()

    async def run_scenario(self) -> None:
        from env.sep_chk_log import SepChkLog

        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        rom_hex = cocotb.plusargs.get("sep_boot_rom_hex")
        self.img = RomImage(rom_hex)
        self.log_image_identity("boot_rom", rom_hex)
        self.write_efuse_image(self.build_efuse_image())
        flash = None
        if self.flash_image is not None:
            from ocah_spi_vip import OcahSpiFlash

            dut = cocotb.top
            cocotb.start_soon(esrc_noise_task(dut, logger=self.logger))
            flash = OcahSpiFlash(
                dut.spi_cs_n_o,
                dut.spi_sck_o,
                mosi=dut.spi_mosi_o,
                miso=dut.spi_miso_i,
                name="sep_rom_boot_flash",
            )
            self.log_image_identity("flash", self.flash_image)
            image = bytearray(Path(self.flash_image).read_bytes())
            flash.preload(bytes(self.mutate_flash_image(image)))
            await flash.start()
        self.obs = LedgerObserver(self, self.watch_set(), **self.observer_kwargs).start()
        stim = cocotb.start_soon(self.inject(self.obs))
        await self.bring_up_cpu_boot(ROM_BASE >> 1, run_pulse_cycles=40)
        reached = await self.obs.run_until(self.done, self.max_run_cycles)
        stim.cancel()
        await self.obs.stop()
        if flash is not None:
            await flash.stop()
        self.chk.ctrl("RUN-REACHED", reached, cycles=self.obs.cycle, retired=self.obs.retired)
        self.grade(self.obs, self.chk)
        self.chk.finish()

    # -- stimulus helpers ------------------------------------------------------

    async def wait_line(self, obs: SepRomObserver, marker: str, after: int = -1) -> int:
        while True:
            t = next((t for t, line in obs.console if marker in line and t > after), None)
            if t is not None:
                return t
            await RisingEdge(cocotb.top.clk_i)

    async def wait_hit(self, obs: LedgerObserver, pc: int, count: int = 1) -> Retire:
        while len(obs.at(pc)) < count:
            await RisingEdge(cocotb.top.clk_i)
        return obs.at(pc)[count - 1]

    async def patch(self, edits: dict[int, int]) -> None:
        """Replace ROM instructions, one hook pulse per 64-bit ROM word."""
        words: dict[int, int] = {}
        for pc, new in edits.items():
            off = pc - ROM_BASE
            words[off // 8] = words.get(off // 8, 0) ^ (
                (self.img.insn(pc) ^ new) << (32 * (off // 4 % 2))
            )
            self.chk.info(
                "ROM-PATCH",
                pc=f"0x{pc:08x}",
                fn=self.img.owner(pc),
                old=f"0x{self.img.insn(pc):08x}",
                new=f"0x{new:08x}",
            )
        for index, mask in sorted(words.items()):
            await rom_flip(cocotb.top, index, mask)

    async def dccm_flip(self, addr: int, data_mask: int) -> tuple[int, int]:
        """Flip data bits of a DCCM word with a consistent ECC; returns (before, after)."""
        before = dccm_stored(addr)
        await tcm_flip(cocotb.top, addr, ecc_consistent_mask(data_mask))
        after = dccm_stored(addr)
        self.chk.info(
            "DCCM-FLIP",
            addr=f"0x{addr:08x}",
            before=f"0x{before:010x}",
            after=f"0x{after:010x}",
        )
        return before, after

    # -- grading helpers -------------------------------------------------------

    def retired_as(self, obs: LedgerObserver, pc: int, word: int) -> list[Retire]:
        return [r for r in obs.at(pc) if r.insn == word and not (r.exc or r.interrupt)]

    def stamp_stores(self, gate: str) -> tuple[int, int]:
        """PCs of the gate_ok and gate_inv stores of one gate's stamp."""
        name = f"gate_stamp_{gate}"
        ok = self.img.stores_to(name, self.img.syms["g_gate_ok"])
        inv = self.img.stores_to(name, self.img.syms["g_gate_inv"])
        assert len(ok) == 1 and len(inv) == 1, f"{name}: gate_ok stores {ok}, gate_inv stores {inv}"
        return ok[0], inv[0]

    def stamps_retired(self, obs: LedgerObserver, gate: str, since: int = -1) -> bool:
        ok, inv = self.stamp_stores(gate)
        return any(r.t_ps > since for r in obs.at(ok)) and any(r.t_ps > since for r in obs.at(inv))

    def last_reset_t(self, obs: LedgerObserver) -> int:
        lo, _ = self.img.func("gate_ledger_reset")
        hits = obs.at(lo)
        return hits[-1].t_ps if hits else -1

    def ledger_readback(self) -> tuple[int, int]:
        return dccm_word(self.img.syms["g_gate_ok"]), dccm_word(self.img.syms["g_gate_inv"])

    def halt_site(self, obs: LedgerObserver) -> tuple[str, int | None, str]:
        """(kind, branch pc, last check) of the self-check branch that called selfcheck_fail.

        kind is eval, counter, tally or none.
        """
        if not self.img.has("rom_handoff_selfcheck"):
            return "none", None, ""
        m = selfcheck_map(self.img)
        fail_lo, _ = self.img.func("selfcheck_fail")
        entry = next((r for r in obs.hits if r.pc == fail_lo), None)
        if entry is None:
            return "none", None, ""
        sc_lo, sc_hi = self.img.func("rom_handoff_selfcheck")
        before = [r for r in obs.hits if r.t_ps < entry.t_ps]
        branch = next(
            (
                r
                for r in reversed(before)
                if sc_lo <= r.pc < sc_hi and r.pc != m.fail_block and r.pc != m.fail_block + 4
            ),
            None,
        )
        check_pcs = {n: self.img.func_pcs(n) for n in CHECKS}
        last_check = next(
            (n for r in reversed(before) for n, pcs in check_pcs.items() if r.pc in pcs), ""
        )
        if branch is None:
            return "none", None, last_check
        kind = (
            "eval"
            if branch.pc == m.eval_branch
            else "counter"
            if branch.pc == m.counter_branch
            else "tally"
            if branch.pc in m.tally_branches
            else f"other:{self.img.owner(branch.pc)}"
        )
        return kind, branch.pc, last_check

    def grade_halt(self, obs: LedgerObserver, chk, *, kind: str, check: str = "") -> None:
        """The halt contract shared by every negative leaf."""
        halt_t = obs.status_t(STATUS_HALT_F004)
        chk.ok(
            "HALT-F004",
            halt_t is not None and obs.verdict_pass() is False,
            status_f004_ps=halt_t if halt_t is not None else -1,
            verdict_pass=obs.verdict_pass(),
            last_status=f"0x{obs.statuses()[-1]:08x}" if obs.status else "none",
        )
        words = obs.statuses()
        chk.ok(
            "NO-STARTING-BL1",
            halt_t is not None
            and STATUS_STARTING_BL1 not in words
            and STATUS_EXEC_IMAGE not in words,
            status_records=len(words),
        )
        prestart = obs.status_t(STATUS_PRESTART_DONE)
        pmp = obs.csr_writes(CSR_PMPCFG0, CSR_PMPCFG0 + 0x3F + 0x10)
        cold = [r for r in pmp if prestart is not None and r.t_ps < prestart]
        late = [r for r in pmp if prestart is None or r.t_ps >= prestart]
        chk.ctrl("PMP-RECORD-LIVE", bool(cold), cold_pmp_writes=len(cold))
        chk.ok(
            "NO-BL1-PMP-WRITE",
            prestart is not None and not late,
            late=[f"0x{r.pc:08x}:0x{decode_csr(r.insn).csr:03x}" for r in late],
        )
        fail_entry = self.img.syms.get("rom_err_fail_ext")
        halted = [r for r in obs.hits if r.pc == fail_entry]
        chk.ctrl("HALT-PATH-RETIRED", bool(halted), rom_err_fail_ext_hits=len(halted))
        chk.ok(
            "NO-BL1-FETCH",
            bool(halted) and not obs.outside_window and obs.post_mret is None and not obs.pre_mret,
            outside_rom=[f"0x{r.pc:08x}" for r in obs.outside_window[:4]],
            mret_retired=bool(obs.pre_mret),
        )
        got_kind, branch, last_check = self.halt_site(obs)
        chk.ok(
            "HALT-SITE",
            got_kind == kind and (not check or last_check == check),
            kind=got_kind,
            want_kind=kind,
            branch=f"0x{branch:08x}" if branch is not None else "none",
            last_check=last_check or "none",
            want_check=check or "any",
        )
