"""
Модуль об'єктної моделі вузлів кластера та побітової діагностики стану.
"""

from datetime import datetime
from enum import IntFlag
from typing import Any

from .exceptions import InvalidBitmaskError

__all__ = [
    "HealthFlag",
    "FLAG_LABELS",
    "AlertableMixin",
    "BaseNodeMetric",
    "ComputeNode",
    "StorageNode",
    "create_node_from_record",
]

MAX_REGISTER_VALUE = 0x0F


class HealthFlag(IntFlag):
    """Бітові прапори апаратного та системного стану ядра/гіпервізора."""

    NONE = 0x00
    MEMORY_DEGRADATION = 1 << 0   # 0x01: деградація пам'яті (ECC-помилки)
    CPU_THROTTLING = 1 << 1       # 0x02: термальний або енергетичний тротлінг CPU
    COOLING_FAILURE = 1 << 2      # 0x04: відмова системи охолодження
    NETWORK_ISOLATION = 1 << 3    # 0x08: ізоляція мережевого інтерфейсу


FLAG_LABELS: dict[HealthFlag, str] = {
    HealthFlag.MEMORY_DEGRADATION: "Деградація пам'яті",
    HealthFlag.CPU_THROTTLING: "Тротлінг CPU",
    HealthFlag.COOLING_FAILURE: "Відмова охолодження",
    HealthFlag.NETWORK_ISOLATION: "Ізоляція мережі",
}


class AlertableMixin:
    """Міксин для формування рівнів тривоги та системних сповіщень."""

    CRITICAL_MASK = HealthFlag.COOLING_FAILURE | HealthFlag.NETWORK_ISOLATION

    def get_alert_level(self) -> str:
        """Визначає рівень інциденту на основі побітових масок та навантаження."""
        reg = getattr(self, "health_register", 0)
        active = getattr(self, "active_flags", lambda: ())()

        # Критичний рівень: відмова охолодження, ізоляція мережі або 2+ прапори одночасно
        if (reg & self.CRITICAL_MASK) != 0 or len(active) >= 2:
            return "CRITICAL"

        # Передаварійний рівень: є хоча б один прапор або перевищено поріг ресурсів
        if reg != 0 or getattr(self, "is_overloaded", False):
            return "WARNING"

        return "OK"

    def generate_alert(self) -> str | None:
        """Повертає текст системного сповіщення або None, якщо вузол у нормі."""
        level = self.get_alert_level()
        if level == "OK":
            return None

        host = getattr(self, "host", "unknown")
        flags_text = ", ".join(FLAG_LABELS[f] for f in self.active_flags())
        if not flags_text:
            flags_text = "Підвищене споживання ресурсів"

        return f"[{level}] {host} ({self.node_type}): {flags_text}"


class BaseNodeMetric:
    """Базова модель телеметричного запису серверного вузла."""

    node_type = "BASE"
    resource_unit = ""

    def __init__(
        self,
        host: str,
        health_register: int,
        resource_value: float,
        timestamp: datetime,
    ) -> None:
        self._host = host.strip().lower()
        self._timestamp = timestamp
        # Присвоєння через властивості, щоб одразу спрацювала валідація
        self.health_register = health_register
        self.resource_value = resource_value

    @property
    def host(self) -> str:
        return self._host

    @property
    def timestamp(self) -> datetime:
        return self._timestamp

    @property
    def health_register(self) -> int:
        return self._health_register

    @health_register.setter
    def health_register(self, value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidBitmaskError(repr(value), "Регістр має бути цілим числом")
        if not (0 <= value <= MAX_REGISTER_VALUE):
            raise InvalidBitmaskError(
                f"0x{value:02X}",
                f"Регістр поза межами 0x00..0x{MAX_REGISTER_VALUE:02X}",
            )
        self._health_register = value

    @property
    def resource_value(self) -> float:
        return self._resource_value

    @resource_value.setter
    def resource_value(self, value: float) -> None:
        if value < 0:
            raise ValueError(f"Обсяг ресурсів не може бути від'ємним: {value}")
        self._resource_value = float(value)

    @property
    def is_degraded(self) -> bool:
        """True, якщо у регістрі піднято хоча б один апаратний прапор."""
        return self._health_register != HealthFlag.NONE

    @property
    def is_overloaded(self) -> bool:
        """Базова перевірка перевантаження (перевизначається у нащадках)."""
        return False

    @property
    def is_pre_emergency(self) -> bool:
        """Передаварійний стан: тротлінг/пам'ять або перевантаження ресурсів."""
        pre_mask = HealthFlag.MEMORY_DEGRADATION | HealthFlag.CPU_THROTTLING
        return bool(self._health_register & pre_mask) or self.is_overloaded

    def has_flag(self, flag: HealthFlag) -> bool:
        """Побітова перевірка наявності конкретного прапора в регістрі."""
        if flag == HealthFlag.NONE:
            return self._health_register == 0
        return (self._health_register & flag) == flag

    def active_flags(self) -> tuple[HealthFlag, ...]:
        """Повертає кортеж усіх активних прапорів поточного вузла."""
        return tuple(flag for flag in FLAG_LABELS if self.has_flag(flag))

    def __str__(self) -> str:
        flags = ", ".join(FLAG_LABELS[f] for f in self.active_flags()) or "Норма"
        return (
            f"{self._host} [{self.node_type}] | "
            f"Reg: 0x{self._health_register:02X} ({flags}) | "
            f"Load: {self._resource_value:.1f}{self.resource_unit}"
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(host={self._host!r}, "
            f"health_register=0x{self._health_register:02X}, "
            f"resource_value={self._resource_value!r}, "
            f"timestamp={self._timestamp.isoformat()!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseNodeMetric):
            return NotImplemented
        return (
            self.__class__ is other.__class__
            and self._host == other._host
            and self._timestamp == other._timestamp
        )

    def __hash__(self) -> int:
        # Хешуємо лише незмінні поля, щоб об'єкти коректно працювали у set/dict
        return hash((self.__class__, self._host, self._timestamp))


class ComputeNode(AlertableMixin, BaseNodeMetric):
    """Спеціалізований клас для обчислювальних вузлів (метрика CPU у %)."""

    node_type = "COMPUTE"
    resource_unit = "%"
    CPU_WARNING_THRESHOLD = 85.0

    @property
    def cpu_load_percent(self) -> float:
        return self._resource_value

    @property
    def is_overloaded(self) -> bool:
        return self._resource_value >= self.CPU_WARNING_THRESHOLD


class StorageNode(AlertableMixin, BaseNodeMetric):
    """Спеціалізований клас для вузлів сховища даних (метрика RAM у GB)."""

    node_type = "STORAGE"
    resource_unit = "GB"
    RAM_WARNING_THRESHOLD_GB = 48.0

    @property
    def ram_allocated_gb(self) -> float:
        return self._resource_value

    @property
    def is_overloaded(self) -> bool:
        return self._resource_value >= self.RAM_WARNING_THRESHOLD_GB


def create_node_from_record(record: dict[str, Any]) -> BaseNodeMetric:
    """Фабрика для створення об'єкта вузла з розпарсеного запису логу."""
    res_type = record["resource_type"]
    kwargs = {
        "host": record["host"],
        "health_register": record["health_register"],
        "resource_value": record["resource_value"],
        "timestamp": record["timestamp"],
    }
    if res_type == "CPU":
        return ComputeNode(**kwargs)
    if res_type == "RAM":
        return StorageNode(**kwargs)
    raise ValueError(f"Невідомий тип ресурсу для моделі вузла: {res_type}")