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
