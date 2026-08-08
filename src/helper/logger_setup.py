import logging
from pathlib import Path
from datetime import datetime


def _get_log_file_path(name: str) -> Path:
    try:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return log_dir / f"{name}_{timestamp}.log"

    except Exception as exc:
        print(f"Failed to create log directory or file: {exc}")
        raise


def setup_logger(name: str = "sbr") -> logging.Logger:
    """
    Configure and return a named logger that writes to a timestamped file
    and to the console.

    Calling this function multiple times for the same logger name will not
    add duplicate handlers.
    """
    logger = logging.getLogger(name)

    # Check before generating another unused filename.
    if logger.handlers:
        return logger

    logfile = _get_log_file_path(name)

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        logfile,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger
