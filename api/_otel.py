"""
OpenTelemetry exporter - agent runs as distributed traces.

Why traces and not just the local event log: an agent run IS a trace. The run is
a root span, each step is a child, each tool call a grandchild. That parent-child
structure is the actual shape of the work, and `_observe.py`'s flat table throws
it away. A trace shows you that step 4 took 3 seconds because the Reddit fetch
inside it retried twice. A flat log shows you two rows and leaves you to guess.

This is an EXPORTER, deliberately not a replacement:
  - `_observe.py` stays the source of truth for the in-app Activity tab. It is
    zero-config, works offline, and needs no collector. A product that cannot
    show its own activity without a Grafana stack is a worse product.
  - OTel is for when you want real tracing infrastructure (Jaeger, Honeycomb,
    Grafana Tempo, Datadog) and cross-service correlation.

Follows the OpenTelemetry GenAI semantic conventions so the spans are legible to
any backend that knows about agents, rather than inventing private attribute
names nothing can read.

Three hard rules, inherited from `_observe.log()`:
  1. NEVER RAISES. Telemetry that breaks the run it measures is worse than none.
  2. ZERO COST WHEN OFF. No endpoint configured means no import, no overhead.
  3. FLUSHES BEFORE FREEZE. On serverless the process is suspended the moment a
     response is returned, so a batching exporter silently loses the last spans.
     `flush()` is called at the end of a run.

Enable with the standard env var, nothing app-specific:
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    OTEL_SERVICE_NAME=gtmstack            (optional, defaults to gtmstack)
    OTEL_EXPORTER_OTLP_HEADERS=...        (for a hosted backend's auth)

No em dashes.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

_tracer = None
_init_tried = False
_provider = None


def enabled():
    """Configured is the only switch. No endpoint means genuinely off."""
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _tracer_or_none():
    """Build the tracer once, lazily. Any failure disables tracing for the
    process rather than propagating: a missing package or an unreachable
    collector must not take down an agent run."""
    global _tracer, _init_tried, _provider
    if _tracer is not None or _init_tried:
        return _tracer
    _init_tried = True
    if not enabled():
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        _provider = TracerProvider(resource=Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "gtmstack"),
            "service.version": os.getenv("VERCEL_GIT_COMMIT_SHA", "dev")[:12],
            "deployment.environment": os.getenv("VERCEL_ENV", "local"),
        }))
        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(_provider)
        _tracer = trace.get_tracer("gtmstack.harness")
        return _tracer
    except Exception:                                            # noqa: BLE001
        return None


@contextmanager
def span(name, kind=None, **attrs):
    """Trace a block. A no-op generator when tracing is off, so call sites read
    the same whether or not a collector exists."""
    t = _tracer_or_none()
    if t is None:
        yield None
        return
    try:
        with t.start_as_current_span(name) as sp:
            try:
                for k, v in attrs.items():
                    if v is not None:
                        sp.set_attribute(k, v if isinstance(v, (str, int, float, bool))
                                         else str(v))
            except Exception:                                    # noqa: BLE001
                pass
            try:
                yield sp
            except Exception as e:                               # noqa: BLE001
                # Record it on the span, then re-raise: the caller decides.
                try:
                    from opentelemetry.trace import Status, StatusCode
                    sp.record_exception(e)
                    sp.set_status(Status(StatusCode.ERROR, str(e)[:200]))
                except Exception:                                # noqa: BLE001
                    pass
                raise
    except Exception:                                            # noqa: BLE001
        # Tracing itself failed. Run the body untraced rather than fail the work.
        yield None


def agent_span(agent, run_id, **attrs):
    """Root span for an agent run, named per the GenAI semantic conventions."""
    return span(f"invoke_agent {agent}",
                **{"gen_ai.operation.name": "invoke_agent",
                   "gen_ai.agent.name": agent,
                   "gen_ai.system": "gtmstack",
                   "gtmstack.run_id": run_id, **attrs})


def tool_span(tool, agent=None, **attrs):
    """Child span for one deterministic tool call inside a run."""
    return span(f"execute_tool {tool}",
                **{"gen_ai.operation.name": "execute_tool",
                   "gen_ai.tool.name": tool,
                   "gen_ai.agent.name": agent,
                   "gen_ai.system": "gtmstack", **attrs})


def set_ok(sp, ok, **attrs):
    """Mark a span's outcome. Safe on a None span."""
    if sp is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode
        for k, v in attrs.items():
            if v is not None:
                sp.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else str(v))
        sp.set_status(Status(StatusCode.OK if ok else StatusCode.ERROR))
    except Exception:                                            # noqa: BLE001
        pass


def flush(timeout_ms=3000):
    """Force-export before the process can be frozen.

    On Vercel the function is suspended as soon as the response is written, so a
    BatchSpanProcessor's background thread never gets to run and the spans for
    the request you most want to debug are exactly the ones you lose."""
    if _provider is None:
        return False
    try:
        return bool(_provider.force_flush(timeout_millis=timeout_ms))
    except Exception:                                            # noqa: BLE001
        return False


def status():
    """What the UI and the smoke suite can report about tracing."""
    return {
        "enabled": enabled(),
        "endpoint": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
        "service": os.getenv("OTEL_SERVICE_NAME", "gtmstack"),
        "active": _tracer_or_none() is not None,
    }
