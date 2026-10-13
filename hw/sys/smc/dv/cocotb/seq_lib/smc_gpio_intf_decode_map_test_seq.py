# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO_INTF instance decode, co-resident aliasing and the Programmer's Guide address formula.

Contract SMC_GPIO_CSR_007, anchor smc_gpio_intf_decode_map_test.
Allocated scenarios: GPIO-CSR-DECODE.S1 to S4.
Spec sources: hw/ip/gpio/regs/gpio_intf.rdl, hw/sys/smc/regs/smc.rdl,
doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import gpio_intf_u32, smc_indexed_addr
from .smc_regblock_field_sweep_utils import SmcRegblockFieldSweepSeq, reg_instances

_ACCESS_FILTER = (
    "gpio_intf/ACCESS_FILTER",
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_NUM",
    "GPIO_INTF_{index}__ACCESS_FILTER_REG_ADDR",
)
_DATA_CTRL_ENABLE = (
    "gpio_intf/DATA_CTRL_ENABLE",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_ENABLE_REG_ADDR",
)
_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)

_INSTANCES = 65
_LAST = _INSTANCES - 1
_ACCESS_FILTER_RESET_WORD = 0x00010100
_PG_BASE = 0xC000_3000
_PG_STRIDE = 0x10
_PG_PINS = (0, 32, 64)
_S4_INSTANCE = 60
_EVENTS = ("S1", "S2", "S3_WRITES", "S3_READBACKS", "S3", "S4", "S5")
_TERMS = (
    "SNAPSHOT_TAKEN",
    "ENDPOINT_PATTERNS",
    "CORESIDENT_WRITES",
    "CORESIDENT_READBACKS",
    "REGISTER_DISTINCT",
    "FORMULA_COMPARE",
)
_CHK_ORDER = (
    ("S2", "CHK-GPIO-DECODE-ENDPOINTS"),
    ("S3", "CHK-GPIO-DECODE-NO-ALIAS"),
    ("S4", "CHK-GPIO-DECODE-REG-DISTINCT"),
    ("S5", "CHK-GPIO-DECODE-PG-FORMULA"),
)


