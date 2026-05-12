"""
Watcher bridge — receives file system events from Tauri, applies debounce, dispatches to agent queue.

The debounce system:
1. Receives file events from Tauri (via POST /internal/file-event)
2. Per-path debounce: waits 300 seconds (5 minutes) of file stability
3. Content hash verification: computes SHA-256 at debounce end, compares to debounce start
4. If hash matches → file was stable, dispatch to pipeline
5. If hash differs → someone wrote again during debounce, reset timer
6. "Run agent now" bypasses debounce for all queued files

The bridge also checks sync_writes table to prevent double-triggering
when Supabase sync writes a file that the watcher picks up.
"""

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from services.paths import normalize_path
from db.repository import is_recent_sync_write

logger = logging.getLogger("vanilla.watcher_bridge")

# Default debounce: 300 seconds (5 minutes)
DEFAULT_DEBOUNCE_SECONDS = 300


def _compute_file_hash(file_path: str) -> Optional[str]:
    """Compute SHA-256 hash of a file's content. Returns None if file doesn't exist."""
    try:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except (OSError, FileNotFoundError):
        return None


class FileEvent:
    """Represents a file system event received from Tauri."""

    def __init__(self, path: str, event_type: str, timestamp: int):
        self.path = normalize_path(path)
        self.event_type = event_type  # "create" | "modify" | "delete"
        self.timestamp = timestamp
        self.hash_at_start: Optional[str] = None


class WatcherBridge:
    """
    Manages the debounce queue for file system events.

    Usage:
        bridge = WatcherBridge(debounce_seconds=300, on_ready=my_callback)
        await bridge.start()
        await bridge.push_event(FileEvent(...))
        # ... later:
        await bridge.stop()
    """

    def __init__(
        self,
        debounce_seconds: int = DEFAULT_DEBOUNCE_SECONDS,
        on_ready: Optional[Callable] = None,
        vault_root: str = "",
    ):
        self.debounce_seconds = debounce_seconds
        self.on_ready = on_ready  # Called when a file passes debounce
        self.vault_root = vault_root

        # Per-path tracking: {normalized_path: FileEvent}
        self._pending: Dict[str, FileEvent] = {}
        # Per-path timer tasks: {normalized_path: asyncio.Task}
        self._timers: Dict[str, asyncio.Task] = {}
        # Paths that have been dispatched (to avoid re-dispatch)
        self._dispatched: Set[str] = set()

        self._running = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def start(self) -> None:
        """Start the bridge's background consumer loop."""
        self._running = True
        asyncio.create_task(self._consume_loop())
        logger.info("WatcherBridge started (debounce=%ds)", self.debounce_seconds)

    async def stop(self) -> None:
        """Stop the bridge and cancel all pending timers."""
        self._running = False
        for task in self._timers.values():
            task.cancel()
        self._timers.clear()
        self._pending.clear()
        logger.info("WatcherBridge stopped")

    async def push_event(self, event: FileEvent) -> bool:
        """
        Push a file event into the debounce queue.

        Returns False if the event was skipped (e.g., sync write).
        """
        # Check if this was a sync write (prevents double-trigger)
        if is_recent_sync_write(event.path):
            logger.debug("Skipping sync write: %s", event.path)
            return False

        await self._queue.put(event)
        return True

    async def force_dispatch_all(self) -> int:
        """
        Bypass debounce and dispatch all pending files immediately.
        Used by the "Run agent now" command.

        Returns number of files dispatched.
        """
        count = 0
        paths = list(self._pending.keys())
        for path in paths:
            # Cancel existing timer
            if path in self._timers:
                self._timers[path].cancel()
                del self._timers[path]
            # Dispatch immediately
            event = self._pending.pop(path, None)
            if event and self.on_ready:
                self._dispatched.add(path)
                await self._dispatch(event)
                count += 1
        logger.info("Force-dispatched %d files", count)
        return count

    def get_pending_paths(self) -> list:
        """Get all paths currently waiting in the debounce queue."""
        return list(self._pending.keys())

    def get_pending_count(self) -> int:
        """Get the number of files waiting in the debounce queue."""
        return len(self._pending)

    async def _consume_loop(self) -> None:
        """Background loop that processes incoming events."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._handle_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Error in consume loop: %s", e)

    async def _handle_event(self, event: FileEvent) -> None:
        """Handle a single file event: start or reset debounce timer."""
        path = event.path

        # Record content hash at the start of debounce
        if self.vault_root:
            abs_path = str(Path(self.vault_root) / path)
        else:
            abs_path = path
        event.hash_at_start = _compute_file_hash(abs_path)

        # Cancel existing timer for this path (resets debounce)
        if path in self._timers:
            self._timers[path].cancel()
            logger.debug("Reset debounce timer for: %s", path)

        # Store event and start new timer
        self._pending[path] = event
        self._dispatched.discard(path)
        self._timers[path] = asyncio.create_task(
            self._debounce_timer(path, event)
        )

    async def _debounce_timer(self, path: str, event: FileEvent) -> None:
        """Wait for debounce period, then verify content hash and dispatch."""
        try:
            await asyncio.sleep(self.debounce_seconds)
        except asyncio.CancelledError:
            return  # Timer was reset by a new event

        # Debounce period complete — verify content hash
        if self.vault_root:
            abs_path = str(Path(self.vault_root) / path)
        else:
            abs_path = path

        current_hash = _compute_file_hash(abs_path)

        if event.event_type == "delete":
            # File was deleted — dispatch regardless of hash
            pass
        elif current_hash != event.hash_at_start:
            # Content changed during debounce — reset timer
            logger.info("Content changed during debounce, resetting: %s", path)
            # Re-queue the event with updated hash
            new_event = FileEvent(path, event.event_type, int(time.time()))
            await self._queue.put(new_event)
            return

        # Content stable — dispatch
        pending_event = self._pending.pop(path, None)
        self._timers.pop(path, None)

        if pending_event and path not in self._dispatched:
            self._dispatched.add(path)
            await self._dispatch(pending_event)

    async def _dispatch(self, event: FileEvent) -> None:
        """Dispatch a verified stable file event to the pipeline callback."""
        logger.info("Dispatching: %s (%s)", event.path, event.event_type)
        if self.on_ready:
            try:
                result = self.on_ready(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("Dispatch callback error for %s: %s", event.path, e)
