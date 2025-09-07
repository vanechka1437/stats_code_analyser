# src/stats_code_analyser/cognitive_visitor.py
"""
Модуль для обхода AST и вычисления когнитивной сложности (Cognitive Complexity) кода.

Алгоритм основан на правилах SonarQube и учитывает дополнительные случаи:
- тернарные выражения
- генераторы и comprehension
- декораторы
- рекурсивные вызовы функций.

Основные принципы подсчёта:

1) Базовые управляющие конструкции
   Каждая управляющая конструкция считается как отдельная точка усложнения:
   - `if`, `for`, `while`, `try`, `with`, `except`, `match` и т.п.
   Вклад каждой такой конструкции увеличивается с учётом текущей глубины вложенности.

2) Вложенность (nesting)
   Под вложенностью понимается число открытых в данный момент управляющих конструкций.
   При входе в тело управляющей конструкции уровень вложенности увеличивается на единицу,
   и каждая последующая конструкция учитывает эту глубину (чем глубже — тем больше вклад).

3) Булевы выражения (`and` / `or` / `not`)
   Логическое выражение типа `a and b and c` трактуется как одна управляющая точка
   плюс `N - 1` дополнительных точек за каждое дополнительное логическое соединение,
   где `N` — число операндов. `not` не даёт дополнительной точки сам по себе,
   но его операнд обходится рекурсивно. Сравнения обходятся рекурсивно и учитываются
   при наличии вложенных булевых выражений.

4) Условные выражения, comprehensions и генераторы
   - Тернарное выражение `x if cond else y` считается отдельной точкой усложнения,
     при этом `cond` и ветви обрабатываются рекурсивно.
   - Comprehensions и generator expressions оценивается эквивалентно ручной записи с `for` и `if`.

5) Рекурсивные вызовы
   Вызов функции, имя которой совпадает с именем текущей анализируемой функции,
   учитывается как дополнительная точка усложнения.
"""

import ast


