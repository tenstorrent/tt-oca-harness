# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_W2T_010 ANCHOR: smc_gpio_pad_enable_walk_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 3d0201cf329d14595dccfaef9bf57982d71c8c9d54c10481ce90dda0da37d9b6
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_W2T_VPLAN_DETAIL_ADDITIONS.md @ artifact_revision 4 ENV: cocotb
"""Per-pad GPIO DATA_CTRL / DATA_CTRL_ENABLE control observed at the pad.

DATA_CTRL (`gpio_intf.adoc`): core2pad [0], enable_rx_tx [5:4] (00 neither,
01 TX, 10 RX, 11 both), interface_enable [16], lsio_select [17],
interrupt_enable [18], lsio_disable [19], interrupt_type [21:20], all RW;
lsio_enable [25] and pad2core [31] are R. DATA_CTRL_ENABLE: use_reg_core2pad
[0], use_reg_tx [4], use_reg_rx [5], RW, each OR'd with interface_enable.
interface_enable selects the register values to drive the pad.

Every GPIO interface except the pads the bench drives itself (11, 27, 28, 37,
38, 51, 55, 56, 57) is walked, 56 in all, phase by phase: field readback, TX
output and enable, direction enables, RX capture into pad2core from a bench
pad drive, interface_enable clear, the use_reg_* overrides, and the restore.
Interface p drives pad p, observed through `tb_core2pad_o`,
`tb_core2pad_en_o` and `tb_pad2core_en_o`. A hardware LSIO request outranks
interface_enable and lsio_disable gates it, so every TX, direction, RX and
use_reg_* word sets lsio_disable. The RX drive leaves out pads 53 and 61, whose
inputs feed the isolate request and the cool-reset input (SF-023). With
interface_enable and every use_reg_* clear the pad values are logged, not
compared (SF-022 is open).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_gpio_vip_utils import drive_gpio_pad
from .smc_pad_table import gpio_pad_count

FUSE_BOUND = 200_000
#: Clock cycles of clk_smc_i a probe poll waits for its expected value.
PROBE_BOUND_CYCLES = 64
#: DATA_CTRL reads a pad2core poll issues before it fails.
PAD2CORE_BOUND_READS = 8

# gpio_intf.adoc DATA_CTRL.
CORE2PAD = 1 << 0
RX_TX_SHIFT = 4
IF_ENABLE = 1 << 16
LSIO_SELECT = 1 << 17
IRQ_ENABLE = 1 << 18
LSIO_DISABLE = 1 << 19
IRQ_TYPE = 0b11 << 20
LSIO_ENABLE = 1 << 25
PAD2CORE = 1 << 31
DATA_CTRL_RW = 0x003F_0031
# gpio_intf.adoc DATA_CTRL_ENABLE.
USE_REG_CORE2PAD = 1 << 0
USE_REG_TX = 1 << 4
USE_REG_RX = 1 << 5
DATA_CTRL_ENABLE_RW = USE_REG_RX | USE_REG_TX | USE_REG_CORE2PAD


def _dir(rx_tx: int) -> int:
    return rx_tx << RX_TX_SHIFT


#: Pads the bench drives itself under the default plusargs.
EXCLUDED_PADS = (11, 27, 28, 37, 38, 51, 55, 56, 57)
WALKED_COUNT = 56
#: Walked pads the RX leg does not drive: isolate request and cool-reset input.
RX_SKIPPED_PADS = (53, 61)
RX_COUNT = 54
#: S2 words, each written and read back on every walked pad.
FIELD_WORDS = (
    DATA_CTRL_RW,
    0x0,
    CORE2PAD,
    _dir(0b11),
    IF_ENABLE,
    LSIO_SELECT,
    IRQ_ENABLE,
    LSIO_DISABLE,
    IRQ_TYPE,
    0x0,
)
#: S3 (core2pad, expected core2pad_en_o, expected core2pad_o).
TX_LEGS = ((0, 1, 0), (1, 1, 1), (0, 1, 0))
#: S4 (enable_rx_tx, expected core2pad_en_o, expected pad2core_en_o).
DIR_LEGS = ((0b00, 0, 0), (0b10, 0, 1), (0b11, 1, 1))
#: S6 register words with interface_enable clear: core2pad 0 -> 1 -> 0 under
#: enable_rx_tx 01, then enable_rx_tx 01 -> 00 -> 01 under core2pad 0.
IFACE_CLEAR_WORDS = (
    _dir(0b01),
    _dir(0b01) | CORE2PAD,
    _dir(0b01),
    _dir(0b00),
    _dir(0b01),
)
#: S7 (DATA_CTRL_ENABLE, DATA_CTRL, {probe: expected}) per leg.
USE_REG_LEGS = (
    ("tx", USE_REG_TX, LSIO_DISABLE | _dir(0b01), {"en": 1}),
    ("tx", USE_REG_TX, LSIO_DISABLE | _dir(0b00), {"en": 0}),
    ("rx", USE_REG_RX, LSIO_DISABLE | _dir(0b10), {"ie": 1}),
    ("rx", USE_REG_RX, LSIO_DISABLE | _dir(0b00), {"ie": 0}),
    ("core2pad", USE_REG_CORE2PAD | USE_REG_TX, LSIO_DISABLE | _dir(0b01), {"en": 1, "out": 0}),
    (
        "core2pad",
        USE_REG_CORE2PAD | USE_REG_TX,
        LSIO_DISABLE | _dir(0b01) | CORE2PAD,
        {"en": 1, "out": 1},
    ),
)
TERMS = ("SETUP", "FIELD-RB", "TX", "DIRECTION", "RX", "IFACE-CLEAR", "USE-REG", "RESTORED")
CHECKERS = (
    "CHK-GPIO-FIELD-RB",
    "CHK-GPIO-TX-OUT",
    "CHK-GPIO-DIR",
    "CHK-GPIO-RX-IN",
    "CHK-GPIO-IFACE-CLEAR",
    "CHK-GPIO-USE-REG",
    "CHK-TIMEOUT-PATHS",
    "CHK-NONVAC",
)
_PROBES = {"out": "tb_core2pad_o", "en": "tb_core2pad_en_o", "ie": "tb_pad2core_en_o"}


def _data_ctrl(pad: int) -> int:
    return smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", pad)


def _data_ctrl_enable(pad: int) -> int:
    return smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR", pad)


class smc_gpio_pad_enable_walk_test_seq(SmcCsrSeq):
    """Walk DATA_CTRL / DATA_CTRL_ENABLE on 56 pads and observe each pad's probes."""

    def __init__(self, name: str = "smc_gpio_pad_enable_walk_test_seq") -> None:
        super().__init__(name)
        self.walked: list[int] = []
        self.chk_seen: list[str] = []
        self._stamps: list[tuple[str, int, int]] = []
        self._phase_start = 0
        self._sep_last = "none"
        self._fuse_last = "not sampled"
        self._probe_polls = 0
        self._probe_max = 0
        self._probe_last = "none"
        self._p2c_polls = 0
        self._p2c_max = 0
        self._p2c_last = "none"

    # -- helpers ---------------------------------------------------------------

    def _mark(self, term: str) -> None:
        count = self.accesses - self._phase_start
        assert count > 0, f"fence term {term} issued no access"
        self._stamps.append((term, count, int(get_sim_time("ns"))))
        self._phase_start = self.accesses

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    async def _sep(self, label: str, addr: int, data: int | None = None) -> int:
        item = SmcSysAxiItem(f"{'wr' if data is not None else 'rd'}_{label}")
        item.op = SmcSysAxiOp.READ if data is None else SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        if data is not None:
            item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._sep_last = (
            f"{label} {item.op.value} 0x{addr:x} resp={item.resp_code} rdata=0x{item.rdata:x}"
        )
        bound = item.timeout_ns or self.cfg.axi_timeout_ns
        assert not item.timed_out and item.resp_ok and item.resp_code == 0, (
            f"SEP_IN {label} at 0x{addr:x}: no OKAY response within {bound} ns "
            f"(timed_out={item.timed_out} resp_code={item.resp_code})"
        )
        return item.rdata

    async def _wr(self, label: str, addr: int, data: int) -> None:
        await self._sep(label, addr, data)

    async def _rd(self, label: str, addr: int) -> int:
        rdata = await self._sep(label, addr)
        assert isinstance(rdata, int), f"{label} readback unresolved: {rdata!r}"
        return rdata

    @staticmethod
    def _bit(name: str, pad: int) -> str:
        """Character of pad ``pad`` of probe ``name``: '0', '1', 'x' or 'z'."""
        v = getattr(cocotb.top, name).value
        s = "".join(c for c in (getattr(v, "binstr", None) or str(v)) if c not in " _").lower()
        return s[-1 - pad] if pad < len(s) else "?"

    def _sample(self, pad: int) -> dict[str, str]:
        return {k: self._bit(sig, pad) for k, sig in _PROBES.items()}

    async def _poll(self, label: str, pad: int, want: dict[str, int]) -> int:
        """Bounded per-cycle poll until every probe in ``want`` reads its value at ``pad``."""
        self._probe_polls += 1
        clk = cocotb.top.clk_smc_i
        for cycle in range(PROBE_BOUND_CYCLES + 1):
            got = self._sample(pad)
            if all(got[k] == str(v) for k, v in want.items()):
                self._probe_max = max(self._probe_max, cycle)
                self._probe_last = f"{label} pad {pad} {got} after {cycle} cycles"
                return cycle
            if cycle < PROBE_BOUND_CYCLES:
                await RisingEdge(clk)
        raise AssertionError(
            f"{label}: pad {pad} probes {got} did not reach {want} within "
            f"{PROBE_BOUND_CYCLES} clk_smc_i cycles"
        )

    async def _poll_pad2core(self, pad: int, want: int) -> int:
        self._p2c_polls += 1
        last = None
        for n in range(1, PAD2CORE_BOUND_READS + 1):
            word = await self._rd(f"GPIO{pad}_PAD2CORE{want}", _data_ctrl(pad))
            last = 1 if word & PAD2CORE else 0
            if last == want:
                self._p2c_max = max(self._p2c_max, n)
                self._p2c_last = f"pad {pad} pad2core={last} after {n} reads"
                return n
        raise AssertionError(
            f"GPIO {pad}: DATA_CTRL.pad2core stayed {last} over {PAD2CORE_BOUND_READS} reads "
            f"while the pad was driven {want}"
        )

    # -- phases ----------------------------------------------------------------

    async def _setup(self) -> dict[int, tuple[int, int]]:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_BOUND)
        fuse = dut.tb_fuse_sense_done.value
        assert fuse.is_resolvable and int(fuse) == 1, f"tb_fuse_sense_done is {fuse}"
        self._fuse_last = f"tb_fuse_sense_done={int(fuse)}"
        count = gpio_pad_count()
        walk = [p for p in range(count) if p not in EXCLUDED_PADS]
        assert len(walk) == WALKED_COUNT, (
            f"{len(walk)} pads to walk of {count}, the contract walks {WALKED_COUNT}"
        )
        for p in walk:
            drive_gpio_pad(dut, p, None)
        saved: dict[int, tuple[int, int]] = {}
        for p in walk:
            dc = await self._rd(f"GPIO{p}_DATA_CTRL_SAVE", _data_ctrl(p))
            dce = await self._rd(f"GPIO{p}_DATA_CTRL_ENABLE_SAVE", _data_ctrl_enable(p))
            saved[p] = (dc, dce)
        self.walked = walk
        cocotb.log.info(
            "S1: %d interfaces, %d walked, excluded %s; tb_gpio_ext_drive_en held 0 on the "
            "walked pads; saved DATA_CTRL/DATA_CTRL_ENABLE %s",
            count,
            len(walk),
            ",".join(map(str, EXCLUDED_PADS)),
            " ".join(f"{p}:0x{dc:08x}/0x{dce:02x}" for p, (dc, dce) in saved.items()),
        )
        self._mark("SETUP")
        return saved

    async def _field_rb(self) -> None:
        compares = 0
        p2c_seen = {0: 0, 1: 0}
        lsio_seen = {0: 0, 1: 0}
        lsio_pads: set[int] = set()
        for p in self.walked:
            for w in FIELD_WORDS:
                await self._wr(f"GPIO{p}_DATA_CTRL_0x{w:08x}", _data_ctrl(p), w)
                rb = await self._rd(f"GPIO{p}_DATA_CTRL_0x{w:08x}_RB", _data_ctrl(p))
                assert rb & DATA_CTRL_RW == w, (
                    f"GPIO {p} DATA_CTRL wrote 0x{w:08x}, RW fields read 0x{rb & DATA_CTRL_RW:08x}"
                )
                compares += 1
                p2c_seen[1 if rb & PAD2CORE else 0] += 1
                lsio = 1 if rb & LSIO_ENABLE else 0
                lsio_seen[lsio] += 1
                if lsio:
                    lsio_pads.add(p)
        expected = WALKED_COUNT * len(FIELD_WORDS)
        assert compares == expected, f"{compares} field compares, expected {expected}"
        self._mark("FIELD-RB")
        self._chk(
            "CHK-GPIO-FIELD-RB",
            f"{len(self.walked)} pads (excluded {','.join(map(str, EXCLUDED_PADS))}), "
            f"{compares}/{expected} RW-field match (mask 0x{DATA_CTRL_RW:08x}); logged: "
            f"pad2core read 0 x{p2c_seen[0]} / 1 x{p2c_seen[1]}, lsio_enable read 0 "
            f"x{lsio_seen[0]} / 1 x{lsio_seen[1]} on pads {sorted(lsio_pads)}",
        )

    async def _tx(self) -> None:
        obs = 0
        lsio: dict[int, int] = {}
        for p in self.walked:
            for c2p, en, out in TX_LEGS:
                w = LSIO_DISABLE | IF_ENABLE | _dir(0b01) | (CORE2PAD if c2p else 0)
                await self._wr(f"GPIO{p}_TX_C2P{c2p}", _data_ctrl(p), w)
                if p not in lsio:
                    rb = await self._rd(f"GPIO{p}_TX_LSIO_ENABLE", _data_ctrl(p))
                    lsio[p] = 1 if rb & LSIO_ENABLE else 0
                await self._poll(f"TX core2pad {c2p}", p, {"en": en, "out": out})
                obs += 1
        set_pads = [p for p, v in lsio.items() if v]
        assert not set_pads, f"pads {set_pads}: lsio_enable reads 1 with lsio_disable set"
        expected = WALKED_COUNT * len(TX_LEGS)
        assert obs == expected, f"{obs} TX observations, expected {expected}"
        self._mark("TX")
        self._chk(
            "CHK-GPIO-TX-OUT",
            f"{len(self.walked)} pads lsio_disable=1 lsio_enable=0 ({len(lsio)}/{WALKED_COUNT} "
            f"read), OE=1, out 0/1/0 {obs}/{expected} within "
            f"{PROBE_BOUND_CYCLES} clk_smc_i (max {self._probe_max} cycles after the write response)",
        )

    async def _direction(self) -> None:
        obs = 0
        for p in self.walked:
            for d, en, ie in DIR_LEGS:
                w = LSIO_DISABLE | IF_ENABLE | CORE2PAD | _dir(d)
                await self._wr(f"GPIO{p}_DIR_{d:02b}", _data_ctrl(p), w)
                await self._poll(f"DIR {d:02b}", p, {"en": en, "ie": ie})
                obs += 1
        expected = WALKED_COUNT * len(DIR_LEGS)
        assert obs == expected, f"{obs} direction observations, expected {expected}"
        self._mark("DIRECTION")
        self._chk(
            "CHK-GPIO-DIR",
            f"{len(self.walked)} pads lsio_disable=1, OE 0/0/1 IE 0/1/1 for enable_rx_tx 00/10/11, "
            f"{obs}/{expected}",
        )

    async def _rx(self) -> None:
        dut = cocotb.top
        obs = 0
        reads: list[int] = []
        rx_pads = [p for p in self.walked if p not in RX_SKIPPED_PADS]
        skipped = [p for p in self.walked if p in RX_SKIPPED_PADS]
        assert len(rx_pads) == RX_COUNT and tuple(skipped) == RX_SKIPPED_PADS, (
            f"RX leg covers {len(rx_pads)} pads, skips {skipped}"
        )
        for p in rx_pads:
            await self._wr(f"GPIO{p}_RX", _data_ctrl(p), LSIO_DISABLE | IF_ENABLE | _dir(0b10))
            for level in (0, 1):
                drive_gpio_pad(dut, p, level)
                reads.append(await self._poll_pad2core(p, level))
                obs += 1
            drive_gpio_pad(dut, p, None)
        expected = RX_COUNT * 2
        assert obs == expected, f"{obs} pad2core observations, expected {expected}"
        en = dut.tb_gpio_ext_drive_en.value
        assert en.is_resolvable and not any((int(en) >> p) & 1 for p in RX_SKIPPED_PADS), (
            f"tb_gpio_ext_drive_en drives a skipped pad: {en}"
        )
        self._mark("RX")
        self._chk(
            "CHK-GPIO-RX-IN",
            f"{len(rx_pads)} pads (skipped {','.join(map(str, skipped))}, not driven) "
            f"lsio_disable=1, pad2core 0/1 {obs}/{expected} (max {max(reads)} of "
            f"{PAD2CORE_BOUND_READS} reads); drives released",
        )

    async def _iface_clear(self) -> None:
        followed: list[int] = []
        logged: list[str] = []
        for p in self.walked:
            snaps: list[dict[str, str]] = []
            await self._wr(
                f"GPIO{p}_IC_FROM", _data_ctrl(p), LSIO_DISABLE | IF_ENABLE | _dir(0b01) | CORE2PAD
            )
            await self._wr(f"GPIO{p}_IC_DC0", _data_ctrl(p), 0)
            snaps.append(self._sample(p))
            await self._wr(f"GPIO{p}_IC_DCE0", _data_ctrl_enable(p), 0)
            snaps.append(self._sample(p))
            regs: list[dict[str, str]] = []
            for w in IFACE_CLEAR_WORDS:
                await self._wr(f"GPIO{p}_IC_0x{w:02x}", _data_ctrl(p), w)
                s = self._sample(p)
                regs.append(s)
                snaps.append(s)
            for w in (LSIO_DISABLE, 0):
                await self._wr(f"GPIO{p}_IC_LSIO_DIS_0x{w:05x}", _data_ctrl(p), w)
                snaps.append(self._sample(p))
            for s in regs:
                for k in ("out", "en"):
                    assert s[k] in "01", f"GPIO {p} interface clear: {k} reads {s[k]!r}, not 0/1"
            out_follows = [s["out"] for s in regs[:3]] == ["0", "1", "0"]
            oe_follows = [s["en"] for s in regs[2:]] == ["1", "0", "1"]
            if out_follows and oe_follows:
                followed.append(p)
            logged.append(f"{p}:" + "/".join(f"{s['out']}{s['en']}{s['ie']}" for s in snaps))
        assert not followed, (
            f"pads {followed}: with interface_enable and every use_reg_* clear the pad output "
            f"followed core2pad and the output enable followed enable_rx_tx[0]"
        )
        self._mark("IFACE-CLEAR")
        self._chk(
            "CHK-GPIO-IFACE-CLEAR",
            f"{len(self.walked)} pads from lsio_disable start, not following register {len(self.walked)}/{WALKED_COUNT}, "
            "values=<logged, LINKED-ISSUE SF-022> out/oe/ie per write (DC=0, DCE=0, "
            "01c0, 01c1, 01c0, 00c0, 01c0, lsio_disable 1, 0): " + " ".join(logged),
        )

    async def _use_reg(self) -> None:
        obs = 0
        per_kind = {"tx": 0, "rx": 0, "core2pad": 0}
        for p in self.walked:
            dce_now = None
            for kind, dce, dc, want in USE_REG_LEGS:
                if dce != dce_now:
                    await self._wr(f"GPIO{p}_DCE_0x{dce:02x}", _data_ctrl_enable(p), dce)
                    dce_now = dce
                await self._wr(f"GPIO{p}_UR_{kind}_0x{dc:02x}", _data_ctrl(p), dc)
                await self._poll(f"USE-REG {kind} DCE 0x{dce:02x} DC 0x{dc:02x}", p, want)
                obs += 1
                per_kind[kind] += 1
        expected = WALKED_COUNT * len(USE_REG_LEGS)
        assert obs == expected, f"{obs} use_reg observations, expected {expected}"
        n = len(self.walked)
        self._mark("USE-REG")
        self._chk(
            "CHK-GPIO-USE-REG",
            f"{n} pads lsio_disable=1, tx {per_kind['tx'] // n}/2, rx {per_kind['rx'] // n}/2, core2pad "
            f"{per_kind['core2pad'] // n}/2, {obs}/{expected}",
        )

    async def _restore(self, saved: dict[int, tuple[int, int]]) -> None:
        dut = cocotb.top
        for p in self.walked:
            dc, dce = saved[p]
            await self._wr(f"GPIO{p}_DATA_CTRL_RESTORE", _data_ctrl(p), dc & DATA_CTRL_RW)
            await self._wr(
                f"GPIO{p}_DATA_CTRL_ENABLE_RESTORE", _data_ctrl_enable(p), dce & DATA_CTRL_ENABLE_RW
            )
            rb = await self._rd(f"GPIO{p}_DATA_CTRL_RESTORE_RB", _data_ctrl(p))
            rbe = await self._rd(f"GPIO{p}_DATA_CTRL_ENABLE_RESTORE_RB", _data_ctrl_enable(p))
            assert rb & DATA_CTRL_RW == dc & DATA_CTRL_RW, (
                f"GPIO {p} DATA_CTRL restore read 0x{rb:08x}, saved 0x{dc:08x}"
            )
            assert rbe & DATA_CTRL_ENABLE_RW == dce & DATA_CTRL_ENABLE_RW, (
                f"GPIO {p} DATA_CTRL_ENABLE restore read 0x{rbe:08x}, saved 0x{dce:08x}"
            )
            drive_gpio_pad(dut, p, None)
        en = dut.tb_gpio_ext_drive_en.value
        en_int = int(en) if en.is_resolvable else None
        assert en_int is not None and all(not (en_int >> p) & 1 for p in self.walked), (
            f"tb_gpio_ext_drive_en still drives a walked pad: {en}"
        )
        self._mark("RESTORED")
        cocotb.log.info(
            "S8: %d pads restored DATA_CTRL / DATA_CTRL_ENABLE exactly; every external drive "
            "on the walked pads released",
            len(self.walked),
        )

    def _finish(self) -> None:
        bound = self.cfg.axi_timeout_ns
        waits = (
            ("fuse_sense_done", f"{FUSE_BOUND}clk_smc_i", self._fuse_last),
            (
                "probe_poll",
                f"{PROBE_BOUND_CYCLES}clk_smc_i",
                f"{self._probe_polls} polls, max {self._probe_max} cycles, last {self._probe_last}",
            ),
            (
                "pad2core_poll",
                f"{PAD2CORE_BOUND_READS}reads",
                f"{self._p2c_polls} polls, max {self._p2c_max} reads, last {self._p2c_last}",
            ),
            ("sep_in_axi_access", f"{bound}ns", f"{self.accesses} done, last {self._sep_last}"),
        )
        n = 1 + self._probe_polls + self._p2c_polls + self.accesses
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{n} bounded waits, "
            + " ".join(f"{name}=bound {b} last={s}" for name, b, s in waits)
            + "; expiry raises AssertionError with the last probe / register value, 0 expired",
        )
        assert tuple(t for t, _c, _s in self._stamps) == TERMS, f"fence {self._stamps}"
        times = [s for _t, _c, s in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        assert tuple(self.chk_seen) == CHECKERS[:-1], f"checker order {self.chk_seen}"
        self.assert_all_reachable(self.accesses, "GPIO_PAD_ENABLE_WALK")
        self._chk(
            "CHK-NONVAC",
            " < ".join(TERMS)
            + " (counts and times per term: "
            + ", ".join(f"{t}(n={c})@{s}ns" for t, c, s in self._stamps)
            + f"); checker lines {','.join(self.chk_seen)}; SEP_IN accesses {self.accesses}",
        )

    async def body(self) -> None:
        saved = await self._setup()
        await self._field_rb()
        await self._tx()
        await self._direction()
        await self._rx()
        await self._iface_clear()
        await self._use_reg()
        await self._restore(saved)
        self._finish()
