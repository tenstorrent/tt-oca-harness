# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target bus symbols: abandoned transactions, START/STOP detect flags, UNEXP_STOP.

Sources: hw/ip/i2c/regs/i2c.rdl (ACQDATA.SIGNAL, ACQDATA.ABYTE, TXDATA.DATA, STATUS.TARGETIDLE,
FIFO_CTRL.ACQRST, INTR_STATE.UNEXP_STOP, INTR_TEST, INTR_ENABLE, TARGET_EVENTS.START_DETECT,
TARGET_EVENTS.STOP_DETECT, CTRL.ENABLETARGET), hw/sys/smc/doc/interrupts.adoc.

The bench controller on the I2C0 pads ends transactions early (STOP, repeated START, read NACK)
and sends bare START and STOP symbols against the instance 0 target. The entry list the ACQ FIFO
holds after each abandon, the bus positions that raise UNEXP_STOP and the START_DETECT /
STOP_DETECT race with a write-1-clear are owner value pending: they are measured and
logged, not compared. The repeated-START entries, the recovery transaction after every case,
the read NACK byte, the interrupt register path and the detect-flag lifecycle are compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    _I2C_H,
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_RESTART,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_ACQDATA_ABYTE,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_TARGETIDLE,
    I2C_STATUS_TXEMPTY,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_TARGET_FIFO_STATUS_TXLVL_BM,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_slot_utils import drive_to_slot, park_scl_high
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

I2C0 = 0
ADDR = 0x23
NO_MATCH_ADDR = 0x2A
VIP_SPEED = 2_000_000

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_REGS = {
    "wrap": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR",
    "ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR",
    "status": "SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR",
    "fifo_ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR",
    "target_id": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR",
    "txdata": "SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR",
    "acqdata": "SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR",
    "fifo_status": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR",
    "events": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_EVENTS_BASE_ADDR",
    "intr_state": "SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR",
    "intr_enable": "SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR",
    "intr_test": "SMC_TOP_SMC_I2C_WRAP_I2C_INTR_TEST_BASE_ADDR",
    "timing0": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR",
    "timing1": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR",
    "timing2": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR",
    "timing3": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR",
    "timing4": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR",
}
R = {key: smc_indexed_addr(sym, I2C0) for key, sym in _REGS.items()}

UNEXP_STATE = _field_mask(_I2C_H, "I2C__INTR_STATE__UNEXP_STOP_bm")
UNEXP_ENABLE = _field_mask(_I2C_H, "I2C__INTR_ENABLE__UNEXP_STOP_bm")
UNEXP_TEST = _field_mask(_I2C_H, "I2C__INTR_TEST__UNEXP_STOP_bm")
UNEXP_BP = _field_mask(_I2C_H, "I2C__INTR_STATE__UNEXP_STOP_bp")
START_DETECT = _field_mask(_I2C_H, "I2C__TARGET_EVENTS__START_DETECT_bm")
STOP_DETECT = _field_mask(_I2C_H, "I2C__TARGET_EVENTS__STOP_DETECT_bm")
DETECT = START_DETECT | STOP_DETECT
CPU_IRQ_BIT = 279

CTRL_SSE = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
CTRL_NOSSE = I2C_CTRL_ENABLETARGET

IDLE_POLLS = 400
IDLE_POLL_CYCLES = 200
TXN_WINDOWS = 2000
TXN_WINDOW_CYCLES = 50
EVENT_WINDOWS = 400
EVENT_WINDOW_CYCLES = 20
IRQ_WINDOWS = 200
IRQ_WINDOW_CYCLES = 4
BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4
SWEEP_OFFSETS = (0, 2, 4, 8, 16)

FENCE_ORDER = [f"S{n}" for n in range(1, 11)]
CHECKER_AFTER = {
    "CHK-I2C-TGT-REPSTART-ENTRIES": "S2",
    "CHK-I2C-TGT-ABANDON-READ-NACK": "S5",
    "CHK-I2C-TGT-ABANDON-LOG": "S6",
    "CHK-I2C-TGT-ABANDON-RECOVER": "S6",
    "CHK-I2C-TGT-UNEXP-STOP-LOG": "S7",
    "CHK-I2C-TGT-UNEXP-STOP-REG": "S7",
    "CHK-I2C-TGT-DETECT-FLAGS": "S9",
    "CHK-I2C-TGT-DETECT-RACE-LOG": "S10",
    "CHK-TIMEOUT-PATHS": "S10",
}

