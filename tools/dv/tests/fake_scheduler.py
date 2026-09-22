# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""A scheduler stand-in that answers as LSF or Slurm would, driven by a scenario file.

Installed as ``bsub``, ``bjobs``, ``bhist``, ``bkill``, ``sbatch``, ``squeue``, ``sacct``,
``scontrol`` and ``scancel`` in a directory the test puts on ``PATH``, it keeps its jobs in
``$OCAH_FAKE_SCHEDULER/jobs.json`` and reads ``$OCAH_FAKE_SCHEDULER/scenario.json`` for
what to do. Time is the sequence of query calls: every live query advances each job one step
through its scripted state list, and a job entering ``RUN`` runs its submitted script right
then, so the leaf's result appears exactly when a real worker would have written it.

The output shapes are the ones the production schedulers were observed to print, including
the ones a driver must not misread: the submission filter's stderr banner in both its shapes
(with and without a memory request), the ``ERROR``
record ``bjobs -json`` returns for an unknown id, ``bkill``'s status 255 for a job that has
already finished, ``squeue``'s failure for an id the controller dropped, ``scancel``'s
success for anything at all.

A job array (``-J name[1-N]`` or ``--array=1-N``) becomes one element job per index, keyed
``<id>[<index>]`` for LSF and ``<id>_<index>`` for Slurm, each running the submitted script
with ``LSB_JOBINDEX`` or ``SLURM_ARRAY_TASK_ID`` set and the output path's ``%I``/``%a``
expanded; a bare array id in a query or kill names every element.

Scenario keys (all optional)::

    submit:  fail_calls [n...]  reject_queue "name"  stderr_noise bool  verbose_id bool
    query:   fail_calls [n...]  hang_calls [n...]  hang_sec float  strict_multi_id bool
             min_job_age_queries int  jobid_with_index bool
    history: fail_calls [n...]  unavailable bool
    cancel:  fail_calls [n...]
    jobs:    {"default": profile, "<job-name-substring>": profile}

A profile holds ``states`` (a list of ``PEND``, ``RUN``, ``SUSP``, ``DONE``, ``AUTO``,
``EXIT:<code>``, ``TIMEOUT``, ``KILLED``, ``PREEMPTED``, ``MEMLIMIT``, ``UNKWN``, ``VANISH``),
``run_script`` (default true), ``history`` (``auto``, ``none`` or one of the terminal tokens),
``ignore_kill`` and ``unknown_to_kill``. ``AUTO`` is ``DONE`` when the script exited 0 and
``EXIT:<code>`` otherwise. A profile key matches a job name by substring; an array element's
name is ``<name>[<index>]``. Call indexes in ``fail_calls`` and ``hang_calls`` count from 1
per command family.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ARRAY_NAME_RE = re.compile(r"^(.*)\[(\d+)-(\d+)(?:%\d+)?\]$")
ARRAY_RANGE_RE = re.compile(r"^(\d+)-(\d+)(?:%\d+)?$")
JOB_ID_RE = re.compile(r"^\d+(?:\[\d+\]|_\d+)?$")

COMMANDS = {
    "bsub": ("lsf", "submit"),
    "bjobs": ("lsf", "query"),
    "bhist": ("lsf", "history"),
    "bkill": ("lsf", "cancel"),
    "sbatch": ("slurm", "submit"),
    "squeue": ("slurm", "query"),
    "sacct": ("slurm", "history"),
    "scontrol": ("slurm", "history"),
    "scancel": ("slurm", "cancel"),
}
TERMINAL = {"DONE", "TIMEOUT", "KILLED", "PREEMPTED", "MEMLIMIT"}
ESUB_NOISE = "*** INFO *** Setting a memory hard limit of 32G"
ESUB_NOISE_UNSIZED = (
    "*** WARNING *** No memory usage or limits specified - setting memory hard limit to 32G"
)
LSF_STAMP = "Sat Sep 20 12:00:0{step}: "


