# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P2-A / P2-11: SMBus / PMBus protocol extension over the I2C VIP.

Proves that `SmcI2cMasterVip.smbus_*` and `pmbus_*` helpers drive real
SMBus / PMBus semantics through the split-port polarity + wired-AND
adapter into `SmcI2cEepromSlave`:

  * SMBus write-with-PEC — computes CRC-8/0x07 checksum and appends it.
  * SMBus ARA query — issues a directed read to reserved slave 0x0C.
  * PMBus Linear11 encode/decode — pure math self-check (no bus traffic).

The EEPROM slave stores the payload including PEC; the assertion then
cross-checks the byte layout in slave memory.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq

try:
    from .smc_i2c_protocol_vip import (
        SmcI2cEepromSlave,
        SmcI2cMasterVip,
    )

    _I2C_VIP_AVAILABLE = True
except Exception:  # noqa: BLE001
    SmcI2cEepromSlave = None  # type: ignore[assignment]
    SmcI2cMasterVip = None  # type: ignore[assignment]
    _I2C_VIP_AVAILABLE = False

_EEPROM_ADDR = 0x50
_SMBUS_PAYLOAD = bytes([0x10, 0xA5])  # regptr byte + data byte
# SMBus 2.0 §5.5 PEC (CRC-8, poly 0x07, init 0) over [0xA0, 0x10, 0xA5].
# Independent of smbus_pec() so the helper is checked, not assumed.
_SMBUS_PEC_REFERENCE = 0x6D
_PMBUS_TEST_VALUES = [0.0, 1.0, 3.14, 12.0, 512.5, 1023.0]
# Linear16 uses a fixed exponent (here -1 => N*0.5) per PMBus helper API.
_PMBUS_LINEAR16_VALUES = [0.0, 1.0, 3.5, 12.0, 100.0]
_PMBUS_LINEAR16_EXP = -1


