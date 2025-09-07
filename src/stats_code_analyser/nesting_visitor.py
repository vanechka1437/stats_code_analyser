# src/stats_code_analyser/nesting_visitor.py
"""

Утилиты для статического определения максимального уровня вложенности управляющих
конструкций внутри блока кода (функции/метода/класса).

Назначение
---------
предоставляет инструмент для измерения глубины вложенности управляющих конструкций
(if, for, while, with, try, match и comprehension/генераторов) внутри конкретного
блока кода. Результат полезен для метрик сложности, рефакторинга и предупреждений
о высокой вложенности.

Что измеряется
--------------
- Вложенность инкрементируется при входе в управляющий блок: if, for, async for,
  while, with, async with, try, match.
- Начало comprehension / generator expression считается дополнительным уровнем.
- Выражения в условиях/итераторах/context-expr учитываются в обходе.
- Тела вложенных определений (вложенные функции и классы) рассматриваются как
  часть внешнего блока и включаются в подсчёт.

Ограничения
-----------
- Анализ синтаксический (AST), без выполнения кода: динамические особенности
  (getattr, метапрограммирование и т. п.) не учитываются.
- Поддержка синтаксических конструкций современных версий Python (включая match/case).
"""

import ast


class _NestingLevelVisitor(ast.NodeVisitor):
    """
    Посетитель AST для подсчёта максимального уровня вложенности управляющих
    конструкций внутри блока кода.

    Класс наследует `NodeVisitor`. Это стандартный механизм обхода AST из модуля
    `ast`: при посещении узла `node` вызывается метод `visit_<NodeClass>` (если он
    определён в классе); в противном случае вызывается `generic_visit`, который
    рекурсивно обходит дочерние узлы.

    Техническая реализация
    ----------------------
    - Переопределены visit_* для конструкций, увеличивающих вложенность.
    - Для управления счётчиком уровня используется объектный контекстный
      менеджер `_BlockCtx`, возвращаемый методом `_block()`. Такой подход
      стабилен для статических анализаторов и прост в тестировании.
    - Публичное API:
        - measure_function(func_node) -> int
        - measure_module_functions(module_node) -> dict[str, int]
    """

    class _BlockCtx:
        """
        Внутренний объектный контекстный менеджер для изменения счётчика уровня.

        Поведение:
          - В __enter__ увеличивает родительский _current и обновляет max_level.
          - В __exit__ уменьшает _current и защищает от отрицательных значений.
        """
        __slots__ = ("_parent",)

        def __init__(self, parent: "NestingLevelVisitor") -> None:
            self._parent = parent

        def __enter__(self) -> None:
            p = self._parent
            p._current += 1
            if p._current > p.max_level:
                p.max_level = p._current

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            p = self._parent
            p._current -= 1
            if p._current < 0:
                p._current = 0
            # не подавляем исключения
            return None

    def __init__(self) -> None:
        """
        Инициализация.

        Атрибуты
        -------
        _current : int
            Текущий уровень вложенности в процессе обхода (0, если нет блоков)
        max_level : int
            Максимальная достигнутая глубина в текущем измерении.
        _qualifier_stack : list[str]
            Стек имён для построения квалифицированных имён функций при обходе
            модуля (используется в measure_module_functions).
        """
        self._current: int = 0
        self.max_level: int = 0
        self._qualifier_stack: list[str] = []

    # Возвращает объектный контекстный менеджер
    def _block(self) -> _BlockCtx:
        """
        Создать контекстный менеджер для входа в управляющий блок.

        := with self._block():
               ...
        """
        return _NestingLevelVisitor._BlockCtx(self)

    # Вспомогательный обход списка узлов
    def traverse(self, nodes: list[ast.AST]) -> None:
        """
        Обойти последовательность AST-узлов, вызывая visit для каждого.

        :param nodes: Список AST-узлов.
        """
        for node in nodes:
            self.visit(node)

    # Публичный API
    def measure_function(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """
        Вычислить максимальный уровень вложенности внутри заданной функции.

        :param func_node: FunctionDef | AsyncFunctionDef
            Узел AST, представляющий функцию или async-функцию
        :return: int
            Максимальная глубина вложенности; 0 означает отсутствие управляющих блоков.
        """
        if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise TypeError("measure_function ожидает ast.FunctionDef или ast.AsyncFunctionDef")

        self._current = 0
        self.max_level = 0

        self.traverse(func_node.body)
        return int(self.max_level)

    def measure_module_functions(self, module_node: ast.Module) -> dict[str, int]:
        """
        Собрать максимальные уровни вложенности для всех функций/async-функций в модуле.

        :param module_node: Module
            Спаршенный AST-модуль
        :return: dict[str, int]
            Сопоставление квалифицированного имени функции -> её максимальная глубина.
            Квалификация: "ClassName.method" для методов и "function_name" для
            функций верхнего уровня.
        """
        results: dict[str, int] = {}

        def _walk(node: ast.AST) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    self._qualifier_stack.append(child.name)
                    _walk(child)
                    self._qualifier_stack.pop()
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if self._qualifier_stack:
                        qname = f"{self._qualifier_stack[-1]}.{child.name}"
                    else:
                        qname = child.name
                    results[qname] = self.measure_function(child)
                    _walk(child)
                else:
                    _walk(child)

        _walk(module_node)
        return results

    # visit_* для управляющих конструкций (увеличивают вложенность)
    def visit_If(self, node: ast.If) -> None:
        """
        if test: body else: orelse

        - посетить условие;
        - тело body считается вложенным блоком;
        - orelse обходится без инкремента вложенности.
        """
        self.visit(node.test)
        with self._block():
            self.traverse(node.body)
        self.traverse(node.orelse)

    def visit_For(self, node: ast.For) -> None:
        """
        for target in iter: body else: orelse
        """
        self.visit(node.target)
        self.visit(node.iter)
        with self._block():
            self.traverse(node.body)
        self.traverse(node.orelse)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        """
        Async for — эквивалентно for.
        """
        self.visit_For(node)

    def visit_While(self, node: ast.While) -> None:
        """
        while test: body else: orelse
        """
        self.visit(node.test)
        with self._block():
            self.traverse(node.body)
        self.traverse(node.orelse)

    def visit_With(self, node: ast.With) -> None:
        """
        with context_expr [as optional_vars]: body
        """
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self.visit(item.optional_vars)
        with self._block():
            self.traverse(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        """
        async with — аналогично with.
        """
        self.visit_With(node)

    def visit_Try(self, node: ast.Try) -> None:
        """
        try / except / else / finally:
        основной try — блок; каждый except — отдельный блок;
        orelse и finalbody обходятся без инкремента.
        """
        with self._block():
            self.traverse(node.body)

        for handler in node.handlers:
            if handler.type:
                self.visit(handler.type)
            with self._block():
                self.traverse(handler.body)

        self.traverse(node.orelse)
        self.traverse(node.finalbody)

    def visit_Match(self, node: ast.Match) -> None:
        """
        match subject: case pattern [if guard]: body
        Каждый case рассматривается как отдельный вложенный блок.
        """
        self.visit(node.subject)
        for case in node.cases:
            with self._block():
                self.visit(case.pattern)
                if case.guard:
                    self.visit(case.guard)
                self.traverse(case.body)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        with self._block():
            self.traverse(node.generators)
            self.visit(node.elt)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        with self._block():
            self.traverse(node.generators)
            self.visit(node.elt)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        with self._block():
            self.traverse(node.generators)
            self.visit(node.key)
            self.visit(node.value)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        with self._block():
            self.traverse(node.generators)
            self.visit(node.elt)