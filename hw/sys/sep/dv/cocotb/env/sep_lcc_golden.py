# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle-Controller (LCC) golden model for the SEP OSS flow.

Pure-Python reference for what the SEP `sep_lifecycle_ctrl` block computes on its
``feat_ctrl`` output as a function of the eFuse-sensed lifecycle state and the
DEMOTE / security-disable inputs. SECURE_TM does not qualify feature control.

This model is derived from Table 50 ("Per-LC-state feature control profile") of
``hw/sys/sep/doc/lifecycle_controller.adoc``, not from
``hw/sys/sep/rtl/sep_lifecycle_ctrl.sv``: an expectation that shares a source
with the thing it measures cannot disagree with it. If the RTL and the chapter
disagree, follow the chapter and let the test fail; do not transcribe the RTL.

Also holds the lifecycle-state encoding / transition model: legal encoding, W1S
monotonicity, the two RMA token gates, the observed-transition predicate, and the
per-write next-state function. These express the lifecycle walk rules in a
value-driven form. Feed them DUT-observed codes, never the codes the test
programmed.
"""

from __future__ import annotations

from sep_reg_meta import SEP_LIFECYCLE_CTRL, sym

# -- lifecycle-state raw encodings (lifecycle_controller.adoc) -----------------
LC_TEST_DEV = 0x0
LC_PROD = 0x1
LC_RMA_SIP_0 = 0x2
LC_RMA_SIP_1 = 0x3
LC_RMA_CHIP_0 = 0x6
LC_RMA_CHIP_1 = 0x7
LC_PROD_END = 0x8
LEGAL_LC_RAW = (
    LC_TEST_DEV,
    LC_PROD,
    LC_RMA_SIP_0,
    LC_RMA_SIP_1,
    LC_RMA_CHIP_0,
    LC_RMA_CHIP_1,
    LC_PROD_END,
)
_LC_NAME = {
    LC_TEST_DEV: "TEST_DEV",
    LC_PROD: "PROD",
    LC_RMA_SIP_0: "RMA_SIP_0",
    LC_RMA_SIP_1: "RMA_SIP_1",
    LC_RMA_CHIP_0: "RMA_CHIP_0",
    LC_RMA_CHIP_1: "RMA_CHIP_1",
    LC_PROD_END: "PROD_END",
}

# -- LCC register map (single source of truth; imported by the LCC sequences) -
SEP_LCC_BASE = sym("SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR")
LCC_FEAT_CTRL = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")
LCC_DEMOTE_1 = SEP_LIFECYCLE_CTRL.addr("DEMOTE_1")
LCC_DEMOTE_2 = SEP_LIFECYCLE_CTRL.addr("DEMOTE_2")

# -- feat_ctrl bit layout (lifecycle_controller.adoc Disable Vector Format) --
# Feature control is per GROUP, and demotion acts on one debug group at a time --
# which is why DBG_1 and DBG_2 need separate masks rather than one Debug mask.
#   [23:0]  DBG_1    bit 0 sep_debug, bit 1 chiplet_dbg, bit 2 sep_fuse_dbg,
#                    bit 3 smc_fuse_dbg, [23:4] reserved
#   [47:24] DBG_2    bit 24 sip_debug, [47:25] reserved
#   [63:48] Function func_reserved[15:0]
# There is no DFT / test group. SECURE_TM does not qualify feature control.
M64 = (1 << 64) - 1
DBG1_MASK = (1 << 24) - 1  # bits [23:0]
DBG2_MASK = ((1 << 24) - 1) << 24  # bits [47:24]
DEBUG_MASK = DBG1_MASK | DBG2_MASK  # bits [47:0]
FUNC_MASK = ((1 << 16) - 1) << 48  # bits [63:48]
SIP_DBG_BIT = 24
SEP_FUSE_DBG_BIT = 2
SMC_FUSE_DBG_BIT = 3


def lc_state_name(raw: int) -> str:
    return _LC_NAME.get(raw & 0xF, f"INVALID(0x{raw & 0xF:x})")


def is_legal_lc(raw: int) -> bool:
    """Valid frontdoor encoding (the 7 reachable codes); 0x4,0x5,0x9-0xF illegal."""
    return (raw & 0xF) in LEGAL_LC_RAW


def is_w1s_superset(prev: int, cur: int) -> bool:
    """W1S: bits only ever go 0->1, so cur must contain every set bit of prev."""
    return (prev & cur) == prev


def is_invalid_lc(raw: int) -> bool:
    """INVALID: any encoding outside the named set ("All other values" in the
    chapter's LC-state table). The chapter calls INVALID the end-of-life state --
    "the chip is permanently inoperable" -- so it is the one terminal condition.
    """
    return not is_legal_lc(raw)


def lc_state_next(
    cur: int,
    wdata: int,
    *,
    sip_match: bool,
    chiplet_match: bool,
) -> int:
    """Spec next-state for ONE write-1-to-set write of the LC_STATE shadow word.

    The chapter gives three rules and no per-state destination table:

      * The shadow word is write-1-to-set, so a bit only ever goes 0 -> 1
        ("only transition from 0 to 1, never from 1 to 0").
      * RMA_SIP is ``4'b001X`` and RMA_CHIPLET is ``4'b011X``: bit 0 is a
        DON'T CARE inside either state, so setting it is a move within one
        state, not a transition out of it. Bit 3 (PROD_END) is likewise ungated.
      * The RMA ordering is hardware-enforced: bit 1 needs the RMA_SIP token,
        and bit 2 needs the RMA_CHIPLET token AND RMA_SIP already established
        ("the device must first enter RMA_SIP via the RMA_SIP_TOKEN, then
        transition to RMA_CHIPLET via the RMA_CHIPLET_TOKEN").

    Everything else follows from those three, including the destinations the
    chapter never names: from PROD_END every reachable set lands outside the
    named set, which is exactly the chapter's "the only permitted transition is
    to INVALID". A destination table would be a second, weaker statement of the
    same rule.

    ``sip_match`` / ``chiplet_match`` are the token-comparator verdicts
    (``TOKEN_MATCH_CODE`` presented, not merely a token written).
    """
    cur &= 0xF
    wdata &= 0xF
    if is_invalid_lc(cur):
        return cur  # end-of-life: nothing leaves INVALID
    nxt = cur | (wdata & 0b1001)  # bit 0 (state-internal) and bit 3: ungated W1S
    if sip_match:
        nxt |= wdata & 0b0010
    if chiplet_match and (cur & 0b0010):
        nxt |= wdata & 0b0100
    return nxt


def is_valid_lc_transition(prev: int, cur: int) -> bool:
    """Is an OBSERVED prev -> cur step one the lifecycle permits?

    The value-driven form of the same three chapter rules, for a checker that
    sees two sensed codes and not the write that caused the step:

      * W1S-monotonic: no bit may drop.
      * RMA_CHIPLET (bit 2) may only appear once RMA_SIP (bit 1) is established.
      * Nothing leaves INVALID.

    A same-state step is always allowed (a resense of an unchanged image, or a
    bit-0 set inside RMA_SIP / RMA_CHIPLET). This does not freeze
    PROD_END or RMA_CHIPLET: the chapter permits PROD_END -> INVALID, and bit 0
    is a don't-care within an RMA state.
    """
    prev &= 0xF
    cur &= 0xF
    if is_invalid_lc(prev):
        return cur == prev
    if cur == prev:
        return True
    if not is_w1s_superset(prev, cur):
        return False
    if (cur & 0b0100) and not (prev & 0b0100) and not (prev & 0b0010):
        return False
    return True


def feat_ctrl_expected(
    lc_raw: int,
    sip_dis: int,
    sys_dis: int,
    *,
    demote_1: int = 0,
    demote_2: int = 0,
    secure_tm: int = 0,
    sec_dis: int = 0,
    sigint_err: int = 0,
) -> int:
    """Expected 64-bit FEAT_CTRL for the given lifecycle state and inputs.

    Derived from the per-LC-state feature-control profile in the lifecycle
    chapter. ``sip_dis``/``sys_dis`` are the 64-bit sensed shadow values;
    ``demote_*``/``sec_dis`` default to the no-CPU image case (DEMOTE regs at
    reset). ``secure_tm`` is accepted and ignored: SECURE_TM is not an
    authorization on feature control.

    DEMOTE_1 and DEMOTE_2 are independent and act only on their own debug group:
    DEMOTE_1 on DBG_1 [23:0], DEMOTE_2 on DBG_2 [47:24]. Neither touches Function.
    In TEST_DEV a demotion forces its group fully open, overriding the DIS
    vectors; in PROD it only relaxes its group to honour them ("one level down from
    disabled"), so a DIS bit set in both vectors keeps that feature off even when
    demoted.
    """
    sip_dis &= M64
    sys_dis &= M64

    if sigint_err:
        feat = 0
    else:
        both = (~(sip_dis | sys_dis)) & M64  # both vectors bind
        sip_only = (~sip_dis) & M64  # SIP_DIS alone binds the SiP owner
        if lc_raw == LC_TEST_DEV:  # 4'b0000
            feat = both
            if demote_1:  # DBG_1 forced open
                feat = (feat & ~DBG1_MASK) | DBG1_MASK
            if demote_2:  # DBG_2 forced open
                feat = (feat & ~DBG2_MASK) | DBG2_MASK
        elif lc_raw == LC_PROD:  # 4'b0001
            feat = both & FUNC_MASK  # debug groups off unless demoted
            if demote_1:  # DBG_1 relaxed to the DIS vectors
                feat |= both & DBG1_MASK
            if demote_2:  # DBG_2 relaxed to the DIS vectors
                feat |= both & DBG2_MASK
        elif lc_raw == LC_PROD_END:  # 4'b1000, demotion has no effect
            feat = both & FUNC_MASK
        elif lc_raw in (LC_RMA_SIP_0, LC_RMA_SIP_1):  # 4'b001?, demotion has no effect
            feat = sip_only
        elif lc_raw in (LC_RMA_CHIP_0, LC_RMA_CHIP_1):  # 4'b011?, all features enabled
            feat = M64
        else:  # INVALID/others -- chip not live
            feat = 0

    if sec_dis:
        feat = M64
    _ = secure_tm  # accepted; SECURE_TM does not qualify feat_ctrl
    return feat & M64


# -- import-time KAT self-test -------------------------------------------------
# Hand-computed (input -> expected) vectors pinning each decode branch, so an error
# in the formula above (wrong mask, dropped branch, inverted override) fails loudly
# here at import rather than as a silent feat_ctrl mismatch deep in a sim.
# Independent of DUT output AND of the RTL: every expected value is worked out by
# hand from the lifecycle chapter. SECURE_TM does not change FEAT_CTRL, so the
# secure_tm=0 and secure_tm=1 rows for the same inputs must match.
_FUNC_ALL = 0xFFFF_0000_0000_0000  # FUNC_MASK only
_DBG1_ALL = 0x0000_0000_00FF_FFFF
_DBG2_ALL = 0x0000_FFFF_FF00_0000
_DEBUG_ALL = _DBG1_ALL | _DBG2_ALL

_LCC_GOLDEN_VECTORS: tuple[tuple[int, int, int, dict[str, int], int], ...] = (
    # (lc_raw, sip_dis, sys_dis, kwargs, expected)
    (LC_TEST_DEV, 0, 0, {}, M64),  # all-enable
    (LC_TEST_DEV, 0, 0, {"secure_tm": 1}, M64),  # SECURE_TM does not qualify feat_ctrl
    (LC_PROD, 0, 0, {}, _FUNC_ALL),  # PROD: func only, debug off
    (LC_PROD, 0, 0, {"demote_1": 1}, _FUNC_ALL | _DBG1_ALL),  # PROD+DEMOTE_1: DBG_1 only
    (LC_PROD, 0, 0, {"demote_2": 1}, _FUNC_ALL | _DBG2_ALL),  # PROD+DEMOTE_2: DBG_2 only
    # DEMOTE in PROD only RELAXES its group to the DIS vectors -- it does not force
    # them open. sep_debug (bit 0) is disabled here, so DEMOTE_1 must leave it off.
    (LC_PROD, 0x1, 0, {"demote_1": 1}, (_FUNC_ALL | _DBG1_ALL) ^ 0x1),
    # In TEST_DEV a demotion DOES force its group open over the DIS vectors, and
    # only its own group -- so an all-ones SIP_DIS still leaves the other group off.
    (LC_TEST_DEV, M64, 0, {"demote_1": 1}, _DBG1_ALL),
    (LC_TEST_DEV, M64, 0, {"demote_2": 1}, _DBG2_ALL),
    (LC_TEST_DEV, M64, 0, {"demote_1": 1, "demote_2": 1}, _DEBUG_ALL),
    (LC_PROD, 0x000A_0000_0000_0000, 0, {}, 0xFFF5_0000_0000_0000),  # func-bit masking by SIP
    (LC_RMA_CHIP_1, 0, 0, {}, M64),  # RMA_CHIPLET: all ones
    (LC_PROD, 0, 0, {"sec_dis": 1}, M64),  # SEC_DIS override = all ones
    (LC_TEST_DEV, 0xFFFF_FFFF_FFFF_FFFF, 0, {"sigint_err": 1}, 0),  # sigint -> all disabled
    # SEC_DIS overrides sigint to all-ones. SECURE_TM does not clear any group.
    (LC_TEST_DEV, 0, 0, {"sigint_err": 1, "sec_dis": 1}, M64),
    (LC_TEST_DEV, 0, 0, {"sigint_err": 1, "sec_dis": 1, "secure_tm": 1}, M64),
    # Stitch-test DIS vectors: both legs match; SECURE_TM does not drop [47:24].
    (LC_TEST_DEV, 0x0F0F_0F0F_0F0F_0F0F, 0x00FF_00FF_00FF_00FF, {}, 0xF000_F000_F000_F000),
    (
        LC_TEST_DEV,
        0x0F0F_0F0F_0F0F_0F0F,
        0x00FF_00FF_00FF_00FF,
        {"secure_tm": 1},
        0xF000_F000_F000_F000,
    ),
    # Named fuse-dbg bits (2, 3) bind in TEST_DEV when both DIS vectors set them.
    (LC_TEST_DEV, 0xC, 0xC, {}, M64 ^ 0xC),
)


def selftest() -> None:
    """Validate feat_ctrl_expected against the hand-computed vectors. Raises on
    any mismatch. Called at import; also runnable standalone."""
    for lc_raw, sip_dis, sys_dis, kwargs, expected in _LCC_GOLDEN_VECTORS:
        got = feat_ctrl_expected(lc_raw, sip_dis, sys_dis, **kwargs)
        assert got == expected, (
            f"LCC golden self-test failed: feat_ctrl_expected({lc_state_name(lc_raw)}, "
            f"sip=0x{sip_dis:x}, sys=0x{sys_dis:x}, {kwargs}) = 0x{got:016x} "
            f"!= expected 0x{expected:016x}"
        )
    # Transition-validator spot checks (chapter rules, not a state table).
    assert is_valid_lc_transition(LC_TEST_DEV, LC_PROD)  # forward W1S
    assert not is_valid_lc_transition(LC_PROD, LC_RMA_CHIP_1)  # bit 2 without RMA_SIP
    assert not is_valid_lc_transition(LC_RMA_SIP_1, LC_PROD)  # W1S: bit 1 cannot drop
    assert is_valid_lc_transition(LC_RMA_CHIP_0, LC_RMA_CHIP_1)  # bit 0 is don't-care in 011X
    assert not is_valid_lc_transition(0x9, LC_PROD_END)  # nothing leaves INVALID

    # Next-state spot checks: the two token gates, and INVALID as the only
    # terminal condition.
    assert lc_state_next(LC_TEST_DEV, 0x1, sip_match=False, chiplet_match=False) == LC_PROD
    assert lc_state_next(LC_PROD, 0x2, sip_match=False, chiplet_match=False) == LC_PROD
    assert lc_state_next(LC_PROD, 0x2, sip_match=True, chiplet_match=False) == LC_RMA_SIP_1
    assert lc_state_next(LC_PROD, 0x4, sip_match=False, chiplet_match=True) == LC_PROD
    assert lc_state_next(LC_RMA_SIP_0, 0x4, sip_match=False, chiplet_match=True) == LC_RMA_CHIP_0
    assert lc_state_next(LC_RMA_SIP_0, 0x1, sip_match=False, chiplet_match=False) == LC_RMA_SIP_1
    assert lc_state_next(LC_RMA_CHIP_0, 0x1, sip_match=False, chiplet_match=False) == LC_RMA_CHIP_1
    # PROD_END's only reachable destinations are outside the named set.
    assert is_invalid_lc(lc_state_next(LC_PROD_END, 0x1, sip_match=True, chiplet_match=True))
    assert lc_state_next(0x9, 0xF, sip_match=True, chiplet_match=True) == 0x9
    assert dbg_disable_unpack(0, DBG_DISABLE_WIDTH)["stap_io"] == 0
    try:
        dbg_disable_unpack(0, DBG_DISABLE_WIDTH + 1)
    except AssertionError:
        pass
    else:
        raise AssertionError("dbg_disable_unpack must reject a width mismatch")

    # sip=1, chiplet=0, sep=0: Case 1 open, Cases 2 and 3 closed. stap_sep
    # and dft_secure are Case 3; a Case 1 formula would open them here.
    sip_only = 1 << SIP_DBG_BIT
    got = dbg_disable_expected(sip_only)
    assert got["stap_io"] == 0
    assert got["dfd"] == 0
    assert got["stap_host"] == 0
    assert got["stap_smc"] == 1
    assert got["stap_sep"] == 1
    assert got["dft_secure"] == 1
    assert got["stap_sep"] != (1 - ((sip_only >> SIP_DBG_BIT) & 1)), (
        "stap_sep Case 3 vs Case 1 must diverge when only SIP_DBG is set"
    )
    # sip=1, chiplet=1, sep=0: Case 2 open, Case 3 still closed.
    sip_chip = (1 << SIP_DBG_BIT) | (1 << 1)
    got = dbg_disable_expected(sip_chip)
    assert got["stap_smc"] == 0
    assert got["dft_secure"] == 1
    assert got["stap_sep"] == 1
    sip_chip_sep = sip_chip | 1
    got = dbg_disable_expected(sip_chip_sep)
    assert got["dft_secure"] == 0
    assert got["stap_sep"] == 0

    # SECURE_TM is not a dbg_disable term. The same FEAT_CTRL must produce the
    # same ladder at both strap polarities, and dft_secure is Case 3, not the
    # inverse of the strap. TEST_DEV with both DIS vectors clear opens Case 3.
    feat_tm0 = feat_ctrl_expected(LC_TEST_DEV, 0, 0, secure_tm=0)
    feat_tm1 = feat_ctrl_expected(LC_TEST_DEV, 0, 0, secure_tm=1)
    assert feat_tm0 == feat_tm1 == M64
    assert dbg_disable_expected(feat_tm0) == dbg_disable_expected(feat_tm1)
    assert dbg_disable_expected(feat_tm0)["dft_secure"] == 0
    # RMA_CHIPLET is all-ones: Case 3 open, SIB enabled.
    assert dbg_disable_expected(feat_ctrl_expected(LC_RMA_CHIP_1, 0, 0))["dft_secure"] == 0
    # PROD, no demote: debug closed, SIB closed at both polarities.
    prod0 = feat_ctrl_expected(LC_PROD, 0, 0, secure_tm=0)
    prod1 = feat_ctrl_expected(LC_PROD, 0, 0, secure_tm=1)
    assert dbg_disable_expected(prod0)["dft_secure"] == 1
    assert dbg_disable_expected(prod1)["dft_secure"] == 1

    # Fuse-path disables: a granular bit is an extra AND, not a substitute.
    closed = sip_chip_sep  # cases open, bits 2/3 closed
    got = fuse_dft_disable_expected(closed)
    assert got["sep_fuse_dft_disable"] == 1
    assert got["smc_fuse_dft_disable"] == 1
    opened = closed | (1 << SEP_FUSE_DBG_BIT) | (1 << SMC_FUSE_DBG_BIT)
    got = fuse_dft_disable_expected(opened)
    assert got["sep_fuse_dft_disable"] == 0
    assert got["smc_fuse_dft_disable"] == 0
    # Case 2 open, Case 3 closed, both granular bits open: only SEP stays disabled.
    case2_only = sip_chip | (1 << SEP_FUSE_DBG_BIT) | (1 << SMC_FUSE_DBG_BIT)
    got = fuse_dft_disable_expected(case2_only)
    assert got["smc_fuse_dft_disable"] == 0
    assert got["sep_fuse_dft_disable"] == 1
    # Cases closed, granular bits open: both stay disabled.
    granular_only = (1 << SEP_FUSE_DBG_BIT) | (1 << SMC_FUSE_DBG_BIT)
    got = fuse_dft_disable_expected(granular_only)
    assert got["sep_fuse_dft_disable"] == 1
    assert got["smc_fuse_dft_disable"] == 1


# ---------------------------------------------------------------------------
# dbg_disable
# ---------------------------------------------------------------------------
# Named dbg_disable bits. Each is a DUT-output port on tb_top; checkers read
# those ports by name. The DTP ladder in lifecycle_controller.adoc states the
# three cases, not a packing order. Same-case bits still share a golden, but
# a swapped pair of ports fails because the sample reads each port by name.
DBG_DISABLE_FIELDS = (
    "stap_io",
    "stap_smc",
    "stap_sep",
    "stap_extra",
    "stap_host",
    "dft_secure",
    "dft_nonsecure",
    "dfd",
    "smc_jtag2axi",
    "smc_otp_jtag2axi",
    "sep_otp_jtag2axi",
)
DBG_DISABLE_WIDTH = len(DBG_DISABLE_FIELDS)

# Every packed dbg_disable bit is claimed. The lifecycle chapter's DTP path
# table states the three nested cases: Case 1 SIP_DBG, Case 2 plus
# CHIPLET_DBG, Case 3 plus SEP_DBG. The DFT-inserted fuse-path disables are
# separate DUT ports; ``fuse_dft_disable_expected`` owns those.
DBG_DISABLE_UNCLAIMED: tuple[str, ...] = ()


def _dbg_cases(feat_ctrl: int) -> tuple[int, int, int]:
    """Nested DTP cases as enable polarity (1 = case open)."""
    sep_dbg = (feat_ctrl >> 0) & 1
    chiplet_dbg = (feat_ctrl >> 1) & 1
    sip_dbg = (feat_ctrl >> SIP_DBG_BIT) & 1
    case1 = sip_dbg
    case2 = sip_dbg & chiplet_dbg
    case3 = case2 & sep_dbg
    return case1, case2, case3


def fuse_dft_disable_expected(feat_ctrl: int) -> dict[str, int]:
    """Expected DFT-inserted fuse-path disables for a FEAT_CTRL value.

    ``sep_fuse_dft_disable`` is Case 3 AND ``sep_fuse_dbg`` (bit 2), inverted
    to disable polarity. ``smc_fuse_dft_disable`` is Case 2 AND
    ``smc_fuse_dbg`` (bit 3), inverted. A granular bit is an additional
    term, not a substitute for its case.
    """
    _case1, case2, case3 = _dbg_cases(feat_ctrl)
    sep_fuse_dbg = (feat_ctrl >> SEP_FUSE_DBG_BIT) & 1
    smc_fuse_dbg = (feat_ctrl >> SMC_FUSE_DBG_BIT) & 1
    return {
        "sep_fuse_dft_disable": 1 - (case3 & sep_fuse_dbg),
        "smc_fuse_dft_disable": 1 - (case2 & smc_fuse_dbg),
    }


def dbg_disable_expected(feat_ctrl: int) -> dict[str, int]:
    """Expected dbg_disable bits for a FEAT_CTRL value, per the DTP gating ladder.

    The lifecycle chapter states the ladder as three nested cases, composed by
    AND so that a partial fuse burn fails safe:

        Case 1  SIP_DBG
        Case 2  SIP_DBG & CHIPLET_DBG
        Case 3  SIP_DBG & CHIPLET_DBG & SEP_DBG

    ``dbg_disable`` is active-high (1 = interface disabled), so each bit is the
    negation of its case. SIP_DBG is the mandatory outer gate: no path opens
    while it is closed, which is what makes SEP_DBG alone insufficient to reach
    SEP internal state.
    """
    case1, case2, case3 = _dbg_cases(feat_ctrl)

    exp = {
        "stap_io": 1 - case1,
        "dfd": 1 - case1,
        "stap_host": 1 - case1,
        "stap_smc": 1 - case2,
        "stap_extra": 1 - case2,
        "dft_nonsecure": 1 - case2,
        "smc_jtag2axi": 1 - case2,
        "dft_secure": 1 - case3,
        "stap_sep": 1 - case3,
        # hw/sys/sep/doc/lifecycle_controller.adoc ("DTP path feature gates"): the
        # SEP and SMC OTP JTAG2AXIL paths are "Ungated" -- no feature control
        # bit gates them; LOCKS and the wrapper access policy enforce access.
        "smc_otp_jtag2axi": 0,
        "sep_otp_jtag2axi": 0,
    }
    assert set(exp) | set(DBG_DISABLE_UNCLAIMED) == set(DBG_DISABLE_FIELDS), (
        "dbg_disable golden does not account for every field in the struct"
    )
    return exp


def dbg_disable_sample(dut) -> dict[str, int]:
    """Read each dbg_disable bit from its named DUT-output port."""
    return {name: int(getattr(dut, f"dbg_disable_{name}_o").value) for name in DBG_DISABLE_FIELDS}


def dbg_disable_unpack(raw: int, width: int) -> dict[str, int]:
    """Split the flattened dbg_disable vector into named bits (MSB first).

    ``width`` is the exported vector's declared width, not ``int.bit_length``:
    leading zeros are bits. A field added or reordered in the packed struct
    changes that width and must fail here so the field list is updated.
    """
    n = DBG_DISABLE_WIDTH
    assert width == n, (
        f"dbg_disable vector is {width} bits, golden lists {n} fields -- "
        "the packed struct changed and the field list must be updated"
    )
    return {name: (raw >> (n - 1 - i)) & 1 for i, name in enumerate(DBG_DISABLE_FIELDS)}


selftest()


if __name__ == "__main__":
    selftest()
    print("LCC GOLDEN SELFTEST PASS")
