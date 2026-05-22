# gitlab-issue-solver

Analysiert Bug-Issues im Quellcode und schlägt konkrete Fixes mit Code-Diffs vor.

## Was er macht

Wird automatisch getriggert wenn der Analyzer `bot::prio-gesetzt` auf einem `type::bug`-Issue setzt. Der Solver:

1. Klont das Projekt-Repo (oder aktualisiert es per `git fetch`)
2. Lässt das LLM den Code mit eigenen Tools durchsuchen (Read, Grep, LS)
3. Postet einen Lösungsvorschlag mit konkretem Diff als Kommentar
4. Setzt `bot::lösungsvorschlag`

Issues werden sequenziell via Queue abgearbeitet — auch bei vielen gleichzeitigen Webhook-Events läuft immer nur ein Solver-Prozess.

Nur `type::bug` Issues werden verarbeitet. Features, Dokumentation etc. werden ignoriert.

## Pipeline-Kontext

```
Neues Issue
    → gitlab-issue-bot       (type::* + ki-ersteinschätzung::*)
    → gitlab-issue-analyzer  (+ bot::prio-gesetzt)
    → gitlab-issue-solver    (+ bot::lösungsvorschlag)  ← dieser Bot
```

## Endpoints

| Endpoint | Beschreibung |
|----------|-------------|
| `POST /webhook` | GitLab Webhook-Empfänger |
| `POST /solve?project_id=X&issue_iid=Y` | Issue manuell lösen |
| `GET /health` | Health-Check (inkl. aktuelle Queue-Größe) |

## Setup

### 1. Repo klonen und .env anlegen

```bash
git clone https://github.com/DESM0NDw/gitlab-issue-solver
cd gitlab-issue-solver
cp .env.example .env
```

`.env` ausfüllen:

```env
GITLAB_URL=https://gitlab.com
GITLAB_TOKEN=your_gitlab_token
WEBHOOK_SECRET=your_secret

LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key
```

### 2. Deployen

```bash
docker compose up -d --build
```

### 3. GitLab Webhook einrichten

In GitLab unter **Settings → Webhooks**:
- URL: `https://your-domain/webhook`
- Trigger: **Issues events**
- Secret Token: Wert aus `WEBHOOK_SECRET`

### 4. Issue manuell lösen

```bash
curl -X POST "https://your-domain/solve?project_id=YOUR_PROJECT_ID&issue_iid=42"
```

## Konfiguration

| Variable | Standard | Beschreibung |
|----------|----------|-------------|
| `GITLAB_URL` | `https://gitlab.com` | GitLab-Instanz URL |
| `GITLAB_TOKEN` | — | Personal Access Token (Scope: api, read_repository) |
| `WEBHOOK_SECRET` | leer | Webhook-Secret (optional) |
| `LLM_PROVIDER` | `groq` | `groq` / `openai` / `mistral` |
| `GROQ_API_KEY` | — | API-Key für Groq |
| `REPOS_BASE_PATH` | `/repos` | Pfad für geklonte Repos (Docker Volume) |

## Hinweise

- Das Repo wird beim ersten Aufruf geklont (`--filter=blob:none`) und danach nur noch per `git fetch` aktualisiert
- Der LLM-Kontext ist auf 8000 Zeichen pro Datei begrenzt
- Timeout: 5 Minuten pro Issue — bei Überschreitung bleibt `bot::lösungsvorschlag` aus und das Issue kann manuell via `/solve` neu getriggert werden
