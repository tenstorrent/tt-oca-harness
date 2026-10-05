# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import importlib.util
import re

import pytest
import testlist_loader
from testlist_loader import load_testlist, load_testlist_dir

pytestmark = pytest.mark.hostonly


def test_testlist_loader_module_exists():
    assert importlib.util.find_spec("testlist_loader") is not None


def test_loads_typed_testcase(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        """
[[testcase]]
name = "scratch"
family = "warm_reset"
classification = "partial"
image = "signed"
base_ini = "secure"
boot = "primary"
timeout = 90
expect_verdict = "PASSED"
markers = ["Does not model a real watchdog reset."]
pytest_markers = ["needs_debug"]
expect = ["WARM_JUMP_OK"]
forbid = ["TRAP H0"]
preloaded_test_programs = ["warm_jump"]
init_writes = [
  { address = 0x10802038, value = 0xC0030000 },
]
"""
    )

    load_testlist = getattr(testlist_loader, "load_testlist", None)
    assert callable(load_testlist), "testlist_loader.load_testlist is not implemented"
    testcase = load_testlist(
        testlist_path,
        known_programs={"warm_jump"},
        known_images={"signed"},
    )[0]

    assert testcase.name == "scratch"
    assert testcase.family == "warm_reset"
    assert testcase.classification == "partial"
    assert testcase.image == "signed"
    assert testcase.base_ini == "secure"
    assert testcase.boot == "primary"
    assert testcase.timeout == 90
    assert testcase.markers == ("Does not model a real watchdog reset.",)
    assert testcase.pytest_markers == ("needs_debug",)
    assert testcase.expect == ("WARM_JUMP_OK",)
    assert testcase.forbid == ("TRAP H0",)
    assert testcase.preloaded_test_programs == ("warm_jump",)
    assert testcase.observation == "complete"
    assert [(write.address, write.value) for write in testcase.init_writes] == [
        (0x10802038, 0xC0030000)
    ]


@pytest.mark.parametrize(
    "body, message",
    [
        (
            'family = "warm_reset"\nclassification = "partial"\nunknown = true',
            "unknown field",
        ),
        ('family = ""\nclassification = "partial"', "family"),
        ('family = "warm_reset"\nclassification = "finished"', "classification"),
        ('family = "warm_reset"\nclassification = "partial"\ntimeout = 0', "timeout"),
        (
            'family = "warm_reset"\nclassification = "partial"\n'
            "init_writes = [{ address = 0x10802039, value = 0 }]",
            "4-byte aligned",
        ),
        (
            'family = "warm_reset"\nclassification = "partial"\n'
            'preloaded_test_programs = ["missing"]',
            "unknown preloaded test program",
        ),
        (
            'family = "warm_reset"\nclassification = "partial"\nimage = "missing"',
            "unknown boot image",
        ),
        (
            'family = "warm_reset"\nclassification = "partial"\nbase_ini = "production"',
            "base_ini",
        ),
        (
            'family = "warm_reset"\nclassification = "model-blocked"\n'
            'markers = ["Needs more work."]',
            "requires a non-empty 'Blocked:' marker",
        ),
        (
            'family = "warm_reset"\nclassification = "partial"\n'
            'expect = ["WARM_JUMP_OK"]\nforbid = ["WARM_JUMP_OK"]',
            "both expect and forbid",
        ),
        (
            'family = "warm_reset"\nclassification = "partial"\nexpect = [" "]',
            "non-empty strings",
        ),
    ],
)
def test_rejects_invalid_testcase_fields(tmp_path, body, message):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        f"""
[[testcase]]
name = "scratch"
{body}
"""
    )

    load_testlist = getattr(testlist_loader, "load_testlist", None)
    assert callable(load_testlist), "testlist_loader.load_testlist is not implemented"
    with pytest.raises(ValueError, match=message):
        load_testlist(testlist_path, known_programs={"warm_jump"})


def test_rejects_duplicate_testcase_names(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        """
[[testcase]]
name = "duplicate"
family = "warm_reset"
classification = "partial"
expect_verdict = "PASSED"

[[testcase]]
name = "duplicate"
family = "warm_reset"
classification = "partial"
expect_verdict = "PASSED"
"""
    )

    load_testlist = getattr(testlist_loader, "load_testlist", None)
    assert callable(load_testlist), "testlist_loader.load_testlist is not implemented"
    with pytest.raises(ValueError, match="duplicate testcase name"):
        load_testlist(testlist_path)


_SPI_DETECT_ENTRY = """
[[testcase]]
name = "spi_detect"
tp_id = "TP013"
family = "spi_boot"
classification = "vp-equivalent"
image = "signed"
base_ini = "secure"
boot = "primary"
observation = "complete"
timeout = 180
expect_verdict = "PASSED"
expect = ["BOOT_SPI", "GO!"]
forbid = ["MANIFEST_BACKUP", "[VP] SIMULATION OF THE TEST FAILED"]
expect_counts = { GO = 1 }
spi_reads = [
  { name = "descriptor",       range = [0x0,     0x1000],    exact = 0 },
  { name = "primary_manifest", range = [0x1000,  0x2000],    min = 1 },
  { name = "primary_payload",  range = [0x2000,  0x41000],   min = 1 },
  { name = "backup",           range = [0x41000, 0x43410],   exact = 0 },
  { name = "beyond",           range = [0x43410, 0x2000000], exact = 0 },
]
spi_read_order = ["primary_manifest", "primary_payload"]
"""


