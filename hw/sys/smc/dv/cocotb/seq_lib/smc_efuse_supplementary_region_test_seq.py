# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The supplementary fuse region of the reference SMC wrapper.

Sources: architecture.adoc (Supplementary Fuse Region: Sensing and Export, Supplementary Locks,
Access Path), memmap.adoc (the supplementary fuse window), smc_efuse_map.rdl (SUPPLEMENTARY_LOCKS),
efuse_interface_ctrl.rdl (EFUSE_PROGRAM_ADDR, EFUSE_READ_ADDR, the request and address errors);
the region of the reference wrappers is the one architecture.adoc describes (128 words in lock
regions ending at words 64, 96 and 128).

The image the testcase writes carries a seeded pattern in the 128 supplementary words (image words
64 to 191) and zero in every harness word, so no lock is set when the sense completes. ``shadow``
is the per-word model of the supplementary shadow file: it starts from the image and changes only
when a write to an unlocked region lands.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import efuse_ifc_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import EFUSE_BLOCKED_READ_DATA

_WORD_MASK = 0xFFFF_FFFF
_LOCKED_DATA = EFUSE_BLOCKED_READ_DATA
_RESP_OKAY = 0
_RESP_DECERR = 3
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_SENSE_BOUND_CYCLES = 200_000
_POLL_BOUND = 10_000
_IRQ_DRAIN = 8

MAP_WORDS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SIZE") // 4
#: The supplementary region of the reference wrappers, as architecture.adoc states it: "128 words in
#: three lock regions" (Configuration) whose LOCK_REGION_END "entries are 64, 96 and 128"
#: (Supplementary Locks), the window "4 x WORDS bytes" (Region Size) and the fuse bits starting
#: "at bit 2048, directly after the 2 Kbit harness map" (Sensing and Export).
SUPP_WORDS = 128
REGION_END = (64, 96, 128)
SUPP_BIT_BASE = 2048
IMAGE_WORDS = MAP_WORDS + SUPP_WORDS

SUPP_WINDOW = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_FUSE_BASE_ADDR")
SUPP_LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SUPPLEMENTARY_LOCKS_BASE_ADDR")
STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
PROGRAM_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR")
READ_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR")
PROGRAM_ADDR = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_ADDR_BASE_ADDR")
READ_ADDR = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_ADDR_BASE_ADDR")
READ_DATA = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_INTERFACE_READ_DATA_BASE_ADDR")


def _f(reg: str, field: str) -> int:
    return efuse_ifc_u32(f"EFUSE_INTERFACE_CTRL__{reg}__{field}_bm")


REQ_ERROR = _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_REQ_ERROR")
PROGRAM_ADDR_ERROR = _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_PROGRAM_ADDR_ERROR")
READ_ADDR_ERROR = _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_READ_ADDR_ERROR")
REQ_ERROR_CLEAR = _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_REQ_ERROR_CLEAR")
PROGRAM_ADDR_ERROR_CLEAR = _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_PROGRAM_ADDR_ERROR_CLEAR")
READ_ADDR_ERROR_CLEAR = _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_READ_ADDR_ERROR_CLEAR")
ERRORS = REQ_ERROR | PROGRAM_ADDR_ERROR | READ_ADDR_ERROR
PROG_DATA = _f("EFUSE_PROGRAM_CTRL", "EFUSE_DATA")
PROG_GO = _f("EFUSE_PROGRAM_CTRL", "EFUSE_PROGRAM_GO")
PROG_RB = _f("EFUSE_PROGRAM_CTRL", "EFUSE_PROGRAM_READ_BACK")
PROG_EN = _f("EFUSE_PROGRAM_CTRL", "PROGRAM_ENABLE")
PROG_BUSY = _f("EFUSE_PROGRAM_CTRL", "PROGRAM_BUSY")
PROG_DONE = _f("EFUSE_PROGRAM_CTRL", "PROGRAM_DONE")
PROG_STATUS = _f("EFUSE_PROGRAM_CTRL", "PROGRAM_STATUS")
READ_GO = _f("EFUSE_READ_CTRL", "EFUSE_READ_GO")
READ_EN = _f("EFUSE_READ_CTRL", "READ_ENABLE")
READ_BUSY = _f("EFUSE_READ_CTRL", "READ_BUSY")
READ_DONE = _f("EFUSE_READ_CTRL", "READ_DONE")
READ_STATUS = _f("EFUSE_READ_CTRL", "READ_STATUS")

