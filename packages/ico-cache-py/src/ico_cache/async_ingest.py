import asyncio
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from .loaders.auto_loader import AutoLoader
from .core.cache_engine import CacheEngine
from .core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.async_ingest")


class IngestionJob(BaseModel):
    job_id: str
    tenant_id: str
    file_path: str
    file_size_bytes: int
    status: str = "queued"  # queued, processing, completed, failed
    is_async: bool = False
    chunks_total: int = 0
    chunks_processed: int = 0
    created_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
    elapsed_s: float = 0.0
    error: Optional[str] = None


class IngestionJobManager:
    """
    Manages synchronous and asynchronous document ingestion.
    Files exceeding async_threshold_bytes (default 1MB) are ingested
    asynchronously in background tasks with queryable job status.
    """

    def __init__(self, async_threshold_bytes: int = 1 * 1024 * 1024):
        self.async_threshold_bytes = async_threshold_bytes
        self.jobs: Dict[str, IngestionJob] = {}
        self._lock = threading.Lock()

    def get_job(self, job_id: str) -> Optional[IngestionJob]:
        with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status == "processing":
                job.elapsed_s = time.time() - job.created_at
            return job

    def list_jobs(self, tenant_id: Optional[str] = None) -> Dict[str, IngestionJob]:
        with self._lock:
            if tenant_id:
                return {k: v for k, v in self.jobs.items() if v.tenant_id == tenant_id}
            return dict(self.jobs)

    def submit_ingest(
        self,
        file_path: str,
        tenant_id: str,
        cache_engine: CacheEngine,
        schema: Optional[MetadataSchema] = None,
        force_async: Optional[bool] = None,
    ) -> IngestionJob:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = os.path.getsize(file_path)
        job_id = str(uuid.uuid4())
        should_async = force_async if force_async is not None else (file_size >= self.async_threshold_bytes)

        job = IngestionJob(
            job_id=job_id,
            tenant_id=tenant_id,
            file_path=file_path,
            file_size_bytes=file_size,
            status="processing",
            is_async=should_async,
            created_at=time.time(),
        )

        with self._lock:
            self.jobs[job_id] = job

        if should_async:
            # Dispatch background worker thread
            worker = threading.Thread(
                target=self._run_ingest,
                args=(job_id, file_path, tenant_id, cache_engine, schema),
                daemon=True,
            )
            worker.start()
            return job
        else:
            # Run synchronously
            self._run_ingest(job_id, file_path, tenant_id, cache_engine, schema)
            with self._lock:
                return self.jobs[job_id]

    def _run_ingest(
        self,
        job_id: str,
        file_path: str,
        tenant_id: str,
        cache_engine: CacheEngine,
        schema: Optional[MetadataSchema] = None,
    ):
        start_t = time.time()
        try:
            loader = AutoLoader(schema=schema)
            chunks = loader.load(file_path)

            with self._lock:
                job = self.jobs[job_id]
                job.chunks_total = len(chunks)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                for idx, chunk in enumerate(chunks):
                    dummy_resp = {
                        "content": chunk.text[:200],
                        "source": chunk.source_file,
                        "section": chunk.page_or_section,
                    }
                    cache_engine.set_l1(chunk.text[:100], dummy_resp, meta=chunk.metadata, tenant_id=tenant_id)
                    loop.run_until_complete(
                        cache_engine.async_write_l2(
                            chunk.text[:100], dummy_resp, meta=chunk.metadata, tenant_id=tenant_id
                        )
                    )
                    with self._lock:
                        job.chunks_processed = idx + 1
            finally:
                loop.close()

            with self._lock:
                job = self.jobs[job_id]
                job.status = "completed"
                job.completed_at = time.time()
                job.elapsed_s = job.completed_at - start_t
                logger.info(f"Ingestion job {job_id} completed: {job.chunks_processed} chunks in {job.elapsed_s:.2f}s")

        except Exception as e:
            with self._lock:
                job = self.jobs[job_id]
                job.status = "failed"
                job.completed_at = time.time()
                job.elapsed_s = job.completed_at - start_t
                job.error = str(e)
            logger.error(f"Ingestion job {job_id} failed: {e}", exc_info=True)


job_manager = IngestionJobManager()
