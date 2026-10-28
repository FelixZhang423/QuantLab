from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dict_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError(f"expected mapping, got {type(value).__name__}")


@dataclass
class ResearchSpec:
    objective: str
    pool_id: str = ""
    target_horizon: int = 20
    holding_period: int = 20
    factor_style: list[str] = field(default_factory=list)
    preferred_fields: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    success_criteria: dict[str, Any] = field(default_factory=dict)
    identity_lock: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchSpec":
        objective = str(payload.get("objective", "")).strip()
        if not objective:
            raise ValueError("ResearchSpec.objective is required")
        return cls(
            objective=objective,
            pool_id=str(payload.get("pool_id", "")),
            target_horizon=int(payload.get("target_horizon", 20)),
            holding_period=int(payload.get("holding_period", 20)),
            factor_style=[str(item) for item in _list_value(payload.get("factor_style"))],
            preferred_fields=[str(item) for item in _list_value(payload.get("preferred_fields"))],
            metrics=[str(item) for item in _list_value(payload.get("metrics"))],
            constraints=[str(item) for item in _list_value(payload.get("constraints"))],
            success_criteria=_dict_value(payload.get("success_criteria")),
            identity_lock=_dict_value(payload.get("identity_lock")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateExpression:
    candidate_id: str
    expression: str
    hypothesis_id: str = ""
    expected_direction: str = "unknown"
    rationale: str = ""
    canonical_hint: str = ""
    used_fields: list[str] = field(default_factory=list)
    used_operators: list[str] = field(default_factory=list)
    complexity_estimate: int = 0
    risk_flags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CandidateExpression":
        candidate_id = str(payload.get("candidate_id", "")).strip()
        expression = str(payload.get("expression", "")).strip()
        if not candidate_id:
            raise ValueError("CandidateExpression.candidate_id is required")
        if not expression:
            raise ValueError("CandidateExpression.expression is required")
        return cls(
            candidate_id=candidate_id,
            expression=expression,
            hypothesis_id=str(payload.get("hypothesis_id", "")),
            expected_direction=str(payload.get("expected_direction", "unknown")),
            rationale=str(payload.get("rationale", "")),
            canonical_hint=str(payload.get("canonical_hint", "")),
            used_fields=[str(item) for item in _list_value(payload.get("used_fields"))],
            used_operators=[str(item) for item in _list_value(payload.get("used_operators"))],
            complexity_estimate=int(payload.get("complexity_estimate", 0) or 0),
            risk_flags=[str(item) for item in _list_value(payload.get("risk_flags"))],
            metadata=_dict_value(payload.get("metadata")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchDebate:
    evidence_advocate: list[str] = field(default_factory=list)
    skeptical_reviewer: list[str] = field(default_factory=list)
    risk_judge: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchDebate":
        return cls(
            evidence_advocate=[str(item) for item in _list_value(payload.get("evidence_advocate"))],
            skeptical_reviewer=[str(item) for item in _list_value(payload.get("skeptical_reviewer"))],
            risk_judge=_dict_value(payload.get("risk_judge")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchSession:
    session_id: str
    research_spec: dict[str, Any]
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "created"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchSession":
        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            raise ValueError("ResearchSession.session_id is required")
        return cls(
            session_id=session_id,
            research_spec=_dict_value(payload.get("research_spec")),
            context_snapshot=_dict_value(payload.get("context_snapshot")),
            status=str(payload.get("status", "created")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
