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
# CLOCK_GATE_CTRL is a placeholder in this repository's sep_cpu_ctrl.rdl with ONE
# implemented bit (pka_cg_enable[0:0], itself marked "not yet implemented") -- there
# is no entropy_fifo gate bit, so the ESRC/CSRNG/EDN CSRs are unconditionally
# clocked. The write below is CSR write-path coverage only; it releases nothing.
#
# It writes the register's RESET value, NOT `mask32()`. `mask32()` is the union of
# implemented field bits, i.e. "set every field to all-ones" -- inert against a
# placeholder (0x1) but tracking the RDL, so real clock-gate enables added there
# would be silently asserted by this bring-up write. The reset value stays inert
# by construction no matter how the register grows.
CLOCK_GATE_CTRL = SEP_CPU_CTRL.addr("CLOCK_GATE_CTRL")
CLOCK_GATE_CTRL_RESET = SEP_CPU_CTRL.reset("CLOCK_GATE_CTRL")
EXT_TRNG_SRC_SEL = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")
SW_RESET_N = SEP_RESET_CTRL.addr("SW_RESET_N")
TRNG_SW_RST_N_MASK = SEP_RESET_CTRL.field_mask("SW_RESET_N", "trng_sw_rst_n")
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
# Do not "speed up" the bring-up by shrinking it. The APT and Markov thresholds are
# SP 800-90B values sized for a full window, so a short window (0x40, for example)
# fails them by construction. entropy_source gates the whole stream on
# entropy_src_main_sm's boot_phase_done, ALERT_THRESHOLD resets to 4, and four
# failing windows park the FSM permanently in AlertHang -- after which the
# decorrelator keeps sampling but the SHA whitener never accepts a word and no seed
# ever reaches CSRNG. That is a shrink which breaks the mechanism it is meant to
# exercise, not a timing-only knob.
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

    ONE object derives BOTH the DUT register writes (via SepEsrcConfigSeq) AND the
    golden-model configuration (via golden_kwargs() for SepEntropyGolden) -- never
    two hand-kept copies, which can disagree (a sequence default of
    DECORRELATOR_CTRL /64 against a golden default of sample_clk_div=7 => /8)
    unless every test overrides both consistently.

    Defaults = the fast alive-smoke policy (/8 raw sampling, small health window,
    SHA-256 whitening on, internal DRBG). The conditioning math is identical to
    FIPS defaults; /8 + small window only trades sample count for wall-clock.
    """

    sample_clk_div: int = 7  # DECORRELATOR_CTRL.SAMPLE_CLK_DIV (=div-1; 7 => /8)
    byte_mask: int = 0xFF  # decorrelator byte mask (DUT reset default; not programmed)
    bypass: bool = False  # decorrelator feedback bypass
    sha_whitening: bool = True  # ESRC_CTRL.SHA256_WHITENING_ENABLE
    glen: int = 32  # EDN/CSRNG Generate length (128b genbits blocks)
    # EDN_CTRL_AUTO also sets BOOT_REQ. The boot Generate uses BOOT_GEN_CMD, which
    # resets to glen=4095 (0xfff003), not GENERATE_CMD. False leaves one open
    # command for the whole run; True is for a test that needs completed
    # Generates (the segmentation contract).
    program_boot_generate: bool = False
    reseed_interval: int = 8  # EDN MAX_NUM_REQS_BETWEEN_RESEEDS
    # Golden seed-accumulation skip: how many post-whitener words the DUT swallows
    # before the CSRNG seed packer starts. ZERO for this DRBG --
    # hw/ip/drbg/doc/architecture.adoc Seed Assembly: one 32-bit entropy word per
    # valid cycle directly from the entropy source, no upstream routing or
    # distribution FIFO, so nothing is absorbed and the golden must not skip.
    # A skip of 12 would model a distribution FIFO this integration does not
    # instantiate and shift the golden by 12 words: CHK3_seed (and so CHK4/CHK5)
    # mismatch while CHK1/CHK2 match exactly.
    ingress_skip: int = 0
    internal_drbg: bool = True  # EXT_TRNG_SRC_SEL = 0 (internal) vs 0x7 (ext_trng)
    health_ctrl: int = HEALTH_CTRL_DEFAULT
    # None leaves HEALTH_TEST_WINDOW_SIZE at its 2048-sample reset -- see the note
    # above; a shrunk window trips ALERT_THRESHOLD and hangs main_sm in AlertHang.
    window_size: int | None = None
    # CHK2 actual-data source: "fifo" = AXI frontdoor FIFO_RDATA (DEFAULT) -- the
    # post-whitener words drained from the FIFO in order, overflow-robust and seeing
    # the FIFO churn XOR; "backdoor" = the entropy_stream_data_o wire-tap (pre-FIFO
    # whitener output), a simpler non-draining cross-check.
    chk2_source: str = "fifo"

    @property
    def chk2_backdoor(self) -> bool:
        return self.chk2_source == "backdoor"

    # ---- DUT register derivations (the SepEsrcConfigSeq writes) -------------
    @property
    def decor_ctrl(self) -> int:
        """DECORRELATOR_CTRL: SAMPLE_CLK_DIV in [31:12] (byte_mask is a separate
        register left at its 0xFF reset default)."""
        return ENTROPY_SOURCE.value("DECORRELATOR_CTRL", SAMPLE_CLK_DIV=self.sample_clk_div)

    @property
    def esrc_ctrl_whiten(self) -> int:
        """ESRC_CTRL built from the generated field metadata.

        Assembling this from named fields (rather than a literal) is what keeps
        ``MODULE_ENABLE`` — which RESETS TO 1 — set. A hand-built
        "just the whitening bit" value (0x1000_0000) clears it, which disables the
        whole entropy source: the decorrelator keeps sampling but the SHA whitener
        never accepts a word, so no seed ever reaches CSRNG.
        """
        return ENTROPY_SOURCE.value("CTRL", SHA256_WHITENING_ENABLE=1 if self.sha_whitening else 0)

    @property
    def ext_trng_src_sel(self) -> int:
        return 0x0 if self.internal_drbg else 0x7

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
        await _wr(self, ESRC_FIFO_CTRL, 0x1)
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
        await _wr(self, ESRC_FIPS_LOCK, 0x1)
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
        self.csrng_err = await _rd(self, CSRNG_ERR_CODE)
        self.csrng_alert = await _rd(self, CSRNG_RECOV_ALERT)
        self.edn_err = await _rd(self, EDN_ERR_CODE)
        self.edn_alert = await _rd(self, EDN_RECOV_ALERT)


# The test-side poll/check helpers (wait_seed_ready / wait_genbits /
# wait_km_entropy_handshake / check_entropy_alerts_zero / assert_noise_force_active)
# live on sep_base_test, alongside the other shared bring-up observers -- these
# sequences are the protocol stimulus they orchestrate.