class smc_gpio_intf_decode_map_test_seq(SmcRegblockFieldSweepSeq):
    """Decode and alias checks over the 65 GPIO_INTF instances."""

    def __init__(self, name: str = "smc_gpio_intf_decode_map_test_seq") -> None:
        super().__init__(name)
        self.events: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str, int]] = []

    def _stamp(self, event: str) -> None:
        self.events.append((event, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        self.chk_steps.append((step, chk_id, int(get_sim_time("ps"))))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _write_word(self, inst, label: str, word: int) -> None:
        assert word & ~inst.reg.rw_mask == 0, (
            f"{inst.label}: pattern 0x{word:08x} leaves rw mask 0x{inst.reg.rw_mask:08x}"
        )
        await self.csr_write(f"{inst.label}:{label}", inst.addr, word)

    async def _read_rw(self, inst, label: str, model: int) -> int:
        got = await self.read_check(inst, label, model)
        assert got & inst.reg.rw_mask == model, (
            f"{inst.label} @ 0x{inst.addr:08x} [{label}]: read 0x{got:08x}, "
            f"pattern 0x{model:08x} (rw mask 0x{inst.reg.rw_mask:08x})"
        )
        return got

    async def _read_trio(self, trio, label: str, models) -> list[int]:
        return [await self._read_rw(inst, label, m) for inst, m in zip(trio, models)]

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        filters = reg_instances(*_ACCESS_FILTER)
        enables = reg_instances(*_DATA_CTRL_ENABLE)
        ctrls = reg_instances(*_DATA_CTRL)
        assert len(filters) == len(enables) == len(ctrls) == _INSTANCES, (
            f"generated map declares {len(filters)} ACCESS_FILTER, {len(enables)} "
            f"DATA_CTRL_ENABLE and {len(ctrls)} DATA_CTRL instances, contract says {_INSTANCES}"
        )
        aw_bp = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_bp")
        ar_bp = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_bp")
        aw_bm = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_bm")
        ar_bm = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_bm")
        core2pad = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
        use_c2p = gpio_intf_u32("GPIO_INTF__DATA_CTRL_ENABLE__USE_REG_CORE2PAD_bm")
        use_rx = gpio_intf_u32("GPIO_INTF__DATA_CTRL_ENABLE__USE_REG_RX_bm")

        def flt(aw: int, ar: int) -> int:
            return ((aw << aw_bp) & aw_bm) | ((ar << ar_bp) & ar_bm)

        # S1
        snap = []
        for f, e, c in zip(filters, enables, ctrls):
            snap.append(
                (
                    await self.csr_read(f"{f.label}:snapshot", f.addr),
                    await self.csr_read(f"{e.label}:snapshot", e.addr),
                    await self.csr_read(f"{c.label}:snapshot", c.addr),
                )
            )
        self._stamp("S1")

        # S2
        s2_ends = []
        for idx in (0, _LAST):
            f, e, c = filters[idx], enables[idx], ctrls[idx]
            assert c.addr + 0x4 == e.addr and c.addr + 0x8 == f.addr, (
                f"instance {idx}: DATA_CTRL 0x{c.addr:08x}, DATA_CTRL_ENABLE 0x{e.addr:08x}, "
                f"ACCESS_FILTER 0x{f.addr:08x} are not at offsets 0x0, 0x4, 0x8"
            )
            got_f = await self.csr_read(f"{f.label}:s2_reset", f.addr)
            assert got_f == _ACCESS_FILTER_RESET_WORD, (
                f"{f.label}: ACCESS_FILTER read 0x{got_f:08x}, "
                f"want 0x{_ACCESS_FILTER_RESET_WORD:08x}"
            )
            base_e, base_c = snap[idx][1], snap[idx][2]
            pat = (core2pad, use_c2p | use_rx, flt(3, 5))
            await self._write_word(c, "s2", pat[0])
            await self._write_word(e, "s2", pat[1])
            await self._write_word(f, "s2", pat[2])
            got = await self._read_trio((c, e, f), "s2", pat)
            s2_ends.append(
                f"instance {idx} @ 0x{c.addr:08x}/0x{e.addr:08x}/0x{f.addr:08x}: "
                f"ACCESS_FILTER reset 0x{got_f:08x}; DATA_CTRL 0x{got[0]:08x}, "
                f"DATA_CTRL_ENABLE 0x{got[1]:08x}, ACCESS_FILTER 0x{got[2]:08x}"
            )
            await self.csr_write(f"{c.label}:s2_restore", c.addr, base_c & c.reg.rw_mask)
            await self.csr_write(f"{e.label}:s2_restore", e.addr, base_e & e.reg.rw_mask)
            await self.csr_write(f"{f.label}:s2_restore", f.addr, _ACCESS_FILTER_RESET_WORD)
            await self._read_trio(
                (c, e, f),
                "s2_restore",
                (base_c & c.reg.rw_mask, base_e & e.reg.rw_mask, _ACCESS_FILTER_RESET_WORD),
            )
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-GPIO-DECODE-ENDPOINTS",
            "instances 0 and 64 answered OKAY at offsets 0x0, 0x4, 0x8 and each pattern read back "
            "at its own offset; " + "; ".join(s2_ends),
        )

        # S3
        sb_before = self.env.scoreboard.sys_axi_value_checks_seen
        patterns = []
        for n in range(_INSTANCES):
            m = n % 64
            ena = use_c2p if n == _LAST else 0
            patterns.append((flt(m & 7, (m >> 3) & 7), ena))
        for n in range(_INSTANCES):
            await self._write_word(filters[n], "s3", patterns[n][0])
            await self._write_word(enables[n], "s3", patterns[n][1])
        self._stamp("S3_WRITES")
        reads = []
        for n in range(_INSTANCES):
            got_f = await self._read_rw(filters[n], "s3", patterns[n][0])
            got_e = await self._read_rw(enables[n], "s3", patterns[n][1])
            got_c = await self.csr_read(f"{ctrls[n].label}:s3", ctrls[n].addr)
            assert got_c & ctrls[n].reg.rw_mask == snap[n][2] & ctrls[n].reg.rw_mask, (
                f"{ctrls[n].label}: DATA_CTRL read 0x{got_c:08x}, snapshot 0x{snap[n][2]:08x}"
            )
            reads.append((got_f, got_e))
        self._stamp("S3_READBACKS")
        distinct_adjacent = 0
        for n in range(_LAST):
            assert reads[n] != reads[n + 1], (
                f"instances {n} and {n + 1} read the same word pair {reads[n]}"
            )
            distinct_adjacent += 1
        assert len(set(reads)) == _INSTANCES, f"only {len(set(reads))} distinct readbacks"
        for n in range(_INSTANCES):
            await self.csr_write(
                f"{filters[n].label}:s3_restore", filters[n].addr, _ACCESS_FILTER_RESET_WORD
            )
            await self.csr_write(
                f"{enables[n].label}:s3_restore",
                enables[n].addr,
                snap[n][1] & enables[n].reg.rw_mask,
            )
        for n in range(_INSTANCES):
            await self._read_rw(filters[n], "s3_restore", _ACCESS_FILTER_RESET_WORD)
            await self._read_rw(enables[n], "s3_restore", snap[n][1] & enables[n].reg.rw_mask)
        self.assert_value_checks(sb_before, _INSTANCES * 2, "GPIO_INTF_DECODE_MAP")
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-GPIO-DECODE-NO-ALIAS",
            f"{_INSTANCES} instances read back their own ACCESS_FILTER pattern "
            f"(n mod 64 over awprot/arprot, 0x{reads[0][0]:08x}..0x{reads[_LAST - 1][0]:08x}) "
            f"and DATA_CTRL_ENABLE (instance {_LAST} only 0x{reads[_LAST][1]:x}) after all writes; "
            f"{distinct_adjacent} adjacent pairs differ, {len(set(reads))} distinct pairs; "
            f"instance {_LAST} ACCESS_FILTER 0x{reads[_LAST][0]:08x}; all restored",
        )

        # S4
        f, e, c = filters[_S4_INSTANCE], enables[_S4_INSTANCE], ctrls[_S4_INSTANCE]
        trio = (c, e, f)
        base_c, base_e = snap[_S4_INSTANCE][2] & c.reg.rw_mask, snap[_S4_INSTANCE][1]
        base_e &= e.reg.rw_mask
        held = [core2pad, use_c2p | use_rx, flt(3, 5)]
        new = [0, use_c2p, flt(4, 2)]
        for inst, word in zip(trio, held):
            await self._write_word(inst, "s4_hold", word)
        await self._read_trio(trio, "s4_hold", held)
        s4 = []
        for k, name in enumerate(("DATA_CTRL", "DATA_CTRL_ENABLE", "ACCESS_FILTER")):
            assert new[k] != held[k]
            await self._write_word(trio[k], "s4", new[k])
            held[k] = new[k]
            got = await self._read_trio(trio, f"s4_{name}", held)
            s4.append(
                f"{name} written 0x{new[k]:08x} -> reads 0x{got[0]:08x}/0x{got[1]:08x}/"
                f"0x{got[2]:08x}"
            )
        await self.csr_write(f"{c.label}:s4_restore", c.addr, base_c)
        await self.csr_write(f"{e.label}:s4_restore", e.addr, base_e)
        await self.csr_write(f"{f.label}:s4_restore", f.addr, _ACCESS_FILTER_RESET_WORD)
        await self._read_trio(trio, "s4_restore", (base_c, base_e, _ACCESS_FILTER_RESET_WORD))
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-GPIO-DECODE-REG-DISTINCT",
            f"instance {_S4_INSTANCE}: each of the three registers written alone left the other "
            "two at their prior values (DATA_CTRL/DATA_CTRL_ENABLE/ACCESS_FILTER reads shown); "
            + "; ".join(s4),
        )

        # S5
        rows = []
        for pin in _PG_PINS:
            base = _PG_BASE + pin * _PG_STRIDE
            for sym, off, reg_addr in (
                ("DATA_CTRL", 0x0, smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", pin)),
                (
                    "DATA_CTRL_ENABLE",
                    0x4,
                    smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR", pin),
                ),
                (
                    "ACCESS_FILTER",
                    0x8,
                    smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", pin),
                ),
            ):
                assert base + off == reg_addr, (
                    f"pin {pin} {sym}: formula 0x{base + off:08x}, generated map 0x{reg_addr:08x}"
                )
            got = await self.csr_read(
                f"pin{pin}:formula_access_filter",
                base + 0x8,
                expected=_ACCESS_FILTER_RESET_WORD,
            )
            assert got == _ACCESS_FILTER_RESET_WORD, (
                f"pin {pin}: ACCESS_FILTER at formula 0x{base + 8:08x} read 0x{got:08x}"
            )
            rows.append(f"pin {pin} base 0x{base:08x} ACCESS_FILTER@0x{base + 8:08x}=0x{got:08x}")
        assert len(rows) == 3
        self._stamp("S5")
        self._chk(
            "S5",
            "CHK-GPIO-DECODE-PG-FORMULA",
            "formula 0xC0003000 + pin*0x10 equals the generated DATA_CTRL address, +0x4 "
            "DATA_CTRL_ENABLE, +0x8 ACCESS_FILTER; " + "; ".join(rows),
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.events) == _EVENTS, f"event order {self.events}"
        ps = [p for _, p in self.events]
        assert all(b > a for a, b in zip(ps, ps[1:])), f"stamps not increasing {ps}"
        assert tuple((s, c) for s, c, _ in self.chk_steps) == _CHK_ORDER, f"{self.chk_steps}"
        stamp = dict(self.events)
        assert all(p >= stamp[s] for s, _, p in self.chk_steps), f"{self.chk_steps}"
        chk_ps = [p for _, _, p in self.chk_steps]
        assert all(b >= a for a, b in zip(chk_ps, chk_ps[1:])), f"{self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(_TERMS),
            ",".join(c for _, c, _ in self.chk_steps),
            ",".join(f"{n}={p}" for n, p in self.events),
        )
