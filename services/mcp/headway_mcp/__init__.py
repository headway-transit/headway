"""Headway MCP server (handoff 0034).

Architecture: ``assistant ⇄ MCP server ⇄ Headway HTTP API ⇄ DB``. This
package is an API *client*, never a database client — it authenticates to
the Headway API with a read-scoped machine key (``hwk_``), holds no
database credentials, and every tool call lands in the existing audit
trail under that key's identity.
"""

__version__ = "0.1.0"
