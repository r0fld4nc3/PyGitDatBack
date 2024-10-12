from pathlib import Path
from libgit import Repository
from log import create_logger
from conf_globals import G_LOG_LEVEL, G_THREAD_NUM_WORKERS
from concurrent.futures import ThreadPoolExecutor

logger = create_logger("src.main", G_LOG_LEVEL)

repos = [
    Repository("https://github.com/r0fld4nc3/Stellaris-Exe-Checksum-Patcher"),
    Repository("https://github.com/Chillsmeit/qBittorrent-ProtonVPN-Guide"),
    Repository("https://github.com/Chillsmeit/PiHole-RPi5-Guide"),
    Repository("https://github.com/Chillsmeit/AutomateGithubSSHkey")
    ]
to = Path(__name__).parent.parent / "tests/gitclone/repos"

def clone_all_task(repo: Repository, to: Path):
    repo.clone_to(to)

    # Do the branches
    repo._collect_branch_names()
    for branch in repo.repo_branches:
        logger.info(f"Cloning branch '{branch}' into {to}...")
        repo.clone_to(to, branch=branch)


def main() -> bool:
    global repos
    global to

    with ThreadPoolExecutor(max_workers=G_THREAD_NUM_WORKERS) as executor:
        logger.info(f"Submitting clone_all_task for repository with {G_THREAD_NUM_WORKERS=}")
        futures = [executor.submit(clone_all_task, repo, to) for repo in repos]
        
        for future in futures:
            try:
                future.result()
                logger.info(f"Result awaited successful")
            except Exception as e:
                logger.error(f"Error cloning repository {e}")

        logger.info(f"Done awaiting all ({len(futures)}) futures")

    return True

if __name__ == "__main__":
    main()