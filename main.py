import hmac
import logging
from fastapi import FastAPI, Request, HTTPException, Header
from gitlab_client import fetch_project, fetch_issue, fetch_issue_comments, post_comment, set_label, repo_clone_url
from repo_manager import ensure_repo
from solver import run_solver
from config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="GitLab Issue Solver")

SKIP_LABELS = {"bot::lösungsvorschlag", "bot::prioritätsliste"}


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

    comments = await fetch_issue_comments(project_id, issue_iid)

    repo_path = await ensure_repo(project_id, clone_url, default_branch)
    log.info(f"Starte Solver für Issue #{issue_iid}")

    result = await run_solver(issue, comments, repo_path)

    comment = (
        f"**KI-Lösungsvorschlag**\n\n"
        f"{result}\n\n"
        f"---\n*Automatisch generiert von gitlab-issue-solver*"
    )
    await post_comment(project_id, issue_iid, comment)
    await set_label(project_id, issue_iid, "bot::lösungsvorschlag")

    log.info(f"Issue #{issue_iid} gelöst")
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request, x_gitlab_token: str | None = Header(None)):
    _verify_secret(x_gitlab_token)

    payload = await request.json()

    if payload.get("object_kind") != "issue":
        return {"status": "ignored"}

    attrs = payload.get("object_attributes", {})
    if attrs.get("action") not in ("open", "update"):
        return {"status": "ignored"}

    # Nur wenn bot::prio-gesetzt gerade NEU hinzugefügt wurde
    changes = payload.get("changes", {})
    label_changes = changes.get("labels", {})
    previous = {lbl["title"] for lbl in label_changes.get("previous", [])}
    current = {lbl["title"] for lbl in label_changes.get("current", [])}
    if "bot::prio-gesetzt" not in (current - previous):
        return {"status": "ignored"}

    project = payload["project"]
    clone_url = repo_clone_url(project)
    default_branch = project.get("default_branch", "main")

    try:
        return await _process(project["id"], attrs["iid"], clone_url, default_branch)
    except Exception as e:
        log.error(f"Solver fehlgeschlagen für Issue #{attrs['iid']}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    return {"status": "ok"}
