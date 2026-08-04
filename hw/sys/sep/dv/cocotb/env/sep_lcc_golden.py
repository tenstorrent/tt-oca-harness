# SPDX-License-Identifier: Apache-2.0
"""Lifecycle-Controller (LCC) golden model for the SEP OSS flow.

Pure-Python reference for what the SEP `sep_lifecycle_ctrl` block computes on its
``feat_ctrl`` output as a function of the eFuse-sensed lifecycle state and the
DEMOTE / secure-test-mode / security-disable inputs. It is an independent port
of the RTL combinational decode (``hw/sep/sep_lifecycle_ctrl.sv`` lines 61-154),
cross-checked against the OCAH UVM golden model
(``compute_expected_feature_ctrl`` in ``sep_lcc_uvm_base_test_seq.sv``). Because
it is derived from the spec/RTL -- not from observed DUT output -- a feat_ctrl
mismatch is a real failure, not a tautology.

Also holds the lifecycle-state encoding / transition validators that mirror the
SVA state checker (``assertions/sep_lcc_state_checker.sv``): legal encoding, W1S
monotonicity, valid transition, and terminal stability. These let a value-driven
test reproduce the SVA intent on the observed lc_state sequence.
"""

from __future__ import annotations

from sep_reg_meta import sym

# -- lifecycle-state raw encodings (efuse_pkg::lc_state_raw_e) -----------------
LC_TEST_DEV = 0x0
LC_PROD = 0x1
LC_RMA_SIP_0 = 0x2
LC_RMA_SIP_1 = 0x3
LC_RMA_CHIP_0 = 0x6
LC_RMA_CHIP_1 = 0x7
LC_PROD_END = 0x8
LEGAL_LC_RAW = (
    LC_TEST_DEV, LC_PROD, LC_RMA_SIP_0, LC_RMA_SIP_1,
    LC_RMA_CHIP_0, LC_RMA_CHIP_1, LC_PROD_END,
)
_LC_NAME = {
    LC_TEST_DEV: "TEST_DEV", LC_PROD: "PROD",
    LC_RMA_SIP_0: "RMA_SIP_0", LC_RMA_SIP_1: "RMA_SIP_1",
    LC_RMA_CHIP_0: "RMA_CHIP_0", LC_RMA_CHIP_1: "RMA_CHIP_1",
    LC_PROD_END: "PROD_END",
}

# -- LCC register map (single source of truth; imported by the LCC sequences) -
SEP_LCC_BASE = sym("SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR")
LCC_FEAT_CTRL = SEP_LCC_BASE + 0x0    # 64-bit RO, hw-driven from lc_state; [0]=sep_debug
LCC_DEMOTE_1 = SEP_LCC_BASE + 0x8     # demote [0:0], lock [1:1]
LCC_DEMOTE_2 = SEP_LCC_BASE + 0x10

# -- feat_ctrl bit layout (sep_efuse_map_lc_disable_reg_t) ---------------------
#   [31:0]  Debug  (sep_debug, soc_debug, ap_debug, ap_trace, sip_debug, rsvd)
#   [47:32] Test   (fuse_test, sep_stest, sep_dtest, ap_stest, ap_dtest, rsvd)
#   [63:48] Func   (func_reserved[15:0])
M64 = (1 << 64) - 1
DEBUG_MASK = (1 << 32) - 1            # bits [31:0]
TEST_MASK = ((1 << 16) - 1) << 32     # bits [47:32]
FUNC_MASK = ((1 << 16) - 1) << 48     # bits [63:48]


def lc_state_name(raw: int) -> str:
    return _LC_NAME.get(raw & 0xF, f"INVALID(0x{raw & 0xF:x})")


def is_legal_lc(raw: int) -> bool:
    """Valid frontdoor encoding (the 7 reachable codes); 0x4,0x5,0x9-0xF illegal."""
    return (raw & 0xF) in LEGAL_LC_RAW


def is_w1s_superset(prev: int, cur: int) -> bool:
    """W1S: bits only ever go 0->1, so cur must contain every set bit of prev."""
    return (prev & cur) == prev


