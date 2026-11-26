#!/usr/bin/env python3
"""Build a static HTML dashboard for Ordo, meant for GitHub Pages.

Pure standard library (like the rest of Ordo). Reads the SQLite database and
writes ``<out>/index.html``. No network, no templating engine.

Usage:
    python3 tools/build_dashboard.py --out _site
    python3 tools/build_dashboard.py --db path/to/ordo.db --out _site
"""

from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ordo import timeparse as tp  # noqa: E402
from ordo.config import load as load_config, resolve_db_path  # noqa: E402
from ordo.db import connect  # noqa: E402
from ordo.models import PRIORITY_NAMES, PRIORITY_SHORT  # noqa: E402
from ordo.report import humanize  # noqa: E402
from ordo.service import Store  # noqa: E402

BUCKETS = [
    ("overdue", "Просрочено"),
    ("today", "Сегодня"),
    ("soon", "Скоро"),
    ("blocked", "Заблокировано"),
    ("postponed", "Перенесённые"),
    ("stale", "Застряло"),
]

PRIORITY_CLASS = {0: "p0", 1: "p1", 2: "p2", 3: "p3"}

STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI",
       Roboto, Helvetica, Arial, sans-serif; background: #0f1115; color: #e6e8eb; }
.wrap { max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }
header { display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline;
         justify-content: space-between; border-bottom: 1px solid #23262d;
         padding-bottom: 12px; margin-bottom: 20px; }
