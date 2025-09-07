# src/stats_code_analyser/attribute_finders.py
"""
Утилиты для статического поиска обращений к `self` в AST.

Модуль содержит два лёгких посетителя AST, которые собирают явные обращения
к атрибутам и вызовам методов на `self`. Работают только на уровне синтаксиса
(не выполняют код).

Ограничения:
- Не распознаёт динамические обращения (например, через `getattr`).
- Не отслеживает переименование/aliasing (`alias = self`).
- Не выполняет типового/семантического анализа.
"""

import ast


class _SelfVisitor(ast.NodeVisitor):
    """Базовый посетитель с утилитой для извлечения dotted-пути из
    цепочки `Attribute` начинающейся от `self`.

    Класс наследует `NodeVisitor`. Это стандартный механизм обхода AST из
    модуля `ast`: при посещении узла `node` вызывается метод `visit_<NodeClass>`
    (если он определён в классе); в противном случае вызывается `generic_visit`,
    которая рекурсивно обходит дочерние узлы.
    """

    @staticmethod
    def _dotted_from_attribute(node: ast.AST) -> str | None:
        """Надёжно извлекает dotted-путь из выражения `Attribute`, если его корень — `self`.

        Рассматриваются только чистые цепочки атрибутов вида `self.x`,
        `self.a.b.c` и т.п. Возвращаемое значение не содержит префикс `self`.

        :param: node : Ожидается ast-узел. В случае, если передан другой тип, возвращается `None`.

        :return: str | None: Dotted-путь (например, `'a.b'` для `self.a.b`) или `None`, если
        выражение не соответствует шаблону `self.<...>`.

        Особенности реализации
        -----------------------
        - Поднимаемся по цепочке `Attribute`, собирая имена `attr` справа налево,
          затем переворачиваем собранный список.
        - Если в основании цепочки не встретился `ast.Name(id='self')`, считаем,
          что выражение не является чистой `self`-цепочкой (например, в
          `self.foo().bar` основанием будет `Call`) и возвращаем `None`.
        """
        if not isinstance(node, ast.Attribute):
            return None
        parts: list[str] = []
        cur: ast.AST | None = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name) and cur.id == "self":
            return ".".join(reversed(parts))
        return None


class _AttributeFinder(_SelfVisitor):
    """Посетитель AST, собирающий явные обращения `self.<attr>`.

    Класс наследует `NodeVisitor`. Это стандартный механизм обхода AST из модуля
    `ast`: при посещении узла `node` вызывается метод `visit_<NodeClass>` (если он
    определён в классе); в противном случае вызывается `generic_visit`, который
    рекурсивно обходит дочерние узлы.
    """

    def __init__(self) -> None:
        """Инициализация.

        `attributes: set[str]` — имена или dotted-пути атрибутов без префикса
        `self` (напр., `'x'` или `'a.b.c'`).
        """
        self.attributes: set[str] = set()