def is_valid_lc_transition(prev: int, cur: int) -> bool:
    """Mirror of the SVA transition truth table (sep_lcc_state_checker.sv).

    Forward-only lifecycle: TEST_DEV -> PROD -> RMA_SIP -> RMA_CHIPLET, plus the
    PROD_END terminal; RMA_CHIPLET and PROD_END are terminal (self only). A
    same-state step is always allowed (resense of an unchanged image).
    """
    prev &= 0xF
    cur &= 0xF
    if not (is_legal_lc(prev) and is_legal_lc(cur)):
        return False
    if cur == prev:
        return True
    # Terminal states cannot leave.
    if prev in (LC_RMA_CHIP_0, LC_RMA_CHIP_1, LC_PROD_END):
        return False
    # All advancing transitions must be W1S-monotonic. NOTE: the W1S gate above
    # is what tightens the per-state table below to the SVA truth table -- e.g.
    # PROD(0x1) lists RMA_SIP_0(0x2) but 0x1->0x2 is not W1S (bit0 would drop),
    # so it is correctly rejected here, not in the table. Do not "simplify" the
    # table without re-adding that filtering.
    if not is_w1s_superset(prev, cur):
        return False
    valid = {
        LC_TEST_DEV: (LC_PROD, LC_RMA_SIP_0, LC_RMA_SIP_1, LC_PROD_END),
        LC_PROD: (LC_RMA_SIP_0, LC_RMA_SIP_1),  # PROD cannot skip to RMA_CHIPLET
        LC_RMA_SIP_0: (LC_RMA_SIP_1, LC_RMA_CHIP_0, LC_RMA_CHIP_1),
        LC_RMA_SIP_1: (LC_RMA_CHIP_0, LC_RMA_CHIP_1),
    }
    return cur in valid.get(prev, ())


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

    Faithful port of sep_lifecycle_ctrl.sv: the unique-case decode (lines 78-154)
    followed by the security_disable override (line 61) and the secure_tm test-bit
    clear (lines 65-73). ``sip_dis``/``sys_dis`` are the 64-bit sensed shadow
    values; ``demote_*``/``secure_tm``/``sec_dis`` default to the no-CPU image
    case (DEMOTE regs at reset, normal non-secure image).
    """
    sip_dis &= M64
    sys_dis &= M64

    if sigint_err:
        feat = 0
    elif lc_raw == LC_TEST_DEV:                       # 4'b0000
        feat = (~(sip_dis | sys_dis)) & M64
        if demote_1 or demote_2:
            feat |= DEBUG_MASK                        # re-enable all debug
    elif lc_raw == LC_PROD:                           # 4'b0001
        if demote_1:                                  # PROD_DBG_1: {T,F,~SIP.FUNC}
            feat = DEBUG_MASK | ((~sip_dis) & FUNC_MASK)
        elif demote_2:                                # PROD_DBG_2: {T,F,~SYS.FUNC}
            feat = DEBUG_MASK | ((~sys_dis) & FUNC_MASK)
        else:                                         # PROD: {F,F,~(SIP|SYS).FUNC}
            feat = (~(sip_dis | sys_dis)) & FUNC_MASK
    elif lc_raw == LC_PROD_END:                       # 4'b1000
        feat = (~(sip_dis | sys_dis)) & FUNC_MASK
    elif lc_raw in (LC_RMA_SIP_0, LC_RMA_SIP_1):      # 4'b001?
        feat = (~sip_dis) & M64
    elif lc_raw in (LC_RMA_CHIP_0, LC_RMA_CHIP_1):    # 4'b011?
        feat = M64
    else:                                             # INVALID/others
        feat = 0

    if sec_dis:
        feat = M64
    if not secure_tm:
        feat &= ~TEST_MASK & M64
    return feat & M64


# -- import-time KAT self-test -------------------------------------------------
# Hand-computed (input -> expected) vectors pinning each decode branch, so a
# transcription error in the formula above (wrong mask, dropped branch, inverted
# override) fails loudly here at import rather than as a silent feat_ctrl mismatch
# deep in a sim. Independent of DUT output: the expected values are derived by
# hand from sep_lifecycle_ctrl.sv, not observed. Note secure_tm=0 (the no-CPU
# image default) clears TEST_MASK ([47:32]), so a full-ones result reads
# 0xFFFF_0000_FFFF_FFFF.
_FULL_NO_TEST = 0xFFFF_0000_FFFF_FFFF       # M64 with TEST_MASK cleared
_FUNC_ALL = 0xFFFF_0000_0000_0000           # FUNC_MASK only

_LCC_GOLDEN_VECTORS = (
    # (lc_raw, sip_dis, sys_dis, kwargs, expected)
    (LC_TEST_DEV, 0, 0, {}, _FULL_NO_TEST),                       # all-enable, test bits cleared
    (LC_TEST_DEV, 0, 0, {"secure_tm": 1}, M64),                   # secure_tm keeps test bits
    (LC_PROD, 0, 0, {}, _FUNC_ALL),                               # PROD: func only, debug off
    (LC_PROD, 0, 0, {"demote_1": 1}, 0xFFFF_0000_FFFF_FFFF),      # PROD_DBG_1: debug + func
    (LC_PROD, 0x000A_0000_0000_0000, 0, {}, 0xFFF5_0000_0000_0000),  # func-bit masking by SIP
    (LC_RMA_CHIP_1, 0, 0, {}, _FULL_NO_TEST),                     # RMA_CHIPLET: all ones
    (LC_PROD, 0, 0, {"sec_dis": 1, "secure_tm": 1}, M64),        # SEC_DIS override = all ones
    (LC_TEST_DEV, 0xFFFF_FFFF_FFFF_FFFF, 0, {"sigint_err": 1}, 0),   # sigint -> all disabled
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
    # Transition-validator spot checks (mirror the SVA truth table).
    assert is_valid_lc_transition(LC_TEST_DEV, LC_PROD)           # forward W1S
    assert not is_valid_lc_transition(LC_PROD, LC_RMA_CHIP_1)     # PROD cannot skip
    assert not is_valid_lc_transition(LC_RMA_CHIP_1, LC_PROD_END) # terminal


selftest()


if __name__ == "__main__":
    selftest()
    print("LCC GOLDEN SELFTEST PASS")
