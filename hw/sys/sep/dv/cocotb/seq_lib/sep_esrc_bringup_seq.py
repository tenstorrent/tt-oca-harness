# SPDX-License-Identifier: Apache-2.0
"""ESRC -> DRBG -> CSRNG -> EDN entropy bring-up sequences + reusable helpers.

Replicates the OCAH real-entropy bring-up order (sep_drbg_uvm_base_test_seq.sv):
PHASE-A configures ESRC with the generators off, resets/pulses ESRC, enables
CSRNG, and stages the EDN commands but does NOT enable EDN; the caller then
enables the generators and waits for a seed; PHASE-B enables EDN last. CSRNG/EDN
registers sit behind a 64-bit lane adapter -- a 4-byte write at the register's
byte address lands on the correct lane automatically.

Reusable across every entropy-consumer test (KM/AES/KMAC/OTBN). The canonical
flow is:

    await self.start_seq(SepEsrcConfigSeq(...))         # PHASE-A (parameterized)
    await self.start_seq(SepEsrcEnableGeneratorsSeq())  # start ring-osc generators
    assert await wait_seed_ready(self)
    await self.start_seq(SepEsrcEnableEdnSeq())          # PHASE-B
    assert await wait_genbits(self)
    assert await wait_km_handshake(self)
    await check_alerts_zero(self)
"""

from __future__ import annotations

from dataclasses import dataclass

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from sep_reg_meta import ENTROPY_SOURCE, SEP_CPU_CTRL

# --- register map -----------------------------------------------------------
# sep_cpu_ctrl addresses come from the generated SystemRDL export (AGENTS.md §7).
# CLOCK_GATE_CTRL is a placeholder in this repository's sep_cpu_ctrl.rdl with ONE
# implemented bit (pka_cg_enable[0:0]) -- there is no entropy_fifo gate bit, so the
# ESRC/CSRNG/EDN CSRs are unconditionally clocked. The write below stays as CSR
# write-path coverage; it releases nothing.
CLOCK_GATE_CTRL = SEP_CPU_CTRL.addr("CLOCK_GATE_CTRL")
CLOCK_GATE_ENTROPY = SEP_CPU_CTRL.mask32("CLOCK_GATE_CTRL")
EXT_TRNG_SRC_SEL = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")
# entropy_source (flat 32-bit map @ 0x1091_6000)
ESRC_CTRL = 0x1091_6004
ESRC_FIFO_CTRL = 0x1091_6020
ESRC_FIFO_STATUS = 0x1091_6024   # [6:0] LEVEL = valid 32-bit words in the FIFO
ESRC_FIFO_RDATA = 0x1091_6028    # read pops one word, decrements LEVEL (frontdoor drain)
ESRC_HEALTH_TEST_CTRL = 0x1091_6030
ESRC_HEALTH_TEST_WINDOW_SIZE = 0x1091_6034
ESRC_HEALTH_TEST_STATUS = 0x1091_6040   # per-test pass/fail, read on a stall
# entropy_src_main_sm state: the OpenTitan boot/startup gate. entropy_source.sv
# gates the whole stream on boot_phase_done, so this register says whether the
# boot phase completed. {STATE[8:0], IDLE[9], ALERT[10], ERR[11]}
ESRC_MAIN_SM_STATUS = 0x1091_60B4
ESRC_RING_OSC_ENABLE = 0x1091_6090
ESRC_DECORRELATOR_CTRL = 0x1091_60A0
# CSRNG @ 0x1091_5000 / EDN @ 0x1091_5800 (lane-adapter)
CSRNG_CTRL = 0x1091_5014
CSRNG_ERR_CODE = 0x1091_5054
CSRNG_RECOV_ALERT = 0x1091_5050
EDN_CTRL = 0x1091_5814
EDN_BOOT_INS_CMD = 0x1091_5818
EDN_RESEED_CMD = 0x1091_582C
EDN_GENERATE_CMD = 0x1091_5830
EDN_MAX_REQS = 0x1091_5834
EDN_ERR_CODE = 0x1091_583C
EDN_RECOV_ALERT = 0x1091_5838

