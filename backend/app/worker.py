"""Background worker: consumes the run queue and runs the daily scheduler.

Scale out by running more replicas (`python -m app.worker`): runs are claimed with
FOR UPDATE SKIP LOCKED so each is executed once, and scheduling is guarded by an advisory lock.
The API can also host one worker in-process (EMBEDDED_WORKER=true) for single-service deploys.
"""

import asyncio
import os
import signal
import socket

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.agents.tracker import follow_up_sweep
from app.config import settings
from app.logging import configure_logging, log
from app.services.ingest import ingest_tick
from app.services.evidence_refresh import refresh_evidence
from app.services.payments import expire_plans
from app.services.quota import weekly_report
from app.services.retention import retention_sweep
from app.services.whatsapp import digest_sweep
from app.sources.authenticity import reverify_jobs
from app.services.runs import (
    claim_next,
    close_graph,
    enqueue_research_runs,
    enqueue_scheduled_runs,
    execute_run,
    get_graph,
)

WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "2"))


class Worker:
    def __init__(self) -> None:
        self.id = f"{socket.gethostname()}:{os.getpid()}"
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    async def _slot(self, n: int) -> None:
        while not self._stop.is_set():
            try:
                claimed = await claim_next(f"{self.id}#{n}")
            except Exception:
                log.exception("worker.claim_failed")
                claimed = None
            if claimed is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=settings.worker_poll_seconds)
                except TimeoutError:
                    pass
                continue
            status = await execute_run(claimed.id, claimed.user_id)
            log.info("worker.run_done", run_id=str(claimed.id), status=status)

    async def start(self) -> None:
        await get_graph()
        self.scheduler.add_job(enqueue_scheduled_runs, "cron", minute=0, id="daily-runs", replace_existing=True)
        self.scheduler.add_job(follow_up_sweep, "cron", minute=15, id="follow-ups", replace_existing=True)
        # Researcher: re-run the agents for each user every research_interval_hours (checked twice an hour).
        self.scheduler.add_job(enqueue_research_runs, "cron", minute="5,35", id="research", replace_existing=True)
        # Shared ingestion: every minute each worker fetches a slice of the due boards / feeds / searches (once for
        # all users) and wakes only the users a new job is close to. More replicas = more targets per minute.
        self.scheduler.add_job(ingest_tick, "cron", minute="*", id="ingest", replace_existing=True, max_instances=1)
        # Authenticity: re-open aggregator apply links daily; closed listings drop off the board.
        self.scheduler.add_job(reverify_jobs, "cron", minute=45, id="reverify", replace_existing=True, max_instances=1)
        # Retention: old traces / notifications / unmatched closed jobs / expired demo accounts (advisory-locked).
        self.scheduler.add_job(retention_sweep, "cron", hour=2, minute=30, id="retention", replace_existing=True, max_instances=1)
        # WhatsApp digest: hourly, each user at the hour they picked (no-op until the WHATSAPP_* keys are set).
        self.scheduler.add_job(digest_sweep, "cron", minute=2, id="whatsapp-digest", replace_existing=True, max_instances=1)
        self.scheduler.add_job(expire_plans, "cron", minute=50, id="expire-plans", replace_existing=True, max_instances=1)
        # Mondays 09:00 IST: "we skipped N weak or risky matches for you".
        self.scheduler.add_job(weekly_report, "cron", day_of_week="mon", hour=3, minute=30, id="weekly-report", replace_existing=True, max_instances=1)
        # Proof-of-skills pack: re-read linked GitHub / Codeforces profiles once a week.
        self.scheduler.add_job(refresh_evidence, "cron", hour=4, minute=20, id="evidence", replace_existing=True, max_instances=1)
        self.scheduler.start()
        self._tasks = [asyncio.create_task(self._slot(i)) for i in range(WORKER_CONCURRENCY)]
        log.info("worker.started", worker=self.id, slots=WORKER_CONCURRENCY)

    async def stop(self) -> None:
        self._stop.set()
        self.scheduler.shutdown(wait=False)
        # Let in-flight runs finish their current step; anything cut off is resumed from its checkpoint.
        await asyncio.wait(self._tasks, timeout=30)
        for t in self._tasks:
            t.cancel()
        await close_graph()
        log.info("worker.stopped", worker=self.id)


async def main() -> None:
    from app.main import init_sentry

    configure_logging()
    init_sentry("worker")
    worker = Worker()
    await worker.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
