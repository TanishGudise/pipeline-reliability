"""Run a task's real verifier (tests/test.sh) locally, without Docker, and measure it."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


@dataclasses.dataclass
class Run:
    reward: int | None
    outcomes: dict  # test name -> "passed" | "failed"
    cpu_s: float
    wall_s: float
    note: str = ""
    load_cpu_s: float = 0.0  # CPU used by the extra load processes (not charged to the task)

    @property
    def failed(self) -> set:
        return {t for t, o in self.outcomes.items() if o != "passed"}


def _wait(proc: subprocess.Popen, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            proc.returncode = os.waitstatus_to_exitcode(status)
            return usage
        if time.monotonic() > deadline:
            os.killpg(proc.pid, 9)
            pid, status, usage = os.wait4(proc.pid, 0)
            proc.returncode = "timeout"
            return usage
        time.sleep(0.02)


def _junit(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    outcomes = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        bad = any(child.tag in ("failure", "error", "skipped") for child in case)
        outcomes[case.get("name")] = "failed" if bad else "passed"
    return outcomes


def overlay_files(app: pathlib.Path, files_dir: pathlib.Path) -> None:
    for src in files_dir.rglob("*"):
        if src.is_file():
            dst = app / src.relative_to(files_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)


DOCKERWORK = pathlib.Path(__file__).resolve().parent.parent / ".dockerwork"  # under $HOME, so colima can mount it


def _docker(work: pathlib.Path, image: str, command: str, timeout: float) -> str | None:
    """Run `command` in a fresh no-network container of `image` with `work` mounted at /work.
    Returns None, or "timeout" if it had to be killed."""
    name = f"prgen-{work.name}"
    cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", "-v", f"{work}:/work",
           "-e", "APP_DIR=/work/app", "-e", "TESTS_DIR=/work/tests", "-e", "LOGS_DIR=/work/logs", "-e", "PYTHON=python",
           image, "bash", "-c", command]
    try:
        subprocess.run(cmd, timeout=timeout, capture_output=True)
        return None
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        return "timeout"


def _container_cpu(work: pathlib.Path) -> float:
    try:
        for line in (work / "cpu.stat").read_text().splitlines():
            if line.startswith("usage_usec"):
                return int(line.split()[1]) / 1e6
    except (OSError, ValueError):
        pass
    return 0.0


def _verify_docker(task_dir: pathlib.Path, overlay, image: str, timeout: float) -> Run:
    DOCKERWORK.mkdir(exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="v", dir=DOCKERWORK))
    try:
        shutil.copytree(task_dir / "environment" / "app", work / "app")
        shutil.copytree(task_dir / "tests", work / "tests")
        (work / "logs").mkdir()
        if overlay is not None:
            overlay_files(work / "app", overlay)
        start = time.monotonic()
        status = _docker(work, image, "bash /work/tests/test.sh > /work/verifier.out 2>&1; cat /sys/fs/cgroup/cpu.stat > /work/cpu.stat",
                         timeout)
        wall = time.monotonic() - start
        reward_file = work / "logs" / "reward.txt"
        try:
            reward = int(reward_file.read_text().strip()) if reward_file.is_file() else None
        except ValueError:
            reward = None
        note = "verifier exit timeout" if status else ""
        if reward is None:
            out = work / "verifier.out"
            note = (note + " " + (out.read_text(errors="replace")[-800:] if out.exists() else "")).strip()
        return Run(None if status else reward, _junit(work / "logs" / "junit.xml"), _container_cpu(work), wall, note)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def project_tests(task_dir: pathlib.Path, world: str, files: list, image: str, overlay=None, timeout: float = 900) -> tuple:
    """Run the project's own tests in the agent's workspace (inside the world image). Returns (passed, cpu_s, tail)."""
    DOCKERWORK.mkdir(exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="p", dir=DOCKERWORK))
    try:
        shutil.copytree(task_dir / "environment" / "app", work / "app")
        if overlay is not None:
            overlay_files(work / "app", overlay)
        status = _docker(work, image, f"cd /work/app/{world} && python -m pytest -q -p no:cacheprovider {' '.join(files)}"
                         " > /work/out.txt 2>&1; echo $? > /work/status; cat /sys/fs/cgroup/cpu.stat > /work/cpu.stat", timeout)
        out = (work / "out.txt").read_text(errors="replace") if (work / "out.txt").exists() else ""
        code = (work / "status").read_text().strip() if (work / "status").exists() else "?"
        return status is None and code == "0", _container_cpu(work), out[-600:]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def verify(task_dir: pathlib.Path, overlay: pathlib.Path | None = None, script: pathlib.Path | None = None,
           load: int = 0, timeout: float = 240, image: str | None = None) -> Run:
    """Copy the workspace, apply an overlay directory or an edit script, run tests/test.sh (inside `image`
    for world tasks; extra CPU load is only applied to local runs)."""
    if image is not None:
        return _verify_docker(task_dir, overlay, image, timeout)
    load_procs: list = []
    load_cpu = 0.0
    try:
        result = _verify(task_dir, overlay, script, load, timeout, load_procs)
    finally:
        for p in load_procs:
            p.kill()
            _, _, usage = os.wait4(p.pid, 0)  # reap here and report it, so the load isn't charged to the task
            p.returncode = -9
            load_cpu += usage.ru_utime + usage.ru_stime
    result.load_cpu_s = load_cpu
    return result


def _verify(task_dir, overlay, script, load, timeout, load_procs) -> Run:
    work = pathlib.Path(tempfile.mkdtemp(prefix="prgen-run-"))
    try:
        app, logs = work / "app", work / "logs"
        shutil.copytree(task_dir / "environment" / "app", app)
        env = dict(os.environ, APP_DIR=str(app), TESTS_DIR=str(task_dir / "tests"), LOGS_DIR=str(logs), PYTHON=sys.executable)
        if overlay is not None:
            overlay_files(app, overlay)
        if script is not None:
            done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=120)
            if done.returncode != 0:
                return Run(None, {}, 0.0, 0.0, f"edit script failed: {done.stderr[-500:]}")
        for _ in range(load):
            load_procs.append(subprocess.Popen([sys.executable, "-c", "while True: pass"]))
        start = time.monotonic()
        proc = subprocess.Popen(["bash", str(task_dir / "tests" / "test.sh")], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
        out_path = work / "verifier.out"
        with open(out_path, "wb") as sink:
            # Drain output in the background so the verifier never blocks on a full pipe.
            import threading
            t = threading.Thread(target=lambda: shutil.copyfileobj(proc.stdout, sink), daemon=True)
            t.start()
            usage = _wait(proc, timeout)
            t.join(5)
        wall = time.monotonic() - start
        cpu = usage.ru_utime + usage.ru_stime
        reward_file = logs / "reward.txt"
        try:
            reward = int(reward_file.read_text().strip()) if reward_file.is_file() else None
        except ValueError:
            reward = None
        note = "" if proc.returncode == 0 else f"verifier exit {proc.returncode}"
        if reward is None:
            note = (note + " " + out_path.read_text(errors="replace")[-800:]).strip()
        return Run(reward, _junit(logs / "junit.xml"), cpu, wall, note)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def public_tests(task_dir: pathlib.Path, overlay: pathlib.Path | None = None) -> tuple[bool, float, str]:
    """Run the public tests on the workspace (optionally with an overlay). Returns (passed, cpu_s, tail)."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="prgen-pub-"))
    try:
        app = work / "app"
        shutil.copytree(task_dir / "environment" / "app", app)
        if overlay is not None:
            overlay_files(app, overlay)
        proc = subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=120", "tests"],
                                cwd=app, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)
            out, _ = proc.communicate()
            return False, 0.0, "public tests timed out"
        return proc.returncode == 0, 0.0, out.decode(errors="replace")[-600:]
    finally:
        shutil.rmtree(work, ignore_errors=True)
