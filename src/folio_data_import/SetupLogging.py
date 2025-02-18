import logging

class ExcludeLevelFilter(logging.Filter):
    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno != self.level

class LevelFilter(logging.Filter):
    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level

def setup_logging(logfile, errorfile):
    DATA_ISSUE_LVL_NUM = 26
    logging.addLevelName(DATA_ISSUE_LVL_NUM, "DATA_ISSUES")
    logger = logging.getLogger()
    logger.propogate = True
    logger.handlers = []
    formatter = logging.Formatter(
        "%(asctime)s\t%(levelname)s\t%(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    stream_handler = logging.StreamHandler()
    stream_handler.addFilter(ExcludeLevelFilter(26))
    logger.setLevel(logging.INFO)
    stream_handler.setLevel(logging.INFO)
    stream_handler.addFilter(ExcludeLevelFilter(30))  # Exclude warnings from pymarc
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(
        filename=logfile, mode="w"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(ExcludeLevelFilter(26))
    # file_handler.addFilter(LevelFilter(0, 20))
    file_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)

    # Data issue file formatter
    data_issue_file_handler = logging.FileHandler(
        filename=errorfile, mode="w"
    )
    data_issue_file_handler.setFormatter("%(message)s")
    data_issue_file_handler.addFilter(LevelFilter(26))
    data_issue_file_handler.setLevel(26)
    logger.addHandler(data_issue_file_handler)
    logging.info("Logging set up")
