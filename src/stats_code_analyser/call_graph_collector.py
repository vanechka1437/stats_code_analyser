# src/stats_code_analyser/call_graph_collector.py
"""
Коллектор ориентированного графа вызовов для последующего вычисления RFC-показателей.

Назначение
---------
Этот модуль собирает ориентированный граф вызовов вида
    caller -> set(callee_qual_name)
где `qual_name` — квалифицированное имя определения:
  - function:<name> — функция верхнего уровня
  - class:<Class>.<method> — метод класса
  - 'global' — вызовы, происходящие в модуле на верхнем уровне

RFC (Response For a Class / Function)
-------------------------------------
- RFC измеряет количество возможных откликов (response) класса/функции — обычно
  считается как число методов плюс число внешних (вызваемых) методов/функций.
- Собранный граф вызовов позволяет вычислить RFC (или его вариации) как
  количество уникальных целевых узлов, достижимых из узла-источника (caller).

Ограничения и предпосылки
-------------------------
- Анализ основан на AST и статическом разрешении имён:
  * Явные обращения `self.method()` разрешаются в `class:Class.method`.
  * Вызовы вида `Class.method()` разрешаются, если `Class` объявлен в том же модуле.
  * Вызовы по имени `foo()` разрешаются в соответствующие `function:foo` и/или
    `class:SomeClass.foo`, собранные по простому имени (by_simple).
- Не выполняется сложное разрешение динамических выражений (aliasing, импортные
  синонимы, getattr, вызовы по ссылкам и т.п.). Такие вызовы будут либо
  сопоставляться по простому имени (если возможно), либо проигнорированы.
"""

import ast
from collections import defaultdict


