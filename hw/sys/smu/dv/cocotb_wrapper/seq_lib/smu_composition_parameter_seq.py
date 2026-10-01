# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_composition_parameter_test (SMU_102).

Passive parameter and connection inspection of the elaborated wrapper: the
SEP security-disable token as it reaches `smu` and the SEP eFuse controller,
the SEP OTP pipeline depths on the DTP, the SEP-to-SMC security_disable wire,
and the consumer-side parameters the SMU derives from its build configuration.

The token-carrying compares have two kinds of golden. A specification value:
`doc/integrator/src/smu.adoc` states the SMU default parameters, the DTP
counts the SMC reservation adds to them, the fixed SEP OTP depths and the
extra-STAP port sizing; the SMC port table states the external interrupt
count; the SEP security-disable document states the token width. Or a
plumbing compare: the same parameter read at the wrapper and at the instance
that consumes it, which a mis-wired parameter fails.

The bench binds SEP_SEC_DISABLE_TOKEN to the SHA-256 of the all-zero 32-byte
token in place of the metal digest, and the token the wrapper carries is
compared against that digest, computed here. No specification in this tree
states the packed layout of the build configuration struct; the per-field
`Cfg` compares that go through `decode_cfg` are drift checks on the
elaboration and carry no evidence token.
"""

from __future__ import annotations

import hashlib

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.smu_compose_helpers import (
    CFG_SPEC_DEFAULTS,
    CFG_TOTAL_BITS,
    DTP_NUM_CLK_STOP_REQ,
    DTP_NUM_INT_CT,
    JTAG_NUM_EXTRA_STAPS,
    NUM_INT_TO_SMC,
    SEP_OTP_PL_DEPTH,
    SEP_SEC_DISABLE_TOKEN_WIDTH,
    SMC_OTP_PL_DEPTH,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
    XTRIG_SMC_INT_CT_LANES,
    GenerateScope,
    bit_width,
    decode_cfg,
    hier,
    parse_plusarg_int,
    sample,
)
from seq_lib.smu_tb_pins import smu_scope

# The bench stands in for the metal SEP_SEC_DISABLE_TOKEN digest with the
# SHA-256 of the all-zero 32-byte token, so a frontdoor token can match.
BENCH_SEC_DISABLE_DIGEST = int.from_bytes(hashlib.sha256(bytes(32)).digest(), "big")
SEP_EFUSE_CTRL_PATH = "gen_sep.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller"


class smu_composition_parameter_seq:
    """Parameter and wire plumbing into the composed subsystems."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        smu = smu_scope(dut)
        wrapper = hier(dut, "u_dut")
        expected_sep = parse_plusarg_int("expected_sep")
        xtrig_mode = parse_plusarg_int("xtrig_int_ct_mode")
        await self.test.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_eq("smu SEP parameter", sample(smu.SEP, "smu.SEP"), expected_sep)
        sb.expect_eq("wrapper SEP parameter", sample(wrapper.SEP, "smu_wrapper.SEP"), expected_sep)
        sb.expect_eq(
            "sep_enabled_o build flag", sample(dut.sep_enabled_o, "sep_enabled_o"), expected_sep
        )

        # SMU-SEC-TOKEN.S2: the token is 256 bits at the wrapper and at smu and
        # reaches smu unchanged. The bench binds the SHA-256 of the all-zero
        # 32-byte token in place of the metal digest, so that is the value the
        # wrapper carries.
        tokens = {}
        for scope, label in ((wrapper, "smu_wrapper"), (smu, "smu")):
            tok = hier(scope, "SEP_SEC_DISABLE_TOKEN")
            sb.expect_eq(
                f"{label}.SEP_SEC_DISABLE_TOKEN width",
                bit_width(tok, f"{label}.SEP_SEC_DISABLE_TOKEN"),
                SEP_SEC_DISABLE_TOKEN_WIDTH,
                evidence="CHK-SMU-SEC-TOKEN-S2",
            )
            tokens[label] = sample(tok, f"{label}.SEP_SEC_DISABLE_TOKEN")
        sb.expect_eq(
            "wrapper SEP_SEC_DISABLE_TOKEN reaches smu unchanged",
            tokens["smu"],
            tokens["smu_wrapper"],
            evidence="CHK-SMU-SEC-TOKEN-S2",
        )
        sb.expect_eq(
            "SEP_SEC_DISABLE_TOKEN is the bench-bound digest of the all-zero token",
            tokens["smu_wrapper"],
            BENCH_SEC_DISABLE_DIGEST,
        )

        # SMU-OTPAXI-SEP.S3: DTP SEP OTP depths are the fixed 2'h3.
        for leg in ("RD", "WR"):
            name = f"SEP_OTP_{leg}_PL_DEPTH"
            sb.expect_eq(
                f"u_dtp.{name} fixed depth",
                sample(hier(smu, f"u_dtp.{name}"), f"u_dtp.{name}"),
                SEP_OTP_PL_DEPTH,
                evidence="CHK-SMU-OTPAXI-SEP-S3",
            )

        # SMU-NOSEP.S4, plumbing: the wrapper's Cfg is the one smu elaborates.
        cfg_handle = hier(smu, "Cfg")
        cfg_raw = sample(cfg_handle, "smu.Cfg")
        sb.expect_eq(
            "wrapper Cfg reaches smu unchanged",
            sample(hier(wrapper, "Cfg"), "smu_wrapper.Cfg"),
            cfg_raw,
            evidence="CHK-SMU-NOSEP-S4",
        )

        # Drift: the struct layout has no specification, so the decode and the
        # per-field compares carry no token.
        sb.expect_eq("smu.Cfg packed width drift", bit_width(cfg_handle, "smu.Cfg"), CFG_TOTAL_BITS)
        fields = decode_cfg(cfg_raw)
        expected = dict(CFG_SPEC_DEFAULTS)
        expected["XTRIG_INT_CT_MODE"] = xtrig_mode
        for name, want in expected.items():
            sb.expect_eq(f"Cfg.{name} drift (SEP={expected_sep})", fields[name], want)
        self.log.info("Cfg decoded (SEP=%d): %s", expected_sep, fields)

        # SMU-NOSEP.S4, consumers: each parameter read where it is consumed is
        # the specified default, plus the SMC reservation where the
        # specification adds one.
        sb.expect_eq(
            "smc_ext_interrupts_i is the SMC external interrupt count wide",
            bit_width(hier(smu, "smc_ext_interrupts_i"), "smc_ext_interrupts_i"),
            NUM_INT_TO_SMC,
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq(
            "u_dtp.XTRIG_NUM_CTP is the default external CTP count",
            sample(hier(smu, "u_dtp.XTRIG_NUM_CTP"), "u_dtp.XTRIG_NUM_CTP"),
            XTRIG_NUM_CTP,
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq(
            "u_dtp.XTRIG_NUM_INT_CT is the exposed count plus the SMC-reserved lanes",
            sample(hier(smu, "u_dtp.XTRIG_NUM_INT_CT"), "u_dtp.XTRIG_NUM_INT_CT"),
            DTP_NUM_INT_CT,
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq(
            "u_dtp.XTRIG_NUM_CLK_STOP_REQ is the exposed count plus the SMC-reserved lane",
            sample(hier(smu, "u_dtp.XTRIG_NUM_CLK_STOP_REQ"), "u_dtp.XTRIG_NUM_CLK_STOP_REQ"),
            DTP_NUM_CLK_STOP_REQ,
            evidence="CHK-SMU-NOSEP-S4",
        )
        dtp_mode = hier(smu, "u_dtp.XTRIG_INT_CT_MODE")
        sb.expect_eq(
            "u_dtp.XTRIG_INT_CT_MODE width is the DTP internal CT count",
            bit_width(dtp_mode, "u_dtp.XTRIG_INT_CT_MODE"),
            DTP_NUM_INT_CT,
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq(
            "u_dtp.XTRIG_INT_CT_MODE is the elaborated mode above zeroed SMC-reserved bits",
            sample(dtp_mode, "u_dtp.XTRIG_INT_CT_MODE"),
            (xtrig_mode & ((1 << XTRIG_NUM_INT_CT) - 1)) << XTRIG_SMC_INT_CT_LANES,
            evidence="CHK-SMU-NOSEP-S4",
        )
        for leg in ("RD", "WR"):
            name = f"SMC_OTP_{leg}_PL_DEPTH"
            sb.expect_eq(
                f"u_dtp.{name} is the default depth",
                sample(hier(smu, f"u_dtp.{name}"), f"u_dtp.{name}"),
                SMC_OTP_PL_DEPTH,
                evidence="CHK-SMU-NOSEP-S4",
            )
        sb.expect_eq(
            "extra STAP port count is the default JTAG_NUM_EXTRA_STAPS",
            bit_width(hier(smu, "jtag_stap_extra_host_tdi_i"), "jtag_stap_extra_host_tdi_i"),
            JTAG_NUM_EXTRA_STAPS,
            evidence="CHK-SMU-NOSEP-S4",
        )

        sec_dis = hier(smu, "sep_security_disable")
        smc_sec_dis = hier(smu, "u_smc.sep_security_disable_i")
        if expected_sep == 1:
            # SMU-SEC-TOKEN.S1: the token reaches the SEP eFuse controller.
            sep_tok = hier(smu, f"{SEP_EFUSE_CTRL_PATH}.SEP_SEC_DISABLE_TOKEN")
            sb.expect_eq(
                "SEP eFuse controller token width",
                bit_width(sep_tok, "sep efuse SEP_SEC_DISABLE_TOKEN"),
                SEP_SEC_DISABLE_TOKEN_WIDTH,
                evidence="CHK-SMU-SEC-TOKEN-S1",
            )
            sb.expect_eq(
                "SEP eFuse controller token equals the SMU parameter",
                sample(sep_tok, "sep efuse SEP_SEC_DISABLE_TOKEN"),
                tokens["smu"],
                evidence="CHK-SMU-SEC-TOKEN-S1",
            )
            # SMU-LC-SECDIS.S1: the security_disable net, recorded while no token is written.
            sep_side = hier(smu, f"{SEP_EFUSE_CTRL_PATH}.security_disable_o")
            samples = set()
            for _ in range(16):
                await ClockCycles(dut.clk_smu_i, 1)
                wire = sample(sec_dis, "sep_security_disable")
                samples.add(
                    (
                        wire,
                        sample(smc_sec_dis, "u_smc.sep_security_disable_i"),
                        sample(sep_side, "sep efuse security_disable_o"),
                    )
                )
            self.log.info(
                "OBSERVATION security_disable samples with no token written (wire, smc, sep): %s",
                sorted(samples),
            )
        else:
            sb.expect_eq(
                "SEP=0 ties security_disable into SMC low",
                (
                    sample(sec_dis, "sep_security_disable"),
                    sample(smc_sec_dis, "u_smc.sep_security_disable_i"),
                ),
                (0, 0),
            )
            sb.expect_true(
                "SEP=0 build elaborates gen_no_sep, not gen_sep",
                GenerateScope(smu, "gen_no_sep").exists()
                and not GenerateScope(smu, "gen_sep").exists(),
            )
