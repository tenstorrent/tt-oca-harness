# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the executor contract, the local executor, the schema-2 executor registry,
and the site layer's executor keys.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import textwrap
import threading
import tomllib
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import cli, site  # noqa: E402
from runlib.config import (  # noqa: E402
    CLUSTER_DRIVERS,
    load_executors,
    parse_walltime_sec,
    validate_executor_registry,
    validate_resource_table,
    validate_stage_table,
)
from runlib.executors import (  # noqa: E402
    DEFAULT_LIMITS,
    IMPLEMENTED_DRIVERS,
    NOT_IMPLEMENTED,
    build_executor,
    dispatch_blocker,
    executor_limits,
)
from runlib.executors.base import (  # noqa: E402
    JobState,
    LeafTask,
    ResourceRequest,
    error_result,
    render_argv,
    resolve_resources,
    result_from_fragment,
    task_identifier,
)
from runlib.executors.local import LocalExecutor  # noqa: E402
from runlib.models import ConfigError, Dut, StageResult  # noqa: E402
from runlib.results import fragment_payload  # noqa: E402
from runlib.site import SITE_EXECUTOR_KEYS, load_site_layer, merged_executors  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

LOCAL_TABLE = (
    'schema_version = 2\n\n[local]\nkind = "local"\nsubmit_argv = []\nwait_mode = "inline"\n'
)
V2_LSF = textwrap.dedent(
    """
    [lsf]
    kind = "cluster"
    description = "example batch scheduler"
    driver = "lsf"
    binaries = ["bsub", "bjobs", "bhist", "bkill"]
    submit_argv = [
      "bsub", ["-q", "{queue}"], ["-n", "{cores}"], ["-R", "rusage[mem={mem_gb}]"],
      ["-W", "{walltime_min}"], "-J", "{jobname}", "-o", "{joblog}", "{script}",
    ]
    query_argv = ["bjobs", "-json", "-o", "jobid stat exit_code exit_reason", "{job_ids_argv}"]
    history_argv = ["bhist", "-l", "{job_ids_argv}"]
    cancel_argv = ["bkill", "{job_ids_argv}"]
    history_parser = "lsf_bhist_long"
    env_passthrough = ["PATH", "LD_LIBRARY_PATH"]
    defaults = { queue = "regress", cores = 1, mem_mb = 20480, walltime = "02:00" }

    [lsf.limits]
    max_in_flight = 200
    poll_interval_sec = 30
    cancel_grace_sec = 60
    """
)


def registry(text: str) -> dict:
    data = tomllib.loads(text)
    return {key: value for key, value in data.items() if key != "schema_version"}


def make_flow(root: Path, scheduler: dict | None = None) -> Dut:
    return Dut(
        name="fixture",
        kind="sim",
        description="executor fixture",
        framework="cocotb",
        visibility="public",
        runnability="runnable",
        license="Apache-2.0",
        root="dut",
        default_tool="verilator",
        tools=["verilator"],
        path=root / "dut" / "fixture_sim_cfg.toml",
        raw={"scheduler": scheduler} if scheduler is not None else {},
        frameworks=["cocotb"],
        default_framework="cocotb",
    )


def make_task(run_dir: Path, item: str = "t_alpha", attempt: int = 0, **kwargs) -> LeafTask:
    leaf_dir = run_dir / item / "seed_7" / f"attempt_{attempt}"
    return LeafTask(
        task_id=task_identifier("sim", 3, attempt),
        leaf_id=3,
        stage="sim",
        item=item,
        seed=7,
        attempt=attempt,
        run_dir=run_dir,
        leaf_dir=leaf_dir,
        nest=True,
        **kwargs,
    )


def passing(task: LeafTask, status: str = "PASS") -> StageResult:
    return StageResult(
        stage=task.stage,
        item=task.item,
        status=status,
        return_code=0 if status == "PASS" else 1,
        duration_sec=0.5,
        started_at="2026-09-20T00:00:00+00:00",
        ended_at="2026-09-20T00:00:01+00:00",
        log=f"dut/build/runs/r/{task.item}/seed_7/attempt_{task.attempt}/logs/sim.log",
        artifacts={"junit": "x.xml"},
        failure_buckets=[],
        reason="",
        parser={"name": "cocotb"},
        metadata={"seed": task.seed, "attempt": task.attempt},
        target="default",
    )


