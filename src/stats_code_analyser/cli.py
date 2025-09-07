# src/stats_code_analyser/cli.py
"""
Модуль для командной строки интерфейса (CLI) статического анализатора.
Содержит функцию main().
"""

import argparse
from .static_analyser import StaticCodeAnalyser
import xml.etree.ElementTree as ET

