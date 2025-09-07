# tests/test_cognitive_complexity.py
"""
Тесты для src/cognitive_visitor._CognitiveComplexityVisitor

- Используется pytest.
- Каждый тест содержит подробное описание логики подсчёта.
"""

import ast
from stats_code_analyser.src.stats_code_analyser.cognitive_visitor import _CognitiveComplexityVisitor


def compute_result(code: str) -> dict:
    """
    Парсит код, запускает посетителя и получает итоговый словарь сложностей.
    Если после обхода осталась сложность в глобальной области, добавляем её в result.
    """
    tree = ast.parse(code)
    visitor = _CognitiveComplexityVisitor()
    visitor.visit(tree)
    if visitor._complexity > 0:
        visitor.result["global"] = visitor._complexity
    return visitor.result


def test_context_name_global():
    """
    Проверяет имя контекста по умолчанию, когда стек контекстов пуст.
    Ожидаемый результат: "global".
    """
    visitor = _CognitiveComplexityVisitor()
    assert visitor._context_name() == "global"


def test_global_simple_if_with_bool():
    """
    Проверяет глобальный if с булевым выражением.
    - if: +1 (base + nesting=0).
    - Булево: a and b or c → AND (+1 за дополнительный), OR (+1 за дополнительный) → +2.
    Что проверяет: базовый if в глобальной области, _count_bool_ops с несколькими операторами.
    Ожидаемый результат: {"global": 3}.
    """
    code = """
if a and b or c:
    pass
else:
    pass
"""
    assert compute_result(code) == {"global": 3}


def test_function_nested_if_with_comparison():
    """
    Проверяет вложенные if внутри функции со сравнениями в условии.
    - Outer if: +1 (nesting=0).
    - Булево в outer: a > b and c == d → AND (+1), сравнения обходятся рекурсивно.
    - Вход в тело: nesting=1.
    - Inner if: + (1 + 1) = +2.
    - Булево в inner: not (e < f or g) → not (не добавляет), inner OR (+1).
    Что проверяет: вложенность, _count_bool_ops со сравнениями и UnaryOp (not), рекурсия в _count_bool_ops.
    Ожидаемый результат: {"function:f": 5}.
    """
    code = """
def f():
    if a > b and c == d:
        if not (e < f or g):
            pass
"""
    assert compute_result(code) == {"function:f": 5}


def test_class_with_multiple_methods():
    """
    Проверяет класс с несколькими методами, сложность класса равна сумме сложностей методов.
    - Метод m1: if → +1.
    - Метод m2: while с bool (and → +1) → +1 (while) +1 (bool) = +2.
    - Класс: сумма методов = 1 + 2 = 3.
    Что проверяет: агрегацию сложностей методов в класс, несколько методов, _exit_scope для методов и класса, _context_name для вложенных контекстов.
    Ожидаемый результат: {"class:C": 3, "class:C.function:m1": 1, "class:C.function:m2": 2}.
    """
    code = """
class C:
    def m1(self):
        if True:
            pass

    def m2(self):
        while a and b:
            pass
"""
    assert compute_result(code) == {"class:C": 3, "class:C.function:m1": 1, "class:C.function:m2": 2}


def test_class_with_nested_class_and_method():
    """
    Проверяет вложенный класс внутри класса, с методом.
    - Outer класс C: нет методов с сложностью.
    - Inner класс D: метод m → for → +1.
    - Сложность C: 0, D: 1 (от метода).
    Что проверяет: вложенные классы, _context_name для глубоких контекстов, _class_method_complexities только для методов в классе.
    Ожидаемый результат: {"class:C": 0, "class:C.class:D": 1, "class:C.class:D.function:m": 1}.
    """
    code = """
class C:
    class D:
        def m(self):
            for i in range(10):
                pass
"""
    assert compute_result(code) == {"class:C": 0, "class:C.class:D": 1, "class:C.class:D.function:m": 1}


def test_bool_ops_with_nested_structures():
    """
    Проверяет сложные булевы с вложенными структурами в _count_bool_ops.
    - if: +1.
    - Булево: (a and b) or not (c if d else e) → OR (+1), AND (+1), not (не добавляет), inner IfExp (обходится как child).
    Что проверяет: обход else в _count_bool_ops (iter_child_nodes для IfExp), рекурсия через child nodes.
    Ожидаемый результат: {"function:f": 3}.
    """
    code = """
def f():
    if (a and b) or not (c if d else e):
        pass
"""
    assert compute_result(code) == {"function:f": 3}


def test_ternary_nested_with_bool():
    """
    Проверяет вложенные тернарные с булевыми.
    - Outer IfExp: +1 (nesting=0).
    - Вход в ветви: nesting=1.
    - Inner IfExp: + (1 +1) = +2.
    - Булево в inner test: and → +1.
    Что проверяет: вложенность в IfExp, _count_bool_ops в test.
    Ожидаемый результат: {"function:f": 4}.
    """
    code = """
def f():
    x = a if b else (c if d and e else f)
"""
    assert compute_result(code) == {"function:f": 4}