class WalltimeTest(unittest.TestCase):
    def test_accepted_forms(self) -> None:
        cases = {
            "90": 5400,
            "90m": 5400,
            "2h": 7200,
            "30s": 30,
            "1d": 86400,
            "1:30": 5400,
            "01:30:15": 5415,
            "1-02:00:00": 93600,
            "1-02:30": 95400,
            "1-02": 93600,
        }
        for text, expected in cases.items():
            self.assertEqual(parse_walltime_sec(text), expected, text)

    def test_rejected_forms(self) -> None:
        for text in ("", "abc", "1:75", "0", "1:2:3:4", "-5"):
            with self.assertRaises(ConfigError, msg=text):
                parse_walltime_sec(text)


class ResourceRequestTest(unittest.TestCase):
    def test_placeholders_render_every_unit(self) -> None:
        request = ResourceRequest(queue="regress", cores=4, mem_mb=20000, walltime="90")
        values = request.placeholders()
        self.assertEqual(values["queue"], "regress")
        self.assertEqual(values["cores"], "4")
        self.assertEqual(values["mem_mb"], "20000")
        self.assertEqual(values["mem_gb"], "20")
        self.assertEqual(values["walltime"], "90")
        self.assertEqual(values["walltime_sec"], "5400")
        self.assertEqual(values["walltime_min"], "90")
        self.assertEqual(values["walltime_hms"], "01:30:00")

    def test_absent_fields_render_nothing(self) -> None:
        self.assertEqual(ResourceRequest().placeholders(), {})
        self.assertEqual(ResourceRequest(mem_mb=1).placeholders()["mem_gb"], "1")

    def test_resolution_order(self) -> None:
        merged = resolve_resources(
            ResourceRequest(cores=8),
            ResourceRequest(queue="q2", cores=2),
            ResourceRequest(queue="q1", cores=1, mem_mb=1024, walltime="10"),
        )
        self.assertEqual(merged, ResourceRequest(queue="q2", cores=8, mem_mb=1024, walltime="10"))

    def test_mapping_round_trip(self) -> None:
        request = ResourceRequest.from_mapping({"queue": "q", "cores": 2, "walltime": "1:00"})
        self.assertEqual(request.to_dict(), {"queue": "q", "cores": 2, "walltime": "1:00"})
        self.assertEqual(ResourceRequest.from_mapping(None), ResourceRequest())


