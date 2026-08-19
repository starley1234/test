"""Фоновые прогоны пайплайнов: события + токены. Изоляция по run_id."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

log = logging.getLogger("specgraph.jobs")


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
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, ev: dict[str, Any]) -> None:
        with self.lock:
            u = ev.get("tokens") or {}
            if u:
                self.tokens["prompt"] += int(u.get("prompt") or 0)
                self.tokens["completion"] += int(u.get("completion") or 0)
                self.tokens["total"] = self.tokens["prompt"] + self.tokens["completion"]
            ev = {**ev, "tokens_total": dict(self.tokens)}
            self.events.append(ev)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "name": self.name,
                "status": self.status,
                "tokens": dict(self.tokens),
                "events": list(self.events),
                "result": self.result,
                "error": self.error,
            }


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def get_job(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def _progress(job: Job) -> Callable[[dict[str, Any]], None]:
    return job.emit


def start_job(
    name: str,
    kwargs: dict[str, Any],
    *,
    scheme_path: Path | None = None,
    scheme_name: str | None = None,
    user_id: int | None = None,
) -> Job:
    job = Job(id=uuid4().hex[:12], name=name, user_id=user_id)
    with _JOBS_LOCK:
        _JOBS[job.id] = job

    def work() -> None:
        from specgraph.db import SessionLocal

        db = SessionLocal()
        try:
            job.status = "running"
            job.emit({"event": "start", "pipeline": name, "step": "старт"})
            result = _dispatch(name, db, kwargs, job, scheme_path, scheme_name)
            job.result = result
            job.status = "done"
            job.emit({"event": "done", "step": "готово", "result": _slim(result)})
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", job.id)
            job.status = "error"
            job.error = str(exc)
            job.emit({"event": "error", "step": "ошибка", "error": str(exc)})
        finally:
            db.close()

    threading.Thread(target=work, daemon=True).start()
    return job


def _slim(result: dict[str, Any]) -> dict[str, Any]:
    keep = {k: result[k] for k in ("download", "output_file", "count", "result", "output", "pipeline", "coverage") if k in result}
    if "files" in result:
        keep["files"] = result["files"]
    return keep


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
        return run_correctness_matrix(db, on_progress=on, **kw)
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