class _CognitiveComplexityVisitor(ast.NodeVisitor):
    """
    Посетитель AST для вычисления когнитивной сложности.

    Класс наследует `NodeVisitor`. Это стандартный механизм обхода AST из модуля
    `ast`: при посещении узла `node` вызывается метод `visit_<NodeClass>` (если он
    определён в классе); в противном случае вызывается `generic_visit`, который
    рекурсивно обходит дочерние узлы. В этой реализации переопределены обработчики
    для узлов, которые важны при подсчёте когнитивной сложности (функции, классы,
    управляющие конструкции, comprehensions, вызовы и т.д.).

    По завершении обхода доступен словарь вида:
       {"global": <сложность вне функций/классов>,
        "class:MyClass": <сложность класса>,
        "class:MyClass.function:method": <сложность метода>,
        "function:foo": <сложность функции>}
    """

    def __init__(self) -> None:
        """
        Инициализация посетителя.

        Атрибуты:
        - result: dict[str, int]
            Финальный словарь с парами {контекст: когнитивная_сложность}.
        - _context: list[tuple[str, str]]
            Стек контекстов в виде списка (kind, name), где kind — "function" или "class".
        - _nesting: int
            Текущий уровень вложенности управляющих конструкций.
        - _complexity: int
            Текущий накопитель сложности для активной области.
        - _rec_funcs: set[str]
            Множество имён функций, которые находятся в стеке вызова (нужно для обнаружения рекурсивных вызовов).
        - _class_method_complexities: dict[str, int]
            Временное хранилище суммарной сложности методов для каждого класс-контекста.
        """
        self.result: dict[str, int] = {}
        self._context: list[tuple[str, str]] = []
        self._nesting: int = 0
        self._complexity: int = 0
        self._rec_funcs: set[str] = set()
        self._class_method_complexities: dict[str, int] = {}

    # ================= Вспомогательные методы =================

    def _context_name(self) -> str:
        """Возвращает строковое имя текущего контекста (например, "global" или "class:Cls.function:fn")."""
        if not self._context:
            return "global"
        return ".".join(f"{kind}:{name}" for kind, name in self._context)

    def _enter_scope(self, kind: str, name: str) -> tuple[int, int]:
        """
        Вход в новую область (функция или класс).

        Возвращает сохранённые значения (complexity, nesting) для восстановления при выходе.
        """
        saved = (self._complexity, self._nesting)
        self._complexity = 0
        self._nesting = 0
        self._context.append((kind, name))
        return saved

    def _exit_scope(self, saved: tuple[int, int]) -> None:
        """
        Выход из области: агрегирует и сохраняет результат для текущего контекста,
        аккумулирует вклад метода в класс (если это метод), затем восстанавливает
        ранее сохранённое состояние.
        """
        ctx = self._context_name()
        if self._context and self._context[-1][0] == "class":
            self._complexity += self._class_method_complexities.get(ctx, 0)
        self.result[ctx] = self._complexity

        if (self._context and self._context[-1][0] == "function" and
                len(self._context) > 1 and self._context[-2][0] == "class"):
            class_ctx = ".".join(f"{k}:{n}" for k, n in self._context[:-1])
            self._class_method_complexities[class_ctx] = (
                    self._class_method_complexities.get(class_ctx, 0) + self._complexity
            )

        self._context.pop()
        self._complexity, self._nesting = saved

    def _add(self, base: int = 1) -> None:
        """
        Увеличивает текущую сложность на `base + _nesting`.
        Это отражает правило: вклад управляющей конструкции увеличивается с учётом глубины вложенности.
        """
        self._complexity += base + self._nesting

    def _count_bool_ops(self, node: ast.AST) -> None:
        """
        Рекурсивно подсчитывает вклад булевых операций (`and` / `or`) и `not`.

        Для `BoolOp` с N значениями добавляется `max(0, N - 1)` (каждая дополнительная логическая
        операция увеличивает сложность). `not` обходит свой операнд без отдельного инкремента.
        """
        if isinstance(node, ast.BoolOp):
            extra = max(0, len(node.values) - 1)
            self._complexity += extra
            for v in node.values:
                self._count_bool_ops(v)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            self._count_bool_ops(node.operand)
        elif isinstance(node, ast.Compare):
            self._count_bool_ops(node.left)
            for c in node.comparators:
                self._count_bool_ops(c)
        else:
            for ch in ast.iter_child_nodes(node):
                self._count_bool_ops(ch)

    def _visit_block(self, body: list[ast.stmt], else_body: list[ast.stmt] | None = None) -> None:
        """
        Унифицированный обход блока кода: увеличивает nesting, обходит тело, уменьшает nesting.
        `else_body` обрабатывается отдельно после уменьшения nesting.
        """
        self._nesting += 1
        for stmt in body:
            self.visit(stmt)
        self._nesting -= 1
        if else_body:
            for stmt in else_body:
                self.visit(stmt)

    def _visit_comprehension(self, generators: list[ast.comprehension], elt: ast.AST,
                             key: ast.AST | None = None, value: ast.AST | None = None) -> None:
        """
        Обработка comprehension'ов и generator expressions.

        Поведение:
         - учитывает одну точку за саму конструкцию
         - входит в отдельную область (увеличивая nesting) для обхода генераторов и фильтров
         - обходит элемент/ключ/значение comprehension'а.
        """
        # базовая точка за сам comprehension (как за конструкцию)
        self._add(1)
        # При обходе генераторов каждый генератор и каждый if внутри него будут
        # учитываться через visit_comprehension (см. visit_comprehension)
        self._nesting += 1
        for gen in generators:
            self.visit(gen)  # вызовет visit_comprehension
        if elt is not None:
            self.visit(elt)
        if key is not None:
            self.visit(key)
        if value is not None:
            self.visit(value)
        self._nesting -= 1

    def _visit_function_like(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """
        Общая логика обработки определения функции (обычной и async).

        Порядок:
         - пометка имени в стеке для обнаружения рекурсии
         - обход декораторов и аннотаций
         - вход в область функции и обход тела
         - снятие пометки и сохранение результата.
        """
        self._rec_funcs.add(node.name)
        for dec in node.decorator_list:
            self.visit(dec)
        saved = self._enter_scope("function", node.name)
        for arg in node.args.args:
            if arg.annotation:
                self.visit(arg.annotation)
        if node.returns:
            self.visit(node.returns)
        for stmt in node.body:
            self.visit(stmt)
        self._rec_funcs.remove(node.name)
        self._exit_scope(saved)

    # ================= Обработчики AST (публичные visit_*) =================

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Обработчик определения функции (def)."""
        self._visit_function_like(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Обработчик асинхронной функции (async def)."""
        self._visit_function_like(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Обработчик объявления класса (class)."""
        for dec in node.decorator_list:
            self.visit(dec)
        saved = self._enter_scope("class", node.name)
        for base in node.bases:
            self.visit(base)
        for stmt in node.body:
            self.visit(stmt)
        self._exit_scope(saved)

    def visit_If(self, node: ast.If) -> None:
        """
        Обработчик `if` (включая `elif`/`else`).

        Поведение:
         - фиксируется точка усложнения за сам `if`
         - учитываются булевы операции в условии
         - обрабатываются тела и `else`/`elif`.
        """
        self._add(1)
        self._count_bool_ops(node.test)
        self._visit_block(node.body, node.orelse)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        """
        Обработчик тернарного выражения `x if cond else y`.

        Тернарный `if` считается отдельной точкой усложнения;
        условие и ветви обходятся рекурсивно с учётом вложенности.
        """
        self._add(1)
        self._count_bool_ops(node.test)
        # учитывать вложенность ветвей тернарного оператора
        self._nesting += 1
        self.visit(node.body)
        self.visit(node.orelse)
        self._nesting -= 1

    def visit_For(self, node: ast.For) -> None:
        """Обработчик `for`-цикла."""
        self._add(1)
        self._visit_block(node.body, node.orelse)

    def visit_While(self, node: ast.While) -> None:
        """Обработчик `while`-цикла."""
        self._add(1)
        self._count_bool_ops(node.test)
        self._visit_block(node.body, node.orelse)

    def visit_Try(self, node: ast.Try) -> None:
        """
        Обработчик `try`-блока: сам `try` считается точкой, каждый `except` — отдельной точкой;
        `else` и `finally` обходятся для полноты анализа.
        """
        self._add(1)
        self._visit_block(node.body)
        for h in node.handlers:
            self._add(1)
            self._visit_block(h.body)
        for s in node.orelse:
            self.visit(s)
        for s in node.finalbody:
            self.visit(s)

    def visit_Call(self, node: ast.Call) -> None:
        """
        Обработчик вызовов. Если имя вызываемой функции совпадает с именем функции
        в текущем стеке (`_rec_funcs`), это рекурсивный вызов и учитывается дополнительно.
        """
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name and name in self._rec_funcs:
            self._complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        """Обработчик контекстного менеджера `with`."""
        # Каждый элемент в with считается как отдельный вложенный with
        # Поэтому для каждого элемента добавляем точку и увеличиваем nesting для тела.
        for item in node.items:
            self._add(1)
            # при входе в тело этого with увеличиваем nesting
            self._nesting += 1
            self.visit(item.context_expr)
            if item.optional_vars:
                self.visit(item.optional_vars)
        # после обработки всех items мы находимся внутри последнего with на глубине увеличенной на len(items)
        for s in node.body:
            self.visit(s)
        # Выйдем из всех вложенных with'ов
        for _ in node.items:
            self._nesting -= 1
