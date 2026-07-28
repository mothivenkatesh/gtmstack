"""
Typed contracts for the shapes that cross module boundaries.

The bug class this closes has bitten twice in this repo, both times invisible to
unit tests: code looked for `mentions` when the engine returned `feed`, and a
test looked for `text` when the transcript engine returns `plain`. Both are
payload-shape mismatches, which is exactly what a typed contract makes
impossible.

Pydantic when installed, a graceful no-op when not. The app must not gain a hard
dependency for a validation nicety, and a serverless cold start should not pay
for an import it may not need.

Deliberately narrow: the shapes that CROSS a boundary (a tool's output consumed
by another module), not every internal dict. Typing everything produces
ceremony; typing the seams produces safety.

No em dashes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field, ValidationError
    HAVE = True
except ImportError:                                              # pragma: no cover
    HAVE = False
    BaseModel = object
    ValidationError = Exception

    def Field(default=None, **kw):                               # noqa: N802
        return default


if HAVE:
    class FeedItem(BaseModel):
        """One post from the Signals keyword feed. THE shape that caused the
        first bug: the keyword unit returns `feed`, person/company return
        `sources[].activity`, and code that assumed `mentions` silently got
        nothing and reported success."""
        text: str = ""
        url: Optional[str] = None
        platform: str = "unknown"
        author: Optional[str] = None
        ts: Optional[str] = None
        ago: Optional[str] = None
        where: Optional[str] = None
        engagement: Optional[List[Dict[str, Any]]] = None

    class Transcript(BaseModel):
        """The transcript engine returns `plain` and `cues`, NOT `text` and
        `segments`. The second bug."""
        plain: str = ""
        cues: List[Dict[str, Any]] = Field(default_factory=list)
        language: Optional[str] = None
        duration: Optional[float] = None

    class SignalNode(BaseModel):
        """What Listener and the tool recorder both write. Keeping one model
        means the manual door and the agent door cannot drift apart."""
        platform: str
        url: Optional[str] = None
        author: Optional[str] = None
        text: str = ""
        sentiment: Optional[str] = None
        intent_type: Optional[str] = None
        posted_at: Optional[str] = None
        delivered_at: Optional[float] = None
        actioned: bool = False

    class ToolStep(BaseModel):
        """One step of an agent run as the UI consumes it."""
        n: int
        text: str
        tool: str
        risk: str = "read"
        status: str = "ok"
        output: str = ""
        rule: Optional[str] = None


def validate(model_name, data):
    """Validate and normalise, or pass the data straight through when pydantic
    is absent. Returns (data, error_or_None) and NEVER raises: a contract check
    that can break a working request is worse than no contract."""
    if not HAVE:
        return data, None
    model = globals().get(model_name)
    if model is None:
        return data, None
    try:
        return model(**(data or {})).model_dump(), None
    except ValidationError as e:                                 # noqa: BLE001
        return data, str(e)[:200]
    except Exception as e:                                       # noqa: BLE001
        return data, str(e)[:200]


def check_feed(items):
    """Validate a Signals feed, returning the rows that are usable plus a count
    of what failed. Used to catch a source changing shape under us."""
    if not HAVE:
        return list(items or []), 0
    ok, bad = [], 0
    for it in (items or []):
        d, err = validate("FeedItem", it)
        if err:
            bad += 1
        else:
            ok.append({**it, **d})
    return ok, bad


def status():
    return {"pydantic": HAVE,
            "models": sorted(k for k, v in globals().items()
                             if isinstance(v, type) and issubclass(v, BaseModel)
                             and v is not BaseModel) if HAVE else []}
