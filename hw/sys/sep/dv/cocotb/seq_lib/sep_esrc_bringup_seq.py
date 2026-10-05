# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC -> DRBG -> CSRNG -> EDN entropy bring-up sequences and register helpers.

PHASE-A applies the shared TRNG reset, configures ESRC with the generators off,
enables CSRNG and stages the EDN commands without enabling EDN. The caller then
enables the generators and waits for a seed; PHASE-B enables EDN last. CSRNG/EDN
registers sit behind a 64-bit lane adapter, so a 4-byte write at the register's
byte address lands on the correct lane.

Typical flow from a test:

    await self.start_seq(SepEsrcConfigSeq(...))         # PHASE-A
    await self.start_seq(SepEsrcEnableGeneratorsSeq())
    assert await self.wait_seed_ready()
    await self.start_seq(SepEsrcEnableEdnSeq())          # PHASE-B
    assert await self.wait_genbits()
    assert await self.wait_km_entropy_handshake()
    await self.check_entropy_alerts_zero()
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from pyuvm import uvm_sequence
from sep_reg_meta import CSRNG, EDN, ENTROPY_SOURCE, SEP_CPU_CTRL, SEP_RESET_CTRL, sym

# --- register map -----------------------------------------------------------
# sep_cpu_ctrl addresses come from the generated SystemRDL export, never literals.
# No field of sep_cpu_ctrl.rdl CLOCK_GATE_CTRL gates the ESRC/CSRNG/EDN CSRs,
# so this write releases nothing; it exercises the CSR write path only.
#
# The reset value keeps this write inert however many clock-gate enables the RDL
# adds to the register.
CLOCK_GATE_CTRL = SEP_CPU_CTRL.addr("CLOCK_GATE_CTRL")
CLOCK_GATE_CTRL_RESET = SEP_CPU_CTRL.reset("CLOCK_GATE_CTRL")
EXT_TRNG_SRC_SEL = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")
SW_RESET_N = SEP_RESET_CTRL.addr("SW_RESET_N")
TRNG_SW_RST_N_MASK = SEP_RESET_CTRL.field_mask("SW_RESET_N", "trng_sw_rst_n")
# EXT_TRNG_SRC_SEL.sel has one bit per stream: 0 = internal DRBG, 1 = external TRNG.
EXT_TRNG_ALL_EXTERNAL = SEP_CPU_CTRL.field_mask("EXT_TRNG_SRC_SEL", "sel")
# entropy_source / CSRNG / EDN addresses from the generated top-level export.
ESRC_CTRL = sym("ENTROPY_SOURCE_CTRL_REG_ADDR")
ESRC_INTR_STATUS = sym("ENTROPY_SOURCE_INTR_STATUS_REG_ADDR")
ESRC_INTR_ENABLE = sym("ENTROPY_SOURCE_INTR_ENABLE_REG_ADDR")
ESRC_INTR_TEST = sym("ENTROPY_SOURCE_INTR_TEST_REG_ADDR")
ESRC_FIFO_CTRL = sym("ENTROPY_SOURCE_FIFO_CTRL_REG_ADDR")
ESRC_FIFO_STATUS = sym("ENTROPY_SOURCE_FIFO_STATUS_REG_ADDR")
ESRC_FIFO_RDATA = sym("ENTROPY_SOURCE_FIFO_RDATA_REG_ADDR")
ESRC_HEALTH_TEST_CTRL = sym("ENTROPY_SOURCE_HEALTH_TEST_CTRL_REG_ADDR")
ESRC_HEALTH_TEST_WINDOW_SIZE = sym("ENTROPY_SOURCE_HEALTH_TEST_WINDOW_SIZE_REG_ADDR")
ESRC_HEALTH_TEST_STATUS = sym("ENTROPY_SOURCE_HEALTH_TEST_STATUS_REG_ADDR")
ESRC_HT_WATERMARK_NUM = sym("ENTROPY_SOURCE_HT_WATERMARK_NUM_REG_ADDR")
ESRC_HT_WATERMARK = sym("ENTROPY_SOURCE_HT_WATERMARK_REG_ADDR")
ESRC_MAIN_SM_STATUS = sym("ENTROPY_SOURCE_MAIN_SM_STATUS_REG_ADDR")
ESRC_RING_OSC_ENABLE = sym("ENTROPY_SOURCE_RING_OSC_ENABLE_REG_ADDR")
ESRC_RING_OSC_TUNE = sym("ENTROPY_SOURCE_RING_OSC_TUNE_REG_ADDR")
ESRC_DECORRELATOR_CTRL = sym("ENTROPY_SOURCE_DECORRELATOR_CTRL_REG_ADDR")
ESRC_GEN0_SAMPLE_CLK = sym("ENTROPY_SOURCE_GENERATOR_0_SAMPLE_CLK_CONFIG_REG_ADDR")
ESRC_FIPS_LOCK = sym("ENTROPY_SOURCE_FIPS_LOCK_REG_ADDR")
ESRC_ALERT_THRESHOLD = sym("ENTROPY_SOURCE_ALERT_THRESHOLD_REG_ADDR")
ESRC_ALERT_SUMMARY_FAIL_COUNTS = sym("ENTROPY_SOURCE_ALERT_SUMMARY_FAIL_COUNTS_REG_ADDR")
ESRC_MARKOV_TEST_PROB_THRESHOLDS = sym("ENTROPY_SOURCE_MARKOV_TEST_PROB_THRESHOLDS_REG_ADDR")
ESRC_APT_PROPORTION_1BIT = sym("ENTROPY_SOURCE_APT_PROPORTION_1BIT_REG_ADDR")
ESRC_APT_PROPORTION_LO = sym("ENTROPY_SOURCE_APT_PROPORTION_LO_REG_ADDR")
ESRC_RING_OSC_CTRL = sym("ENTROPY_SOURCE_RING_OSC_CTRL_REG_ADDR")
ESRC_DECORRELATOR_MASK = sym("ENTROPY_SOURCE_DECORRELATOR_MASK_REG_ADDR")
ESRC_MIN_ENTROPY_H = sym("ENTROPY_SOURCE_MIN_ENTROPY_H_REG_ADDR")
ESRC_RECOMMENDED_THRESHOLDS = sym("ENTROPY_SOURCE_RECOMMENDED_THRESHOLDS_REG_ADDR")
ESRC_ALERT_FAIL_COUNTS = sym("ENTROPY_SOURCE_ALERT_FAIL_COUNTS_REG_ADDR")
ESRC_BIW_OBS_CTRL = sym("ENTROPY_SOURCE_BIW_OBS_CTRL_REG_ADDR")
CSRNG_CTRL = sym("CSRNG_CTRL_REG_ADDR")
CSRNG_ERR_CODE = sym("CSRNG_ERR_CODE_REG_ADDR")
CSRNG_RECOV_ALERT = sym("CSRNG_RECOV_ALERT_STS_REG_ADDR")
EDN_CTRL = sym("EDN_CTRL_REG_ADDR")
EDN_BOOT_INS_CMD = sym("EDN_BOOT_INS_CMD_REG_ADDR")
EDN_BOOT_GEN_CMD = sym("EDN_BOOT_GEN_CMD_REG_ADDR")
EDN_RESEED_CMD = sym("EDN_RESEED_CMD_REG_ADDR")
EDN_GENERATE_CMD = sym("EDN_GENERATE_CMD_REG_ADDR")
EDN_MAX_REQS = sym("EDN_MAX_NUM_REQS_BETWEEN_RESEEDS_REG_ADDR")
EDN_ERR_CODE = sym("EDN_ERR_CODE_REG_ADDR")
EDN_RECOV_ALERT = sym("EDN_RECOV_ALERT_STS_REG_ADDR")

