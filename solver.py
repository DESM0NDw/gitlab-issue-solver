import json
import logging
import subprocess
from pathlib import Path

import httpx

from config import settings

log = logging.getLogger(__name__)

MAX_ITERATIONS = 15

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Listet Dateien und Verzeichnisse in einem Pfad auf.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relativer Pfad im Repo, z.B. '.' oder 'src/'."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Liest den Inhalt einer Datei.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relativer Pfad zur Datei."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Sucht nach einem Muster in Dateien des Repos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Suchbegriff oder Regex."},
                    "path": {"type": "string", "description": "Pfad zum Durchsuchen, z.B. '.' oder 'src/'."},
                },
                "required": ["pattern", "path"],
            },
        },
    },
]

SYSTEM_PROMPT = """Du bist ein erfahrener Software-Entwickler. Du analysierst GitLab-Issues und erstellst konkrete Lösungsvorschläge.

Du hast Zugriff auf Tools:
- list_files: Verzeichnisinhalt anzeigen
- read_file: Datei lesen
- grep: Nach Mustern suchen

Pflichtablauf:
1. Starte IMMER mit list_files('.') um die Projektstruktur zu sehen.
2. Lies alle relevanten Dateien vollständig mit read_file bevor du antwortest.
3. Nutze grep um konkrete Fehlerstellen zu finden.
4. Antworte NUR wenn du den genauen Bug im Code gefunden hast.
5. Zeige den fehlerhaften Code und den korrekten Code als Diff.

Antworte auf Deutsch. Sei konkret mit Dateiname und Zeilennummer."""

PROMPT_TEMPLATE = """Analysiere dieses GitLab-Issue. Lies den Code und finde den konkreten Bug.

**Issue #{iid}: {title}**

**Beschreibung:**
{description}

**Bisherige Kommentare:**
{comments}

**Dateien im Repository:**
{file_tree}

---

Lies die relevanten Dateien aus der obigen Liste mit read_file. Nutze NUR Pfade die in der Liste stehen.

Deine Antwort MUSS enthalten:
1. **Ursache**: Die genaue Codezeile die das Problem verursacht (Datei + Zeile).
2. **Fehlerhafter Code**: Den problematischen Code-Ausschnitt.
3. **Korrektur**: Den korrigierten Code als Diff.
4. **Erklärung**: Warum dieser Fix das Problem löst."""


def _file_tree(repo_path: Path) -> str:
    result = subprocess.run(
        ["find", ".", "-not", "-path", "./.git/*", "-type", "f"],
        capture_output=True, text=True, timeout=10, cwd=repo_path,
    )
    return result.stdout.strip() or "(leer)"


def _execute_tool(name: str, args: dict, repo_path: Path) -> str:
    try:
        if name == "list_files":
            target = (repo_path / args["path"]).resolve()
            if not str(target).startswith(str(repo_path)):
                return "Fehler: Pfad außerhalb des Repos."
            result = subprocess.run(
                ["find", str(target), "-not", "-path", "*/.git/*", "-type", "f"],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() or "(keine Dateien)"

        elif name == "read_file":
            target = (repo_path / args["path"]).resolve()
            if not str(target).startswith(str(repo_path)):
                return "Fehler: Pfad außerhalb des Repos."
            if not target.is_file():
                return f"Datei nicht gefunden: {args['path']}"
            content = target.read_text(errors="replace")
            if len(content) > 8000:
                content = content[:8000] + "\n... (abgeschnitten)"
            return content

        elif name == "grep":
            result = subprocess.run(
                ["grep", "-rn", "--include=*", args["pattern"], args["path"]],
                capture_output=True, text=True, timeout=10, cwd=repo_path,
            )
            out = result.stdout[:4000] if result.stdout else "(keine Treffer)"
            return out

    except Exception as e:
        return f"Fehler: {e}"

    return "Unbekanntes Tool."


async def run_solver(issue: dict, comments: list[dict], repo_path: Path) -> str:
    base_url, model, api_key = settings.llm

    comment_text = "\n".join(
        f"- {c['author']['name']}: {c['body'][:200]}"
        for c in comments
        if not c.get("system")
    ) or "(keine)"

    file_tree = _file_tree(repo_path)

    prompt = PROMPT_TEMPLATE.format(
        iid=issue["iid"],
        title=issue["title"],
        description=issue.get("description") or "(keine Beschreibung)",
        comments=comment_text,
        file_tree=file_tree,
    )

    messages = [{"role": "user", "content": prompt}]

    async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
        for i in range(MAX_ITERATIONS):
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                    "tools": TOOLS,
                    "tool_choice": "auto",
                },
            )
            if not response.is_success:
                log.error(f"Groq Fehler {response.status_code}: {response.text}")
            response.raise_for_status()
            data = response.json()

            msg = data["choices"][0]["message"]
            if msg.get("content") is None:
                msg = {k: v for k, v in msg.items() if k != "content"}
            messages.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg.get("content", "")

            for call in tool_calls:
                args = json.loads(call["function"]["arguments"])
                log.info(f"Tool: {call['function']['name']}({args})")
                result = _execute_tool(call["function"]["name"], args, repo_path)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                })

    return "Maximale Iterationen erreicht."