def test_loads_spi_read_contract(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(_SPI_DETECT_ENTRY)

    testcase = testlist_loader.load_testlist(testlist_path, known_images={"signed"})[0]

    assert testcase.tp_id == "TP013"
    assert testcase.expect_counts == {"GO": 1}
    assert [
        (span.name, span.low, span.high, span.exact, span.minimum, span.maximum)
        for span in testcase.spi_reads
    ] == [
        ("descriptor", 0x0, 0x1000, 0, None, None),
        ("primary_manifest", 0x1000, 0x2000, None, 1, None),
        ("primary_payload", 0x2000, 0x41000, None, 1, None),
        ("backup", 0x41000, 0x43410, 0, None, None),
        ("beyond", 0x43410, 0x2000000, 0, None, None),
    ]
    assert testcase.spi_read_order == ("primary_manifest", "primary_payload")
    assert testcase.expect_verdict == "PASSED"


@pytest.mark.parametrize(
    "assertions, message",
    [
        (
            'spi_reads = [{ name = "a", range = [0x0, 0x100] }]',
            "asserts nothing",
        ),
        (
            'spi_reads = [{ name = "a", range = [0x100, 0x100], exact = 0 }]',
            "range is empty",
        ),
        (
            'spi_reads = [{ name = "a", range = [0x0, 0x100], exact = -1 }]',
            "non-negative integer",
        ),
        (
            'spi_reads = [{ name = "a", range = [0x0, 0x100], exact = 0 },\n'
            '              { name = "a", range = [0x100, 0x200], exact = 0 }]',
            "two spans named",
        ),
        (
            'spi_reads = [{ name = "a", range = [0x0, 0x200], exact = 0 },\n'
            '              { name = "b", range = [0x100, 0x300], exact = 0 }]',
            "overlap",
        ),
        (
            'spi_reads = [{ name = "a", range = [0x0, 0x100], exact = 0, size = 4 }]',
            "unknown field",
        ),
        ('spi_read_order = ["a"]', "spi_read_order needs spi_reads"),
        (
            'spi_reads = [{ name = "a", range = [0x0, 0x100], exact = 0 }]\nspi_read_order = ["b"]',
            "unknown span",
        ),
        (
            'observation = "streaming"\nexpect = ["A"]\n'
            'spi_reads = [{ name = "a", range = [0x0, 0x100], exact = 0 }]',
            "streaming observation cannot use",
        ),
    ],
)
def test_rejects_invalid_spi_read_assertions(tmp_path, assertions, message):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        f"""
[[testcase]]
name = "invalid"
family = "spi_boot"
classification = "vp-equivalent"
{assertions}
"""
    )

    with pytest.raises(ValueError, match=message):
        testlist_loader.load_testlist(testlist_path)


def test_loads_efuse_overrides(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        """
[[testcase]]
name = "policy"
family = "secure_boot_policy"
classification = "vp-equivalent"
base_ini = "secure"
expect = ["GO!"]
expect_verdict = "PASSED"
efuse = { lc_state = "TEST_DEV", sboot_dis = 1, chiplet_uid = [1, 2] }
"""
    )

    testcase = testlist_loader.load_testlist(testlist_path)[0]

    assert testcase.efuse == {
        "lc_state": "TEST_DEV",
        "sboot_dis": 1,
        "chiplet_uid": (1, 2),
    }


@pytest.mark.parametrize(
    "body, message",
    [
        ('base_ini = "secure"\nexpect = ["A"]\nefuse = 1', "efuse must be a table"),
        (
            'base_ini = "secure"\nexpect = ["A"]\nefuse = { "" = 1 }',
            "efuse field names",
        ),
        (
            'base_ini = "secure"\nexpect = ["A"]\nefuse = { lc_state = 1.5 }',
            "efuse lc_state",
        ),
        (
            'base_ini = "secure"\nexpect = ["A"]\nefuse = { uid = ["a"] }',
            "efuse uid",
        ),
        ('expect = ["A"]\nefuse = { sboot_dis = 1 }', "efuse needs a base_ini"),
    ],
)
def test_rejects_invalid_efuse_overrides(tmp_path, body, message):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        f"""
[[testcase]]
name = "policy"
family = "secure_boot_policy"
classification = "vp-equivalent"
{body}
"""
    )

    with pytest.raises(ValueError, match=message):
        testlist_loader.load_testlist(testlist_path)


def test_loads_expect_verdict(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        """
[[testcase]]
name = "terminal"
family = "spi_boot"
classification = "vp-equivalent"
expect = ["HALT", "[VP] SIMULATION OF THE TEST FAILED"]
expect_verdict = "FAILED"
"""
    )

    testcase = testlist_loader.load_testlist(testlist_path)[0]

    assert testcase.expect_verdict == "FAILED"


