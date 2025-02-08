import logging

logger = logging.getLogger("worker")

if not logger.hasHandlers():
    logging.basicConfig(
        format="[{asctime}] [{levelname}] ({name}) {message}",
        style="{",
        level=logging.INFO,
    )
    logger = logging.getLogger("worker")
