#!/usr/bin/env python3
"""node_types.py v1.0.0 -- KG Phase 1 DecisionNode + WorkItemSchema (EAG-S332-MVKG-001)"""
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

VERSION = "1.0.0"
EAG_ID  = "EAG-S332-MVKG-001"

VALID_ACTORS = frozenset({"domi", "jeni", "caddy", "beo", "external"})
VALID_WORK_TYPES = frozenset({"DESIGN", "VERIFY", "IMPLEMENT", "TEST", "EAG", "REVIEW"})
VALID_STATUSES = frozenset({"waiting", "ready", "in_progress", "done", "blocked"})
VALID_NODE_STATUSES = frozenset({
    "active", "stale", "quarantine",
    "verified", "rejected", "retired", "archived",
})
VALID_DCS = frozenset({"DC-1", "DC-2", "DC-3", "DC-4"})


@dataclass
class DecisionNode:
    """
    KG Decision Node -- Area 11 decision_ledger entry KG 뷰.
    헌법 Section 3.2 공통 속성 준수. EAG-S332-MVKG-001.
    """
    node_id: str = field(default_factory=lambda: "DN-" + str(uuid.uuid4())[:8])
    node_type: str = "DecisionNode"
    source_schema: str = "decision_ledger_v1"
    source_declared_at: str = ""
    source_actor: str = ""
    source_eag: str = ""
    dc: str = ""
    subject: str = ""
    rationale: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    created_by: str = "connector"
    status: str = "active"
    references: list = field(default_factory=list)
    workitem_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> list:
        """유효성 검증. 오류 메시지 리스트 반환."""
        errors = []
        if self.dc and self.dc not in VALID_DCS:
            errors.append("Invalid dc: " + self.dc)
        if not self.subject:
            errors.append("subject is required")
        if self.status not in VALID_NODE_STATUSES:
            errors.append("Invalid status: " + self.status)
        return errors


@dataclass
class WorkItemSchema:
    """
    WorkItem 스키마 -- Phase 1: 스키마만, 실행 연동 없음.
    헌법 Section 4.10 준수. EAG-S332-MVKG-001.
    """
    work_id: str = field(default_factory=lambda: "WI-" + str(uuid.uuid4())[:8])
    parent_decision_id: str = ""
    actor: str = ""
    work_type: str = ""
    status: str = "waiting"
    depends_on: list = field(default_factory=list)
    sla_deadline: str = ""
    escalate_at: str = ""
    wf05_task_id: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    created_by: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> list:
        """스키마 검증. 오류 메시지 리스트 반환."""
        errors = []
        if self.actor and self.actor not in VALID_ACTORS:
            errors.append("Invalid actor: " + self.actor)
        if self.work_type and self.work_type not in VALID_WORK_TYPES:
            errors.append("Invalid work_type: " + self.work_type)
        if self.status and self.status not in VALID_STATUSES:
            errors.append("Invalid status: " + self.status)
        return errors
