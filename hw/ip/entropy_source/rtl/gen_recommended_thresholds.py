#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Single source of truth for the RECOMMENDED_THRESHOLDS lookup table.

OCAH-specific hardware assist: OpenTitan's entropy_src leaves all health-test
threshold selection to firmware (input-only REPCNT/ADAPTP threshold registers,
no min-entropy input, no derived-threshold output). We add a read-only
RECOMMENDED_THRESHOLDS register fed by MIN_ENTROPY_H so hardware offers the
SP 800-90B cutoffs directly; firmware still chooses whether to program them.

SP 800-90B recommends health-test cutoffs derived from the assessed per-sample
min-entropy H. This module computes, for every Q4.4 unsigned value of
MIN_ENTROPY_H.H (0..255, i.e. H = val / 16 bits/sample):

  * RCT_LIMIT  - Repetition Count Test cutoff, SP 800-90B 4.4.1:
        C = 1 + ceil(20 / H)                      (alpha = 2**-20)
    H is in bits/sample. Clamped to 16 bits (0xFFFF) for very small H.

  * APT_LIMIT  - Adaptive Proportion Test cutoff, SP 800-90B 4.4.2, for the
    fixed binary window W = 1024. The standard (4.4.2 body text) defines C as
    the smallest integer with
        Pr[X >= C] <= alpha,   X ~ Binomial(W, p),  p = 2**-H,
    i.e. the EXACT binomial upper critical value, which footnote 10 writes as
        C = 1 + CRITBINOM(W, 2**-H, 1 - alpha).
    We evaluate this directly from the binomial distribution (see apt_limit()),
    NOT with a normal approximation. The exact cutoff is required to reproduce
    the five W=1024 cutoffs the standard publishes in Table 2; the previous
    normal-approximation implementation reproduced only one of them and was
    wrong at 249 of the 256 Q4.4 codes (issue tenstorrent/tt-oca-harness#216).

NUMERICAL METHOD AND ORACLE INDEPENDENCE
    apt_limit() uses scipy.stats.binom, whose ppf/sf go through the regularized
    incomplete beta function - a different numerical path from the SEP DV
    checker (sep_drbg_esrc_recommended_thresholds_test_seq.p48_apt_cutoff),
    which sums the binomial PMF in log space. The two implementations are kept
    deliberately independent and are each validated against the STANDARD's own
    published Table 2, never against each other. Do not import this module into
    a checker: the DV re-derives the formula from SP 800-90B by hand so that a
    modelling error here cannot hide behind a checker that shares it.

Both cutoffs are ADVISORY (the RECOMMENDED_THRESHOLDS register is sw=r/hw=w):
firmware reads them and programs HEALTH_TEST_CTRL.REPETITION_LIMIT /
APT_PROPORTION_* before setting FIPS_LOCK. Nothing here gates the datapath.

Run as a script to (re)generate the RTL module:
    python3 gen_recommended_thresholds.py > entropy_source_rec_thresh_lut.sv

scipy is required (a broken numpy/scipy ABI on the default python3.9 on some
hosts will fail to import; use a python where `import scipy.stats` works, e.g.
/tools_soc/opensrc/python/python-3.12.10/bin/python3). The module self-checks
against SP 800-90B Table 2 before emitting and aborts if any anchor is missed.
"""

import math

from scipy.stats import binom

# Fixed binary APT window (SP 800-90B 4.4.2). Matches the certified
# HEALTH_TEST_WINDOW_SIZE floor of 1024.
APT_WINDOW = 1024

# One-sided false-positive rate (SP 800-90B 4.4, alpha = 2**-20). Table 2 is
# published for exactly this alpha.
ALPHA = 2.0**-20

# Field widths (bits) - must match the RDL RECOMMENDED_THRESHOLDS fields.
RCT_WIDTH = 16
APT_WIDTH = 16

_RCT_MAX = (1 << RCT_WIDTH) - 1
_APT_MAX = (1 << APT_WIDTH) - 1


def h_bits_per_sample(h_q44: int) -> float:
    """Convert a Q4.4 unsigned MIN_ENTROPY_H.H code to bits/sample."""
    return (h_q44 & 0xFF) / 16.0


def rct_limit(h_q44: int) -> int:
    """RCT cutoff C = 1 + ceil(20 / H), clamped to the field width.

    SP 800-90B 4.4.1: C = 1 + ceil(-log2(alpha) / H); -log2(2**-20) = 20.
    """
    h = h_bits_per_sample(h_q44)
    if h <= 0.0:
        return _RCT_MAX  # H=0: no entropy claimed -> unreachable cutoff.
    c = 1 + math.ceil(20.0 / h)
    return min(c, _RCT_MAX)


def apt_limit(h_q44: int) -> int:
    """Exact APT cutoff for W=1024 (SP 800-90B 4.4.2), no approximation.

    Returns the smallest integer C with Pr[X >= C] <= alpha for
    X ~ Binomial(W, p), p = 2**-H - the standard's definition, equivalently
    C = 1 + CRITBINOM(W, p, 1 - alpha) (4.4.2 footnote 10). Clamped to W.
    """
    h = h_bits_per_sample(h_q44)
    if h <= 0.0:
        # p = 1: every sample is identical, no cutoff below W is significant.
        return min(APT_WINDOW, _APT_MAX)

    p = 2.0 ** (-h)

    # Footnote-10 CRITBINOM seed via the inverse CDF (incomplete beta).
    c = 1 + int(binom.ppf(1.0 - ALPHA, APT_WINDOW, p))

    # Enforce the definition directly, correcting any boundary rounding from
    # ppf at the ~2**-20 tail. Pr[X >= k] = sf(k-1) (survival function, an
    # independent evaluation path). Smallest c with sf(c-1) <= alpha:
    while binom.sf(c - 1, APT_WINDOW, p) > ALPHA:
        c += 1  # c violates the bound -> loosen
    while c > 1 and binom.sf(c - 2, APT_WINDOW, p) <= ALPHA:
        c -= 1  # c-1 also satisfies -> tighten

    return min(c, _APT_MAX, APT_WINDOW)


# SP 800-90B Table 2 (the standard's own published cutoffs). The generator must
# reproduce every one of these or it is not implementing 4.4.2. Binary column is
# W=1024; the non-binary column (W=512) is checked too as a method-validity
# cross-check even though the emitted LUT only uses W=1024.
_TABLE2_BINARY_W1024 = {0.2: 941, 0.4: 840, 0.6: 748, 0.8: 664, 1.0: 589}
_TABLE2_NONBIN_W512 = {0.5: 410, 1.0: 311, 2.0: 177, 4.0: 62, 8.0: 13}


def _apt_cutoff(h_bits: float, window: int) -> int:
    """Exact APT cutoff at an arbitrary (non-Q4.4) H, for the Table 2 check."""
    p = 2.0 ** (-h_bits)
    c = 1 + int(binom.ppf(1.0 - ALPHA, window, p))
    while binom.sf(c - 1, window, p) > ALPHA:
        c += 1
    while c > 1 and binom.sf(c - 2, window, p) <= ALPHA:
        c -= 1
    return min(c, window)


def _self_check() -> None:
    """Reproduce SP 800-90B Table 2 exactly, or abort. Anchors the generator to
    the standard - not to the RTL LUT or the DV checker."""
    for h, expected in _TABLE2_BINARY_W1024.items():
        got = _apt_cutoff(h, 1024)
        if got != expected:
            raise SystemExit(
                f"SELF-CHECK FAILED: SP 800-90B Table 2 (binary, W=1024) "
                f"H={h} expects C={expected}, got {got}. Refusing to emit."
            )
    for h, expected in _TABLE2_NONBIN_W512.items():
        got = _apt_cutoff(h, 512)
        if got != expected:
            raise SystemExit(
                f"SELF-CHECK FAILED: SP 800-90B Table 2 (non-binary, W=512) "
                f"H={h} expects C={expected}, got {got}. Refusing to emit."
            )


def _emit_module() -> str:
    lines = []
    lines.append("// SPDX-License-Identifier: Apache-2.0")
    lines.append("// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.")
    lines.append("")
    lines.append("// AUTO-GENERATED by gen_recommended_thresholds.py -- DO NOT EDIT.")
    lines.append("// SP 800-90B RECOMMENDED_THRESHOLDS lookup. Regenerate with:")
    lines.append("//   python3 gen_recommended_thresholds.py > entropy_source_rec_thresh_lut.sv")
    lines.append("//")
    lines.append("// Pure combinational LUT: maps MIN_ENTROPY_H.H[7:0] (Q4.4) to the")
    lines.append("// recommended {APT_LIMIT[15:0], RCT_LIMIT[15:0]} cutoffs. Instantiated")
    lines.append("// by entropy_source.sv. RCT_LIMIT is the SP 800-90B 4.4.1 closed form")
    lines.append("// C = 1 + ceil(20/H); APT_LIMIT is the SP 800-90B 4.4.2 EXACT binomial")
    lines.append("// cutoff 1 + CRITBINOM(W=1024, 2^-H, 1-2^-20). The SEP DV checker")
    lines.append("// re-derives both formulas independently from the standard (oracle")
    lines.append("// independence) -- it does NOT read this table.")
    lines.append("")
    lines.append("module entropy_source_rec_thresh_lut (")
    lines.append("    input  logic [ 7:0] min_entropy_h_i,")
    lines.append("    output logic [15:0] rct_limit_o,")
    lines.append("    output logic [15:0] apt_limit_o")
    lines.append(");")
    lines.append("")
    lines.append("    logic [15:0] rct_limit, apt_limit;")
    lines.append("")
    lines.append("    always_comb begin")
    lines.append("        unique case (min_entropy_h_i)")
    for code in range(256):
        rct = rct_limit(code)
        apt = apt_limit(code)
        lines.append(f"            8'h{code:02X}: begin")
        lines.append(f"                rct_limit = 16'd{rct};")
        lines.append(f"                apt_limit = 16'd{apt};")
        lines.append("            end")
    lines.append("            default: begin")
    lines.append("                rct_limit = 16'd0;")
    lines.append("                apt_limit = 16'd0;")
    lines.append("            end")
    lines.append("        endcase")
    lines.append("    end")
    lines.append("")
    lines.append("    assign rct_limit_o = rct_limit;")
    lines.append("    assign apt_limit_o = apt_limit;")
    lines.append("")
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    _self_check()
    sys.stdout.write(_emit_module())
