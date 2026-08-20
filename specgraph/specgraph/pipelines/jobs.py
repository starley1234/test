"""Фоновые прогоны: RAM + таблица pipeline_runs. Своя Session в потоке."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from specgraph.config import settings

log = logging.getLogger("specgraph.jobs")


class JobStopped(Exception):
    pass


@dataclass
class Job:
    id: str
    name: str
    status: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0})
    result: dict[str, Any] | None = None
    error: str | None = None
    user_id: int | None = None
    mode: str | None = None
    paused: bool = False
    halt: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def wait_gate(self) -> None:
        while True:
            with self.lock:
                if self.halt:
                    raise JobStopped("остановлено")
                if not self.paused:
                    return
            time.sleep(0.2)

    def emit(self, ev: dict[str, Any]) -> None:
        with self.lock:
            u = ev.get("tokens") or {}
            if u:
                self.tokens["prompt"] += int(u.get("prompt") or 0)
                self.tokens["completion"] += int(u.get("completion") or 0)
                self.tokens["total"] = self.tokens["prompt"] + self.tokens["completion"]
            ev = {**ev, "tokens_total": dict(self.tokens)}
            self.events.append(ev)
        _persist(self)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "name": self.name,
                "status": self.status,
                "paused": self.paused,
                "halt": self.halt,
                "mode": self.mode,
                "tokens": dict(self.tokens),
                "events": list(self.events),
                "result": self.result,
                "error": self.error,
            }


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def _running_count() -> int:
    return sum(1 for j in _JOBS.values() if j.status in {"queued", "running"})


def get_job(job_id: str) -> Job | None:
    j = _JOBS.get(job_id)
    if j:
        return j
    return _load_db(job_id)


def _persist(job: Job) -> None:
    from specgraph.db import SessionLocal
    from specgraph.models import PipelineRun

    db = SessionLocal()
    try:
        row = db.get(PipelineRun, job.id)
        snap = job.snapshot()
        if not row:
            db.add(
                PipelineRun(
                    id=job.id,
                    name=job.name,
                    status=job.status,
                    mode=job.mode,
                    events=snap["events"][-80:],
                    tokens=snap["tokens"],
                    result=job.result,
                    error=job.error,
                    user_id=job.user_id,
                )
            )
        else:
            row.status = job.status
            row.mode = job.mode
            row.events = snap["events"][-80:]
            row.tokens = snap["tokens"]
            row.result = job.result
            row.error = job.error
        db.commit()
    except Exception:
        log.exception("persist job %s", job.id)
        db.rollback()
    finally:
        db.close()


def _load_db(job_id: str) -> Job | None:
    from specgraph.db import SessionLocal
    from specgraph.models import PipelineRun

    db = SessionLocal()
    try:
        row = db.get(PipelineRun, job_id)
        if not row:
            return None
        j = Job(id=row.id, name=row.name, status=row.status, user_id=row.user_id, mode=row.mode)
        j.events = list(row.events or [])
        j.tokens = dict(row.tokens or {})
        j.result = row.result
        j.error = row.error
        return j
    finally:
        db.close()


def start_job(
    name: str,
    kwargs: dict[str, Any],
    *,
    scheme_path: Path | None = None,
    scheme_name: str | None = None,
    user_id: int | None = None,
) -> Job:
    if _running_count() >= int(settings.max_parallel_jobs):
        raise RuntimeError(f"уже идёт {_running_count()} прогона — подождите")
    ids = list(kwargs.get("requirement_ids") or [])
    cap = int(settings.guest_max_reqs if user_id is None else settings.max_reqs_per_run)
    if len(ids) > cap:
        kwargs = {**kwargs, "requirement_ids": ids[:cap], "truncated_to": cap}
    job = Job(id=uuid4().hex[:12], name=name, user_id=user_id)
    with _JOBS_LOCK:
        _JOBS[job.id] = job
    _persist(job)

    def work() -> None:
        from specgraph.db import SessionLocal

        db = SessionLocal()
        try:
            job.status = "running"
            job.emit({"event": "start", "pipeline": name, "step": "старт", "truncated_to": kwargs.get("truncated_to")})
            result = _dispatch(name, db, kwargs, job, scheme_path, scheme_name)
            job.result = result
            job.mode = result.get("mode")
            job.status = "stopped" if result.get("stopped") else "done"
            job.emit({"event": job.status if job.status == "stopped" else "done", "step": "готово" if job.status == "done" else "остановлено", "result": _slim(result), "mode": job.mode})
        except JobStopped:
            job.status = "stopped"
            job.emit({"event": "stopped", "step": "остановлено, матрица по уже оценённым", "result": _slim(job.result or {})})
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", job.id)
            job.status = "error"
            job.error = str(exc)
            job.mode = "error"
            job.emit({"event": "error", "step": "ошибка", "error": str(exc)})
        finally:
            _persist(job)
            db.close()

    threading.Thread(target=work, daemon=True).start()
    return job


def _slim(result: dict[str, Any]) -> dict[str, Any]:
    keep = {
        k: result[k]
        for k in ("download", "downloads", "output_file", "count", "result", "output", "pipeline", "coverage", "mode")
        if k in result
    }
    if "files" in result:
        keep["files"] = result["files"]
    if "suggestions" in result:
        keep["suggestions"] = result["suggestions"]
    return keep


def set_job_control(job_id: str, *, paused: bool | None = None, halt: bool = False) -> Job:
    job = _JOBS.get(job_id)
    if not job:
        raise KeyError(job_id)
    with job.lock:
        if halt:
            job.halt = True
            job.paused = False
            if job.status in {"queued", "running", "paused"}:
                job.status = "stopping"
        elif paused is True:
            job.paused = True
            if job.status == "running":
                job.status = "paused"
            job.emit({"event": "pause", "step": "пауза"})
        elif paused is False:
            job.paused = False
            if job.status == "paused":
                job.status = "running"
            job.emit({"event": "resume", "step": "продолжили"})
    _persist(job)
    return job


def _progress(job: Job) -> Callable[[dict[str, Any]], None]:
    def on(ev: dict[str, Any]) -> None:
        job.wait_gate()
        job.emit(ev)

    return on


def _dispatch(name: str, db, kwargs: dict[str, Any], job: Job, scheme_path: Path | None, scheme_name: str | None) -> dict[str, Any]:
    on = _progress(job)
    if name in {"review-correctness", "review-one"}:
        from specgraph.pipelines.correctness import run_correctness_matrix

        kw = dict(kwargs)
        if name == "review-one":
            ids = list(kw.get("requirement_ids") or [])
            if kw.get("requirement_id"):
                ids = [kw["requirement_id"]]
            kw["requirement_ids"] = ids[:1]
        return run_correctness_matrix(db, on_progress=on, run_id=job.id, **kw)
    if name == "unit-tests":
        from specgraph.pipelines.unit_tests import run_unit_tests

        return run_unit_tests(db, on_progress=on, **kwargs)
    if name == "schematic-coverage":
        from specgraph.pipelines.schematic import run_schematic_coverage

        if not scheme_path:
            raise ValueError("нужен файл схемы")
        return run_schematic_coverage(db, scheme_path, scheme_name or scheme_path.name, on_progress=on, **kwargs)
    from specgraph.pipelines.graphs import run_pipeline

    return run_pipeline(name, db, on_progress=on, **kwargs)


def iter_events(job: Job, start: int = 0):
    i = start
    while True:
        with job.lock:
            chunk = job.events[i:]
            status = job.status
        for ev in chunk:
            yield ev
            i += 1
        if status in {"done", "error"} and i >= len(job.events):
            return
        time.sleep(0.15)


def ndjson(job: Job):
    for ev in iter_events(job):
        yield json.dumps(ev, ensure_ascii=False) + "\n"
