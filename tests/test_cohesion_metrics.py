# tests/test_cohesion_metrics
"""
Модуль тестов для `src.cohesion_calculators` и некоторых вспомогательных
функций из `src.attribute_finders`.
"""

import ast
import pytest
from stats_code_analyser.cohesion_calculators import _connected_components, _LCOM4Calculator, _ClassCohesionCalculator
from stats_code_analyser.attribute_finders import _AttributeFinder


def parse_class(code: str) -> ast.ClassDef:
    """
    Парсит строку кода и возвращает первый встретившийся узел `ClassDef`.

    Если класс в коде не найден — будет выброшено ValueError.
    """
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            return node
    raise ValueError("No class definition found in the provided code")


def _expr(expr: str) -> ast.AST:
    """
    Парсит выражение в режиме `eval` и возвращает корневой AST-узел.
    """
    return ast.parse(expr, mode="eval").body


def test_connected_components_empty_graph():
    """
    Пустой граф — ожидаем пустой список компонент.
    """
    assert _connected_components({}) == []


def test_connected_components_single_node():
    """
    Граф с одной вершиной и без рёбер должен вернуть одну компоненту,
    содержащую только эту вершину.
    """
    graph = {"a": set()}
    components = _connected_components(graph)
    assert len(components) == 1
    assert components[0] == {"a"}


def test_connected_components_disconnected_nodes():
    """
    Несвязные вершины — каждая должна образовать свою компоненту.
    """
    graph = {"a": set(), "b": set(), "c": set()}
    components = _connected_components(graph)
    assert len(components) == 3
    assert set(frozenset(comp) for comp in components) == {
        frozenset({"a"}),
        frozenset({"b"}),
        frozenset({"c"}),
    }


def test_connected_components_simple_connected():
    """
    Две вершины, соединённые друг с другом — одна компонента.
    """
    graph = {"a": {"b"}, "b": {"a"}}
    components = _connected_components(graph)
    assert len(components) == 1
    assert components[0] == {"a", "b"}


def test_connected_components_multiple_components():
    """
    Три компоненты различного вида — проверяем корректность разбиения.
    """
    graph = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"}, "e": set()}
    components = _connected_components(graph)
    assert len(components) == 3
    assert set(frozenset(comp) for comp in components) == {
        frozenset({"a", "b"}),
        frozenset({"c", "d"}),
        frozenset({"e"}),
    }


def test_connected_components_with_cycle():
    """
    Треугольник — все вершины попадают в одну компоненту.
    """
    graph = {"a": {"b", "c"}, "b": {"a", "c"}, "c": {"a", "b"}}
    components = _connected_components(graph)
    assert len(components) == 1
    assert components[0] == {"a", "b", "c"}


def test_connected_components_ignores_unlisted_nodes():
    """
    Сосед может быть не указан явно как ключ в словаре графа — код
    при обходе всё равно должен добавлять такую вершину в компоненту.

    Пример: {'а': {'b'}} — при старте только 'a' в keys, но 'b' должен
    попасть в компоненту вместе с 'а'.
    """
    graph = {"a": {"b"}}
    components = _connected_components(graph)
    assert len(components) == 1
    assert components[0] == {"a", "b"}


def test_connected_components_duplicate_in_queue():
    """
    Сценарий, когда в очередь попадают дубликаты вершин — проверяем,
    что алгоритм корректно обходит visited и не создаёт лишних записей.
    """
    graph = {"a": {"b", "c"}, "b": {"a"}, "c": {"a", "b"}}
    components = _connected_components(graph)
    assert len(components) == 1
    assert components[0] == {"a", "b", "c"}


def test_lcom4_no_methods():
    """
    Класс без методов — LCOM4 должен быть 0.
    """
    class_node = parse_class("class C: pass")
    assert _LCOM4Calculator.compute(class_node) == 0


