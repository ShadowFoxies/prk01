"""
Головна точка входу утиліти моніторингу та діагностики вузлів кластера.
"""

from pathlib import Path
import time

from cluster_monitor import (
    ClusterMonitorError,
    HealthFlag,
    StorageSubsystemError,
    analyze_telemetry,
    create_node_from_record,
    filter_nodes,
    save_incident_dump,
    stream_log_records,
)


def print_diagnostic_report(
    analysis: dict,
    parse_errors: list[ClusterMonitorError],
    dump_info: dict,
) -> None:
    """Виводить у консоль форматований аналітичний звіт по кластеру."""
    sep = "=" * 80
    sub_sep = "-" * 80

    print(sep)
    print(f"{'АНАЛІТИЧНИЙ ЗВІТ ДІАГНОСТИКИ ХМАРНОГО КЛАСТЕРА':^80}")
    print(sep)

    print(f"Усього валідних записів:        {analysis['total_records']}")
    print(f"Унікальних хостів у журналі:    {analysis['total_hosts']}")
    print(f"Унікальних деградованих вузлів: {len(analysis['degraded_hosts'])}")
    print(f"Пропущено пошкоджених рядків:   {len(parse_errors)}")

    cpu_min, cpu_avg, cpu_max = analysis["cpu_stats"]
    ram_min, ram_avg, ram_max = analysis["ram_stats"]

    print(sub_sep)
    print(f"{'СТАТИСТИКА СПОЖИВАННЯ РЕСУРСІВ':^80}")
    print(sub_sep)
    print(
        f"| {'Ресурс':<16} | {'Мінімум':<16} | {'Середнє':<16} | {'Максимум':<19} |"
    )
    print(sub_sep)
    print(
        f"| {'CPU (Compute)':<16} | {f'{cpu_min:.1f} %':<16} "
        f"| {f'{cpu_avg:.1f} %':<16} | {f'{cpu_max:.1f} %':<19} |"
    )
    print(
        f"| {'RAM (Storage)':<16} | {f'{ram_min:.1f} GB':<16} "
        f"| {f'{ram_avg:.1f} GB':<16} | {f'{ram_max:.1f} GB':<19} |"
    )

    print(sub_sep)
    print(f"{'РОЗШИФРУВАННЯ АПАРАТНИХ ТА СИСТЕМНИХ ПРАПОРІВ':^80}")
    print(sub_sep)
    for flag_label, count in analysis["flag_counts"].items():
        print(f"  * {flag_label:<32} : {count} раз(ів)")

    print(sub_sep)
    print(f"{'СИСТЕМНІ СПОВІЩЕННЯ (AlertableMixin)':^80}")
    print(sub_sep)
    if analysis["alerts"]:
        for alert_msg in analysis["alerts"]:
            print(f"  {alert_msg}")
    else:
        print("  Інцидентів не зафіксовано.")

    # Демонстрація filter_nodes з *args, keyword-only та **kwargs
    all_grouped = [
        node for host_nodes in analysis["grouped_by_host"].values() for node in host_nodes
    ]
    throttled_high_cpu = filter_nodes(
        all_grouped,
        HealthFlag.CPU_THROTTLING,
        node_type="COMPUTE",
        only_pre_emergency=True,
        min_load=80.0,
    )

    print(sub_sep)
    print(f"{'ВИБІРКА: COMPUTE-ВУЗЛИ З ТРОТЛІНГОМ І CPU >= 80%':^80}")
    print(sub_sep)
    for node in throttled_high_cpu:
        print(f"  -> {node}")

    if parse_errors:
        print(sub_sep)
        print(f"{'ПРОПУЩЕНІ ПОШКОДЖЕНІ ЗАПИСИ ТА НЕВАЛІДНІ МАСКИ':^80}")
        print(sub_sep)
        for err in parse_errors:
            print(f"  [!] {err}")

    print(sub_sep)
    print(
        f"Дамп інцидентів збережено: {dump_info['path']} "
        f"({dump_info['bytes']} байт)"
    )
    print(sep)


def run_pipeline(log_path: Path, dump_path: Path) -> int:
    """Запускає повний цикл читання, аналізу та збереження результатів."""
    parse_errors: list[ClusterMonitorError] = []

    try:
        # Потокове читання -> генератор об'єктів вузлів -> аналіз
        raw_records_stream = stream_log_records(log_path, errors=parse_errors)
        nodes_stream = (create_node_from_record(rec) for rec in raw_records_stream)
        analysis = analyze_telemetry(nodes_stream)

        dump_info = save_incident_dump(
            dump_path,
            analysis,
            parse_errors_count=len(parse_errors),
        )
    except StorageSubsystemError as exc:
        print(f"[КРИТИЧНА ПОМИЛКА ДИСКА] {exc}")
        return 1
    except ClusterMonitorError as exc:
        print(f"[ПОМИЛКА ДІАГНОСТИКИ] {exc}")
        return 1
    else:
        print_diagnostic_report(analysis, parse_errors, dump_info)
        return 0
    finally:
        print("Завершення сеансу діагностики кластера.")


if __name__ == "__main__":
    t_start = time.perf_counter()
    base_dir = Path(__file__).resolve().parent
    exit_code = run_pipeline(
        log_path=base_dir / "sample_cluster.log",
        dump_path=base_dir / "incidents_dump.json",
    )
    t_elapsed = (time.perf_counter() - t_start) * 1000
    print(f"Час виконання утиліти: {t_elapsed:.2f} мс")
    raise SystemExit(exit_code)