def install(bin_dir: Path, python: str = sys.executable) -> None:
    """Write one wrapper per scheduler command into ``bin_dir``."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in COMMANDS:
        wrapper = bin_dir / name
        wrapper.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(python)} {shlex.quote(str(Path(__file__).resolve()))} "
            f'{name} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)


class Fake:
    def __init__(self, state_dir: Path) -> None:
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        scenario_path = self.dir / "scenario.json"
        self.scenario: dict[str, Any] = (
            json.loads(scenario_path.read_text(encoding="utf-8")) if scenario_path.is_file() else {}
        )
        self.path = self.dir / "jobs.json"
        if self.path.is_file():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.state = {
                "next_id": int(self.scenario.get("start_id", 1001)),
                "jobs": {},
                "calls": {},
            }

    def save(self) -> None:
        # A command the executor kills mid-write must leave the previous state readable.
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(self.state, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    def record_call(self, command: str, argv: list[str], family: str) -> int:
        calls = self.state["calls"]
        calls[family] = int(calls.get(family, 0)) + 1
        with (self.dir / "calls.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"command": command, "argv": argv, "n": calls[family]}) + "\n")
        # A call that hangs past the executor's timeout is killed before it can save.
        self.save()
        return int(calls[family])

    def knob(self, family: str, key: str, default: Any = None) -> Any:
        table = self.scenario.get(family) or {}
        return table.get(key, default)

    # -- jobs ----------------------------------------------------------------------------

    def profile(self, name: str) -> dict[str, Any]:
        profiles = self.scenario.get("jobs") or {}
        for key, profile in profiles.items():
            if key != "default" and key in name:
                return dict(profile)
        return dict(profiles.get("default") or {"states": ["PEND", "RUN", "AUTO"]})

    def submit(self, argv: list[str], driver: str) -> tuple[int, str, str]:
        call = self.record_call("bsub" if driver == "lsf" else "sbatch", argv, "submit")
        options = parse_options(argv)
        queue = options.get("queue")
        if call in (self.knob("submit", "fail_calls") or []):
            if driver == "lsf":
                return 255, "", "Request from non-LSF host rejected. Job not submitted.\n"
            return 1, "", "sbatch: error: Batch job submission failed: Socket timed out\n"
        if queue and queue == self.knob("submit", "reject_queue"):
            if driver == "lsf":
                return 255, "", f"{queue}: User cannot use the queue. Job not submitted.\n"
            return (
                1,
                "",
                f"sbatch: error: invalid partition specified: {queue}\n"
                "sbatch: error: Batch job submission failed: Invalid partition name specified\n",
            )
        job_id = str(self.state["next_id"])
        self.state["next_id"] += 1
        name = options.get("name") or f"job{job_id}"
        array = options.get("array")
        if array is None:
            elements = [(job_id, name, None)]
        else:
            first, last = (int(part) for part in array.split("-"))
            elements = [
                (
                    f"{job_id}[{index}]" if driver == "lsf" else f"{job_id}_{index}",
                    f"{name}[{index}]",
                    index,
                )
                for index in range(first, last + 1)
            ]
        for key, element_name, index in elements:
            self.state["jobs"][key] = {
                "id": key,
                "name": element_name,
                "queue": queue,
                "script": options.get("script"),
                "out": options.get("out"),
                "argv": argv,
                "profile": self.profile(element_name),
                "step": 0,
                "killed": False,
                "ran": False,
                "script_rc": None,
                "terminal_queries": 0,
                "array": None if index is None else {"id": job_id, "index": index},
            }
        stderr = ""
        if self.knob("submit", "stderr_noise"):
            sized = any("rusage[mem=" in token or token.startswith("--mem") for token in argv)
            stderr = f"{ESUB_NOISE if sized else ESUB_NOISE_UNSIZED}\n"
        if driver == "lsf":
            shown = f"queue <{queue}>" if queue else "default queue <normal>"
            return 0, f"Job <{job_id}> is submitted to {shown}.\n", stderr
        if self.knob("submit", "verbose_id") or "--parsable" not in argv:
            return 0, f"Submitted batch job {job_id}\n", stderr
        return 0, f"{job_id}\n", stderr

    def advance_all(self) -> None:
        for job in self.state["jobs"].values():
            states = job["profile"].get("states") or ["PEND", "RUN", "AUTO"]
            if job["step"] < len(states) - 1:
                job["step"] += 1
            self.materialize(job)

    def materialize(self, job: dict[str, Any]) -> None:
        """Run the script when the job first reaches RUN; count queries spent terminal."""
        states = job["profile"].get("states") or ["PEND", "RUN", "AUTO"]
        token = states[min(job["step"], len(states) - 1)]
        if token == "RUN" and not job["ran"] and job["profile"].get("run_script", True):
            job["ran"] = True
            job["script_rc"] = self.run_script(job)
        if is_terminal(self.token_of(job)) or self.token_of(job) == "VANISH":
            job["terminal_queries"] = int(job.get("terminal_queries", 0)) + 1

    def run_script(self, job: dict[str, Any]) -> int | None:
        script = job.get("script")
        if not script:
            return None
        out_text = str(job.get("out") or self.dir / f"{job['id']}.out")
        array = job.get("array")
        if array:
            index = str(array["index"])
            for token, value in (
                ("%I", index),
                ("%a", index),
                ("%J", array["id"]),
                ("%A", array["id"]),
                ("%j", array["id"]),
            ):
                out_text = out_text.replace(token, value)
        out = Path(out_text.replace("%J", job["id"]).replace("%j", job["id"]))
        out.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["FAKE_JOB_ID"] = job["id"]
        if array:
            env["LSB_JOBID"] = env["SLURM_ARRAY_JOB_ID"] = array["id"]
            env["LSB_JOBINDEX"] = env["SLURM_ARRAY_TASK_ID"] = str(array["index"])
        with out.open("a", encoding="utf-8") as log:
            proc = subprocess.run(
                ["/bin/sh", script],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                check=False,
            )
        return proc.returncode

    def token_of(self, job: dict[str, Any]) -> str:
        """The scripted state the job shows right now, after kills and AUTO resolution."""
        states = job["profile"].get("states") or ["PEND", "RUN", "AUTO"]
        token = str(states[min(job["step"], len(states) - 1)])
        if job["killed"] and not job["profile"].get("ignore_kill") and token != "VANISH":
            return "KILLED"
        if token == "AUTO":
            rc = job.get("script_rc")
            if rc is None:
                return "RUN"
            return "DONE" if rc == 0 else f"EXIT:{rc}"
        return token

    def exit_code(self, job: dict[str, Any], token: str) -> int | None:
        if token.startswith("EXIT:"):
            return int(token.split(":", 1)[1])
        if token == "DONE":
            return 0
        return None

    def history_token(self, job: dict[str, Any]) -> str | None:
        wanted = job["profile"].get("history", "auto")
        if wanted == "none":
            return None
        if wanted != "auto":
            return str(wanted)
        token = self.token_of(job)
        if token == "VANISH":
            # The scheduler forgot the job before it ended: history knows only what happened.
            if job["killed"]:
                return "KILLED"
            rc = job.get("script_rc")
            if rc is None:
                return "RUN" if job["ran"] else "PEND"
            return "DONE" if rc == 0 else f"EXIT:{rc}"
        return token

    # -- query -----------------------------------------------------------------------------

    def query(self, argv: list[str], driver: str) -> tuple[int, str, str]:
        call = self.record_call("bjobs" if driver == "lsf" else "squeue", argv, "query")
        if call in (self.knob("query", "hang_calls") or []):
            time.sleep(float(self.knob("query", "hang_sec", 3.0)))
        if call in (self.knob("query", "fail_calls") or []):
            self.save()
            if driver == "lsf":
                return 255, "", "LSF is down. Please wait ...\n"
            return (
                1,
                "",
                "slurm_load_jobs error: Unable to contact slurm controller (connect failure)\n",
            )
        if self.knob("query", "advance", True):
            self.advance_all()
        ids = expand_ids(self.state["jobs"], parse_ids(argv, driver))
        return (
            self.render_query_lsf(argv, ids) if driver == "lsf" else self.render_squeue(argv, ids)
        )

    def render_query_lsf(self, argv: list[str], ids: list[str]) -> tuple[int, str, str]:
        fields = ["JOBID", "STAT", "EXIT_CODE", "EXIT_REASON"]
        if "-o" in argv:
            fields = [name.upper() for name in argv[argv.index("-o") + 1].split()]
        records = []
        for job_id in ids:
            job = self.state["jobs"].get(job_id)
            token = self.token_of(job) if job else "VANISH"
            if job is None or token == "VANISH":
                records.append({"JOBID": job_id, "ERROR": f"Job <{job_id}> is not found"})
                continue
            stat, reason = lsf_state(token)
            code = self.exit_code(job, token)
            array = job.get("array")
            shown_id = job_id
            if array and not self.knob("query", "jobid_with_index"):
                shown_id = array["id"]
            values = {
                "JOBID": shown_id,
                "JOBINDEX": str(array["index"]) if array else "0",
                "STAT": stat,
                "EXIT_CODE": "" if code in (None, 0) else str(code),
                "EXIT_REASON": reason,
                "PEND_REASON": "New job is waiting for scheduling;" if stat == "PEND" else "",
                "JOB_NAME": job["name"],
                "QUEUE": job.get("queue") or "normal",
            }
            records.append({name: values.get(name, "") for name in fields})
        if "-json" not in argv:
            body = "\n".join(f"{r.get('JOBID')} {r.get('STAT', 'ERROR')}" for r in records)
            return 0, body + "\n", ""
        return 0, json.dumps({"COMMAND": "bjobs", "JOBS": len(records), "RECORDS": records}), ""

    def render_squeue(self, argv: list[str], ids: list[str]) -> tuple[int, str, str]:
        all_states = "--states=all" in argv or (
            "-t" in argv and argv[argv.index("-t") + 1 :][:1] == ["all"]
        )
        min_age = int(self.knob("query", "min_job_age_queries", 2))
        lines = []
        unknown = []
        for job_id in ids:
            job = self.state["jobs"].get(job_id)
            token = self.token_of(job) if job else "VANISH"
            if job is None or token == "VANISH":
                unknown.append(job_id)
                continue
            if is_terminal(token) and (not all_states or job.get("terminal_queries", 0) > min_age):
                unknown.append(job_id)
                continue
            state, reason = slurm_state(token)
            lines.append(f"{job_id}|{state}|{reason}")
        if unknown and (len(ids) == 1 or self.knob("query", "strict_multi_id")):
            return 1, "", "slurm_load_jobs error: Invalid job id specified\n"
        return 0, "".join(line + "\n" for line in lines), ""

    # -- history ---------------------------------------------------------------------------

    def history(self, command: str, argv: list[str], driver: str) -> tuple[int, str, str]:
        call = self.record_call(command, argv, "history")
        if call in (self.knob("history", "fail_calls") or []):
            if driver == "lsf":
                return (
                    255,
                    "",
                    "Failed in an LSF library call: Slave LIM configuration is not ready yet\n",
                )
            return 1, "", "sacct: error: Problem talking to the database: Connection refused\n"
        if driver == "lsf":
            return self.render_bhist(argv)
        if command == "scontrol":
            return self.render_scontrol(argv)
        return self.render_sacct(argv)

    def render_bhist(self, argv: list[str]) -> tuple[int, str, str]:
        blocks = []
        for job_id in expand_ids(self.state["jobs"], parse_ids(argv, "lsf")):
            job = self.state["jobs"].get(job_id)
            token = self.history_token(job) if job else None
            if job is None or token is None:
                continue
            blocks.append(bhist_block(job, token))
        if not blocks:
            return 255, "No matching job found\n", ""
        return 0, "\n".join(blocks), ""

    def render_sacct(self, argv: list[str]) -> tuple[int, str, str]:
        if self.knob("history", "unavailable"):
            return 1, "", "sacct: error: Slurm accounting storage is disabled\n"
        lines = []
        for job_id in expand_ids(self.state["jobs"], parse_ids(argv, "slurm")):
            job = self.state["jobs"].get(job_id)
            token = self.history_token(job) if job else None
            if job is None or token is None or token in {"PEND"}:
                continue
            state, _reason = slurm_state(token)
            code = self.exit_code(job, token) or 0
            signal = 15 if token == "KILLED" else 0
            shown = "CANCELLED by 1000" if token == "KILLED" else state
            lines.append(f"{job_id}|{shown}|{code}:{signal}")
            lines.append(f"{job_id}.batch|{state}|{code}:{signal}")
        return 0, "".join(line + "\n" for line in lines), ""

    def render_scontrol(self, argv: list[str]) -> tuple[int, str, str]:
        job_id = argv[-1]
        job = self.state["jobs"].get(job_id)
        token = self.history_token(job) if job else None
        if job is None or token is None or self.knob("history", "unavailable"):
            return 1, "", "slurm_load_jobs error: Invalid job id specified\n"
        state, reason = slurm_state(token)
        code = self.exit_code(job, token) or 0
        signal = 15 if token == "KILLED" else 0
        array = job.get("array")
        # An element's own id differs from its array's, as on a live controller.
        head = (
            f"JobId={9000 + int(array['index'])} ArrayJobId={array['id']} "
            f"ArrayTaskId={array['index']} JobName={job['name']}"
            if array
            else f"JobId={job_id} JobName={job['name']}"
        )
        text = (
            f"{head}\n"
            f"   UserId=user(1000) GroupId=user(1000) MCS_label=N/A\n"
            f"   JobState={state} Reason={reason or 'None'} Dependency=(null)\n"
            f"   ExitCode={code}:{signal}\n"
            f"   Command={job.get('script')}\n"
        )
        return 0, text, ""

    # -- cancel ----------------------------------------------------------------------------

    def cancel(self, argv: list[str], driver: str) -> tuple[int, str, str]:
        call = self.record_call("bkill" if driver == "lsf" else "scancel", argv, "cancel")
        if call in (self.knob("cancel", "fail_calls") or []):
            if driver == "lsf":
                return 255, "", "LSF is down. Please wait ...\n"
            return 1, "", "scancel: error: Kill job error: Unable to contact slurm controller\n"
        lines: list[str] = []
        errors: list[str] = []
        any_live = False
        for job_id in expand_ids(self.state["jobs"], parse_ids(argv, driver)):
            job = self.state["jobs"].get(job_id)
            token = self.token_of(job) if job else "VANISH"
            unknown = job is None or token == "VANISH" or job["profile"].get("unknown_to_kill")
            if unknown:
                if driver == "lsf":
                    lines.append(f"Job <{job_id}>: No matching job found")
                else:
                    errors.append(
                        f"scancel: error: Kill job error on job id {job_id}: Invalid job id specified"
                    )
                continue
            assert job is not None
            if is_terminal(token):
                if driver == "lsf":
                    lines.append(f"Job <{job_id}>: Job has already finished")
                continue
            any_live = True
            job["killed"] = True
            if driver == "lsf":
                lines.append(f"Job <{job_id}> is being terminated")
        stdout = "".join(line + "\n" for line in lines)
        stderr = "".join(line + "\n" for line in errors)
        if driver == "lsf":
            return (0 if any_live else 255), stdout, stderr
        return 0, stdout, stderr


def is_terminal(token: str) -> bool:
    return token in TERMINAL or token.startswith("EXIT:")


def parse_options(argv: list[str]) -> dict[str, str | None]:
    """Queue, name, output and script from a bsub or sbatch command line."""
    out: dict[str, str | None] = {
        "queue": None,
        "name": None,
        "out": None,
        "script": None,
        "array": None,
    }
    index = 1
    while index < len(argv):
        part = argv[index]
        pairs = {"-q": "queue", "-J": "name", "-o": "out"}
        if part in pairs and index + 1 < len(argv):
            out[pairs[part]] = argv[index + 1]
            index += 2
            continue
        for prefix, key in (
            ("--partition=", "queue"),
            ("--job-name=", "name"),
            ("--output=", "out"),
            ("--array=", "array"),
        ):
            if part.startswith(prefix):
                out[key] = part[len(prefix) :]
        if part in {"-n", "-R", "-W", "-M", "-app", "-e", "-env"} and index + 1 < len(argv):
            index += 2
            continue
        index += 1
    out["script"] = argv[-1] if argv[-1] and not argv[-1].startswith("-") else None
    name_spec = ARRAY_NAME_RE.match(out["name"] or "")
    if name_spec:
        out["name"] = name_spec.group(1)
        out["array"] = f"{name_spec.group(2)}-{name_spec.group(3)}"
    if out["array"] is not None:
        spec = ARRAY_RANGE_RE.match(out["array"])
        if spec is None:
            raise SystemExit(f"fake scheduler: unsupported array range {out['array']!r}")
        out["array"] = f"{spec.group(1)}-{spec.group(2)}"
    return out


def parse_ids(argv: list[str], driver: str) -> list[str]:
    ids: list[str] = []
    skip = False
    for part in argv[1:]:
        if skip:
            skip = False
            continue
        if part.startswith("--jobs="):
            ids.extend(token for token in part[len("--jobs=") :].split(",") if token)
        elif part in {"-j", "--jobs", "-o", "-t", "--states"}:
            skip = True
        elif part.startswith("-"):
            continue
        elif part in {"show", "job", "jobs"}:
            continue
        elif JOB_ID_RE.match(part.strip()):
            ids.append(part.strip())
    return ids


def expand_ids(jobs: dict[str, Any], ids: list[str]) -> list[str]:
    """Job keys for the asked ids: a bare array id names every element."""
    out: list[str] = []
    for job_id in ids:
        if job_id in jobs or not job_id.isdigit():
            out.append(job_id)
            continue
        elements = [
            key for key, job in jobs.items() if (job.get("array") or {}).get("id") == job_id
        ]
        out.extend(elements or [job_id])
    return out


def lsf_state(token: str) -> tuple[str, str]:
    if token.startswith("EXIT:"):
        return "EXIT", ""
    return {
        "PEND": ("PEND", ""),
        "RUN": ("RUN", ""),
        "SUSP": ("USUSP", ""),
        "DONE": ("DONE", ""),
        "TIMEOUT": ("EXIT", "TERM_RUNLIMIT: job killed after reaching LSF run time limit"),
        "KILLED": ("EXIT", "TERM_OWNER: job killed by owner"),
        "PREEMPTED": ("EXIT", "TERM_PREEMPT: job killed after preemption"),
        "MEMLIMIT": ("EXIT", "TERM_MEMLIMIT: job killed after reaching LSF memory usage limit"),
        "UNKWN": ("UNKWN", ""),
    }.get(token, ("RUN", ""))


def slurm_state(token: str) -> tuple[str, str]:
    if token.startswith("EXIT:"):
        return "FAILED", "NonZeroExitCode"
    return {
        "PEND": ("PENDING", "Priority"),
        "RUN": ("RUNNING", "None"),
        "SUSP": ("SUSPENDED", "None"),
        "DONE": ("COMPLETED", "None"),
        "TIMEOUT": ("TIMEOUT", "TimeLimit"),
        "KILLED": ("CANCELLED", "None"),
        "PREEMPTED": ("PREEMPTED", "Preempted"),
        "MEMLIMIT": ("OUT_OF_MEMORY", "OutOfMemory"),
        "UNKWN": ("RESIZING", "None"),
    }.get(token, ("RUNNING", "None"))


def bhist_block(job: dict[str, Any], token: str) -> str:
    lines = [
        f"Job <{job['id']}>, Job Name <{job['name']}>, User <user>, Project <default>, "
        f"Command <{job.get('script')}>",
        LSF_STAMP.format(step=0)
        + f"Submitted from host <login1>, to Queue <{job.get('queue') or 'normal'}>, CWD <$HOME>;",
    ]
    if token != "PEND":
        lines += [
            LSF_STAMP.format(step=1)
            + "Dispatched 1 Task(s) on Host(s) <node7>, Allocated 1 Slot(s) on Host(s) <node7>;",
            LSF_STAMP.format(step=1) + "Starting (Pid 4242);",
            LSF_STAMP.format(step=2)
            + "Running with execution home <$HOME>, Execution CWD <$HOME>, Execution Pid <4242>;",
        ]
    if token == "DONE":
        lines.append(
            LSF_STAMP.format(step=5) + "Done successfully. The CPU time used is 1.1 seconds;"
        )
    elif token.startswith("EXIT:"):
        lines.append(
            LSF_STAMP.format(step=5)
            + f"Exited with exit code {token.split(':', 1)[1]}. The CPU time used is 0.9 seconds;"
        )
    elif token == "KILLED":
        lines += [
            LSF_STAMP.format(step=5) + "Signal <KILL> requested by user or administrator <user>;",
            LSF_STAMP.format(step=5) + "Exited by signal 9. The CPU time used is 0.5 seconds;",
            LSF_STAMP.format(step=5) + "Completed <exit>; TERM_OWNER: job killed by owner;",
        ]
    elif token == "TIMEOUT":
        lines.append(
            LSF_STAMP.format(step=5)
            + "Completed <exit>; TERM_RUNLIMIT: job killed after reaching LSF run time limit;"
        )
    elif token == "PREEMPTED":
        lines.append(
            LSF_STAMP.format(step=5)
            + "Completed <exit>; TERM_PREEMPT: job killed after preemption;"
        )
    elif token == "MEMLIMIT":
        lines.append(
            LSF_STAMP.format(step=5)
            + "Completed <exit>; TERM_MEMLIMIT: job killed after reaching LSF memory usage limit;"
        )
    lines.append("")
    lines.append("Summary of time in seconds spent in various states by  Sat Sep 20 12:00:09")
    lines.append("  PEND     PSUSP    RUN      USUSP    SSUSP    UNKWN    TOTAL")
    lines.append("  1        0        3        0        0        0        4")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    command = Path(argv[0]).name
    driver, family = COMMANDS[command]
    fake = Fake(Path(os.environ["OCAH_FAKE_SCHEDULER"]))
    argv = [command, *argv[1:]]
    if family == "submit":
        rc, out, err = fake.submit(argv, driver)
    elif family == "query":
        rc, out, err = fake.query(argv, driver)
    elif family == "history":
        rc, out, err = fake.history(command, argv, driver)
    else:
        rc, out, err = fake.cancel(argv, driver)
    fake.save()
    sys.stdout.write(out)
    sys.stderr.write(err)
    sys.stdout.flush()
    sys.stderr.flush()
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
