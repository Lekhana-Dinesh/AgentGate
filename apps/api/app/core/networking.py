from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse


DEVELOPMENT_ENVIRONMENTS = {"development", "test"}
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def is_development_environment(environment: str) -> bool:
    return str(environment or "").strip().lower() in DEVELOPMENT_ENVIRONMENTS


def is_production_like_environment(environment: str) -> bool:
    return not is_development_environment(environment)


def normalize_origin(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def is_http_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def uses_https(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def is_loopback_or_private_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    return is_loopback_or_private_host(host)


def is_loopback_or_private_host(host: str) -> bool:
    normalized = str(host or "").strip().lower().strip("[]")
    if not normalized:
        return False
    if normalized in LOCAL_HOSTNAMES or normalized.endswith(".localhost"):
        return True
    try:
        candidate = ip_address(normalized)
    except ValueError:
        return False
    return bool(
        candidate.is_private
        or candidate.is_loopback
        or candidate.is_link_local
        or candidate.is_reserved
        or candidate.is_unspecified
        or candidate.is_multicast
    )
