# src/stats_code_analyser/static_analyser.py
"""
Статический анализатор Python-кода — фасад для вычисления набора метрик качества и сложности.
Каждая метрика возвращается в виде отображения (mapping) для классов (и там, где уместно,
для методов/контекстов). Описание вычисляемых метрик:

Метрики связности класса
------------------------
- LCOM4 (Lack of Cohesion in Methods, Hitz & Montazeri):
    Число связных компонент в неориентированном графе (методы + поля).
    Вершины: методы и поля; ребро метод-поле — если метод использует поле;
    ребро метод-метод — если метод явно вызывает другой метод.
    LCOM4 = число компонент, содержащих хотя бы один метод.

- TCC (Tight Class Cohesion, Bieman & Kang):
    Доля пар методов, связанных непосредственно через общие используемые поля.
    TCC = NDC / num_pairs, где NDC — число связанных пар, num_pairs = n*(n-1)/2.

- LCC (Loose Class Cohesion):
    Доля пар методов, связанных непосредственно или косвенно (через цепочки общих полей).
    LCC вычисляется через суммарное число пар в компонентах графа методов.

Метрики сложности и читабельности
---------------------------------
- Cognitive Complexity:
    Статическая оценка сложности метода/функции по правилам visitor-а (учитываются
    вложенные управляющие конструкции, ветвления, циклы и т. п.). Возвращается по контекстам.

- Halstead-метрики (Volume, Difficulty, Effort):
    - n1 = число уникальных операторов
    - n2 = число уникальных операндов
    - N1 = общее число операторов
    - N2 = общее число операндов
    Формулы:
      vocabulary = n = n1 + n2
      length = N = N1 + N2
      volume = N * log2(n) (при n > 0)
      difficulty = (n1 / 2) * (N2 / n2) (при n2 > 0)
      effort = difficulty * volume

Метрики размеров и комментариев
------------------------------
- SLOC (source lines of code): число существенных строк кода в диапазоне (без пустых строк,
  без строк, состоящих только из комментариев, и с учётом исключения docstring из кода).
- Code-to-comment ratio: отношение code_lines / comment_lines (docstring учитывается как комментарий для этой метрики).

Метрика ответов класса
----------------------
- RFC (Response For a Class):
    Оценивается через ориентированный граф вызовов caller -> set(callees).
    Для каждого метода класса выполняется обход достижимых узлов в графе; RFC класса
    принимается как максимум размеров множеств достижимости среди его методов.

Вложенность
----------
- Максимальный уровень вложенности управляющих конструкций внутри метода — считается
  путём обхода AST метода посетителем вложенности (композитный visitor).

Ограничения
-----------
- Анализ синтаксический (AST) и локальный — динамическое разрешение имён, импортов,
  aliasing, отражение (reflection) и вызовы через полученные объекты не разрешаются.
- Для вычисления некоторых метрик используются вспомогательные модули (см. импорты):
  cognitive_visitor, halstead_utils, cohesion_calculators, call_graph_collector, nesting_visitor.
"""

import ast
from .cognitive_visitor import _CognitiveComplexityVisitor
from .halstead_utils import _QualifiedHalsteadMetricsVisitor
from .cohesion_calculators import _LCOM4Calculator, _ClassCohesionCalculator
from .call_graph_collector import _CallGraphCollector
from .nesting_visitor import _NestingLevelVisitor


