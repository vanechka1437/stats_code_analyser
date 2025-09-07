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

    @staticmethod
    def classify(tok_type: int, tok_string: str) -> tuple[str, str] | None:
        """
        Классифицирует один токен.

        :param tok_type: int — тип токена (из `tokenize`)
        :param tok_string: str — лексемная строка токена
        :return: ("operator" | "operand", token_string) или None
        :algorithm:
          - игнорируем синтаксические служебные токены
          - классифицируем OP/NAME/NUMBER/STRING как оператор/операнд по правилам выше
        """
        # игнорируем служебные токены
        if tok_type in (
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.COMMENT,
                tokenize.ENDMARKER,
        ):
            return None

        if tok_type == tokenize.OP:
            return "operator", tok_string

        if tok_type == tokenize.NAME:
            # keyword.iskeyword считает True/False/None ключевыми, но такие литералы
            # более корректно считать операндами для Halstead
            if keyword.iskeyword(tok_string):
                if tok_string in ("True", "False", "None"):
                    return "operand", tok_string
                return "operator", tok_string
            return "operand", tok_string

        if tok_type in (tokenize.NUMBER, tokenize.STRING):
            return "operand", tok_string

        return None


def _count_tokens(tokens: list[tuple[str, str]]) -> tuple[set[str], set[str], int, int]:
    """
    Посчитать уникальные и общие количества операторов/операндов.

    :param tokens: список пар (kind, token_string)
    :return: (unique_operators, unique_operands, total_operators, total_operands)
    """
    unique_ops: set[str] = set()
    unique_vals: set[str] = set()
    total_ops = total_vals = 0
    for kind, string in tokens:
        if kind == "operator":
            unique_ops.add(string)
            total_ops += 1
        elif kind == "operand":
            unique_vals.add(string)
            total_vals += 1
    return unique_ops, unique_vals, total_ops, total_vals
