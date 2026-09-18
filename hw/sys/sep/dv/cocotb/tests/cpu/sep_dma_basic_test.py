# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Secure-DMA basic-breadth firmware-boot test (PyUVM).

OSS rep DMA basic breadth. reference provenance: the uvm_tests/dma reg_rw / reg_reset /
cfg_regwen / range_regwen / addr_fixed / addr_wrap / addr_combo / mem_copy
(width sweep) / err_opcode family. Boots the VeeR EL2 core and runs the
dma_basic firmware, which drives the Secure DMA over the CPU LSU and proves the
DMA CSR + copy-datapath basic contracts on bare sep (SRAM->SRAM transfers).

Distinct from the DMA trio (sep_dma_hash inline SHA-256 + SRAM->DCCM +
IRQ; sep_dma_cpu_contention mid-flight BUSY + dual-master; sep_spi_ot_dma_rx
lsio handshake): DMA basic breadth adds the CSR/REGWEN breadth, the FIXED/INCR/WRAP address-
mode matrix, the 1B/2B/4B transfer-width sweep, and one opcode-error path.

SepDmaBasicCfg is the single source of truth for src/dst offsets, copy length
and fill seed. Discrete mode/width cells stay walked every invocation; the
continuous knobs come from the run seed (patched into the firmware param block).

Firmware-self-checking: the firmware returns its error count and start.S emits
the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on the 0x8000_0000 mailbox, which
the boot scoreboard gates on. The firmware self-checks (each with a positive PASS
line in the console log): CHK-RESET (reset values), CHK-CFG-REGWEN (HW busy-lock),
CHK-RANGE-REGWEN (range gating + rw0c lock), CHK-COPY-MODE (FIXED/INCR/WRAP
expected images + neighbor), CHK-WIDTH (1B/2B/4B), CHK-DONE-RW1C, CHK-ERR-OPCODE
(opcode_error + recovery), CHK-ERR-ADDR (four misaligned descriptors, each
raising its ERROR_CODE bit exclusively, then a recovery copy), CHK-HOSTINTG
(DMA-issued command under dma_host_intg_inject_i -> exclusive host_path_err
+ aggregator [41], CLEAR, recovery copy), CHK-HOSTFABRIC (fabric DECERR dest
-> exclusive host_path_err with the pin low, CLEAR, recovery). The
scoreboard also checks the banner + ICCM execution.

cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_basic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_basic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_basic_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 4_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP DMA basic test"

_PARAM_MAGIC = 0xDA0A11C0
_BUSY_LEN = 0x100
_IRQ_DMA_REG_PATH = 40
_IRQ_DMA_HOST_PATH = 41
_PIC_POLL = 200_000


@dataclass(frozen=True)
class SepDmaBasicCfg:
    """Single source of truth for DMA basic-breadth continuous knobs.

    Discrete cells (INCR/FIXED/WRAP x 1B/2B/4B) are walked every invocation.
    src/dst offsets, copy length and fill seed come from the run seed.
    """

    seed: int
    src_off: int
    dst_off: int
    nbytes: int
    fill_seed: int

    @classmethod
    def from_seed(cls, seed: int) -> "SepDmaBasicCfg":
        # The stimulus is a pure function of the seed, so a failing leaf replays
        # with `--stage sim --seed N`.
        rng = SepSeededRng(seed)
        nbytes = rng.choice((16, 32))
        src_off = rng.randrange(0, 0x10000, 16)
        dst_off = rng.randrange(0x20000, 0x30000, 16)
        fill = rng.getrandbits(32) or 0x1234567
        return cls(seed=seed, src_off=src_off, dst_off=dst_off, nbytes=nbytes, fill_seed=fill)

    def param_words(self) -> list[int]:
        return [_PARAM_MAGIC, self.src_off, self.dst_off, self.nbytes, self.fill_seed]