class StaticCodeAnalyser:
    """
    Фасадный класс статического анализатора.

    Техническая реализация
    ----------------------
    - Парсинг: при инициализации файл читается в память и парсится в AST (ast.parse).
    - Ленивые вычисления: дорогостоящие операции (посетители, сбор графа) выполняются
      по требованию и кэшируются в полях-«кэше».
    - Связь с внешними компонентами:
        * `_CognitiveComplexityVisitor` — собирает cognitive complexity по контекстам.
        * `_QualifiedHalsteadMetricsVisitor` — собирает Halstead-метрики для квалифицированных контекстов.
        * `_LCOM4Calculator`, `_ClassCohesionCalculator` — вычисляют cohesion-метрики.
        * `_CallGraphCollector` — строит ориентированный граф вызовов для RFC.
        * `_NestingLevelVisitor` — считает уровень вложенности для метода.
    - Форматы имен:
        - Функции:   "function:<name>"
        - Методы:    "class:<Class>.<method>"
        - Классы:    "class:<Class>"
        - Глобальные вызовы: ключ "global" в некоторых visitor-результатах
    - Публичный API: набор методов, возвращающих mapping 'class:Name' -> значение
      (или mapping квалифицированных имён методов, где это уместно).
    """

    def __init__(self, filename: str) -> None:
        """
        Инициализация анализатора: чтение файла и парсинг в AST.

        Атрибуты экземпляра (основные):
        - code: str
            Содержимое файла.
        - tree: ast.Module
            AST-представление модуля.
        - code_lines: list[str]
            Список строк исходного кода, используется для подсчёта SLOC и комментариев.
        - _class_nodes_cache: list[ast.ClassDef] | None
            Кэш списка top-level классов.
        - _all_cognitive_cache: dict[str, int] | None
            Кэш всех значений cognitive complexity по контекстам.
        - _method_cognitive_map_cache: dict[str, int] | None
            Кэш cognitive complexity для методов классов (формат "class:Cls.method" -> int).
        - _all_halstead_cache: dict[str, tuple[float,float,float]] | None
            Кэш Halstead-метрик по контекстам.
        - _method_halstead_map_cache: dict[str, tuple[float, float, float]] | None
            Halstead-метрики для методов классов.
        """
        with open(filename, "r", encoding="utf-8") as f:
            self.code: str = f.read()
        try:
            self.tree: ast.Module = ast.parse(self.code)
        except SyntaxError as e:
            raise ValueError(f"Ошибка парсинга кода: {e}")

        # Кэши (ленивые вычисления)
        self._class_nodes_cache: list[ast.ClassDef] | None = None
        self._all_cognitive_cache: dict[str, int] | None = None
        self._method_cognitive_map_cache: dict[str, int] | None = None
        self._all_halstead_cache: dict[str, tuple[float, float, float]] | None = None
        self._method_halstead_map_cache: dict[str, tuple[float, float, float]] | None = None

        # Список строк исходного кода (1-based логика обращения в методах)
        self.code_lines: list[str] = self.code.splitlines()

    def _class_nodes(self) -> list[ast.ClassDef]:
        """
        Возвращает список top-level ast.ClassDef в модуле (кэшируется).
        """
        if self._class_nodes_cache is None:
            self._class_nodes_cache = [n for n in self.tree.body if isinstance(n, ast.ClassDef)]
        return self._class_nodes_cache

    def _compute_all_cognitive(self) -> dict[str, int]:
        """
        Запустить _CognitiveComplexityVisitor по дереву и вернуть результат mapping context->value.
        Гарантируется наличие ключа "global" (0 при отсутствии).
        """
        if self._all_cognitive_cache is None:
            v = _CognitiveComplexityVisitor()
            v.visit(self.tree)
            if "global" not in v.result:
                v.result["global"] = 0
            self._all_cognitive_cache = v.result
        return self._all_cognitive_cache

    def _compute_method_cognitive_map(self) -> dict[str, int]:
        """
        Вернуть cognitive complexity только для методов классов в формате:
            "class:ClassName.method" -> int

        Отбор производится по ключам, начинающимся с "class:" и содержащим точку после префикса.
        """
        if self._method_cognitive_map_cache is None:
            all_cc = self._compute_all_cognitive()
            self._method_cognitive_map_cache = {
                k: int(v) for k, v in all_cc.items() if k.startswith("class:") and "." in k
            }
        return self._method_cognitive_map_cache
