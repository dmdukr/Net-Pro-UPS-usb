"""File logging helpers for NetPRO UPS USB."""

from __future__ import annotations

from logging.handlers import RotatingFileHandler
import logging
import os
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER_NAME, LOG_BACKUP_COUNT, LOG_FILE_NAME, LOG_MAX_BYTES

_LOGGER = logging.getLogger(__name__)
_HANDLER_KEY = "file_log_handler"
_PATH_KEY = "file_log_path"


class _ResilientRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that recreates the log file if deleted externally."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not os.path.exists(self.baseFilename):
                if self.stream:
                    self.stream.close()
                self.stream = self._open()
        except Exception:
            pass
        super().emit(record)


def setup_integration_file_logger(hass: HomeAssistant) -> str:
    """Attach a rotating file handler for integration diagnostics."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if _PATH_KEY in domain_data:
        return domain_data[_PATH_KEY]

    log_path = Path(hass.config.path(LOG_FILE_NAME))
    logger = logging.getLogger(LOGGER_NAME)

    handler = _ResilientRotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )

    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    domain_data[_HANDLER_KEY] = handler
    domain_data[_PATH_KEY] = str(log_path)

    _LOGGER.info("Integration file log enabled: %s", log_path)
    return str(log_path)


def teardown_integration_file_logger(hass: HomeAssistant) -> None:
    """Remove the file handler when the last config entry is unloaded."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None:
        return

    handler = domain_data.pop(_HANDLER_KEY, None)
    if handler is not None:
        logger = logging.getLogger(LOGGER_NAME)
        logger.removeHandler(handler)
        handler.close()
        _LOGGER.debug("Integration file log handler removed")

    domain_data.pop(_PATH_KEY, None)