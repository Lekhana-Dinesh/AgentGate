from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from threading import Lock


DEFAULT_HISTOGRAM_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    rendered = []
    for key, value in labels.items():
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        rendered.append(f'{key}="{escaped}"')
    return "{" + ",".join(rendered) + "}"


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counter_defs: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._histogram_defs: dict[str, tuple[str, tuple[str, ...], tuple[float, ...]]] = {}
        self._gauge_defs: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._counters: dict[str, dict[tuple[str, ...], float]] = defaultdict(dict)
        self._gauges: dict[str, dict[tuple[str, ...], float]] = defaultdict(dict)
        self._histograms: dict[str, dict[tuple[str, ...], dict[str, object]]] = defaultdict(dict)

    def register_counter(self, name: str, documentation: str, *, labels: tuple[str, ...] = ()) -> None:
        with self._lock:
            self._counter_defs.setdefault(name, (documentation, labels))

    def register_gauge(self, name: str, documentation: str, *, labels: tuple[str, ...] = ()) -> None:
        with self._lock:
            self._gauge_defs.setdefault(name, (documentation, labels))

    def register_histogram(
        self,
        name: str,
        documentation: str,
        *,
        labels: tuple[str, ...] = (),
        buckets: tuple[float, ...] = DEFAULT_HISTOGRAM_BUCKETS,
    ) -> None:
        with self._lock:
            self._histogram_defs.setdefault(name, (documentation, labels, buckets))

    def increment(self, name: str, amount: float = 1.0, **labels: str) -> None:
        with self._lock:
            _, label_names = self._counter_defs[name]
            key = self._label_values(label_names, labels)
            current = self._counters[name].get(key, 0.0)
            self._counters[name][key] = current + amount

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            _, label_names = self._gauge_defs[name]
            key = self._label_values(label_names, labels)
            self._gauges[name][key] = float(value)

    def observe(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            _, label_names, buckets = self._histogram_defs[name]
            key = self._label_values(label_names, labels)
            sample = self._histograms[name].get(key)
            if sample is None:
                sample = {
                    "buckets": {bucket: 0 for bucket in buckets},
                    "count": 0,
                    "sum": 0.0,
                }
                self._histograms[name][key] = sample
            for bucket in buckets:
                if value <= bucket:
                    sample["buckets"][bucket] += 1
            sample["count"] += 1
            sample["sum"] += float(value)

    def reset(self) -> None:
        with self._lock:
            self._counters = defaultdict(dict)
            self._gauges = defaultdict(dict)
            self._histograms = defaultdict(dict)

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, (documentation, label_names) in sorted(self._counter_defs.items()):
                lines.append(f"# HELP {name} {documentation}")
                lines.append(f"# TYPE {name} counter")
                samples = self._counters.get(name, {})
                for label_values, value in sorted(samples.items()):
                    labels = dict(zip(label_names, label_values))
                    lines.append(f"{name}{_format_labels(labels)} {value}")

            for name, (documentation, label_names) in sorted(self._gauge_defs.items()):
                lines.append(f"# HELP {name} {documentation}")
                lines.append(f"# TYPE {name} gauge")
                samples = self._gauges.get(name, {})
                for label_values, value in sorted(samples.items()):
                    labels = dict(zip(label_names, label_values))
                    lines.append(f"{name}{_format_labels(labels)} {value}")

            for name, (documentation, label_names, buckets) in sorted(self._histogram_defs.items()):
                lines.append(f"# HELP {name} {documentation}")
                lines.append(f"# TYPE {name} histogram")
                samples = self._histograms.get(name, {})
                for label_values, sample in sorted(samples.items()):
                    labels = dict(zip(label_names, label_values))
                    cumulative = 0
                    for bucket in buckets:
                        cumulative += int(sample["buckets"][bucket])
                        lines.append(
                            f"{name}_bucket{_format_labels(labels | {'le': str(bucket)})} {cumulative}"
                        )
                    lines.append(f"{name}_bucket{_format_labels(labels | {'le': '+Inf'})} {int(sample['count'])}")
                    lines.append(f"{name}_sum{_format_labels(labels)} {sample['sum']}")
                    lines.append(f"{name}_count{_format_labels(labels)} {int(sample['count'])}")
        return "\n".join(lines) + "\n"

    def _label_values(self, label_names: tuple[str, ...], labels: dict[str, str]) -> tuple[str, ...]:
        return tuple(str(labels.get(name, "")) for name in label_names)


def configure_metrics_registry(registry: MetricsRegistry) -> MetricsRegistry:
    registry.register_counter(
        "agentgate_http_requests_total",
        "Total HTTP requests handled by AgentGate.",
        labels=("method", "route", "status_code", "error_code"),
    )
    registry.register_histogram(
        "agentgate_http_request_duration_seconds",
        "HTTP request duration for AgentGate routes.",
        labels=("method", "route"),
    )
    registry.register_counter(
        "agentgate_gateway_decisions_total",
        "Gateway decision outcomes by decision and tool-call status.",
        labels=("decision", "status"),
    )
    registry.register_counter(
        "agentgate_approvals_total",
        "Approval lifecycle events.",
        labels=("status",),
    )
    registry.register_counter(
        "agentgate_jobs_transitions_total",
        "Job status transitions by job type and resulting status.",
        labels=("job_type", "status"),
    )
    registry.register_gauge(
        "agentgate_jobs_current",
        "Current durable job counts by status.",
        labels=("status",),
    )
    registry.register_counter(
        "agentgate_audit_export_runs_total",
        "Audit export run outcomes.",
        labels=("result",),
    )
    registry.register_counter(
        "agentgate_slack_notifications_total",
        "Slack notification delivery outcomes.",
        labels=("result",),
    )
    registry.register_counter(
        "agentgate_retention_purge_runs_total",
        "Retention purge runs.",
        labels=("dry_run",),
    )
    registry.register_counter(
        "agentgate_retention_purged_total",
        "Protected payloads purged by retention jobs.",
    )
    registry.register_counter(
        "agentgate_oidc_logins_total",
        "OIDC login outcomes.",
        labels=("result",),
    )
    registry.register_counter(
        "agentgate_rate_limit_exceeded_total",
        "Requests rejected by rate limiting.",
        labels=("scope",),
    )
    return registry


@lru_cache(maxsize=1)
def get_metrics_registry() -> MetricsRegistry:
    return configure_metrics_registry(MetricsRegistry())
