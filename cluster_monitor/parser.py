"""
Модуль синтаксичного розбору та потокового читання лог-файлів телеметрії.
"""

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Iterator

from .exceptions import (
    ClusterMonitorError,
    CorruptedLogRecordError,
    InvalidBitmaskError,
    StorageSubsystemError,
)

__all__ = [
    "LOG_LINE_PATTERN",
    "MAX_VALID_REGISTER",
    "parse_log_line",
    "stream_log_records",
]

# Нас цікавлять 4 молодші біти регістру (0x00 .. 0x0F)
MAX_VALID_REGISTER = 0x0F

# Шаблон без двозначних квантифікаторів, щоб уникнути catastrophic backtracking
LOG_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)"
    r"\s*\|\s*"
    r"(?P<host>(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
    r"|[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+))"
    r"\s*\|\s*"
    r"(?P<health_reg>0[xX][0-9a-fA-F]+)"
    r"\s*\|\s*"
    r"(?P<res_type>CPU|RAM):(?P<res_value>\d+(?:\.\d+)?)(?P<res_unit>%|GB)$"
)


def parse_log_line(raw_line: str, line_number: int = 0) -> dict[str, Any]:
    """Перевіряє синтаксис одного рядка журналу та повертає словник з полями."""
    cleaned = raw_line.strip()
    match = LOG_LINE_PATTERN.match(cleaned)
    if not match:
        raise CorruptedLogRecordError(
            "Рядок не відповідає формату телеметрії",
            line_number=line_number,
            raw_line=cleaned,
        )

    groups = match.groupdict()

    # У Python 3.10 fromisoformat не розуміє 'Z' в кінці, міняємо на +00:00
    ts_str = groups["timestamp"]
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"

    try:
        parsed_ts = datetime.fromisoformat(ts_str)
    except ValueError as exc:
        raise CorruptedLogRecordError(
            "Некоректна дата ISO 8601",
            line_number=line_number,
            raw_line=cleaned,
        ) from exc

    # Перевіряємо діапазон шістнадцяткового регістру стану
    reg_hex = groups["health_reg"]
    reg_int = int(reg_hex, 16)
    if not (0 <= reg_int <= MAX_VALID_REGISTER):
        raise InvalidBitmaskError(
            reg_hex,
            reason=f"Значення регістру виходить за межі 0x00..0x{MAX_VALID_REGISTER:02X}",
        )

    res_type = groups["res_type"]
    res_value = float(groups["res_value"])
    res_unit = groups["res_unit"]

    # Узгоджуємо одиниці виміру: CPU у відсотках (0..100), RAM у гігабайтах
    if res_type == "CPU" and (res_unit != "%" or res_value > 100.0):
        raise CorruptedLogRecordError(
            "Некоректне навантаження CPU",
            line_number=line_number,
            raw_line=cleaned,
        )
    if res_type == "RAM" and res_unit != "GB":
        raise CorruptedLogRecordError(
            "Для RAM очікуються одиниці виміру GB",
            line_number=line_number,
            raw_line=cleaned,
        )

    return {
        "line_number": line_number,
        "timestamp": parsed_ts,
        "host": groups["host"].lower(),
        "health_register": reg_int,
        "resource_type": res_type,
        "resource_value": res_value,
        "resource_unit": res_unit,
    }


def stream_log_records(
    filepath: str | Path,
    errors: list[ClusterMonitorError] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Потоково читає лог-файл рядок за рядком і віддає розібрані записи.
    Якщо передано список errors, биті рядки збираються туди без зупинки потоку.
    """
    path = Path(filepath)
    try:
        # Читаємо файл ітератором рядок за рядком, без read() / readlines()
        with path.open(mode="r", encoding="utf-8") as log_file:
            for line_num, raw_line in enumerate(log_file, start=1):
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                try:
                    yield parse_log_line(stripped, line_number=line_num)
                except (CorruptedLogRecordError, InvalidBitmaskError) as exc:
                    if errors is not None:
                        errors.append(exc)
                    else:
                        raise
    except OSError as exc:
        raise StorageSubsystemError(str(path), str(exc)) from exc