# --- values -----------------------------------------------------------------
# 4-bit multi-bit-bool, derived from the register export rather than copied from
# an RTL package. csrng.rdl resets CTRL.ENABLE to the disabled encoding and
# describes the enabling value as kMultiBitBool4True, so the field's reset IS
# mubi-false and mubi-true is its complement across the field width. The
# encoding is chosen for Hamming distance, which is why it is not 0 and 1.
_MUBI4_FIELD = CSRNG.fields("CTRL")["ENABLE"]
_MUBI4_FALSE = _MUBI4_FIELD["reset"]
_MUBI4_TRUE = (~_MUBI4_FALSE) & ((1 << _MUBI4_FIELD["bw"]) - 1)
CSRNG_CTRL_ENABLE = CSRNG.value(
    "CTRL",
    ENABLE=_MUBI4_TRUE,
    SW_APP_ENABLE=_MUBI4_TRUE,
    READ_INT_STATE=_MUBI4_TRUE,
    FIPS_FORCE_ENABLE=_MUBI4_FALSE,
)
EDN_CTRL_AUTO = EDN.value(
    "CTRL",
    EDN_ENABLE=_MUBI4_TRUE,
    BOOT_REQ_MODE=_MUBI4_TRUE,
    AUTO_REQ_MODE=_MUBI4_TRUE,
    CMD_FIFO_RST=_MUBI4_FALSE,
)
EDN_CTRL_BOOT = EDN.value(
    "CTRL",
    EDN_ENABLE=_MUBI4_TRUE,
    BOOT_REQ_MODE=_MUBI4_TRUE,
    AUTO_REQ_MODE=_MUBI4_FALSE,
    CMD_FIFO_RST=_MUBI4_FALSE,
)


