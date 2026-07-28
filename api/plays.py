"""
Vercel function — Plays (composite, agent-callable multi-step tools).
  GET  /api/plays   -> list available plays (metadata only)
  POST /api/plays   -> run a play: body { "play": id, "input": { ... } }

A play chains existing single-tool engines server-side and returns a steps[]
array an agent can branch on. Core logic lives in api/_plays.py, shared with
app.py. Runs INLINE: the response already carries every step's result, so
there is nothing to poll.

Phase 1 ships one play, 'video_messaging' (transcript -> dev-persona reactions);
see api/_plays.py for why the contact-axis plays wait for Phase-2 connectors.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

# Vercel's Python builder finds a function by STATICALLY looking for a `handler`
# class statement. It does not follow `handler = make_handler(...)`, so every
# shim in this repo was invisible to it: the build reported "pattern does not
# match any Serverless Functions", produced a static-only site, and production
# silently kept serving an old deploy. Subclassing keeps the one-line shim while
# giving the builder the class statement it needs.
_Base = make_handler("plays")


class handler(_Base):
    pass