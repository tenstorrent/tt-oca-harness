# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA shared configuration registers: storage, field independence, retention, aliases.

Contract SMC_POWER_DMA_ZEROER_011, anchor smc_dma_csr_config_test.
Scenarios DMA-CSR-CONFIG.S1 to S5 (own value, HI full 32 bits, CONFIG fields, retention, alias).
Specs hw/sys/smc/doc/dma.adoc, hw/sys/smc/doc/memmap.adoc, vendor idma overlay dma_ctrl.rdl.

The destination bytes of both copies are read through the SYS_OUT responder's backdoor.
Reserved CONFIG bits [31:11] are never written; their read-back is measured and printed.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import DMA_CG_EN, smc_addr
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dma_sanity_test_seq import (
    DMA_CONFIG_ENABLED_ND,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
LOCAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
GLOBAL_BASE_MASK = 0x00FF_FFFF_FFFF_FFFF

REG_NAMES = (
    "CONFIG",
    "DST_ADDRESS_LO",
    "DST_ADDRESS_HI",
    "SRC_ADDRESS_LO",
    "SRC_ADDRESS_HI",
    "LENGTH_LO",
    "LENGTH_HI",
    "DST_STRIDE_LO",
    "DST_STRIDE_HI",
    "SRC_STRIDE_LO",
    "SRC_STRIDE_HI",
    "NUM_REPETITIONS_LO",
    "NUM_REPETITIONS_HI",
)
ADDR = {n: smc_addr(f"SMC_TOP_DMA_CTRL_{n}_BASE_ADDR") for n in REG_NAMES}
HI_NAMES = tuple(n for n in REG_NAMES if n.endswith("_HI"))
DONE_0 = smc_addr("SMC_TOP_DMA_CTRL_DONE_0_BASE_ADDR")
NEXT_ID_0 = smc_addr("SMC_TOP_DMA_CTRL_NEXT_ID_0_BASE_ADDR")

CONFIG_MASK = 0x7FF
SRC_MAX_LLEN_SHIFT = 4
DST_MAX_LLEN_SHIFT = 7

WINDOW = 0x0200_0000
GUARD = 8
GUARD_BYTE = 0xEE
POISON = 0xA5
POLL_LIMIT = 1000
POLL_CYCLES = 20
LINEAR_SRC = WINDOW + 0x100
LINEAR_DST = WINDOW + 0x200
ND_SRC = WINDOW + 0x400
ND_DST = WINDOW + 0x600
ROW_BYTES = 8
ND_SRC_STRIDE = 0x10
ND_DST_STRIDE = 0x20


def _own_pattern(index: int) -> int:
    return (0x9E37_79B9 * (index + 1)) & 0xFFFF_FFFF | 1


class smc_dma_csr_config_test_seq(SmcCsrSeq):
    """Storage, field independence, retention and alias reachability of the DMA registers."""

    def __init__(self, name: str = "smc_dma_csr_config_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.waits: list[tuple[str, int, str]] = []
        self.next_expected_id = 0

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        self.chk_ids.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    async def _write_all(self, tag: str, values: dict[str, int]) -> None:
        for name in REG_NAMES:
            await self.csr_write(f"{tag}_{name}", ADDR[name], values[name])

    async def _read_all(self, tag: str, want: dict[str, int]) -> dict[str, int]:
        got: dict[str, int] = {}
        for name in REG_NAMES:
            got[name] = await self.csr_read(f"{tag}_{name}", ADDR[name])
        for name in REG_NAMES:
            assert got[name] == want[name], (
                f"{tag}: {name} reads 0x{got[name]:08x}, expected 0x{want[name]:08x}; "
                f"readback { ({n: f'0x{v:08x}' for n, v in got.items()}) }"
            )
        return got

    async def _s1(self) -> None:
        dut = cocotb.top
        await wait_fuse_sense_done()
        cg = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        await self.csr_write("DMA_CG_EN_CLEAR", CLOCK_GATE_CONTROL, cg & ~DMA_CG_EN, length=8)
        cg_rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        assert cg_rb & DMA_CG_EN == 0, f"dma_cg_en still set: CLOCK_GATE_CONTROL=0x{cg_rb:x}"
        for name, addr, value in (
            ("IN_START", INBOUND0_START, 0),
            ("IN_END", INBOUND0_END, GLOBAL_BASE_MASK),
            ("IN_CFG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("OUT_START", OUTBOUND0_START, 0),
            ("OUT_END", OUTBOUND0_END, GLOBAL_BASE_MASK),
            ("OUT_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            await self.csr_write(f"PASS_{name}", addr, value, length=8)
        self.next_expected_id = await self.csr_read("DONE_BASE", DONE_0)
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> str:
        want = {name: _own_pattern(i) for i, name in enumerate(REG_NAMES)}
        want["CONFIG"] = 0x5A5
        assert len(set(want.values())) == len(REG_NAMES), "own patterns are not distinct"
        await self._write_all("OWN_WR", want)
        await self._read_all("OWN_RD", want)
        self._mark("S2")
        return (
            f"{len(REG_NAMES)} registers each read back their own pattern after all were written: "
            + ",".join(f"{n}=0x{want[n]:08x}" for n in REG_NAMES)
        )

    async def _s3(self) -> str:
        seen = []
        for i, name in enumerate(HI_NAMES):
            value = 0xFF00_0000 | ((0x11 * (i + 1)) << 8) | (i + 1)
            await self.csr_write(f"HI_WR_{name}", ADDR[name], value)
            got = await self.csr_read(f"HI_RD_{name}", ADDR[name])
            assert got == value, (
                f"{name} reads 0x{got:08x} after writing 0x{value:08x}; "
                f"bits [31:24] 0x{got >> 24:02x} expected 0x{value >> 24:02x}"
            )
            seen.append(f"{name}=0x{got:08x}")
        self._mark("S3")
        return f"{len(HI_NAMES)} HI registers read back all 32 bits incl. [31:24]: " + ",".join(
            seen
        )

    async def _s4(self) -> str:
        reserved_or = 0
        writes = 0

        async def sweep(value: int) -> None:
            nonlocal reserved_or, writes
            await self.csr_write(f"CFG_WR_0x{value:03x}", ADDR["CONFIG"], value)
            got = await self.csr_read(f"CFG_RD_0x{value:03x}", ADDR["CONFIG"])
            assert got & CONFIG_MASK == value, (
                f"CONFIG wrote 0x{value:03x}, bits [10:0] read 0x{got & CONFIG_MASK:03x} "
                f"(full 0x{got:08x})"
            )
            reserved_or |= got & ~CONFIG_MASK & 0xFFFF_FFFF
            writes += 1

        for bit in range(11):
            await sweep(1 << bit)
        for n in range(8):
            await sweep(n << SRC_MAX_LLEN_SHIFT)
        for n in range(8):
            await sweep(n << DST_MAX_LLEN_SHIFT)
        self._mark("S4")
        return (
            f"{writes} CONFIG writes (bits 0..10 alone, SRC_MAX_LLEN 0..7, DST_MAX_LLEN 0..7) "
            f"read back exactly in bits [10:0]; reserved bits [31:11] never written, read "
            f"back with OR 0x{reserved_or:08x} (SF-021 open: measured, not asserted)"
        )

    def _seed(self, src: int, dst: int, rows: int, src_stride: int, dst_stride: int) -> bytes:
        payload = b""
        for r in range(rows):
            row = bytes(((src + r * src_stride + i) * 7 + 0x31) & 0xFF for i in range(ROW_BYTES))
            self._responder.write(src + r * src_stride, row)
            self._responder.write(dst + r * dst_stride, bytes([POISON]) * ROW_BYTES)
            payload += row
        self._responder.write(dst - GUARD, bytes([GUARD_BYTE]) * GUARD)
        end = dst + (rows - 1) * dst_stride + ROW_BYTES
        self._responder.write(end, bytes([GUARD_BYTE]) * GUARD)
        return payload

    def _compare(self, name: str, payload: bytes, dst: int, rows: int, dst_stride: int) -> None:
        for r in range(rows):
            got = bytes(self._responder.read(dst + r * dst_stride, ROW_BYTES))
            want = payload[r * ROW_BYTES : (r + 1) * ROW_BYTES]
            assert got == want, f"{name}: row {r} holds {got.hex()}, expected {want.hex()}"
        before = bytes(self._responder.read(dst - GUARD, GUARD))
        after = bytes(self._responder.read(dst + (rows - 1) * dst_stride + ROW_BYTES, GUARD))
        guard = bytes([GUARD_BYTE]) * GUARD
        assert before == guard and after == guard, f"{name}: guard bytes changed"

    async def _copy(
        self, name: str, rows: int, src_stride: int, dst_stride: int, src: int, dst: int
    ) -> str:
        payload = self._seed(src, dst, rows, src_stride, dst_stride)
        want = {
            "CONFIG": DMA_CONFIG_ENABLED_ND,
            "DST_ADDRESS_LO": dst,
            "DST_ADDRESS_HI": 0,
            "SRC_ADDRESS_LO": src,
            "SRC_ADDRESS_HI": 0,
            "LENGTH_LO": ROW_BYTES,
            "LENGTH_HI": 0,
            "DST_STRIDE_LO": dst_stride,
            "DST_STRIDE_HI": 0,
            "SRC_STRIDE_LO": src_stride,
            "SRC_STRIDE_HI": 0,
            "NUM_REPETITIONS_LO": rows,
            "NUM_REPETITIONS_HI": 0,
        }
        await self._write_all(f"{name}_PROG", want)
        # Reading NEXT_ID launches the programmed descriptor.
        copy_id = await self.csr_read(f"{name}_NEXT_ID", NEXT_ID_0)
        assert copy_id == self.next_expected_id + 1, (
            f"{name}: NEXT_ID returned {copy_id} after DONE {self.next_expected_id}"
        )
        done = -1
        for _ in range(POLL_LIMIT):
            done = await self.csr_read(f"{name}_DONE", DONE_0)
            if done == copy_id:
                break
            assert done < copy_id, f"{name}: DONE_0 reads {done}, past its id {copy_id}"
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{name}: DONE_0 reached {done}, not id {copy_id} within {POLL_LIMIT} polls"
            )
        self.next_expected_id = copy_id
        self._compare(name, payload, dst, rows, dst_stride)
        await self._read_all(f"{name}_RD", want)
        return f"{name} id={copy_id} DONE_0={done}"

    async def _s5(self) -> str:
        linear = await self._copy("LINEAR", 1, 0x40, 0x80, LINEAR_SRC, LINEAR_DST)
        nd = await self._copy("ND2", 2, ND_SRC_STRIDE, ND_DST_STRIDE, ND_SRC, ND_DST)
        self._mark("S5")
        self.waits.append(("DONE_0_poll", POLL_LIMIT, f"DONE_0={self.next_expected_id}"))
        return (
            f"{linear} and {nd} retired and delivered their destination bytes; all "
            f"{len(REG_NAMES)} registers read the programmed value after each"
        )

    async def _s6(self) -> str:
        gb = await self.csr_read("GLOBAL_BASE_RD", GLOBAL_BASE, length=8)
        base = gb & GLOBAL_BASE_MASK
        local_base = await self.csr_read("LOCAL_BASE_RD", LOCAL_BASE, length=8)
        local_base &= GLOBAL_BASE_MASK

        def alias(addr: int) -> int:
            return base + (addr - local_base)

        a, b = "LENGTH_LO", "SRC_STRIDE_HI"
        v1, v2 = 0xA5C3_1E78, 0x1B2D_4F69
        await self.csr_write("ALIAS_LOCAL_WR", ADDR[a], v1)
        g1 = await self.csr_read("ALIAS_GLOBAL_RD", alias(ADDR[a]))
        assert g1 == v1, f"{a} written local 0x{v1:08x}, global alias reads 0x{g1:08x}"
        await self.csr_write("ALIAS_GLOBAL_WR", alias(ADDR[b]), v2)
        l2 = await self.csr_read("ALIAS_LOCAL_RD", ADDR[b])
        assert l2 == v2, f"{b} written global 0x{v2:08x}, local alias reads 0x{l2:08x}"
        self._mark("S6")
        return (
            f"{a} written at 0x{ADDR[a]:08x} read 0x{g1:08x} at 0x{alias(ADDR[a]):x}; "
            f"{b} written at 0x{alias(ADDR[b]):x} read 0x{l2:08x} at 0x{ADDR[b]:08x}; "
            f"GLOBAL_BASE=0x{base:x}"
        )

    async def body(self) -> None:
        await self._s1()
        self._chk("S2", "CHK-DMA-CSR-OWN-VALUE", await self._s2())
        self._chk("S3", "CHK-DMA-CSR-HI-FULL32", await self._s3())
        self._chk("S4", "CHK-DMA-CSR-CONFIG-FIELDS", await self._s4())
        self._chk("S5", "CHK-DMA-CSR-RETAIN-AFTER-COPY", await self._s5())
        self._chk("S6", "CHK-DMA-CSR-GLOBAL-ALIAS", await self._s6())
        self._nonvac()

    def _nonvac(self) -> None:
        order = ["S1", "S2", "S3", "S4", "S5", "S6"]
        assert [s for s, _ in self.steps] == order, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        want = [
            ("S2", "CHK-DMA-CSR-OWN-VALUE"),
            ("S3", "CHK-DMA-CSR-HI-FULL32"),
            ("S4", "CHK-DMA-CSR-CONFIG-FIELDS"),
            ("S5", "CHK-DMA-CSR-RETAIN-AFTER-COPY"),
            ("S6", "CHK-DMA-CSR-GLOBAL-ALIAS"),
        ]
        assert self.chk_steps == want, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; checker lines %s; stamps %s",
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
