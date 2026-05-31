from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.workflows.checkpoints import CheckpointRegistry


@dataclass
class WorkflowContext:
    job_id: str
    profile_id: str
    page: Any
    repo: AutomationRepository
    checkpoints: CheckpointRegistry
    otp_provider: Any | None = None
    session_manager: Any | None = None
    proxy: Any | None = None
    data: dict[str, Any] = field(default_factory=dict)
