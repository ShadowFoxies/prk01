"""
Модуль користувацьких винятків для діагностики кластера.
"""

__all__ = [
    "ClusterMonitorError",
    "CorruptedLogRecordError",
    "InvalidBitmaskError",
    "StorageSubsystemError",
]


class ClusterMonitorError(Exception):
    """Базовий виняток для всіх помилок утиліти моніторингу."""


class CorruptedLogRecordError(ClusterMonitorError):
    """Виникає при порушенні формату або синтаксису рядка логу."""

    def __init__(self, message: str, line_number: int = 0, raw_line: str = "") -> None:
        self.line_number = line_number
        self.raw_line = raw_line
        super().__init__(f"[Рядок {line_number}] {message}: {raw_line!r}")


class InvalidBitmaskError(ClusterMonitorError):
    """Виникає при некоректному значенні шістнадцяткового регістру або маски."""

    def __init__(self, mask_value: str | int, reason: str = "Недійсна бітова маска") -> None:
        self.mask_value = mask_value
        super().__init__(f"{reason}: {mask_value}")


class StorageSubsystemError(ClusterMonitorError):
    """Критична помилка дискової підсистеми (читання логу або запис дампу)."""

    def __init__(self, filepath: str, reason: str) -> None:
        self.filepath = filepath
        super().__init__(f"Помилка роботи з файлом '{filepath}': {reason}")