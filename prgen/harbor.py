"""Stage B: run accepted tasks through Harbor on local Docker, with no model calls.

- the oracle agent (applies solution/solve.sh) --oracle-k times per task: every trial must score 1
- the nop agent (changes nothing) once per task: must score 0
- for a sample of tasks, one random mutant and the tamper edits that act on /logs/verifier (T2, T6, T7;
  that directory only exists in Docker), each as a task copy whose solution applies that edit: must score 0

Every expected trial must produce a result; a missing one counts as not as expected.

Results go to harbor.json next to the batch report, and report.md is rewritten to include them.
"""

from __future__ import annotations

import json
import pathlib
import random
import shutil
import subprocess
import time

from . import report, tamper


def _copy_task(src: pathlib.Path, dst: pathlib.Path, files: dict) -> None:
    """A copy of the task whose solution applies `files` ({path under solution/files: text}) instead of the fix."""
    shutil.copytree(src, dst)
    sol = dst / "solution" / "files"
    shutil.rmtree(sol)
    for rel, text in files.items():
        p = sol / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _run(harbor: str, path: pathlib.Path, agent: str, k: int, n: int, jobs: pathlib.Path, name: str, timeout: int) -> tuple:
    start = time.time()
    with open(jobs / f"{name}.out", "w") as log:
        done = subprocess.run([harbor, "run", "-p", str(path), "-a", agent, "-e", "docker", "-k", str(k), "-n", str(n), "-o", str(jobs),
                               "--job-name", name, "-q"], stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    return time.time() - start, done.returncode


def _tally(job: pathlib.Path, expect, expected_trials: int | None = None) -> dict:
    out = {"trials": 0, "ok": 0, "bad": 0, "exceptions": 0, "missing": 0, "mismatches": [], "by_template": {}}
    for result in sorted(job.glob("*/result.json")):
        data = json.loads(result.read_text())
        task = pathlib.Path(((data.get("config") or {}).get("task") or {}).get("path") or result.parent.name).name
        reward = ((data.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        out["trials"] += 1
        tpl = task.split("__")[0].rsplit("-", 1)[0].replace("-", "_")
        per = out["by_template"].setdefault(tpl, {"trials": 0, "ok": 0})
        per["trials"] += 1
        per["ok"] += int(not data.get("exception_info") and reward == expect(task))
        if data.get("exception_info"):
            out["exceptions"] += 1
            out["mismatches"].append(f"{task}: exception {str(data['exception_info'])[:120]}")
        elif reward == expect(task):
            out["ok"] += 1
        else:
            out["bad"] += 1
            out["mismatches"].append(f"{task}: reward {reward}, expected {expect(task)}")
    if expected_trials is not None and out["trials"] < expected_trials:
        out["missing"] = expected_trials - out["trials"]
        out["bad"] += out["missing"]
        out["mismatches"].append(f"{out['missing']} of {expected_trials} expected trials produced no result")
    return out


def stage_b(out: pathlib.Path, harbor: str, sample: int, oracle_k: int, concurrency: int, adversarial: int, seed: int,
            timeout: int = 6 * 3600) -> dict:
    out = out.resolve()
    accepted = sorted(p for p in (out / "accepted").iterdir() if p.is_dir())
    rng = random.Random(f"stage-b:{seed}")
    chosen = accepted if sample <= 0 or sample >= len(accepted) else sorted(rng.sample(accepted, sample))
    work = out / "harbor"
    if work.exists():
        shutil.rmtree(work)
    sets, jobs = work / "sets", work / "jobs"
    (sets / "accepted").mkdir(parents=True)
    jobs.mkdir()
    for task in chosen:
        shutil.copytree(task, sets / "accepted" / task.name)
    (sets / "adversarial").mkdir()
    for task in rng.sample(chosen, min(adversarial, len(chosen))):
        meta = json.loads((out / "qa" / task.name / "meta.json").read_text())
        mode = rng.choice(meta["mutants"])
        # A world task's package sits inside the project (<world>/<package>); its mutants mirror that layout.
        pkg_path = meta["world"]["package_path"] if meta.get("world") else meta["package"]
        mroot = out / "qa" / task.name / "mutants" / mode
        mutant = {str(p.relative_to(mroot)): p.read_text() for p in sorted(mroot.rglob("*")) if p.is_file()}
        _copy_task(task, sets / "adversarial" / f"{task.name}__mut_{mode}", mutant)
        init = (task / "environment" / "app" / pkg_path / "__init__.py").read_text()
        for name in tamper.DOCKER:
            _copy_task(task, sets / "adversarial" / f"{task.name}__{name.split('_')[0]}",
                       {f"{pkg_path}/__init__.py": tamper.apply(init, name)})

    version = subprocess.run([harbor, "--version"], capture_output=True, text=True).stdout.strip()
    runs = {}
    wall, code = _run(harbor, sets / "accepted", "oracle", oracle_k, concurrency, jobs, "oracle", timeout)
    runs[f"oracle x{oracle_k}"] = dict(_tally(jobs / "oracle", lambda t: 1, len(chosen) * oracle_k), wall_s=wall, exit_code=code)
    wall, code = _run(harbor, sets / "accepted", "nop", 1, concurrency, jobs, "nop", timeout)
    runs["nop x1"] = dict(_tally(jobs / "nop", lambda t: 0, len(chosen)), wall_s=wall, exit_code=code)
    copies = len(list((sets / "adversarial").iterdir()))
    if copies:
        wall, code = _run(harbor, sets / "adversarial", "oracle", 1, concurrency, jobs, "adversarial", timeout)
        runs["mutant + tamper copies"] = dict(_tally(jobs / "adversarial", lambda t: 0, copies), wall_s=wall, exit_code=code)
    info = subprocess.run(["docker", "info", "--format", "{{.NCPU}}"], capture_output=True, text=True).stdout.strip()
    data = {"harbor_version": version, "concurrency": concurrency, "tasks": len(chosen), "runs": runs,
            "docker_cpus": int(info) if info.isdigit() else None}
    (out / "harbor.json").write_text(json.dumps(data, indent=1, sort_keys=True))
    report.write(out)
    return data
