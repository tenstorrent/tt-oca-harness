# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Terminal UI helpers for the native DV runner."""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, TextIO

_CI_TRUE = {"1", "true", "yes", "on"}
_STATUS_COLOR = {
    "PASS": "32",
    "FAIL": "31",
    "ERROR": "31",
    "TIMEOUT": "33",
    "UNKNOWN": "33",
    "SKIP": "36",
    "RUN": "36",
}


class Console:
    """Small dependency-free console facade with TTY and CI aware formatting."""

    def __init__(
        self,
        mode: str = "auto",
        *,
        quiet: bool = False,
        verbose: bool = False,
        stream: TextIO | None = None,
    ) -> None:
        self.mode = mode
        self.quiet = quiet
        self.verbose = verbose
        self.stream = stream or sys.stdout
        self.is_ci = os.environ.get("CI", "").lower() in _CI_TRUE
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.pretty = self._resolve_pretty()
        self.color = self.pretty and "NO_COLOR" not in os.environ
        self._regression_item_width = 44
        self._regression_seed_width = 8
        self._fd: int | None = None
        try:
            self._fd = os.dup(self.stream.fileno())
        except (AttributeError, OSError):
            self._fd = None
        self._local = threading.local()

    def _suppressed(self) -> bool:
        return bool(getattr(self._local, "suppressed", False))

    @contextmanager
    def suppress(self, enabled: bool = True) -> Iterator[None]:
        previous = self._suppressed()
        self._local.suppressed = previous or enabled
        try:
            yield
        finally:
            self._local.suppressed = previous

    def clear_suppression(self) -> None:
        """Drop the leaf-UI suppression a stage abandoned mid-flight left on this thread."""
        self._local.suppressed = False

    def _resolve_pretty(self) -> bool:
        if self.mode == "pretty":
            return True
        if self.mode == "plain":
            return False
        return self.is_tty and not self.is_ci

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _paint(self, text: str, code: str) -> str:
        if not self.color:
            return text
        return f"\033[{code}m{text}\033[0m"

    def _status(self, status: str) -> str:
        return self._paint(status, _STATUS_COLOR.get(status, "0"))

    @staticmethod
    def _regression_duration(duration_sec: float) -> str:
        if duration_sec < 60.0:
            return f"{max(0.0, duration_sec):.1f}s"
        total_sec = max(0, int(duration_sec + 0.5))
        hours, rem = divmod(total_sec, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours}h{minutes:02d}m{seconds:02d}s"
        return f"{minutes}m{seconds:02d}s"

    def write(self, text: str = "", *, force: bool = False) -> None:
        if self._suppressed() and not force:
            return
        if self.quiet and not force:
            return
        line = text + "\n"
        if self._fd is not None:
            os.write(self._fd, line.encode("utf-8", errors="replace"))
        else:
            self.stream.write(line)
            self.stream.flush()

    def event(self, kind: str, message: str, *, force: bool = False) -> None:
        if self.pretty:
            self.write(f"{kind:<10} {message}", force=force)
        else:
            stamp = datetime.now().strftime("%H:%M:%S")
            self.write(f"{stamp} {kind:<10} {message}", force=force)

    def run_header(
        self,
        *,
        flow: str,
        tool: str,
        run_dir: str,
        items: int,
        stages: list[str],
        verbose: bool,
        jobs: int = 1,
        executor: str = "local",
        mode: str | None = None,
    ) -> None:
        if self.quiet:
            return
        if self.pretty:
            self.write(self._paint(f"{flow}  {tool}", "1"))
            self.write(f"Run dir : {run_dir}")
            self.write(f"Items   : {items}")
            self.write(f"Stages  : {', '.join(stages)}")
            if mode:
                self.write(f"Mode    : {mode}")
            self.write(f"Sim jobs: {jobs}")
            self.write(f"Executor: {executor}")
            self.write(f"Backend : {'live stdout' if verbose else 'logs only'}")
        else:
            self.event(
                "run",
                (
                    f"flow={flow} tool={tool} items={items} "
                    f"stages={','.join(stages)} run_dir={run_dir} "
                    f"mode={mode or '-'} sim_jobs={jobs} executor={executor} "
                    f"backend={'live' if verbose else 'log'}"
                ),
            )

    def stage_header(
        self,
        *,
        stage: str,
        log: str,
        item: str | None = None,
        seed: int | None = None,
        target: str | None = None,
    ) -> None:
        if self.quiet:
            return
        name = f"{stage}"
        if item:
            name += f" {item}"
        elif target:
            name += f" target={target}"
        seed_text = f" seed={seed}" if seed is not None else ""
        if self.pretty:
            self.write("")
            self.write(self._paint(f"[{name}]{seed_text}", "1"))
            self.write(f"  log: {log}")
        else:
            target_text = f" target={target}" if target else ""
            self.event(
                "stage",
                f"start name={stage} item={item or '-'}{target_text}{seed_text} log={log}",
            )

    def stage_result(
        self,
        *,
        stage: str,
        status: str,
        duration_sec: float,
        item: str | None = None,
        target: str | None = None,
    ) -> None:
        if self.quiet:
            return
        if item:
            name = f"{stage}:{item}"
        elif target:
            name = f"{stage}:{target}"
        else:
            name = stage
        if self.pretty:
            self.write(f"  {name:<24} {self._status(status):<16} {duration_sec:.1f}s")
        else:
            target_text = f" target={target}" if target else ""
            self.event(
                "stage",
                (
                    f"done name={stage} item={item or '-'}{target_text} status={status} "
                    f"elapsed={duration_sec:.1f}s"
                ),
            )

    def regression_start(
        self,
        *,
        total: int,
        jobs: int,
        executor: str,
        seeds: int | str,
        retry: int,
        item_width: int | None = None,
        seed_width: int | None = None,
    ) -> None:
        if self.quiet:
            return
        self._regression_item_width = max(44, item_width or 44)
        self._regression_seed_width = max(8, seed_width or 8)
        if self.pretty:
            self.write("")
            self.write(
                self._paint(
                    f"[regression] {total} tests, sim_jobs={jobs}, executor={executor}, "
                    f"seeds={seeds}, retry={retry}",
                    "1",
                )
            )
        else:
            self.event(
                "regression",
                f"start total={total} sim_jobs={jobs} executor={executor} seeds={seeds} retry={retry}",
            )

    def regression_leaf_done(
        self,
        *,
        index: int,
        total: int,
        item: str,
        seed: int,
        attempt: int,
        status: str,
        duration_sec: float,
        log: str | None,
        reason: str,
        target: str | None = None,
    ) -> None:
        if self.quiet:
            return
        failed = status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}
        if self.pretty:
            digits = max(2, len(str(total)))
            count = f"[{index:0{digits}d}/{total}]"
            attempt_text = f" attempt={attempt}" if attempt else ""
            target_text = f" target={target}" if target else ""
            item_width = max(self._regression_item_width, len(item))
            seed_width = max(self._regression_seed_width, len(str(seed)))
            status_text = self._paint(f"{status:<7}", _STATUS_COLOR.get(status, "0"))
            duration_text = f"{self._regression_duration(duration_sec):>8}"
            line = (
                f"  {count} {status_text} {item:<{item_width}} "
                f"seed={seed:<{seed_width}} {duration_text}"
                f"{attempt_text}{target_text}"
            )
            if failed and log:
                line += f" log={log}"
            self.write(line)
        else:
            message = (
                f"done index={index}/{total} status={status} item={item} seed={seed} "
                f"attempt={attempt} elapsed={duration_sec:.1f}s"
            )
            if target:
                message += f" target={target}"
            if failed and log:
                message += f" log={log}"
            if failed and reason:
                message += f" reason={self._shorten(reason, 120)}"
            self.event("regression", message)

    def regression_summary(
        self,
        runs_by_item: dict[str, list[tuple[int, Any]]],
        *,
        ordered_items: list[str],
        elapsed_sec: float,
        planned: int | None = None,
    ) -> None:
        if self.quiet:
            return
        rows = self._ordered_regression_rows(runs_by_item, ordered_items)
        if not rows:
            return

        total = len(rows)
        passing = sum(1 for _, _, result in rows if result.status == "PASS")
        skipped = sum(1 for _, _, result in rows if result.status == "SKIP")
        failing = total - passing - skipped
        failed_rows = [
            (item, seed, result)
            for item, seed, result in rows
            if result.status in {"FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}
        ]
        skipped_text = f", {skipped} skipped" if skipped else ""
        executed = total - skipped
        incomplete = planned is not None and planned > executed
        if incomplete:
            header = (
                f"Regression Summary: incomplete run, {executed} of {planned} planned leaves "
                f"ran; {passing} passed, {failing} failed{skipped_text}, "
                f"elapsed={elapsed_sec:.1f}s"
            )
        else:
            header = (
                f"Regression Summary: {passing}/{total} passed, {failing} failed"
                f"{skipped_text}, elapsed={elapsed_sec:.1f}s"
            )

        if self.pretty:
            status_width = max(7, max(len(result.status) for _, _, result in rows))
            item_width = max(44, max(len(item) for item, _, _ in rows))
            seed_width = max(8, max(len(str(seed)) for _, seed, _ in rows))
            self.write("")
            self.write(header)
            for item, seed, result in rows:
                reason = self._shorten(result.reason, 80)
                reason_text = f" reason={reason}" if result.status != "PASS" and reason else ""
                status_text = self._paint(
                    f"{result.status:<{status_width}}",
                    _STATUS_COLOR.get(result.status, "0"),
                )
                duration_text = f"{self._regression_duration(result.duration_sec):>8}"
                self.write(
                    f"  {status_text} {item:<{item_width}} "
                    f"seed={seed:<{seed_width}} {duration_text}"
                    f"{reason_text}"
                )
            if failed_rows:
                self.write("")
                self.write("Failed tests:")
                for item, _, result in failed_rows:
                    self.write(f"  {item}")
                    if result.log:
                        self.write(f"    log: {result.log}")
                    if result.reason:
                        self.write(f"    reason: {result.reason}")
        else:
            incomplete_text = f" incomplete={executed}/{planned}" if incomplete else ""
            self.event(
                "summary",
                (
                    f"passing={passing} total={total} failing={failing} "
                    f"skipped={skipped} elapsed={elapsed_sec:.1f}s{incomplete_text}"
                ),
            )
            for item, seed, result in rows:
                message = (
                    f"status={result.status} item={item} seed={seed} "
                    f"elapsed={result.duration_sec:.1f}s"
                )
                if result.status != "PASS" and result.reason:
                    message += f" reason={self._shorten(result.reason, 120)}"
                self.event("summary", message)
            for item, _, result in failed_rows:
                if result.log:
                    self.event("failure", f"item={item} log={result.log}")
                if result.reason:
                    self.event("failure", f"item={item} reason={result.reason}")

    def step_start(self, label: str) -> None:
        if self.pretty:
            self.write(f"  {label:<24} {self._status('RUN')}")
        else:
            self.event("step", f"start {label}")

    def step_heartbeat(self, label: str, elapsed_sec: int) -> None:
        if self.pretty:
            self.write(f"  {label:<24} still running ({elapsed_sec}s elapsed)")
        else:
            self.event("step", f"running {label} elapsed={elapsed_sec}s")

    def step_done(self, label: str, elapsed_sec: float) -> None:
        if self.pretty:
            self.write(f"  {label:<24} {self._status('PASS'):<16} {elapsed_sec:.1f}s")
        else:
            self.event("step", f"done {label} elapsed={elapsed_sec:.1f}s")

    def step_failed(self, label: str, elapsed_sec: float) -> None:
        if self.pretty:
            self.write(f"  {label:<24} {self._status('FAIL'):<16} {elapsed_sec:.1f}s")
        else:
            self.event("step", f"failed {label} elapsed={elapsed_sec:.1f}s")

    def artifact(self, label: str, path: str | Path) -> None:
        if self.quiet:
            return
        if self.pretty:
            self.write(f"  {label:<10}: {path}")
        else:
            self.event("artifact", f"{label}={path}")

    def failure_tail(self, path: Path, *, lines: int = 40) -> None:
        if self.quiet or not path.is_file():
            return
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        tail = content[-lines:]
        if self.pretty:
            self.write("")
            self.write(self._paint(f"Failure log tail: {path}", "31"))
            for line in tail:
                self.write(f"  {line}")
        else:
            self.event("failure", f"log_tail={path} lines={len(tail)}")
            for line in tail:
                self.write(line)

    def result(
        self,
        *,
        status: str,
        elapsed_sec: float,
        tests: int,
        run_dir: str,
        result_json: str,
        incomplete: str | None = None,
        force: bool = False,
    ) -> None:
        force = self.quiet or force
        if self.pretty and not self.quiet:
            self.write("")
            self.write(
                f"Result  : {self._status(status)}  tests={tests}  elapsed={elapsed_sec:.1f}s",
                force=force,
            )
            if incomplete:
                self.write(f"Note    : {incomplete}", force=force)
            self.write(f"Run dir : {run_dir}", force=force)
            self.write(f"JSON    : {result_json}", force=force)
        else:
            note = f" note={incomplete!r}" if incomplete else ""
            self.event(
                "result",
                (
                    f"status={status} tests={tests} elapsed={elapsed_sec:.1f}s "
                    f"run_dir={run_dir} json={result_json}{note}"
                ),
                force=force,
            )

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."

    @staticmethod
    def _ordered_regression_rows(
        runs_by_item: dict[str, list[tuple[int, Any]]],
        ordered_items: list[str],
    ) -> list[tuple[str, int, Any]]:
        rows: list[tuple[str, int, Any]] = []
        seen: set[str] = set()
        for item in ordered_items:
            if item not in runs_by_item:
                continue
            seen.add(item)
            for seed, result in runs_by_item[item]:
                rows.append((item, seed, result))
        for item, runs in runs_by_item.items():
            if item in seen:
                continue
            for seed, result in runs:
                rows.append((item, seed, result))
        return rows
