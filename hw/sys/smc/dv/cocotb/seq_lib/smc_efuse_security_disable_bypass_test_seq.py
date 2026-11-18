# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse security-disable bypass: no bank read, all-zero shadow registers, no sense wait.

Specs: hw/ip/efuse/doc/architecture.adoc (Security Disable Bypass Mechanism, the
eFuse security-disable behavior table: FSM Bypass, Shadow Register Loading, APB Access, Reset
Values; "For SMC, the internal security disable signal is directly driven by the
`security_disable_i` input port") and hw/sys/smc/doc/clk_rst.adoc (Primary and Warm Reset).

The run carries `+smc_sep_security_disable`, so `tb_sep_security_disable` holds
`sep_security_disable_i` at 1 from time 0. The leaf writes a `random` bank image before the
primary reset releases (the bank model loads it at that release) and starts `BypassSampler`
before the clocks run. The sampler reads the hook level at every `clk_smc_i` rise and, from the
first rise with `rst_primary_smc_clk_no` at 1, the shim command and response valids, the bank
read channel, `tb_fuse_sense_done` and the warm reset. The seed draws the shadow registers read
and the three read times; LOCKS word 0, whose bank word `tb_efuse_otp_word0` shows non-zero, and
one 64-bit register read at full width are read at every time on every seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_image_pattern_test_seq import LOCKS_WORDS, EfuseImage
from .smc_efuse_vip_utils import EFUSE_MAP_BASE, EFUSE_MAP_SIZE

EFUSE_MAP_WORDS = EFUSE_MAP_SIZE // 4
#: architecture.adoc, Security Disable Bypass Mechanism: the shadow registers retain their reset
#: values, all zeros for SMC.
SHADOW_BYPASS_VALUE = 0

#: Word offsets of the 64-bit registers of SMC_EFUSE_MAP other than LOCKS.
REG64_WORDS = tuple(
    (addr - EFUSE_MAP_BASE) // 4
    for addr in (
        *(
            smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", k)
            for k in range(smc_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_NUM"))
        ),
        smc_addr("SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR"),
        smc_addr("SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR"),
    )
)
LOCKS_LOW_WORD = LOCKS_WORDS[0]

WINDOW = 200_000
READ_TIMES = 3
REGS_MIN, REGS_MAX = 4, 8
# Read-time offsets in clk_smc_i rises: the first from the scenario start, each next from the
# previous read time.
T1_RANGE = (1, 2_000)
T2_RANGE = (1_000, 30_000)
T3_RANGE = (1_000, 60_000)
TAIL_CYCLES = 2

STEPS = ("S1", "S2", "S3", "S4")
CHK_STEPS = (
    ("CHK-SDB-IMAGE-NONZERO", "S1"),
    ("CHK-SDB-SHADOW-ZERO", "S2"),
    ("CHK-SDB-ACCESS-NO-WAIT", "S2"),
    ("CHK-SDB-NO-BANK-READ", "S3"),
    ("CHK-SDB-HOOK-LEVEL", "S3"),
)
_POST_TAPS = (
    "tb_efuse_shim_cmd_valid",
    "tb_efuse_shim_resp_valid",
    "tb_efuse_bank_arvalid",
    "tb_efuse_bank_rvalid",
    "tb_fuse_sense_done",
    "tb_rst_warm_smc_clk_n",
    "rst_primary_smc_clk_no",
    "tb_sep_security_disable",
)
CMD, RESP, BANK_AR, BANK_R, SENSE, WARM, PRIMARY, HOOK = range(len(_POST_TAPS))


def _level(signal) -> str:
    """A printed-only level: the value, or its raw form when it does not resolve."""
    value = signal.value
    return str(int(value)) if value.is_resolvable else str(value)


class BypassSampler:
    """Hook level at every `clk_smc_i` rise; the bank and sense taps after the primary release."""

    def __init__(self) -> None:
        self.running = True
        self.pre = 0
        self.pre_hook_low = 0
        self.post = 0
        self.ones = [0] * len(_POST_TAPS)
        self.first_sense = -1
        self.release_ps = -1

    async def run(self) -> None:
        dut = cocotb.top
        while self.running:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            hook = dut.tb_sep_security_disable.value
            assert hook.is_resolvable, f"tb_sep_security_disable is X/Z ({hook}) at rise {self.pre}"
            prim = dut.rst_primary_smc_clk_no.value
            if self.post == 0 and not (prim.is_resolvable and int(prim) == 1):
                self.pre += 1
                self.pre_hook_low += int(hook) == 0
                continue
            if self.post == 0:
                self.release_ps = int(get_sim_time("ps"))
            row = []
            for name in _POST_TAPS:
                value = getattr(dut, name).value
                assert value.is_resolvable, f"{name} is X/Z ({value}) at post-release {self.post}"
                row.append(int(value) & 1)
            for tap, bit in enumerate(row):
                self.ones[tap] += bit
            if row[SENSE] and self.first_sense < 0:
                self.first_sense = self.post
            self.post += 1


@dataclass(frozen=True)
class _Reg:
    word: int
    length: int
    pinned: str

    @property
    def addr(self) -> int:
        return EFUSE_MAP_BASE + 4 * self.word

    @property
    def words(self) -> tuple[int, ...]:
        return tuple(range(self.word, self.word + self.length // 4))

    def label(self) -> str:
        tag = f" {self.pinned}" if self.pinned else ""
        return f"0x{self.addr:08x}/{8 * self.length}b{tag}"


class smc_efuse_security_disable_bypass_test_seq(SmcCsrSeq):
    """Drawn shadow registers read at three drawn times under the held security-disable input."""

    def __init__(
        self,
        name: str = "smc_efuse_security_disable_bypass_test_seq",
        *,
        seed: int,
        image: EfuseImage,
        sampler: BypassSampler,
    ) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.image = image
        self.sampler = sampler
        self.regs: list[_Reg] = []
        self.times: list[int] = []
        self.reads: list[list[tuple[_Reg, int, int, int, int, int]]] = []
        self.bank_word0 = -1
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.waits: list[str] = []
        self.done = False

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    def _drawn(self) -> str:
        regs = ", ".join(r.label() for r in self.regs)
        return f"drawn=registers [{regs}] read times {self.times} (post-release clk_smc_i rises)"

    def _nonzero(self, reg: _Reg) -> bool:
        return all(self.image.words[w] != 0 for w in reg.words)

    def _image_value(self, reg: _Reg) -> int:
        return sum(self.image.words[w] << (32 * i) for i, w in enumerate(reg.words))

    def _draw(self, s0: int) -> None:
        words = self.image.words
        assert len(words) == EFUSE_MAP_WORDS, f"image holds {len(words)} words"
        regs = [_Reg(LOCKS_LOW_WORD, 4, "pinned LOCKS word 0")]
        wide = [w for w in REG64_WORDS if words[w] and words[w + 1]]
        assert wide, "no 64-bit register has both image words non-zero"
        regs.append(_Reg(self.rng.choice(wide), 8, "pinned 64-bit"))
        used = {w for r in regs for w in r.words}
        count = self.rng.randint(REGS_MIN, REGS_MAX)
        pool = [w for w in range(EFUSE_MAP_WORDS) if words[w] and w not in used]
        self.rng.shuffle(pool)
        for w in pool:
            if len(regs) == count:
                break
            if w in used:
                continue
            length = 4
            if w in REG64_WORDS and words[w + 1] and w + 1 not in used:
                length = self.rng.choice((4, 8))
            reg = _Reg(w, length, "")
            regs.append(reg)
            used.update(reg.words)
        assert len(regs) == count, f"drew {len(regs)} registers, want {count}"
        assert all(self._nonzero(r) for r in regs), "a drawn register has a zero image word"
        assert len(used) == sum(len(r.words) for r in regs), "drawn registers overlap"
        self.regs = regs
        t1 = s0 + self.rng.randint(*T1_RANGE)
        t2 = t1 + self.rng.randint(*T2_RANGE)
        t3 = t2 + self.rng.randint(*T3_RANGE)
        self.times = [t1, t2, t3]
        assert t3 < WINDOW, f"read time {t3} not inside the {WINDOW}-rise window (start {s0})"

    async def _read(self, reg: _Reg, tag: str) -> tuple[int, int, int]:
        item = SmcSysAxiItem(f"rd_SHADOW_{tag}_0x{reg.addr:08x}")
        item.op, item.addr, item.length = SmcSysAxiOp.READ, reg.addr, reg.length
        item.expected = SHADOW_BYPASS_VALUE
        t0 = get_sim_time("ns")
        await self.start_item(item)
        await self.finish_item(item)
        latency = int(get_sim_time("ns") - t0)
        self.accesses += 1
        assert not item.timed_out, f"{tag} {reg.label()}: no response within the driver guard"
        assert item.resp_code == 0, (
            f"{tag} {reg.label()}: response {item.resp_code}, want OKAY; {self._drawn()}"
        )
        return int(item.rdata), int(item.resp_code), latency

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        smp = self.sampler
        for name in _POST_TAPS + ("tb_efuse_otp_word0",):
            assert hasattr(dut, name), f"tb_top has no {name}"
        assert smp.post > 0, "the scenario started before rst_primary_smc_clk_no released"
        s0 = smp.post
        self._draw(s0)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %d shadow registers %s; read times %s post-release "
            "clk_smc_i rises (scenario start %d; offsets %s, %s, %s); image %s",
            self.seed,
            len(self.regs),
            [r.label() for r in self.regs],
            self.times,
            s0,
            T1_RANGE,
            T2_RANGE,
            T3_RANGE,
            self.image.path.name,
        )
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        bank0 = dut.tb_efuse_otp_word0.value
        assert bank0.is_resolvable, f"tb_efuse_otp_word0 is X/Z ({bank0})"
        self.bank_word0 = int(bank0)
        image0 = self.image.words[LOCKS_LOW_WORD]
        assert image0 != 0, f"{self.image.path.name} word 0 is 0"
        assert self.bank_word0 == image0, (
            f"bank-model word 0 0x{self.bank_word0:08x}, image word 0 0x{image0:08x}: the "
            "generated image did not reach the bank model"
        )
        await RisingEdge(dut.clk_smc_i)
        self._mark("S1")
        vals = ", ".join(f"{r.label()}=0x{self._image_value(r):x}" for r in self.regs)
        self._chk(
            "S1",
            "CHK-SDB-IMAGE-NONZERO",
            f"bank-model word 0 (tb_efuse_otp_word0) 0x{self.bank_word0:08x} equals word 0 of "
            f"{self.image.path.name}, so the bank holds that image, and every word of every "
            f"drawn register is non-zero in it: {vals}; {self._drawn()}",
        )

    async def _s2(self) -> None:
        dut = cocotb.top
        smp = self.sampler
        for idx, t in enumerate(self.times):
            waited = 0
            while smp.post < t:
                assert waited <= WINDOW, f"read time {t}: sampler at {smp.post} after {waited}"
                await RisingEdge(dut.clk_smc_i)
                waited += 1
            start = smp.post
            rows = []
            for reg in self.regs:
                issue = _level(dut.tb_fuse_sense_done)
                rdata, resp, latency = await self._read(reg, f"T{idx + 1}")
                sense = (issue, _level(dut.tb_fuse_sense_done))
                rows.append((reg, rdata, resp, latency, sense, _level(dut.tb_rst_warm_smc_clk_n)))
            self.reads.append(rows)
            self.waits.append(f"read_time_{idx + 1}={t}(began {start})<={WINDOW} clk_smc_i")
        self._mark("S2")
        bad = [
            (i + 1, reg.label(), f"0x{rdata:x}")
            for i, rows in enumerate(self.reads)
            for reg, rdata, *_ in rows
            if rdata != SHADOW_BYPASS_VALUE
        ]
        assert not bad, f"shadow reads not 0 under the bypass: {bad}; {self._drawn()}"
        cells = "; ".join(
            f"T{i + 1}: " + ", ".join(f"{r.label()}=0x{d:x}/resp {c}" for r, d, c, *_ in rows)
            for i, rows in enumerate(self.reads)
        )
        self._chk(
            "S2",
            "CHK-SDB-SHADOW-ZERO",
            f"{sum(len(r) for r in self.reads)} reads over {READ_TIMES} read times returned "
            f"0x{SHADOW_BYPASS_VALUE:x} with OKAY on every drawn register although its image "
            f"word is non-zero: {cells}; {self._drawn()}",
        )
        guard = self.cfg.axi_timeout_ns
        lat = [lat for rows in self.reads for _, _, _, lat, _, _ in rows]
        sensed = [
            (i + 1, reg.label(), s) for i, rows in enumerate(self.reads) for reg, *_, s, _ in rows
        ]
        assert all(s == ("0", "0") for *_, s in sensed), (
            f"tb_fuse_sense_done not 0 at the issue and the completion of every shadow read, so "
            f"a read may have waited on it (time, register, (issue, completion)): {sensed}; "
            f"{self._drawn()}"
        )
        warm = [w for rows in self.reads for *_, w in rows]
        self._chk(
            "S2",
            "CHK-SDB-ACCESS-NO-WAIT",
            f"every one of {len(lat)} shadow reads completed OKAY inside the {guard} ns driver "
            f"guard (latency min {min(lat)} max {max(lat)} ns), the only bound, with "
            f"tb_fuse_sense_done 0 at the issue and the completion of each read; logged, not "
            f"compared: tb_rst_warm_smc_clk_n at the reads {sorted(set(warm))}; {self._drawn()}",
        )

    async def _s3(self) -> None:
        dut = cocotb.top
        smp = self.sampler
        waited = 0
        while smp.post < WINDOW:
            assert waited <= WINDOW, f"sampler at {smp.post} after {waited} rises"
            await RisingEdge(dut.clk_smc_i)
            waited += 1
        self.waits.append(f"window={smp.post}>={WINDOW} post-release clk_smc_i rises")
        smp.running = False
        await RisingEdge(dut.clk_smc_i)
        self._mark("S3")
        n = smp.post
        ones = smp.ones
        assert ones[CMD] == 0 and ones[RESP] == 0, (
            f"bank read under the bypass: tb_efuse_shim_cmd_valid 1 at {ones[CMD]} and "
            f"tb_efuse_shim_resp_valid 1 at {ones[RESP]} of {n} rises; {self._drawn()}"
        )
        sense_end = _level(dut.tb_fuse_sense_done)
        self._chk(
            "S3",
            "CHK-SDB-NO-BANK-READ",
            f"tb_efuse_shim_cmd_valid and tb_efuse_shim_resp_valid read 0 at all {n} "
            f"clk_smc_i rises from the primary reset release (window {WINDOW}); logged, not "
            f"compared: tb_efuse_bank_arvalid 1 at {ones[BANK_AR]}, tb_efuse_bank_rvalid 1 "
            f"at {ones[BANK_R]}, tb_fuse_sense_done 1 at {ones[SENSE]} rises (first "
            f"{smp.first_sense}) and {sense_end} at the window end, tb_rst_warm_smc_clk_n 1 at "
            f"{ones[WARM]} rises; {self._drawn()}",
        )
        assert smp.pre_hook_low == 0 and ones[HOOK] == n, (
            f"tb_sep_security_disable read 0 at {smp.pre_hook_low} of {smp.pre} rises before "
            f"the primary release and at {n - ones[HOOK]} of {n} after it"
        )
        assert ones[PRIMARY] == n, f"rst_primary_smc_clk_no low at {n - ones[PRIMARY]} rises"
        self._chk(
            "S3",
            "CHK-SDB-HOOK-LEVEL",
            f"tb_sep_security_disable (sep_security_disable_i) read 1 at all {smp.pre} rises "
            f"before the primary reset release and all {n} rises after it, and "
            f"rst_primary_smc_clk_no stayed 1 after its release; {self._drawn()}",
        )

    async def _s4(self) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, TAIL_CYCLES)
        self._mark("S4")
        guard = self.cfg.axi_timeout_ns
        self.waits.append(f"axi_access<={guard} ns per access ({self.accesses} accesses)")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; each wait raises AssertionError at its "
            "bound and the driver fails an access with no response inside %d ns",
            len(self.waits),
            "; ".join(self.waits),
            guard,
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == list(CHK_STEPS), f"checker lines {self.chk_lines}"
        assert len(self.reads) == READ_TIMES, f"{len(self.reads)} read times"
        per_time = [len(rows) for rows in self.reads]
        assert all(n >= REGS_MIN for n in per_time), f"registers per read time {per_time}"
        assert self.sampler.post >= WINDOW, f"window {self.sampler.post} rises"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; %d read times with %s "
            "registers each; sampler window %d rises; %s",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(c for c, _ in self.chk_lines),
            len(self.reads),
            per_time,
            self.sampler.post,
            self._drawn(),
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        self.done = True