def csrng_cmd(*, acmd: int, flag0: int = 0x9, clen: int = 0, glen: int = 0) -> int:
    """CSRNG command word: {8'h0, glen[11:0], flag0[3:0], clen[3:0], acmd[3:0]}.

    ``flag0=0x9`` is the OpenTitan ``kMultiBitBool4True`` encoding (use real
    entropy). Field layout is the CSRNG application-command word, not an RDL
    register; ``csrng_generate_cmd`` uses the same packing.
    """
    return ((glen & 0xFFF) << 12) | ((flag0 & 0xF) << 8) | ((clen & 0xF) << 4) | (acmd & 0xF)


CMD_INSTANTIATE = csrng_cmd(acmd=1)
CMD_RESEED = csrng_cmd(acmd=2)
RING_OSC_SAMPLECLK_ONLY = ENTROPY_SOURCE.value("RING_OSC_ENABLE", ENABLE=0, SAMPLE_CLK_ENABLE=0xFFF)
RING_OSC_ALL_ON = ENTROPY_SOURCE.value("RING_OSC_ENABLE", ENABLE=0xFFF, SAMPLE_CLK_ENABLE=0xFFF)

# DECORRELATOR_CTRL.SAMPLE_CLK_DIV: division = field+1
# (entropy_source.rdl: "this value plus one sample-clock cycles").
# Reset is divide-by-64 (OTP-faithful). Divide-by-8 samples faster for a quick
# alive bring-up.
DECOR_CTRL_DIV64 = ENTROPY_SOURCE.value("DECORRELATOR_CTRL", SAMPLE_CLK_DIV=63)
DECOR_CTRL_DIV8 = ENTROPY_SOURCE.value("DECORRELATOR_CTRL", SAMPLE_CLK_DIV=7)
DECOR_CTRL_DEFAULT = DECOR_CTRL_DIV64
# rep/apt/markov enabled; repetition limit 50 (reset is 25).
HEALTH_CTRL_DEFAULT = ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", ENABLE=0x7, REPETITION_LIMIT=50)

# HEALTH_TEST_WINDOW_SIZE is LEFT AT ITS 2048-SAMPLE RESET.
#
# The APT and Markov thresholds are SP 800-90B values sized for a full window,
# so a short window (0x40, for example) fails them by construction.
# entropy_source gates the whole stream on entropy_src_main_sm's boot_phase_done,
# ALERT_THRESHOLD resets to 4, and four failing windows park the FSM permanently
# in AlertHang -- after which the decorrelator keeps sampling but the SHA
# whitener never accepts a word and no seed ever reaches CSRNG.
#
# Cost at the /8 raw-sampling default: one window is 2048 samples x 8 core cycles
# ~= 16.4k cycles, well inside wait_seed_ready()'s 60k budget.

SEED_TIMEOUT = 60_000
GENBITS_TIMEOUT = 60_000


def csrng_generate_cmd(glen: int) -> int:
    """CSRNG generate command: acmd=3, flag0=use-entropy, glen from the config."""
    return csrng_cmd(acmd=3, glen=glen)