@pytest.mark.parametrize(
    "body, message",
    [
        ('expect = ["A"]\nexpect_verdict = "passed"', "expect_verdict must be one of"),
        ('expect = ["A"]\nexpect_verdict = true', "expect_verdict must be one of"),
        (
            'observation = "streaming"\nexpect = ["A"]\nexpect_verdict = "PASSED"',
            "streaming observation cannot use",
        ),
        (
            'expect = ["A", "[VP] SIMULATION OF THE TEST FAILED"]',
            'expect_verdict = "FAILED"',
        ),
        (
            'expect = ["A", "[VP] SIMULATION OF THE TEST FAILED"]\nexpect_verdict = "none"',
            'expect_verdict = "FAILED"',
        ),
    ],
)
def test_rejects_inconsistent_expect_verdict(tmp_path, body, message):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        f"""
[[testcase]]
name = "verdict"
family = "spi_boot"
classification = "vp-equivalent"
{body}
"""
    )

    with pytest.raises(ValueError, match=re.escape(message)):
        testlist_loader.load_testlist(testlist_path)


def test_loads_image_asserts(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        """
[[testcase]]
name = "mutated"
family = "spi_boot"
classification = "vp-equivalent"
image = "spi_primary_slot_blank"
expect = ["GO!"]
expect_verdict = "PASSED"
image_asserts = [
  { range = [0x1000, 0x41000], all = 0xFF },
  { range = [0x41000, "end"], same_as = "signed" },
  { range = [0x1000, 0x1004], differs_from = "signed" },
]
"""
    )

    testcase = testlist_loader.load_testlist(
        testlist_path, known_images={"spi_primary_slot_blank"}
    )[0]

    assert [
        (check.low, check.high, check.all_byte, check.same_as, check.differs_from)
        for check in testcase.image_asserts
    ] == [
        (0x1000, 0x41000, 0xFF, None, None),
        (0x41000, None, None, "signed", None),
        (0x1000, 0x1004, None, None, "signed"),
    ]


@pytest.mark.parametrize(
    "asserts, message",
    [
        ("image_asserts = [{ range = [0, 16] }]", "must name exactly one of"),
        (
            'image_asserts = [{ range = [0, 16], all = 0xFF, same_as = "signed" }]',
            "must name exactly one of",
        ),
        (
            'image_asserts = [{ range = [0, 16], same_as = "signed", differs_from = "signed" }]',
            "must name exactly one of",
        ),
        ("image_asserts = [{ range = [16, 16], all = 0xFF }]", "range is empty"),
        ("image_asserts = [{ range = [0, 16], all = 256 }]", "must be a byte"),
        ('image_asserts = [{ range = [0, 16], same_as = "" }]', "same_as"),
        ('image_asserts = [{ range = [0, 16], differs_from = "" }]', "differs_from"),
        (
            "image_asserts = [{ range = [0, 16], all = 0xFF, note = 1 }]",
            "unknown field",
        ),
    ],
)
def test_rejects_invalid_image_asserts(tmp_path, asserts, message):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        f"""
[[testcase]]
name = "mutated"
family = "spi_boot"
classification = "vp-equivalent"
image = "signed"
expect = ["GO!"]
{asserts}
"""
    )

    with pytest.raises(ValueError, match=message):
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})


def test_image_asserts_require_a_boot_image(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        """
[[testcase]]
name = "no-image"
family = "spi_boot"
classification = "vp-equivalent"
expect = ["GO!"]
image_asserts = [{ range = [0, 16], all = 0xFF }]
"""
    )

    with pytest.raises(ValueError, match="image_asserts needs an image"):
        testlist_loader.load_testlist(testlist_path)


def test_loads_complete_run_assertion_fields(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        """
[[testcase]]
name = "complete"
family = "manifest"
classification = "vp-equivalent"
expect = ["RETRY", "HALT"]
forbid = ["GO!"]
expect_counts = { RETRY = 2 }
terminal_token = "HALT"
expect_status = ["INFO 0x0031", "ERROR 0x005f"]
forbid_status = ["ERROR 0x9999"]
expect_verdict = "PASSED"
"""
    )

    testcase = testlist_loader.load_testlist(testlist_path)[0]

    assert testcase.expect_counts == {"RETRY": 2}
    assert testcase.terminal_token == "HALT"
    assert testcase.expect_silence is False
    assert testcase.expect_status == ("INFO 0x0031", "ERROR 0x005f")
    assert testcase.forbid_status == ("ERROR 0x9999",)
    assert testcase.observation == "complete"


@pytest.mark.parametrize(
    "assertions, message",
    [
        ('expect = [" "]', "non-empty strings"),
        ('expect = ["A"]\nexpect_counts = { A = -1 }', "non-negative integer"),
        ('expect = ["A"]\nterminal_token = ""', "terminal_token"),
        (
            'expect = ["A"]\nexpect_status = ["not-a-status"]',
            "expect_status",
        ),
        (
            'expect = ["A"]\nexpect_silence = true\nforbid = ["B"]',
            "expect_silence and expect",
        ),
        ("expect_silence = true", "requires forbid"),
        ('expect_silence = true\nforbid = ["GO!"]', "liveness stimulus"),
        ('expect = ["A"]\nobservation = "short"', "observation"),
        (
            'observation = "streaming"\nexpect = ["A"]\nexpect_counts = { A = 1 }',
            "streaming observation cannot use",
        ),
    ],
)
def test_rejects_invalid_complete_run_assertions(tmp_path, assertions, message):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        f"""
[[testcase]]
name = "invalid"
family = "manifest"
classification = "vp-equivalent"
{assertions}
"""
    )

    with pytest.raises(ValueError, match=message):
        testlist_loader.load_testlist(testlist_path)


