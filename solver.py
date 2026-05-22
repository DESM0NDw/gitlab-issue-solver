import asyncio
import logging
import os
from pathlib import Path
from config import settings

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """Du analysierst ein GitLab-Issue und schlägst eine konkrete Lösung vor.

**Issue #{iid}: {title}**

**Beschreibung:**
{description}

**Bisherige Kommentare:**
{comments}

---

Analysiere den Code in diesem Repository und erstelle einen strukturierten Lösungsvorschlag:

1. **Ursache**: Wo liegt das Problem wahrscheinlich? Welche Dateien/Funktionen sind betroffen?
2. **Betroffene Dateien**: Liste konkrete Dateipfade mit Zeilennummern auf.
3. **Lösungsvorschlag**: Beschreibe die notwendigen Code-Änderungen konkret.
4. **Code-Änderungen**: Zeige die relevanten Änderungen als Diff oder konkreten Code-Ausschnitt.

Sei präzise und beziehe dich auf echte Dateien und Funktionen aus diesem Repository."""


async def run_solver(issue: dict, comments: list[dict], repo_path: Path) -> str:
    comment_text = "\n".join(
        f"- {c['author']['name']}: {c['body'][:200]}"
        for c in comments
        if not c.get("system")
    ) or "(keine)"

    prompt = PROMPT_TEMPLATE.format(
        iid=issue["iid"],
        title=issue["title"],
        description=issue.get("description") or "(keine Beschreibung)",
        comments=comment_text,
    )

    env = {**os.environ, "ANTHROPIC_API_KEY": settings.anthropic_api_key}

    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p", prompt,
        "--allowedTools", "Read,Write,Edit,Bash,Grep,Glob,LS",
        "--output-format", "text",
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Claude Code Timeout nach 5 Minuten")

    if proc.returncode != 0:
        err = stderr.decode()[:500]
        raise RuntimeError(f"Claude Code Fehler: {err}")

    return stdout.decode().strip()
