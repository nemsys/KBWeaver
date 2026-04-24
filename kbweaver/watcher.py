"""File watcher — monitors raw/ for new files and triggers ingestion.

Uses watchdog to detect FileCreated and FileMoved events.
Processes files serially via an in-memory queue to avoid
concurrent LLM calls competing for memory (TECH_SPEC §3.1).
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from kbweaver.config import Config
from kbweaver.database import Database
from kbweaver.ingestion import ingest_file
from kbweaver.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class _IngestHandler(FileSystemEventHandler):
    """Watchdog event handler that queues new files for ingestion."""

    def __init__(self, file_queue: queue.Queue[Path]) -> None:
        super().__init__()
        self._queue = file_queue

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            path = Path(event.src_path)
            logger.info("Detected new file: %s", path.name)
            self._queue.put(path)

    def on_moved(self, event: FileMovedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            path = Path(event.dest_path)
            logger.info("Detected moved file: %s", path.name)
            self._queue.put(path)


class FileWatcher:
    """Watches ``raw/`` for new files and processes them serially.

    Usage::

        watcher = FileWatcher(config, db, llm)
        watcher.start()   # blocks until interrupted
    """

    def __init__(self, config: Config, db: Database, llm: LLMProvider) -> None:
        self._config = config
        self._db = db
        self._llm = llm
        self._file_queue: queue.Queue[Path] = queue.Queue()
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start watching and processing. Blocks until interrupted."""
        raw_dir = self._config.raw_dir
        raw_dir.mkdir(parents=True, exist_ok=True)

        handler = _IngestHandler(self._file_queue)
        observer = Observer()
        observer.schedule(handler, str(raw_dir), recursive=False)
        observer.start()

        logger.info("Watching %s for new files... (Ctrl+C to stop)", raw_dir)

        # Process any existing files in raw/
        for existing in sorted(raw_dir.iterdir()):
            if existing.is_file():
                self._file_queue.put(existing)

        try:
            while not self._stop_event.is_set():
                try:
                    file_path = self._file_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                if not file_path.exists():
                    continue

                logger.info("Processing: %s", file_path.name)
                try:
                    result = ingest_file(file_path, self._config, self._db, self._llm)
                    if result.error:
                        logger.error("Ingestion error: %s", result.error)
                except Exception as exc:
                    logger.error("Unexpected error processing %s: %s", file_path.name, exc)

        except KeyboardInterrupt:
            logger.info("Stopping file watcher...")
        finally:
            observer.stop()
            observer.join()

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._stop_event.set()