class smc_smbus_pmbus_test_seq(SmcCsrSeq):
    """P2-A SMBus/PMBus helper proof."""

    async def body(self) -> None:
        assert _I2C_VIP_AVAILABLE, "I2C protocol VIP unavailable"

        # Real DUT gate (model-free): drive the DUT I2C0 controller and verify it
        # physically actuates the tb_i2c0 SCL/SDA pins via OVRD. This fails if the
        # DUT I2C0 controller reg->pin path is broken, so the test is not a pure
        # VIP-side self-check. (The SMBus PEC / PMBus Linear11 checks below
        # are protocol-math helpers on the cocotb master VIP -- SMBus/PMBus are
        # software layers on top of I2C, verified VIP-side; the byte transaction,
        # when run, traverses the DUT-facing I2C0 pins.)
        await self.prove_dut_i2c0_pins()
        await self.wait_i2c0_lsio_ready("I2C0_PMBUS_AFTER_PIN_PROOF")

        # PMBus Linear11 encode/decode self-check (pure math, no bus traffic).
        for v in _PMBUS_TEST_VALUES:
            enc = SmcI2cMasterVip.pmbus_encode_linear11(v)
            dec = SmcI2cMasterVip.pmbus_decode_linear11(enc)
            cocotb.log.info(
                "PMBus Linear11: %s -> enc=0x%04X -> dec=%s",
                v,
                enc,
                dec,
            )
            if v > 0:
                relative = abs(dec - v) / v
                assert relative < 0.02, (
                    f"PMBus Linear11 round-trip error {relative * 100:.1f}% for {v}"
                )

        # PMBus Linear16 encode/decode (fixed exponent).
        encode16 = getattr(SmcI2cMasterVip, "pmbus_encode_linear16", None)
        decode16 = getattr(SmcI2cMasterVip, "pmbus_decode_linear16", None)
        if encode16 is None or decode16 is None:
            cocotb.log.info(
                "PMBus Linear16 helpers absent on SmcI2cMasterVip; "
                "Linear11+PEC remain the defended subset"
            )
        else:
            for v in _PMBUS_LINEAR16_VALUES:
                enc = encode16(v, _PMBUS_LINEAR16_EXP)
                dec = decode16(enc, _PMBUS_LINEAR16_EXP)
                cocotb.log.info(
                    "PMBus Linear16: %s exp=%d -> enc=0x%04X -> dec=%s",
                    v,
                    _PMBUS_LINEAR16_EXP,
                    enc,
                    dec,
                )
                if v > 0:
                    relative = abs(dec - v) / v
                    assert relative < 0.02, (
                        f"PMBus Linear16 round-trip error {relative * 100:.1f}% for {v}"
                    )

        # Static PEC check against an independently computed reference, so the
        # bus compare below is not the checker grading its own arithmetic.
        # SMBus 2.0 §5.5 PEC is CRC-8 with polynomial x^8+x^2+x+1 (0x07),
        # init 0, over the frame including the address byte:
        #   frame = [(0x50 << 1) | 0, 0x10, 0xA5] = [0xA0, 0x10, 0xA5] -> 0x6D
        expected_pec = SmcI2cMasterVip.smbus_pec(_EEPROM_ADDR, 0, _SMBUS_PAYLOAD)
        assert expected_pec == _SMBUS_PEC_REFERENCE, (
            f"SMBus PEC helper returned 0x{expected_pec:02X} for frame "
            f"[0x{(_EEPROM_ADDR << 1) | 0:02X}, {_SMBUS_PAYLOAD.hex(' ')}], "
            f"expected the CRC-8/0x07 reference 0x{_SMBUS_PEC_REFERENCE:02X}"
        )
        cocotb.log.info(
            "CHK-SMBUS-PEC-REF: addr=0x%02X payload=%s -> PEC=0x%02X matches the "
            "CRC-8/0x07 reference",
            _EEPROM_ADDR,
            _SMBUS_PAYLOAD.hex(),
            expected_pec,
        )

        # Real bus traffic: SMBus write-with-PEC via master → slave EEPROM.
        # Same path on VCS and Verilator (LSIO enable must be ready first).
        slave = SmcI2cEepromSlave(addr=_EEPROM_ADDR)
        master = SmcI2cMasterVip(speed=100_000)

        pec = await master.smbus_write_with_pec(_EEPROM_ADDR, _SMBUS_PAYLOAD)

        # Slave stores full payload including PEC. First byte is the regptr
        # 0x10; subsequent bytes (data 0xA5, PEC) land at offset 0x10.
        stored = slave.read_mem(0x10, 2)
        cocotb.log.info(
            "SMBus PEC bus proof: slave memory at 0x10 = %s (expected 0x%02X 0x%02X)",
            stored.hex(),
            _SMBUS_PAYLOAD[1],
            pec,
        )
        assert stored[0] == _SMBUS_PAYLOAD[1], (
            f"SMBus data byte mismatch: got 0x{stored[0]:02X}, expected 0x{_SMBUS_PAYLOAD[1]:02X}"
        )
        assert stored[1] == pec, f"SMBus PEC mismatch: got 0x{stored[1]:02X}, expected 0x{pec:02X}"

        # ARA query — no target alerting, so the reserved Alert Response Address
        # 0x0C must go unclaimed and the master's read defaults to 0xFF.
        #
        # 0xFF on its own proves nothing: SmcI2cMasterVip.read() returns
        # 0xFF * count on an address NACK without raising, which is byte-for-byte
        # what a dead bus, a mis-bound VIP, or a DUT holding SCL low produces.
        # So gate on what the slave witnessed on the wire instead.
        #
        # The positive control is in this same run, on this same bus: the
        # write-with-PEC above was ACKed by the slave and its payload landed in
        # slave memory, so the pads and the VIP are demonstrably alive here.
        assert slave.acks > 0, (
            "positive control missing: the slave never ACKed an address in this "
            "run, so the ARA result below cannot be distinguished from a dead bus"
        )
        starts_before = slave.starts
        acks_before = slave.acks

        ara = await master.smbus_query_ara()

        starts_seen = slave.starts - starts_before
        acks_seen = slave.acks - acks_before
        assert starts_seen >= 1, (
            "SMBus ARA query put no START on the wire: the slave monitor saw "
            f"{starts_seen} new STARTs, so nothing was driven to 0x0C and the "
            f"0x{ara:02X} reply is the VIP's NACK default, not an observation"
        )
        assert acks_seen == 0, (
            f"SMBus ARA query was ACKed {acks_seen} time(s) at address 0x0C: a "
            "target claimed the Alert Response Address when none should be "
            "alerting"
        )
        assert ara == 0xFF, (
            f"SMBus ARA reply 0x{ara:02X} is not the unclaimed-address default "
            "0xFF, yet the address went unACKed"
        )
        cocotb.log.info(
            "CHK-SMBUS-ARA: ARA read to 0x0C drove %d START(s) the slave "
            "observed and went unACKed (%d ACKs), reply 0x%02X — no target "
            "alerting, on a bus the PEC write above proved alive",
            starts_seen,
            acks_seen,
            ara,
        )
