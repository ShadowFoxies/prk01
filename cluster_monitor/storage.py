"""
Модуль відмовостійкого збереження підсумкового дампу інцидентів.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, TextIO

from .exceptions import StorageSubsystemError
from .models import FLAG_LABELS, BaseNodeMetric

__all__ = [
    "IncidentDumpWriter",
    "save_incident_dump",
]


class IncidentDumpWriter:
    """
    Контекстний менеджер для безпечного запису дампу через тимчасовий файл (RAII).
    Якщо під час запису стається збій, основний файл не пошкоджується.
    """

    def __init__(self, target_path: str | Path, encoding: str = "utf-8") -> None:
        self.target_path = Path(target_path)
        self.encoding = encoding
        self._temp_path = self.target_path.with_suffix(self.target_path.suffix + ".tmp")
        self._file: TextIO | None = None

    def __enter__(self) -> TextIO:
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._temp_path.open(mode="w", encoding=self.encoding)
        return self._file

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if self._file is not None:
            try:
                if exc_type is None:
                    self._file.flush()
            finally:
                # Обов'язково закриваємо файл до os.replace (критично для Windows)
                self._file.close()
                self._file = None

        if exc_type is None and self._temp_path.exists():
            os.replace(self._temp_path, self.target_path)
        elif self._temp_path.exists():
            self._temp_path.unlink(missing_ok=True)

        # Повертаємо False, щоб помилки не глушилися мовчки
        return False


def _serialize_incident(node: BaseNodeMetric) -> dict[str, Any]:
    """Перетворює об'єкт вузла в словник для експорту у JSON."""
    return {
        "host": node.host,
        "node_type": node.node_type,
        "timestamp": node.timestamp.isoformat(),
        "health_register": f"0x{node.health_register:02X}",
        "active_flags": [FLAG_LABELS[f] for f in node.active_flags()],
        "resource_value": node.resource_value,
        "resource_unit": node.resource_unit,
        "alert_level": node.get_alert_level() if hasattr(node, "get_alert_level") else "UNKNOWN",
    }


def save_incident_dump(
    filepath: str | Path,
    analysis_result: dict[str, Any],
    parse_errors_count: int = 0,
) -> dict[str, Any]:
    """
    Зберігає аналітичний звіт інцидентів у JSON-файл з багаторівневою
    обробкою помилок try-except-else-finally.
    """
    path = Path(filepath)
    incidents_sorted = sorted(
        analysis_result["unique_incidents"],
        key=lambda item: item.timestamp,
    )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_records": analysis_result["total_records"],
            "total_hosts": analysis_result["total_hosts"],
            "degraded_hosts_count": len(analysis_result["degraded_hosts"]),
            "degraded_hosts": sorted(analysis_result["degraded_hosts"]),
            "parse_errors_skipped": parse_errors_count,
            "flag_statistics": analysis_result["flag_counts"],
        },
        "incidents": [_serialize_incident(node) for node in incidents_sorted],
    }

    status_info: dict[str, Any] = {"saved": False, "path": str(path), "bytes": 0}

    try:
        with IncidentDumpWriter(path) as dump_file:
            try:
                json.dump(payload, dump_file, ensure_ascii=False, indent=2)
            except (TypeError, ValueError) as exc:
                raise StorageSubsystemError(
                    str(path),
                    f"Помилка серіалізації даних: {exc}",
                ) from exc
    except OSError as exc:
        raise StorageSubsystemError(str(path), f"Збій запису на диск: {exc}") from exc
    else:
        status_info["saved"] = True
        status_info["bytes"] = path.stat().st_size
    finally:
        # Гарантована фіксація часу завершення операції збереження
        status_info["completed_at"] = datetime.now(timezone.utc).isoformat()

    return status_info