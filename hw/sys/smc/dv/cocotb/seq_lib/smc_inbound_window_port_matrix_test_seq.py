# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base registers, window words and scratch storage on sep, sys and jtag at both bases.

Spec sources: fabric.adoc Fabric Topology and Alias Remapping, memmap.adoc Memory Map,
smc_base_config.rdl resets.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

LOCAL_BASE = LOCAL_BASE_RESET
GLOBAL_BASE = GLOBAL_BASE_RESET
BASES = (("LOCAL", LOCAL_BASE), ("GLOBAL", GLOBAL_BASE))
PORTS = ("SEP", "SYS", "JTAG")
GLOBAL_BASE_WORD = GLOBAL_BASE_RESET
LOCAL_BASE_WORD = LOCAL_BASE_RESET
REGION_SIZE_WORD = REGION_SIZE_RESET
BASE_REGS = (
    ("GLOBAL_BASE", 0x0, GLOBAL_BASE_WORD),
    ("LOCAL_BASE", 0x8, LOCAL_BASE_WORD),
    ("REGION_SIZE", 0x10, REGION_SIZE_WORD),
)
WDT_CTRL_RESET = 0x0
BASE_CONFIG_OFFSET = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR") - LOCAL_BASE
MID_OFFSET = 0x000E_0000
LAST_OFFSET = 0x00FF_FFF8
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
ADMIT_POLL_BOUND_CYCLES = 6_000
AXI_TIMEOUT_NS = 50_000
STIMULUS_FLOOR = 79
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}