def _probe_bit_raw(sig, bit: int) -> str:
    """One bit of a probe as its raw character: '0', '1', or 'x'/'z'.

    The shared rd() helper resolves unknowns to zero per bit, which is right
    where a zero is the failing direction and wrong where it is the passing
    one. Two cocotb versions are in use: 1.x exposes BinaryValue.binstr, 2.x a
    LogicArray that str()s to the same characters.
    """
    v = sig.value
    text = getattr(v, "binstr", None) or str(v)
    # binstr is most-significant-first, so index from the right.
    return text[len(text) - 1 - bit].lower()


@pyuvm.test()
class sep_dma_basic_test(sep_base_test):
    """Boot VeeR EL2 and run the Secure-DMA basic-breadth firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self) -> str:
        cfg = SepDmaBasicCfg.from_seed(self.random_seed())
        # The source and destination windows must not overlap, or a copy would
        # read bytes it has already written and the golden compare would pass on
        # a DMA that did nothing. The ranges the config draws from are disjoint;
        # this fails if either is widened into the other.
        src_hi = cfg.src_off + _BUSY_LEN
        dst_hi = cfg.dst_off + _BUSY_LEN
        assert src_hi <= cfg.dst_off or dst_hi <= cfg.src_off, (
            f"DMA windows overlap: src 0x{cfg.src_off:x}..0x{src_hi:x} "
            f"dst 0x{cfg.dst_off:x}..0x{dst_hi:x}"
        )
        patched = os.path.join(os.getcwd(), "sep_dtcm_dma.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, cfg.param_words())
        self.logger.info(
            "DMA basic RANDCFG seed=%d src_off=0x%x dst_off=0x%x nbytes=%d fill=0x%08x",
            cfg.seed,
            cfg.src_off,
            cfg.dst_off,
            cfg.nbytes,
            cfg.fill_seed,
        )
        self._dma_cfg = cfg
        return patched

    async def _drive_host_intg_inject(self) -> None:
        """Drive ``dma_host_intg_inject_i`` for the integrity copy.

        Pin high from CHK-HOSTINTG-ARM until CHK-HOSTINTG-RELEASE.
        Aggregator bit 41 must be 1 and exclusive of bit 40 while the pin
        is high, and 0 after CLEAR.
        """
        dut = cocotb.top
        for _ in range(_MAX_RUN_CYCLES):
            text = self.sb.console_text()
            if "CHK-HOSTINTG-ARM" in text:
                break
            if self.sb.fw_done:
                raise AssertionError("firmware finished without printing CHK-HOSTINTG-ARM")
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError("firmware never printed CHK-HOSTINTG-ARM")

        dut.dma_host_intg_inject_i.value = 1
        self.logger.info("STEP host-intg: dma_host_intg_inject_i=1")

        # Bit 41 asserts only on a DMA-issued a_valid. RELEASE with the bit
        # still low means the injected command did not set host_path_err.
        for _ in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            vec = self.rd(dut.sep_internal_interrupts_probe_o)
            if (vec >> _IRQ_DMA_HOST_PATH) & 1:
                assert ((vec >> _IRQ_DMA_REG_PATH) & 1) == 0, (
                    f"register-path [40] set on host-path inject (vec=0x{vec:x})"
                )
                self.logger.info(
                    "CHK-HOSTINTG-PIC PASS: sep_internal_interrupts[41]=1 exclusive (vec=0x%x)",
                    vec,
                )
                break
            if self.sb.fw_done or "CHK-HOSTINTG-RELEASE" in self.sb.console_text():
                raise AssertionError(
                    "sep_internal_interrupts[41] stayed 0 through the injected DMA command"
                )
        else:
            raise AssertionError("sep_internal_interrupts[41] stayed 0 after host-path inject")

        for _ in range(_MAX_RUN_CYCLES):
            if "CHK-HOSTINTG-RELEASE" in self.sb.console_text():
                break
            if self.sb.fw_done:
                raise AssertionError("firmware finished without printing CHK-HOSTINTG-RELEASE")
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError("firmware never printed CHK-HOSTINTG-RELEASE")

        dut.dma_host_intg_inject_i.value = 0
        self.logger.info("STEP host-intg: dma_host_intg_inject_i=0")

        # self.rd() resolves an unknown bit to 0, which is the safe direction for
        # the assert leg above but the wrong one here: an X would read as a
        # cleared bit and pass. Require a RESOLVED zero instead.
        for _ in range(_PIC_POLL):
            await RisingEdge(dut.clk_i)
            bit = _probe_bit_raw(dut.sep_internal_interrupts_probe_o, _IRQ_DMA_HOST_PATH)
            if bit == "0":
                self.logger.info(
                    "CHK-HOSTINTG-CLR PASS: sep_internal_interrupts[41] resolved 0 "
                    "after DMA_BUS_ERR_CLEAR"
                )
                return
        raise AssertionError(
            f"sep_internal_interrupts[41] not a resolved 0 after DMA_BUS_ERR_CLEAR "
            f"(last raw value {bit!r}); an X here is not a cleared bit"
        )

    async def _check_host_fabric_pin(self) -> None:
        """Require the integrity inject pin low at the fabric-DECERR arm."""
        dut = cocotb.top
        for _ in range(_MAX_RUN_CYCLES):
            if "CHK-HOSTFABRIC-ARM" in self.sb.console_text():
                pin = self.rd_known(dut.dma_host_intg_inject_i)
                assert pin == 0, (
                    f"CHK-HOSTFABRIC-ARM: dma_host_intg_inject_i={pin}, expected 0"
                )
                self.logger.info("CHK-HOSTFABRIC-ARM PASS: dma_host_intg_inject_i=0")
                return
            if self.sb.fw_done:
                raise AssertionError("firmware finished without printing CHK-HOSTFABRIC-ARM")
            await RisingEdge(dut.clk_i)
        raise AssertionError("firmware never printed CHK-HOSTFABRIC-ARM")

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        dtcm = self._stage_dtcm()
        inj = cocotb.start_soon(self._drive_host_intg_inject())
        fabric = cocotb.start_soon(self._check_host_fabric_pin())
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            dtcm,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
        await inj
        await fabric
        cfg = self._dma_cfg
        needle = (
            f"SCENARIO src=0x{_SRAM_BASE + cfg.src_off:08x} "
            f"dst=0x{_SRAM_BASE + cfg.dst_off:08x} "
            f"nbytes=0x{cfg.nbytes:08x} "
            f"fill=0x{cfg.fill_seed:08x}"
        )
        console = self.sb.console_text()
        if needle not in console:
            raise AssertionError(
                "firmware did not consume the patched DMA cfg "
                f"(missing {needle!r} in console; patch was inert or the image is stale)"
            )
        if "CHK-HOSTINTG PASS:" not in console:
            raise AssertionError(
                "firmware console missing CHK-HOSTINTG PASS "
                "(host-path integrity contract was not proven)"
            )
        if "CHK-HOSTFABRIC PASS:" not in console:
            raise AssertionError(
                "firmware console missing CHK-HOSTFABRIC PASS "
                "(host-path fabric non-OKAY contract was not proven)"
            )
        # The two checkers that actually walk the modes and the widths. Logging
        # CHK-RAND-REP without them would put a PASS record in the kept log on a
        # run where the walk failed -- poll_boot returns normally on a firmware
        # FAIL, and the scoreboard verdict lands later.
        for needle, what in (
            ("CHK-COPY-MODE PASS:", "the INCR/FIXED/WRAP walk"),
            ("CHK-WIDTH PASS:", "the 1B/2B/4B width walk"),
            ("CHK-ERR-ASID PASS:", "the unencoded-ASID error legs"),
            ("CHK-ERR-SIZE PASS:", "the unencoded-width error leg"),
            ("CHK-ICCM PASS:", "the SRAM->ICCM->SRAM round trip"),
        ):
            if needle not in console:
                raise AssertionError(
                    f"firmware console missing {needle} ({what} did not pass), so "
                    "CHK-RAND-REP has nothing to report"
                )
        self.logger.info(
            "CHK-RAND-REP PASS: walked INCR/FIXED/WRAP x 1B/2B/4B; seed=%d nbytes=%d",
            cfg.seed,
            cfg.nbytes,
        )