_SMC_SRAM_ENTRY = """
[[testcase]]
name = "secondary"
family = "secondary_chiplet"
classification = "vp-equivalent"
boot = "secondary"
expect = ["BOOT_SECONDARY"]
expect_verdict = "PASSED"
smc_sram_image = "signed"
smc_sram_source = [0x1000, 0x41000]
smc_sram_offset = 0x2000
smc_sram_manifest_at = 0x0
"""


def test_loads_smc_sram_staging(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(_SMC_SRAM_ENTRY)

    testcase = testlist_loader.load_testlist(testlist_path, known_images={"signed"})[0]

    assert testcase.smc_sram_image == "signed"
    assert testcase.smc_sram_source == (0x1000, 0x41000)
    assert testcase.smc_sram_offset == 0x2000
    assert testcase.smc_sram_manifest_at == 0x0


def test_smc_sram_fields_default_to_none(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        """
[[testcase]]
name = "plain"
family = "manifest"
classification = "vp-equivalent"
expect = ["GO!"]
expect_verdict = "PASSED"
"""
    )

    testcase = testlist_loader.load_testlist(testlist_path)[0]

    assert testcase.smc_sram_image is None
    assert testcase.smc_sram_source is None
    assert testcase.smc_sram_offset is None
    assert testcase.smc_sram_manifest_at is None


@pytest.mark.parametrize(
    "replacement, message",
    [
        # A partial declaration cannot say what the ROM is pointed at.
        ("smc_sram_offset = 0x2000\n", "one statement"),
        # Two of the four is still a partial declaration.
        ("smc_sram_offset = 0x2000\nsmc_sram_source = [0x1000, 0x41000]\n", "one statement"),
    ],
)
def test_rejects_partial_smc_sram_declaration(tmp_path, replacement, message):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        f"""
[[testcase]]
name = "secondary"
family = "secondary_chiplet"
classification = "vp-equivalent"
boot = "secondary"
expect = ["BOOT_SECONDARY"]
{replacement}"""
    )

    with pytest.raises(ValueError, match=message):
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("smc_sram_image", '"nope"', "unknown boot image"),
        ("smc_sram_source", "[0x41000, 0x1000]", "range is empty"),
        ("smc_sram_offset", "0x2001", "4-byte aligned"),
        ("smc_sram_offset", "0x100000", "1 MiB SMC SRAM window"),
        # 0x40000 staged bytes at 0xF0000 run past the 1 MiB window.
        ("smc_sram_offset", "0xF0000", "does not fit"),
        ("smc_sram_manifest_at", "0x2", "4-byte aligned"),
        ("smc_sram_manifest_at", "0x40000", "lies past"),
    ],
)
def test_rejects_invalid_smc_sram_fields(tmp_path, field, value, message):
    lines = []
    for line in _SMC_SRAM_ENTRY.strip().splitlines():
        if line.startswith(f"{field} "):
            line = f"{field} = {value}"
        lines.append(line)
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ValueError, match=message):
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})


def test_rejects_smc_sram_on_a_primary_boot(tmp_path):
    """A primary chiplet boots from SPI flash and never reads the SMC window."""
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(_SMC_SRAM_ENTRY.replace('boot = "secondary"', 'boot = "primary"'))

    with pytest.raises(ValueError, match='needs boot = "secondary"'):
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})


def test_loads_smc_sram_staging_on_a_recovery_boot(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        _SMC_SRAM_ENTRY.replace('boot = "secondary"', 'boot = "primary"\nrecovery = true')
    )

    testcase = testlist_loader.load_testlist(testlist_path, known_images={"signed"})[0]

    assert testcase.recovery is True
    assert testcase.smc_sram_image == "signed"


def test_recovery_defaults_to_false(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(_SMC_SRAM_ENTRY)
    assert (
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})[0].recovery is False
    )


def test_recovery_must_be_a_boolean(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        _SMC_SRAM_ENTRY.replace('boot = "secondary"', 'boot = "primary"\nrecovery = 1')
    )
    with pytest.raises(ValueError, match="recovery must be a boolean"):
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})


def test_recovery_needs_a_primary_boot(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(_SMC_SRAM_ENTRY.replace('boot = "secondary"', "recovery = true"))
    with pytest.raises(ValueError, match='recovery needs boot = "primary"'):
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})


def test_recovery_excludes_rotate_update(tmp_path):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        _SMC_SRAM_ENTRY.replace(
            'boot = "secondary"', 'boot = "primary"\nrecovery = true\nrotate_update = true'
        )
    )
    with pytest.raises(ValueError, match="recovery cannot combine with rotate_update"):
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})


def test_rejects_smc_sram_on_a_streaming_observation(tmp_path):
    """The staging fence is a complete-run judge; streaming would lose it silently."""
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(
        _SMC_SRAM_ENTRY.replace(
            'boot = "secondary"', 'boot = "secondary"\nobservation = "streaming"'
        )
    )

    with pytest.raises(ValueError, match='needs observation = "complete"'):
        testlist_loader.load_testlist(testlist_path, known_images={"signed"})


_MEASUREMENT_ENTRY = """
[[testcase]]
name = "measurement"
family = "measurement"
classification = "partial"
image = "signed"
base_ini = "secure"
boot = "primary"
observation = "complete"
expect_verdict = "PASSED"
measurement_golden = { slot = "primary", lc_state = 0x1, demotion_decision = 0x2, secure_boot = 1, sboot_dis = 0 }
expect = [
  "MEAS_LC=0x00000001",
  "MEAS_DEMOTE=0x00000002",
  "MEAS_SBOOT=0x00000001",
  "MEAS_SBOOT_DIS=0x00000000",
  "{measurement_golden}",
]
"""


