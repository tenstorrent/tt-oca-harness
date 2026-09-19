# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_composition_parameter_test (SMU_102).

Passive parameter and connection inspection of the elaborated wrapper: the
SEP security-disable token as it reaches the SEP eFuse controller, the forced
SEP OTP pipeline depths on the DTP, the SEP-to-SMC security_disable wire, and
the elaborated `Cfg` struct decoded field by field.

The per-field `Cfg` compares use `CFG_ELABORATION_DEFAULTS`, which mirrors
`smu_pkg::DefaultCfg`; they detect unintended drift in the elaborated build
parameters and prove no requirement, so they carry no evidence token. The same
table is applied to the SEP=1 (DefaultCfg) and SEP=0 (NoSepCfg) builds, which
is what shows the two presets field-identical -- again as drift, not as
conformance. The token-carrying checks are the plumbing ones: a parameter or
net observed at the instance that consumes it, and a decoded `Cfg` field
observed to be the width or depth the design actually elaborated from it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.smu_compose_helpers import (
    CFG_ELABORATION_DEFAULTS,
    CFG_TOTAL_BITS,
    DTP_NUM_INT_CT,
    NUM_INT_TO_SMC,
    SEP_OTP_PL_DEPTH,
    SEP_SEC_DISABLE_TOKEN_WIDTH,
    XTRIG_NUM_INT_CT,
    XTRIG_SMC_CLK_STOP_LANES,
    XTRIG_SMC_INT_CT_LANES,
    GenerateScope,
    bit_width,
    decode_cfg,
    hier,
    parse_plusarg_int,
    sample,
)
from seq_lib.smu_tb_pins import smu_scope

