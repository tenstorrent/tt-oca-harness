# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C `INTR_TEST` into `INTR_STATE`: status force and release, event latch, partial clears.

Sources: hw/ip/i2c/regs/i2c.rdl INTR_TEST / INTR_STATE, hw/ip/i2c/regs/i2c_wrap.rdl.

`INTR_TEST` is `rw` on the seven status bits ("Writing 1 forces the interrupt",
"Writing 0 releases it") and `sw = w` `singlepulse` on the 13 event bits;
`INTR_STATE` is `sw = r` on the status bits and `woclr` on the event bits. Every
`INTR_ENABLE` word stays at reset, so only register reads observe the result.
The `INTR_TEST` read-back and the combination of a live condition with
`INTR_TEST`: the specification does not state the values; both are logged and never compared.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_master_target_test_seq import _i2c_u32
from .smc_rdl_regmap import rdl_contract

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
NUM_I2CS = 3

_TEST_FIELDS = rdl_contract("smc_i2c_wrap/i2c[0]/INTR_TEST").fields
STATUS_NAMES = tuple(f.name for f in _TEST_FIELDS if f.access == "read-write")
EVENT_NAMES = tuple(f.name for f in _TEST_FIELDS if f.access == "write-only")

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")


def _i2c(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _mask(register: str, names: tuple[str, ...]) -> int:
    word = 0
    for name in names:
        word |= _i2c_u32(f"I2C__{register}__{name}_bm")
    return word


def _bit(register: str, name: str) -> int:
    return _i2c_u32(f"I2C__{register}__{name}_bm")


def _alternating(mask: int) -> tuple[int, int]:
    """Split a mask into two interleaved halves, lowest set bit first."""
    first = 0
    second = 0
    for index, bit in enumerate(b for b in range(mask.bit_length()) if mask >> b & 1):
        if index % 2:
            second |= 1 << bit
        else:
            first |= 1 << bit
    return first, second


INTR_STATE = tuple(_i2c("INTR_STATE", n) for n in range(NUM_I2CS))
INTR_TEST = tuple(_i2c("INTR_TEST", n) for n in range(NUM_I2CS))
INTR_ENABLE = tuple(_i2c("INTR_ENABLE", n) for n in range(NUM_I2CS))

STATE_STATUS = {name: _bit("INTR_STATE", name) for name in STATUS_NAMES}
TEST_STATUS = {name: _bit("INTR_TEST", name) for name in STATUS_NAMES}
EVENTS_STATE = _mask("INTR_STATE", EVENT_NAMES)
EVENTS_TEST = _mask("INTR_TEST", EVENT_NAMES)
RX_OVERFLOW_STATE = _bit("INTR_STATE", "RX_OVERFLOW")
RX_OVERFLOW_TEST = _bit("INTR_TEST", "RX_OVERFLOW")

LOW_HALF = _mask("INTR_STATE", EVENT_NAMES[:6])
HIGH_HALF = EVENTS_STATE & ~LOW_HALF
ALT_A, ALT_B = _alternating(EVENTS_STATE)


class smc_i2c_intr_test_state_test_seq(SmcCsrSeq):
    """Drive INTR_TEST and read INTR_STATE for the status, event and isolation cases."""

    def __init__(self, name: str = "smc_i2c_intr_test_state_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}
        self.measured: list[str] = []
        self.unmeasured: list[str] = []

    def _emit(self, chk: str, text: str) -> None:
        line = f"{chk}: {text}"
        cocotb.log.info("%s", line)
        self.chk_seen[chk] = line

    def _mark(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time(unit="ps"))))

    async def _write_resp(self, name: str, addr: int, data: int) -> int:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name}: no write response code"
        return item.resp_code

    async def _state(self, name: str, n: int = 0) -> int:
        word = await self.csr_read(name, INTR_STATE[n])
        assert 0 <= word <= 0xFFFF_FFFF, f"{name}: INTR_STATE[{n}] read 0x{word:x}"
        return word

    async def _s1_baseline(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        words = []
        for n in range(NUM_I2CS):
            enable = await self.csr_read(f"INTR_ENABLE{n}", INTR_ENABLE[n])
            state = await self._state(f"BASE{n}", n)
            words.append((enable, state))
        self.base_state = words[0][1]
        held = [nm for nm, bm in STATE_STATUS.items() if self.base_state & bm]
        cocotb.log.info(
            "S1 baseline: INTR_ENABLE %s INTR_STATE %s; instance 0 status bits held live: %s",
            [f"0x{e:08x}" for e, _ in words],
            [f"0x{s:08x}" for _, s in words],
            held or "none",
        )
        self.live = held
        self._mark("S1")

    async def _s2_force(self) -> None:
        forced, readbacks = [], {}
        for name in STATUS_NAMES:
            if name in self.live:
                self.unmeasured.append(name)
                continue
            pre = await self._state(f"{name}_PRE")
            if pre & STATE_STATUS[name]:
                self.unmeasured.append(name)
                continue
            await self.csr_write(f"{name}_FORCE", INTR_TEST[0], TEST_STATUS[name])
            post = await self._state(f"{name}_FORCED")
            readbacks[name] = await self.csr_read(f"{name}_TEST_RB", INTR_TEST[0])
            assert post & STATE_STATUS[name], (
                f"INTR_TEST.{name} written, INTR_STATE reads 0x{post:08x} (pre 0x{pre:08x}); "
                f"'Writing 1 forces the interrupt'"
            )
            self.measured.append(name)
            forced.append(f"{name}=0x{post:08x}")
        await self.csr_write("STATUS_RELEASE", INTR_TEST[0], 0)
        assert not self.live, f"status bits held live at the baseline: {self.live}"
        assert len(self.measured) == len(STATUS_NAMES), (
            f"{len(self.measured)} of {len(STATUS_NAMES)} status bits measured; "
            f"UNMEASURED {self.unmeasured}"
        )
        self._emit(
            "CHK-I2C-STATUS-FORCE",
            f"measured {self.measured} read 1 in INTR_STATE after INTR_TEST force "
            f"({', '.join(forced)}); INTR_TEST read-back (not specified, logged only) "
            f"{ {k: f'0x{v:08x}' for k, v in readbacks.items()} }; "
            f"UNMEASURED {self.unmeasured}",
        )
        self._mark("S2")

    async def _s3_release(self) -> None:
        legs = []
        for name in self.measured:
            await self.csr_write(f"{name}_SET", INTR_TEST[0], TEST_STATUS[name])
            observed = await self._state(f"{name}_SET_RB")
            await self.csr_write(f"{name}_ZERO", INTR_TEST[0], 0)
            released = await self._state(f"{name}_ZERO_RB")
            assert observed & STATE_STATUS[name], f"{name}: not 1 before release (0x{observed:08x})"
            assert not released & STATE_STATUS[name], (
                f"INTR_TEST 0 left INTR_STATE.{name} set (0x{released:08x}); "
                f"'Writing 0 releases it'"
            )
            legs.append(f"{name}: set=1 observed=0x{observed:08x} released=0x{released:08x}")
        self._emit(
            "CHK-I2C-STATUS-RELEASE",
            f"after INTR_TEST 0 every measured bit read 0 (set/observed/cleared/checked_cleared: "
            f"{'; '.join(legs)})",
        )
        self._mark("S3")

    async def _s4_sw_ro(self) -> None:
        legs = []
        for name in self.measured:
            bm = STATE_STATUS[name]
            await self.csr_write(f"{name}_FORCE", INTR_TEST[0], TEST_STATUS[name])
            held = await self._state(f"{name}_HELD")
            resp_one = await self._write_resp(f"{name}_W1", INTR_STATE[0], bm)
            after_one = await self._state(f"{name}_AFTER_W1")
            resp_zero = await self._write_resp(f"{name}_W0", INTR_STATE[0], 0)
            after_zero = await self._state(f"{name}_AFTER_W0")
            await self.csr_write(f"{name}_RELEASE", INTR_TEST[0], 0)
            freed = await self._state(f"{name}_FREED")
            assert held & bm, f"{name}: not forced before the software writes (0x{held:08x})"
            assert after_one & bm and after_zero & bm, (
                f"INTR_STATE.{name} (sw = r) changed on a software write: after W1 "
                f"0x{after_one:08x}, after W0 0x{after_zero:08x}"
            )
            assert not freed & bm, f"{name}: INTR_TEST 0 left the bit set (0x{freed:08x})"
            legs.append(f"{name}: resp W1={resp_one} W0={resp_zero} kept=1,1 cleared=0")
        self._emit(
            "CHK-I2C-STATUS-SW-RO",
            f"INTR_STATE write of the bit and write of 0 left each forced bit reading 1 "
            f"({'; '.join(legs)})",
        )
        self._mark("S4")

    async def _s5_live(self) -> None:
        if not self.unmeasured:
            idle = await self._state("LIVE_NONE_STATE")
            idle_test = await self.csr_read("LIVE_NONE_TEST", INTR_TEST[0])
            self._emit(
                "CHK-I2C-STATUS-LIVE-OBS",
                f"no status bit was live (INTR_STATE=0x{idle:08x} INTR_TEST=0x{idle_test:08x}); "
                f"the cell condition-and-INTR_TEST combination (not specified, measured) "
                f"is not measured",
            )
        else:
            words = []
            for name in self.unmeasured:
                await self.csr_write(f"{name}_LIVE_SET", INTR_TEST[0], TEST_STATUS[name])
                one = await self._state(f"{name}_LIVE_AFTER1")
                await self.csr_write(f"{name}_LIVE_ZERO", INTR_TEST[0], 0)
                zero = await self._state(f"{name}_LIVE_AFTER0")
                words.append(f"{name}: after_test1=0x{one:08x} after_test0=0x{zero:08x}")
            self._emit(
                "CHK-I2C-STATUS-LIVE-OBS",
                f"live status bits observed, not specified, no value compared: {'; '.join(words)}",
            )
        self._mark("S5")

    async def _events(self, name: str, n: int = 0) -> int:
        return await self._state(name, n) & EVENTS_STATE

    async def _s6_event_hold(self) -> None:
        await self.csr_write("EVENTS_PRECLEAR", INTR_STATE[0], EVENTS_STATE)
        pre = await self._events("EVENTS_PRE")
        assert pre == 0, f"event bits 0x{pre:08x} still set after a W1C of all 13"
        await self.csr_write("EVENTS_SET", INTR_TEST[0], EVENTS_TEST)
        set_word = await self._events("EVENTS_SET_RB")
        await self.csr_write("EVENTS_TEST0", INTR_TEST[0], 0)
        after_test0 = await self._events("EVENTS_AFTER_TEST0")
        await self.csr_write("EVENTS_STATE0", INTR_STATE[0], 0)
        after_state0 = await self._events("EVENTS_AFTER_STATE0")
        assert set_word == EVENTS_STATE, (
            f"INTR_TEST of 13 event bits left 0x{set_word:08x}, want 0x{EVENTS_STATE:08x}"
        )
        assert after_test0 == EVENTS_STATE and after_state0 == EVENTS_STATE, (
            f"event bits after INTR_TEST 0 0x{after_test0:08x}, after INTR_STATE 0 "
            f"0x{after_state0:08x}; want 0x{EVENTS_STATE:08x} (woclr, no release text)"
        )
        self._emit(
            "CHK-I2C-EVENT-NO-RELEASE",
            f"13 event bits set=0x{set_word:08x} observed after INTR_TEST 0=0x{after_test0:08x} "
            f"and INTR_STATE 0=0x{after_state0:08x}; cleared and checked_cleared in step S7",
        )
        self._mark("S6")

    async def _clear_expect(self, name: str, write: int, remaining: int) -> str:
        await self.csr_write(f"{name}_W1C", INTR_STATE[0], write)
        left = await self._events(f"{name}_RB")
        assert left == remaining, (
            f"{name}: after W1C 0x{write:08x} events read 0x{left:08x}, want 0x{remaining:08x}"
        )
        return f"{name} wrote 0x{write:08x} left 0x{left:08x}"

    async def _s7_partial(self) -> None:
        legs = [await self._clear_expect("LOW", LOW_HALF, EVENTS_STATE & ~LOW_HALF)]
        legs.append(await self._clear_expect("HIGH", HIGH_HALF, 0))
        await self.csr_write("ALT_RAISE", INTR_TEST[0], EVENTS_TEST)
        raised = await self._events("ALT_RAISED")
        assert raised == EVENTS_STATE, f"re-raise left 0x{raised:08x}"
        legs.append(await self._clear_expect("ALT_A", ALT_A, EVENTS_STATE & ~ALT_A))
        legs.append(await self._clear_expect("ALT_B", ALT_B, 0))
        await self.csr_write("ALT_RAISE_REV", INTR_TEST[0], EVENTS_TEST)
        raised = await self._events("ALT_RAISED_REV")
        assert raised == EVENTS_STATE, f"re-raise left 0x{raised:08x}"
        legs.append(await self._clear_expect("ALT_B_FIRST", ALT_B, EVENTS_STATE & ~ALT_B))
        legs.append(await self._clear_expect("ALT_A_SECOND", ALT_A, 0))
        await self.csr_write("ZERO_WRITE", INTR_STATE[0], 0)
        kept = await self._events("ZERO_WRITE_RB")
        assert kept == 0, f"a zero write changed the cleared word to 0x{kept:08x}"
        await self.csr_write("ZERO_WRITE_SET", INTR_TEST[0], EVENTS_TEST)
        await self._clear_expect("ZERO_ON_SET_PREP", LOW_HALF, EVENTS_STATE & ~LOW_HALF)
        await self.csr_write("ZERO_WRITE_PARTIAL", INTR_STATE[0], 0)
        unchanged = await self._events("ZERO_WRITE_PARTIAL_RB")
        assert unchanged == EVENTS_STATE & ~LOW_HALF, (
            f"a zero write changed 0x{EVENTS_STATE & ~LOW_HALF:08x} to 0x{unchanged:08x}"
        )
        await self._clear_expect("FINAL_CLEAR", EVENTS_STATE, 0)
        self._emit(
            "CHK-I2C-EVENT-PARTIAL-CLEAR",
            f"from 13 set: {'; '.join(legs)}; zero write unchanged at 0x{unchanged:08x}; "
            f"13 bits checked_cleared=0x00000000",
        )
        self._mark("S7")

    async def _s8_rearm(self) -> None:
        bm = RX_OVERFLOW_STATE
        start = await self._events("REARM_START")
        assert not start & bm, f"RX_OVERFLOW set before its INTR_TEST (0x{start:08x})"
        await self.csr_write("REARM_SET1", INTR_TEST[0], RX_OVERFLOW_TEST)
        set1 = await self._events("REARM_SET1_RB")
        await self.csr_write("REARM_W1C1", INTR_STATE[0], bm)
        clr1 = await self._events("REARM_W1C1_RB")
        await self.csr_write("REARM_SET2", INTR_TEST[0], RX_OVERFLOW_TEST)
        set2 = await self._events("REARM_SET2_RB")
        await self.csr_write("REARM_SET3", INTR_TEST[0], RX_OVERFLOW_TEST)
        set3 = await self._events("REARM_SET3_RB")
        await self.csr_write("REARM_W1C2", INTR_STATE[0], bm)
        clr2 = await self._events("REARM_W1C2_RB")
        assert set1 & bm and not clr1 & bm, (
            f"RX_OVERFLOW set 0x{set1:08x} then after W1C 0x{clr1:08x}"
        )
        assert set2 & bm and set3 & bm, (
            f"RX_OVERFLOW after re-arm 0x{set2:08x}, after the repeated INTR_TEST 0x{set3:08x}"
        )
        assert not clr2 & bm, f"one W1C left RX_OVERFLOW set (0x{clr2:08x})"
        self._emit(
            "CHK-I2C-EVENT-REARM",
            f"RX_OVERFLOW INTR_STATE bit 3: set={set1 & bm:#x} W1C={clr1 & bm:#x} "
            f"re-armed={set2 & bm:#x} repeated INTR_TEST while set={set3 & bm:#x} "
            f"single W1C checked_cleared={clr2 & bm:#x}",
        )
        self._mark("S8")

    async def _s9_isolation(self) -> None:
        bm = RX_OVERFLOW_STATE
        for n in range(NUM_I2CS):
            await self.csr_write(f"ISO_PRECLEAR{n}", INTR_STATE[n], bm)
            await self.csr_write(f"ISO_SET{n}", INTR_TEST[n], RX_OVERFLOW_TEST)
        legs = []
        for n in range(NUM_I2CS):
            seen = [await self._state(f"ISO_SET_RB{n}_{m}", m) & bm for m in range(NUM_I2CS)]
            assert all(seen), f"RX_OVERFLOW not set on all instances before W1C of {n}: {seen}"
        for n in range(NUM_I2CS):
            await self.csr_write(f"ISO_W1C{n}", INTR_STATE[n], bm)
            after = [await self._state(f"ISO_AFTER{n}_{m}", m) & bm for m in range(NUM_I2CS)]
            expect = [0 if m == n else bm for m in range(NUM_I2CS)]
            assert after == expect, (
                f"W1C of RX_OVERFLOW on instance {n}: bit reads {after}, want {expect}"
            )
            legs.append(f"n={n}: bits {[1 if a else 0 for a in after]}")
            await self.csr_write(f"ISO_REARM{n}", INTR_TEST[n], RX_OVERFLOW_TEST)
        for n in range(NUM_I2CS):
            await self.csr_write(f"ISO_FINAL{n}", INTR_STATE[n], bm)
        final = [await self._state(f"ISO_FINAL_RB{m}", m) & bm for m in range(NUM_I2CS)]
        assert final == [0] * NUM_I2CS, f"final clear left {final}"
        self._emit(
            "CHK-I2C-W1C-ISOLATION",
            f"RX_OVERFLOW set on 3 instances; W1C on one instance cleared only it "
            f"({'; '.join(legs)}); final clear {final}",
        )
        self._mark("S9")

    def _nonvac(self) -> None:
        order = [s for s, _ in self.fence]
        stamps = [t for _, t in self.fence]
        assert order == list(STEPS), f"fence order {order}, want {list(STEPS)}"
        assert all(a < b for a, b in zip(stamps, stamps[1:])), f"stamps not increasing: {stamps}"
        ids = [c for c in self.chk_seen if c != "CHK-NONVAC"]
        assert len(ids) == 8, f"checker lines printed: {ids}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps ps %s",
            " < ".join(order),
            ", ".join(ids),
            stamps,
        )

    async def body(self) -> None:
        await self._s1_baseline()
        await self._s2_force()
        await self._s3_release()
        await self._s4_sw_ro()
        await self._s5_live()
        await self._s6_event_hold()
        await self._s7_partial()
        await self._s8_rearm()
        await self._s9_isolation()
        self._nonvac()
