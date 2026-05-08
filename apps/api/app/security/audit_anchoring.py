from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

try:  # pragma: no cover - exercised indirectly in environments with boto3 available
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - fallback for lighter local test environments
    boto3 = None
    BotoConfig = None

    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        response: dict[str, Any] = {}

from app.core.config import get_settings
from app.core.enums import AuditIntegrityCheckpointType
from app.security.secret_references import SecretResolutionError, get_secret_resolver


@dataclass(slots=True)
class AuditAnchorError(Exception):
    detail: str
    code: str
    retryable: bool

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.detail


@dataclass(frozen=True, slots=True)
class AuditAnchorWriteResult:
    destination_ref: str
    metadata: dict[str, Any]


class AuditAnchorAdapter(Protocol):
    checkpoint_type: AuditIntegrityCheckpointType

    def write_document(
        self,
        *,
        checkpoint_id: str,
        tenant_id: str,
        document: dict[str, Any],
    ) -> AuditAnchorWriteResult:
        ...

    def read_document(self, *, destination_ref: str) -> dict[str, Any]:
        ...


class LocalAuditAnchorAdapter:
    checkpoint_type = AuditIntegrityCheckpointType.LOCAL

    def __init__(self, *, base_dir: str) -> None:
        self.base_dir = Path(base_dir).resolve()

    def write_document(
        self,
        *,
        checkpoint_id: str,
        tenant_id: str,
        document: dict[str, Any],
    ) -> AuditAnchorWriteResult:
        relative_path = Path(tenant_id) / f"{checkpoint_id}.json"
        target_path = self._resolve_relative_path(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        target_path.write_text(payload, encoding="utf-8")
        return AuditAnchorWriteResult(
            destination_ref=f"local://audit-integrity/{relative_path.as_posix()}",
            metadata={"ref_kind": "local_file"},
        )

    def read_document(self, *, destination_ref: str) -> dict[str, Any]:
        parsed = urlparse(destination_ref)
        if parsed.scheme != "local" or parsed.netloc != "audit-integrity":
            raise AuditAnchorError(
                detail="Checkpoint destination reference is invalid for the local anchor adapter.",
                code="audit_integrity_anchor_destination_invalid",
                retryable=False,
            )
        relative_path = Path(parsed.path.lstrip("/"))
        source_path = self._resolve_relative_path(relative_path)
        try:
            return json.loads(source_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AuditAnchorError(
                detail="Checkpoint document was not found in local anchor storage.",
                code="audit_integrity_anchor_document_missing",
                retryable=False,
            ) from exc
        except ValueError as exc:
            raise AuditAnchorError(
                detail="Checkpoint document in local anchor storage is invalid.",
                code="audit_integrity_anchor_document_invalid",
                retryable=False,
            ) from exc

    def _resolve_relative_path(self, relative_path: Path) -> Path:
        candidate = (self.base_dir / relative_path).resolve()
        if not candidate.is_relative_to(self.base_dir):
            raise AuditAnchorError(
                detail="Checkpoint destination path is invalid.",
                code="audit_integrity_anchor_destination_invalid",
                retryable=False,
            )
        return candidate


class S3AuditAnchorAdapter:
    checkpoint_type = AuditIntegrityCheckpointType.OBJECT_STORAGE

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str | None,
        region: str,
        endpoint_url: str | None,
        access_key_id_ref: str | None,
        secret_access_key_ref: str | None,
        session_token_ref: str | None,
    ) -> None:
        self.bucket = bucket
        self.prefix = str(prefix or "").strip().strip("/")
        self.region = region
        self.endpoint_url = endpoint_url
        self.access_key_id_ref = access_key_id_ref
        self.secret_access_key_ref = secret_access_key_ref
        self.session_token_ref = session_token_ref

    def write_document(
        self,
        *,
        checkpoint_id: str,
        tenant_id: str,
        document: dict[str, Any],
    ) -> AuditAnchorWriteResult:
        key = self._key_for_checkpoint(tenant_id=tenant_id, checkpoint_id=checkpoint_id)
        payload = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            response = self._client().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentType="application/json",
            )
        except (BotoCoreError, ClientError) as exc:
            raise self._map_boto_error(exc) from exc
        metadata: dict[str, Any] = {"ref_kind": "s3"}
        if response.get("ETag"):
            metadata["etag"] = str(response["ETag"]).strip('"')
        if response.get("VersionId"):
            metadata["version_id"] = str(response["VersionId"])
        return AuditAnchorWriteResult(
            destination_ref=f"s3://{self.bucket}/{key}",
            metadata=metadata,
        )

    def read_document(self, *, destination_ref: str) -> dict[str, Any]:
        parsed = urlparse(destination_ref)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
            raise AuditAnchorError(
                detail="Checkpoint destination reference is invalid for the object-storage anchor adapter.",
                code="audit_integrity_anchor_destination_invalid",
                retryable=False,
            )
        try:
            response = self._client().get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except (BotoCoreError, ClientError) as exc:
            raise self._map_boto_error(exc) from exc
        except ValueError as exc:
            raise AuditAnchorError(
                detail="Checkpoint document in object storage is invalid.",
                code="audit_integrity_anchor_document_invalid",
                retryable=False,
            ) from exc

    def _client(self):
        if boto3 is None or BotoConfig is None:
            raise AuditAnchorError(
                detail="boto3 is required for object-storage audit anchoring.",
                code="audit_integrity_anchor_client_unavailable",
                retryable=False,
            )
        session = boto3.session.Session()
        return session.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self._resolve_secret(self.access_key_id_ref),
            aws_secret_access_key=self._resolve_secret(self.secret_access_key_ref),
            aws_session_token=self._resolve_secret(self.session_token_ref),
            config=BotoConfig(
                s3={"addressing_style": "path" if self.endpoint_url else "auto"},
            ),
        )

    def _resolve_secret(self, raw_reference: str | None) -> str | None:
        if not raw_reference:
            return None
        try:
            return get_secret_resolver().resolve(raw_reference, allow_bare_env=False).value
        except SecretResolutionError as exc:
            if exc.code == "invalid_secret_ref":
                raise AuditAnchorError(
                    detail="Object-storage anchor secret reference is invalid.",
                    code="audit_integrity_anchor_secret_ref_invalid",
                    retryable=False,
                ) from exc
            if exc.code == "secret_provider_unconfigured":
                raise AuditAnchorError(
                    detail="Object-storage anchor secret reference requires an unsupported resolver.",
                    code="audit_integrity_anchor_secret_ref_unsupported",
                    retryable=False,
                ) from exc
            raise AuditAnchorError(
                detail="Object-storage anchor credentials are not available in the current environment.",
                code="audit_integrity_anchor_credentials_missing",
                retryable=False,
            ) from exc

    def _key_for_checkpoint(self, *, tenant_id: str, checkpoint_id: str) -> str:
        key = f"{tenant_id}/{checkpoint_id}.json"
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def _map_boto_error(self, exc: Exception) -> AuditAnchorError:
        if isinstance(exc, ClientError):
            error_code = str(exc.response.get("Error", {}).get("Code") or "").strip()
            if error_code in {"NoSuchBucket", "NoSuchKey", "404"}:
                return AuditAnchorError(
                    detail="Checkpoint object-storage destination was not found.",
                    code="audit_integrity_anchor_destination_not_found",
                    retryable=False,
                )
            if error_code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                return AuditAnchorError(
                    detail="Checkpoint object-storage credentials were rejected.",
                    code="audit_integrity_anchor_auth_failed",
                    retryable=False,
                )
            if error_code in {"RequestTimeout", "SlowDown", "InternalError", "ServiceUnavailable"}:
                return AuditAnchorError(
                    detail="Checkpoint object storage is temporarily unavailable.",
                    code="audit_integrity_anchor_unavailable",
                    retryable=True,
                )
        return AuditAnchorError(
            detail="Checkpoint object storage is temporarily unavailable.",
            code="audit_integrity_anchor_unavailable",
            retryable=True,
        )