@dataclass(frozen=True)
class SepEntropyCfg:
    """Single source of truth for the ESRC->DRBG->...->KM entropy policy.

    One object derives both the DUT register writes (SepEsrcConfigSeq) and the
    golden-model configuration (golden_kwargs() for SepEntropyGolden), so the
    two cannot drift.

    Defaults are the alive-smoke policy: /8 raw sampling, the 2048-sample reset
    health window (window_size=None), SHA-256 whitening on, internal DRBG.
    """

    sample_clk_div: int = 7  # DECORRELATOR_CTRL.SAMPLE_CLK_DIV (=div-1; 7 => /8)
    # Decorrelator byte mask: the DUT reset value; not programmed.
    byte_mask: int = ENTROPY_SOURCE.fields("DECORRELATOR_MASK")["ENTROPY_BYTE_MASK"]["reset"]
    bypass: bool = False  # decorrelator feedback bypass
    sha_whitening: bool = True  # ESRC_CTRL.SHA256_WHITENING_ENABLE
    glen: int = 32  # EDN/CSRNG Generate length (128b genbits blocks)
    # EDN_CTRL_AUTO also sets BOOT_REQ. The boot Generate uses BOOT_GEN_CMD, which
    # resets to glen=4095 (0xfff003), not GENERATE_CMD. False leaves one open
    # command for the whole run; True is for a test that needs completed
    # Generates (the segmentation contract).
    program_boot_generate: bool = False
    reseed_interval: int = 8  # EDN MAX_NUM_REQS_BETWEEN_RESEEDS
    # Golden seed-accumulation skip: post-whitener words the DUT swallows before
    # the CSRNG seed packer starts. Zero for this DRBG:
    # hw/ip/drbg/doc/architecture.adoc Seed Assembly feeds one 32-bit entropy
    # word per valid cycle straight from the entropy source, with no distribution
    # FIFO, so the golden must not skip.
    ingress_skip: int = 0
    internal_drbg: bool = True  # EXT_TRNG_SRC_SEL: every stream internal vs every stream external
    health_ctrl: int = HEALTH_CTRL_DEFAULT
    # None leaves HEALTH_TEST_WINDOW_SIZE at its 2048-sample reset -- see the note
    # above; a shrunk window trips ALERT_THRESHOLD and hangs main_sm in AlertHang.
    window_size: int | None = None
    # CHK2 actual-data source: "fifo" = AXI frontdoor FIFO_RDATA (DEFAULT) -- the
    # post-whitener words drained from the FIFO in order, overflow-robust and seeing
    # the FIFO churn XOR; "backdoor" = the entropy_stream_data_o wire-tap (pre-FIFO
    # whitener output), a simpler non-draining cross-check.
    chk2_source: str = "fifo"
    # FIFO_CTRL.ENABLE. It gates only the main-FIFO write: the same words seed the
    # DRBG whatever its value. 0 closes the FIFO_RDATA read path, so CHK2 then needs
    # chk2_source="backdoor" (the FIFO input tap) because the FIFO stays empty.
    fifo_enable: int = 1

    @property
    def chk2_backdoor(self) -> bool:
        return self.chk2_source == "backdoor"

    @property
    def fifo_ctrl(self) -> int:
        """FIFO_CTRL with ENABLE from the config and every other field at reset."""
        return ENTROPY_SOURCE.value("FIFO_CTRL", ENABLE=self.fifo_enable)

    # ---- DUT register derivations (the SepEsrcConfigSeq writes) -------------
    @property
    def decor_ctrl(self) -> int:
        """DECORRELATOR_CTRL: SAMPLE_CLK_DIV in [31:12] (byte_mask is a separate
        register left at its 0xFF reset default)."""
        return ENTROPY_SOURCE.value("DECORRELATOR_CTRL", SAMPLE_CLK_DIV=self.sample_clk_div)

    @property
    def esrc_ctrl_whiten(self) -> int:
        """ESRC_CTRL built from the generated field metadata.

        Built from the generated field metadata so ``MODULE_ENABLE`` (reset 1)
        stays set: clearing it disables the whole entropy source -- the
        decorrelator keeps sampling but the SHA whitener never accepts a word
        and no seed reaches CSRNG.
        """
        return ENTROPY_SOURCE.value("CTRL", SHA256_WHITENING_ENABLE=1 if self.sha_whitening else 0)

    @property
    def ext_trng_src_sel(self) -> int:
        return 0 if self.internal_drbg else EXT_TRNG_ALL_EXTERNAL

    @property
    def edn_generate_cmd(self) -> int:
        return csrng_generate_cmd(self.glen)

    # ---- golden-model derivation (SepEntropyGolden kwargs) -----------------
    def golden_kwargs(self) -> dict:
        return dict(
            sample_clk_div=self.sample_clk_div,
            byte_mask=self.byte_mask,
            bypass=self.bypass,
            sha_whitening=self.sha_whitening,
            glen=self.glen,
            ingress_skip=self.ingress_skip,
        )


# --- low-level AXI register helpers (shared by the sequences) ----------------
async def _wr(seq, addr: int, data: int) -> None:
    item = SepAxiItem(f"esrc_wr_0x{addr:08x}")
    item.op = SepAxiOp.WRITE
    item.addr = addr
    item.length = 4
    item.wdata = data
    await seq.start_item(item)
    await seq.finish_item(item)


