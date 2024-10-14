from pathlib import Path
from libgit import Repository
from log import create_logger, reset_log_file
from conf_globals import G_LOG_LEVEL, THREAD_TIMEOUT_SECONDS
from concurrent.futures import ThreadPoolExecutor

logger = create_logger("src.main", G_LOG_LEVEL)

repos = []
to = (Path(__name__).parent.parent / "tests/gitclone/repos").resolve()

def clone_all_task(repo: Repository, to: Path):
    repo.clone_from(to)
    repo.clone_branches()

def main() -> bool:
    global repos
    global to
    
    logger.info(f"Main Clone Directory: {to}")

    with ThreadPoolExecutor() as executor:
        logger.info(f"Submitting clone_all_task for repositories [{', '.join(repo.name for repo in repos)}]")
        futures = [executor.submit(clone_all_task, repo, to) for repo in repos]
        
        for future in futures:
            try:
                f = future.result(timeout=THREAD_TIMEOUT_SECONDS)
                logger.info(f"{f} Result awaited successful")
            except Exception as e:
                logger.error(f"Error cloning repository {e}")

        logger.info(f"Done awaiting all ({len(futures)}) futures")

    return True

if __name__ == "__main__":
    reset_log_file()
    main()