#: Fuse-command request valids of the program and read interfaces (tb_top.sv): high while a
#: command is issued to the SHIM, never for a start the guard or the address bound refuses.
PROGRAM_PROBE = "tb_efuse_program_req_valid"
READ_PROBE = "tb_efuse_read_req_valid"
#: Read-address valid of smc_external_req_o (tb_top.sv): a window read the shadow does not
#: serve leaves the SMC here.
EXTERNAL_AR_PROBE = "tb_axil_external_arvalid"
#: Word of each lock region the guard commands target (two past the region's first word).
GUARD_OFFSET = 2
GUARD_BIT = 7
#: Supplementary word and bit the leaf programs (region 1); the testcase clears that bit in the
#: image so the program is a 0-to-1 transition.
PROG_WORD = 70
PROG_BIT = 5
#: Supplementary words at the region boundaries: (first word, last word) per lock region.
REGION_WORDS = tuple((0 if r == 0 else REGION_END[r - 1], REGION_END[r] - 1) for r in range(3))


def region_of(word: int) -> int:
    for r, end in enumerate(REGION_END):
        if word < end:
            return r
    raise ValueError(f"supplementary word {word} is past the region")


def write_lock_bit(region: int) -> int:
    return 1 << (2 * region)


def read_lock_bit(region: int) -> int:
    return 1 << (2 * region + 1)


def supp_addr(word: int) -> int:
    return SUPP_WINDOW + 4 * word


def supp_bit(word: int, bit: int = 0) -> int:
    return SUPP_BIT_BASE + 32 * word + bit


