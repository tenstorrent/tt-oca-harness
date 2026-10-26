# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse interface control written from the JTAG eFuse port, read back over SEP_IN.

Contract: ``SMC_COV_W2T_009`` revision 1
(``hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_W2T_VPLAN_DETAIL_ADDITIONS.md``).

Every write goes through the ``ej_axi`` AXI-Lite manager on the JTAG eFuse port; every
compared value is read over SEP_IN at the same generated ``SMC_TOP_EFUSE_INTERFACE_CTRL_*``
address. Field masks and resets come from the generated ``efuse_interface_ctrl.h``; the
field access types are those of ``efuse_interface_ctrl.adoc``.

* S1 drives ``tb_lc_state`` to TEST_DEV and requires ``efuse_sense_done`` 1 with the
  error bits [6:4] 0.
* S2 writes all RW fields, zero and a walking one to EFUSE_PROGRAM_CTRL (19 RW bits),
  EFUSE_READ_CTRL (17 RW bits) and both timeout registers (29 RW bits), then the
  0x0080_0000 reset to the timeouts. Each SEP_IN readback masked to the RW fields equals
  the written word and the status fields read 0. One JTAG read of each register follows.
* S3 writes EFUSE_PROGRAM_CTRL full-width 0x1234, with WSTRB 0x1 and data 0x0805_FFA5,
  then full-width 0. The strobed readback and response are logged (SF-009).
* S4 reads bit A through the read interface, programs it with ``efuse_data`` 1 and polls
  ``program_done``; S5 reads A again; S6 issues a data-0 program to bit A2 and reads A2
  before and after. Each read first clears EFUSE_PROGRAM_CTRL, since ``program_enable``
  and ``read_enable`` are mutually exclusive owners of the command path.
* S7 writes both control registers 0 and both timeouts 0x0080_0000 and drives
  ``tb_lc_state`` back to its S1 value.

A and A2 are bits of SPARE[2] and SPARE[3], whose write and read locks the default image's
LOCKS word leaves clear and whose image words are 0.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import efuse_ifc_u32, smc_addr, smc_efuse_map_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import EFUSE_MAP_BASE, efuse_preload_word_at

STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
PROGRAM_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR")
READ_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR")
PROG_IF_DATA = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_INTERFACE_READ_DATA_BASE_ADDR")
READ_DATA = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_INTERFACE_READ_DATA_BASE_ADDR")
READ_TMO = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR")
PROG_TMO = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_BASE_ADDR")


def _f(reg: str, field: str) -> int:
    return efuse_ifc_u32(f"EFUSE_INTERFACE_CTRL__{reg}__{field}_bm")


SENSE_DONE = _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_SENSE_DONE")
STATUS_ERRORS = (
    _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_REQ_ERROR")
    | _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_PROGRAM_ADDR_ERROR")
    | _f("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_READ_ADDR_ERROR")
)

PROG_ADDR = _f("EFUSE_PROGRAM_CTRL", "EFUSE_ADDR")
PROG_DATA = _f("EFUSE_PROGRAM_CTRL", "EFUSE_DATA")
PROG_GO = _f("EFUSE_PROGRAM_CTRL", "EFUSE_PROGRAM_GO")
PROG_RB = _f("EFUSE_PROGRAM_CTRL", "EFUSE_PROGRAM_READ_BACK")
PROG_BUSY = _f("EFUSE_PROGRAM_CTRL", "PROGRAM_BUSY")
PROG_DONE = _f("EFUSE_PROGRAM_CTRL", "PROGRAM_DONE")
PROG_ERR = _f("EFUSE_PROGRAM_CTRL", "PROGRAM_STATUS")
PROG_EN = _f("EFUSE_PROGRAM_CTRL", "PROGRAM_ENABLE")
PROG_RW = PROG_ADDR | PROG_DATA | PROG_RB | PROG_EN
PROG_STATE = PROG_BUSY | PROG_DONE | PROG_ERR

READ_ADDR = _f("EFUSE_READ_CTRL", "EFUSE_ADDR")
READ_GO = _f("EFUSE_READ_CTRL", "EFUSE_READ_GO")
READ_BUSY = _f("EFUSE_READ_CTRL", "READ_BUSY")
READ_DONE = _f("EFUSE_READ_CTRL", "READ_DONE")
READ_ERR = _f("EFUSE_READ_CTRL", "READ_STATUS")
READ_EN = _f("EFUSE_READ_CTRL", "READ_ENABLE")
READ_RW = READ_ADDR | READ_EN
READ_STATE = READ_BUSY | READ_DONE | READ_ERR

