"""Outbound provider adapters.

Only `app.services.executor` may import a concrete payment provider. The
import-linter contract in `.importlinter` enforces this mechanically, so the
claim "the LLM cannot move money" is verifiable by a build step rather than by
reading prose.
"""
