# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO DATA_CTRL hardware-status bits written from software.

Sources hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL, DATA_CTRL_ENABLE), integrator GPIO pad table.

lsio_enable (bit 25) and pad2core (bit 31) are sw=r hw=w. Instance 60 receives software writes
carrying those bits; the writable fields of the same register are checked beside them.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_DATA_CTRL = (
    "gpio_intf/DATA_CTRL",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_REG_ADDR",
)
_DATA_CTRL_ENABLE = (
    "gpio_intf/DATA_CTRL_ENABLE",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR",
    "SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_NUM",
    "GPIO_INTF_{index}__DATA_CTRL_ENABLE_REG_ADDR",
)

_INSTANCE = 60
_PAD_COUNT = 65
_LSIO_ENABLE_BIT = 25
_PAD2CORE_BIT = 31
_ALL_ONES = 0xFFFF_FFFF

STEP_ORDER = (
    "BRINGUP_DONE",
    "PAD_SCAN",
    "LSIO_ENABLE_WRITE",
    "PAD2CORE_WRITE",
    "ALL_ONES_WRITE",
    "RESTORE_READBACK",
)
CHK_ORDER = (
    ("LSIO_ENABLE_WRITE", "CHK-GPIO-DATA-CTRL-LSIO-ENABLE-RO"),
    ("PAD2CORE_WRITE", "CHK-GPIO-DATA-CTRL-PAD2CORE-RO"),
    ("ALL_ONES_WRITE", "CHK-GPIO-DATA-CTRL-WRITE-ALL-ONES"),
)


def _field_bp(reg, name: str) -> int:
    mask = {f.name: f.mask for f in reg.fields}[name]
    return (mask & -mask).bit_length() - 1