TMO_RW_R = _f("EFUSE_READ_REQ_TIMEOUT", "READ_REQ_TIMEOUT_CYCLES") | _f(
    "EFUSE_READ_REQ_TIMEOUT", "READ_REQ_TIMOUT_ENABLE"
)
TMO_RW_P = _f("EFUSE_PROGRAM_REQ_TIMEOUT", "PROGRAM_REQ_TIMEOUT_CYCLES") | _f(
    "EFUSE_PROGRAM_REQ_TIMEOUT", "PROGRAM_REQ_TIMEOUT_ENABLE"
)
TMO_RESET_R = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_READ_REQ_TIMEOUT__READ_REQ_TIMEOUT_CYCLES_reset"
)
TMO_RESET_P = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_REQ_TIMEOUT__PROGRAM_REQ_TIMEOUT_CYCLES_reset"
)

#: Contract S2 words: every RW field set and the documented timeout reset.
PROG_ALL_RW = 0x0805_FFFF
READ_ALL_RW = 0x1000_FFFF
TMO_ALL_RW = 0x1FFF_FFFF
TMO_RESET = 0x0080_0000
#: Contract S3 words.
PARTIAL_PRE = 0x0000_1234
PARTIAL_DATA = 0x0805_FFA5
PARTIAL_STRB = 0x1
PARTIAL_EXPECT = 0x0000_12A5

#: Documented write counts per register in S2 (all RW, zero, one per RW bit).
WALK_COUNTS = {"PROGRAM_CTRL": 21, "READ_CTRL": 19, "READ_TO": 31, "PROG_TO": 31}

#: TEST_DEV in the {diff_n, diff_p} encoding of port_table.adoc:64.
LC_TEST_DEV_PACKED = 0xF0

FULL_STROBE = 0xF
RESP_OKAY = 0
WORD = 0xFFFF_FFFF
JTAG_ACCESS_TIMEOUT_NS = 2_000
POLL_BOUND = 10_000

FENCE = ("SETUP", "WALK", "PARTIAL-STROBE", "PROGRAM", "READ-BACK", "DATA0", "RESTORED")


def _bits(mask: int) -> list[int]:
    return [1 << b for b in range(32) if mask >> b & 1]


def _spare_bit(index: int, offset: int) -> int:
    """Fuse bit address of bit ``offset`` of SPARE[``index``]; map byte n holds bits 8n..8n+7."""
    return (
        smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", index) - EFUSE_MAP_BASE
    ) * 8 + (offset)


SPARE_A, SPARE_A2 = 2, 3
BIT_A = _spare_bit(SPARE_A, 5)
BIT_A2 = _spare_bit(SPARE_A2, 9)


