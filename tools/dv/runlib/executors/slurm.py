# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The Slurm dialect: ``sbatch --parsable``, ``squeue``, ``sacct``, ``scontrol`` and ``scancel``.

``sbatch --parsable`` prints the bare job id, with ``;<cluster>`` appended on a federated
site. ``squeue`` lists live jobs as ``id|STATE|reason`` lines when asked with that format; a
job the controller has dropped makes the command fail with ``Invalid job id specified``,
and since a finished job leaves the controller after ``MinJobAge``, that failure is the
ordinary way a job is missing rather than an error. A batched query that fails for that reason
is therefore retried one id at a time. ``sacct`` (with accounting) and ``scontrol show job``
(inside ``MinJobAge``) are the two history sources, selected by ``history_parser``.
``scancel`` exits 0 whatever the ids were, and names an unknown id only on stderr.

A job array is ``--array=1-N``; ``sbatch --parsable`` prints the array's id and every
element is ``<id>_<index>`` to every command. ``squeue %i`` prints that form per element
(``--array`` keeps pending elements from folding into ``<id>_[2-4]``), ``sacct``'s ``JobID``
prints it too, and ``scontrol show job`` gives the element its own ``JobId`` beside
``ArrayJobId`` and ``ArrayTaskId``. ``SLURM_ARRAY_TASK_ID`` is the element's index inside
the job and ``%a`` in an output path.
"""

from __future__ import annotations

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

SUBMIT_RE = re.compile(r"^(\d+)(?:;(\S+))?\s*$", re.MULTILINE)
SUBMIT_VERBOSE_RE = re.compile(r"Submitted batch job (\d+)(?: on cluster (\S+))?")
INVALID_JOB_RE = re.compile(r"Invalid job id specified", re.IGNORECASE)
ACCOUNTING_OFF_RE = re.compile(r"accounting storage is disabled", re.IGNORECASE)
SCONTROL_FIELD_RE = re.compile(r"\b(JobId|JobState|ExitCode|Reason|ArrayJobId|ArrayTaskId)=(\S+)")
SCANCEL_ERROR_RE = re.compile(r"job id (\d+(?:_\d+)?):\s*(.+)$", re.MULTILINE)
FOLDED_ARRAY_RE = re.compile(r"^(\d+)_\[([^\]]+)\]$")


def expand_job_id(text: str) -> list[str]:
    """The ids one ``squeue`` id field names: itself, or every element of a folded range."""
    token = text.strip().split(";")[0]
    folded = FOLDED_ARRAY_RE.match(token)
    if not folded:
        return [token]
    array_id, spec = folded.groups()
    out: list[str] = []
    for part in spec.split("%")[0].split(","):
        low, _, high = part.partition("-")
        if not low.strip().isdigit():
            continue
        start = int(low)
        stop = int(high) if high.strip().isdigit() else start
        out.extend(f"{array_id}_{index}" for index in range(start, stop + 1))
    return out


def scontrol_job_id(fields: dict[str, str]) -> str:
    """The element id of one ``scontrol show job`` block, or its plain id."""
    array_id = fields.get("ArrayJobId", "")
    task_id = fields.get("ArrayTaskId", "")
    if array_id.isdigit() and task_id.isdigit():
        return f"{array_id}_{task_id}"
    return base_job_id(fields.get("JobId", ""))


STATE_MAP = {
    "PENDING": JobState.QUEUED,
    "CONFIGURING": JobState.QUEUED,
    "REQUEUE_HOLD": JobState.QUEUED,
    "REQUEUE_FED": JobState.QUEUED,
    "RESV_DEL_HOLD": JobState.QUEUED,
    "RUNNING": JobState.RUNNING,
    "COMPLETING": JobState.RUNNING,
    "SIGNALING": JobState.RUNNING,
    "STAGE_OUT": JobState.RUNNING,
    "RESIZING": JobState.RUNNING,
    "SUSPENDED": JobState.SUSPENDED,
    "STOPPED": JobState.SUSPENDED,
    "COMPLETED": JobState.SUCCEEDED,
    "FAILED": JobState.FAILED,
    "NODE_FAIL": JobState.FAILED,
    "OUT_OF_MEMORY": JobState.FAILED,
    "BOOT_FAIL": JobState.FAILED,
    "DEADLINE": JobState.FAILED,
    "REVOKED": JobState.FAILED,
    "SPECIAL_EXIT": JobState.FAILED,
    "TIMEOUT": JobState.TIMED_OUT,
    "CANCELLED": JobState.CANCELLED,
    "PREEMPTED": JobState.PREEMPTED,
    "REQUEUED": JobState.PREEMPTED,
}


def state_observation(
    state_text: str, exit_text: str, reason: str, stamp: str, raw: dict[str, object]
) -> JobObservation:
    """One normalized observation from Slurm's state name, ``code:signal`` and reason text."""
    token = state_text.strip().split()[0].upper() if state_text.strip() else ""
    state = STATE_MAP.get(token, JobState.RUNNING)
    exit_code: int | None = None
    detail = reason.strip()
    if exit_text:
        code, _, signal = exit_text.strip().partition(":")
        if code.isdigit():
            exit_code = int(code)
        if signal.isdigit() and int(signal) and exit_code in (0, None):
            detail = f"signal {signal}" + (f"; {detail}" if detail else "")
    if state is JobState.SUCCEEDED and exit_code is None:
        exit_code = 0
    if token not in STATE_MAP:
        detail = f"unmapped Slurm state {token}" + (f"; {detail}" if detail else "")
    elif state_text.strip() != token:
        detail = state_text.strip() + (f"; {detail}" if detail else "")
    return JobObservation(
        state=state, exit_code=exit_code, reason=detail, observed_at=stamp, raw=raw
    )