def _measurement(tmp_path, text):
    testlist_path = tmp_path / "testlist.toml"
    testlist_path.write_text(text)
    return testlist_loader.load_testlist(testlist_path, known_images={"signed"})


def test_loads_a_measurement_golden_spec(tmp_path):
    testcase = _measurement(tmp_path, _MEASUREMENT_ENTRY)[0]

    assert testcase.measurement_golden == testlist_loader.MeasurementGolden(
        slot="primary", lc_state=1, demotion_decision=2, secure_boot=1, sboot_dis=0
    )


def test_rejects_a_measurement_placeholder_without_a_spec(tmp_path):
    """Unsubstituted, the placeholder is matched as the literal text in braces."""
    entry = "\n".join(
        line
        for line in _MEASUREMENT_ENTRY.splitlines()
        if not line.startswith("measurement_golden")
    )

    with pytest.raises(ValueError, match="declares no measurement_golden"):
        _measurement(tmp_path, entry)


def test_rejects_a_measurement_spec_whose_digest_nothing_expects(tmp_path):
    entry = _MEASUREMENT_ENTRY.replace('  "{measurement_golden}",\n', "")

    with pytest.raises(ValueError, match=r"does not expect \{measurement_golden\}"):
        _measurement(tmp_path, entry)


def test_rejects_a_measurement_input_wider_than_its_field(tmp_path):
    """measurement.h masks lc_state to 4 bits, so 0x11 is not what would be hashed."""
    entry = _MEASUREMENT_ENTRY.replace("lc_state = 0x1", "lc_state = 0x11")

    with pytest.raises(ValueError, match="lc_state must be an integer in 0..0xf"):
        _measurement(tmp_path, entry)


def test_rejects_a_measurement_spec_without_an_image(tmp_path):
    entry = _MEASUREMENT_ENTRY.replace('image = "signed"\n', "")

    with pytest.raises(ValueError, match="measurement_golden needs an image"):
        _measurement(tmp_path, entry)


_MINIMAL = """
[[testcase]]
name = "{name}"
family = "{family}"
classification = "vp-equivalent"
image = "signed"
base_ini = "secure"
boot = "primary"
expect = ["GO!"]
expect_verdict = "PASSED"
"""


def _write(directory, family, *names):
    path = directory / f"{family}.toml"
    path.write_text("".join(_MINIMAL.format(name=n, family=family) for n in names))
    return path


def _write_all(directory):
    """One entry per family, named after it, so every FAMILY_ORDER file exists."""
    for family in testlist_loader.FAMILY_ORDER:
        _write(directory, family, family)


def test_dir_loads_families_in_fixed_order(tmp_path):
    _write_all(tmp_path)
    cases = load_testlist_dir(tmp_path, known_images={"signed"})
    assert [c.name for c in cases] == list(testlist_loader.FAMILY_ORDER)


def test_dir_rejects_a_name_used_in_two_files(tmp_path):
    _write_all(tmp_path)
    _write(tmp_path, "spi_boot", "same")
    _write(tmp_path, "warm_reset", "same")
    with pytest.raises(ValueError, match="spi_boot.toml"):
        load_testlist_dir(tmp_path, known_images={"signed"})


def test_dir_rejects_a_file_that_is_not_a_family(tmp_path):
    _write_all(tmp_path)
    (tmp_path / "misc.toml").write_text(_MINIMAL.format(name="x", family="misc"))
    with pytest.raises(ValueError, match="FAMILY_ORDER"):
        load_testlist_dir(tmp_path, known_images={"signed"})


def test_dir_rejects_a_family_that_disagrees_with_its_file(tmp_path):
    _write_all(tmp_path)
    (tmp_path / "spi_boot.toml").write_text(_MINIMAL.format(name="x", family="golden"))
    with pytest.raises(ValueError, match="declares family"):
        load_testlist_dir(tmp_path, known_images={"signed"})


def test_dir_rejects_an_empty_directory(tmp_path):
    with pytest.raises(ValueError, match="warm_reset.toml is missing"):
        load_testlist_dir(tmp_path)


def test_retired_entry_needs_a_reason_and_nothing_runnable(tmp_path):
    path = tmp_path / "t.toml"
    path.write_text(
        '[[testcase]]\nname = "r"\nfamily = "sram_selection"\nclassification = "retired"\n'
        'reason = "use_ext_sram is gone from the OCA manifest"\n'
    )
    (case,) = load_testlist(path)
    assert case.classification == "retired" and case.reason
    path.write_text(path.read_text() + 'image = "signed"\n')
    with pytest.raises(ValueError, match="retired"):
        load_testlist(path, known_images={"signed"})


def test_retired_entry_without_a_reason_is_refused(tmp_path):
    path = tmp_path / "t.toml"
    path.write_text(
        '[[testcase]]\nname = "r"\nfamily = "sram_selection"\nclassification = "retired"\n'
    )
    with pytest.raises(ValueError, match="reason"):
        load_testlist(path)


def test_reason_is_only_for_retired_entries(tmp_path):
    path = _write(tmp_path, "spi_boot", "a")
    path.write_text(path.read_text() + 'reason = "x"\n')
    with pytest.raises(ValueError, match="reason"):
        load_testlist(path, known_images={"signed"})