# --- values -----------------------------------------------------------------
CSRNG_CTRL_ENABLE = 0x0000_9666  # {FIPS_FORCE=F, READ_INT_STATE=T, SW_APP_ENABLE=T, ENABLE=T}
EDN_CTRL_AUTO = 0x0000_9666      # {CMD_FIFO_RST=F, AUTO_REQ=T, BOOT_REQ=T, EDN_ENABLE=T}
EDN_CTRL_BOOT = 0x0000_9966      # {CMD_FIFO_RST=F, AUTO_REQ=F, BOOT_REQ=T, EDN_ENABLE=T}
CMD_INSTANTIATE = 0x0000_0901    # acmd=1, flag0=9 (use real entropy)
CMD_RESEED = 0x0000_0902         # acmd=2
RING_OSC_SAMPLECLK_ONLY = 0x00FF_F000  # SAMPLE_CLK_ENABLE on, generators off
RING_OSC_ALL_ON = 0x00FF_FFFF          # generators + sample-clk on

# DECORRELATOR_CTRL: SAMPLE_CLK_DIV is bits [31:12], division = field+1 (RTL
# entropy_decorrelator.sv). 63<<12 -> divide-by-64 (the OTP-faithful default);
# 7<<12 -> divide-by-8, which samples ~8x faster for a quick alive bring-up.
DECOR_CTRL_DIV64 = 0x0003_F000
DECOR_CTRL_DIV8 = 0x0000_7000
DECOR_CTRL_DEFAULT = DECOR_CTRL_DIV64
# rep_limit=50, rep/apt/markov enabled
HEALTH_CTRL_DEFAULT = 0x0000_3207

# HEALTH_TEST_WINDOW_SIZE is deliberately LEFT AT ITS 2048-SAMPLE RESET.
#
# Do not "speed up" the bring-up by shrinking it. The APT and Markov thresholds are
# SP 800-90B values sized for a full window, so a short window (a 0x40 window was
# tried) fails them by construction. entropy_source gates the whole stream on
# entropy_src_main_sm's boot_phase_done, ALERT_THRESHOLD resets to 4, and four
# failing windows park the FSM permanently in AlertHang -- after which the
# decorrelator keeps sampling but the SHA whitener never accepts a word and no seed
# ever reaches CSRNG. That is a shrink which breaks the mechanism it is meant to
# exercise (AGENTS.md §8), not a timing-only knob.
#
# Cost at the /8 raw-sampling default: one window is 2048 samples x 8 core cycles
# ~= 16.4k cycles, well inside wait_seed_ready()'s 60k budget.

SEED_TIMEOUT = 60_000
GENBITS_TIMEOUT = 60_000


def csrng_generate_cmd(glen: int) -> int:
    """csrng cmd word {8'h0, glen[11:0], flag0=9(use-entropy), clen=0, acmd=3}."""
    return ((glen & 0xFFF) << 12) | (0x9 << 8) | 0x3


