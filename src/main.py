from pathlib import Path
from libgit import Repository
from log import create_logger, reset_log_file
from conf_globals import G_LOG_LEVEL, G_THREAD_NUM_WORKERS
from concurrent.futures import ThreadPoolExecutor

logger = create_logger("src.main", G_LOG_LEVEL)

repos = []
to = (Path(__name__).parent.parent / "tests/gitclone/repos").resolve()

def clone_all_task(repo: Repository, to: Path):
    repo.clone_from(to)
    
    # for branch in repo.repo_branches:
    #     repo.clone_from(to, branch=branch)
        
    # return
    
    with ThreadPoolExecutor(max_workers=G_THREAD_NUM_WORKERS) as executor:
        logger.info(f"Submitting clone_from for branches {', '.join(branch.name for branch in repo.repo_branches)} with {G_THREAD_NUM_WORKERS=}")
        futures = [executor.submit(repo.clone_from, to, branch=branch) for branch in repo.repo_branches]
        
        for future in futures:
            try:
                f = future.result()
                logger.info(f"{f.name} Result branch awaited successful")
            except Exception as e:
                logger.error(f"Error cloning repository branch {e}")

        logger.info(f"Done awaiting all ({len(futures)}) futures")


def main() -> bool:
    global repos
    global to
    
    logger.info(f"Main Clone Directory: {to}")

    with ThreadPoolExecutor(max_workers=G_THREAD_NUM_WORKERS) as executor:
        logger.info(f"Submitting clone_all_task for repositories [{', '.join(repo.name for repo in repos)}] with {G_THREAD_NUM_WORKERS=}")
        futures = [executor.submit(clone_all_task, repo, to) for repo in repos]
        
        for future in futures:
            try:
                f = future.result()
                logger.info(f"{f} Result awaited successful")
            except Exception as e:
                logger.error(f"Error cloning repository {e}")

        logger.info(f"Done awaiting all ({len(futures)}) futures")

    return True

if __name__ == "__main__":
    reset_log_file()
    main()