def test_xfail_reason_must_cite_a_dv_b_number(tmp_path):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(path.read_text() + 'xfail_reason = "ROM accepts it"\n')
    with pytest.raises(ValueError, match="B-number"):
        load_testlist(path, known_images={"signed"})
    path.write_text(
        path.read_text().replace("ROM accepts it", "DV B7: ROM accepts it") + 'xfail_match = "x"\n'
    )
    assert load_testlist(path, known_images={"signed"})[0].xfail_reason.startswith("DV B7")


def test_xfail_match_is_required_with_xfail_reason(tmp_path):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(path.read_text() + 'xfail_reason = "DV B7: x"\n')
    with pytest.raises(ValueError, match="xfail_match"):
        load_testlist(path, known_images={"signed"})


def test_xfail_match_is_forbidden_without_xfail_reason(tmp_path):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(path.read_text() + 'xfail_match = "x"\n')
    with pytest.raises(ValueError, match="xfail_match needs xfail_reason"):
        load_testlist(path, known_images={"signed"})


@pytest.mark.parametrize("value", ['""', "5", '"("'])
def test_xfail_match_must_be_a_compilable_regex(tmp_path, value):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(path.read_text() + f'xfail_reason = "DV B7: x"\nxfail_match = {value}\n')
    with pytest.raises(ValueError, match="xfail_match"):
        load_testlist(path, known_images={"signed"})


def test_xfail_match_loads_as_a_regex_string(tmp_path):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(
        path.read_text() + 'xfail_reason = "DV B7: x"\nxfail_match = "status: \'INFO 0x0055\'"\n'
    )
    assert load_testlist(path, known_images={"signed"})[0].xfail_match == "status: 'INFO 0x0055'"


def test_xfail_reason_cannot_combine_with_a_blocked_classification(tmp_path):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(
        path.read_text().replace("vp-equivalent", "model-blocked")
        + 'markers = ["Blocked: model"]\nxfail_reason = "DV B7: x"\nxfail_match = "x"\n'
    )
    with pytest.raises(ValueError, match="blocked classification"):
        load_testlist(path, known_images={"signed"})


def test_field_image_assert(tmp_path):
    path = _write(tmp_path, "demotion", "a")
    path.write_text(
        path.read_text()
        + 'image_asserts = [{ field = { name = "OFF_DEMOTION_CONTROL", slot = "primary", '
        "size = 2, value = 5 } }]\n"
    )
    (case,) = load_testlist(path, known_images={"signed"})
    assert case.image_asserts[0].field.name == "OFF_DEMOTION_CONTROL"


@pytest.mark.parametrize(
    "field, message",
    [
        ('{ name = "OFF_TOC_X", slot = "primary", size = 4, value = 1 }', "OFF_TOC_"),
        ('{ name = "DEMOTION", slot = "primary", size = 4, value = 1 }', "OFF_"),
        ('{ name = "OFF_X", slot = "third", size = 4, value = 1 }', "slot"),
        ('{ name = "OFF_X", slot = "primary", size = 3, value = 1 }', "size"),
        ('{ name = "OFF_X", slot = "primary", size = 1, value = 256 }', "value"),
    ],
)
def test_invalid_field_image_asserts_are_refused(tmp_path, field, message):
    path = _write(tmp_path, "demotion", "a")
    path.write_text(path.read_text() + f"image_asserts = [{{ field = {field} }}]\n")
    with pytest.raises(ValueError, match=message):
        load_testlist(path, known_images={"signed"})


def test_field_image_assert_cannot_carry_a_range(tmp_path):
    path = _write(tmp_path, "demotion", "a")
    path.write_text(
        path.read_text()
        + 'image_asserts = [{ range = [0, 4], field = { name = "OFF_X", slot = "primary", '
        "size = 1, value = 1 } }]\n"
    )
    with pytest.raises(ValueError, match="cannot carry a range"):
        load_testlist(path, known_images={"signed"})


def test_toc_field_image_assert(tmp_path):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(
        path.read_text()
        + 'image_asserts = [{ toc_field = { name = "OFF_TOC_ENTRY_OFFSET", slot = "backup", '
        "entry = 2, size = 8, value = 0x368 } }]\n"
    )
    (case,) = load_testlist(path, known_images={"signed"})
    check = case.image_asserts[0]
    assert (check.field, check.same_as, check.differs_from, check.all_byte) == (None,) * 4
    assert check.toc_field == testlist_loader.TocFieldAssert(
        "OFF_TOC_ENTRY_OFFSET", "backup", 2, 8, 0x368
    )


@pytest.mark.parametrize(
    "field, message",
    [
        ('{ name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", size = 8, value = 1 }', "exactly"),
        (
            '{ name = "OFF_PAYLOAD_OFFSET", slot = "primary", entry = 0, size = 8, value = 1 }',
            "OFF_TOC_ENTRY_",
        ),
        (
            '{ name = "OFF_TOC_IMAGE_COUNT", slot = "primary", entry = 0, size = 8, value = 1 }',
            "OFF_TOC_ENTRY_",
        ),
        (
            '{ name = "OFF_TOC_ENTRY_OFFSET", slot = "third", entry = 0, size = 8, value = 1 }',
            "slot",
        ),
        (
            '{ name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = -1, size = 8, value = 1 }',
            "entry",
        ),
        (
            '{ name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = "0", size = 8, value = 1 }',
            "entry",
        ),
        (
            '{ name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = 0, size = 3, value = 1 }',
            "size",
        ),
        (
            '{ name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = 0, size = 1, value = 256 }',
            "value",
        ),
    ],
)
def test_invalid_toc_field_image_asserts_are_refused(tmp_path, field, message):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(path.read_text() + f"image_asserts = [{{ toc_field = {field} }}]\n")
    with pytest.raises(ValueError, match=message):
        load_testlist(path, known_images={"signed"})


