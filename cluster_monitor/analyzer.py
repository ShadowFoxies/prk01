"""
Модуль фільтрації та статистичного аналізу телеметрії кластера.
"""

from typing import Any, Iterable

from .models import BaseNodeMetric, ComputeNode, FLAG_LABELS, HealthFlag, StorageNode

__all__ = [
    "filter_nodes",
    "compute_resource_stats",
    "analyze_telemetry",
]


def filter_nodes(
    nodes: Iterable[BaseNodeMetric],
    *required_flags: HealthFlag,
    node_type: str | None = None,
    only_pre_emergency: bool = False,
    **extra_filters: Any,
) -> list[BaseNodeMetric]:
    """
    Фільтрує вузли за прапорами (*args), типом та передаварійним станом
    (keyword-only), а також додатковими критеріями (**kwargs: min_load, host_prefix).
    """
    min_load = extra_filters.get("min_load")
    host_prefix = extra_filters.get("host_prefix")

    result: list[BaseNodeMetric] = []
    for node in nodes:
        if node_type and node.node_type != node_type.upper():
            continue
        if only_pre_emergency and not node.is_pre_emergency:
            continue
        # Перевіряємо всі передані через *args бітові прапори
        if required_flags and not all(node.has_flag(flag) for flag in required_flags):
            continue
        if min_load is not None and node.resource_value < float(min_load):
            continue
        if host_prefix and not node.host.startswith(host_prefix.lower()):
            continue
        result.append(node)

    return result


def compute_resource_stats(values: Iterable[float]) -> tuple[float, float, float]:
    """
    Рахує (min, avg, max) для послідовності числових метрик.
    Повертає кортеж нулів, якщо даних немає.
    """
    count = 0
    total = 0.0
    min_val = float("inf")
    max_val = float("-inf")

    for val in values:
        count += 1
        total += val
        if val < min_val:
            min_val = val
        if val > max_val:
            max_val = val

    if count == 0:
        return (0.0, 0.0, 0.0)
    return (min_val, total / count, max_val)


def analyze_telemetry(nodes: Iterable[BaseNodeMetric]) -> dict[str, Any]:
    """
    Виконує повну агрегацію метрик кластера з підбором оптимальних структур даних:
    - dict для швидкого групування записів за хостами (O(1) доступ);
    - set для відбору унікальних деградованих вузлів та інцидентів;
    - tuple для незмінних статистичних зрізів;
    - list для впорядкованої стрічки сповіщень.
    """
    grouped_by_host: dict[str, list[BaseNodeMetric]] = {}
    all_nodes: list[BaseNodeMetric] = []

    for node in nodes:
        all_nodes.append(node)
        grouped_by_host.setdefault(node.host, []).append(node)

    # Set comprehension для унікальних хостів з апаратними збоями
    degraded_hosts: set[str] = {
        node.host for node in all_nodes if node.is_degraded
    }

    # Унікальні об'єкти інцидентів (працює завдяки __eq__ та __hash__)
    unique_incidents: set[BaseNodeMetric] = {
        node for node in all_nodes if node.is_degraded or node.is_pre_emergency
    }

    # Генераторні вирази не створюють проміжних списків у пам'яті
    cpu_stats = compute_resource_stats(
        node.resource_value for node in all_nodes if isinstance(node, ComputeNode)
    )
    ram_stats = compute_resource_stats(
        node.resource_value for node in all_nodes if isinstance(node, StorageNode)
    )

    # Підрахунок частоти кожного прапора через dict comprehension
    flag_counts: dict[str, int] = {
        label: sum(1 for node in all_nodes if node.has_flag(flag))
        for flag, label in FLAG_LABELS.items()
    }

    # Формування списку текстових сповіщень через AlertableMixin
    alerts: list[str] = [
        alert
        for node in all_nodes
        if (alert := node.generate_alert()) is not None
    ]

    return {
        "total_records": len(all_nodes),
        "total_hosts": len(grouped_by_host),
        "grouped_by_host": grouped_by_host,
        "degraded_hosts": degraded_hosts,
        "unique_incidents": unique_incidents,
        "cpu_stats": cpu_stats,
        "ram_stats": ram_stats,
        "flag_counts": flag_counts,
        "alerts": alerts,
    }