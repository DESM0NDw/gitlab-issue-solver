import asyncio
import logging
from pathlib import Path
from config import settings

log = logging.getLogger(__name__)


async def _git(*args, cwd: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr.decode()}")


async def ensure_repo(project_id: str | int, clone_url: str) -> Path:
    repo_path = Path(settings.repos_base_path) / str(project_id)

    if repo_path.exists():
        log.info(f"Repo {project_id}: fetch + reset")
        await _git("fetch", "--prune", cwd=repo_path)
        await _git("reset", "--hard", "origin/HEAD", cwd=repo_path)
    else:
        log.info(f"Repo {project_id}: initial clone")
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        await _git("clone", "--filter=blob:none", clone_url, str(repo_path), cwd=repo_path.parent)

    return repo_path
