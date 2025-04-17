import logging
import logging.handlers
import sys
import os
from gesetzgebung.models import set_update_active

ERROR_MAIL_PASSWORD = os.environ.get("ERROR_MAIL_PASSWORD")
ERROR_MAIL_ADDRESS = os.environ.get("ERROR_MAIL_ADDRESS")
ERROR_MAIL_SMTP = "smtp.gmail.com"
DEVELOPER_MAIL_ADDRESS = os.environ.get("DEVELOPER_MAIL_ADDRESS")
logger_dict = {}

# Custom class so we can specify mail subjects if we want to
class CustomSmtpHandler(logging.handlers.SMTPHandler):
    def __init__(self, mailhost, fromaddr, toaddrs, subject, credentials=None, secure=None, timeout=5.0):
        super().__init__(mailhost, fromaddr, toaddrs, subject, credentials, secure, timeout)

    def getSubject(self, record) -> str:
        return getattr(record, "subject") or "Error in Application, see message for details"


class CustomLogger(logging.Logger):
    """Custom class that will: 1. Always log to console, 2. Also log to mail for logging.ERROR and above, 3. sys.exit() for logging.CRITICAL"""

    def __init__(self, name: str = "daily_update", log_level: int = logging.INFO):
        super().__init__(name, log_level)

        if self.handlers:
            return

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(lineno)d - %(message)s",
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

    def error(self, msg: str, subject: str = None, *args, **kwargs):
        self.log(logging.ERROR, msg, subject=subject, *args, **kwargs)

    def critical(self, msg: str, subject: str = None, *args, **kwargs):
        self.log(logging.CRITICAL, msg, subject=subject, *args, **kwargs)

    def log(self, level: int, msg: str, *args, subject: str = None, **kwargs):
        if subject:
            kwargs["extra"] = kwargs.get("extra", {})
            if isinstance(kwargs["extra"], dict):
                kwargs["extra"]["subject"] = subject

        super().log(level, msg, *args, **kwargs)

        # Here, we can specify individual teardown behaviour depending on where the logger is being used
        if level >= logging.CRITICAL:
            super().log(level, "Terminating program due to critical error.")

            if self.name == "daily_update_logger":
                set_update_active(False)

            sys.exit(1)


def get_logger(name: str) -> CustomLogger:
    global logger_dict
    
    if not logger_dict.get(name):
        logger_dict[name] = CustomLogger(name)

    return logger_dict[name]