class smc_efuse_jtag_otp_data_walk_test_seq(SmcCsrSeq):
    """JTAG-port writes of the eFuse interface control block with SEP_IN readback."""

    def __init__(self, name: str = "smc_efuse_jtag_otp_data_walk_test_seq") -> None:
        super().__init__(name)
        self.jtag = None
        self.jtag_writes = 0
        self.jtag_reads = 0
        self.fence: list[tuple[str, int, int]] = []
        self.waits: list[str] = []
        self.chk_seen: list[str] = []
        self._last = "no SEP_IN read completed"

    # --- accesses -------------------------------------------------------------
    def _total(self) -> int:
        return self.accesses + self.jtag_writes + self.jtag_reads

    async def _sep_read(self, label: str, addr: int) -> int:
        value = int(await self.csr_read(label, addr)) & WORD
        self._last = f"{label}@0x{addr:08x}=0x{value:08x}"
        return value

    async def _jtag_write(
        self, label: str, addr: int, data: int, strb: int = FULL_STROBE, check: bool = True
    ) -> int:
        try:
            result = await self.jtag.write_result(
                addr,
                data,
                strb=strb,
                check_response=False,
                timeout_ns=JTAG_ACCESS_TIMEOUT_NS,
            )
        except AssertionError as exc:
            raise AssertionError(
                f"{label}: JTAG write 0x{data:08x} strb 0x{strb:x} to 0x{addr:08x} got no B "
                f"within {JTAG_ACCESS_TIMEOUT_NS} ns; last SEP_IN word {self._last}"
            ) from exc
        self.jtag_writes += 1
        resp = int(result.resp)
        if check:
            assert resp == RESP_OKAY, (
                f"{label}: JTAG write 0x{data:08x} to 0x{addr:08x} answered resp {resp}, "
                f"expected OKAY; last SEP_IN word {self._last}"
            )
        return resp

    async def _jtag_read(self, label: str, addr: int) -> tuple[int, int]:
        try:
            result = await self.jtag.read_result(
                addr, check_response=False, timeout_ns=JTAG_ACCESS_TIMEOUT_NS
            )
        except AssertionError as exc:
            raise AssertionError(
                f"{label}: JTAG read of 0x{addr:08x} got no R within {JTAG_ACCESS_TIMEOUT_NS} ns; "
                f"last SEP_IN word {self._last}"
            ) from exc
        self.jtag_reads += 1
        return int(result.data) & WORD, int(result.resp)

    async def _poll(self, label: str, addr: int, done) -> tuple[int, list[int]]:
        """SEP_IN reads of ``addr`` until ``done`` holds, at most POLL_BOUND reads."""
        samples: list[int] = []
        for _ in range(POLL_BOUND):
            value = await self._sep_read(label, addr)
            samples.append(value)
            if done(value):
                self.waits.append(
                    f"{label} bound={POLL_BOUND} reads used={len(samples)} last=0x{value:08x}"
                )
                return value, samples
        raise AssertionError(
            f"{label}: condition not met within {POLL_BOUND} SEP_IN reads of 0x{addr:08x}; "
            f"last 0x{samples[-1]:08x}"
        )

    def _stamp(self, term: str) -> None:
        count = self._total() - sum(c for _t, c, _ns in self.fence)
        self.fence.append((term, count, int(get_sim_time("ns"))))

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        cocotb.log.info("%s: " + fmt, chk_id, *args)
        self.chk_seen.append(chk_id)

    # --- read interface -----------------------------------------------------
    async def _fuse_read(self, label: str, bit: int) -> tuple[int, int, int]:
        """Read ``bit`` through the read interface: (READ_CTRL at done, dout, busy samples).

        ``program_enable`` owns the command path while it is set, and a read issued then
        does not reach the bank (architecture.adoc, Command-path ownership), so every read
        starts by writing EFUSE_PROGRAM_CTRL to 0.
        """
        await self._jtag_write(f"{label}_PROG_OFF", PROGRAM_CTRL, 0)
        await self._jtag_write(f"{label}_EN", READ_CTRL, bit | READ_EN)
        await self._jtag_write(f"{label}_GO", READ_CTRL, bit | READ_EN | READ_GO)
        ctrl, samples = await self._poll(
            f"{label}_DONE", READ_CTRL, lambda v: bool(v & READ_DONE) and not v & READ_BUSY
        )
        assert ctrl & READ_ERR == 0, f"{label}: read_status 1 (READ_CTRL=0x{ctrl:08x})"
        dout = await self._sep_read(f"{label}_DOUT", READ_DATA)
        return ctrl, dout, sum(1 for s in samples if s & READ_BUSY)

    # --- body -----------------------------------------------------------------
    async def body(self) -> None:
        assert self.jtag is not None, "the testcase hands the JTAG eFuse port to the sequence"
        await self._setup()
        await self._walk()
        await self._partial_strobe()
        dout_pre = await self._program()
        await self._read_back(dout_pre)
        await self._data0()
        await self._restore()
        self._timeout_paths()
        self._nonvac()

    async def _setup(self) -> None:
        dut = cocotb.top
        locks = efuse_preload_word_at(smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR"))
        locks |= efuse_preload_word_at(smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR") + 4) << 32
        for spare, bit in ((SPARE_A, BIT_A), (SPARE_A2, BIT_A2)):
            lock_mask = smc_efuse_map_u32(
                f"SMC_EFUSE_MAP__LOCKS__SPARE{spare}_WRITE_LOCK_bm"
            ) | smc_efuse_map_u32(f"SMC_EFUSE_MAP__LOCKS__SPARE{spare}_READ_LOCK_bm")
            assert locks & lock_mask == 0, (
                f"SPARE{spare} is locked by the image LOCKS 0x{locks:016x} (mask 0x{lock_mask:x})"
            )
            word = efuse_preload_word_at(EFUSE_MAP_BASE + (bit // 32) * 4)
            assert word >> (bit % 32) & 1 == 0, (
                f"image word of bit 0x{bit:x} is 0x{word:08x}: the bit is already 1"
            )
        prior = str(dut.tb_lc_state.value)
        dut.tb_lc_state.value = LC_TEST_DEV_PACKED
        await self.wait_fuse_sense_done()
        self.waits.append("fuse_sense bound=200000 clk_smc_i cycles (raises on expiry)")
        self.lc_s1 = int(dut.tb_lc_state.value)
        status = await self._sep_read("S1_STATUS", STATUS)
        assert status & SENSE_DONE and status & STATUS_ERRORS == 0, (
            f"S1: EFUSE_INTERFACE_CTRL_STATUS=0x{status:08x}; sense_done must be 1 and bits [6:4] 0"
        )
        cocotb.log.info(
            "STEP S1: tb_lc_state 0x%02x (TEST_DEV; prior value %s; LINKED-ISSUE SF-017), "
            "STATUS=0x%08x; A=0x%04x (SPARE%d) A2=0x%04x (SPARE%d), locks clear in LOCKS 0x%016x",
            self.lc_s1,
            prior,
            status,
            BIT_A,
            SPARE_A,
            BIT_A2,
            SPARE_A2,
            locks,
        )
        self._stamp("SETUP")

    async def _walk_reg(
        self, name: str, addr: int, rw: int, state: int, words: list[int]
    ) -> tuple[int, set[int]]:
        matched = 0
        reserved: set[int] = set()
        for n, word in enumerate(words):
            await self._jtag_write(f"S2_{name}_{n}", addr, word)
            rb = await self._sep_read(f"S2_{name}_{n}_RB", addr)
            assert rb & rw == word & rw, (
                f"S2 {name}: wrote 0x{word:08x}, SEP_IN read 0x{rb:08x}; RW fields 0x{rw:08x} "
                f"differ (0x{(rb ^ word) & rw:08x})"
            )
            assert rb & state == 0, (
                f"S2 {name}: status field set after writing 0x{word:08x} (read 0x{rb:08x}, "
                f"status mask 0x{state:08x})"
            )
            reserved.add(rb & ~(rw | state) & WORD)
            matched += 1
        assert matched == WALK_COUNTS[name], (
            f"S2 {name}: {matched} writes, documented count {WALK_COUNTS[name]}"
        )
        return matched, reserved

    async def _walk(self) -> None:
        plan = (
            ("PROGRAM_CTRL", PROGRAM_CTRL, PROG_RW, PROG_STATE, PROG_ALL_RW),
            ("READ_CTRL", READ_CTRL, READ_RW, READ_STATE, READ_ALL_RW),
            ("READ_TO", READ_TMO, TMO_RW_R, 0, TMO_ALL_RW),
            ("PROG_TO", PROG_TMO, TMO_RW_P, 0, TMO_ALL_RW),
        )
        counts = {}
        reserved = {}
        for name, addr, rw, state, all_rw in plan:
            assert rw == all_rw, (
                f"{name}: generated RW mask 0x{rw:08x} is not the documented 0x{all_rw:08x}"
            )
            words = [all_rw, 0] + _bits(rw)
            counts[name], reserved[name] = await self._walk_reg(name, addr, rw, state, words)
        assert TMO_RESET_R == TMO_RESET and TMO_RESET_P == TMO_RESET, (
            f"generated timeout resets 0x{TMO_RESET_R:x}/0x{TMO_RESET_P:x} are not 0x{TMO_RESET:x}"
        )
        finals = []
        for name, addr in (("READ_TO", READ_TMO), ("PROG_TO", PROG_TMO)):
            await self._jtag_write(f"S2_{name}_RESET", addr, TMO_RESET)
            rb = await self._sep_read(f"S2_{name}_RESET_RB", addr)
            assert rb == TMO_RESET, (
                f"S2 {name}: final readback 0x{rb:08x}, expected 0x{TMO_RESET:08x}"
            )
            finals.append(rb)
        jtag_rd = []
        for name, addr in (
            ("STATUS", STATUS),
            ("PROGRAM_CTRL", PROGRAM_CTRL),
            ("READ_CTRL", READ_CTRL),
            ("READ_TO", READ_TMO),
            ("PROG_TO", PROG_TMO),
        ):
            data, resp = await self._jtag_read(f"S2_JTAG_RD_{name}", addr)
            jtag_rd.append(f"{name}=0x{data:08x}/resp{resp}")
        self._stamp("WALK")
        self._chk(
            "CHK-EFUSE-JTAG-WALK",
            "PROGRAM_CTRL %d/%d, READ_CTRL %d/%d, READ_TO %d/%d, PROG_TO %d/%d masked match, "
            "status idle; final timeouts 0x%08x/0x%08x; JTAG writes OKAY; reserved bits read %s "
            "(LINKED-ISSUE SF-001); JTAG reads logged %s",
            counts["PROGRAM_CTRL"],
            WALK_COUNTS["PROGRAM_CTRL"],
            counts["READ_CTRL"],
            WALK_COUNTS["READ_CTRL"],
            counts["READ_TO"],
            WALK_COUNTS["READ_TO"],
            counts["PROG_TO"],
            WALK_COUNTS["PROG_TO"],
            finals[0],
            finals[1],
            {k: sorted(f"0x{v:x}" for v in vals) for k, vals in reserved.items()},
            " ".join(jtag_rd),
        )

    async def _partial_strobe(self) -> None:
        await self._jtag_write("S3_PRE", PROGRAM_CTRL, PARTIAL_PRE)
        pre = await self._sep_read("S3_PRE_RB", PROGRAM_CTRL)
        assert pre == PARTIAL_PRE, f"S3: readback 0x{pre:08x}, expected 0x{PARTIAL_PRE:08x}"
        resp = await self._jtag_write(
            "S3_STRB", PROGRAM_CTRL, PARTIAL_DATA, strb=PARTIAL_STRB, check=False
        )
        strobed = await self._sep_read("S3_STRB_RB", PROGRAM_CTRL)
        await self._jtag_write("S3_POST", PROGRAM_CTRL, 0)
        post = await self._sep_read("S3_POST_RB", PROGRAM_CTRL)
        assert post == 0, f"S3: readback 0x{post:08x} after the zero write, expected 0x0"
        self._stamp("PARTIAL-STROBE")
        self._chk(
            "CHK-EFUSE-JTAG-PARTIAL-STRB",
            "pre=0x%08x exact, strobe0 rb=0x%08x resp=%d (logged against 0x%08x, LINKED-ISSUE "
            "SF-009), post=0x%08x exact",
            pre,
            strobed,
            resp,
            PARTIAL_EXPECT,
            post,
        )

    async def _program(self) -> int:
        _ctrl, dout_pre, _busy = await self._fuse_read("S4_PRE", BIT_A)
        self.dout_pre_a = dout_pre
        await self._jtag_write("S4_ARM", PROGRAM_CTRL, BIT_A | PROG_DATA | PROG_EN)

        async def _go() -> None:
            await self._jtag_write("S4_GO", PROGRAM_CTRL, BIT_A | PROG_DATA | PROG_EN | PROG_GO)

        go = cocotb.start_soon(_go())
        ctrl, samples = await self._poll("S4_DONE", PROGRAM_CTRL, lambda v: bool(v & PROG_DONE))
        await go
        busy_before_done = sum(1 for s in samples[:-1] if s & PROG_BUSY)
        assert busy_before_done >= 1, (
            f"S4: program_busy never read 1 before program_done ({len(samples)} samples, "
            f"last 0x{ctrl:08x})"
        )
        assert ctrl & PROG_ERR == 0, f"S4: program_status 1 (PROGRAM_CTRL=0x{ctrl:08x})"
        prog_if = await self._sep_read("S4_PROG_IF_DATA", PROG_IF_DATA)
        self._stamp("PROGRAM")
        self._chk(
            "CHK-EFUSE-JTAG-PROGRAM",
            "A=0x%04x busy seen %d of %d samples, done=1 status=0 (PROGRAM_CTRL=0x%08x); "
            "dout_pre(A)=0x%08x; EFUSE_PROGRAM_INTERFACE_READ_DATA=0x%08x logged",
            BIT_A,
            busy_before_done,
            len(samples),
            ctrl,
            dout_pre,
            prog_if,
        )
        return dout_pre

    async def _read_back(self, dout_pre: int) -> None:
        ctrl, dout_post, busy = await self._fuse_read("S5_READ", BIT_A)
        changed = dout_pre ^ dout_post
        assert changed and changed & (changed - 1) == 0, (
            f"S5: dout 0x{dout_pre:08x} -> 0x{dout_post:08x}; exactly one bit must change"
        )
        assert dout_post & changed, (
            f"S5: dout 0x{dout_pre:08x} -> 0x{dout_post:08x}; the changed bit was cleared"
        )
        jtag_dout, jtag_resp = await self._jtag_read("S5_JTAG_DOUT", READ_DATA)
        self._stamp("READ-BACK")
        self._chk(
            "CHK-EFUSE-JTAG-READBACK",
            "read_done=1 status=0 (READ_CTRL=0x%08x, busy samples %d), dout 0x%08x -> 0x%08x, "
            "one new bit at %d for A=0x%04x (A mod 32 = %d; LINKED-ISSUE SF-016); JTAG read of "
            "READ_DATA 0x%08x resp %d logged",
            ctrl,
            busy,
            dout_pre,
            dout_post,
            changed.bit_length() - 1,
            BIT_A,
            BIT_A % 32,
            jtag_dout,
            jtag_resp,
        )

    async def _data0(self) -> None:
        _ctrl, pre, _busy = await self._fuse_read("S6_PRE", BIT_A2)
        await self._jtag_write("S6_ARM", PROGRAM_CTRL, BIT_A2 | PROG_EN)
        await self._jtag_write("S6_GO", PROGRAM_CTRL, BIT_A2 | PROG_EN | PROG_GO)
        ctrl, samples = await self._poll("S6_IDLE", PROGRAM_CTRL, lambda v: not v & PROG_BUSY)
        _ctrl2, post, _busy2 = await self._fuse_read("S6_POST", BIT_A2)
        assert post == pre, (
            f"S6: data-0 program of A2=0x{BIT_A2:04x} changed dout 0x{pre:08x} -> 0x{post:08x}"
        )
        self._stamp("DATA0")
        self._chk(
            "CHK-EFUSE-JTAG-DATA0",
            "A2=0x%04x dout 0x%08x == 0x%08x, done/busy=%s over %d samples (logged; "
            "PROGRAM_CTRL=0x%08x)",
            BIT_A2,
            pre,
            post,
            ",".join(f"{int(bool(s & PROG_DONE))}/{int(bool(s & PROG_BUSY))}" for s in samples[:8]),
            len(samples),
            ctrl,
        )

    async def _restore(self) -> None:
        dut = cocotb.top
        readbacks = []
        for name, addr, word in (
            ("PROGRAM_CTRL", PROGRAM_CTRL, 0),
            ("READ_CTRL", READ_CTRL, 0),
            ("READ_TO", READ_TMO, TMO_RESET),
            ("PROG_TO", PROG_TMO, TMO_RESET),
        ):
            await self._jtag_write(f"S7_{name}", addr, word)
            rb = await self._sep_read(f"S7_{name}_RB", addr)
            mask = {"PROGRAM_CTRL": PROG_RW, "READ_CTRL": READ_RW}.get(name, WORD)
            assert rb & mask == word, (
                f"S7 {name}: readback 0x{rb:08x}, expected 0x{word:08x} over mask 0x{mask:08x}"
            )
            readbacks.append(f"{name}=0x{rb:08x}")
        dut.tb_lc_state.value = self.lc_s1
        cocotb.log.info(
            "STEP S7: %s; tb_lc_state driven back to 0x%02x", " ".join(readbacks), self.lc_s1
        )
        self._stamp("RESTORED")

    def _timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, 0 expired: %s; %d JTAG writes and %d JTAG "
            "reads bound %d ns each; %d SEP_IN accesses bound %d ns (driver); every expiry "
            "raises AssertionError with the last observed state (last %s)",
            len(self.waits),
            "; ".join(self.waits),
            self.jtag_writes,
            self.jtag_reads,
            JTAG_ACCESS_TIMEOUT_NS,
            self.accesses,
            self.cfg.axi_timeout_ns,
            self._last,
        )
        self.chk_seen.append("CHK-TIMEOUT-PATHS")

    def _nonvac(self) -> None:
        terms = [t for t, _c, _ns in self.fence]
        assert terms == list(FENCE), f"fence terms {terms}, want {list(FENCE)}"
        zero = [t for t, c, _ns in self.fence if c <= 0]
        assert not zero, f"fence terms with zero accesses {zero}"
        times = [ns for _t, _c, ns in self.fence]
        assert all(b > a for a, b in zip(times, times[1:])), f"fence times not increasing {times}"
        cocotb.log.info(
            "CHK-NONVAC: %s (%s)",
            " < ".join(FENCE),
            ", ".join(f"{t} count={c} t={ns}ns" for t, c, ns in self.fence),
        )
        self.chk_seen.append("CHK-NONVAC")