def test_toc_field_image_assert_cannot_carry_a_range(tmp_path):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(
        path.read_text()
        + 'image_asserts = [{ range = [0, 4], toc_field = { name = "OFF_TOC_ENTRY_OFFSET", '
        'slot = "primary", entry = 0, size = 8, value = 1 } }]\n'
    )
    with pytest.raises(ValueError, match="toc_field check cannot carry a range"):
        load_testlist(path, known_images={"signed"})


def test_same_as_xor_image_assert(tmp_path):
    path = _write(tmp_path, "bl1_image", "a")
    path.write_text(
        path.read_text()
        + 'image_asserts = [{ range = [0x1e64, 0x1e65], same_as = "signed", xor = 0xFF }]\n'
    )
    (case,) = load_testlist(path, known_images={"signed"})
    check = case.image_asserts[0]
    assert (check.low, check.high, check.same_as, check.xor) == (0x1E64, 0x1E65, "signed", 0xFF)


@pytest.mark.parametrize(
    "check, message",
    [
        ('{ range = [0, 1], differs_from = "signed", xor = 0xFF }', "xor needs same_as"),
        ("{ range = [0, 1], all = 0x00, xor = 0xFF }", "xor needs same_as"),
        ('{ range = [0, 1], same_as = "signed", xor = 0 }', "non-zero byte"),
        ('{ range = [0, 1], same_as = "signed", xor = 0x100 }', "non-zero byte"),
        ('{ range = [0, 1], same_as = "signed", xor = "ff" }', "non-zero byte"),
    ],
)
def test_invalid_xor_image_asserts_are_refused(tmp_path, check, message):
    path = _write(tmp_path, "bl1_image", "a")
    path.write_text(path.read_text() + f"image_asserts = [{check}]\n")
    with pytest.raises(ValueError, match=message):
        load_testlist(path, known_images={"signed"})


@pytest.mark.parametrize("address", [0x00000100, 0xC0030000, 0x10930000, 0x10802000])
def test_init_writes_outside_the_allowed_windows_are_refused(tmp_path, address):
    path = _write(tmp_path, "warm_reset", "a")
    path.write_text(path.read_text() + f"init_writes = [{{ address = {address}, value = 1 }}]\n")
    with pytest.raises(ValueError, match="init_writes"):
        load_testlist(path, known_images={"signed"})


@pytest.mark.parametrize("address", [0x10802004, 0x10802038, 0x40039080, 0x400390FC, 0x4000B800])
def test_init_writes_inside_the_allowed_windows_load(tmp_path, address):
    path = _write(tmp_path, "warm_reset", "a")
    path.write_text(path.read_text() + f"init_writes = [{{ address = {address}, value = 1 }}]\n")
    assert load_testlist(path, known_images={"signed"})[0].init_writes[0].address == address


def test_a_complete_entry_must_declare_its_verdict(tmp_path):
    path = _write(tmp_path, "spi_boot", "a")
    path.write_text(path.read_text().replace('expect_verdict = "PASSED"\n', ""))
    with pytest.raises(ValueError, match="must declare expect_verdict"):
        load_testlist(path, known_images={"signed"})


@pytest.mark.parametrize("value", ['".*"', '"x?"', '"(?:)"'])
def test_xfail_match_that_matches_an_empty_message_is_refused(tmp_path, value):
    path = _write(tmp_path, "payload_metadata", "a")
    path.write_text(path.read_text() + f'xfail_reason = "DV B7: x"\nxfail_match = {value}\n')
    with pytest.raises(ValueError, match="matches an empty message"):
        load_testlist(path, known_images={"signed"})


def test_dir_rejects_a_missing_family_file(tmp_path):
    _write_all(tmp_path)
    (tmp_path / "golden.toml").unlink()
    with pytest.raises(ValueError, match="golden.toml"):
        load_testlist_dir(tmp_path, known_images={"signed"})


def _with(tmp_path, family, extra):
    path = _write(tmp_path, family, "a")
    path.write_text(path.read_text() + extra + "\n")
    return path


def test_image_fact_bounds_and_values_load_as_expressions(tmp_path):
    path = _with(
        tmp_path,
        "payload_metadata",
        "image_asserts = [\n"
        '  { range = ["primary.payload_end", "end"], same_as = "signed" },\n'
        '  { range = [0x2138, "primary.bl1_start"], all = 0 },\n'
        '  { toc_field = { name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = 0, '
        'size = 8, value = "4092 - primary.bl1_len" } },\n'
        '  { toc_field = { name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = 0, '
        'size = 8, value_from = { image = "multi", entry = 2 } } },\n'
        '  { field = { name = "OFF_PAYLOAD_LENGTH", slot = "backup", size = 8, '
        'value_from = { image = "toc_cap" } } },\n'
        "]\n"
        'spi_reads = [{ name = "p", range = [0x2000, "primary.payload_end"], min = 1 }]\n'
        'forbid = ["LEN={primary.bl1_len}", "COPY_SRC={backup.bl1_copy_src}"]',
    )
    (case,) = load_testlist(path, known_images={"signed"})
    ranges, fill, offset, moved, length = case.image_asserts
    assert (ranges.low, ranges.high, fill.high) == (
        "primary.payload_end",
        None,
        "primary.bl1_start",
    )
    assert offset.toc_field.value == "4092 - primary.bl1_len"
    assert moved.toc_field.value_from == testlist_loader.ValueFrom("multi", 2)
    assert length.field.value_from == testlist_loader.ValueFrom("toc_cap")
    assert case.spi_reads[0].high == "primary.payload_end"
    assert case.forbid == ("LEN={primary.bl1_len}", "COPY_SRC={backup.bl1_copy_src}")