class CustomPlaceholderAuditAnchorAdapter:
    checkpoint_type = AuditIntegrityCheckpointType.CUSTOM_PLACEHOLDER

    def write_document(
        self,
        *,
        checkpoint_id: str,
        tenant_id: str,
        document: dict[str, Any],
    ) -> AuditAnchorWriteResult:
        raise AuditAnchorError(
            detail="Custom external audit anchoring is not implemented in this build.",
            code="audit_integrity_anchor_custom_unimplemented",
            retryable=False,
        )

    def read_document(self, *, destination_ref: str) -> dict[str, Any]:
        raise AuditAnchorError(
            detail="Custom external audit anchoring is not implemented in this build.",
            code="audit_integrity_anchor_custom_unimplemented",
            retryable=False,
        )


def get_default_audit_anchor_checkpoint_type() -> AuditIntegrityCheckpointType:
    return AuditIntegrityCheckpointType(get_settings().audit_integrity_anchor_type)


def get_audit_anchor_adapter(
    *,
    checkpoint_type: AuditIntegrityCheckpointType | None = None,
) -> AuditAnchorAdapter:
    settings = get_settings()
    effective_type = checkpoint_type or AuditIntegrityCheckpointType(settings.audit_integrity_anchor_type)
    if effective_type == AuditIntegrityCheckpointType.LOCAL:
        return LocalAuditAnchorAdapter(base_dir=settings.audit_integrity_local_path or ".tmp/audit-integrity-checkpoints")
    if effective_type == AuditIntegrityCheckpointType.OBJECT_STORAGE:
        region = settings.audit_integrity_s3_region or settings.aws_region
        if not settings.audit_integrity_s3_bucket or not region:
            raise AuditAnchorError(
                detail="Object-storage audit anchoring is not fully configured.",
                code="audit_integrity_anchor_not_configured",
                retryable=False,
            )
        return S3AuditAnchorAdapter(
            bucket=settings.audit_integrity_s3_bucket,
            prefix=settings.audit_integrity_s3_prefix,
            region=region,
            endpoint_url=settings.audit_integrity_s3_endpoint_url,
            access_key_id_ref=settings.audit_integrity_s3_access_key_id_ref,
            secret_access_key_ref=settings.audit_integrity_s3_secret_access_key_ref,
            session_token_ref=settings.audit_integrity_s3_session_token_ref,
        )
    return CustomPlaceholderAuditAnchorAdapter()
