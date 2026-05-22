import asyncio
import hmac
import logging
import httpx
from fastapi import FastAPI, Request, HTTPException, Header
from gitlab_client import fetch_project, fetch_issue, fetch_issue_comments, post_comment, set_label, repo_clone_url
from repo_manager import ensure_repo
from solver import run_solver
from config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="GitLab Issue Solver")

SKIP_LABELS = {"bot::lösungsvorschlag", "bot::prioritätsliste"}

_queue: asyncio.Queue = asyncio.Queue()


def _verify_secret(token: str | None) -> None:
    if not settings.webhook_secret:
        return
    if not token or not hmac.compare_digest(token, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Ungültiges Webhook-Secret")


async def _process(project_id: str | int, issue_iid: int, clone_url: str, default_branch: str = "main") -> dict:
    issue = await fetch_issue(project_id, issue_iid)

    existing = set(issue.get("labels", []))
    if "bot::lösungsvorschlag" in existing:
        return {"status": "ignored", "reason": "already solved"}
    if SKIP_LABELS & existing:
        return {"status": "ignored", "reason": "skip label"}
    if "type::bug" not in existing:
        return {"status": "ignored", "reason": "not a bug"}

    comments = await fetch_issue_comments(project_id, issue_iid)
    repo_path = await ensure_repo(project_id, clone_url, default_branch)
    log.info(f"Starte Solver für Issue #{issue_iid}")

    result = None
    for attempt in range(3):
        try:
            result = await run_solver(issue, comments, repo_path)
            break
        except httpx.HTTPStatusError as e:
            if "tool_use_failed" in e.response.text and attempt < 2:
                log.warning(f"Tool-Call Format-Fehler, Retry {attempt + 1}/3")
                continue
            raise
    if result is None:
        raise RuntimeError("Solver nach 3 Versuchen fehlgeschlagen")

    comment = (
        f"**KI-Lösungsvorschlag**\n\n"
        f"{result}\n\n"
        f"---\n*Automatisch generiert von gitlab-issue-solver*"
    )
    await post_comment(project_id, issue_iid, comment)
    await set_label(project_id, issue_iid, "bot::lösungsvorschlag")

    log.info(f"Issue #{issue_iid} gelöst")
    return {"status": "ok"}


async def _worker() -> None:
    while True:
        project_id, issue_iid, clone_url, default_branch = await _queue.get()
        log.info(f"Queue: verarbeite Issue #{issue_iid} ({_queue.qsize()} verbleibend)")
        try:
            await _process(project_id, issue_iid, clone_url, default_branch)
        except Exception as e:
            log.error(f"Queue-Worker Fehler bei Issue #{issue_iid}: {e}")
        finally:
            _queue.task_done()


@app.on_event("startup")
async def startup():
    asyncio.create_task(_worker())
    log.info("Solver-Queue gestartet")


@app.post("/webhook")
async def webhook(request: Request, x_gitlab_token: str | None = Header(None)):
    _verify_secret(x_gitlab_token)

    payload = await request.json()

    if payload.get("object_kind") != "issue":
        return {"status": "ignored"}

    attrs = payload.get("object_attributes", {})
    if attrs.get("action") not in ("open", "update"):
        return {"status": "ignored"}

    changes = payload.get("changes", {})
    label_changes = changes.get("labels", {})
    previous = {lbl["title"] for lbl in label_changes.get("previous", [])}
    current = {lbl["title"] for lbl in label_changes.get("current", [])}

    if "bot::prio-gesetzt" not in (current - previous):
        return {"status": "ignored"}

    if "type::bug" not in current:
        return {"status": "ignored"}

    project = payload["project"]
    clone_url = repo_clone_url(project)
    default_branch = project.get("default_branch", "main")

    await _queue.put((project["id"], attrs["iid"], clone_url, default_branch))
    log.info(f"Issue #{attrs['iid']} in Queue ({_queue.qsize()} gesamt)")
    return {"status": "queued"}


@app.post("/solve")
async def solve(project_id: str, issue_iid: int):
    project = await fetch_project(project_id)
    clone_url = repo_clone_url(project)
    default_branch = project.get("default_branch", "main")
    try:
        return await _process(project_id, issue_iid, clone_url, default_branch)
    except Exception as e:
        log.error(f"Solver fehlgeschlagen: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "queue_size": _queue.qsize()}
