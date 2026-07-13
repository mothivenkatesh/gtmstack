"""
Vercel function — Synthetic Dev Persona preview.
  GET  /api/persona            -> the persona roster (for the UI chips)
  POST /api/persona            -> { text, type, personas[] }  =>  reactions + scores

Set ANTHROPIC_API_KEY in the Vercel project env to upgrade reactions from the
built-in model to live Claude. Without it, the deterministic engine still runs.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # make api/_*.py importable on Vercel

from _http import make_handler  # noqa: E402

handler = make_handler("persona")