def test_lcom4_one_method():
    """
    Один метод — по определению LCOM4 равен 1 (одна компонент с методом).
    """
    class_node = parse_class("""
class C:
    def m(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_two_disconnected_methods():
    """
    Два метода, не использующие общие поля и не вызывающие друг друга — две
    отдельные компоненты, LCOM4 == 2.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        pass
    def m2(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 2


def test_lcom4_methods_connected_via_attribute():
    """
    Два метода связаны общим полем `x` — ожидается одна компонента.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        print(self.x)
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_methods_connected_via_direct_call():
    """
    Прямой вызов метода другой — считается связью в графе LCOM4.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.m2()
    def m2(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_methods_connected_via_dotted_call():
    """
    Вызов через dotted-путь вида `self.a.m2()` должен соединять m1 с m2,
    если имя метода совпадает с существующим методом класса.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.a.m2()
    def m2(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_dotted_call_not_connecting_if_not_method():
    """
    Если последний идентификатор dotted-пути не совпадает с методом класса,
    то связи не происходит (например `self.a.b()` — 'b' не метод класса).
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.a.b()
    def m2(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 2


def test_lcom4_self_call():
    """
    Метод вызывает сам себя — остаётся одна компонента с этим методом.
    """
    class_node = parse_class("""
class C:
    def m(self):
        self.m()
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_multiple_components_with_fields():
    """
    Сложный случай: две связанные методы через x, один метод использует y
    и один метод полностью изолирован — ожидаем три компоненты.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        print(self.x)
    def m3(self):
        self.y = 2
    def m4(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 3


def test_lcom4_async_methods():
    """
    Асинхронные методы также должны учитываться одинаково с синхронными.
    """
    class_node = parse_class("""
class C:
    async def m1(self):
        self.x = 1
    async def m2(self):
        await self.m1()
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_complex_realistic_class():
    """
    Класс Point — все методы используют x и y, значит одно связное
    множество: LCOM4 == 1.
    """
    class_node = parse_class("""
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def distance(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5
    def move(self, dx, dy):
        self.x += dx
        self.y += dy
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_uncohesive_class():
    """
    Два метода, не использующие поля класса — два компонента.
    """
    class_node = parse_class("""
class Mixed:
    def calculator(self, a, b):
        return a + b
    def greeter(self, name):
        print(f"Hello, {name}")
""")
    assert _LCOM4Calculator.compute(class_node) == 2


def test_lcom4_isolated_field_not_affecting():
    """
    Поле y не упоминается вовсе — не должно влиять на подсчёт.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        pass  # no use of y, but if y not used anywhere, not in attributes
""")
    assert _LCOM4Calculator.compute(class_node) == 2


def test_lcom4_method_using_multiple_attrs():
    """
    Один метод использует x и y — это соединяет все методы, использующие
    x или y, в одну компоненту.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
        self.y = 2
    def m2(self):
        print(self.x)
    def m3(self):
        print(self.y)
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_call_chain():
    """
    Цепочка вызовов m1->m2->m3 объединяет все методы в одну компоненту.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.m2()
    def m2(self):
        self.m3()
    def m3(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_dotted_deep_call():
    """
    Dotted-путь с глубокой цепочкой должен корректно извлечь последний
    идентификатор и соединить методы (a.b.c.m3 -> m3).
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.a.b.c.m3()
    def m3(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 1


def test_lcom4_dotted_from_attribute_various_cases():
    """
    Тесты, покрывающие приватную статическую функцию `_dotted_from_attribute`.

    Сценарии:
    - `self.a.b` -> возвращается 'a.b'
    - Неподходящий узел (например `Name`) -> `None`
    - `self.foo().bar` -> основание цепочки — `Call`, в таком случае
      ожидаем `None` (покрывает конечный `return None` в реализации).
    """
    # корректный dotted-путь
    node = _expr("self.a.b")
    got = _AttributeFinder._dotted_from_attribute(node)
    assert got == "a.b"

    # не-Attribute: передали Name -> None
    node = _expr("self")
    assert _AttributeFinder._dotted_from_attribute(node) is None

    # Attribute, но основание — Call (self.foo().bar) -> None (ветка возвращения None)
    node = _expr("self.foo().bar")
    assert _AttributeFinder._dotted_from_attribute(node) is None


def test_tcc_no_methods():
    """
    Пустой класс — TCC == 0.0.
    """
    class_node = parse_class("class C: pass")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 0.0


def test_tcc_one_method():
    """
    Один метод — пар для оценки нет, возвращаем 0.0.
    """
    class_node = parse_class("""
class C:
    def m(self):
        pass
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 0.0


def test_tcc_two_disconnected():
    """
    Два метода используют разные поля — TCC == 0.0.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        self.y = 2
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 0.0


def test_tcc_two_connected():
    """
    Два метода используют одно и то же поле — TCC == 1.0.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        print(self.x)
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 1.0


def test_tcc_three_all_connected():
    """
    Все три метода используют поле x — каждая пара связана -> TCC == 1.0.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        self.x += 1
    def m3(self):
        print(self.x)
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 1.0


def test_tcc_three_partial():
    """
    Частичная связность: пары (m1-m2) и (m2-m3) связаны, (m1-m3) — нет.
    Ожидаем TCC = 2/3.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        self.x += 1
        self.y = 2
    def m3(self):
        print(self.y)
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == pytest.approx(2 / 3)


def test_tcc_async():
    """
    Асинхронные методы должны учитываться корректно.
    """
    class_node = parse_class("""
class C:
    async def m1(self):
        self.x = 1
    async def m2(self):
        print(self.x)
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 1.0


def test_tcc_realistic_cohesive():
    """
    Пример банковского счёта — все операции затрагивают одно поле balance.
    """
    class_node = parse_class("""
class BankAccount:
    def __init__(self, balance):
        self.balance = balance
    def deposit(self, amount):
        self.balance += amount
    def withdraw(self, amount):
        self.balance -= amount
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 1.0


def test_tcc_uncohesive():
    """
    Примитивно несвязанные методы — TCC == 0.0.
    """
    class_node = parse_class("""
class Mixed:
    def add(self, a, b):
        return a + b
    def greet(self, name):
        print(name)
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 0.0


def test_tcc_multiple_shared_attrs():
    """
    Метод m1 делит атрибуты с m2 и m3 по разным полям — ожидаем 2/3.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
        self.y = 1
    def m2(self):
        self.x += 1
    def m3(self):
        self.y += 1
""")
    assert _ClassCohesionCalculator.compute_tcc(class_node) == pytest.approx(2 / 3)


def test_lcc_no_methods():
    """
    Пустой класс — LCC == 0.0.
    """
    class_node = parse_class("class C: pass")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 0.0


def test_lcc_one_method():
    """
    Один метод — пар для оценки нет, возвращаем 0.0.
    """
    class_node = parse_class("""
class C:
    def m(self):
        pass
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 0.0


def test_lcc_two_disconnected():
    """
    Два метода используют разные поля — LCC == 0.0.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        self.y = 2
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 0.0


def test_lcc_two_connected():
    """
    Два метода используют одно и то же поле — LCC == 1.0.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        print(self.x)
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 1.0


def test_lcc_three_direct_all():
    """
    Все три метода используют одно поле — LCC == 1.0.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        self.x += 1
    def m3(self):
        print(self.x)
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 1.0


def test_lcc_three_indirect():
    """
    Связность через цепочку: m1-m2-m3 образуют одну компоненту -> LCC == 1.0.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        self.x += 1
        self.y = 2
    def m3(self):
        print(self.y)
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 1.0


def test_lcc_multiple_components():
    """
    Две независимые пары методов -> LCC = 2 / 6 = 1/3 для 4 методов.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.x = 1
    def m2(self):
        self.x += 1
    def m3(self):
        self.y = 2
    def m4(self):
        print(self.y)
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == pytest.approx(1 / 3)


def test_lcc_async():
    """
    Асинхронные методы также учитываются при вычислении LCC.
    """
    class_node = parse_class("""
class C:
    async def m1(self):
        self.x = 1
    async def m2(self):
        print(self.x)
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 1.0


def test_lcc_realistic():
    """
    LinkedListNode — все операции опираются на `next` и `value` и образуют
    полностью связный набор методов по `next`.
    """
    class_node = parse_class("""
class LinkedListNode:
    def __init__(self, value):
        self.value = value
        self.next = None
    def set_next(self, node):
        self.next = node
    def get_next(self):
        return self.next
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 1.0


def test_lcc_partial_cohesion():
    """
    Частичный пример: три метода в одной компоненте и один изолирован —
    ожидаем 0.5.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.a = 1
        self.b = 1
    def m2(self):
        self.b = 2
        self.c = 2
    def m3(self):
        self.c = 3
    def m4(self):
        self.d = 4
""")
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 0.5


def test_class_cohesion_count_edges_empty():
    """
    Подсчёт рёбер в пустом графе должен вернуть 0.
    """
    assert _ClassCohesionCalculator._count_edges({}) == 0


def test_class_cohesion_count_edges_no_edges():
    """
    Граф без рёбер (вершины без соседей) — 0 рёбер.
    """
    assert _ClassCohesionCalculator._count_edges({"a": set(), "b": set()}) == 0


def test_class_cohesion_count_edges_with_edges():
    """
    Проверяем подсчёт рёбер в небольшом неориентированном графе
    (a-b, a-c) -> 2 рёбра.
    """
    graph = {"a": {"b", "c"}, "b": {"a"}, "c": {"a"}}
    assert _ClassCohesionCalculator._count_edges(graph) == 2  # (a-b, a-c)


def test_cohesion_vs_lcom_different():
    """
    LCOM4 учитывает вызовы методов, а TCC/LCC — только общие поля.
    Этот тест подтверждает, что LCOM4 и Cohesion могут давать разные
    результаты для одного и того же класса.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        self.m2()
    def m2(self):
        pass
""")
    assert _LCOM4Calculator.compute(class_node) == 1  # connected via call
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 0.0  # no shared attrs
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 0.0


def test_special_methods():
    """
    Специальные методы (__init__, __str__) должны учитываться обычным
    образом — связь через поле x даёт полную связность.
    """
    class_node = parse_class("""
class C:
    def __init__(self):
        self.x = 1
    def __str__(self):
        return str(self.x)
""")
    assert _LCOM4Calculator.compute(class_node) == 1
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 1.0
    assert _ClassCohesionCalculator.compute_lcc(class_node) == 1.0


def test_nested_def():
    """
    Если `self.x` используется во вложенной функции, анализатор должен
    по-прежнему это обнаружить — метод и вложенная функция логически
    принадлежат методу и поэтому поле считается используемым.
    """
    class_node = parse_class("""
class C:
    def m1(self):
        def inner():
            self.x = 1
        inner()
    def m2(self):
        print(self.x)
""")
    assert _LCOM4Calculator.compute(class_node) == 1
    assert _ClassCohesionCalculator.compute_tcc(class_node) == 1.0