h1 { font-size: 22px; margin: 0; letter-spacing: .3px; }
h1 span { color: #7d8590; font-weight: 400; font-size: 13px; }
.actions a { color: #6cb2ff; text-decoration: none; margin-left: 14px; font-size: 14px; }
.actions a:hover { text-decoration: underline; }
.cards { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }
.card { background: #171a21; border: 1px solid #23262d; border-radius: 10px;
        padding: 10px 14px; min-width: 110px; }
.card .n { font-size: 22px; font-weight: 700; }
.card .l { color: #7d8590; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; }
section { margin-bottom: 26px; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: .8px;
     color: #9aa4b2; margin: 0 0 10px; }
ul { list-style: none; margin: 0; padding: 0; }
li { background: #14171d; border: 1px solid #23262d; border-left: 3px solid #23262d;
     border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
li.overdue { border-left-color: #f85149; }
li.today { border-left-color: #d29922; }
.title { font-weight: 600; }
.meta { color: #7d8590; font-size: 13px; margin-top: 3px; }
.chip { display: inline-block; font-size: 11px; font-weight: 700; padding: 1px 7px;
        border-radius: 999px; margin-right: 8px; vertical-align: 1px; }
.p0 { background: #f85149; color: #fff; }
.p1 { background: #db6d28; color: #fff; }
.p2 { background: #3b82f6; color: #fff; }
.p3 { background: #3d444d; color: #e6e8eb; }
.empty { color: #7d8590; font-style: italic; }
footer { margin-top: 32px; color: #7d8590; font-size: 12px; border-top: 1px solid #23262d;
         padding-top: 12px; }
code { background: #23262d; padding: 1px 5px; border-radius: 4px; }
"""


def esc(text):
    return html.escape(str(text if text is not None else ""))


def repo_links():
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        return None
    return {
        "issues": "https://github.com/%s/issues" % repo,
        "add": "https://github.com/%s/issues/new?title=%s" % (
            repo,
            "add+%22%D0%BD%D0%BE%D0%B2%D0%B0%D1%8F+%D0%B7%D0%B0%D0%B4%D0%B0%D1%87%D0%B0%22+-d+3d",
        ),
    }


def task_item(task, projects, now):
    due = task.due_datetime()
    bits = []
    if due is not None:
        bits.append(esc(tp.format_local(due)))
        bits.append(esc(humanize(due, now)))
    project = (projects or {}).get(task.project_id)
    if project:
        bits.append(esc(project))
    bits.append("status: %s" % esc(task.status))
    if task.postpone_count:
        bits.append("перенесена %d раз" % task.postpone_count)
    pclass = PRIORITY_CLASS.get(task.priority, "p3")
    plabel = PRIORITY_SHORT.get(task.priority, "P?")
    ptitle = PRIORITY_NAMES.get(task.priority, "")
    return (
        '<li class="{cls}">'
        '<span class="chip {pclass}" title="{ptitle}">{plabel}</span>'
        '<span class="title">#{tid} {title}</span>'
        '<div class="meta">{meta}</div>'
        "</li>"
    ).format(
        cls=esc(task.status if task.status in ("blocked",) else ""),
        pclass=pclass,
        ptitle=esc(ptitle),
        plabel=esc(plabel),
        tid=task.id,
        title=esc(task.title),
        meta=" · ".join(bits),
    )


def build(out_dir, db_path=None):
    config = load_config()
    path = resolve_db_path(config, db_path)
    store = Store(connect(path), config)
    now = tp.now_utc()
    buckets = store.review(now)
    projects = {p.id: p.name for p in store.list_projects(include_archived=True)}
    open_tasks = store.list_tasks(include_done=False, now=now)
    updates = store.recent_events(15)
    store.conn.close()

    links = repo_links()

    parts = []
    parts.append("<!doctype html><html lang='ru'><head><meta charset='utf-8'>")
    parts.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    parts.append("<title>Ordo</title><style>%s</style></head><body><div class='wrap'>" % STYLE)
    parts.append("<header><h1>Ordo <span>%s</span></h1>" % esc(tp.format_local(now)))
    if links:
        parts.append(
            "<div class='actions'><a href='%s'>Добавить задачу</a>"
            "<a href='%s'>Все задачи (issue)</a></div>" % (esc(links["add"]), esc(links["issues"]))
        )
    parts.append("</header>")

    # summary cards
    parts.append("<div class='cards'>")
    for key, label in BUCKETS:
        n = len(buckets.get(key, []))
        parts.append("<div class='card'><div class='n'>%d</div><div class='l'>%s</div></div>"
                     % (n, esc(label)))
    parts.append("<div class='card'><div class='n'>%d</div><div class='l'>Открытых</div></div>"
                 % len(open_tasks))
    parts.append("</div>")

    # buckets
    for key, label in BUCKETS:
        tasks = buckets.get(key, [])
        if not tasks:
            continue
        parts.append("<section><h2>%s (%d)</h2><ul>" % (esc(label), len(tasks)))
        for task in tasks:
            item = task_item(task, projects, now)
            # decorate the border by bucket
            item = item.replace('<li class="', '<li class="%s ' % key, 1)
            parts.append(item)
        parts.append("</ul></section>")

    if not any(buckets.get(k) for k, _ in BUCKETS):
        parts.append("<p class='empty'>Активных задач нет — добавьте через Issues "
                     "или командой <code>ordo add</code>.</p>")

    # recent activity
    if updates:
        parts.append("<section><h2>Последняя активность</h2><ul>")
        for event in updates:
            when = tp.format_local(tp.from_storage(event.created_at))
            task = ("#%d " % event.task_id) if event.task_id else ""
            detail = esc(event.detail) if event.detail else ""
            parts.append("<li><div class='meta'>%s · %s</div><div>%s%s%s</div></li>"
                         % (esc(when), esc(event.kind), esc(task),
                            esc(project_label(event, projects)), detail))
        parts.append("</ul></section>")

    parts.append("<footer>Статический снимок базы Ordo. Обновляется workflow "
                 "<code>dashboard</code>. Данные и управление — через GitHub Issues.</footer>")
    parts.append("</div></body></html>")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    (out_dir / "index.html").write_text("\n".join(parts), encoding="utf-8")
    return out_dir / "index.html"


def project_label(event, projects):
    if not event.project_id:
        return ""
    name = projects.get(event.project_id)
    return ("[%s] " % html.escape(name)) if name else ""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Ordo static dashboard.")
    parser.add_argument("--out", default="_site", help="output directory (default: _site)")
    parser.add_argument("--db", default=None, help="database file (default: from config)")
    args = parser.parse_args(argv)
    target = build(args.out, args.db)
    print("wrote %s" % target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
