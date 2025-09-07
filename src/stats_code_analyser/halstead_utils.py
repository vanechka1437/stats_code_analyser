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


def _compute_volume(n_total: int, n_unique: int) -> float:
    """
    Вычислить Volume = N * log2(n). Возвращает 0.0, если n_unique <= 0.
    """
    if n_unique <= 0:
        return 0.0
    return n_total * math.log2(n_unique)


def _compute_difficulty(n1_unique: int, n2_total: int, n2_unique: int) -> float:
    """
    Вычислить Difficulty = (n1 / 2) * (N2 / n2). Обрабатывает деление на ноль.
    """
    if n2_unique == 0:
        return 0.0
    return (n1_unique / 2.0) * (n2_total / n2_unique)


def _compute_halstead_metrics_from_tokens(tokens: list[tuple[str, str]]) -> tuple[float, float, float]:
    """
    Чистая функция: по списку токенов возвращает (volume, difficulty, effort).

    :param tokens: список пар (kind, token_string)
    :return: (volume, difficulty, effort)
    :algorithm:
      - подсчитать уникальные и общие количества (см. Halstead)
      - при нулевой уникальности возвращать (0.0, 0.0, 0.0)
    """
    unique_ops, unique_vals, total_ops, total_vals = _count_tokens(tokens)
    n1 = len(unique_ops)
    n2 = len(unique_vals)

    if n1 == 0 or n2 == 0:
        return 0.0, 0.0, 0.0

    n_unique = n1 + n2
    n_total = total_ops + total_vals

    volume = _compute_volume(n_total, n_unique)
    difficulty = _compute_difficulty(n1, total_vals, n2)
    effort = difficulty * volume
    return volume, difficulty, effort


