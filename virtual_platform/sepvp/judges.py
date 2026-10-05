# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Pure post-run judges for SEP ROM console and status output."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sepvp.run_result import RunResult, StopReason

_VERDICT_PREFIX = "[VP] SIMULATION OF THE TEST "
_STATUS_RE = re.compile(
    r"^(?P<stage>\S+) +(?P<severity>\S+) +"
    r"0x(?P<code>[0-9a-fA-F]{4}) +SEP_MSG_\w+\s*$"
)
_TAGGED_CHANNEL_RE = re.compile(
    r"^(?:\[[^\]\r\n]+\]\s+){0,2}"
    r"\[(?P<channel>SIM_OUT|SEP_STATUS)\]\s+-\s+(?P<payload>.*)$"
)
_NOISE_PREFIXES = (
    "SystemC",
    "Accellera",
    "ALL RIGHTS RESERVED",
    "Copyright",
    "och_sep_ss1",
    "Setting:",
    "Argument received:",
    "CCI targets override",
    "CCI param name for Elf:",
    "CSML global log file",
    "RegLogger global log file:",
    "Info: och_sep_ss1.",
    "Veer ISS",
    "Loading ELF file",
    "Setting register ",
    "och_sep_ss:",
    "smc_global: staged ",
    "[init_writes]",
    "[spi_flash]",
    "/OSCI/",
)


_SPI_TAG = "[spi_flash]"
_SPI_READ_RE = re.compile(r"\[spi_flash\] Read @ 0x(?P<address>[0-9a-fA-F]+) len=(?P<length>\d+)$")
_SPI_BACKDOOR_RE = re.compile(r"\[spi_flash\] Backdoor: loaded (?P<size>\d+) bytes")

# The platform reports SMC SRAM staging itself; its failure paths only warn and carry on.
_SMC_TAG = "smc_global: staged "
_SMC_STAGED_RE = re.compile(
    r"smc_global: staged (?P<size>\d+) bytes .* at SMC SRAM offset 0x(?P<offset>[0-9a-fA-F]+)$"
)


class JudgeError(AssertionError):
    """The complete run does not satisfy its declared test contract."""


class UnjudgeableError(JudgeError):
    """The output lacks enough provenance to certify the assertion."""


@dataclass(frozen=True)
class SpiReadSpan:
    """A half-open flash address span and the read count the contract permits there."""

    name: str
    low: int
    high: int
    exact: int | None = None
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class SpiRead:
    address: int
    length: int


def _tagged_channel(line: str) -> tuple[str, str] | None:
    match = _TAGGED_CHANNEL_RE.fullmatch(line.strip())
    if match is None:
        return None
    return match.group("channel"), match.group("payload").strip()


def _status_payload(line: str, *, tagged_only: bool = False) -> str | None:
    stripped = line.strip()
    tagged = _tagged_channel(stripped)
    if tagged is not None:
        channel, payload = tagged
        return payload if channel == "SEP_STATUS" else None
    if tagged_only:
        return None
    return stripped if _STATUS_RE.fullmatch(stripped) else None


def _status_tokens(raw: str, *, tagged_only: bool) -> list[str]:
    tokens = []
    for line in raw.splitlines():
        payload = _status_payload(line, tagged_only=tagged_only)
        if payload is None:
            continue
        match = _STATUS_RE.fullmatch(payload)
        if match:
            tokens.append(f"{match.group('severity')} 0x{match.group('code').lower()}")
    return tokens


def status_tokens(raw: str) -> list[str]:
    """Return normalized ``SEVERITY 0xCODE`` status-ring entries."""
    return _status_tokens(raw, tagged_only=False)


def _console_tokens(
    raw: str,
    *,
    include_verdict: bool,
    tagged_only: bool = False,
) -> list[str]:
    tokens = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        tagged = _tagged_channel(stripped)
        if tagged is not None:
            channel, payload = tagged
            if channel == "SIM_OUT":
                tokens.append(payload)
            continue
        if _status_payload(stripped) is not None:
            continue
        if stripped.startswith(_VERDICT_PREFIX):
            if include_verdict:
                tokens.append(stripped)
            continue
        if stripped.startswith(_NOISE_PREFIXES):
            continue
        if stripped.startswith("[") and "]" in stripped:
            continue
        if not tagged_only:
            tokens.append(stripped)
    return tokens