def test_smc_sram_source_may_end_at_the_image_end(tmp_path):
    path = tmp_path / "testlist.toml"
    path.write_text(_SMC_SRAM_ENTRY.replace("[0x1000, 0x41000]", '[0x0, "image_end"]'))
    (case,) = load_testlist(path, known_images={"signed"})
    assert case.smc_sram_source == (0, "image_end")


@pytest.mark.parametrize(
    "value, message",
    [
        ('"primary.bogus"', "unknown image fact 'primary.bogus'"),
        ('"primary.payload_end +"', "expression over image facts"),
        ('"primary.payload_end 8"', "expression over image facts"),
        ('"4092"', "expression over image facts"),
        ("1.5", "expression over image facts"),
    ],
)
def test_malformed_image_fact_expressions_are_refused(tmp_path, value, message):
    path = _with(
        tmp_path,
        "payload_metadata",
        f'image_asserts = [{{ range = [{value}, "end"], same_as = "signed" }}]',
    )
    with pytest.raises(ValueError, match=re.escape(message)):
        load_testlist(path, known_images={"signed"})


@pytest.mark.parametrize(
    "check, message",
    [
        (
            '{ field = { name = "OFF_X", slot = "primary", size = 8, value = 1, '
            'value_from = { image = "signed" } } }',
            "one of value or value_from",
        ),
        (
            '{ field = { name = "OFF_X", slot = "primary", size = 8 } }',
            "one of value or value_from",
        ),
        (
            '{ field = { name = "OFF_X", slot = "primary", size = 8, '
            'value_from = { image = "signed", entry = 0 } } }',
            "value_from must contain exactly image",
        ),
        (
            '{ toc_field = { name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = 0, '
            'size = 8, value_from = { image = "signed" } } }',
            "value_from must contain exactly entry and image",
        ),
        (
            '{ toc_field = { name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = 0, '
            'size = 8, value_from = { image = "signed", entry = -1 } } }',
            "value_from entry",
        ),
        (
            '{ toc_field = { name = "OFF_TOC_ENTRY_OFFSET", slot = "primary", entry = 0, '
            'size = 8, value = "primary.payload" } }',
            "unknown image fact",
        ),
    ],
)
def test_invalid_field_value_sources_are_refused(tmp_path, check, message):
    path = _with(tmp_path, "payload_metadata", f"image_asserts = [{check}]")
    with pytest.raises(ValueError, match=message):
        load_testlist(path, known_images={"signed"})


def test_a_token_may_name_only_a_known_image_fact(tmp_path):
    path = _with(tmp_path, "manifest", 'forbid = ["LEN={primary.bl1_length}"]')
    with pytest.raises(ValueError, match="unknown image fact 'primary.bl1_length'"):
        load_testlist(path, known_images={"signed"})


def test_an_image_fact_needs_a_boot_image(tmp_path):
    path = tmp_path / "testlist.toml"
    for extra, message in (
        ('expect = ["LEN={primary.bl1_len}"]', "boots no image"),
        ('spi_reads = [{ name = "p", range = [0x0, "image_end"], min = 1 }]', "boots no image"),
    ):
        path.write_text(
            '[[testcase]]\nname = "a"\nfamily = "manifest"\nclassification = "vp-equivalent"\n'
            f'expect_verdict = "PASSED"\n{extra}\n'
        )
        with pytest.raises(ValueError, match=message):
            load_testlist(path)


def test_decrypt_pad_image_assert(tmp_path):
    path = _with(
        tmp_path,
        "encryption",
        'image_asserts = [{ decrypt_pad = { slot = "primary", valid = false } }]',
    )
    (case,) = load_testlist(path, known_images={"signed"})
    assert case.image_asserts[0].decrypt_pad == testlist_loader.DecryptPad("primary", False)


@pytest.mark.parametrize(
    "check, message",
    [
        ('{ decrypt_pad = { slot = "primary" } }', "exactly slot and valid"),
        ('{ decrypt_pad = { slot = "third", valid = false } }', "slot"),
        ('{ decrypt_pad = { slot = "primary", valid = 0 } }', "boolean"),
        ('{ range = [0, 4], decrypt_pad = { slot = "primary", valid = false } }', "range"),
        ('{ decrypt_pad = { slot = "primary", valid = false }, all = 0 }', "exactly one"),
    ],
)
def test_invalid_decrypt_pad_image_asserts_are_refused(tmp_path, check, message):
    path = _with(tmp_path, "encryption", f"image_asserts = [{check}]")
    with pytest.raises(ValueError, match=message):
        load_testlist(path, known_images={"signed"})