class smc_gpio_data_ctrl_ro_status_test_seq(SmcCsrSeq):
    """Write the sw=r hw=w DATA_CTRL bits of instance 60 and observe the readbacks."""

    def __init__(self, name: str = "smc_gpio_data_ctrl_ro_status_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _read(self, label: str, inst: RegInstance) -> int:
        got = await self.csr_read(label, inst.addr)
        assert isinstance(got, int), f"{label}: unresolved read data {got!r}"
        return got

    async def _write(self, label: str, inst: RegInstance, data: int) -> int | None:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = inst.addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.resp_code

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP_DONE < PAD_SCAN < LSIO_ENABLE_WRITE < "
            "PAD2CORE_WRITE < ALL_ONES_WRITE < RESTORE_READBACK; checker lines %s; stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        dcs = reg_instances(*_DATA_CTRL)
        en = reg_instances(*_DATA_CTRL_ENABLE)[_INSTANCE]
        assert len(dcs) == _PAD_COUNT, f"{len(dcs)} DATA_CTRL instances, expected {_PAD_COUNT}"
        dc = dcs[_INSTANCE]
        reg = dc.reg
        rw = reg.rw_mask
        lsio = 1 << _LSIO_ENABLE_BIT
        p2c = 1 << _PAD2CORE_BIT
        assert rw == 0x003F_0031, f"software-writable mask 0x{rw:08x}"
        assert reg.declared_mask == rw | lsio | p2c, f"declared mask 0x{reg.declared_mask:08x}"
        reset = reg.reset_word
        assert reset == 0, f"DATA_CTRL reset word 0x{reset:08x}"
        use_reg_rx = {f.name: f.mask for f in en.reg.fields}["use_reg_rx"]
        assert use_reg_rx == 0x20, f"use_reg_rx mask 0x{use_reg_rx:x}"
        rx_on = 2 << _field_bp(reg, "enable_rx_tx")
        self._mark("BRINGUP_DONE")

        scan: list[int] = []
        for inst in dcs:
            scan.append(await self._read(f"SCAN_{inst.index}", inst))
        high = [i for i, w in enumerate(scan) if w & lsio]
        pre = scan[_INSTANCE]
        assert pre & rw == reset & rw, f"instance {_INSTANCE} writable bits read 0x{pre & rw:08x}"
        self._mark("PAD_SCAN")
        cocotb.log.info(
            "PAD_SCAN: bit 25 reads 1 on pads %s; instance %d word 0x%08x", high, _INSTANCE, pre
        )

        resp = await self._write("LSIO_SET", dc, lsio)
        got = await self._read("LSIO_RB", dc)
        assert got & lsio == pre & lsio, (
            f"instance {_INSTANCE} bit 25 reads {got >> _LSIO_ENABLE_BIT & 1} after a software "
            f"write of 1, it read {pre >> _LSIO_ENABLE_BIT & 1} before"
        )
        assert pre & lsio == 0, f"instance {_INSTANCE} bit 25 reads 1 before any write"
        assert got & rw == 0, f"instance {_INSTANCE} writable bits read 0x{got & rw:08x}"
        assert got & ~(lsio | p2c) == 0, f"instance {_INSTANCE} word reads 0x{got:08x}"
        high_resps = []
        for idx in high:
            inst = dcs[idx]
            before = scan[idx]
            r = await self._write(f"HIGH_{idx}_CLR", inst, before & rw)
            after = await self._read(f"HIGH_{idx}_RB", inst)
            assert after & lsio == lsio, (
                f"pad {idx} bit 25 reads {after >> _LSIO_ENABLE_BIT & 1} after a software "
                f"write of 0, it read 1 before"
            )
            high_resps.append(f"pad{idx}:resp={r}")
            await self._write(f"HIGH_{idx}_RESTORE", inst, reset)
            await self._read(f"HIGH_{idx}_RESTORE_RB", inst)
        self._mark("LSIO_ENABLE_WRITE")
        leg = (
            f"bit 25 reads 1 on pads {high}; write-zero responses {high_resps}"
            if high
            else "no pad reads bit 25 = 1, the write-zero leg is open (owner value pending)"
        )
        self._chk(
            "LSIO_ENABLE_WRITE",
            "CHK-GPIO-DATA-CTRL-LSIO-ENABLE-RO",
            f"instance {_INSTANCE} bit 25 read {pre >> _LSIO_ENABLE_BIT & 1} before and "
            f"{got >> _LSIO_ENABLE_BIT & 1} after a software write of 0x{lsio:08x} "
            f"(write response {resp}); {leg}",
        )

        idle_en = await self._read("EN_IDLE", en)
        assert idle_en & use_reg_rx == 0, f"use_reg_rx reads 0x{idle_en:08x} before the write"
        await self._write("P2C_SET", dc, p2c)
        off = await self._read("P2C_RB", dc)
        assert off & p2c == 0, f"bit 31 reads 1 with the receive path unselected: 0x{off:08x}"
        await self._write("RX_ON", dc, rx_on)
        await self._write("EN_RX_SET", en, use_reg_rx)
        en_on = await self._read("EN_RX_RB", en)
        assert en_on & use_reg_rx, f"use_reg_rx reads 0x{en_on:08x} after its write"
        level = await self._read("P2C_RX", dc)
        assert level & p2c, f"bit 31 reads 0 with the receive path enabled: 0x{level:08x}"
        await self._write("EN_RX_CLR", en, idle_en)
        await self._write("RX_OFF", dc, reset)
        back = await self._read("P2C_CLR_RB", dc)
        assert back & p2c == 0, f"bit 31 reads 1 after use_reg_rx cleared: 0x{back:08x}"
        self._mark("PAD2CORE_WRITE")
        self._chk(
            "PAD2CORE_WRITE",
            "CHK-GPIO-DATA-CTRL-PAD2CORE-RO",
            f"instance {_INSTANCE} bit 31 read {off >> _PAD2CORE_BIT & 1} after a software write "
            f"of 1 with the receive path unselected, {level >> _PAD2CORE_BIT & 1} with "
            f"enable_rx_tx=2'b10 and use_reg_rx set (pull-up level, printed), "
            f"{back >> _PAD2CORE_BIT & 1} after both cleared",
        )

        await self._write("ALL_ONES", dc, _ALL_ONES)
        ones = await self._read("ALL_ONES_RB", dc)
        assert ones & rw == rw, f"writable bits read 0x{ones & rw:08x}, expected 0x{rw:08x}"
        assert ones & lsio == pre & lsio, f"bit 25 reads 0x{ones & lsio:08x} after all ones"
        assert ones & ~reg.declared_mask == 0, f"undeclared bits set: 0x{ones:08x}"
        await self._write("ALL_ZEROS", dc, 0)
        zeros = await self._read("ALL_ZEROS_RB", dc)
        assert zeros & rw == 0, f"writable bits read 0x{zeros & rw:08x} after writing 0x0"
        assert zeros & lsio == pre & lsio, f"bit 25 reads 0x{zeros & lsio:08x} after 0x0"
        self._mark("ALL_ONES_WRITE")
        self._chk(
            "ALL_ONES_WRITE",
            "CHK-GPIO-DATA-CTRL-WRITE-ALL-ONES",
            f"instance {_INSTANCE} after 0xffffffff the writable bits read 0x{ones & rw:08x}, "
            f"bit 25 read {ones >> _LSIO_ENABLE_BIT & 1}, bit 31 read "
            f"{ones >> _PAD2CORE_BIT & 1} (level printed); after 0x0 the writable bits read "
            f"0x{zeros & rw:08x}",
        )

        await self._write("RESTORE", dc, reset)
        final = await self._read("RESTORE_RB", dc)
        assert final & rw == reset & rw, f"restore reads 0x{final & rw:08x}"
        assert final & lsio == pre & lsio, f"bit 25 reads 0x{final & lsio:08x} after restore"
        final_en = await self._read("EN_END", en)
        assert final_en == en.reg.reset_word, f"DATA_CTRL_ENABLE restore reads 0x{final_en:08x}"
        self._mark("RESTORE_READBACK")
        self._nonvac()