def console_tokens(raw: str) -> list[str]:
    """Return firmware-console payloads, from tagged lines or bare output."""
    return _console_tokens(raw, include_verdict=False)


def _match_ordered(tokens: Sequence[str], expected: Sequence[str], label: str) -> None:
    position = 0
    for wanted in expected:
        while position < len(tokens) and tokens[position] != wanted:
            position += 1
        if position == len(tokens):
            raise JudgeError(f"expected {label} not found in order: {wanted!r}")
        position += 1


def _forbidden_hits(tokens: Sequence[str], forbidden: str) -> list[str]:
    # An entry ending in a value separator forbids that token with any value.
    if forbidden[-1:] in ("=", ":"):
        return [token for token in tokens if token.startswith(forbidden)]
    return [token for token in tokens if token == forbidden or token.startswith(f"{forbidden}=")]


# Entries a failure message quotes; enough to reach back to the slot attempt that ended the boot.
_TAIL_ENTRIES = 64


def _tail(entries: Sequence[str]) -> str:
    return " | ".join(entries[-_TAIL_ENTRIES:])


def _check_process(result: RunResult, expect_verdict: str | None = None) -> None:
    # Only a testcase that declares expect_verdict = "FAILED" may see a FAILED verdict.
    if result.firmware_verdict == "FAILED" and expect_verdict != "FAILED":
        tail = _tail(console_tokens(result.output))
        raise JudgeError(f"firmware reported FAILED; console tail: {tail}")
    if result.stop_reason is StopReason.SIMULATOR_CRASH:
        detail = (
            f"signal {result.signal}"
            if result.signal is not None
            else f"exit code {result.exit_code}"
        )
        raise JudgeError(f"simulator crashed with {detail}")
    if result.stop_reason is StopReason.PROCESS_EXIT:
        if result.exit_code != 0:
            raise JudgeError(f"simulator exited with exit code {result.exit_code}")
        if result.firmware_verdict is None:
            raise JudgeError("simulator exited before a firmware verdict (exit code 0)")


def _judge_verdict(result: RunResult, expect_verdict: str | None) -> None:
    if expect_verdict is None:
        return
    if expect_verdict == "none":
        if result.firmware_verdict is not None:
            raise JudgeError(
                f"testcase declared no terminal verdict, but firmware reported "
                f"{result.firmware_verdict}"
            )
        return
    if result.firmware_verdict is None:
        raise JudgeError(
            f"firmware published no terminal verdict; the contract requires {expect_verdict}"
        )
    if result.firmware_verdict != expect_verdict:
        raise JudgeError(
            f"firmware reported {result.firmware_verdict}, expected {expect_verdict}; "
            f"console tail: {_tail(console_tokens(result.output))}"
        )


def _judge_status_assertions(
    raw: str,
    expect_status: Sequence[str],
    forbid_status: Sequence[str],
) -> None:
    if not (expect_status or forbid_status):
        return
    statuses = status_tokens(raw)
    trusted_statuses = _status_tokens(raw, tagged_only=True)
    if not statuses:
        raise JudgeError("status channel produced no entries")
    if not trusted_statuses:
        raise UnjudgeableError("status channel has only bare output without SEP_STATUS provenance")
    for forbidden in forbid_status:
        if forbidden in statuses:
            raise JudgeError(
                f"forbidden status present: {forbidden!r}; status tail: {_tail(statuses)}"
            )
    try:
        _match_ordered(trusted_statuses, expect_status, "status")
    except JudgeError:
        try:
            _match_ordered(statuses, expect_status, "status")
        except JudgeError as error:
            raise JudgeError(f"{error}; status tail: {_tail(statuses)}") from None
        raise UnjudgeableError(
            "expected status sequence is present only in bare output without SEP_STATUS provenance"
        ) from None


def _spi_lines(raw: str) -> list[str]:
    """Model-emitted flash lines only; a tagged ``[SIM_OUT]`` payload is firmware text."""
    return [
        stripped for stripped in map(str.strip, raw.splitlines()) if stripped.startswith(_SPI_TAG)
    ]


def flash_reads(raw: str) -> list[SpiRead]:
    """Every read the flash model served, in the order it served them."""
    reads = []
    for line in _spi_lines(raw):
        match = _SPI_READ_RE.fullmatch(line)
        if match:
            reads.append(SpiRead(int(match.group("address"), 16), int(match.group("length"))))
    return reads