class SlurmDialect(SchedulerDialect):
    driver = "slurm"
    history_parsers = {"slurm_sacct": "parse_sacct", "slurm_scontrol": "parse_scontrol"}
    retry_failed_query_per_id = True
    array_index_env = "SLURM_ARRAY_TASK_ID"
    array_log_token = "%a"
    array_range_placeholder = "array_range"

    def element_id(self, array_id: str, index: int) -> str:
        return f"{array_id}_{index}"

    def parse_submit(self, result: CommandResult) -> SubmitOutcome:
        if not result.ok:
            return SubmitOutcome(error=result.failure_text)
        match = SUBMIT_RE.search(result.stdout) or SUBMIT_VERBOSE_RE.search(result.stdout)
        if match:
            return SubmitOutcome(job_id=match.group(1), cluster=match.group(2))
        return SubmitOutcome(error=result.failure_text or "no job id in sbatch output")

    def parse_query(self, result: CommandResult, job_ids: Sequence[str]) -> QueryOutcome:
        if not result.ok:
            if INVALID_JOB_RE.search(result.stderr) and len(job_ids) == 1:
                return QueryOutcome(missing=set(job_ids))
            return whole_command_failed(result, job_ids)
        outcome = QueryOutcome()
        stamp = now_iso()
        asked = set(job_ids)
        for line in result.stdout.splitlines():
            fields = line.strip().split("|")
            if len(fields) < 2 or not fields[0]:
                continue
            reason = fields[2] if len(fields) > 2 and fields[2] not in {"None", "(null)"} else ""
            for job_id in expand_job_id(fields[0]):
                if job_id not in asked:
                    job_id = base_job_id(job_id)
                    if job_id not in asked:
                        continue
                outcome.observations[job_id] = state_observation(
                    fields[1], "", reason, stamp, {"line": line.strip()}
                )
        outcome.missing |= asked - set(outcome.observations)
        return outcome

    def parse_sacct(self, result: CommandResult, job_ids: Sequence[str]) -> QueryOutcome:
        if not result.ok:
            return whole_command_failed(result, job_ids)
        outcome = QueryOutcome()
        stamp = now_iso()
        asked = set(job_ids)
        for line in result.stdout.splitlines():
            fields = line.strip().split("|")
            if len(fields) < 2 or not fields[0]:
                continue
            # `--allocations` leaves one line per job; a step line names a sub-id and loses.
            if "." in fields[0]:
                continue
            job_id = fields[0].strip()
            if job_id not in asked:
                job_id = base_job_id(job_id)
                if job_id not in asked:
                    continue
            exit_text = fields[2] if len(fields) > 2 else ""
            outcome.observations[job_id] = state_observation(
                fields[1], exit_text, "", stamp, {"line": line.strip()}
            )
        outcome.missing |= asked - set(outcome.observations)
        return outcome

    def parse_scontrol(self, result: CommandResult, job_ids: Sequence[str]) -> QueryOutcome:
        if not result.ok:
            if INVALID_JOB_RE.search(result.stderr) or INVALID_JOB_RE.search(result.stdout):
                return QueryOutcome(missing=set(job_ids))
            return whole_command_failed(result, job_ids)
        outcome = QueryOutcome()
        stamp = now_iso()
        asked = set(job_ids)
        for block in re.split(r"\n\s*\n", result.stdout.strip()):
            fields = {key: value for key, value in SCONTROL_FIELD_RE.findall(block)}
            job_id = scontrol_job_id(fields)
            if job_id not in asked or "JobState" not in fields:
                continue
            reason = fields.get("Reason", "")
            outcome.observations[job_id] = state_observation(
                fields["JobState"],
                fields.get("ExitCode", ""),
                "" if reason in {"None", "(null)"} else reason,
                stamp,
                dict(fields),
            )
        outcome.missing |= asked - set(outcome.observations)
        return outcome

    def parse_cancel(self, result: CommandResult, job_ids: Sequence[str]) -> dict[str, CancelReply]:
        replies: dict[str, CancelReply] = {}
        for match in SCANCEL_ERROR_RE.finditer(result.stderr):
            job_id, message = match.group(1), match.group(2).lower()
            if "invalid job id" in message:
                replies[job_id] = CancelReply.UNKNOWN
            elif "already" in message and ("complete" in message or "finish" in message):
                replies[job_id] = CancelReply.FINISHED
        fallback = CancelReply.REQUESTED if result.ok else CancelReply.UNKNOWN
        for job_id in job_ids:
            replies.setdefault(job_id, fallback)
        return replies


__all__ = [
    "ACCOUNTING_OFF_RE",
    "INVALID_JOB_RE",
    "STATE_MAP",
    "SUBMIT_RE",
    "SlurmDialect",
    "expand_job_id",
    "scontrol_job_id",
    "state_observation",
]
