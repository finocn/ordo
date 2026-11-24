"""Ordo - a small, dependency-free deadline planner.

Everything lives in the standard library: storage is SQLite, the CLI is
argparse, and the reminder delivery layer is pluggable so it can talk to
Telegram or SMTP without any third-party package.
"""

__version__ = "0.1.0"