async def _rd(seq, addr: int) -> int:
    item = SepAxiItem(f"esrc_rd_0x{addr:08x}")
    item.op = SepAxiOp.READ
    item.addr = addr
    item.length = 4
    await seq.start_item(item)
    await seq.finish_item(item)
    return item.rdata


# --- sequences --------------------------------------------------------------
class SepEsrcConfigSeq(uvm_sequence):
    """PHASE-A: select the entropy source, configure ESRC (generators OFF), enable
    CSRNG, and stage the EDN commands. Does NOT enable the generators or EDN.

    All policy comes from one SepEntropyCfg, the SAME object that configures the
    golden model (cfg.golden_kwargs()), so DUT registers and golden never drift.
    """

    def __init__(
        self,
        name: str = "esrc_config",
        *,
        cfg: SepEntropyCfg | None = None,
        reset_trng: bool = True,
    ) -> None:
        super().__init__(name)
        self.cfg = cfg if cfg is not None else SepEntropyCfg()
        self.reset_trng = reset_trng

    async def body(self) -> None:
        cfg = self.cfg
        await _wr(self, CLOCK_GATE_CTRL, CLOCK_GATE_CTRL_RESET)  # CSR write path only
        if self.reset_trng:
            # Initial bring-up has no enabled entropy consumers. Alarm recovery
            # uses SepSwReset.begin_trng_recovery(), then invokes this sequence
            # with reset_trng=False while the consumers remain held.
            saved_sw_reset_n = await _rd(self, SW_RESET_N)
            await _wr(self, SW_RESET_N, saved_sw_reset_n & ~TRNG_SW_RST_N_MASK)
            await _wr(self, SW_RESET_N, saved_sw_reset_n)
        await _wr(self, EXT_TRNG_SRC_SEL, cfg.ext_trng_src_sel)
        await _wr(self, ESRC_RING_OSC_ENABLE, RING_OSC_SAMPLECLK_ONLY)  # generators off
        await _wr(self, ESRC_DECORRELATOR_CTRL, cfg.decor_ctrl)
        await _wr(self, ESRC_FIFO_CTRL, cfg.fifo_ctrl)
        await _wr(self, ESRC_HEALTH_TEST_CTRL, cfg.health_ctrl)
        if cfg.window_size is not None:
            await _wr(self, ESRC_HEALTH_TEST_WINDOW_SIZE, cfg.window_size)
        await _wr(self, ESRC_CTRL, cfg.esrc_ctrl_whiten)
        await _wr(self, CSRNG_CTRL, CSRNG_CTRL_ENABLE)
        await _wr(self, EDN_BOOT_INS_CMD, CMD_INSTANTIATE)
        if cfg.program_boot_generate:
            await _wr(self, EDN_BOOT_GEN_CMD, cfg.edn_generate_cmd)
        await _wr(self, EDN_RESEED_CMD, CMD_RESEED)
        await _wr(self, EDN_GENERATE_CMD, cfg.edn_generate_cmd)
        await _wr(self, EDN_MAX_REQS, cfg.reseed_interval)


class SepEsrcEnableGeneratorsSeq(uvm_sequence):
    """Enable the ESRC ring-osc generators. The raw noise itself is supplied by the
    tb (+esrc_noise_force) under Verilator; this only turns the generators on so
    the seed begins to accumulate."""

    async def body(self) -> None:
        await _wr(self, ESRC_RING_OSC_ENABLE, RING_OSC_ALL_ON)


class SepEsrcEnableEdnSeq(uvm_sequence):
    """PHASE-B: lock ESRC and enable EDN last, after startup health testing."""

    def __init__(self, name: str = "esrc_enable_edn", *, auto_mode: bool = True) -> None:
        super().__init__(name)
        self.auto_mode = auto_mode

    async def body(self) -> None:
        await _wr(self, ESRC_FIPS_LOCK, ENTROPY_SOURCE.value("FIPS_LOCK", LOCK=1))
        await _wr(self, EDN_CTRL, EDN_CTRL_AUTO if self.auto_mode else EDN_CTRL_BOOT)