Entry = tuple[int, int]


def _fmt(entries: list[Entry]) -> str:
    meaningful = (0, 1, 3, 4, 5)
    return (
        " ".join(
            f"({sig:#x},{abyte:#04x})" if sig in meaningful else f"({sig:#x},-)"
            for sig, abyte in entries
        )
        or "none"
    )


class smc_i2c_target_bus_symbol_test_seq(SmcCsrSeq):
    """Abandoned transactions and bare bus symbols against the I2C0 target."""

    def __init__(self, name: str = "smc_i2c_target_bus_symbol_test_seq") -> None:
        super().__init__(name)
        self.vip: SmcI2cMasterVip | None = None
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.cases: dict[str, dict] = {}
        self.drained: list[Entry] = []

    # ------------------------------------------------------------ plumbing --
    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        self.chk_lines.append((name, line, len(self.stamps)))

    @staticmethod
    async def _cycles(count: int) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, count)

    @staticmethod
    def _probe(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return int(value)

    def _irq(self, instance: int) -> int:
        return (self._probe("tb_i2c_irq") >> instance) & 1

    def _cpu_irq(self) -> int:
        return (self._probe("tb_cpu_interrupts") >> CPU_IRQ_BIT) & 1

    def _pad_levels(self) -> str:
        names = ("scl", "sda", "scl_dut_low", "sda_dut_low")
        return " ".join(f"{n}={self._probe(f'tb_i2c0_{n}')}" for n in names)

    async def _diag(self) -> str:
        status = await self.csr_read("DIAG_STATUS", R["status"])
        events = await self.csr_read("DIAG_EVENTS", R["events"])
        fifo = await self.csr_read("DIAG_FIFO_STATUS", R["fifo_status"])
        intr = await self.csr_read("DIAG_INTR_STATE", R["intr_state"])
        return (
            f"STATUS=0x{status:08x} ACQLVL={(fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> 16} "
            f"TARGET_EVENTS=0x{events:08x} INTR_STATE=0x{intr:08x} {self._pad_levels()}"
        )

    async def _poll(self, name: str, windows: int, gap: int, probe) -> None:
        """Run ``probe`` up to ``windows`` times ``gap`` cycles apart; expiry fails the leaf."""
        bound = f"{windows}x{gap}cyc clk_smc_i"
        state = "never sampled"
        for _ in range(windows):
            done, state = await probe()
            if done:
                self.waits.append((name, bound, state))
                return
            await self._cycles(gap)
        self.waits.append((name, bound, f"EXPIRED {state}"))
        diag = await self._diag()
        raise AssertionError(f"{name}: not satisfied within {bound}; last {state}; {diag}")

    async def _txn(self, name: str, coro, sink: list[Entry] | None = None) -> None:
        """Run a bench controller transaction, draining the ACQ FIFO into ``sink``, bounded.

        The target holds SCL when the ACQ FIFO lacks room for the next entry, so software
        drains while the transaction runs; the pop order is the FIFO order.
        """
        task = cocotb.start_soon(coro)
        into = self.drained if sink is None else sink

        async def probe() -> tuple[bool, str]:
            if task.done():
                task.result()
            popped, _ = await self._pop(f"{name}_DRAIN")
            into.extend(popped)
            return task.done(), f"done={task.done()} drained={len(into)}"

        await self._poll(name, TXN_WINDOWS, TXN_WINDOW_CYCLES, probe)

    async def _wait_idle(self, name: str) -> int:
        async def probe() -> tuple[bool, str]:
            status = await self.csr_read(f"{name}_STATUS", R["status"])
            return bool(status & I2C_STATUS_TARGETIDLE), f"STATUS=0x{status:08x}"

        await self._poll(name, IDLE_POLLS, IDLE_POLL_CYCLES, probe)
        return 1

    async def _wait_events(self, name: str, want: int) -> int:
        seen = [0]

        async def probe() -> tuple[bool, str]:
            seen[0] = await self.csr_read(f"{name}_EVENTS", R["events"])
            return (seen[0] & want) == want, f"events=0x{seen[0]:08x} want=0x{want:x}"

        await self._poll(name, EVENT_WINDOWS, EVENT_WINDOW_CYCLES, probe)
        return seen[0]

    async def _events(self, label: str) -> int:
        return await self.csr_read(label, R["events"])

    async def _unexp(self, label: str) -> int:
        state = await self.csr_read(label, R["intr_state"])
        return (state & UNEXP_STATE) >> UNEXP_BP

    async def _pop(self, label: str) -> tuple[list[Entry], int]:
        """Pop every ACQ entry; returns the entries and TARGET_FIFO_STATUS.TXLVL."""
        fifo = await self.csr_read(f"{label}_FIFO_STATUS", R["fifo_status"])
        level = (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP
        entries: list[Entry] = []
        for i in range(level):
            word = await self.csr_read(f"{label}_ACQDATA{i}", R["acqdata"])
            entries.append(
                ((word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP, word & I2C_ACQDATA_ABYTE)
            )
        return entries, fifo & I2C_TARGET_FIFO_STATUS_TXLVL_BM

    async def _acq_reset(self, label: str) -> None:
        await self.csr_write(f"{label}_ACQRST", R["fifo_ctrl"], I2C_FIFO_CTRL_ACQRST)

    async def _load(self, label: str, data) -> None:
        for i, byte in enumerate(data):
            await self.csr_write(f"{label}_TXDATA{i}", R["txdata"], byte)

    # ---------------------------------------------------------- bus actions --
    async def _write_txn(self, acks: list[int], payload=(0x31, 0x32)) -> None:
        vip = self.vip
        await vip.send_start()
        acks.append(await vip.send_byte(ADDR << 1))
        for value in payload:
            acks.append(await vip.send_byte(value))
        await vip.send_stop()

    async def _recover(self, label: str) -> dict:
        await self._acq_reset(f"{label}_REC")
        await self._wait_idle(f"{label.lower()}_recover_idle")
        acks: list[int] = []
        entries: list[Entry] = []
        await self._txn(f"{label.lower()}_recover_wire", self._write_txn(acks), entries)
        await self._wait_idle(f"{label.lower()}_recover_done")
        entries.extend((await self._pop(f"{label}_REC"))[0])
        unexp = await self._unexp(f"{label}_REC_INTR")
        assert acks == [0, 0, 0], f"{label}: recovery write ACK bits {acks}, expected [0, 0, 0]"
        want = [(I2C_ACQ_SIGNAL_START, ADDR << 1), (I2C_ACQ_SIGNAL_NONE, 0x31)]
        want.append((I2C_ACQ_SIGNAL_NONE, 0x32))
        assert len(entries) == 4, f"{label}: recovery popped {_fmt(entries)}, expected 4 entries"
        assert entries[:3] == want, f"{label}: recovery entries {_fmt(entries)}, want {_fmt(want)}"
        assert entries[3][0] == I2C_ACQ_SIGNAL_STOP, (
            f"{label}: recovery last entry {_fmt(entries[3:])}, expected SIGNAL 0x2"
        )
        return {"acks": acks, "entries": entries, "unexp": unexp}

    async def _case(self, label: str, action, txdata=None) -> dict:
        """One abandon: clean state, run the action, log the ACQ entries, then recover."""
        await self.csr_write(f"{label}_UNEXP_CLR", R["intr_state"], UNEXP_STATE)
        await self.csr_write(
            f"{label}_FIFO_RST", R["fifo_ctrl"], I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )
        await self._wait_idle(f"{label.lower()}_pre_idle")
        if txdata:
            await self._load(label, txdata)
        out: dict = {"acks": [], "data": []}
        entries: list[Entry] = []
        await self._txn(f"{label.lower()}_wire", action(out), entries)
        await self._wait_idle(f"{label.lower()}_idle")
        status = await self.csr_read(f"{label}_STATUS_AFTER", R["status"])
        tail, txlvl = await self._pop(label)
        entries.extend(tail)
        unexp = await self._unexp(f"{label}_INTR_AFTER")
        out.update(
            idle=int(bool(status & I2C_STATUS_TARGETIDLE)),
            entries=entries,
            txlvl=txlvl,
            unexp=unexp,
            rec=await self._recover(label),
        )
        self.cases[label] = out
        cocotb.log.info(
            "%s: acks=%s entries=%s idle=%d txlvl=%d unexp=%d; recovery unexp=%d",
            label,
            out["acks"],
            _fmt(entries),
            out["idle"],
            txlvl,
            unexp,
            out["rec"]["unexp"],
        )
        return out

    # ---------------------------------------------------------------- steps --
    async def _s1_setup(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.arm_i2c_gpio_lsio(0, "I2C0_BUS_SYMBOL")
        await self.csr_write("I2C0_WRAP_TARGET", R["wrap"], I2C_WRAP_CTRL_TARGET)

        async def released() -> tuple[bool, str]:
            scl = self._probe("tb_i2c0_scl")
            sda = self._probe("tb_i2c0_sda")
            scl_i = self._probe("tb_i2c0_scl_i")
            return (scl, sda, scl_i) == (1, 1, 1), f"scl={scl} sda={sda} scl_i={scl_i}"

        await self._poll("bus_released", BUS_RELEASE_POLLS, BUS_RELEASE_STEP, released)
        await self.csr_write("I2C0_TIMING0", R["timing0"], _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", R["timing1"], _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", R["timing2"], _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", R["timing3"], _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", R["timing4"], _pack_timing4(4, 5))
        await self.csr_write(
            "I2C0_FIFO_RST", R["fifo_ctrl"], I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write("I2C0_TARGET_ID", R["target_id"], _pack_target_id(ADDR, 0x7F, 0, 0))
        await self.csr_write("I2C0_CTRL", R["ctrl"], CTRL_SSE)
        await self.csr_write("S1_UNEXP_CLR", R["intr_state"], UNEXP_STATE)
        await self.csr_write("S1_DETECT_CLR", R["events"], DETECT)
        state = await self.csr_read("S1_INTR_STATE", R["intr_state"])
        events = await self.csr_read("S1_EVENTS", R["events"])
        assert not state & UNEXP_STATE, f"S1: INTR_STATE.UNEXP_STOP reads 1 after W1C ({state:#x})"
        assert not events & DETECT, f"S1: TARGET_EVENTS detect bits read 1 after W1C ({events:#x})"
        status = await self.csr_read("S1_STATUS", R["status"])
        assert status & I2C_STATUS_ACQEMPTY, f"S1: STATUS.ACQEMPTY clear (0x{status:08x})"
        assert status & I2C_STATUS_TXEMPTY, f"S1: STATUS.TXEMPTY clear (0x{status:08x})"
        levels = self._pad_levels()
        assert self._probe("tb_i2c0_scl") == 1 and self._probe("tb_i2c0_sda") == 1, levels
        assert self._probe("tb_i2c0_sda_dut_low") == 0, f"S1: the DUT pulls SDA low; {levels}"
        self.vip = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_bus_symbol_master")
        cocotb.log.info("S1: instance 0 target enabled; STATUS=0x%08x %s", status, levels)
        self._stamp("S1")

    async def _s2_repstart(self) -> None:
        await self.csr_write("S2_TXDATA", R["txdata"], 0x5C)
        vip = self.vip
        got: dict = {}

        async def wire() -> None:
            await vip.send_start()
            got["a1"] = await vip.send_byte(ADDR << 1)
            got["a2"] = await vip.send_byte(0x21)
            await vip.send_start()
            got["a3"] = await vip.send_byte((ADDR << 1) | 1)
            got["rd"] = await vip.recv_byte(ack=False)
            await vip.send_stop()

        entries: list[Entry] = []
        await self._txn("s2_wire", wire(), entries)
        await self._wait_idle("s2_idle")
        entries.extend((await self._pop("S2"))[0])
        acks = [got["a1"], got["a2"], got["a3"]]
        assert acks == [0, 0, 0], f"S2: ACK bits {acks}, expected [0, 0, 0]"
        assert got["rd"] == 0x5C, f"S2: read byte {got['rd']:#04x}, expected 0x5c"
        want = [
            (I2C_ACQ_SIGNAL_START, ADDR << 1),
            (I2C_ACQ_SIGNAL_NONE, 0x21),
            (I2C_ACQ_SIGNAL_RESTART, (ADDR << 1) | 1),
        ]
        assert entries[:3] == want, f"S2: first entries {_fmt(entries)}, expected {_fmt(want)}"
        self._stamp("S2")
        self._chk(
            "CHK-I2C-TGT-REPSTART-ENTRIES",
            f"write, repeated START, read: ack bits {acks}; read byte {got['rd']:#04x} == 0x5c; "
            f"first three entries {_fmt(entries[:3])} == {_fmt(want)}; all entries {_fmt(entries)}",
        )

    def _abandon_actions(self):
        vip = self.vip

        async def early_stop_addr(out: dict) -> None:
            await drive_to_slot(vip, ADDR, 0x31, "addr", 4)
            await vip.send_stop()

        async def stop_mid_data(out: dict) -> None:
            await drive_to_slot(vip, ADDR, 0x31, "data", 4)
            await vip.send_stop()

        async def restart_mid_data(out: dict) -> None:
            await drive_to_slot(vip, ADDR, 0x31, "data", 4)
            await vip.send_start()
            out["acks"].append(await vip.send_byte(ADDR << 1))
            await vip.send_stop()

        async def stop_after_ack(out: dict) -> None:
            await vip.send_start()
            out["acks"].append(await vip.send_byte(ADDR << 1))
            await vip.send_stop()

        return early_stop_addr, stop_mid_data, restart_mid_data, stop_after_ack

    async def _s3_case_a(self) -> None:
        early_stop_addr, *_ = self._abandon_actions()
        await self._case("CASE_A", early_stop_addr)
        self._stamp("S3")

    async def _s4_cases_bc(self) -> None:
        _, stop_mid_data, restart_mid_data, _ = self._abandon_actions()
        await self._case("CASE_B", stop_mid_data)
        await self._case("CASE_C", restart_mid_data)
        self._stamp("S4")

    async def _s5_read_nack(self) -> None:
        vip = self.vip

        async def read_nack(out: dict) -> None:
            await vip.send_start()
            out["acks"].append(await vip.send_byte((ADDR << 1) | 1))
            out["data"].append(await vip.recv_byte(ack=False))
            await vip.send_stop()

        out = await self._case("CASE_D", read_nack, txdata=(0x61, 0x62, 0x63))
        assert out["acks"] == [0], f"S5: read address ACK bits {out['acks']}, expected [0]"
        assert out["data"] == [0x61], f"S5: first byte read {out['data']}, expected [0x61]"
        self._stamp("S5")
        self._chk(
            "CHK-I2C-TGT-ABANDON-READ-NACK",
            f"read address ack bits {out['acks']} == [0]; first byte {out['data'][0]:#04x} == "
            f"0x61 before the NACK and STOP; TXLVL after={out['txlvl']}; UNEXP_STOP after="
            f"{out['unexp']}",
        )

    async def _s6_case_e(self) -> None:
        *_, stop_after_ack = self._abandon_actions()
        await self._case("CASE_E", stop_after_ack)
        self._stamp("S6")
        rows = []
        rec_rows = []
        for label, c in self.cases.items():
            rows.append(
                f"{label}: entries {_fmt(c['entries'])} idle={c['idle']} txlvl={c['txlvl']}"
            )
            rec_rows.append(f"{label}: acks {c['rec']['acks']} entries {_fmt(c['rec']['entries'])}")
        self._chk(
            "CHK-I2C-TGT-ABANDON-LOG",
            "observe-and-log (owner value pending): " + "; ".join(rows),
        )
        self._chk(
            "CHK-I2C-TGT-ABANDON-RECOVER",
            "each case recovered after ACQRST and TARGETIDLE=1, ack bits [0, 0, 0] and entries "
            "(0x1,0x46) (0x0,0x31) (0x0,0x32) (0x2,-) exactly: " + "; ".join(rec_rows),
        )

    async def _lines(self, want_irq: int, name: str) -> str:
        seen = [""]

        async def probe() -> tuple[bool, str]:
            irq0, cpu = self._irq(0), self._cpu_irq()
            seen[0] = f"tb_i2c_irq[0]={irq0} tb_cpu_interrupts[{CPU_IRQ_BIT}]={cpu}"
            return (irq0, cpu) == (want_irq, want_irq), seen[0]

        await self._poll(name, IRQ_WINDOWS, IRQ_WINDOW_CYCLES, probe)
        return seen[0]

    def _others_low(self, where: str) -> None:
        for n in (1, 2):
            assert self._irq(n) == 0, f"{where}: tb_i2c_irq[{n}] is high"

    async def _s7_unexp_register(self) -> None:
        reg_rows = []
        await self.csr_write("S7_ENABLE_OFF", R["intr_enable"], 0)
        await self.csr_write("S7_UNEXP_CLR", R["intr_state"], UNEXP_STATE)
        await self.csr_write("S7_INTR_TEST", R["intr_test"], UNEXP_TEST)
        state = await self._unexp("S7_AFTER_TEST")
        assert state == 1, "S7: INTR_TEST did not set INTR_STATE.UNEXP_STOP"
        irq0, cpu = self._irq(0), self._cpu_irq()
        assert (irq0, cpu) == (0, 0), (
            f"S7: line high with INTR_ENABLE.UNEXP_STOP=0 (irq0={irq0} cpu{CPU_IRQ_BIT}={cpu})"
        )
        self._others_low("S7 enable clear")
        reg_rows.append(f"set state={state}; enable clear irq0={irq0} cpu{CPU_IRQ_BIT}={cpu}")
        await self.csr_write("S7_ENABLE_ON", R["intr_enable"], UNEXP_ENABLE)
        high = await self._lines(1, "s7_lines_high")
        self._others_low("S7 enable set")
        reg_rows.append(f"enable set {high}")
        await self.csr_write("S7_UNEXP_CLR2", R["intr_state"], UNEXP_STATE)
        cleared = await self._unexp("S7_AFTER_CLR")
        assert cleared == 0, "S7: INTR_STATE.UNEXP_STOP survived the write of 1"
        low = await self._lines(0, "s7_lines_low")
        self._others_low("S7 cleared")
        reg_rows.append(f"cleared state={cleared} {low}")
        early_stop_addr, *_ = self._abandon_actions()
        await self._txn("s7_second_stop_wire", early_stop_addr({}))
        await self._wait_idle("s7_second_stop_idle")
        second = await self._unexp("S7_SECOND_STOP")
        second_lines = f"tb_i2c_irq[0]={self._irq(0)} tb_cpu_interrupts[{CPU_IRQ_BIT}]="
        second_lines += str(self._cpu_irq())
        await self.csr_write("S7_ENABLE_RESTORE", R["intr_enable"], 0)
        await self.csr_write("S7_UNEXP_CLR3", R["intr_state"], UNEXP_STATE)
        await self._acq_reset("S7")
        self._stamp("S7")
        rows = [
            f"{label}: after case {c['unexp']}, after recovery {c['rec']['unexp']}"
            for label, c in self.cases.items()
        ]
        self._chk(
            "CHK-I2C-TGT-UNEXP-STOP-LOG",
            "observe-and-log (owner value pending): UNEXP_STOP "
            + "; ".join(rows)
            + f"; second early STOP of case A after a write-1-clear {second} ({second_lines})",
        )
        self._chk(
            "CHK-I2C-TGT-UNEXP-STOP-REG",
            "; ".join(reg_rows) + "; tb_i2c_irq[1] and tb_i2c_irq[2] stayed 0 at every sample",
        )

    async def _s8_flags(self) -> dict:
        vip = self.vip
        rows = []

        async def one(out: list[int]) -> None:
            await vip.send_start()
            out.append(await vip.send_byte(ADDR << 1))
            out.append(await vip.send_byte(0x41))
            await vip.send_stop()

        await self.csr_write("S8_CTRL_NOSSE", R["ctrl"], CTRL_NOSSE)
        await self._acq_reset("S8")
        await self._wait_idle("s8_idle")
        await self.csr_write("S8_DETECT_CLR", R["events"], DETECT)
        acks_first: list[int] = []
        await self._txn("s8_first_wire", one(acks_first))
        after_first = await self._wait_events("s8_first_events", DETECT)
        assert after_first & DETECT == DETECT, f"S8: events {after_first:#x} after one write"
        acks_more: list[int] = []
        for i in range(2):
            await self._txn(f"s8_more{i}_wire", one(acks_more))
            await self._wait_idle(f"s8_more{i}_idle")
        after_more = await self._events("S8_AFTER_MORE")
        assert after_more & DETECT == DETECT, f"S8: events {after_more:#x} after two more"
        await self.csr_write("S8_DETECT_CLR2", R["events"], DETECT)
        cleared = await self._events("S8_AFTER_CLR")
        assert cleared & DETECT == 0, f"S8: events {cleared:#x} after the write of 1"
        await self.csr_write("S8_CTRL_OFF", R["ctrl"], 0)
        acks_off: list[int] = []
        await self._txn("s8_off_wire", one(acks_off))
        await self._wait_idle("s8_off_idle")
        after_off = await self._events("S8_AFTER_OFF")
        assert after_off & DETECT == 0, f"S8: events {after_off:#x} with ENABLETARGET=0"
        rows.append(
            f"START_DETECT/STOP_DETECT after one write {after_first >> 3 & 3:#x}; after two "
            f"more {after_more >> 3 & 3:#x}; after W1C {cleared >> 3 & 3:#x}; with ENABLETARGET=0 "
            f"{after_off >> 3 & 3:#x} (ack bits {acks_first} {acks_more} {acks_off})"
        )
        self._stamp("S8")
        return {"rows": rows}

    async def _s9_restart(self, s8: dict) -> None:
        vip = self.vip
        acks: list[int] = []

        async def first(out: list[int]) -> None:
            await vip.send_start()
            out.append(await vip.send_byte(ADDR << 1))
            out.append(await vip.send_byte(0x41))

        async def second(out: list[int]) -> None:
            await vip.send_start()
            out.append(await vip.send_byte(ADDR << 1))
            out.append(await vip.send_byte(0x42))
            await vip.send_stop()

        await self.csr_write("S9_CTRL", R["ctrl"], CTRL_NOSSE)
        await self._acq_reset("S9")
        await self.csr_write("S9_DETECT_CLR", R["events"], DETECT)
        await self._txn("s9_first_wire", first(acks))
        before = await self._wait_events("s9_start_set", START_DETECT)
        await self.csr_write("S9_START_CLR", R["events"], START_DETECT)
        after_clr = await self._events("S9_AFTER_CLR")
        assert after_clr & START_DETECT == 0, f"S9: START_DETECT reads 1 after W1C ({after_clr:#x})"
        await self._txn("s9_second_wire", second(acks))
        after_restart = await self._wait_events("s9_restart_events", START_DETECT)
        await self._wait_idle("s9_idle")
        self._stamp("S9")
        self._chk(
            "CHK-I2C-TGT-DETECT-FLAGS",
            "; ".join(s8["rows"])
            + f"; lifecycle START_DETECT set={before >> 3 & 1} observed, cleared by W1C, "
            f"checked_cleared={after_clr >> 3 & 1}, repeated START set it again="
            f"{after_restart >> 3 & 1} (ack bits {acks})",
        )

    async def _timed_stop(self, delay: int) -> None:
        vip = self.vip
        if delay:
            await self._cycles(delay)
        vip._pull_sda(False)

    async def _s10_race(self) -> None:
        vip = self.vip
        await self.csr_write("S10_CTRL", R["ctrl"], CTRL_SSE)
        await self._acq_reset("S10")
        await self._wait_idle("s10_idle0")
        await self.csr_write("S10_DETECT_CLR", R["events"], DETECT)
        await self.csr_write("S10_UNEXP_CLR", R["intr_state"], UNEXP_STATE)
        acks: list[int] = []

        async def mismatch() -> None:
            await vip.send_start()
            acks.append(await vip.send_byte(NO_MATCH_ADDR << 1))
            await vip.send_stop()

        await self._txn("s10_nomatch_wire", mismatch())
        await self._wait_idle("s10_nomatch_idle")
        events = await self._events("S10_NOMATCH_EVENTS")
        unexp = await self._unexp("S10_NOMATCH_INTR")
        rows = [
            f"no-match 0x{NO_MATCH_ADDR:02x}: ack {acks} START_DETECT={events >> 3 & 1} "
            f"STOP_DETECT={events >> 4 & 1} UNEXP_STOP={unexp}"
        ]
        timings = [("at", 0)]
        timings += [(side, d) for d in SWEEP_OFFSETS[1:] for side in ("before", "after")]
        for target, clear_reg, clear_val in (
            ("STOP_DETECT", R["events"], STOP_DETECT),
            ("UNEXP_STOP", R["intr_state"], UNEXP_STATE),
        ):
            for side, d in timings:
                tag = f"S10_{target}_{side}{d}"
                if target == "UNEXP_STOP":
                    await self.csr_write(f"{tag}_SET", R["intr_test"], UNEXP_TEST)
                pre_events = await self._events(f"{tag}_PRE_EVENTS")
                pre_unexp = await self._unexp(f"{tag}_PRE_INTR")
                await vip.send_start()
                await park_scl_high(vip, vip._half_ns)
                if side == "after":
                    vip._pull_sda(False)
                    await self._cycles(d)
                    await self.csr_write(f"{tag}_CLR", clear_reg, clear_val)
                else:
                    release = cocotb.start_soon(self._timed_stop(d))
                    await self.csr_write(f"{tag}_CLR", clear_reg, clear_val)
                    await release
                await Timer(vip._half_ns, unit="ns")
                vip._active = False
                await self._wait_idle(f"s10_{target.lower()}_{side}{d}_idle")
                events = await self._events(f"{tag}_EVENTS")
                unexp = await self._unexp(f"{tag}_INTR")
                rows.append(
                    f"clear {target} {side} {d}cyc: pre START/STOP={pre_events >> 3 & 3} "
                    f"UNEXP={pre_unexp}; post START_DETECT={events >> 3 & 1} "
                    f"STOP_DETECT={events >> 4 & 1} UNEXP_STOP={unexp}; idle=1"
                )
        self._stamp("S10")
        self._chk(
            "CHK-I2C-TGT-DETECT-RACE-LOG",
            "observe-and-log (owner value pending): "
            + "; ".join(rows)
            + "; the sweep places the clear near the STOP and proves no same-cycle coincidence",
        )

    # --------------------------------------------------------------- tokens --
    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
        ]
        vip = self.vip
        own = [
            (
                "vip_scl_release",
                f"{vip.scl_timeout_ns}ns",
                f"last SCL hold {vip.last_scl_hold_ns}ns",
            )
        ]
        axi = ("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses completed")
        waits = inherited + self.waits + own + [axi]
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(waits)} bounded waits, each raising AssertionError with its last state on "
            f"expiry; " + "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
        )

    def _emit_checks(self) -> None:
        order = [term for term, _ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = {name: idx for name, _, idx in self.chk_lines}
        for name, term in CHECKER_AFTER.items():
            assert name in printed, f"{name} never recorded"
            assert printed[name] > order.index(term), f"{name} recorded before {term}"
        for name, line, _ in self.chk_lines:
            cocotb.log.info("%s: %s", name, line)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(f"{t}={ps}" for t, ps in self.stamps),
            ",".join(name for name, _, _ in self.chk_lines),
            ",".join(str(ps) for ps in times),
        )

    async def body(self) -> None:
        await self._s1_setup()
        await self._s2_repstart()
        await self._s3_case_a()
        await self._s4_cases_bc()
        await self._s5_read_nack()
        await self._s6_case_e()
        await self._s7_unexp_register()
        s8 = await self._s8_flags()
        await self._s9_restart(s8)
        await self._s10_race()
        self._emit_timeout_paths()
        self._emit_checks()
