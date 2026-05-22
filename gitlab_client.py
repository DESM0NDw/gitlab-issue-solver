import httpx
from config import settings

HEADERS = {"PRIVATE-TOKEN": settings.gitlab_token}


def _url(project_id: str | int, path: str) -> str:
    return f"{settings.gitlab_url}/api/v4/projects/{project_id}{path}"


async def fetch_project(project_id: str | int) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.gitlab_url}/api/v4/projects/{project_id}",
            headers=HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()


async def fetch_issue(project_id: str | int, issue_iid: int) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(_url(project_id, f"/issues/{issue_iid}"), headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()


async def fetch_issue_comments(project_id: str | int, issue_iid: int) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _url(project_id, f"/issues/{issue_iid}/notes"),
            headers=HEADERS,
            params={"per_page": 20, "sort": "asc"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()


async def post_comment(project_id: str | int, issue_iid: int, body: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            _url(project_id, f"/issues/{issue_iid}/notes"),
            headers=HEADERS,
            json={"body": body},
            timeout=10,
        )


async def set_label(project_id: str | int, issue_iid: int, label: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.put(
            _url(project_id, f"/issues/{issue_iid}"),
            headers=HEADERS,
            json={"add_labels": label},
            timeout=10,
        )


def repo_clone_url(project: dict) -> str:
    url = project["http_url_to_repo"]
    return url.replace("https://", f"https://oauth2:{settings.gitlab_token}@")
