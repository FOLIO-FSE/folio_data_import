import importlib.metadata
import logging
import sys
from datetime import datetime as dt

import questionary
from rich.logging import RichHandler


def get_folio_connection_parameters(
    gateway_url: str | None, tenant_id: str | None, username: str | None, password: str | None
) -> tuple[str, str, str, str]:
    """
    Prompt for missing FOLIO connection parameters using interactive input.

    Parameters:
        gateway_url (str): The FOLIO Gateway URL, or None to prompt for input.
        tenant_id (str): The FOLIO Tenant ID, or None to prompt for input.
        username (str): The FOLIO Username, or None to prompt for input.
        password (str): The FOLIO password, or None to prompt for input.

    Returns:
        tuple: A tuple containing (gateway_url, tenant_id, username, password).
    """
    if not gateway_url:
        gateway_url = questionary.text("Enter FOLIO Gateway URL:").ask()
    if not tenant_id:
        tenant_id = questionary.text("Enter FOLIO Tenant ID:").ask()
    if not username:
        username = questionary.text("Enter FOLIO Username:").ask()
    if not password:
        password = questionary.password("Enter FOLIO password:").ask()
    return gateway_url, tenant_id, username, password


# Logging setup and customizations

# Custom log level for data issues, set to 26
DATA_ISSUE_LVL_NUM = 26
logging.addLevelName(DATA_ISSUE_LVL_NUM, "DATA_ISSUES")


class CustomLogger(logging.Logger):
    """Logger subclass with custom data_issues method."""

    def data_issues(self, msg: str, *args, **kws) -> None:
        """Log data issues at custom level (26)."""
        if self.isEnabledFor(DATA_ISSUE_LVL_NUM):
            self._log(DATA_ISSUE_LVL_NUM, msg, args, **kws)


class ExcludeLevelFilter(logging.Filter):
    def __init__(self, level) -> None:
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno != self.level


class IncludeLevelFilter(logging.Filter):
    def __init__(self, level) -> None:
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level


# Set the custom logger class as the default
logging.setLoggerClass(CustomLogger)


def set_up_cli_logging(
    logger: logging.Logger,
    log_file_prefix: str,
    debug: bool = False,
    log_data_issues: bool = False,
    stream_level: int = logging.INFO,
) -> None:
    """
    This function sets up logging for the CLI.

    Parameters:
        logger (logging.Logger): The logger to configure.
        log_file_prefix (str): The prefix for the log file name.
        debug (bool): Whether to enable debug logging.
        log_data_issues (bool): Whether to enable logging of data issues.
        stream_level (int): The logging level for the stream handler (default: logging.INFO).
    """
    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    logger.propagate = False

    # Set up file and stream handlers
    file_handler = logging.FileHandler(
        "{}_{}.log".format(log_file_prefix, dt.now().strftime("%Y%m%d%H%M%S"))
    )
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    if log_data_issues:
        file_handler.addFilter(ExcludeLevelFilter(DATA_ISSUE_LVL_NUM))
    # file_handler.addFilter(IncludeLevelFilter(25))
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    if not any(
        isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in logger.handlers
    ):
        stream_handler = RichHandler(
            show_level=False,
            show_time=False,
            omit_repeated_times=False,
            show_path=False,
        )
        stream_handler.setLevel(logging.DEBUG if debug else stream_level)
        if log_data_issues:
            stream_handler.addFilter(ExcludeLevelFilter(DATA_ISSUE_LVL_NUM))
        stream_formatter = logging.Formatter("%(message)s")
        stream_handler.setFormatter(stream_formatter)
        logger.addHandler(stream_handler)

    # Set up data issues logging
    if log_data_issues:
        data_issues_handler = logging.FileHandler(
            "data_issues_{}_{}.log".format(log_file_prefix, dt.now().strftime("%Y%m%d%H%M%S"))
        )
        data_issues_handler.setLevel(26)
        data_issues_handler.addFilter(IncludeLevelFilter(DATA_ISSUE_LVL_NUM))
        data_issues_formatter = logging.Formatter("%(message)s")
        data_issues_handler.setFormatter(data_issues_formatter)
        logger.addHandler(data_issues_handler)

    # Stop httpx from logging info messages to the console
    logging.getLogger("httpx").setLevel(logging.WARNING)


__version__ = importlib.metadata.version("folio-data-import")
