"""
Ingestion job queue — manages async ingest jobs with status tracking.

Each ingest request (file upload, URL paste) creates a job that runs
in a FastAPI background task. The frontend polls job status via
GET /ingest/status/{job_id}.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger("vanilla.ingestion.queue")


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class IngestJob:
    job_id: str
    source_type: str  # "pdf" | "url" | "md"
    source_path: Optional[str] = None  # For file uploads
    source_url: Optional[str] = None  # For URL ingestion
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    output_path: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "progress": self.progress,
            "output_path": self.output_path,
            "error": self.error,
            "source_type": self.source_type,
        }


class IngestJobQueue:
    """
    In-memory job queue for ingestion operations.

    Jobs are tracked by job_id. Completed jobs are kept for 1 hour
    for status polling, then cleaned up.
    """

    def __init__(self):
        self._jobs: Dict[str, IngestJob] = {}

    def create_job(
        self,
        source_type: str,
        source_path: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> IngestJob:
        """Create a new ingest job and return it."""
        job_id = f"ingest_{uuid.uuid4().hex[:12]}"
        job = IngestJob(
            job_id=job_id,
            source_type=source_type,
            source_path=source_path,
            source_url=source_url,
        )
        self._jobs[job_id] = job
        logger.info("Created ingest job: %s (%s)", job_id, source_type)
        return job

    def get_job(self, job_id: str) -> Optional[IngestJob]:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def update_job(
        self,
        job_id: str,
        status: Optional[JobStatus] = None,
        progress: Optional[float] = None,
        output_path: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update job status."""
        job = self._jobs.get(job_id)
        if not job:
            return
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if output_path is not None:
            job.output_path = output_path
        if error is not None:
            job.error = error
        if status in (JobStatus.COMPLETE, JobStatus.ERROR):
            job.completed_at = time.time()

    def get_active_jobs(self) -> list:
        """Get all pending/processing jobs."""
        return [
            j.to_dict() for j in self._jobs.values()
            if j.status in (JobStatus.PENDING, JobStatus.PROCESSING)
        ]

    def cleanup_old_jobs(self, max_age_seconds: int = 3600) -> int:
        """Remove completed/errored jobs older than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        to_remove = [
            jid for jid, j in self._jobs.items()
            if j.completed_at and j.completed_at < cutoff
        ]
        for jid in to_remove:
            del self._jobs[jid]
        return len(to_remove)


# Singleton instance
ingest_queue = IngestJobQueue()