class SepEsrcFifoDrainSeq(uvm_sequence):
    """Drain the entropy FIFO through FIFO_RDATA into ``self.words`` in pop order.

    FIFO_RDATA is the only FIFO pop, and the DRBG seed taps the whitener before the
    FIFO, so the drain does not disturb CHK3..CHK5. Reads FIFO_STATUS.LEVEL words,
    so it never underflows."""

    def __init__(self, name: str = "esrc_fifo_drain", *, max_words: int = 128) -> None:
        super().__init__(name)
        self.max_words = max_words
        self.words: list[int] = []

    async def body(self) -> None:
        level_meta = ENTROPY_SOURCE.fields("FIFO_STATUS")["LEVEL"]
        level = ((await _rd(self, ESRC_FIFO_STATUS)) & level_meta["bm"]) >> level_meta["bp"]
        for _ in range(min(level, self.max_words)):
            self.words.append((await _rd(self, ESRC_FIFO_RDATA)) & 0xFFFFFFFF)


class SepEsrcRegSeq(uvm_sequence):
    """Write one entropy_source register (when ``wdata`` is given), then read it back.

    ``reg`` is the RDL register name; the address comes from the generated
    top-level export. ``rdata`` holds the readback after the sequence runs.
    """

    def __init__(self, name: str = "esrc_reg", *, reg: str, wdata: int | None = None) -> None:
        super().__init__(name)
        self.addr = sym(f"ENTROPY_SOURCE_{reg}_REG_ADDR")
        self.wdata = wdata
        self.rdata = -1

    async def body(self) -> None:
        if self.wdata is not None:
            await _wr(self, self.addr, self.wdata)
        self.rdata = await _rd(self, self.addr)


class SepEsrcFifoReadPathSeq(uvm_sequence):
    """Sample the main-FIFO read path: FIFO_STATUS, then ``reads`` FIFO_RDATA pops.

    Unlike SepEsrcFifoDrainSeq, the pop count does not depend on LEVEL, so the
    pops reach an empty FIFO too. entropy_source.rdl says such a read returns
    undefined data and sets INTR_STATUS.FIFO_UNDERFLOW. The caller grades the
    status bits; the returned data is discarded. ``level`` / ``wptr`` are the
    FIFO_STATUS fields read before the pops.
    """

    def __init__(self, name: str = "esrc_fifo_read_path", *, reads: int = 2) -> None:
        super().__init__(name)
        self.reads = reads
        self.level = -1
        self.wptr = -1

    async def body(self) -> None:
        meta = ENTROPY_SOURCE.fields("FIFO_STATUS")
        status = await _rd(self, ESRC_FIFO_STATUS)
        self.level = (status & meta["LEVEL"]["bm"]) >> meta["LEVEL"]["bp"]
        self.wptr = (status & meta["WPTR"]["bm"]) >> meta["WPTR"]["bp"]
        for _ in range(self.reads):
            await _rd(self, ESRC_FIFO_RDATA)


class SepEsrcAlertReadSeq(uvm_sequence):
    """Read CSRNG/EDN err_code + recov_alert for a post-check; use check_alerts_zero()
    for the asserting wrapper."""

    def __init__(self, name: str = "esrc_alert_read_seq") -> None:
        super().__init__(name)
        self.csrng_err = 0xFFFFFFFF
        self.csrng_alert = 0xFFFFFFFF
        self.edn_err = 0xFFFFFFFF
        self.edn_alert = 0xFFFFFFFF

    async def body(self) -> None:
        self.csrng_err = await self._rd_ok(CSRNG_ERR_CODE, "CSRNG ERR_CODE")
        self.csrng_alert = await self._rd_ok(CSRNG_RECOV_ALERT, "CSRNG RECOV_ALERT")
        self.edn_err = await self._rd_ok(EDN_ERR_CODE, "EDN ERR_CODE")
        self.edn_alert = await self._rd_ok(EDN_RECOV_ALERT, "EDN RECOV_ALERT")

    async def _rd_ok(self, addr: int, what: str) -> int:
        """Read one alert register; a non-OKAY or timed-out read fails here, so a
        zero value is a register value and never an error response's data."""
        item = SepAxiItem(f"esrc_alert_rd_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        await self.start_item(item)
        await self.finish_item(item)
        assert not item.timed_out and item.resp_ok, (
            f"{what} read at 0x{addr:08x} did not complete OKAY "
            f"(timed_out={item.timed_out} resp={item.resp_code})"
        )
        return item.rdata


# The test-side poll/check helpers (wait_seed_ready / wait_genbits /
# wait_km_entropy_handshake / check_entropy_alerts_zero / assert_noise_force_active)
# live on sep_base_test, alongside the other shared bring-up observers -- these
# sequences are the protocol stimulus they orchestrate.