def flash_backdoor_bytes(raw: str) -> int | None:
    """Image size the flash model loaded, or None if it never reported a load."""
    for line in _spi_lines(raw):
        match = _SPI_BACKDOOR_RE.match(line)
        if match:
            return int(match.group("size"))
    return None


def _smc_lines(raw: str) -> list[str]:
    """Model-emitted SMC staging lines only; a tagged ``[SIM_OUT]`` payload is firmware text."""
    return [
        stripped for stripped in map(str.strip, raw.splitlines()) if stripped.startswith(_SMC_TAG)
    ]


def smc_sram_staged(raw: str) -> tuple[int, int] | None:
    """Bytes and SMC-SRAM offset the platform reported staging, or None if it never did."""
    for line in _smc_lines(raw):
        match = _SMC_STAGED_RE.fullmatch(line)
        if match:
            return int(match.group("size")), int(match.group("offset"), 16)
    return None


def _judge_smc_sram(raw: str, expected: tuple[int, int] | None) -> None:
    """Require the exact SMC SRAM staging the testcase declared, before any manifest claim."""
    if expected is None:
        return
    size, offset = expected
    staged = smc_sram_staged(raw)
    if staged is None:
        raise JudgeError(
            "platform reported no SMC SRAM staging; the boot handshake publishes a "
            "MANIFEST_ADDR either way, so the ROM would read an erased window and every "
            "manifest assertion here would hold for that reason instead of the declared one"
        )
    if staged != (size, offset):
        raise JudgeError(
            f"platform staged {staged[0]} bytes at SMC SRAM offset 0x{staged[1]:x}; the "
            f"testcase declared {size} bytes at 0x{offset:x}"
        )


def _span_count_error(span: SpiReadSpan, label: str, wanted: int, count: int) -> str:
    return (
        f"span {span.name} [0x{span.low:x},0x{span.high:x}): expected {label} "
        f"{wanted} read(s), device served {count}"
    )


def _judge_spi_reads(
    raw: str,
    spans: Sequence[SpiReadSpan],
    order: Sequence[str],
) -> None:
    if not (spans or order):
        return
    if order and not spans:
        raise JudgeError("spi_read_order needs spi_reads; it orders spans by name")

    loaded = flash_backdoor_bytes(raw)
    if not loaded:
        held = "no" if loaded is None else "0 bytes of"
        raise JudgeError(
            f"flash model reported {held} backdoor load; the device served no image, "
            "so no read assertion — least of all an exact-0 one — is meaningful"
        )

    served: dict[str, int] = {span.name: 0 for span in spans}
    first_touch: dict[str, int] = {}
    for index, read in enumerate(flash_reads(raw)):
        span = next((s for s in spans if s.low <= read.address < s.high), None)
        if span is None:
            raise JudgeError(
                f"read @0x{read.address:x} len={read.length} falls outside every "
                "declared span; the testlist does not describe where this ROM reads"
            )
        if read.address + read.length > span.high:
            raise JudgeError(
                f"read @0x{read.address:x} len={read.length} starts in span "
                f"{span.name!r} but ends past its top — the declared bounds do not "
                "match how the ROM chunks its transfers"
            )
        served[span.name] += 1
        first_touch.setdefault(span.name, index)

    for span in spans:
        count = served[span.name]
        if span.exact is not None and count != span.exact:
            raise JudgeError(_span_count_error(span, "exactly", span.exact, count))
        if span.minimum is not None and count < span.minimum:
            raise JudgeError(_span_count_error(span, "at least", span.minimum, count))
        if span.maximum is not None and count > span.maximum:
            raise JudgeError(_span_count_error(span, "at most", span.maximum, count))

    positions = []
    for name in order:
        if name not in first_touch:
            raise JudgeError(
                f"spi_read_order names span {name!r}, but the device served no read there"
            )
        positions.append(first_touch[name])
    for index in range(1, len(positions)):
        if positions[index - 1] >= positions[index]:
            raise JudgeError(
                f"device read {order[index]!r} before {order[index - 1]!r}; "
                "required order is " + " -> ".join(order)
            )


