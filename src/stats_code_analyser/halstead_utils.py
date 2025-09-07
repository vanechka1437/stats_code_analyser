# src/halstead_utils
"""
Утилиты для вычисления Halstead-метрик по исходному коду Python.

Описание метрик Halstead
-----------------------
Halstead-метрики (Maurice H. Halstead, 1977) — статические метрики сложности кода,
вычисляемые на основе подсчёта операторов и операндов:

- n1  — число уникальных операторов
- n2  — число уникальных операндов
- N1  — общее число операторов
- N2  — общее число операндов

Формулы (классические):
- vocabulary  = n = n1 + n2
- length      = N = N1 + N2
- volume      = N * log2(n)         (при n > 0)
- difficulty  = (n1 / 2) * (N2 / n2) (при n2 > 0)
- effort      = difficulty * volume

Ограничения и предпосылки
-------------------------
- Статический анализ по токенам, не выполняется парсинг семантики (динамические вызовы,
  alias-ы, getattr и т.п. не разрешаются).
- Контексты (scope) определяются по диапазонам строк (lineno .. end_lineno) AST-узлов.
- Константы True/False/None трактуются как операнды (соответствие распространённым
  практикам Halstead-анализа).

Структура модуля
----------------
- _HalsteadTokenClassifier — классификатор токенов (operator / operand).
- _QualifiedHalsteadMetricsVisitor — сбор Halstead-метрик по "квалифицированным"
  контекстам: `function:name`, `class:Class.method`, а также lambda (qualified by line).
- Вспомогательные dataclass'ы и чистые функции для расчёта метрик.
"""

import ast
import io
import keyword
import math
import tokenize
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    """
    Описывает контекст (диапазон строк) в исходном файле.

    :param name: Имя контекста, например "function:foo" или "class:Bar.baz"
    :param start: начальная строка (inclusive)
    :param end: конечная строка (inclusive)
    :param depth: вложенность (целое) — используется для выбора самого глубокого контекста
    """
    name: str
    start: int
    end: int
    depth: int


class _HalsteadTokenClassifier:
    """
    Классификатор токенов для Halstead-анализа.

    Технические детали:
    - Статический метод `classify` принимает значения из модуля `tokenize` и строковое
      представление токена.
    - Возвращает кортеж (kind, token_string), где kind ∈ {"operator", "operand"},
      либо None для игнорируемых токенов (newlines, comments и т.п.).
    - Правила:
      * Игнорируем NL, NEWLINE, INDENT, DEDENT, COMMENT, ENDMARKER
      * OP -> "operator"
      * NAME: ключевые слова (keyword.iskeyword) считаются операторами, за исключением
        литералов `True`, `False`, `None` — их трактуем как операнды.
      * NUMBER, STRING -> "operand"
    """

