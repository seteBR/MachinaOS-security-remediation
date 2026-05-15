"""Concrete `AICliProvider` implementations that still live under the
generic framework (i.e. haven't been migrated to the canonical
plugin-folder layout yet):

- `openai_codex.OpenAICodexProvider` — sandbox-first, no session
- `google_gemini.GoogleGeminiProvider` — v2 stub raising NotImplementedError

The claude provider has moved to its plugin folder
(``server/nodes/agent/claude_code_agent/_provider.py``) and is
discovered via the ``register_provider`` registry. The codex
provider will follow once `codex_agent` adopts the per-plugin
folder structure.
"""