def judge(
    result: RunResult,
    *,
    expect: Sequence[str] = (),
    forbid: Sequence[str] = (),
    expect_counts: Mapping[str, int] | None = None,
    terminal_token: str | None = None,
    expect_silence: bool = False,
    liveness: Sequence[str] = (),
    expect_status: Sequence[str] = (),
    forbid_status: Sequence[str] = (),
    spi_reads: Sequence[SpiReadSpan] = (),
    spi_read_order: Sequence[str] = (),
    expect_verdict: str | None = None,
    smc_sram: tuple[int, int] | None = None,
) -> None:
    """Raise :class:`JudgeError` unless the complete run satisfies the contract."""
    _check_process(result, expect_verdict)
    _judge_verdict(result, expect_verdict)
    # A pre-boot deposit the model never applied would leave the run judging an unseeded boot.
    lines = {line.strip() for line in result.output.splitlines()}
    missing = [witness for witness in liveness if witness not in lines]
    if missing:
        raise JudgeError(f"missing liveness witness: {missing[0]!r}")
    _judge_smc_sram(result.output, smc_sram)
    tokens = console_tokens(result.output)
    contract_tokens = _console_tokens(result.output, include_verdict=True)
    trusted_tokens = _console_tokens(
        result.output,
        include_verdict=True,
        tagged_only=True,
    )
    trusted_console = _console_tokens(
        result.output,
        include_verdict=False,
        tagged_only=True,
    )
    _judge_status_assertions(result.output, expect_status, forbid_status)

    if expect_silence:
        if expect:
            raise JudgeError("expect_silence and expect are contradictory")
        if not forbid:
            raise JudgeError("expect_silence requires at least one forbidden token")
        if not liveness:
            raise JudgeError("expect_silence requires at least one liveness witness")
        if not result.timed_out:
            raise JudgeError("expect_silence must end at the run timeout")
        for forbidden in forbid:
            hits = _forbidden_hits(contract_tokens, forbidden)
            if hits:
                raise JudgeError(f"forbidden token present: {hits[0]!r}")
        if tokens:
            raise JudgeError(f"expected firmware silence, first token was {tokens[0]!r}")
        _judge_spi_reads(result.output, spi_reads, spi_read_order)
        return

    if not expect:
        raise JudgeError("testcase declares no expected console token")

    for forbidden in forbid:
        hits = _forbidden_hits(contract_tokens, forbidden)
        if hits:
            raise JudgeError(f"forbidden token present: {hits[0]!r}")
    for wanted in expect:
        if wanted in contract_tokens:
            continue
        valued = next(
            (token for token in contract_tokens if token.startswith(f"{wanted}=")),
            None,
        )
        if valued is not None:
            raise JudgeError(
                f"expected token {wanted!r} is a bare prefix; assert its value "
                f"explicitly, for example {valued!r}"
            )
    try:
        _match_ordered(trusted_tokens, expect, "token")
    except JudgeError:
        try:
            _match_ordered(contract_tokens, expect, "token")
        except JudgeError:
            raise
        raise UnjudgeableError(
            "expected sequence is present only in bare output without SIM_OUT provenance"
        ) from None

    for token, wanted in (expect_counts or {}).items():
        actual = tokens.count(token)
        if actual != wanted:
            raise JudgeError(
                f"token {token!r} appeared {actual} time(s), expected exactly {wanted}"
            )
        if trusted_console.count(token) != wanted:
            raise UnjudgeableError(
                f"exact count for {token!r} depends on bare output without SIM_OUT provenance"
            )

    if terminal_token is not None:
        if not (result.timed_out or result.firmware_verdict is not None):
            raise JudgeError("cannot judge terminal silence after an incomplete or crashed run")
        if terminal_token not in tokens:
            raise JudgeError(f"terminal token never appeared: {terminal_token!r}")
        terminal_position = len(tokens) - 1 - tokens[::-1].index(terminal_token)
        if terminal_position != len(tokens) - 1:
            raise JudgeError(
                f"firmware emitted {tokens[terminal_position + 1]!r} after terminal "
                f"token {terminal_token!r}"
            )
        if terminal_token not in trusted_console:
            raise UnjudgeableError(
                f"terminal token {terminal_token!r} is present only in bare output "
                "without SIM_OUT provenance"
            )

    # Device witness runs last so a console disagreement is reported first.
    _judge_spi_reads(result.output, spi_reads, spi_read_order)
