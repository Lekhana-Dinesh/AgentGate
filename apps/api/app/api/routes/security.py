from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_roles
from app.core.enums import UserRole
from app.schemas.security import KeyPurposeStatusResponse, KeyStatusResponse
from app.security.key_management import (
    KEY_PURPOSE_PAYLOAD_PROTECTION,
    KeyManagementError,
    get_key_provider,
)

router = APIRouter()


@router.get("/key-status", response_model=KeyStatusResponse)
def get_key_status(
    _: object = Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
) -> KeyStatusResponse:
    provider = get_key_provider()
    warnings: list[str] = []
    try:
        purpose_status = provider.get_purpose_status(KEY_PURPOSE_PAYLOAD_PROTECTION)
    except KeyManagementError as exc:
        warnings.append(exc.detail)
        purpose_status = KeyPurposeStatusResponse(
            purpose=KEY_PURPOSE_PAYLOAD_PROTECTION,
            provider=provider.provider_name,
            active_key_ref=None,
            active_key_version=None,
            configured_key_refs=[],
            status="unconfigured",
            warnings=[exc.detail],
        )
        return KeyStatusResponse(
            provider=provider.provider_name,
            purposes=[purpose_status],
            warnings=warnings,
        )

    return KeyStatusResponse(
        provider=provider.provider_name,
        purposes=[
            KeyPurposeStatusResponse(
                purpose=purpose_status.purpose,
                provider=purpose_status.provider,
                active_key_ref=purpose_status.active_key_ref,
                active_key_version=purpose_status.active_key_version,
                configured_key_refs=purpose_status.configured_key_refs,
                status=purpose_status.status,
                warnings=purpose_status.warnings,
            )
        ],
        warnings=warnings + purpose_status.warnings,
    )
