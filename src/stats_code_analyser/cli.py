# src/stats_code_analyser/cli.py
"""
Модуль для командной строки интерфейса (CLI) статического анализатора.
Содержит функцию main().
"""

import argparse
from .static_analyser import StaticCodeAnalyser
import xml.etree.ElementTree as ET


def main() -> None:
    """
    Точка входа CLI: парсит аргументы, вычисляет метрики, сохраняет отчёт в XML.

    :return: None
    :algorithm:
      - argparse для filename и output
      - создаёт StaticCodeAnalyser
      - вычисляет все метрики
      - сохраняет в XML формате по указанному пути
    """
    parser = argparse.ArgumentParser(description="Статический анализатор кода Python.")
    parser.add_argument("-f", "--file", type=str, required=True, help="Путь к Python-файлу для анализа")
    parser.add_argument("-o", "--output", type=str, default="report.xml", help="Путь к выходному XML-файлу (по умолчанию: report.xml)")
    args = parser.parse_args()

    try:
        analyser = StaticCodeAnalyser(args.file)
        metrics = {
            "lcom4": analyser.lcom4(),
            "tcc": analyser.tcc(),
            "lcc": analyser.lcc(),
            "max_cognitive_per_class": analyser.max_cognitive_per_class(),
            "avg_cognitive_per_class": analyser.avg_cognitive_per_class(),
            "total_cognitive_per_class": analyser.total_cognitive_per_class(),
            "sloc_per_class": analyser.sloc_per_class(),
            "max_method_sloc_per_class": analyser.max_method_sloc_per_class(),
            "avg_method_sloc_per_class": analyser.avg_method_sloc_per_class(),
            "max_halstead_difficulty_per_class": analyser.max_halstead_difficulty_per_class(),
            "max_halstead_effort_per_class": analyser.max_halstead_effort_per_class(),
            "avg_halstead_difficulty_per_class": analyser.avg_halstead_difficulty_per_class(),
            "avg_halstead_effort_per_class": analyser.avg_halstead_effort_per_class(),
            "number_of_methods_per_class": analyser.number_of_methods_per_class(),
            "min_code_to_comment_ratio_per_class": analyser.min_code_to_comment_ratio_per_class(),
            "avg_code_to_comment_ratio_per_class": analyser.avg_code_to_comment_ratio_per_class(),
            "response_for_class": analyser.response_for_class(),
            "max_nesting_level_per_class": analyser.max_nesting_level_per_class(),
        }

        classes = sorted(set(key for metric in metrics.values() for key in metric.keys()))

        root = ET.Element("report")

        if not classes:
            ET.SubElement(root, "message").text = "В файле нет классов."
        else:
            for cls in classes:
                class_elem = ET.SubElement(root, "class", name=cls)
                for metric_name, metric_dict in metrics.items():
                    value = metric_dict.get(cls, "N/A")
                    ET.SubElement(class_elem, "metric", name=metric_name).text = str(value)

        tree = ET.ElementTree(root)
        tree.write(args.output, encoding='utf-8', xml_declaration=True)

    except ValueError as e:
        root = ET.Element("report")
        ET.SubElement(root, "error").text = f"Ошибка: {e}"
        tree = ET.ElementTree(root)
        tree.write(args.output, encoding='utf-8', xml_declaration=True)
    except Exception as e:
        root = ET.Element("report")
        ET.SubElement(root, "error").text = f"Неизвестная ошибка: {e}"
        tree = ET.ElementTree(root)
        tree.write(args.output, encoding='utf-8', xml_declaration=True)
