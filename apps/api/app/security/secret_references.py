from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

_ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUPPORTED_REFERENCE_TYPES = {"env", "secret_ref", "vault"}


class SecretResolutionError(Exception):
    def __init__(self, detail: str, *, code: str) -> None:
        self.detail = detail
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class SecretReference:
    reference_type: str
    identifier: str
    display_ref: str


@dataclass(frozen=True, slots=True)
class ResolvedSecret:
    value: str
    reference: SecretReference


class SecretResolver(Protocol):
    def parse(self, raw_reference: str, *, allow_bare_env: bool = True) -> SecretReference:
        ...

    def resolve(self, raw_reference: str, *, allow_bare_env: bool = True) -> ResolvedSecret:
        ...


class LocalSecretResolver:
    def parse(self, raw_reference: str, *, allow_bare_env: bool = True) -> SecretReference:
        normalized = str(raw_reference or "").strip()
        if not normalized:
            raise SecretResolutionError(
                "Secret reference is not configured.",
                code="secret_ref_missing",
            )
        if ":" not in normalized:
            if not allow_bare_env or not _ENV_VAR_PATTERN.match(normalized):
                raise SecretResolutionError(
                    "Secret reference format is invalid.",
                    code="invalid_secret_ref",
                )
            return SecretReference(
                reference_type="env",
                identifier=normalized,
                display_ref=f"env:{normalized}",
            )

        ref_type, identifier = normalized.split(":", 1)
        normalized_type = ref_type.strip().lower()
        normalized_identifier = identifier.strip()
        if normalized_type not in _SUPPORTED_REFERENCE_TYPES or not normalized_identifier:
            raise SecretResolutionError(
                "Secret reference format is invalid.",
                code="invalid_secret_ref",
            )
        if normalized_type == "env" and not _ENV_VAR_PATTERN.match(normalized_identifier):
            raise SecretResolutionError(
                "Secret reference format is invalid.",
                code="invalid_secret_ref",
            )
        return SecretReference(
            reference_type=normalized_type,
            identifier=normalized_identifier,
            display_ref=f"{normalized_type}:{normalized_identifier}",
        )

    def resolve(self, raw_reference: str, *, allow_bare_env: bool = True) -> ResolvedSecret:
        reference = self.parse(raw_reference, allow_bare_env=allow_bare_env)
        if reference.reference_type == "env":
            value = os.getenv(reference.identifier, "").strip()
            if not value:
                raise SecretResolutionError(
                    "The referenced secret is not available in the environment.",
                    code="secret_unavailable",
                )
            return ResolvedSecret(value=value, reference=reference)

        raise SecretResolutionError(
            "The configured secret reference type is not available in this build.",
            code="secret_provider_unconfigured",
        )


def build_env_secret_reference(env_var: str) -> str:
    return f"env:{str(env_var or '').strip()}"


@lru_cache(maxsize=1)
def get_secret_resolver() -> LocalSecretResolver:
    return LocalSecretResolver()