def _scratch(index: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", index)


SCRATCH_OFFSETS = tuple(_scratch(i) - LOCAL_BASE for i in range(4))
WDT_CTRL_ADDR = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
assert WDT_CTRL_ADDR == LOCAL_BASE
SCRATCH_PATTERNS = (0x1A2B_3C4D, 0x5E6F_7A8B, 0x9C0D_1E2F, 0xB3A4_9586)
MID_PATTERNS = {
    ("SYS", "LOCAL"): 0x1111_2222_3333_4444,
    ("SYS", "GLOBAL"): 0x5555_6666_7777_8888,
    ("SEP", "LOCAL"): 0x9999_AAAA_BBBB_CCCC,
    ("SEP", "GLOBAL"): 0xDDDD_EEEE_0F0F_1E1E,
}
# (scratch index, writer port, write base, ((reader port, read base), ...)).
CROSS_LEGS = (
    (0, "SEP", "LOCAL", (("SYS", "GLOBAL"), ("JTAG", "GLOBAL"))),
    (1, "SYS", "GLOBAL", (("JTAG", "LOCAL"), ("SEP", "LOCAL"))),
    (2, "JTAG", "LOCAL", (("SEP", "GLOBAL"), ("SYS", "GLOBAL"))),
)

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_FENCE = "SETUP_PASS_ALL<LOCAL_READS<GLOBAL_READS<WINDOW_WORDS<CROSS_BASE_WRITES<JTAG_LEG<RESTORE"
_CHECKERS = (
    ("CHK-WIN-LOCAL-BASEREG-PORTS", "S2"),
    ("CHK-WIN-LOCAL-REGS-PORTS", "S2"),
    ("CHK-WIN-GLOBAL-RESET-PORTS", "S3"),
    ("CHK-SYS-SEP-WINDOW-WORDS", "S4"),
    ("CHK-WIN-CROSS-BASE-STORAGE", "S5"),
    ("CHK-JTAG-CROSS-PORT-STORAGE", "S5"),
    ("CHK-JTAG-LOCAL-WINDOW", "S6"),
)


class _ProbeWatch:
    """Samples tb_top probes at clk_smc_i edges and keeps the OR of every sampled value.

    A probe named in ``gates`` is counted only on edges where its gate signal is high; the
    ungated OR is kept in ``idle_seen`` for the log.
    """

    def __init__(self, names: tuple[str, ...], gates: dict[str, str] | None = None) -> None:
        self.names = names
        self.gates = gates or {}
        self.gated_samples = dict.fromkeys(self.gates, 0)
        self.idle_seen = dict.fromkeys(names, 0)
        self.stop = False
        self.samples = 0
        self.seen = dict.fromkeys(names, 0)

    async def run(self) -> None:
        dut = cocotb.top
        while not self.stop:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            for name in self.names:
                value = getattr(dut, name).value
                assert value.is_resolvable, f"{name} is X/Z at sample {self.samples}"
                self.idle_seen[name] |= int(value)
                gate = self.gates.get(name)
                if gate is not None:
                    gate_value = getattr(dut, gate).value
                    assert gate_value.is_resolvable, f"{gate} is X/Z at sample {self.samples}"
                    if not int(gate_value):
                        continue
                    self.gated_samples[name] += 1
                self.seen[name] |= int(value)
            self.samples += 1


class smc_inbound_window_port_matrix_test_seq(SmcCsrSeq):
    """Drive the three inbound ports at the local and the global base of the SMC window."""

    def __init__(self, name: str = "smc_inbound_window_port_matrix_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.admit_state = "not polled"
        self.watch_state = "no watcher"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _sequencer(self, port: str):
        agent = {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }[port]
        return agent.sequencer

    def _item(self, port, op, label, addr, length, wdata, expected, allow_error):
        item = SmcSysAxiItem(f"{port.lower()}_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = wdata
        item.expected = expected
        item.allow_error = allow_error
        return item

    async def _rd(
        self,
        port: str,
        label: str,
        addr: int,
        length: int = 8,
        *,
        expected: int | None = None,
        allow_error: bool = False,
    ) -> SmcSysAxiItem:
        item = self._item(port, SmcSysAxiOp.READ, label, addr, length, 0, expected, allow_error)
        await _OneShot(item, f"{port.lower()}_{label}_os").start(self._sequencer(port))
        self.accesses += 1
        assert item.resp_code is not None, f"{port} {label} @ 0x{addr:08x}: no response recorded"
        mask = (1 << (8 * length)) - 1
        item.value = item.rdata & mask
        if not allow_error:
            assert item.resp_code == 0, (
                f"{port} {label} @ 0x{addr:08x}: rresp {_RESP_NAMES.get(item.resp_code)}"
            )
        return item

    async def _wr(
        self,
        port: str,
        label: str,
        addr: int,
        data: int,
        length: int = 8,
        *,
        allow_error: bool = False,
    ) -> SmcSysAxiItem:
        item = self._item(port, SmcSysAxiOp.WRITE, label, addr, length, data, None, allow_error)
        await _OneShot(item, f"{port.lower()}_{label}_os").start(self._sequencer(port))
        self.accesses += 1
        assert item.resp_code is not None, f"{port} {label} @ 0x{addr:08x}: no bresp recorded"
        if not allow_error:
            assert item.resp_code == 0, (
                f"{port} {label} @ 0x{addr:08x}: bresp {_RESP_NAMES.get(item.resp_code)}"
            )
        return item

    async def _rd_eq(self, port, label, addr, want, length=8) -> int:
        item = await self._rd(port, label, addr, length, expected=want)
        assert item.value == want, (
            f"{port} {label} @ 0x{addr:08x}: read 0x{item.value:x}, want 0x{want:x}"
        )
        return item.value

    async def _s1_setup_and_admit(self) -> str:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        dut = cocotb.top
        item = self._item("SYS", SmcSysAxiOp.READ, "S1_PROBE", LOCAL_BASE, 4, 0, None, False)
        task = cocotb.start_soon(_OneShot(item, "sys_S1_PROBE_os").start(self._sequencer("SYS")))
        cycles = 0
        hits = 0
        isolated = 0
        while not task.done():
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            cycles += 1
            self.admit_state = f"{cycles} cycles, read_hit[0] seen {hits}"
            assert cycles <= ADMIT_POLL_BOUND_CYCLES, (
                f"sys_axi_in probe read of LOCAL_BASE not answered in {cycles} cycles"
            )
            hit = dut.tb_inb_read_hit.value
            iso = dut.tb_inb_isolate_read.value
            assert hit.is_resolvable and iso.is_resolvable, "inbound filter probe is X/Z"
            hits += int(hit) & 1
            isolated += int(iso)
        await RisingEdge(dut.clk_smc_i)
        await task
        self.accesses += 1
        assert item.resp_code == 0, f"admitted probe read answered {item.resp_code}, want OKAY"
        assert hits > 0, f"tb_inb_read_hit[0] never set in {cycles} cycles of the probe read"
        self.admit_state = f"{cycles} cycles, read_hit[0] seen {hits}, isolate_read {isolated}"
        return (
            f"entry 0 pass-all programmed over sep_axi_in; sys_axi_in read of 0x{LOCAL_BASE:08X} "
            f"OKAY rdata 0x{item.rdata & 0xFFFF_FFFF:X} with tb_inb_read_hit[0] high for "
            f"{hits} samples in {cycles} cycles (tb_inb_isolate_read high {isolated})"
        )

    async def _base_matrix(self, base_name: str, base: int) -> dict[tuple[str, str], int]:
        got = {}
        for port in PORTS:
            for reg, offset, want in BASE_REGS:
                got[(port, reg)] = await self._rd_eq(
                    port, f"{base_name}_{reg}", base + BASE_CONFIG_OFFSET + offset, want
                )
        return got

    async def _first_word(self, port: str, base_name: str, base: int) -> str:
        pre = await self._rd(port, f"{base_name}_WDT_CTRL_RD", base, 4, expected=WDT_CTRL_RESET)
        assert pre.value == WDT_CTRL_RESET, (
            f"{port}@{base_name} WDT CTRL read 0x{pre.value:x}, RDL reset 0x{WDT_CTRL_RESET:x}"
        )
        await self._wr(port, f"{base_name}_WDT_CTRL_WR", base, WDT_CTRL_RESET, 4)
        post = await self._rd(port, f"{base_name}_WDT_CTRL_RB", base, 4)
        assert post.value == WDT_CTRL_RESET, (
            f"{port}@{base_name} WDT CTRL after write 0x{post.value:x}, want 0x{WDT_CTRL_RESET:x}"
        )
        return f"first=0x{post.value:X}"

    async def _mid_word(self, port: str, base_name: str, base: int) -> str:
        pattern = MID_PATTERNS[(port, base_name)]
        addr = base + MID_OFFSET
        await self._wr(port, f"{base_name}_SPM_WR", addr, pattern)
        await self._rd_eq(port, f"{base_name}_SPM_RB", addr, pattern)
        return f"mid=0x{pattern:X}"

    async def _last_word(self, port: str, base_name: str, base: int) -> str:
        addr = base + LAST_OFFSET
        self.env.axi_monitor.expected_decerr_addrs.add(addr)
        rd = await self._rd(port, f"{base_name}_LAST_RD", addr, 8, allow_error=True)
        wr = await self._wr(port, f"{base_name}_LAST_WR", addr, 0, 8, allow_error=True)
        return (
            f"last@0x{addr:08X} rresp={_RESP_NAMES.get(rd.resp_code)} rdata=0x{rd.value:X} "
            f"bresp={_RESP_NAMES.get(wr.resp_code)}"
        )

    async def _s4_window_words(self) -> str:
        watch = _ProbeWatch(("tb_output_axi_awvalid", "tb_output_axi_arvalid"))
        task = cocotb.start_soon(watch.run())
        parts = []
        for port in ("SYS", "SEP"):
            for base_name, base in BASES:
                first = await self._first_word(port, base_name, base)
                mid = await self._mid_word(port, base_name, base)
                last = await self._last_word(port, base_name, base)
                parts.append(f"{port}@{base_name} {first} {mid} {last}")
        watch.stop = True
        await task
        assert watch.samples > 0, "output_axi probes were never sampled"
        assert all(v == 0 for v in watch.seen.values()), (
            f"request seen on output_axi during window accesses: {watch.seen}"
        )
        self.watch_state = f"S4 probe watcher {watch.samples} samples"
        return (
            f"{'; '.join(parts)}; tb_output_axi_awvalid/arvalid never high in "
            f"{watch.samples} samples (last-word answer is observe-only, not specified, measured)"
        )

    async def _s5_cross_base(self) -> tuple[str, str]:
        legs = []
        for index, writer, wbase, readers in CROSS_LEGS:
            pattern = SCRATCH_PATTERNS[index]
            offset = SCRATCH_OFFSETS[index]
            await self._wr(
                writer, f"SCRATCH{index}_{wbase}_WR", dict(BASES)[wbase] + offset, pattern, 4
            )
            for rport, rbase in readers:
                assert rport != writer and rbase != wbase
                await self._rd_eq(
                    rport, f"SCRATCH{index}_{rbase}_RB", dict(BASES)[rbase] + offset, pattern, 4
                )
            legs.append(
                f"SCRATCH_COLD[{index}]=0x{pattern:08X} written {writer}@{wbase} read "
                + ",".join(f"{p}@{b}" for p, b in readers)
            )
        return "; ".join(legs)

    async def _s6_jtag_leg(self) -> str:
        watch = _ProbeWatch(
            ("tb_remap_jtag_ar_hit", "tb_remap_jtag_aw_hit"),
            {
                "tb_remap_jtag_ar_hit": "jtag_axi_arvalid",
                "tb_remap_jtag_aw_hit": "jtag_axi_awvalid",
            },
        )
        task = cocotb.start_soon(watch.run())
        parts = []
        for base_name, base in BASES:
            await self._rd_eq(
                "JTAG",
                f"{base_name}_REGION_SIZE",
                base + BASE_CONFIG_OFFSET + 0x10,
                REGION_SIZE_WORD,
            )
            addr = base + SCRATCH_OFFSETS[3]
            await self._wr("JTAG", f"{base_name}_SCRATCH3_WR", addr, SCRATCH_PATTERNS[3], 4)
            await self._rd_eq("JTAG", f"{base_name}_SCRATCH3_RB", addr, SCRATCH_PATTERNS[3], 4)
            parts.append(f"{base_name} REGION_SIZE=0x{REGION_SIZE_WORD:X} SCRATCH_COLD[3] ok")
        watch.stop = True
        await task
        assert all(n > 0 for n in watch.gated_samples.values()), (
            f"remap hit probes never sampled with a jtag request valid: {watch.gated_samples}"
        )
        self.watch_state += f"; S6 probe watcher {watch.samples} samples"
        return (
            f"{'; '.join(parts)}; tb_remap_jtag_ar_hit/aw_hit observe-only "
            f"OR while arvalid/awvalid high "
            f"({watch.gated_samples['tb_remap_jtag_ar_hit']}/"
            f"{watch.gated_samples['tb_remap_jtag_aw_hit']} samples) = "
            f"0x{watch.seen['tb_remap_jtag_ar_hit']:X}/0x{watch.seen['tb_remap_jtag_aw_hit']:X}; "
            f"ungated OR over {watch.samples} samples = "
            f"0x{watch.idle_seen['tb_remap_jtag_ar_hit']:X}/"
            f"0x{watch.idle_seen['tb_remap_jtag_aw_hit']:X}"
        )

    async def _s7_restore(self) -> None:
        for index in range(4):
            await self.csr_write(f"SCRATCH{index}_RESTORE", _scratch(index), 0)
        for index in range(4):
            await self.csr_read(f"SCRATCH{index}_RESTORE_RB", _scratch(index), expected=0)
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
        )
        for name, addr, want in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT),
            ("END", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT),
            ("START", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT),
        ):
            await self.csr_read(f"INBOUND0_{name}_RESTORE_RB", addr, expected=want, length=8)

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)

        admit = await self._s1_setup_and_admit()
        self._mark_step("S1")

        local = await self._base_matrix("LOCAL", LOCAL_BASE)
        self._mark_step("S2")
        self._log_chk(
            "CHK-WIN-LOCAL-BASEREG-PORTS",
            "LOCAL_BASE read at 0x%08X+0x%X+0x8 = %s; %s"
            % (
                LOCAL_BASE,
                BASE_CONFIG_OFFSET,
                ", ".join(f"{p}=0x{local[(p, 'LOCAL_BASE')]:X}" for p in PORTS),
                admit,
            ),
        )
        self._log_chk(
            "CHK-WIN-LOCAL-REGS-PORTS",
            "; ".join(
                f"{p}: " + ", ".join(f"{r}@+0x{o:X}=0x{local[(p, r)]:X}" for r, o, _ in BASE_REGS)
                for p in PORTS
            ),
        )

        glob = await self._base_matrix("GLOBAL", GLOBAL_BASE)
        assert glob == local, f"global-side reads {glob} differ from local-side reads {local}"
        self._mark_step("S3")
        self._log_chk(
            "CHK-WIN-GLOBAL-RESET-PORTS",
            "; ".join(
                f"{p}: " + ", ".join(f"{r}=0x{glob[(p, r)]:X}" for r, _, _ in BASE_REGS)
                for p in PORTS
            )
            + f" at 0x{GLOBAL_BASE:08X}, each equal to the LOCAL_BASE-side read, all OKAY",
        )

        words = await self._s4_window_words()
        self._mark_step("S4")
        self._log_chk("CHK-SYS-SEP-WINDOW-WORDS", words)

        legs = await self._s5_cross_base()
        self._mark_step("S5")
        self._log_chk("CHK-WIN-CROSS-BASE-STORAGE", legs)
        self._log_chk(
            "CHK-JTAG-CROSS-PORT-STORAGE",
            "jtag-written SCRATCH_COLD[2] read exactly via sep and sys; sep-written [0] and "
            "sys-written [1] read exactly via jtag",
        )

        jtag = await self._s6_jtag_leg()
        self._mark_step("S6")
        self._log_chk("CHK-JTAG-LOCAL-WINDOW", jtag)

        await self._s7_restore()
        self._mark_step("S7")

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; S1 admit poll bounded %d clk_smc_i rises, last observed %s; probe "
            "watcher joins each bounded by one clk_smc_i rise after stop, last observed %s; "
            "%d AXI accesses each bounded by the driver timeout %d ns (allow_timeout False), "
            "all answered; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            ADMIT_POLL_BOUND_CYCLES,
            self.admit_state,
            self.watch_state,
            self.accesses,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d >= floor %d; stamps %s",
            _FENCE,
            ",".join(chk_ids),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
