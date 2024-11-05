from queue import Queue
import threading
from time import sleep
from PySide6.QtCore import QRunnable, QThread, QThreadPool, QObject

from .clone_repo_task import CloneRepoTask
from conf_globals import G_LOG_LEVEL, MAX_CONCURRENT_TASKS
from log import create_logger

logger = create_logger(__name__, G_LOG_LEVEL)


class TaskQueue(QObject):
    _task_lock = threading.Lock()
    _ongoing_tasks: int = 0
    MAX_CONCURRENT_TASKS: int = MAX_CONCURRENT_TASKS

    def __init__(self):
        super().__init__()
        self.queue = Queue()
        self.thread_pool = QThreadPool()
        self.is_running = True
        
        self.worker_thread = QThread()
        self.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.process_tasks)
        self.worker_thread.start()

    @classmethod
    def get_ongoing_tasks(cls) -> int:
        with cls._task_lock:
            return cls._ongoing_tasks
        
    @classmethod
    def increment_ongoing_tasks(cls) -> bool:
        with cls._task_lock:
            if cls._ongoing_tasks < cls.MAX_CONCURRENT_TASKS:
                cls._ongoing_tasks += 1
                return True
            return False
        
    @classmethod
    def decrement_ongoing_tasks(cls):
        with cls._task_lock:
            if cls._ongoing_tasks > 0:
                cls._ongoing_tasks -= 1

    def add_task(self, task: QRunnable | CloneRepoTask):
        self.queue.put(task)
        logger.debug(f"Put task: {task.entry.get_url()}")

    def process_tasks(self):
        while self.is_running:
            if self.queue.qsize() == 0:
                sleep(1) # Prevent busy waiting
                continue

            try:
                # Peek without taking
                task = self.queue.queue[0]

                # Try to increment the task counter
                if self.increment_ongoing_tasks():
                    task = self.queue.get(timeout=1)
                    logger.info(f"Got task {task.entry.get_url()}! Ongoing: {self.get_ongoing_tasks()}")

                    # Wrap run method to handle completion
                    original_run = task.run
                    def wrapped_run():
                        try:
                            original_run()
                        except Exception as e:
                            logger.error(f"Error in wrapped run: {e}")
                        finally:
                            self.decrement_ongoing_tasks()
                            logger.debug(f"Task completed. Remaining active tasks: {self.get_ongoing_tasks()}")

                    task.run = wrapped_run

                    # Start the task
                    self.thread_pool.start(task)
                    self.queue.task_done()
                    sleep(0.5)
                else:
                    # If we can't process now, wait before trying again
                    logger.debug(f"Max concurrent tasks reached ({self.MAX_CONCURRENT_TASKS}). Tasks in queue: {self.queue.qsize()}")
                    sleep(1)
                continue
            except Exception as e:
                logger.error(f"Error processing task: {e}")
                self.decrement_ongoing_tasks()

    def stop(self):
        logger.info("Stopping Task Queue")
        self.is_running = False
        self.worker_thread.quit()
        self.worker_thread.wait()

    def cleanup(self):
        self.stop()

    @classmethod
    def reset_task_counter(cls):
        with cls._task_lock:
            cls._ongoing_tasks = 0