SEP_EFUSE_CTRL_PATH = "gen_sep.u_sep.sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller"


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

        # SMU-SEC-TOKEN.S2: the default build presents 256'b0 on the token.
        for scope, label in ((wrapper, "smu_wrapper"), (smu, "smu")):
            tok = hier(scope, "SEP_SEC_DISABLE_TOKEN")
            sb.expect_eq(
                f"{label}.SEP_SEC_DISABLE_TOKEN width",
                bit_width(tok, f"{label}.SEP_SEC_DISABLE_TOKEN"),
                SEP_SEC_DISABLE_TOKEN_WIDTH,
                evidence="CHK-SMU-SEC-TOKEN-S2",
            )
            sb.expect_eq(
                f"{label}.SEP_SEC_DISABLE_TOKEN default",
                sample(tok, f"{label}.SEP_SEC_DISABLE_TOKEN"),
                0,
                evidence="CHK-SMU-SEC-TOKEN-S2",
            )

        # SMU-OTPAXI-SEP.S3: DTP SEP OTP depths are the forced 2'h3.
        for leg in ("RD", "WR"):
            name = f"SEP_OTP_{leg}_PL_DEPTH"
            sb.expect_eq(
                f"u_dtp.{name} forced",
                sample(hier(smu, f"u_dtp.{name}"), f"u_dtp.{name}"),
                SEP_OTP_PL_DEPTH,
                evidence="CHK-SMU-OTPAXI-SEP-S3",
            )

        # Drift checks on the elaborated build parameters: CFG_LAYOUT and
        # CFG_ELABORATION_DEFAULTS mirror smu_pkg, so these carry no token.
        cfg_handle = hier(smu, "Cfg")
        sb.expect_eq(
            "smu.Cfg packed width matches the smu_cfg_t layout",
            bit_width(cfg_handle, "smu.Cfg"),
            CFG_TOTAL_BITS,
        )
        cfg_raw = sample(cfg_handle, "smu.Cfg")
        sb.expect_eq(
            "wrapper Cfg reaches smu unchanged",
            sample(hier(wrapper, "Cfg"), "smu_wrapper.Cfg"),
            cfg_raw,
            evidence="CHK-SMU-NOSEP-S4",
        )
        fields = decode_cfg(cfg_raw)
        expected = dict(CFG_ELABORATION_DEFAULTS)
        expected["XTRIG_INT_CT_MODE"] = xtrig_mode
        for name, want in expected.items():
            sb.expect_eq(f"Cfg.{name} drift (SEP={expected_sep})", fields[name], want)
        # Token-carrying: each decoded field is the width or depth the design
        # elaborated from it, which a mis-plumbed parameter fails.
        sb.expect_eq(
            "smc_ext_interrupts_i width follows Cfg.NUM_INT_TO_SMC",
            bit_width(hier(smu, "smc_ext_interrupts_i"), "smc_ext_interrupts_i"),
            fields["NUM_INT_TO_SMC"],
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq("Cfg.NUM_INT_TO_SMC drift", fields["NUM_INT_TO_SMC"], NUM_INT_TO_SMC)
        sb.expect_eq(
            "u_dtp.XTRIG_NUM_CTP follows Cfg.XTRIG_NUM_CTP",
            sample(hier(smu, "u_dtp.XTRIG_NUM_CTP"), "u_dtp.XTRIG_NUM_CTP"),
            fields["XTRIG_NUM_CTP"],
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq(
            "u_dtp.XTRIG_NUM_INT_CT is Cfg.XTRIG_NUM_INT_CT plus the SMC-reserved lanes",
            sample(hier(smu, "u_dtp.XTRIG_NUM_INT_CT"), "u_dtp.XTRIG_NUM_INT_CT"),
            fields["XTRIG_NUM_INT_CT"] + XTRIG_SMC_INT_CT_LANES,
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq(
            "u_dtp.XTRIG_NUM_CLK_STOP_REQ is Cfg.XTRIG_NUM_CLK_STOP_REQ plus the SMC-reserved lanes",
            sample(hier(smu, "u_dtp.XTRIG_NUM_CLK_STOP_REQ"), "u_dtp.XTRIG_NUM_CLK_STOP_REQ"),
            fields["XTRIG_NUM_CLK_STOP_REQ"] + XTRIG_SMC_CLK_STOP_LANES,
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq(
            "u_dtp.XTRIG_INT_CT_MODE follows Cfg.XTRIG_INT_CT_MODE",
            sample(hier(smu, "u_dtp.XTRIG_INT_CT_MODE"), "u_dtp.XTRIG_INT_CT_MODE"),
            (fields["XTRIG_INT_CT_MODE"] & ((1 << XTRIG_NUM_INT_CT) - 1)) << XTRIG_SMC_INT_CT_LANES,
            evidence="CHK-SMU-NOSEP-S4",
        )
        sb.expect_eq(
            "u_dtp.XTRIG_INT_CT_MODE width",
            bit_width(hier(smu, "u_dtp.XTRIG_INT_CT_MODE"), "u_dtp.XTRIG_INT_CT_MODE"),
            DTP_NUM_INT_CT,
        )
        for leg in ("RD", "WR"):
            name = f"SMC_OTP_{leg}_PL_DEPTH"
            sb.expect_eq(
                f"u_dtp.{name} follows Cfg.{name}",
                sample(hier(smu, f"u_dtp.{name}"), f"u_dtp.{name}"),
                fields[name],
                evidence="CHK-SMU-NOSEP-S4",
            )
        sb.expect_eq(
            "extra STAP port count follows Cfg.JTAG_NUM_EXTRA_STAPS",
            bit_width(hier(smu, "jtag_stap_extra_host_tdi_i"), "jtag_stap_extra_host_tdi_i"),
            fields["JTAG_NUM_EXTRA_STAPS"],
            evidence="CHK-SMU-NOSEP-S4",
        )
        self.log.info("Cfg decoded (SEP=%d): %s", expected_sep, fields)

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
                sample(hier(smu, "SEP_SEC_DISABLE_TOKEN"), "smu.SEP_SEC_DISABLE_TOKEN"),
                evidence="CHK-SMU-SEC-TOKEN-S1",
            )
            # SMU-LC-SECDIS.S1: one security_disable net from the SEP into SMC.
            sep_side = hier(smu, f"{SEP_EFUSE_CTRL_PATH}.security_disable_i")
            samples = set()
            for _ in range(16):
                await ClockCycles(dut.clk_smu_i, 1)
                wire = sample(sec_dis, "sep_security_disable")
                samples.add(
                    (
                        wire,
                        sample(smc_sec_dis, "u_smc.sep_security_disable_i"),
                        sample(sep_side, "sep efuse security_disable_i"),
                    )
                )
            sb.expect_true(
                "security_disable identical at the SEP consumer, the SMU wire and the SMC input",
                all(a == b == c for a, b, c in samples),
                evidence="CHK-SMU-LC-SECDIS-S1",
            )
            self.log.info("security_disable samples (wire, smc, sep): %s", sorted(samples))
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