@dataclass(frozen=True)
class SepEntropyCfg:
    """Single source of truth for the ESRC->DRBG->...->KM entropy policy.

    ONE object derives BOTH the DUT register writes (via SepEsrcConfigSeq) AND the
    golden-model configuration (via golden_kwargs() for SepEntropyGolden) -- never
    two hand-kept copies. This closes the latent trap where the sequence default
    (DECORRELATOR_CTRL /64) and the golden default (sample_clk_div=7 => /8)
    disagreed unless a test happened to override both consistently.

    Defaults = the fast alive-smoke policy (/8 raw sampling, small health window,
    SHA-256 whitening on, internal DRBG). The conditioning math is identical to
    FIPS defaults; /8 + small window only trades sample count for wall-clock.
    """

    sample_clk_div: int = 7            # DECORRELATOR_CTRL.SAMPLE_CLK_DIV (=div-1; 7 => /8)
    byte_mask: int = 0xFF              # decorrelator byte mask (DUT reset default; not programmed)
    bypass: bool = False               # decorrelator feedback bypass
    sha_whitening: bool = True         # ESRC_CTRL.SHA256_WHITENING_ENABLE
    glen: int = 32                     # EDN/CSRNG Generate length (128b genbits blocks)
    reseed_interval: int = 8           # EDN MAX_NUM_REQS_BETWEEN_RESEEDS
    # Golden seed-accumulation skip: how many post-whitener words the DUT swallows
    # before the CSRNG seed packer starts. ZERO for this DRBG -- drbg.sv wires the
    # packer straight to the stream (`.csrng_word_valid_i (entropy_stream_vld_i)`,
    # drbg.sv:141) with no distribution FIFO in between, so nothing is absorbed and
    # the golden must not skip. The old default of 12 modelled a distribution FIFO
    # that this repository's drbg.sv does not instantiate, which shifted the golden
    # by 12 words and mismatched CHK3_seed (and hence CHK4/CHK5) while CHK1/CHK2
    # still matched exactly.
    ingress_skip: int = 0
    internal_drbg: bool = True         # EXT_TRNG_SRC_SEL = 0 (internal) vs 0x3 (ext_trng)
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
        return (self.sample_clk_div & 0xFFFFF) << 12

    @property
    def esrc_ctrl_whiten(self) -> int:
        """ESRC_CTRL with RESET deasserted, built from the generated field metadata.

        Assembling this from named fields (rather than a literal) is what keeps
        ``MODULE_ENABLE`` — which RESETS TO 1 — set. A hand-built
        "just the whitening bit" value (0x1000_0000) silently cleared it, which
        disables the whole entropy source: the decorrelator keeps sampling but the
        SHA whitener never accepts a word, so no seed ever reaches CSRNG.
        """
        return ENTROPY_SOURCE.value(
            "CTRL", RESET=0, SHA256_WHITENING_ENABLE=1 if self.sha_whitening else 0
        )

    @property
    def esrc_ctrl_reset_pulse(self) -> int:
        """Same as :attr:`esrc_ctrl_whiten` but with CTRL.RESET asserted."""
        return ENTROPY_SOURCE.value(
            "CTRL", RESET=1, SHA256_WHITENING_ENABLE=1 if self.sha_whitening else 0
        )

    @property
    def ext_trng_src_sel(self) -> int:
        return 0x0 if self.internal_drbg else 0x3

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
    ) -> None:
        super().__init__(name)
        self.cfg = cfg if cfg is not None else SepEntropyCfg()

    async def body(self) -> None:
        cfg = self.cfg
        await _wr(self, CLOCK_GATE_CTRL, CLOCK_GATE_ENTROPY)  # ungate entropy_fifo clock
        await _wr(self, EXT_TRNG_SRC_SEL, cfg.ext_trng_src_sel)
        await _wr(self, ESRC_RING_OSC_ENABLE, RING_OSC_SAMPLECLK_ONLY)  # generators off
        await _wr(self, ESRC_DECORRELATOR_CTRL, cfg.decor_ctrl)
        await _wr(self, ESRC_FIFO_CTRL, 0x1)
        await _wr(self, ESRC_HEALTH_TEST_CTRL, cfg.health_ctrl)
        if cfg.window_size is not None:
            await _wr(self, ESRC_HEALTH_TEST_WINDOW_SIZE, cfg.window_size)
        await _wr(self, ESRC_CTRL, cfg.esrc_ctrl_reset_pulse)   # RESET=1 (soft-reset ESRC)
        await _wr(self, ESRC_CTRL, cfg.esrc_ctrl_whiten)        # RESET=0
        await _wr(self, CSRNG_CTRL, CSRNG_CTRL_ENABLE)
        await _wr(self, EDN_BOOT_INS_CMD, CMD_INSTANTIATE)
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
    """PHASE-B: enable EDN last (after entropy is flowing). EDN then auto-issues
    Instantiate+Generate and streams genbits to the selected sink (KM by default)."""

    def __init__(self, name: str = "esrc_enable_edn", *, auto_mode: bool = True) -> None:
        super().__init__(name)
        self.auto_mode = auto_mode

    async def body(self) -> None:
        await _wr(self, EDN_CTRL, EDN_CTRL_AUTO if self.auto_mode else EDN_CTRL_BOOT)


class SepEsrcFifoDrainSeq(uvm_sequence):
    """Drain the entropy FIFO via the AXI frontdoor (FIFO_RDATA), collecting every
    word into ``self.words`` in pop (= push) order for the CHK2 compare.

    This is the OCAH-faithful CHK2 observation point: FIFO_RDATA is the ONLY thing
    that pops the FIFO, and the DRBG seed taps the pre-FIFO whitener output, so the
    frontdoor read is non-invasive to the CHK3..CHK5 chain AND reflects any FIFO
    churn the backdoor wire-tap would miss. Reads exactly FIFO_STATUS.LEVEL words so
    it never underflows."""

    def __init__(self, name: str = "esrc_fifo_drain", *, max_words: int = 128) -> None:
        super().__init__(name)
        self.max_words = max_words
        self.words: list[int] = []

    async def body(self) -> None:
        level = (await _rd(self, ESRC_FIFO_STATUS)) & 0x7F
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