class RenderArgvTest(unittest.TestCase):
    TEMPLATE = ["bsub", ["-q", "{queue}"], ["-n", "{cores}"], "-J", "{jobname}", "{job_ids_argv}"]

    def test_scalars_groups_and_lists(self) -> None:
        argv = render_argv(
            self.TEMPLATE,
            {"queue": "regress", "cores": "2", "jobname": "leaf"},
            {"job_ids_argv": ["11", "12"]},
        )
        self.assertEqual(argv, ["bsub", "-q", "regress", "-n", "2", "-J", "leaf", "11", "12"])

    def test_optional_group_drops_without_its_value(self) -> None:
        argv = render_argv(self.TEMPLATE, {"jobname": "leaf"}, {"job_ids_argv": []})
        self.assertEqual(argv, ["bsub", "-J", "leaf"])

    def test_missing_scalar_outside_a_group_is_an_error(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            render_argv(["-J", "{jobname}"], {})
        self.assertIn("{jobname}", str(ctx.exception))


class TaskAndResultTest(unittest.TestCase):
    def test_task_identifier(self) -> None:
        self.assertEqual(task_identifier("sim", 12, 1), "sim-000012-a1")
        self.assertEqual(
            task_identifier("regress", 0, 2, debug_only=True), "regress-000000-a2-debug"
        )

    def test_fragment_round_trip(self) -> None:
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        run_dir = root / "dut" / "build" / "runs" / "r"
        task = make_task(run_dir)
        result = passing(task)
        payload = fragment_payload(
            flow=make_flow(root),
            root=root,
            tool="verilator",
            run_dir=run_dir,
            item=task.item,
            seed=task.seed,
            result=result,
        )
        back = result_from_fragment(payload, stage="sim", item=task.item)
        for name in (
            "stage",
            "item",
            "status",
            "return_code",
            "duration_sec",
            "started_at",
            "ended_at",
            "log",
            "artifacts",
            "failure_buckets",
            "reason",
            "parser",
            "metadata",
            "target",
        ):
            self.assertEqual(getattr(back, name), getattr(result, name), name)

    def test_error_result_grades_error_with_the_reason(self) -> None:
        task = make_task(Path("/r"))
        result = error_result(task, "environment_error: gone")
        self.assertEqual((result.status, result.reason), ("ERROR", "environment_error: gone"))
        self.assertEqual(result.metadata["attempt"], 0)


class LocalExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.run_dir = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)

    def test_inline_runs_on_submit(self) -> None:
        calls: list[str] = []

        def runner(task: LeafTask) -> StageResult:
            calls.append(task.task_id)
            return passing(task)

        executor = LocalExecutor("local", runner, max_workers=1)
        self.assertEqual(executor.max_in_flight, 1)
        task = make_task(self.run_dir)
        handle = executor.submit(task)
        self.assertEqual(calls, [task.task_id])
        self.assertEqual(handle.native_job_id, "local-1")
        self.assertEqual(executor.poll([handle])[task.task_id].state, JobState.SUCCEEDED)
        outcome = executor.collect(handle)
        self.assertEqual(outcome.state, JobState.SUCCEEDED)
        assert outcome.result is not None
        self.assertEqual(outcome.result.status, "PASS")
        executor.close()

    def test_inline_exception_is_a_failed_attempt(self) -> None:
        def runner(task: LeafTask) -> StageResult:
            raise RuntimeError("stage execution cancelled")

        executor = LocalExecutor("local", runner, max_workers=1)
        handle = executor.submit(make_task(self.run_dir))
        observation = executor.poll([handle])[handle.task_id]
        self.assertEqual(observation.state, JobState.FAILED)
        self.assertIn("cancelled", observation.reason)
        outcome = executor.collect(handle)
        self.assertIsNone(outcome.result)
        self.assertIn("cancelled", outcome.error)

    def test_inline_interruption_propagates(self) -> None:
        def runner(task: LeafTask) -> StageResult:
            raise KeyboardInterrupt

        executor = LocalExecutor("local", runner, max_workers=1)
        with self.assertRaises(KeyboardInterrupt):
            executor.submit(make_task(self.run_dir))

    def test_pool_bounds_running_attempts(self) -> None:
        started: dict[str, threading.Event] = {}
        release = threading.Event()

        def runner(task: LeafTask) -> StageResult:
            started[task.task_id].set()
            release.wait(timeout=10)
            return passing(task)

        executor = LocalExecutor("local", runner, max_workers=2)
        tasks = [make_task(self.run_dir, item=f"t_{index}", attempt=index) for index in range(3)]
        for task in tasks:
            started[task.task_id] = threading.Event()
        handles = [executor.submit(task) for task in tasks]
        for task in tasks[:2]:
            self.assertTrue(started[task.task_id].wait(timeout=5))
        states = {task_id: obs.state for task_id, obs in executor.poll(handles).items()}
        self.assertEqual(states[tasks[0].task_id], JobState.RUNNING)
        self.assertEqual(states[tasks[1].task_id], JobState.RUNNING)
        self.assertEqual(states[tasks[2].task_id], JobState.QUEUED)
        release.set()
        for _ in range(50):
            executor.wait(handles, timeout_sec=0.2)
            if all(obs.state.terminal for obs in executor.poll(handles).values()):
                break
        for handle in handles:
            outcome = executor.collect(handle)
            self.assertEqual(outcome.state, JobState.SUCCEEDED)
        executor.close()

    def test_cancel_drops_queued_and_stops_running(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def runner(task: LeafTask) -> StageResult:
            started.set()
            release.wait(timeout=10)
            return passing(task)

        executor = LocalExecutor("local", runner, max_workers=1 + 1)
        running = executor.submit(make_task(self.run_dir, item="running"))
        # A third task past the pool's two workers is queued, not running, when cancel arrives.
        executor.submit(make_task(self.run_dir, item="second", attempt=1))
        queued = executor.submit(make_task(self.run_dir, item="queued", attempt=2))
        self.assertTrue(started.wait(timeout=5))
        with mock.patch(
            "runlib.executors.local.request_stage_cancellation", side_effect=release.set
        ) as stop:
            confirmed = executor.cancel([running, queued], grace_sec=5)
        stop.assert_called_once()
        self.assertTrue(confirmed[running.task_id])
        self.assertTrue(confirmed[queued.task_id])
        self.assertEqual(executor.poll([queued])[queued.task_id].state, JobState.CANCELLED)
        self.assertEqual(executor.collect(queued).state, JobState.CANCELLED)
        executor.close(wait=False)


class RegistrySchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.configs = self.root / "hw" / "common" / "dv" / "configs"
        self.configs.mkdir(parents=True)

    def write_registry(self, text: str) -> Path:
        path = self.configs / "executors.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_schema_2_registry_loads(self) -> None:
        self.write_registry(LOCAL_TABLE + V2_LSF)
        executors = load_executors(self.root)
        self.assertEqual(set(executors), {"local", "lsf"})
        self.assertEqual(executors["lsf"]["driver"], "lsf")
        self.assertEqual(executor_limits(executors["lsf"])["max_in_flight"], 200)
        self.assertEqual(executor_limits(executors["lsf"])["poll_interval_sec"], 30)
        self.assertEqual(
            executor_limits(executors["lsf"])["artifact_grace_sec"],
            DEFAULT_LIMITS["artifact_grace_sec"],
        )

    def test_checked_in_registry_declares_both_cluster_drivers(self) -> None:
        executors = load_executors(REPO_ROOT)
        self.assertEqual(set(executors), {"local", "lsf", "slurm"})
        self.assertEqual(executors["lsf"]["driver"], "lsf")
        self.assertEqual(executors["slurm"]["driver"], "slurm")
        for name in ("lsf", "slurm"):
            self.assertIsNotNone(dispatch_blocker(name, executors[name]))
            self.assertNotIn("defaults", executors[name], "the public registry names no site value")

    def test_checked_in_templates_render_every_placeholder(self) -> None:
        executors = load_executors(REPO_ROOT)
        request = ResourceRequest(queue="q", cores=2, mem_mb=4096, walltime="1:30")
        values = {
            **request.placeholders(),
            "jobname": "dtp-sim-000001-a0",
            "joblog": "/run/jobs/sim-000001-a0.log",
            "script": "/run/jobs/sim-000001-a0.sh",
        }
        lists = {"job_ids_argv": ["11", "12"], "job_ids_csv": ["11,12"]}
        lsf = render_argv(executors["lsf"]["submit_argv"], values)
        self.assertEqual(
            lsf[:9], ["bsub", "-q", "q", "-n", "2", "-R", "rusage[mem=4096]", "-W", "90"]
        )
        self.assertEqual(lsf[-1], "/run/jobs/sim-000001-a0.sh")
        slurm = render_argv(executors["slurm"]["submit_argv"], values)
        self.assertIn("--time=01:30:00", slurm)
        self.assertIn("--mem=4096M", slurm)
        bare = render_argv(
            executors["slurm"]["submit_argv"],
            {k: v for k, v in values.items() if k not in request.placeholders()},
        )
        self.assertNotIn("--partition=q", bare)
        self.assertEqual(bare[:2], ["sbatch", "--parsable"])
        self.assertEqual(
            render_argv(executors["lsf"]["cancel_argv"], {}, lists), ["bkill", "11", "12"]
        )
        self.assertEqual(
            render_argv(executors["slurm"]["query_argv"], {"job_ids_csv": "11,12"}),
            ["squeue", "--noheader", "--format=%i|%T|%r", "--jobs=11,12"],
        )

    def test_unknown_schema_version(self) -> None:
        self.write_registry(LOCAL_TABLE.replace("schema_version = 2", "schema_version = 3"))
        with self.assertRaises(ConfigError) as ctx:
            load_executors(self.root)
        self.assertIn("schema_version", str(ctx.exception))

    def test_setup_hook_belongs_in_the_site_layer(self) -> None:
        self.write_registry(
            LOCAL_TABLE + V2_LSF.replace('driver = "lsf"', 'driver = "lsf"\nsetup_hook = "lsf.env"')
        )
        with self.assertRaises(ConfigError) as ctx:
            load_executors(self.root)
        self.assertIn("site layer", str(ctx.exception))

    def test_schema_1_cluster_shape_still_validates(self) -> None:
        table = registry(
            LOCAL_TABLE
            + '[grid]\nkind = "cluster"\nbinary = "qsub"\nsubmit_argv = ["qsub", "-q", "{queue}"]\n'
        )
        validate_executor_registry(table, "test")
        table["grid"].pop("binary")
        with self.assertRaises(ConfigError):
            validate_executor_registry(table, "test")

    def check_rejected(self, mutate, needle: str) -> None:
        table = registry(LOCAL_TABLE + V2_LSF)
        mutate(table["lsf"])
        with self.assertRaises(ConfigError) as ctx:
            validate_executor_registry(table, "test")
        self.assertIn(needle, str(ctx.exception))

    def test_schema_2_rejections(self) -> None:
        self.check_rejected(lambda t: t.update(driver="pbs"), "driver")
        self.check_rejected(lambda t: t.update(binaries=[]), "binaries")
        self.check_rejected(lambda t: t.update(wait_mode="inline"), "wait_mode")
        self.check_rejected(lambda t: t.pop("submit_argv"), "submit_argv")
        self.check_rejected(lambda t: t.update(query_argv=["bjobs", "{queue}"]), "placeholder")
        self.check_rejected(lambda t: t.update(submit_argv=["bsub", "{job_id}"]), "placeholder")
        self.check_rejected(lambda t: t.update(submit_argv=["bsub", ["-q", ""]]), "group")
        self.check_rejected(lambda t: t["defaults"].update(cores=0), "cores")
        self.check_rejected(lambda t: t["defaults"].update(walltime="1:99"), "walltime")
        self.check_rejected(lambda t: t["defaults"].update(slots=4), "slots")
        self.check_rejected(lambda t: t["limits"].update(poll_interval_sec=0), "poll_interval_sec")
        self.check_rejected(lambda t: t["limits"].update(max_in_flight=1.5), "integer")
        self.check_rejected(lambda t: t["limits"].update(retries=3), "retries")
        self.check_rejected(lambda t: t.update(colour="blue"), "colour")
        self.check_rejected(lambda t: t.update(history_parser=""), "history_parser")

    def test_stage_resources_take_the_normalized_vocabulary(self) -> None:
        validate_stage_table(
            "sim", {"kind": "noop", "resources": {"cores": 2, "walltime": "30"}}, "cfg"
        )
        with self.assertRaises(ConfigError) as ctx:
            validate_stage_table("sim", {"kind": "noop", "resources": {"slots": 2}}, "cfg")
        self.assertIn("slots", str(ctx.exception))
        with self.assertRaises(ConfigError):
            validate_stage_table("sim", {"kind": "noop", "default_executor": ""}, "cfg")
        self.assertEqual(validate_resource_table({"mem_mb": 4096}, "x"), {"mem_mb": 4096})


class SiteExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        configs = self.root / "hw" / "common" / "dv" / "configs"
        configs.mkdir(parents=True)
        (configs / "executors.toml").write_text(LOCAL_TABLE + V2_LSF, encoding="utf-8")
        self.base = load_executors(self.root)

    def load(self, text: str) -> site.SiteLayer:
        path = self.root / "site.toml"
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        layer = load_site_layer(self.root, {site.SITE_ENV: str(path)})
        assert layer is not None
        return layer

    def test_site_keys_cover_the_schema_2_data_keys(self) -> None:
        for key in ("driver", "binaries", "submit_argv", "query_argv", "limits", "setup_hook"):
            self.assertIn(key, SITE_EXECUTOR_KEYS)
        self.assertNotIn("kind", SITE_EXECUTOR_KEYS)

    def test_site_overrides_data_keys_of_a_declared_executor(self) -> None:
        layer = self.load(
            """
            [executors.lsf]
            binaries = ["bsub-site", "bjobs", "bhist", "bkill"]
            defaults = { queue = "nightly" }
            [executors.lsf.limits]
            max_in_flight = 50
            """
        )
        merged = merged_executors(self.base, layer)
        self.assertEqual(merged["lsf"]["binaries"][0], "bsub-site")
        self.assertEqual(merged["lsf"]["defaults"], {"queue": "nightly"})
        self.assertEqual(merged["lsf"]["limits"], {"max_in_flight": 50})
        self.assertEqual(merged["lsf"]["driver"], "lsf")
        self.assertEqual(merged["local"], self.base["local"])

    def test_site_cannot_change_an_executor_kind(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            merged_executors(self.base, self.load('[executors.lsf]\nkind = "local"\n'))
        self.assertIn("kind", str(ctx.exception))

    def test_site_adds_a_complete_schema_2_table(self) -> None:
        layer = self.load(
            """
            [executors.slurm]
            kind = "cluster"
            driver = "slurm"
            binaries = ["sbatch", "squeue", "sacct", "scancel"]
            submit_argv = ["sbatch", "--parsable", ["--partition={queue}"], "{script}"]
            query_argv = ["squeue", "--noheader", "--jobs={job_ids_csv}"]
            cancel_argv = ["scancel", "{job_ids_argv}"]
            """
        )
        merged = merged_executors(self.base, layer)
        self.assertEqual(merged["slurm"]["driver"], "slurm")

    def test_setup_hook_resolves_against_the_site_file(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self.load('[executors.lsf]\nsetup_hook = "lsf.env"\n')
        self.assertIn("setup_hook", str(ctx.exception))
        (self.root / "lsf.env").write_text("export LSF_ENVDIR=/x\n", encoding="utf-8")
        layer = self.load('[executors.lsf]\nsetup_hook = "lsf.env"\n')
        merged = merged_executors(self.base, layer)
        self.assertEqual(merged["lsf"]["setup_hook"], str(self.root / "lsf.env"))


class DispatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.executors = registry(LOCAL_TABLE + V2_LSF)

    def test_driver_tables(self) -> None:
        self.assertEqual(set(CLUSTER_DRIVERS), {"lsf", "slurm"})
        self.assertEqual(set(IMPLEMENTED_DRIVERS), {"local"})

    def test_blocker_names_the_undispatchable_executor(self) -> None:
        self.assertIsNone(dispatch_blocker("local", self.executors["local"]))
        blocker = dispatch_blocker("lsf", self.executors["lsf"])
        assert blocker is not None
        self.assertIn("`lsf`", blocker)
        self.assertIn(NOT_IMPLEMENTED, blocker)
        with self.assertRaises(ConfigError):
            build_executor("lsf", self.executors["lsf"], runner=passing, max_workers=1)
        local = build_executor("local", self.executors["local"], runner=passing, max_workers=3)
        self.assertIsInstance(local, LocalExecutor)
        self.assertEqual(local.max_in_flight, 3)
        local.close()

    def test_selected_executor_checks_allowlist_registry_and_dispatch(self) -> None:
        root = Path("/fixture")
        flow = make_flow(root, {"default_executor": "lsf", "allowed": ["local", "lsf"]})
        with self.assertRaises(ConfigError) as ctx:
            cli.selected_executor(flow, Namespace(executor=None), self.executors)
        self.assertIn(NOT_IMPLEMENTED, str(ctx.exception))
        self.assertEqual(
            cli.selected_executor(flow, Namespace(executor="local"), self.executors), "local"
        )
        with self.assertRaises(ConfigError) as ctx:
            cli.selected_executor(flow, Namespace(executor="slurm"), self.executors)
        self.assertIn("not allowed", str(ctx.exception))
        open_flow = make_flow(root, {"default_executor": "local"})
        with self.assertRaises(ConfigError) as ctx:
            cli.selected_executor(open_flow, Namespace(executor="pbs"), self.executors)
        self.assertIn("not in the executor registry", str(ctx.exception))
        self.assertEqual(
            cli.selected_executor(make_flow(root), Namespace(executor=None), self.executors),
            "local",
        )

    def test_resource_request_layers_cli_stage_and_defaults(self) -> None:
        args = Namespace(queue=None, cores=8, mem_mb=None, walltime=None)
        stage = {"kind": "noop", "resources": {"queue": "q2", "cores": 2}}
        request = cli.resource_request(args, stage, self.executors["lsf"])
        self.assertEqual(
            request, ResourceRequest(queue="q2", cores=8, mem_mb=20480, walltime="02:00")
        )
        self.assertEqual(cli.resource_request(Namespace(), {}, {}), ResourceRequest())


if __name__ == "__main__":
    unittest.main()
