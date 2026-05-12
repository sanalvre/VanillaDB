"""
Pydantic response models for the FastAPI sidecar.

These define the API contract between the React frontend and the Python backend.
"""

from typing import Optional
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str  # "ok"


class LastRun(BaseModel):
    id: str
    completed_at: int  # unix timestamp
    tokens_used: int
    warnings: list = []


class StatusResponse(BaseModel):
    agent_status: str  # "idle" | "running" | "error"
    current_phase: Optional[str] = None  # "ingest" | "analysis" | "proposal" | "fileback"
    last_run: Optional[LastRun] = None
    pending_proposals: int = 0
    last_run_warnings: list = []


class VaultStructureResponse(BaseModel):
    initialized: bool
    clean_vault_path: Optional[str] = None
    wiki_vault_path: Optional[str] = None


class VaultCreateRequest(BaseModel):
    base_path: str
    ontology_content: Optional[str] = None
    agents_content: Optional[str] = None


class VaultCreateResponse(BaseModel):
    success: bool
    clean_vault_path: str
    wiki_vault_path: str


class FileEventRequest(BaseModel):
    path: str
    event_type: str  # "create" | "modify" | "delete"
    timestamp: int


class IngestUrlRequest(BaseModel):
    url: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # "pending" | "processing" | "complete" | "error"
    progress: float = 0.0
    output_path: Optional[str] = None
    error: Optional[str] = None


class LLMValidateRequest(BaseModel):
    provider: str  # "openai" | "anthropic" | "openrouter" | "ollama"
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # for Ollama
    model: Optional[str] = None
    transcription_api_key: Optional[str] = None  # separate OpenAI key for Whisper
    groq_transcription_key: Optional[str] = None  # Groq key for whisper-large-v3


class LLMValidateResponse(BaseModel):
    valid: bool
    error: Optional[str] = None


class OnboardingGenerateRequest(BaseModel):
    description: str
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None


class OnboardingGenerateResponse(BaseModel):
    ontology_md: str
    agents_md: str
    suggested_categories: list[str]


class ProposalApproveRequest(BaseModel):
    """Request body for approving a proposal batch (currently no fields needed)."""
    pass


class ProposalRejectRequest(BaseModel):
    """Request body for rejecting a proposal batch."""
    reason: Optional[str] = None


class ProposalActionResponse(BaseModel):
    """Response from approve/reject endpoints."""
    batch_id: str
    status: str  # "approved" | "rejected"
    articles_written: int = 0
    errors: list[str] = []


class RunPipelineResponse(BaseModel):
    """Response from run-now endpoint when pipeline is triggered."""
    run_id: Optional[str] = None
    dispatched: int = 0
    already_running: bool = False


class FileTreeNode(BaseModel):
    name: str
    path: str
    type: str  # "file" | "directory"
    children: list["FileTreeNode"] = []


FileTreeNode.model_rebuild()


class FileContentResponse(BaseModel):
    path: str
    content: str


class FileWriteRequest(BaseModel):
    path: str
    content: str


# ─── Sync Models ──────────────────────────────────────────────────

class SyncStatusResponse(BaseModel):
    is_repo: bool
    has_remote: bool
    remote_url: Optional[str] = None
    last_commit_hash: Optional[str] = None
    last_commit_message: Optional[str] = None
    last_commit_time: Optional[int] = None  # unix timestamp
    dirty_files: int = 0
    ahead: int = 0
    behind: int = 0
    branch: Optional[str] = None
    error: Optional[str] = None


class SyncConfigRequest(BaseModel):
    remote_url: str


class SyncActionResponse(BaseModel):
    success: bool
    committed: bool = False
    pushed: bool = False
    files_changed: int = 0
    error: Optional[str] = None
