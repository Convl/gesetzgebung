import logging
import logging.handlers
import sys
import os
import inspect
import functools
from threading import local, RLock
from gesetzgebung.models import set_update_active

ERROR_MAIL_PASSWORD = os.environ.get("ERROR_MAIL_PASSWORD")
ERROR_MAIL_ADDRESS = os.environ.get("ERROR_MAIL_ADDRESS")
ERROR_MAIL_SMTP = "smtp.gmail.com"
DEVELOPER_MAIL_ADDRESS = os.environ.get("DEVELOPER_MAIL_ADDRESS")
MAX_LOG_LINE_LENGTH = 135
INDENT_BY = 4
logger_dict = {}

# Made some attempts at thread-safety here (nowhere else though...)
# TODO: Rewrite this to some degree. Encapsulate both LogIndent and _indentation inside CustomLogger, make messages from decorator function log_indent get printed instantly instead of added to a queue.
_indentation = local()
_indentation.level = 0
_indentation.messages = []
_logger_lock = RLock()


class LogIndent:
    """Context manager for indenting logs"""

    def __init__(self, message=None):
        if message:
            _indentation.messages = getattr(_indentation, "messages", [])
            _indentation.messages.append(message)

    def __enter__(self):
        _indentation.level = getattr(_indentation, "level", 0) + 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _indentation.level = max(0, getattr(_indentation, "level", 0) - 1)
        if getattr(_indentation, "messages", ["dummy"]):
            _indentation.messages.pop(-1)


def get_indent():
    """Returns the appropriate amount of whitespace for the current indentation level"""
    return " " * getattr(_indentation, "level", 0) * INDENT_BY


def log_indent(func):
    """Decorator to apply the LogIndent context manager to a function"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with LogIndent(
            f"{' ' * (getattr(_indentation, "level", 0) + 1) * INDENT_BY}##### Entering function {func.__name__} #####"
        ):
            return func(*args, **kwargs)

    return wrapper


class CustomFormatter(logging.Formatter):
    """Custom Formatter that indents records by _indentation.level"""

    def format(self, record):
        # attach format string
        formatted = super().format(record)

        # indent each line according to _indentation.level
        if whitespace := (get_indent()):
            lines = formatted.splitlines()
            formatted = "\n".join(whitespace + line for line in lines)

        # make sure no line is > MAX_LOG_LINE_LENGTH
        lines = []
        for line in formatted.splitlines():
            while len(line) > MAX_LOG_LINE_LENGTH:
                offset = len(get_indent())
                if (cutoff := line[:MAX_LOG_LINE_LENGTH].rfind(" ", offset) + 1) == 0:
                    cutoff = MAX_LOG_LINE_LENGTH
                lines.append(line[:cutoff])
                line = get_indent() + line[cutoff:]
            lines.append(line)
        formatted = "\n".join(lines)

        # attach message(s) up top, if any
        if messages := getattr(_indentation, "messages", []):
            formatted = "\n".join(message for message in messages) + "\n" + formatted
            setattr(_indentation, "messages", [])

        # add a newline up top
        formatted = "\n" + formatted

        return formatted


# Custom class so we can specify mail subjects if we want to
class CustomSmtpHandler(logging.handlers.SMTPHandler):
    def __init__(self, mailhost, fromaddr, toaddrs, subject, credentials=None, secure=None, timeout=5.0):
        super().__init__(mailhost, fromaddr, toaddrs, subject, credentials, secure, timeout)

    def getSubject(self, record) -> str:
        return getattr(record, "subject", "Error in Application, see message for details")


class CustomLogger(logging.Logger):
    """Custom class that will:
    1. Always log to console
    2. Also log to mail for logging.ERROR and above
    3. sys.exit() for logging.CRITICAL"""

    def __init__(self, name: str = "daily_update", log_level: int = logging.DEBUG):
        super().__init__(name, log_level)

        if self.handlers:
            return

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        formatter = CustomFormatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(real_funcName)s - %(real_lineno)d - %(message)s",
            datefmt="%m/%d/%Y %H:%M:%S",
        )
        console_handler.setFormatter(formatter)
        self.addHandler(console_handler)

        email_handler = CustomSmtpHandler(
            mailhost=(ERROR_MAIL_SMTP, 587),
            fromaddr=ERROR_MAIL_ADDRESS,
            credentials=(ERROR_MAIL_ADDRESS, ERROR_MAIL_PASSWORD),
            toaddrs=DEVELOPER_MAIL_ADDRESS,
            subject="Error in Application, see message for details",
            secure=(),
        )
        email_handler.setLevel(logging.ERROR)
        email_handler.setFormatter(formatter)
        self.addHandler(email_handler)

    def debug(self, msg: str, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self.log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, subject: str = None, *args, **kwargs):
        self.log(logging.ERROR, msg, subject=subject, *args, **kwargs)

    def critical(self, msg: str, subject: str = None, *args, **kwargs):
        self.log(logging.CRITICAL, msg, subject=subject, *args, **kwargs)

    def log(self, level: int, msg: str, *args, subject: str = None, **kwargs):
        # get func_name, file_name and lineno by going two frame back in the call stack, as otherwise it will just be the function name / line number from within this class
        frame = inspect.currentframe().f_back.f_back
        func_name = frame.f_code.co_name
        lineno = frame.f_lineno
        file_name = frame.f_code.co_filename

        kwargs["extra"] = kwargs.get("extra", {})
        kwargs["extra"]["real_funcName"] = func_name
        kwargs["extra"]["real_lineno"] = lineno
        kwargs["extra"]["real_filename"] = file_name

        if subject:
            kwargs["extra"]["subject"] = subject

        super().log(level, msg, *args, **kwargs)

        # Here, we can specify individual teardown behaviour depending on where the logger is being used
        if level >= logging.CRITICAL:

            if self.name == "update_logger":
                set_update_active(False)

            sys.exit(1)


def get_logger(name: str) -> CustomLogger:
    global logger_dict

    with _logger_lock:
        if not logger_dict.get(name):
            logger_dict[name] = CustomLogger(name)

    return logger_dict[name]