class smc_efuse_supplementary_region_test_seq(SmcCsrSeq):
    """Sense, window, shadow writes, program and read, lock pairs, guard and address errors."""

    def __init__(self, name: str = "smc_efuse_supplementary_region_test_seq") -> None:
        super().__init__(name)
        self.image: tuple[int, ...] = ()
        self.seed = 1
        self.access_floor = 0
        self.shadow: list[int] = []
        self.locks_model = 0
        self._calls = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []
        self._used: set[int] = set()
        #: (label, kind, bit, outcome) of every guard command the leaf issued.
        self._guard: list[tuple[str, str, int, str]] = []
        #: Pattern draws; seeded apart from the image so a written pattern is never an image word.
        self._rnd = random.Random(1)
        self._last_result = None

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        self._events.append(("chk", chk_id))
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _sig(name: str):
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        return getattr(dut, name)

    def _sig_int(self, name: str) -> int:
        value = self._sig(name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _sense_state(self) -> str:
        return (
            f"tb_fuse_sense_done={self._sig_int('tb_fuse_sense_done')},"
            f"tb_fuse_reset_n={self._sig_int('tb_fuse_reset_n')}"
        )

    async def _sense_wait(self, label: str) -> None:
        try:
            await self.wait_fuse_sense_done(_SENSE_BOUND_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}; {self._sense_state()}") from exc
        self._waits.append((label, _SENSE_BOUND_CYCLES, self._sense_state()))

    async def _count_irq_edges_during(self, label: str, coro) -> int:
        """Rising edges of tb_efuse_locked_access_irq during ``coro``; 0 before and after."""
        pin = self._sig("tb_efuse_locked_access_irq")
        assert int(pin.value) == 0, f"{label}: tb_efuse_locked_access_irq is 1 before the access"
        edges = 0

        async def _watch() -> None:
            nonlocal edges
            while True:
                await RisingEdge(pin)
                edges += 1

        task = cocotb.start_soon(_watch())
        try:
            result = await coro
            await ClockCycles(cocotb.top.clk_periph_i, _IRQ_DRAIN)
        finally:
            task.kill()
        assert int(pin.value) == 0, (
            f"{label}: tb_efuse_locked_access_irq is still 1 {_IRQ_DRAIN} periph clocks after "
            "the access; the locked-access interrupt is a pulse for the access phase"
        )
        self._last_result = result
        return edges

    async def _count_rises_during(self, probe: str, coro) -> int:
        """Rising edges of ``probe`` sampled on clk_smc_i during ``coro``."""
        pin = self._sig(probe)
        clk = cocotb.top.clk_smc_i
        rises = 0
        prev = 0

        async def _watch() -> None:
            nonlocal rises, prev
            while True:
                await RisingEdge(clk)
                cur = int(pin.value) if pin.value.is_resolvable else 0
                if cur and not prev:
                    rises += 1
                prev = cur

        task = cocotb.start_soon(_watch())
        try:
            self._last_result = await coro
        finally:
            task.kill()
        return rises

    async def _count_command_cycles_during(self, probe: str, coro) -> int:
        """clk_smc_i cycles with ``probe`` (a fuse-command request valid) high during ``coro``."""
        pin = self._sig(probe)
        clk = cocotb.top.clk_smc_i
        hits = 0

        async def _watch() -> None:
            nonlocal hits
            while True:
                await RisingEdge(clk)
                if pin.value.is_resolvable and int(pin.value):
                    hits += 1

        task = cocotb.start_soon(_watch())
        try:
            self._last_result = await coro
        finally:
            task.kill()
        return hits

    # --- access ---------------------------------------------------------
    async def _rd(self, label: str, addr: int, expected: int) -> int:
        self._calls += 1
        return await self.csr_read(label, addr, expected=expected) & _WORD_MASK

    async def _wr(self, label: str, addr: int, data: int) -> None:
        self._calls += 1
        await self.csr_write(label, addr, data)

    async def _rd_ok(self, label: str, addr: int) -> int:
        """A read that must complete OKAY; the scoreboard rejects an error response."""
        self._calls += 1
        return await self.csr_read(label, addr) & _WORD_MASK

    async def _rd_any(self, label: str, addr: int) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._calls += 1
        assert item.resp_code is not None, f"{label}: the read got no response"
        return item.rdata & _WORD_MASK, item.resp_code

    async def _wr_any(self, label: str, addr: int, data: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._calls += 1
        assert item.resp_code is not None, f"{label}: the write got no response"
        return item.resp_code

    async def _poll(self, label: str, addr: int, pred) -> int:
        clk = cocotb.top.clk_smc_i
        for n in range(_POLL_BOUND):
            await RisingEdge(clk)
            value = await self._rd_ok(f"{label}_{n}", addr)
            if pred(value):
                self._waits.append((label, _POLL_BOUND, f"polls={n + 1} value=0x{value:08x}"))
                return value
        raise AssertionError(f"{label}: 0x{addr:08x} never satisfied the poll in {_POLL_BOUND}")

    def _fresh(self) -> int:
        while True:
            value = self._rnd.getrandbits(32)
            if value in (0, _WORD_MASK, _LOCKED_DATA) or value in self._used:
                continue
            self._used.add(value)
            return value

    async def _read_supp_locks(self, label: str) -> int:
        return await self._rd(label, SUPP_LOCKS, self.locks_model)

    async def _set_supp_locks(self, label: str, bits: int) -> int:
        await self._wr(label, SUPP_LOCKS, bits)
        self.locks_model |= bits
        return await self._read_supp_locks(f"{label}_RB")

    async def _program(self, label: str, bit: int) -> int:
        """Program fuse ``bit`` through the program interface; returns PROGRAM_CTRL at done."""
        await self._wr(f"{label}_ADDR", PROGRAM_ADDR, bit)
        await self._wr(f"{label}_GO", PROGRAM_CTRL, PROG_DATA | PROG_GO | PROG_RB | PROG_EN)
        ctrl = await self._poll(
            f"{label}_DONE", PROGRAM_CTRL, lambda v: bool(v & PROG_DONE) and not v & PROG_BUSY
        )
        await self._wr(f"{label}_OFF", PROGRAM_CTRL, 0)
        return ctrl

    async def _program_start(self, label: str, bit: int) -> tuple[int, int]:
        """Start a program of ``bit``: (EFUSE_INTERFACE_CTRL_STATUS, PROGRAM_CTRL at done)."""
        await self._wr(f"{label}_ADDR", PROGRAM_ADDR, bit)
        await self._wr(f"{label}_GO", PROGRAM_CTRL, PROG_DATA | PROG_GO | PROG_RB | PROG_EN)
        ctrl = await self._poll(
            f"{label}_DONE", PROGRAM_CTRL, lambda v: bool(v & PROG_DONE) and not v & PROG_BUSY
        )
        await self._wr(f"{label}_OFF", PROGRAM_CTRL, 0)
        return await self._rd_ok(f"{label}_STATUS", STATUS), ctrl

    async def _fuse_read(self, label: str, bit: int) -> tuple[int, int]:
        """Read the fuse word at ``bit`` through the read interface: (READ_CTRL at done, data)."""
        await self._wr(f"{label}_PROG_OFF", PROGRAM_CTRL, 0)
        await self._wr(f"{label}_ADDR", READ_ADDR, bit)
        await self._wr(f"{label}_EN", READ_CTRL, READ_EN)
        await self._wr(f"{label}_GO", READ_CTRL, READ_EN | READ_GO)
        ctrl = await self._poll(
            f"{label}_DONE", READ_CTRL, lambda v: bool(v & READ_DONE) and not v & READ_BUSY
        )
        data = await self._rd_ok(f"{label}_DATA", READ_DATA)
        await self._wr(f"{label}_OFF", READ_CTRL, 0)
        return ctrl, data

    async def _read_start(self, label: str, bit: int) -> tuple[int, int]:
        """Start a read of ``bit``: (EFUSE_INTERFACE_CTRL_STATUS, READ_CTRL at done)."""
        await self._wr(f"{label}_PROG_OFF", PROGRAM_CTRL, 0)
        await self._wr(f"{label}_ADDR", READ_ADDR, bit)
        await self._wr(f"{label}_EN", READ_CTRL, READ_EN)
        await self._wr(f"{label}_GO", READ_CTRL, READ_EN | READ_GO)
        ctrl = await self._poll(
            f"{label}_DONE", READ_CTRL, lambda v: bool(v & READ_DONE) and not v & READ_BUSY
        )
        await self._wr(f"{label}_OFF", READ_CTRL, 0)
        return await self._rd_ok(f"{label}_STATUS", STATUS), ctrl

    async def _guard_cmd(self, label: str, kind: str, bit: int, refused: bool) -> None:
        """Issue a ``kind`` ("program" or "read") at ``bit`` and grade the guard's decision.

        Refused: no fuse-command cycle, done and status set, efuse_req_error latched and no
        address error; the error is then cleared (it gates both enables while set). Accepted:
        at least one fuse-command cycle, done with status 0 and no error bit.
        """
        if kind == "program":
            probe, start, done, stat = PROGRAM_PROBE, self._program_start, PROG_DONE, PROG_STATUS
        else:
            probe, start, done, stat = READ_PROBE, self._read_start, READ_DONE, READ_STATUS
        hits = await self._count_command_cycles_during(probe, start(label, bit))
        status, ctrl = self._last_result
        if refused:
            assert hits == 0, f"{label}: the refused {kind} at bit {bit} issued {hits} cycles"
            assert ctrl & (done | stat) == done | stat, (
                f"{label}: refused {kind} at bit {bit}: CTRL 0x{ctrl:08x} lacks done and status"
            )
            assert status & ERRORS == REQ_ERROR, (
                f"{label}: refused {kind} at bit {bit}: status 0x{status:08x}, expected "
                f"efuse_req_error alone"
            )
            await self._clear_errors(f"{label}_CLEAR")
        else:
            assert hits > 0, f"{label}: the accepted {kind} at bit {bit} issued no fuse command"
            assert ctrl & (done | stat) == done, (
                f"{label}: accepted {kind} at bit {bit}: CTRL 0x{ctrl:08x}, expected done, status 0"
            )
            assert status & ERRORS == 0, (
                f"{label}: accepted {kind} at bit {bit}: status 0x{status:08x} reports an error"
            )
        self._guard.append((label, kind, bit, "refused" if refused else "accepted"))

    async def _clear_errors(self, label: str) -> int:
        await self._wr(
            label, STATUS, REQ_ERROR_CLEAR | PROGRAM_ADDR_ERROR_CLEAR | READ_ADDR_ERROR_CLEAR
        )
        status = await self._rd_ok(f"{label}_RB", STATUS)
        assert status & ERRORS == 0, f"{label}: status 0x{status:08x} keeps an error after clear"
        return status

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        image = self.image
        assert len(image) == IMAGE_WORDS, f"image holds {len(image)} words, not {IMAGE_WORDS}"
        assert all(w == 0 for w in image[:MAP_WORDS]), "the image sets a harness word"
        assert image[MAP_WORDS + PROG_WORD] & (1 << PROG_BIT) == 0, "the program bit is set"
        self._rnd = random.Random(self.seed ^ 0x5A5A_0001)
        self.shadow = list(image[MAP_WORDS:])
        self.locks_model = 0
        assert SUPP_BIT_BASE == 32 * MAP_WORDS, (
            f"the architecture's supplementary base, bit {SUPP_BIT_BASE}, is not the end of the "
            f"{MAP_WORDS}-word harness map"
        )
        assert SUPP_WINDOW + 4 * SUPP_WORDS <= SUPP_WINDOW + smc_addr(
            "SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_FUSE_SIZE"
        ), "the window does not fit the fuse slot"

        # S1: sense; the 128 supplementary words read through the window; SUPPLEMENTARY_LOCKS 0
        await self._sense_wait("sense")
        for word in range(SUPP_WORDS):
            await self._rd(f"S1_RD_{word}", supp_addr(word), self.shadow[word])
        await self._read_supp_locks("S1_LOCKS")
        self._done("S1")
        self._chk(
            "CHK-SUPP-SENSE-WORDS",
            "after the sense all %d supplementary words read through the window at 0x%08x equal "
            "image words %d..%d (first 0x%08x, last 0x%08x); SUPPLEMENTARY_LOCKS reads 0",
            SUPP_WORDS,
            SUPP_WINDOW,
            MAP_WORDS,
            IMAGE_WORDS - 1,
            self.shadow[0],
            self.shadow[-1],
        )

        # S2: the first word past the window is not served by the shadow (the testcase registers
        # the address with the AXI monitor: the reference integration's terminator answers DECERR)
        past = supp_addr(SUPP_WORDS)
        ar_in = await self._count_rises_during(
            EXTERNAL_AR_PROBE, self._rd("S2_IN", supp_addr(SUPP_WORDS - 1), self.shadow[-1])
        )
        assert ar_in == 0, (
            f"S2: the in-window read of word {SUPP_WORDS - 1} raised {EXTERNAL_AR_PROBE} "
            f"{ar_in} times; the shadow serves it"
        )
        item = SmcSysAxiItem("rd_S2_PAST")
        item.op = SmcSysAxiOp.READ
        item.addr = past
        item.length = 4
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = _RESP_DECERR

        async def _past() -> None:
            await self.start_item(item)
            await self.finish_item(item)

        ar_past = await self._count_rises_during(EXTERNAL_AR_PROBE, _past())
        self.accesses += 1
        self._calls += 1
        assert ar_past >= 1, (
            f"S2: the read of 0x{past:08x} never raised {EXTERNAL_AR_PROBE}; it did not leave "
            "on smc_external_req_o"
        )
        assert item.resp_code == _RESP_DECERR, (
            f"S2: 0x{past:08x} answered resp={item.resp_code}, expected DECERR from the terminator"
        )
        past_data = item.rdata
        self._done("S2")
        self._chk(
            "CHK-SUPP-WINDOW-END",
            "the first word past the %d-byte window, 0x%08x, is not served by the shadow: it "
            "raised %s %d time(s), where the window's last word raised it %d times, and answers "
            "DECERR (rdata 0x%08x) from the external terminator",
            4 * SUPP_WORDS,
            past,
            EXTERNAL_AR_PROBE,
            ar_past,
            ar_in,
            past_data & _WORD_MASK,
        )

        # S3: positive control, one word per region accepts a new pattern
        for region, (first, _last) in enumerate(REGION_WORDS):
            word = first + 1
            value = self._fresh()
            await self._wr(f"S3_WR_{region}", supp_addr(word), value)
            self.shadow[word] = value
            await self._rd(f"S3_RB_{region}", supp_addr(word), value)
        self._done("S3")
        self._chk(
            "CHK-SUPP-SHADOW-WRITE",
            "with SUPPLEMENTARY_LOCKS 0 a new pattern written to word %d, %d and %d landed and "
            "read back",
            *[first + 1 for first, _last in REGION_WORDS],
        )

        # S4: program one supplementary bit and read the word back through the read interface
        bit = supp_bit(PROG_WORD, PROG_BIT)
        hits_p = await self._count_command_cycles_during(
            PROGRAM_PROBE, self._program("S4_PROG", bit)
        )
        ctrl = self._last_result
        assert ctrl & PROG_STATUS == 0, f"S4: program_status 1 (PROGRAM_CTRL=0x{ctrl:08x})"
        assert hits_p > 0, f"S4: {PROGRAM_PROBE} never rose during the accepted program"
        hits_r = await self._count_command_cycles_during(
            READ_PROBE, self._fuse_read("S4_READ", supp_bit(PROG_WORD))
        )
        rctrl, data = self._last_result
        assert rctrl & READ_STATUS == 0, f"S4: read_status 1 (READ_CTRL=0x{rctrl:08x})"
        assert hits_r > 0, f"S4: {READ_PROBE} never rose during the accepted read"
        expected = image[MAP_WORDS + PROG_WORD] | (1 << PROG_BIT)
        assert data == expected, (
            f"S4: fuse word {PROG_WORD} reads 0x{data:08x} after programming bit {PROG_BIT}, "
            f"expected 0x{expected:08x}"
        )
        status = await self._rd_ok("S4_STATUS", STATUS)
        assert status & ERRORS == 0, f"S4: status 0x{status:08x} reports an error"
        # the last supplementary word is inside the bound: a read of it is issued, no error
        await self._guard_cmd("S4_LAST_READ", "read", supp_bit(SUPP_WORDS - 1), refused=False)
        window = await self._rd_ok("S4_WINDOW", supp_addr(PROG_WORD))
        self._done("S4")
        self._chk(
            "CHK-SUPP-PROGRAM-READ",
            "EFUSE_PROGRAM_ADDR=%d (word %d bit %d) programmed with status 0 and %d program "
            "command cycles; EFUSE_READ_ADDR=%d returned 0x%08x = image word | bit after %d read "
            "command cycles (the live controls of the command probes); no request or address "
            "error; the shadow word reads 0x%08x until the next sense (measured, not compared)",
            bit,
            PROG_WORD,
            PROG_BIT,
            hits_p,
            supp_bit(PROG_WORD),
            data,
            hits_r,
            window,
        )

        # S5: write locks then read locks, region by region, with the neighbour open
        rejected = 0
        irq_edges = 0
        for region, (first, last) in enumerate(REGION_WORDS):
            await self._set_supp_locks(f"S5_WLOCK_{region}", write_lock_bit(region))
            for word in (first, last):
                edges = await self._count_irq_edges_during(
                    f"S5_WLOCKED_{word}",
                    self._wr_any(f"S5_WLOCKED_{word}", supp_addr(word), self._fresh()),
                )
                assert edges >= 1, f"S5: no locked-access interrupt on the write to word {word}"
                assert self._last_result == _RESP_OKAY, (
                    f"S5: the write to write-locked word {word} answered resp="
                    f"{self._last_result}, expected OKAY"
                )
                irq_edges += edges
                await self._rd(f"S5_HELD_{word}", supp_addr(word), self.shadow[word])
                rejected += 1
            # guard: only write locks 0..region are set
            gword = first + GUARD_OFFSET
            await self._guard_cmd(
                f"S5_GP_{region}", "program", supp_bit(gword, GUARD_BIT), refused=True
            )
            await self._guard_cmd(f"S5_GR_{region}", "read", supp_bit(gword), refused=False)
            if region + 1 < len(REGION_WORDS):
                nword = REGION_WORDS[region + 1][0] + GUARD_OFFSET
                await self._guard_cmd(
                    f"S5_GPN_{region}", "program", supp_bit(nword, GUARD_BIT), refused=False
                )
            if region + 1 < len(REGION_WORDS):
                nxt = REGION_WORDS[region + 1][0]
                value = self._fresh()
                await self._wr(f"S5_NB_WR_{nxt}", supp_addr(nxt), value)
                self.shadow[nxt] = value
                await self._rd(f"S5_NB_RB_{nxt}", supp_addr(nxt), value)
        hidden = 0
        for region, (first, last) in enumerate(REGION_WORDS):
            await self._set_supp_locks(f"S5_RLOCK_{region}", read_lock_bit(region))
            for word in (first, last):
                edges = await self._count_irq_edges_during(
                    f"S5_RLOCKED_{word}", self._rd_any(f"S5_RLOCKED_{word}", supp_addr(word))
                )
                data, resp = self._last_result
                assert edges >= 1, f"S5: no locked-access interrupt on the read of word {word}"
                assert resp == _RESP_OKAY and data == _LOCKED_DATA, (
                    f"S5: read-locked word {word} reads 0x{data:08x} resp={resp}, expected "
                    f"0x{_LOCKED_DATA:08x} with OKAY"
                )
                irq_edges += edges
                hidden += 1
            # guard: every write lock and read locks 0..region are set
            gword = first + GUARD_OFFSET
            await self._guard_cmd(f"S5_GRL_{region}", "read", supp_bit(gword), refused=True)
            # the region's last word is still in it, the next region's first word is not
            await self._guard_cmd(f"S5_GRE_{region}", "read", supp_bit(last), refused=True)
            if region + 1 < len(REGION_WORDS):
                nfirst = REGION_WORDS[region + 1][0]
                await self._guard_cmd(f"S5_GRN_{region}", "read", supp_bit(nfirst), refused=False)
            if region + 1 < len(REGION_WORDS):
                nxt = REGION_WORDS[region + 1][0]
                await self._rd(f"S5_NB_RD_{nxt}", supp_addr(nxt), self.shadow[nxt])
        self._done("S5")
        self._chk(
            "CHK-SUPP-WRITE-LOCK",
            "SUPPLEMENTARY_LOCKS=0x%x: the first and last word of each region (%s) rejected a new "
            "pattern and kept their value, %d words; the next region's first word accepted a "
            "write while its neighbour was locked",
            self.locks_model,
            REGION_WORDS,
            rejected,
        )
        self._chk(
            "CHK-SUPP-READ-LOCK",
            "SUPPLEMENTARY_LOCKS=0x%x: the first and last word of each region read 0x%08x with "
            "OKAY, %d words; the next region's first word still read its value while its "
            "neighbour was read-locked",
            self.locks_model,
            _LOCKED_DATA,
            hidden,
        )
        self._chk(
            "CHK-SUPP-LOCK-IRQ",
            "tb_efuse_locked_access_irq pulsed on every locked access: %d rising edges over %d "
            "rejected writes and %d hidden reads, 0 before and after each",
            irq_edges,
            rejected,
            hidden,
        )

        # S6: with every region write- and read-locked, the guard refuses a program and a read
        await self._clear_errors("S6_CLEAR0")
        await self._guard_cmd("S6_PROG", "program", supp_bit(PROG_WORD, PROG_BIT + 1), refused=True)
        await self._guard_cmd("S6_READ", "read", supp_bit(PROG_WORD), refused=True)
        refused = [g for g in self._guard if g[3] == "refused"]
        accepted = [g for g in self._guard if g[3] == "accepted"]
        assert len(refused) == 11 and len(accepted) == 8, (
            f"guard commands: {len(refused)} refused, {len(accepted)} accepted, expected 11 and 8"
        )
        self._done("S6")
        self._chk(
            "CHK-SUPP-GUARD",
            "the guard decided each command by its own region's SUPPLEMENTARY_LOCKS pair: "
            "refused (0 fuse-command cycles, done and status set, efuse_req_error alone, cleared "
            "after) %s; accepted (fuse command issued, done with status 0, no error) %s",
            " ".join(f"{label}:{kind}@{bit}" for label, kind, bit, _o in refused),
            " ".join(f"{label}:{kind}@{bit}" for label, kind, bit, _o in accepted),
        )

        # S7: commands at the first bit past the region set the address errors, no fuse command
        end_bit = supp_bit(SUPP_WORDS)
        hits_p = await self._count_command_cycles_during(
            PROGRAM_PROBE, self._program_start("S7_PROG", end_bit)
        )
        status_p, ctrl_p = self._last_result
        assert status_p & ERRORS == PROGRAM_ADDR_ERROR, (
            f"S7: program at bit {end_bit}: status 0x{status_p:08x}, expected "
            "efuse_program_addr_error alone"
        )
        assert ctrl_p & (PROG_DONE | PROG_STATUS) == PROG_DONE | PROG_STATUS, (
            f"S7: program at bit {end_bit}: PROGRAM_CTRL 0x{ctrl_p:08x} lacks done and status"
        )
        assert hits_p == 0, (
            f"S7: the out-of-range program issued a fuse command for {hits_p} cycles"
        )
        hits_r = await self._count_command_cycles_during(
            READ_PROBE, self._read_start("S7_READ", end_bit)
        )
        status_r, ctrl_r = self._last_result
        assert status_r & ERRORS == PROGRAM_ADDR_ERROR | READ_ADDR_ERROR, (
            f"S7: read at bit {end_bit}: status 0x{status_r:08x}, expected the read address "
            "error next to the program one and no request error"
        )
        assert ctrl_r & (READ_DONE | READ_STATUS) == READ_DONE | READ_STATUS, (
            f"S7: read at bit {end_bit}: READ_CTRL 0x{ctrl_r:08x} lacks done and status"
        )
        assert hits_r == 0, f"S7: the out-of-range read issued a fuse command for {hits_r} cycles"
        await self._clear_errors("S7_CLEAR")
        self._done("S7")
        self._chk(
            "CHK-SUPP-ADDR-ERROR",
            "EFUSE_PROGRAM_ADDR=%d and EFUSE_READ_ADDR=%d (2048 + 32 x %d) completed with done "
            "and status set and latched efuse_program_addr_error (status 0x%08x) and "
            "efuse_read_addr_error (status 0x%08x), no efuse_req_error, with 0 fuse-command "
            "cycles each; the clears returned the status to 0",
            end_bit,
            end_bit,
            SUPP_WORDS,
            status_p,
            status_r,
        )
        self.access_floor = self._calls

        # fence
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_step = {
            "CHK-SUPP-SENSE-WORDS": "S1",
            "CHK-SUPP-WINDOW-END": "S2",
            "CHK-SUPP-SHADOW-WRITE": "S3",
            "CHK-SUPP-PROGRAM-READ": "S4",
            "CHK-SUPP-WRITE-LOCK": "S5",
            "CHK-SUPP-READ-LOCK": "S5",
            "CHK-SUPP-LOCK-IRQ": "S5",
            "CHK-SUPP-GUARD": "S6",
            "CHK-SUPP-ADDR-ERROR": "S7",
        }
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(chk_step), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", chk_step[ident]) in self._events[:index], (
                    f"{ident} printed before step {chk_step[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SENSE < WINDOW END < SHADOW WRITE < PROGRAM < LOCKS < "
            "GUARD < ADDRESS ERROR; checker lines %s; stamps %s ps",
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(
                f"{name}={bound}(fails with AssertionError on expiry) last={state}"
                for name, bound, state in self._waits
            ),
        )
