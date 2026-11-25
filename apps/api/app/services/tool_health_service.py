from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuditActorType, JobType, ToolType
from app.models import AuditEvent, Job, Tool
from app.models.base import utcnow
from app.schemas.tool import ToolHealthResponse
from app.services.audit_service import AuditService
from app.services.job_service import JobProcessingError, JobService
from app.tools.github_adapter import GitHubToolAdapter
from app.tools.jira_adapter import JiraToolAdapter
from app.tools.mcp_adapter import MCPToolAdapter

CONNECTOR_HEALTH_CHECK_QUEUED_EVENT = "connector_health_check.queued"
CONNECTOR_HEALTH_CHECK_COMPLETED_EVENT = "connector_health_check.completed"
CONNECTOR_HEALTH_PROBE_RECORDED_EVENT = "connector_health_probe.recorded"


@dataclass(frozen=True, slots=True)
class ToolProbeObservation:
    status: str
    checked_at: datetime
    probe_performed: bool
    can_connect: bool | None = None
    error_summary: str | None = None
    source: str | None = None


class ToolHealthService:
    def __init__(
        self,
        github_adapter: GitHubToolAdapter | None = None,
        jira_adapter: JiraToolAdapter | None = None,
        mcp_adapter: MCPToolAdapter | None = None,
    ) -> None:
        self.audit_service = AuditService()
        self.job_service = JobService()
        self.github_adapter = github_adapter or GitHubToolAdapter()
        self.jira_adapter = jira_adapter or JiraToolAdapter()
        self.mcp_adapter = mcp_adapter or MCPToolAdapter()

    def check(self, *, tool, probe: bool = False) -> ToolHealthResponse:
        if tool.type == ToolType.GITHUB:
            result = self.github_adapter.health_check(
                base_url=tool.base_url,
                config=tool.config or {},
                probe=probe,
            )
        elif tool.type == ToolType.JIRA:
            result = self.jira_adapter.health_check(
                base_url=tool.base_url,
                config=tool.config or {},
                probe=probe,
            )
        elif tool.type == ToolType.MCP:
            result = self.mcp_adapter.health_check(
                base_url=tool.base_url,
                config=tool.config or {},
                probe=probe,
            )
        else:
            return ToolHealthResponse(
                tool_id=tool.id,
                tool_name=tool.name,
                tool_type=tool.type,
                status="unsupported",
                adapter=tool.type.value,
                details={"message": "Health checks are only implemented for GitHub, Jira, and MCP tools in this build."},
            )
        details = dict(result.get("details") or {})
        for key in (
            "token_env_var",
            "api_token_env_var",
            "api_key_env_var",
            "email_env_var",
            "secret_reference",
            "repository_allowlist_count",
            "project_allowlist_count",
            "issue_type_allowlist_count",
            "external_project_key_count",
            "allowed_tool_count",
            "blocked_tool_count",
            "transport",
            "trust_domain",
            "max_request_bytes",
            "max_response_bytes",
            "timeout_ms",
            "credentials_configured",
            "app_id",
            "installation_id",
            "private_key_env_var",
            "private_key_reference_type",
            "token_expires_at",
            "cache_hit",
            "warnings",
        ):
            value = result.get(key)
            if value is not None:
                details[key] = value
        return ToolHealthResponse(
            tool_id=tool.id,
            tool_name=tool.name,
            tool_type=tool.type,
            status=result["status"],
            adapter=result["adapter"],
            auth_provider=result.get("auth_provider"),
            token_present=result.get("token_present"),
            probe_performed=result.get("probe_performed", False),
            can_connect=result.get("can_connect"),
            details=details,
        )

    def record_probe_observation(
        self,
        db: Session,
        *,
        tenant_id: str,
        tool,
        response: ToolHealthResponse,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
        source: str = "manual_probe",
    ) -> ToolProbeObservation:
        observation = self._observation_from_response(response=response, checked_at=utcnow(), source=source)
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=CONNECTOR_HEALTH_PROBE_RECORDED_EVENT,
            resource_type="tool",
            resource_id=tool.id,
            metadata={
                "tool_name": tool.name,
                "tool_type": tool.type.value,
                "status": observation.status,
                "probe_performed": observation.probe_performed,
                "can_connect": observation.can_connect,
                "error_summary": observation.error_summary,
                "source": source,
            },
            ip_address=ip_address,
        )
        return observation

    def get_latest_probe_observations(
        self,
        db: Session,
        *,
        tenant_id: str,
        tool_id: str,
    ) -> tuple[ToolProbeObservation | None, datetime | None, datetime | None, str | None]:
        observations: list[ToolProbeObservation] = []

        event_rows = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.event_type == CONNECTOR_HEALTH_PROBE_RECORDED_EVENT,
                    AuditEvent.resource_type == "tool",
                    AuditEvent.resource_id == tool_id,
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(25)
            )
        )
        for event in event_rows:
            metadata = dict(event.metadata_json or {})
            status = str(metadata.get("status") or "").strip()
            if status not in {"ready", "degraded", "unconfigured", "unsupported"}:
                continue
            observations.append(
                ToolProbeObservation(
                    status=status,
                    checked_at=event.created_at,
                    probe_performed=bool(metadata.get("probe_performed")),
                    can_connect=metadata.get("can_connect")
                    if isinstance(metadata.get("can_connect"), bool)
                    else None,
                    error_summary=str(metadata.get("error_summary") or "").strip() or None,
                    source=str(metadata.get("source") or "").strip() or "manual_probe",
                )
            )

        job_rows = list(
            db.scalars(
                select(Job)
                .where(
                    Job.tenant_id == tenant_id,
                    Job.job_type == JobType.CONNECTOR_HEALTH_CHECK_PLACEHOLDER,
                )
                .order_by(Job.created_at.desc())
                .limit(25)
            )
        )
        for job in job_rows:
            observation = self._observation_from_job(job=job, tool_id=tool_id)
            if observation is not None:
                observations.append(observation)

        if not observations:
            return None, None, None, None

        observations.sort(key=lambda item: item.checked_at, reverse=True)
        latest = observations[0]
        latest_success = next((item.checked_at for item in observations if item.status == "ready"), None)
        latest_failure = next((item for item in observations if item.status != "ready"), None)
        return latest, latest_success, latest_failure.checked_at if latest_failure else None, (
            latest_failure.error_summary if latest_failure else None
        )

    def enqueue_connector_health_check_job(
        self,
        db: Session,
        *,
        tenant_id: str,
        config,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
        idempotency_key: str,
        source: str,
        scheduled_task_id: str | None,
    ) -> Job:
        job = self.job_service.enqueue(
            db,
            tenant_id=tenant_id,
            job_type=JobType.CONNECTOR_HEALTH_CHECK_PLACEHOLDER,
            idempotency_key=idempotency_key,
            payload={
                "tool_ids": list(config.tool_ids),
                "probe": bool(config.probe),
                "source": source,
                "scheduled_task_id": scheduled_task_id,
                "ip_address": ip_address,
            },
            max_attempts=1,
        )
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=CONNECTOR_HEALTH_CHECK_QUEUED_EVENT,
            resource_type="job",
            resource_id=job.id,
            metadata={
                "job_id": job.id,
                "source": source,
                "scheduled_task_id": scheduled_task_id,
            },
            ip_address=ip_address,
        )
        return job

    def handle_connector_health_check_job(self, db: Session, *, job: Job) -> None:
        payload = job.payload or {}
        tool_ids = payload.get("tool_ids") or []
        if not isinstance(tool_ids, list):
            raise JobProcessingError(
                detail="Connector health check job payload is invalid.",
                code="connector_health_check_job_invalid",
                retryable=False,
            )
        probe = bool(payload.get("probe", False))
        query = select(Tool).where(Tool.tenant_id == job.tenant_id).order_by(Tool.created_at.asc())
        unique_tool_ids = [str(item) for item in tool_ids if str(item).strip()]
        if unique_tool_ids:
            query = query.where(Tool.id.in_(list(dict.fromkeys(unique_tool_ids))))
        tools = list(db.scalars(query))
        results = [self.check(tool=tool, probe=probe).model_dump(mode="json") for tool in tools]
        degraded = sum(1 for item in results if item["status"] in {"degraded", "unconfigured"})
        unsupported = sum(1 for item in results if item["status"] == "unsupported")
        job.payload = {
            **payload,
            "result": {
                "probe": probe,
                "checked_tools": len(results),
                "degraded_tools": degraded,
                "unsupported_tools": unsupported,
                "results": results,
            },
        }
        self.audit_service.create_event(
            db,
            tenant_id=job.tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=CONNECTOR_HEALTH_CHECK_COMPLETED_EVENT,
            resource_type="job",
            resource_id=job.id,
            metadata={
                "job_id": job.id,
                "checked_tools": len(results),
                "degraded_tools": degraded,
                "unsupported_tools": unsupported,
                "source": payload.get("source"),
                "scheduled_task_id": payload.get("scheduled_task_id"),
            },
            ip_address=str(payload.get("ip_address") or "").strip() or None,
        )

    def _observation_from_response(
        self,
        *,
        response: ToolHealthResponse,
        checked_at: datetime,
        source: str,
    ) -> ToolProbeObservation:
        details = dict(response.details or {})
        error_summary = self._extract_error_summary(
            status=response.status,
            probe_performed=response.probe_performed,
            can_connect=response.can_connect,
            details=details,
        )
        return ToolProbeObservation(
            status=response.status,
            checked_at=checked_at,
            probe_performed=response.probe_performed,
            can_connect=response.can_connect,
            error_summary=error_summary,
            source=source,
        )

    def _observation_from_job(self, *, job: Job, tool_id: str) -> ToolProbeObservation | None:
        payload = dict(job.payload or {})
        result = dict(payload.get("result") or {})
        rows = result.get("results")
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict) or str(row.get("tool_id") or "").strip() != tool_id:
                continue
            status = str(row.get("status") or "").strip()
            if status not in {"ready", "degraded", "unconfigured", "unsupported"}:
                return None
            details = dict(row.get("details") or {})
            checked_at = job.completed_at or job.updated_at or job.created_at
            return ToolProbeObservation(
                status=status,
                checked_at=checked_at,
                probe_performed=bool(row.get("probe_performed")),
                can_connect=row.get("can_connect") if isinstance(row.get("can_connect"), bool) else None,
                error_summary=self._extract_error_summary(
                    status=status,
                    probe_performed=bool(row.get("probe_performed")),
                    can_connect=row.get("can_connect") if isinstance(row.get("can_connect"), bool) else None,
                    details=details,
                ),
                source="health_check_job",
            )
        return None

    def _extract_error_summary(
        self,
        *,
        status: str,
        probe_performed: bool,
        can_connect: bool | None,
        details: dict,
    ) -> str | None:
        explicit = str(details.get("error_detail") or "").strip()
        if explicit:
            return explicit
        warnings = details.get("warnings")
        if isinstance(warnings, list):
            for item in warnings:
                message = str(item or "").strip()
                if message:
                    return message
        if status == "ready":
            return None
        if probe_performed and can_connect is False:
            return "The latest live connector probe could not reach the upstream service successfully."
        if status == "unconfigured":
            return "The latest connector probe could not run a live check because required live credentials are not configured."
        if status == "unsupported":
            return "This connector type does not support a live health probe in the current build."
        return "The latest connector probe still needs operator attention before live use."
