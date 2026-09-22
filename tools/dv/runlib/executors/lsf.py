# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The LSF dialect: ``bsub``, ``bjobs -json``, ``bhist -l`` and ``bkill`` output.

The submission id comes from the ``Job <N> is submitted to queue <q>`` line on stdout and
from nothing else: site submission filters print on stderr, and stderr text is not a failure.
The live query is ``bjobs -json`` with named fields, so a record is a JSON object whose keys
are the requested field names in upper case; an id the cluster does not know comes back as
a record carrying an ``ERROR`` field, and the command's return code says nothing about that.
``bhist -l`` has no machine-readable form, so its parser reads the event lines of each job's
block. ``bkill`` answers one line per id, and its return code is not a signal either: a
finished job is refused with status 255 exactly like an unknown one.

A job array is ``-J name[1-N]``; its elements are ``<id>[<index>]`` to every command, and
``bjobs -o`` reports an element's index in ``JOBINDEX`` while ``JOBID`` may or may not carry
the bracket, so the query template must request ``jobindex`` and the parser composes the
element id from both. ``LSB_JOBINDEX`` is the element's index inside the job and ``%I`` in
an output path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from .base import JobObservation, JobState, now_iso
from .cluster import (
    CancelReply,
    CommandResult,
    QueryOutcome,
    SchedulerDialect,
    SubmitOutcome,
    base_job_id,
    whole_command_failed,
)

SUBMIT_RE = re.compile(r"^Job <(\d+)> is submitted to (?:default )?queue <([^>]+)>", re.MULTILINE)
# `STAT` values that map without an exit reason.
STATE_MAP = {
    "PEND": JobState.QUEUED,
    "WAIT": JobState.QUEUED,
    "PROV": JobState.QUEUED,
    "PSUSP": JobState.SUSPENDED,
    "USUSP": JobState.SUSPENDED,
    "SSUSP": JobState.SUSPENDED,
    "RUN": JobState.RUNNING,
    "STARTING": JobState.RUNNING,
    "DONE": JobState.SUCCEEDED,
    "UNKWN": JobState.RECONCILING,
    "ZOMBI": JobState.RECONCILING,
}
# An `EXIT` record's `TERM_*` reason, by the token that starts `EXIT_REASON`.
TERM_REASON_MAP = {
    "TERM_OWNER": JobState.CANCELLED,
    "TERM_ADMIN": JobState.CANCELLED,
    "TERM_FORCE_OWNER": JobState.CANCELLED,
    "TERM_FORCE_ADMIN": JobState.CANCELLED,
    "TERM_BUCKET_KILL": JobState.CANCELLED,
    "TERM_RUNLIMIT": JobState.TIMED_OUT,
    "TERM_CPULIMIT": JobState.TIMED_OUT,
    "TERM_DEADLINE": JobState.TIMED_OUT,
    "TERM_PREEMPT": JobState.PREEMPTED,
    "TERM_REQUEUE_OWNER": JobState.PREEMPTED,
    "TERM_REQUEUE_ADMIN": JobState.PREEMPTED,
    "TERM_RERUN": JobState.PREEMPTED,
    "TERM_WINDOW": JobState.PREEMPTED,
    "TERM_LOAD": JobState.PREEMPTED,
}
TERM_TOKEN_RE = re.compile(r"\b(TERM_[A-Z_]+)\b")
EXIT_CODE_RE = re.compile(r"Exited with exit code (\d+)")
EXIT_SIGNAL_RE = re.compile(r"Exited by signal (\d+)")
HISTORY_BLOCK_RE = re.compile(r"^Job <(\d+(?:\[\d+\])?)>,", re.MULTILINE)
NOT_FOUND_RE = re.compile(r"(?:Job <[\d\[\]]+>:? )?(?:is not found|No matching job found)")
KILL_LINE_RE = re.compile(r"^Job <(\d+(?:\[\d+\])?)>(?::)? (.+?)\.?$", re.MULTILINE)


def record_job_id(record: dict[str, object]) -> str:
    """The id a ``bjobs`` record describes: ``<id>[<index>]`` for an array element."""
    job_id = str(record.get("JOBID", "")).strip()
    index = str(record.get("JOBINDEX", "")).strip()
    if "[" not in job_id and index.isdigit() and int(index) > 0:
        return f"{job_id}[{index}]"
    return job_id


def exit_state(stat: str, reason: str) -> JobState:
    """The normalized state of one `EXIT` record from its `EXIT_REASON` text."""
    if stat != "EXIT":
        return STATE_MAP.get(stat, JobState.RUNNING)
    token = TERM_TOKEN_RE.search(reason or "")
    if token:
        return TERM_REASON_MAP.get(token.group(1), JobState.FAILED)
    return JobState.FAILED


