import logging
from pathlib import Path
from datetime import datetime


def _get_log_file_path(name: str) -> Path:
    try:
        log_dir = Path(__file__).parent.parent / "logs"
        if not log_dir.exists():
            log_dir.mkdir(parents=True, exist_ok=True)
        logfile = log_dir / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        return logfile
    except Exception as e:
        print(f"Failed to create log directory or file: {e}")
        raise


def setup_logger(name: str = "sbr") -> logging.Logger:
    """
    Configure and return a named logger that writes to a timestamped file
    in src/logs and also to the console. Idempotent (will not add handlers
    twice if called multiple times).
    """
    logfile = _get_log_file_path(name)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    fh = logging.FileHandler(logfile, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    #sh = logging.StreamHandler()
    #sh.setFormatter(fmt)
    #logger.addHandler(sh)

    return logger