def test_for_loop_with_else_and_nested_if():
    """
    Проверяет for с else и вложенным if.
    - for: +1.
    - Вход в тело: nesting=1.
    - if: + (1 +1) = +2.
    - else_body: обходится без дополнительного nesting.
    Что проверяет: _visit_block с else_body, вложенность.
    Ожидаемый результат: {"function:f": 3}.
    """
    code = """
def f():
    for i in range(10):
        if cond:
            pass
    else:
        pass
"""
    assert compute_result(code) == {"function:f": 3}


def test_while_with_complex_bool_and_compare():
    """
    Проверяет while с сложным булевым включая сравнения.
    - while: +1.
    - Булево: not (a > b and c < d or e == f) → not (не добавляет), inner AND (+1), OR (+1).
    Что проверяет: покрытие Compare в _count_bool_ops.
    Ожидаемый результат: {"function:f": 3}.
    """
    code = """
def f():
    while not (a > b and c < d or e == f):
        pass
"""
    assert compute_result(code) == {"function:f": 3}


def test_try_except_multiple_with_nested():
    """
    Проверяет try с несколькими except, else, finally и вложенностью.
    - try: +1.
    - Вход в тело: nesting=1.
    - if в теле: + (1 +1) = +2.
    - except1: +1 (nesting=0 после тела).
    - except2: +1.
    - else и finally: обходятся без +base.
    Что проверяет: несколько handlers, orelse, finalbody.
    Ожидаемый результат: {"function:f": 5}.
    """
    code = """
def f():
    try:
        if cond:
            pass
    except Exception:
        pass
    except ValueError:
        pass
    else:
        pass
    finally:
        pass
"""
    assert compute_result(code) == {"function:f": 5}


def test_multi_with_nested():
    """
    Проверяет несколько with, с вложенностью.
    - Первый item: +1 (nesting=0), nesting +=1 →1.
    - Второй item: + (1 +1) = +2, nesting +=1 →2.
    - В теле: if → + (1 +2) = +3.
    - Выход: nesting -=2.
    Что проверяет: множественные items в with, аккумуляция nesting.
    Ожидаемый результат: {"function:f": 6}.
    """
    code = """
def f():
    with A() as a, B() as b:
        if cond:
            pass
"""
    assert compute_result(code) == {"function:f": 6}


def test_list_comprehension_complex():
    """
    Проверяет сложный list comprehension с несколькими generators, ifs и bool.
    - base: +1.
    - nesting +=1 → 1.
    - Первый gen for: + (1 +1) = +2.
    - nesting +=1 → 2 (для if).
    - if: + (1 +2) = +3, bool and or → +2.
    - nesting -=1 → 1.
    - Второй gen for: + (1 +1) = +2.
    - nesting +=1 → 2.
    - if: + (1 +2) = +3.
    - nesting -=1 → 1.
    - elt: обход.
    Итого: 13.
    Что проверяет: множественные generators, ifs с bool, _visit_comprehension.
    Ожидаемый результат: {"function:f": 13}.
    """
    code = """
def f():
    [x + y for x in lst1 if a and b or c for y in lst2 if d]
"""
    assert compute_result(code) == {"function:f": 13}


def test_set_dict_gen_comprehensions_complex():
    """
    Проверяет set, dict, gen с if и bool.
    - Для каждого: base +1, for +2, if +3, bool +1 → 7.
    Что проверяет: разные типы comprehensions, key/value в dict.
    Ожидаемый результат: 7 для каждого.
    """
    code_set = """
def f():
    {x for x in lst if a and b}
"""
    code_dict = """
def f():
    {k: v for k, v in d.items() if a and b}
"""
    code_gen = """
def f():
    (x for x in lst if a and b)
"""
    assert compute_result(code_set) == {"function:f": 7}
    assert compute_result(code_dict) == {"function:f": 7}
    assert compute_result(code_gen) == {"function:f": 7}


def test_decorator_with_ternary_and_class_decorator():
    """
    Проверяет декоратор с тернарным, и декоратор класса.
    - Для функции: IfExp в декораторе → +1 в global (перед enter_scope).
    - Для класса: IfExp в декораторе → +1 в global.
    Что проверяет: обход decorator_list перед enter_scope, покрытие visit_ClassDef decorators.
    Ожидаемый результат: для func: {"global": 1, "function:f": 0}; для class: {"global": 1, "class:C": 0}.
    """
    code_func = """
@(dec if cond else other)
def f():
    pass
"""
    code_class = """
@(dec if cond else other)
class C:
    pass
"""
    assert compute_result(code_func) == {"global": 1, "function:f": 0}
    assert compute_result(code_class) == {"global": 1, "class:C": 0}


def test_function_with_annotations_and_returns():
    """
    Проверяет функцию с аннотациями аргументов и returns.
    - Аннотация arg: IfExp → +1 (внутри функции).
    - Returns: IfExp → +1.
    Что проверяет: покрытие обхода args.annotation и returns в _visit_function_like.
    Ожидаемый результат: {"function:f": 2}.
    """
    code = """
def f(a: int if cond1 else str) -> float if cond2 else int:
    pass
"""
    assert compute_result(code) == {"function:f": 2}