class LsfDialect(SchedulerDialect):
    driver = "lsf"
    history_parsers = {"lsf_bhist_long": "parse_bhist_long"}
    array_index_env = "LSB_JOBINDEX"
    array_log_token = "%I"
    array_query_marker = "jobindex"

    def array_jobname(self, name: str, count: int) -> str:
        return f"{name}[1-{count}]"

    def element_id(self, array_id: str, index: int) -> str:
        return f"{array_id}[{index}]"

    def parse_submit(self, result: CommandResult) -> SubmitOutcome:
        match = SUBMIT_RE.search(result.stdout)
        if match:
            return SubmitOutcome(job_id=match.group(1), queue=match.group(2))
        return SubmitOutcome(error=result.failure_text)

    def parse_query(self, result: CommandResult, job_ids: Sequence[str]) -> QueryOutcome:
        text = result.stdout.strip()
        if not text.startswith("{"):
            if result.ok and not text and not result.stderr.strip():
                return QueryOutcome(missing=set(job_ids))
            return whole_command_failed(result, job_ids)
        data = json.loads(text)
        records = data.get("RECORDS") if isinstance(data, dict) else None
        if not isinstance(records, list):
            return whole_command_failed(result, job_ids)
        outcome = QueryOutcome()
        stamp = now_iso()
        asked = set(job_ids)
        for record in records:
            if not isinstance(record, dict):
                continue
            job_id = record_job_id(record)
            if job_id not in asked:
                job_id = base_job_id(job_id)
                if job_id not in asked:
                    continue
            if record.get("ERROR"):
                outcome.missing.add(job_id)
                continue
            outcome.observations[job_id] = record_observation(record, stamp)
        outcome.missing |= asked - set(outcome.observations) - outcome.missing
        return outcome

    def parse_bhist_long(self, result: CommandResult, job_ids: Sequence[str]) -> QueryOutcome:
        text = result.stdout
        starts = list(HISTORY_BLOCK_RE.finditer(text))
        if not starts:
            if NOT_FOUND_RE.search(text) or NOT_FOUND_RE.search(result.stderr):
                return QueryOutcome(missing=set(job_ids))
            if result.ok and not text.strip():
                return QueryOutcome(missing=set(job_ids))
            return whole_command_failed(result, job_ids)
        outcome = QueryOutcome()
        stamp = now_iso()
        asked = set(job_ids)
        for index, start in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
            job_id = start.group(1)
            if job_id not in asked:
                continue
            seen = history_observation(text[start.start() : end], stamp)
            if seen is not None:
                outcome.observations[job_id] = seen
        outcome.missing |= asked - set(outcome.observations)
        return outcome

    def parse_cancel(self, result: CommandResult, job_ids: Sequence[str]) -> dict[str, CancelReply]:
        replies: dict[str, CancelReply] = {}
        for text in (result.stdout, result.stderr):
            for match in KILL_LINE_RE.finditer(text):
                job_id, message = match.group(1), match.group(2).lower()
                if "already finished" in message or "has finished" in message:
                    replies[job_id] = CancelReply.FINISHED
                elif "no matching job" in message or "not found" in message:
                    replies[job_id] = CancelReply.UNKNOWN
                elif "terminated" in message or "in progress" in message or "signal" in message:
                    replies[job_id] = CancelReply.REQUESTED
        fallback = CancelReply.REQUESTED if result.ok else CancelReply.UNKNOWN
        for job_id in job_ids:
            replies.setdefault(job_id, fallback)
        return replies


def record_observation(record: dict[str, object], stamp: str) -> JobObservation:
    stat = str(record.get("STAT", "")).strip().upper()
    reason = str(record.get("EXIT_REASON") or record.get("PEND_REASON") or "").strip()
    code_text = str(record.get("EXIT_CODE") or "").strip()
    exit_code = int(code_text) if code_text.isdigit() else None
    state = exit_state(stat, reason)
    if state is JobState.SUCCEEDED and exit_code is None:
        exit_code = 0
    if stat not in STATE_MAP and stat != "EXIT":
        reason = f"unmapped LSF state {stat}" + (f"; {reason}" if reason else "")
    return JobObservation(
        state=state,
        exit_code=exit_code,
        reason=reason,
        observed_at=stamp,
        raw={str(key): value for key, value in record.items()},
    )


def history_observation(block: str, stamp: str) -> JobObservation | None:
    """The state one `bhist -l` block records, or None when the block says nothing usable."""
    token = TERM_TOKEN_RE.search(block)
    exit_code_match = EXIT_CODE_RE.search(block)
    exit_code = int(exit_code_match.group(1)) if exit_code_match else None
    if token:
        state = TERM_REASON_MAP.get(token.group(1), JobState.FAILED)
        return JobObservation(
            state=state, exit_code=exit_code, reason=token.group(1), observed_at=stamp
        )
    if "Done successfully" in block:
        return JobObservation(
            state=JobState.SUCCEEDED, exit_code=0, reason="Done successfully", observed_at=stamp
        )
    if exit_code_match:
        return JobObservation(
            state=JobState.FAILED,
            exit_code=exit_code,
            reason=exit_code_match.group(0),
            observed_at=stamp,
        )
    if "Signal <KILL>" in block or "Signal <TERM>" in block:
        return JobObservation(
            state=JobState.CANCELLED, reason="killed by request", observed_at=stamp
        )
    signal_match = EXIT_SIGNAL_RE.search(block)
    if signal_match:
        return JobObservation(
            state=JobState.FAILED, reason=signal_match.group(0), observed_at=stamp
        )
    if "Running with execution home" in block or "Starting (Pid" in block:
        return JobObservation(state=JobState.RUNNING, reason="history: running", observed_at=stamp)
    if "Submitted from host" in block:
        return JobObservation(state=JobState.QUEUED, reason="history: submitted", observed_at=stamp)
    return None


__all__ = [
    "EXIT_CODE_RE",
    "HISTORY_BLOCK_RE",
    "STATE_MAP",
    "SUBMIT_RE",
    "TERM_REASON_MAP",
    "LsfDialect",
    "exit_state",
    "history_observation",
    "record_job_id",
    "record_observation",
]
