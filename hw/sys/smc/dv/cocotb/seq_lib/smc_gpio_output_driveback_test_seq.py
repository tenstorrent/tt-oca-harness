# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO register-driven output (core2pad) driveback verification.

Programs GPIO wrap 0 as a register-driven TX output and checks the DUT pad
outputs actually follow the CSR programming.

The tb_top ``tb_gpio_core2pad_*`` observables are OR-reductions over the whole
``core2pad_o`` pad bus (which also carries idle-high LSIO pads such as UART TX),
so they cannot isolate a single GPIO wrap. Instead this sequence reads the full
``tb_core2pad_o`` / ``tb_core2pad_en_o`` buses (TB mirrors of real
``smc.core2pad_*``) and isolates wrap 0 by *delta*: only wrap 0 is programmed,
so exactly one output-enable bit must change, and that bit's value must track
the register. This is self-locating (no hard-coded pad index) and does not
depend on the OR aggregates.

DATA_CTRL field encoding (hw/ip/gpio/regs/gpio_intf.rdl):
  * bit0      core2pad          register-driven value to the pad
  * bit[5:4]  enable_rx_tx      2'b01 = TX enabled (drive pad)
  * bit16     interface_enable  select register values to drive the pad

After the wrap-0 leg, every GPIO interface except the bench-owned pads 27, 28
and 51, the boot-stall pad 57 and the cool-reset-in pad 61 is walked alone
with lsio_disable set: enable_rx_tx 01 (TX), 00, 11, then the reset word, each
written and read back over SEP_IN before ``tb_core2pad_en_o``,
``tb_pad2core_en_o`` and ``tb_core2pad_o`` are sampled. Each interface's pad
p_w is the one ``core2pad_en_o`` bit that differs between its TX and 00
samples. The absolute enable levels and DATA_CTRL.pad2core are logged, not
compared (SF-013). The AVS controller drives the data bits of pads 49 and 50
(AVS_CFG_1.STOP_AVS_CLOCK_ON_IDLE resets to 0, so the AVS clock runs while the
bus is idle); every other-pads compare logs those two data bits instead of
comparing them and keeps their enables.
"""

from __future__ import annotations

import inspect

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_indexed_addr
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import gpio_pad_count, pad_index
from .smc_regblock_field_sweep_utils import reg_instances

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)

_CORE2PAD = 1 << 0
_TX_ENABLE = 1 << 4  # enable_rx_tx = 2'b01
_IF_ENABLE = 1 << 16  # interface_enable

OUT_DRIVE_HIGH = _IF_ENABLE | _TX_ENABLE | _CORE2PAD
OUT_DRIVE_LOW = _IF_ENABLE | _TX_ENABLE
OUT_DISABLE = 0

_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)
#: Interfaces left out of the walk, as the testcase contract names them.
EXCLUDED_PADS = {
    27: "bench-owned",
    28: "bench-owned",
    51: "bench-owned",
    57: "boot stall",
    61: "cool reset in",
}
#: Pads whose core2pad_o data bit the AVS controller drives; the other-pads compares
#: log it instead of comparing it, and keep comparing their enables.
AVS_DATA_PADS = {49: "AVS.CLOCK", 50: "AVS.MDATA"}
#: Pad-to-pad transitions of one interface, as (from term, to term).
TRANSITIONS = (
    ("BEFORE", "TX"),
    ("TX", "BOTH-OFF"),
    ("BOTH-OFF", "RESTORE"),
    ("RESTORE", "RESET-WORD"),
)
#: Interfaces the testcase contract walks (0..64 minus the five above).
WALKED_COUNT = 60
#: (term, enable_rx_tx) for each write of one interface, in walk order.
WALK_TERMS = (("TX", 0b01), ("BOTH-OFF", 0b00), ("RESTORE", 0b11), ("RESET-WORD", None))


class smc_gpio_output_driveback_test_seq(SmcCsrSeq):
    """Drive wrap 0 as output via CSR and observe the pad it controls."""

    def __init__(self, name: str = "smc_gpio_output_driveback_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int | None, int]] = []
        self.walked: list[int] = []
        self.pads: dict[int, int] = {}
        self.waits: list[tuple[str, int, bool, bool]] = []

    @staticmethod
    def _resolve_int(sig) -> int:
        """Read a wide pad-bus vector, resolving X/Z bits to 0 (bit positions
        preserved). VCS leaves undriven upper pad bits at X (X-init pessimism)
        while Verilator zero-inits them; this test isolates GPIO wrap 0 by a
        single-bit delta, so the undriven X bits are irrelevant and safely read
        as 0. The pad under test is separately required to read a driven 0/1
        by ``_require_resolved`` before each compare."""
        v = sig.value
        try:
            return int(v)
        except Exception:  # noqa: BLE001 - X/Z present (VCS undriven pads)
            s = getattr(v, "binstr", None) or str(v)
            bits = "".join(c if c in "01" else "0" for c in s if c not in " _")
            return int(bits, 2) if bits else 0

    def _en_vec(self, dut) -> int:
        return self._resolve_int(dut.tb_core2pad_en_o)

    def _val_vec(self, dut) -> int:
        return self._resolve_int(dut.tb_core2pad_o)

    @staticmethod
    def _require_resolved(sig, bit: int, what: str) -> None:
        """The pad under test must read 0 or 1; an X or Z there is a failure, not a 0."""
        s = getattr(sig.value, "binstr", None) or str(sig.value)
        bits = "".join(c for c in s if c not in " _")
        ch = bits[-1 - bit] if bit < len(bits) else "?"
        assert ch in "01", f"GPIO wrap0 pad[{bit}] {what} reads {ch!r}, not a driven 0/1"

    async def _wrap0_leg(self) -> None:
        dut = cocotb.top

        # Baseline pad-output vectors before any GPIO programming. Undriven upper
        # pad bits may be X on VCS, so we do NOT require the whole vector to be
        # resolvable; the single-bit wrap-0 delta below is the real gate (and a
        # driven bit stuck at X would resolve to 0 and trip those asserts).
        await ClockCycles(dut.clk_smc_i, 4)
        width = len(dut.tb_core2pad_en_o.value)
        mask = (1 << width) - 1
        base_en = self._en_vec(dut)

        # 1) Enable TX + drive value high. Exactly one output-enable bit (the
        #    pad owned by GPIO wrap 0) must newly assert, and its value = 1.
        await self.csr_write("GPIO0_TX_HIGH", GPIO0_DATA_CTRL, OUT_DRIVE_HIGH)
        await ClockCycles(dut.clk_smc_i, 8)
        newly_en = self._en_vec(dut) & (~base_en & mask)
        assert newly_en != 0, (
            "programming GPIO wrap0 as TX asserted no new pad output-enable "
            f"(base core2pad_en_o=0x{base_en:x})"
        )
        assert (newly_en & (newly_en - 1)) == 0, (
            f"GPIO wrap0 output touched more than one pad (delta=0x{newly_en:x})"
        )
        pad_bit = newly_en
        pad_idx = newly_en.bit_length() - 1
        self._require_resolved(dut.tb_core2pad_o, pad_idx, "value")
        val_high = self._val_vec(dut)
        assert (val_high & pad_bit) != 0, (
            f"GPIO wrap0 pad[{pad_idx}] value did not follow register (high)"
        )

        # 2) Keep TX enabled, drive value low -> value clears, enable stays.
        await self.csr_write("GPIO0_TX_LOW", GPIO0_DATA_CTRL, OUT_DRIVE_LOW)
        await ClockCycles(dut.clk_smc_i, 8)
        self._require_resolved(dut.tb_core2pad_en_o, pad_idx, "output-enable")
        self._require_resolved(dut.tb_core2pad_o, pad_idx, "value")
        en_low = self._en_vec(dut)
        val_low = self._val_vec(dut)
        assert (en_low & pad_bit) != 0, (
            f"GPIO wrap0 pad[{pad_idx}] output-enable dropped while TX still enabled"
        )
        assert (val_low & pad_bit) == 0, (
            f"GPIO wrap0 pad[{pad_idx}] value did not follow register (low)"
        )

        # 3) Disable the register interface -> pad output released.
        await self.csr_write("GPIO0_DISABLE", GPIO0_DATA_CTRL, OUT_DISABLE)
        await ClockCycles(dut.clk_smc_i, 8)
        self._require_resolved(dut.tb_core2pad_en_o, pad_idx, "output-enable")
        en_off = self._en_vec(dut)
        assert (en_off & pad_bit) == 0, (
            f"GPIO wrap0 pad[{pad_idx}] output-enable did not release after disable"
        )

        # `assert_all_reachable` cross-checks the access count against the
        # scoreboard, which a mis-bound analysis path or a dead port fails.
        self.assert_all_reachable(3, "GPIO_OUTPUT_DRIVEBACK")
        cocotb.log.info(
            "CHK-GPIO-OUTPUT-DRIVEBACK: GPIO wrap0 TX enable raised exactly one "
            "core2pad_en_o bit, pad[%d] (delta 0x%x over base 0x%x); core2pad_o[%d] "
            "read %d with DATA_CTRL.core2pad=1 and %d with core2pad=0 while "
            "core2pad_en_o[%d] stayed %d, and core2pad_en_o[%d] read %d after "
            "interface disable; 3 CSR writes reached the scoreboard",
            pad_idx,
            newly_en,
            base_en,
            pad_idx,
            (val_high >> pad_idx) & 1,
            (val_low >> pad_idx) & 1,
            pad_idx,
            (en_low >> pad_idx) & 1,
            pad_idx,
            (en_off >> pad_idx) & 1,
        )

    def _mark(self, term: str, intf: int | None = None) -> None:
        self.fence.append((term, intf, int(get_sim_time("ps"))))

    @staticmethod
    def _bits(sig, width: int) -> str:
        """The vector as a string of width characters, MSB first, X/Z kept."""
        s = getattr(sig.value, "binstr", None) or str(sig.value)
        bits = "".join(c for c in s if c not in " _").lower()
        assert len(bits) == width, f"vector reads {len(bits)} bits, expected {width}"
        return bits

    def _snap(self, dut, width: int) -> dict[str, str]:
        return {
            "en": self._bits(dut.tb_core2pad_en_o, width),
            "rx": self._bits(dut.tb_pad2core_en_o, width),
            "val": self._bits(dut.tb_core2pad_o, width),
        }

    @staticmethod
    def _at(bits: str, pad: int) -> str:
        return bits[-1 - pad]

    @staticmethod
    def _diff(a: str, b: str, skip: frozenset[int] = frozenset()) -> list[int]:
        """Pad indices whose characters differ between a and b, except those in skip."""
        n = len(a)
        return [n - 1 - i for i in range(n) if a[i] != b[i] and n - 1 - i not in skip]

    async def _access(self, name: str, addr: int, data: int | None = None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{'wr' if data is not None else 'rd'}_{name}")
        item.op = SmcSysAxiOp.READ if data is None else SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        if data is not None:
            item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        bound = item.timeout_ns or self.cfg.axi_timeout_ns
        self.waits.append((name, bound, item.allow_timeout, item.timed_out))
        assert not item.timed_out and item.resp_ok, (
            f"{name} @ 0x{addr:08x}: no OKAY response within {bound} ns "
            f"(allow_timeout={item.allow_timeout} timed_out={item.timed_out} "
            f"resp_code={item.resp_code})"
        )
        return item

    async def _program(self, w: int, addr: int, word: int, rw_mask: int) -> int:
        await self._access(f"GPIO{w}_DATA_CTRL_0x{word:08x}", addr, word)
        rb = (await self._access(f"GPIO{w}_DATA_CTRL_0x{word:08x}_RB", addr)).rdata
        assert isinstance(rb, int), f"GPIO {w} DATA_CTRL readback unresolved: {rb!r}"
        assert rb & rw_mask == word & rw_mask, (
            f"GPIO {w} DATA_CTRL wrote 0x{word:08x}, writable bits read 0x{rb & rw_mask:08x}"
        )
        return rb

    async def _walk_one(self, dut, w, inst, words, width, base) -> dict:
        """TX, both-disabled, both-enabled and reset word on interface w alone."""
        rw = inst.reg.rw_mask
        pre = self._snap(dut, width)
        snaps: dict[str, dict[str, str]] = {}
        rbs: dict[str, int] = {}
        for term, _ in WALK_TERMS:
            rbs[term] = await self._program(w, inst.addr, words[term], rw)
            snaps[term] = self._snap(dut, width)
            self._mark(term, w)
            cocotb.log.info(
                "GPIO %d %s: DATA_CTRL wrote 0x%08x read 0x%08x; core2pad_en_o=%s "
                "pad2core_en_o=%s core2pad_o=%s",
                w,
                term,
                words[term],
                rbs[term],
                snaps[term]["en"],
                snaps[term]["rx"],
                snaps[term]["val"],
            )
        snaps["BEFORE"] = pre
        tx, off, rst, home = snaps["TX"], snaps["BOTH-OFF"], snaps["RESTORE"], snaps["RESET-WORD"]

        en_delta = self._diff(tx["en"], off["en"])
        assert len(en_delta) == 1, (
            f"GPIO {w}: core2pad_en_o differs between TX and 00 on pads {en_delta}, "
            f"expected exactly one (TX {tx['en']} / 00 {off['en']})"
        )
        p = en_delta[0]
        for key in ("en", "rx", "val"):
            for label, snap in (("TX", tx), ("RESTORE", rst)):
                ch = self._at(snap[key], p)
                assert ch in "01", f"GPIO {w} {label}: {key}[{p}] reads {ch!r}, not 0/1"
        for key in ("en", "rx"):
            for label, snap in (("00", off), ("reset word", home)):
                ch = self._at(snap[key], p)
                assert ch in "01", f"GPIO {w} {label}: {key}[{p}] reads {ch!r}, not 0/1"
        logged = frozenset(AVS_DATA_PADS) - {p}
        avs_moved: dict[tuple[str, str], list[int]] = {}
        for la, lb in TRANSITIONS:
            a, b = snaps[la], snaps[lb]
            for key in ("en", "rx", "val"):
                skip = frozenset({p}) | (logged if key == "val" else frozenset())
                moved = self._diff(a[key], b[key], skip)
                assert not moved, (
                    f"GPIO {w} (pad {p}): {key} of pads {moved} changed from {la} to {lb}"
                )
            avs_moved[(la, lb)] = [
                q for q in sorted(logged) if self._at(a["val"], q) != self._at(b["val"], q)
            ]
        cocotb.log.info(
            "GPIO %d (pad %d) AVS data bits logged, not compared: %s",
            w,
            p,
            "; ".join(
                f"{t} "
                + " ".join(
                    f"core2pad_o[{q}]={self._at(snaps[t]['val'], q)}" for q in sorted(logged)
                )
                for t in ("BEFORE",) + tuple(t for t, _ in WALK_TERMS)
            ),
        )
        assert self._at(tx["val"], p) == "1", (
            f"GPIO {w}: core2pad_o[{p}] reads {self._at(tx['val'], p)} under TX with core2pad 1"
        )
        # BOTH-DISABLED: transmit enable leaves its TX level, receive enable holds.
        assert self._at(off["en"], p) != self._at(tx["en"], p), (
            f"GPIO {w}: core2pad_en_o[{p}] reads {self._at(off['en'], p)} under both 00 and TX"
        )
        assert self._at(off["rx"], p) == self._at(tx["rx"], p), (
            f"GPIO {w}: pad2core_en_o[{p}] reads {self._at(off['rx'], p)} under 00 and "
            f"{self._at(tx['rx'], p)} under TX; receive is disabled in both words"
        )
        # RESTORE: transmit back to its TX level, receive leaves its 00 level.
        assert self._at(rst["en"], p) == self._at(tx["en"], p), (
            f"GPIO {w}: core2pad_en_o[{p}] reads {self._at(rst['en'], p)} under 11, "
            f"TX level {self._at(tx['en'], p)}"
        )
        assert self._at(rst["rx"], p) != self._at(off["rx"], p), (
            f"GPIO {w}: pad2core_en_o[{p}] reads {self._at(rst['rx'], p)} under 11 and "
            f"under 00; it did not follow enable_rx_tx[1]"
        )
        for key in ("en", "rx"):
            assert self._at(home[key], p) == self._at(base[key], p), (
                f"GPIO {w}: {key}[{p}] reads {self._at(home[key], p)} after the reset "
                f"word, S1 baseline {self._at(base[key], p)}"
            )
        return {
            "pad": p,
            "tx_en": self._at(tx["en"], p),
            "tx_rx": self._at(tx["rx"], p),
            "pad2core": rbs["RESTORE"],
            "avs_moved": avs_moved,
        }

    def _nonvac(self) -> str:
        terms = [t for t, _, _ in self.fence]
        stamps = [ps for _, _, ps in self.fence]
        expected = ["WRAP0-LEG"] + [t for _ in self.walked for t, _ in WALK_TERMS]
        assert terms == expected, f"fence terms out of order: {terms}"
        assert [w for _, w, _ in self.fence[1:]] == [w for w in self.walked for _ in WALK_TERMS], (
            "fence interfaces out of order"
        )
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"fence stamps not rising {stamps}"
        counts = {t: terms.count(t) for t in ["WRAP0-LEG"] + [t for t, _ in WALK_TERMS]}
        assert counts["WRAP0-LEG"] == 1, f"WRAP0-LEG count {counts['WRAP0-LEG']}"
        for t, _ in WALK_TERMS:
            assert counts[t] == len(self.walked) > 0, f"{t} count {counts[t]}"
        per_w: dict[int, list[int]] = {}
        for _, w, ps in self.fence[1:]:
            per_w.setdefault(w, []).append(ps)
        return (
            "counts "
            + " ".join(f"{t}={n}" for t, n in counts.items())
            + f"; WRAP0-LEG@{stamps[0]}ps; per w TX/BOTH-OFF/RESTORE/RESET-WORD ps: "
            + " ".join(f"{w}:{'/'.join(map(str, v))}" for w, v in per_w.items())
        )

    async def body(self) -> None:
        dut = cocotb.top
        fuse_bound = inspect.signature(wait_fuse_sense_done).parameters["max_cycles"].default
        await self.wait_fuse_sense_done()
        cocotb.log.info(
            "wait fuse_sense_done: bound %d clk_smc_i cycles, last state tb_fuse_sense_done=%s",
            fuse_bound,
            dut.tb_fuse_sense_done.value,
        )
        width = len(dut.tb_core2pad_en_o.value)
        base = self._snap(dut, width)
        cocotb.log.info(
            "S1 baseline: core2pad_en_o=%s pad2core_en_o=%s core2pad_o=%s",
            base["en"],
            base["rx"],
            base["val"],
        )

        await self._wrap0_leg()
        self._mark("WRAP0-LEG")
        wrap0_accesses = self.accesses

        insts = reg_instances(*_DATA_CTRL)
        count = gpio_pad_count()
        assert len(insts) == count, f"{len(insts)} DATA_CTRL instances, {count} interfaces"
        fields = {f.name: f for f in insts[0].reg.fields}
        f_if = fields["interface_enable"].mask
        f_lsio_dis = fields["lsio_disable"].mask
        f_dir = fields["enable_rx_tx"]
        f_c2p = fields["core2pad"].mask
        f_p2c = fields["pad2core"]
        assert (f_if, f_lsio_dis, f_dir.offset, f_dir.width, f_c2p, f_p2c.mask) == (
            1 << 16,
            1 << 19,
            4,
            2,
            1 << 0,
            1 << 31,
        ), f"DATA_CTRL field layout differs from gpio_intf.adoc: {fields}"
        words = {
            term: (f_if | f_lsio_dis | (d << f_dir.offset) | f_c2p) if d is not None else 0
            for term, d in WALK_TERMS
        }
        for q, function in AVS_DATA_PADS.items():
            assert pad_index(function) == q, (
                f"the integrator pad table puts {function} on pad {pad_index(function)}, not {q}"
            )
        walk = [w for w in range(count) if w not in EXCLUDED_PADS]
        assert len(walk) == WALKED_COUNT, f"{len(walk)} interfaces to walk, contract says 60"
        cocotb.log.info(
            "walk: %d interfaces of %d; excluded %s; words %s",
            len(walk),
            count,
            ", ".join(f"{w} ({why})" for w, why in EXCLUDED_PADS.items()),
            ", ".join(f"{t}=0x{v:08x}" for t, v in words.items()),
        )

        results: dict[int, dict] = {}
        for w in walk:
            first = len(self.waits)
            results[w] = await self._walk_one(dut, w, insts[w], words, width, base)
            self.walked.append(w)
            done = self.waits[first:]
            cocotb.log.info(
                "GPIO %d waits: %d AXI accesses, bounds %s ns, allow_timeout %s, timed_out %s; "
                "last state pad %d",
                w,
                len(done),
                sorted({b for _, b, _, _ in done}),
                sorted({a for _, _, a, _ in done}),
                sorted({t for _, _, _, t in done}),
                results[w]["pad"],
            )

        pads = [r["pad"] for r in results.values()]
        n_walked = len(results)
        n_distinct = len(set(pads))
        assert n_walked == WALKED_COUNT and n_distinct == n_walked, (
            f"{n_walked} interfaces walked onto {n_distinct} distinct pads: "
            + ", ".join(f"{w}->{r['pad']}" for w, r in results.items())
        )
        self.pads = {w: r["pad"] for w, r in results.items()}
        tx_levels = {lvl: sum(r["tx_en"] == lvl for r in results.values()) for lvl in "01"}
        rx_levels = {lvl: sum(r["tx_rx"] == lvl for r in results.values()) for lvl in "01"}
        p2c_shift = f_p2c.offset
        p2c = {w: (r["pad2core"] >> p2c_shift) & 1 for w, r in results.items()}
        p2c_tally = {v: sum(x == v for x in p2c.values()) for v in (0, 1)}
        mapping = " ".join(f"{w}->{p}" for w, p in self.pads.items())

        def avs_tally(*trans: tuple[str, str]) -> str:
            parts = []
            for q in AVS_DATA_PADS:
                moved = sum(q in r["avs_moved"][t] for r in results.values() for t in trans)
                pairs = sum(q != r["pad"] for r in results.values()) * len(trans)
                names = "/".join(f"{a}->{b}" for a, b in trans)
                parts.append(f"core2pad_o[{q}] changed in {moved} of {pairs} {names} pairs")
            return ", ".join(parts)

        avs_txoff = avs_tally(("TX", "BOTH-OFF"))
        avs_restore = avs_tally(("BOTH-OFF", "RESTORE"), ("RESTORE", "RESET-WORD"))
        cocotb.log.info(
            "CHK-GPIO-PAD-TX-ENABLE: %d interfaces, %d distinct pads, en(TX)!=en(00) on p_w "
            "only, core2pad_o[p_w]=1 on all %d; no other pad's enable bit and no other "
            "pad's data bit outside 49/50 changed; measured core2pad_en_o[p_w] level under "
            "TX: %d read 1, %d read 0 (SF-013); core2pad_o[49]/[50] logged, not compared: "
            "%s; w->p_w %s",
            n_walked,
            n_distinct,
            n_walked,
            tx_levels["1"],
            tx_levels["0"],
            avs_txoff,
            mapping,
        )
        cocotb.log.info(
            "CHK-GPIO-PAD-BOTH-DISABLED: %d/%d tx-en dropped from TX level, rx-en unchanged "
            "between 01 and 00 (measured pad2core_en_o[p_w] level: %d read 1, %d read 0), "
            "others unchanged; core2pad_o[49]/[50] logged, not compared: %s",
            n_walked,
            n_walked,
            rx_levels["1"],
            rx_levels["0"],
            avs_txoff,
        )
        cocotb.log.info(
            "CHK-GPIO-PAD-RESTORE: %d/%d tx-en back to TX level, rx-en toggled, baseline after "
            "reset word; pad2core logged (LINKED-ISSUE SF-013): %d read 1, %d read 0; "
            "core2pad_o[49]/[50] logged, not compared: %s; pad2core per w %s",
            n_walked,
            n_walked,
            p2c_tally[1],
            p2c_tally[0],
            avs_restore,
            " ".join(f"{w}:{v}" for w, v in p2c.items()),
        )

        per_w = len(WALK_TERMS) * 2
        self.assert_all_reachable(wrap0_accesses + per_w * n_walked, "GPIO_PAD_DIRECTION_WALK")
        cocotb.log.info(
            "CHK-NONVAC: WRAP0-LEG < TX(w) < BOTH-OFF(w) < RESTORE(w) < RESET-WORD(w), for "
            "every walked w (%d interfaces); %s",
            n_walked,
            self._nonvac(),
        )