class _QualifiedHalsteadMetricsVisitor(ast.NodeVisitor):
    """
    Сборщик Halstead-метрик по квалифицированным контекстам.

    Класс наследует `NodeVisitor`. Это стандартный механизм обхода AST из модуля
    `ast`: при посещении узла `node` вызывается метод `visit_<NodeClass>` (если он
    определён в классе); в противном случае вызывается `generic_visit`, который
    рекурсивно обходит дочерние узлы. В этой реализации переопределены обработчики
    для узлов, которые важны при подсчёте когнитивной сложности (функции, классы,
    управляющие конструкции, comprehensions, вызовы и т.д.).

    Контексты:
      - "function:<name>" — обычная функция на уровне модуля
      - "class:<Class>.<method>" — метод класса
      - "lambda:<lineno>" или "class:<Class>.lambda:<lineno>" — лямбда, квалифицированная строкой

    Техническая реализация:
      1. Проход AST для сбора диапазонов (lineno..end_lineno) для целевых контекстов.
         Учитываются декораторы (расширяют start/end).
      2. Генерация токенов из исходного кода и распределение токенов по контекстам
         — токен попадает в наиболее вложенный диапазон, содержащий его lineno.
      3. Для каждого контекста вычисляются Halstead-метрики чистой функцией.
    """

    def __init__(self, code: str) -> None:
        """
        Инициализация посетителя.

        :param code: исходный текст модуля (вся строка)
        :attributes:
          - code: str — хранит исходный код
          - result: dict[str, tuple[float, float, float]] — итоговые метрики по контекстам
            (ключ — имя контекста, значение — (volume, difficulty, effort))
          - _ranges: list[Range] — накопленные диапазоны контекстов
          - _depth: int — текущая глубина обхода (для корректного выбора вложенного контекста)
          - _class_stack: list[str] — стек имён классов при рекурсивном обходе
        """
        self.code = code
        self.result: dict[str, tuple[float, float, float]] = {}
        self._ranges: list[Range] = []
        self._depth = 0
        self._class_stack: list[str] = []

    def _collect_ranges(self, node: ast.AST) -> None:
        """
        Рекурсивно обходит AST и сохраняет диапазоны для функций/лямбд/методов.

        :param node: AST
        :algorithm:
          - при встрече FunctionDef/AsyncFunctionDef формируется Range с учётом декораторов
          - при встрече ClassDef — имя класса кладётся в стек, продолжается обход
          - лямбды тоже фиксируются (qualifier — номер строки)
          - depth увеличивается на 1 при заходе в функциональный/классовый контекст
        """
        # итерация по дочерним узлам — рекурсивно
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = getattr(child, "lineno", 0)
                end = getattr(child, "end_lineno", start)
                # учитывать декораторы
                for dec in getattr(child, "decorator_list", ()):
                    start = min(start, getattr(dec, "lineno", start))
                    end = max(end, getattr(dec, "end_lineno", end))
                if self._class_stack:
                    name = f"class:{self._class_stack[-1]}.{child.name}"
                else:
                    name = f"function:{child.name}"
                self._ranges.append(Range(name, start, end, self._depth))
                # рекурсивный обход в теле функции (увеличиваем глубину)
                self._depth += 1
                self._collect_ranges(child)
                self._depth -= 1

            elif isinstance(child, ast.Lambda):
                start = getattr(child, "lineno", 0)
                end = getattr(child, "end_lineno", start)
                if self._class_stack:
                    name = f"class:{self._class_stack[-1]}.lambda:{start}"
                else:
                    name = f"lambda:{start}"
                self._ranges.append(Range(name, start, end, self._depth))
                self._depth += 1
                self._collect_ranges(child)
                self._depth -= 1

            elif isinstance(child, ast.ClassDef):
                # войти в класс: добавить в стек и обойти тело
                self._class_stack.append(child.name)
                self._depth += 1
                self._collect_ranges(child)
                self._depth -= 1
                self._class_stack.pop()

            else:
                # рекурсивно углубиться в остальные узлы
                self._collect_ranges(child)

    def _tokens_by_context(self) -> dict[str, list[tuple[str, str]]]:
        """
        Генерирует токены из self.code и распределяет их по контекстам.

        :return: dict mapping context_name -> list[(kind, token_string)]
        :algorithm:
          - сортирует диапазоны по (depth desc, start asc, end desc) чтобы найти
            наиболее вложенный контекст первым
          - для каждого токена выясняет lineno и помещает токен в первый
            диапазон, содержащий эту строку; если ни один — кладёт в "global"
        """
        # сортируем диапазоны для выбора наиболее вложенного подходящего
        sorted_ranges = sorted(self._ranges, key=lambda r: (-r.depth, r.start, -r.end))
        tokens_by_ctx: dict[str, list[tuple[str, str]]] = defaultdict(list)
        tokens_by_ctx["global"] = []

        # безопасная генерация токенов (возврат пустой структуры при ошибке)
        try:
            gen = tokenize.generate_tokens(io.StringIO(self.code).readline)
        except Exception:
            return dict(tokens_by_ctx)

        for tok in gen:
            classified = _HalsteadTokenClassifier.classify(tok.type, tok.string)
            if not classified:
                continue
            kind, string = classified
            lineno = tok.start[0]
            assigned = False
            for r in sorted_ranges:
                if r.start <= lineno <= r.end:
                    tokens_by_ctx[r.name].append((kind, string))
                    assigned = True
                    break
            if not assigned:
                tokens_by_ctx["global"].append((kind, string))

        return dict(tokens_by_ctx)

    def visit_Module(self, node: ast.Module) -> None:
        """
        Точка входа: собрать диапазоны, распределить токены и посчитать метрики.

        :param node: ast.Module
        :algorithm:
          - _collect_ranges собирает self._ranges
          - _tokens_by_context распределяет токены из self.code по контекстам
          - для каждого контекста вычисляет Halstead через _compute_halstead_from_tokens
        """
        self._collect_ranges(node)
        tokens_by_ctx = self._tokens_by_context()
        for ctx, tokens in tokens_by_ctx.items():
            volume, difficulty, effort = _compute_halstead_metrics_from_tokens(tokens)
            self.result[ctx] = (volume, difficulty, effort)