class _CallGraphCollector(ast.NodeVisitor):
    """
    Коллектор графа вызовов (caller -> set(callees)) с квалифицированными именами.

    Класс наследует `NodeVisitor`. Это стандартный механизм обхода AST из модуля
    `ast`: при посещении узла `node` вызывается метод `visit_<NodeClass>` (если он
    определён в классе); в противном случае вызывается `generic_visit`, который
    рекурсивно обходит дочерние узлы.

    Основная идея реализации
    -----------------------
    1. Первый проход (`_DefsCollector`) собирает все определения функций/методов
       и имена классов:
         - `defs`: множество квалифицированных имён (function:... / class:...).
         - `by_simple`: mapping простого имени -> список соответствующих qual имён.
         - `class_names`: множество имён классов для распознавания вызовов вида Class.m().
    2. Второй проход (`_CallCollector`) обходит AST и собирает ребра вызовов:
         - вычисляет текущего `caller` (qualified name или 'global');
         - при встрече ast.Call разрешает callee по простому имени или по атрибутной нотации:
             - self.method() -> class:CurrentClass.method
             - Class.method() (если Class в class_names) -> class:Class.method
             - name() -> все qual'ы из by_simple[name]
    3. Результат — словарь caller -> set(callees). Гарантируется, что все найденные
       определения присутствуют в ключах графа (хотя их значение может быть пустым).

    Ограничения:
    - Не разрешаются вызовы импортированных модулей/динамические вызовы.
    """

    def __init__(self) -> None:
        """
        Инициализация.

        Атрибуты:
        - defs_by_simple: dict[str, list[str]]
            Mapping простого имени (например, "foo") -> список квалифицированных имён,
            например ["function:foo", "class:Bar.foo"].
        - class_names: set[str]
            Набор имён классов, обнаруженных в модуле.
        - defined_quals: set[str]
            Множество всех найденных квалифицированных имён определений.
        - _caller_stack: list[str]
            Стек текущих вызвавших контекстов (не используется в текущей реализации,
            но остаётся для расширений).
        - graph: dict[str, set[str]]
            Сборный граф (результат build).
        """
        self.defs_by_simple: dict[str, list[str]] = {}
        self.class_names: set[str] = set()
        self.defined_quals: set[str] = set()
        self._caller_stack: list[str] = []
        self.graph: dict[str, set[str]] = defaultdict(set)

    def build(self, tree: ast.AST) -> dict[str, set[str]]:
        """
        Построить граф вызовов для AST-дерева модуля.

        :param tree: ast.AST — ожидается ast.Module (но метод работает с AST-деревом)
        :return: dict[str, set[str]] — mapping caller -> set(callee_qual_names)

        Алгоритм:
          1. Первый проход: собрать определения через _DefsCollector.
          2. Второй проход: собрать ребра вызовов через _CallCollector с учётом
             ранее собранных определений и имён классов.
          3. Обеспечить присутствие всех определённых qual-имён в возвращаемом графе.
        """
        # 1) собрать определения
        defs_collector = self._DefsCollector()
        defs_collector.visit(tree)
        self.defs_by_simple = defs_collector.by_simple
        self.class_names = defs_collector.class_names
        self.defined_quals = defs_collector.defs

        # 2) собрать вызовы
        call_collector = self._CallCollector(self.defs_by_simple, self.class_names)
        call_collector.visit(tree)

        # Привести defaultdict -> обычный dict со set-значениями
        self.graph = {k: set(v) for k, v in call_collector.callees_by_caller.items()}

        # 3) гарантировать присутствие всех определённых qual-имён в графе
        for qual in self.defined_quals:
            self.graph.setdefault(qual, set())

        return self.graph

    # ---- Вспомогательный класс: сбор определений ----
    class _DefsCollector(ast.NodeVisitor):
        """
        Собирает определения функций/методов и имена классов.

        Результаты:
        - defs: set[str]          — множество квалифицированных имён определений
        - by_simple: dict[str, list[str]] — mapping простого имени -> список qual имён
        - class_names: set[str]   — имена классов, встреченных в модуле
        """

        def __init__(self) -> None:
            self.current_class: list[str] = []
            self.defs: set[str] = set()
            self.by_simple: dict[str, list[str]] = {}
            self.class_names: set[str] = set()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            """
            Обработать определение класса: запомнить имя и обойти тело.
            """
            self.class_names.add(node.name)
            self.current_class.append(node.name)
            for child in node.body:
                self.visit(child)
            self.current_class.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            """
            Обработать определение функции/метода:
              - сформировать квалифицированное имя;
              - зарегистрировать qual в self.defs и self.by_simple.
            """
            if self.current_class:
                qual = f"class:{self.current_class[-1]}.{node.name}"
            else:
                qual = f"function:{node.name}"

            self.defs.add(qual)
            self.by_simple.setdefault(node.name, []).append(qual)

            for child in node.body:
                self.visit(child)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            """
            Async def обрабатывается как обычная функция.
            """
            # reuse same logic as for FunctionDef
            self.visit_FunctionDef(node)

    # ---- Вспомогательный класс: сбор вызовов ----
    class _CallCollector(ast.NodeVisitor):
        """
        Сборщик ребер вызовов caller -> set(callees).

        Параметры конструктора:
        - defs_by_simple: dict[str, list[str]] — mapping простого имени -> список qual имён
        - class_names: set[str] — имена классов, обнаруженные в модуле

        Результат:
        - callees_by_caller: dict[str, set[str]]
        """

        def __init__(self, defs_by_simple: dict[str, list[str]], class_names: set[str]) -> None:
            self.current_class: list[str] = []
            self.current_function: list[str] = []
            self.defs_by_simple = defs_by_simple
            self.class_names = class_names
            self.callees_by_caller: dict[str, set[str]] = defaultdict(set)

        def _current_caller(self) -> str:
            """
            Сформировать квалифицированное имя текущего caller.

            Возвращаемое значение:
              - "class:Class.method" — если внутри метода класса
              - "function:<name>" — если внутри функции верхнего уровня
              - "global" — если вызов вне функций (на уровне модуля)
            """
            if self.current_function:
                if self.current_class:
                    return f"class:{self.current_class[-1]}.{self.current_function[-1]}"
                return f"function:{self.current_function[-1]}"
            return "global"
