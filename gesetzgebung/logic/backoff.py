import functools
import sys
import time

from gesetzgebung.logic.webapp_logger import webapp_logger


def exp_backoff(
    attempts=5, base_delay=1, terminate_on_final_failure=True, callback_on_first_failure=None, pass_attempt_count=False
):
    """Decorator function for implementing exponential backoff, e.g. when querying LLMs or Google News"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, attempts + 1):
                try:
                    if pass_attempt_count:
                        return func(attempt=attempt, *args, **kwargs)
                    else:
                        return func(*args, **kwargs)
                except Exception as e:
                    webapp_logger.warning(
                        f"Exception while trying to execute function {func.__name__} with exponential backoff: {e}"
                    )
                if attempt == 1 and callback_on_first_failure:
                    try:
                        callback_on_first_failure()
                    except Exception as e:
                        callback_name = getattr(
                            callback_on_first_failure,
                            "__name__",
                            "of unknown name. Likely something that is not a function was passed as a callback.",
                        )
                        webapp_logger.critical(f"Callback function {callback_name} raised error: {e}")
                if attempt < attempts:
                    delay *= 2
                    webapp_logger.warning(f"Retrying in {delay} seconds.")
                    time.sleep(delay)
            webapp_logger.error(
                f"All {attempts} attempts at executing {func.__name__} failed. Terminating.",
                subject="Exponential backoff failed all retries",
            )
            if terminate_on_final_failure:
                sys.exit(1)

        return wrapper

    return decorator


class ExpBackoffException(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)