def test_class_with_bases_ternary():
    """
    Проверяет класс с базовыми классами через ternary.
    - Bases: IfExp → +1 (внутри класса).
    Что проверяет: покрытие обхода bases в visit_ClassDef.
    Ожидаемый результат: {"class:C": 1}.
    """
    code = """
class C(A if cond else B):
    pass
"""
    assert compute_result(code) == {"class:C": 1}


def test_recursion_factorial():
    """
    Проверяет рекурсию в вычислении факториала.
    - if: +1.
    - Рекурсивный вызов factorial в else: +1.
    Что проверяет: рекурсивный вызов в Call (name match).
    Ожидаемый результат: {"function:factorial": 2}.
    """
    code = """
def factorial(n):
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)
"""
    assert compute_result(code) == {"function:factorial": 2}


def test_recursion_in_class_method_factorial():
    """
    Проверяет рекурсию в методе класса (factorial-like).
    - if: +1.
    - Рекурсивный self.m: +1.
    - Класс: сумма = 2.
    Что проверяет: rec в Attribute (attr match), агрегация в класс.
    Ожидаемый результат: {"class:C": 2, "class:C.function:m": 2}.
    """
    code = """
class C:
    def m(self, n):
        if n <= 1:
            return 1
        else:
            return n * self.m(n - 1)
"""
    assert compute_result(code) == {"class:C": 2, "class:C.function:m": 2}


def test_no_recursion_in_decorator():
    """
    Проверяет отсутствие рекурсии в декораторе (вызов func не rec).
    Что проверяет: не засчитывается rec если имя не в _rec_funcs.
    Ожидаемый результат: {"function:dec": 0, "function:f": 0}.
    """
    code = """
def dec(func):
    func()

@dec
def f():
    pass
"""
    assert compute_result(code) == {"function:dec": 0, "function:f": 0}


def test_complex_bool_in_comprehension_with_compare():
    """
    Проверяет comprehension с bool включая compare.
    - base: +1.
    - for: +2 (nesting=1).
    - if: +3 (nesting=2).
    - bool: not (a > b and c) → AND +1.
    Что проверяет: _count_bool_ops в if_clause со сравнениями.
    Ожидаемый результат: {"function:f": 7}.
    """
    code = """
def f():
    [x for x in lst if not (a > b and c)]
"""
    assert compute_result(code) == {"function:f": 7}


def test_ternary_in_comprehension_elt():
    """
    Проверяет ternary в elt comprehension.
    - base: +1.
    - for: +2.
    - elt IfExp: + (1 +1) = +2.
    Что проверяет: обход elt в _visit_comprehension.
    Ожидаемый результат: {"function:f": 5}.
    """
    code = """
def f():
    [x if cond else y for x in lst]
"""
    assert compute_result(code) == {"function:f": 5}


def test_recursive_call_in_ternary():
    """
    Проверяет rec вызов в ternary.
    - IfExp: +1.
    - В ветви (nesting=1): rec f() → +1.
    Что проверяет: rec в ветви IfExp.
    Ожидаемый результат: {"function:f": 2}.
    """
    code = """
def f():
    x = f() if cond else 0
"""
    assert compute_result(code) == {"function:f": 2}


def test_combination_deep_nested():
    """
    Проверяет глубокую комбинацию конструкций.
    - if: +1, bool or → +1 →2.
    - nesting=1.
    - for: +2.
    - nesting=2.
    - try: +3.
    - nesting=3.
    - with (2 items): первый +4, второй +5.
    - nesting=5.
    - if: +6, bool and → +1.
    - except: +3 (nesting=2 после тела).
    Итого: 26.
    Что проверяет: глубокая вложенность, комбинация, точность подсчёта.
    Ожидаемый результат: {"function:f": 26}.
    """
    code = """
def f():
    if a or b:
        for i in range(10):
            try:
                with open('file') as fh, context() as ctx:
                    if c and d:
                        pass
            except Exception:
                pass
"""
    assert compute_result(code) == {"function:f": 26}


def test_match_with_guards_and_bool():
    """
    Проверяет match с guards и bool.
    - match: +1.
    - Первый guard: and → +1.
    - Второй guard: or not → +1 (or +1, not не добавляет).
    - Тела: nesting +=1 для каждого, без base для case.
    - В втором теле: if → + (1 +1) = +2.
    Что проверяет: guards, _count_bool_ops в guard, nesting в guard и body.
    Ожидаемый результат: {"function:f": 5}.
    """
    code = """
def f():
    match x:
        case 1 if a and b:
            pass
        case 2 if c or not d:
            if e:
                pass
"""
    assert compute_result(code) == {"function:f": 5}


def test_async_function_with_nested():
    """
    Проверяет async функцию с вложенностью.
    - Async def: обрабатывается как function.
    - if: +1.
    - nesting=1.
    - while: +2.
    Что проверяет: visit_AsyncFunctionDef, _visit_function_like.
    Ожидаемый результат: {"function:f": 3}.
    """
    code = """
async def f():
    if True:
        while cond:
            pass
"""
    assert compute_result(code) == {"function:f": 3}
