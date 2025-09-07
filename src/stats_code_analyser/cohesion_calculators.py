# src/stats_code_analyser/cohesion_calculators.py
"""
Модуль вычисления cohesion-метрик класса: LCOM4, TCC и LCC.

Описание метрик и алгоритмов
----------------------------
- LCOM4 (на основе Hitz & Montazeri): число связных компонент в неориентированном
  графе, где вершины — методы и поля класса; ребро соединяет метод с полем,
  если метод использует поле, и соединяет метод с другим методом, если
  первый вызывает второй напрямую. LCOM4 равен числу компонент, содержащих
  по крайней мере один метод.

- TCC (Tight Class Cohesion, Bieman & Kang): доля пар методов, связанных
  напрямую через общие используемые поля. TCC = NDC / num_pairs, где
  NDC — число связанных пар (direct connections), num_pairs = n*(n-1)/2.

- LCC (Loose Class Cohesion): доля пар методов, связанных напрямую или
  косвенно через цепочки общих полей (оценка через связные компоненты
  графа методов). LCC = sum_c c*(c-1)/2 / num_pairs, где сумма берётся
  по компонентам методов размера c.

Ограничения и предпосылки
-------------------------
- Статический анализ основан на `_AttributeFinder` и `_MethodCallFinder`.
  Рассматриваются только явные обращения `self.x` и явные вызовы методов
  на `self` (включая dotted-пути типа `self.a.b`).
- Не выполняется разрешение alias/динамических обращений (например,
  `alias = self` или `getattr(self, name)`).

Структура модуля
----------------
- Вспомогательная функция `_connected_components(graph)` — общая
  реализация поиска компонент связности для неориентированного графа.
- Класс `_LCOM4Calculator` — сбор данных (методы, поля, вызовы), построение
  графа (методы + поля) и подсчёт LCOM4.
- Класс `_ClassCohesionCalculator` — построение графа методов (ребро
  при пересечении используемых полей) и вычисление TCC/LCC.
"""

import ast
from collections import deque
from .attribute_finders import _AttributeFinder, _MethodCallFinder


def _connected_components(graph: dict[str, set[str]]) -> list[set[str]]:
    """
    Находит связные компоненты в неориентированном графе.

    :param graph: Mapping node -> set(neighbours). Все вершины ожидаются
                  присутствующими как ключи (если нет — они будут проигнорированы).
    :return: Список множеств, каждая — связная компонента графа.
    """
    visited: set[str] = set()
    components: list[set[str]] = []
    nodes = list(graph.keys())
    for node in nodes:
        if node in visited:
            continue
        comp: set[str] = set()
        q: deque[str] = deque([node])
        while q:
            cur = q.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            comp.add(cur)
            for nb in graph.get(cur, set()):
                if nb not in visited:
                    q.append(nb)
        if comp:
            components.append(comp)
    return components


class _LCOM4Calculator:
    """
    Калькулятор LCOM4.

    Техническая реализация:
    - Сбор: для каждого метода класса собираются используемые атрибуты
      (`self.x`, dotted-пути) и вызовы методов на `self`.
    - Построение графа: вершины — имена методов + атрибуты; рёбра — метод-атрибут
      (если метод использует атрибут) и метод-метод (если метод вызывает другой метод).
    - Подсчёт LCOM4: число компонент графа, содержащих хотя бы один метод.
    """

    @staticmethod
    def _gather_methods_and_attrs(class_node: ast.ClassDef) -> \
            tuple[list[str], set[str], dict[str, set[str]], dict[str, set[str]]]:
        """
        Собрать методы класса и для каждого метода — используемые атрибуты
        и вызовы методов.

        :param class_node: ast.ClassDef
        :return: tuple:
            - methods: list[str] — список имён методов в порядке обхода тела класса
            - attributes: set[str] — набор всех найденных атрибутов (без префикса `self`)
            - method_attributes: dict[method, set(attr)] — mapping метод -> используемые атрибуты
            - method_calls: dict[method, set(dotted_names)] — mapping метод -> вызовы на self
        """
        methods: list[str] = []
        attributes: set[str] = set()
        method_attributes: dict[str, set[str]] = {}
        method_calls: dict[str, set[str]] = {}

        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = item.name
                af = _AttributeFinder()
                af.visit(item)
                mf = _MethodCallFinder()
                mf.visit(item)

                methods.append(name)
                method_attributes[name] = set(af.attributes)
                method_calls[name] = set(mf.called_methods)
                attributes.update(af.attributes)

        return methods, attributes, method_attributes, method_calls