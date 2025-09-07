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

    def _compute_all_halstead(self) -> dict[str, tuple[float, float, float]]:
        """
        Запустить _QualifiedHalsteadMetricsVisitor и вернуть mapping context -> (volume, difficulty, effort).
        Кэшируется; гарантируется наличие ключа "global".
        """
        if self._all_halstead_cache is None:
            v = _QualifiedHalsteadMetricsVisitor(self.code)
            v.visit(self.tree)
            if "global" not in v.result:
                v.result["global"] = (0.0, 0.0, 0.0)
            self._all_halstead_cache = v.result
        return self._all_halstead_cache

    def _compute_method_halstead_map(self) -> dict[str, tuple[float, float, float]]:
        """
        Вернуть Halstead-метрики только для методов классов:
            "class:ClassName.method" -> (volume, difficulty, effort)
        """
        if self._method_halstead_map_cache is None:
            all_h = self._compute_all_halstead()
            self._method_halstead_map_cache = {
                k: (float(v[0]), float(v[1]), float(v[2]))
                for k, v in all_h.items()
                if k.startswith("class:") and "." in k
            }
        return self._method_halstead_map_cache

    def _node_loc(self, node: ast.AST) -> int:
        """
        Посчитать SLOC (source lines of code) для узла (ClassDef / FunctionDef / AsyncFunctionDef).

        Подход:
          - берём диапазон node.lineno .. node.end_lineno;
          - считаем строки с кодом (inline-комментарии не уменьшают кодовую строку);
          - вычитаем строки docstring (если есть).
        """
        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", start)
        if end is None:
            end = start
        code_count, _ = self._count_code_and_comment_lines(start, end)
        doc = ast.get_docstring(node)
        if doc:
            doc_lines = len(doc.splitlines())
            code_count -= doc_lines
        return max(0, code_count)

    def _count_code_and_comment_lines(self, start: int, end: int) -> tuple[int, int]:
        """
        Вернуть (code_count, comment_count) на отрезке [start, end] (1-based).

        Правила:
        - строка с кодом и inline-комментарием считается кодовой;
        - строки, содержащие только комментарии — считаются комментариями;
        - пустые строки игнорируются.
        """
        code_count = 0
        comment_count = 0
        n = len(self.code_lines)
        s = max(1, start)
        e = min(n, end)
        for lineno in range(s, e + 1):
            line = self.code_lines[lineno - 1]
            line_no_comment = line.split("#", 1)[0].strip()
            if not line_no_comment:
                stripped = line.strip()
                if stripped and stripped.startswith("#"):
                    comment_count += 1
                continue
            code_count += 1
        return code_count, comment_count

    def lcom4(self) -> dict[str, int]:
        """LCOM4 для каждого top-level класса: 'class:Name' -> int"""
        return {f"class:{cls.name}": _LCOM4Calculator.compute(cls) for cls in self._class_nodes()}

    def tcc(self) -> dict[str, float]:
        """TCC для каждого top-level класса: 'class:Name' -> float"""
        return {f"class:{cls.name}": _ClassCohesionCalculator.compute_tcc(cls) for cls in self._class_nodes()}

    def lcc(self) -> dict[str, float]:
        """LCC для каждого top-level класса: 'class:Name' -> float"""
        return {f"class:{cls.name}": _ClassCohesionCalculator.compute_lcc(cls) for cls in self._class_nodes()}

    def max_cognitive_per_class(self) -> dict[str, int]:
        """Максимальная cognitive complexity среди методов класса: 'class:Name' -> int"""
        method_map = self._compute_method_cognitive_map()
        results: dict[str, int] = {}
        for cls in self._class_nodes():
            prefix = f"class:{cls.name}."
            vals = [v for k, v in method_map.items() if k.startswith(prefix)]
            results[f"class:{cls.name}"] = max(vals) if vals else 0
        return results

    def avg_cognitive_per_class(self) -> dict[str, float]:
        """Средняя cognitive complexity методов класса: 'class:Name' -> float"""
        method_map = self._compute_method_cognitive_map()
        results: dict[str, float] = {}
        for cls in self._class_nodes():
            prefix = f"class:{cls.name}."
            vals = [v for k, v in method_map.items() if k.startswith(prefix)]
            avg = sum(vals) / len(vals) if vals else 0.0
            results[f"class:{cls.name}"] = avg
        return results

    def total_cognitive_per_class(self) -> dict[str, int]:
        """Суммарная cognitive complexity всех методов класса."""
        method_map = self._compute_method_cognitive_map()
        results: dict[str, int] = {}
        for cls in self._class_nodes():
            prefix = f"class:{cls.name}."
            total = sum(v for k, v in method_map.items() if k.startswith(prefix))
            results[f"class:{cls.name}"] = total
        return results

    def sloc_per_class(self) -> dict[str, int]:
        """SLOC класса (без blanks/comments/docstrings)."""
        return {f"class:{cls.name}": self._node_loc(cls) for cls in self._class_nodes()}

    def max_method_sloc_per_class(self) -> dict[str, int]:
        """Максимальный SLOC среди методов класса."""
        results: dict[str, int] = {}
        for cls in self._class_nodes():
            method_locs = [
                self._node_loc(m) for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            results[f"class:{cls.name}"] = max(method_locs) if method_locs else 0
        return results

    def avg_method_sloc_per_class(self) -> dict[str, float]:
        """Средний SLOC методов класса."""
        results: dict[str, float] = {}
        for cls in self._class_nodes():
            method_locs = [
                self._node_loc(m) for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            avg = sum(method_locs) / len(method_locs) if method_locs else 0.0
            results[f"class:{cls.name}"] = avg
        return results

    def max_halstead_difficulty_per_class(self) -> dict[str, float]:
        """Максимальная Halstead difficulty среди методов класса."""
        method_h = self._compute_method_halstead_map()
        results: dict[str, float] = {}
        for cls in self._class_nodes():
            prefix = f"class:{cls.name}."
            diffs = [v[1] for k, v in method_h.items() if k.startswith(prefix)]
            results[f"class:{cls.name}"] = max(diffs) if diffs else 0.0
        return results

    def max_halstead_effort_per_class(self) -> dict[str, float]:
        """Максимальная Halstead effort среди методов класса."""
        method_h = self._compute_method_halstead_map()
        results: dict[str, float] = {}
        for cls in self._class_nodes():
            prefix = f"class:{cls.name}."
            efforts = [v[2] for k, v in method_h.items() if k.startswith(prefix)]
            results[f"class:{cls.name}"] = max(efforts) if efforts else 0.0
        return results

    def avg_halstead_difficulty_per_class(self) -> dict[str, float]:
        """Средняя Halstead difficulty методов класса."""
        method_h = self._compute_method_halstead_map()
        results: dict[str, float] = {}
        for cls in self._class_nodes():
            prefix = f"class:{cls.name}."
            diffs = [v[1] for k, v in method_h.items() if k.startswith(prefix)]
            avg = sum(diffs) / len(diffs) if diffs else 0.0
            results[f"class:{cls.name}"] = avg
        return results

    def avg_halstead_effort_per_class(self) -> dict[str, float]:
        """Средняя Halstead effort методов класса."""
        method_h = self._compute_method_halstead_map()
        results: dict[str, float] = {}
        for cls in self._class_nodes():
            prefix = f"class:{cls.name}."
            efforts = [v[2] for k, v in method_h.items() if k.startswith(prefix)]
            avg = sum(efforts) / len(efforts) if efforts else 0.0
            results[f"class:{cls.name}"] = avg
        return results

    def number_of_methods_per_class(self) -> dict[str, int]:
        """Число методов (FunctionDef/AsyncFunctionDef) в каждом классе."""
        return {
            f"class:{cls.name}": sum(1 for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
            for cls in self._class_nodes()
        }

    def min_code_to_comment_ratio_per_class(self) -> dict[str, float]:
        """
        Минимальное отношение code/comment среди методов класса.

        Docstring рассматривается как часть комментариев в этой метрике.
        """
        results: dict[str, float] = {}
        for cls in self._class_nodes():
            ratios: list[float] = []
            for m in (node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
                start = getattr(m, "lineno", 0)
                end = getattr(m, "end_lineno", start)
                code_count, comment_count = self._count_code_and_comment_lines(start, end)
                doc = ast.get_docstring(m)
                if doc:
                    comment_count += len(doc.splitlines())
                ratio = code_count / max(1, comment_count)
                ratios.append(ratio)
            results[f"class:{cls.name}"] = min(ratios) if ratios else 0.0
        return results

    def avg_code_to_comment_ratio_per_class(self) -> dict[str, float]:
        """Среднее отношение code/comment среди методов класса."""
        results: dict[str, float] = {}
        for cls in self._class_nodes():
            ratios: list[float] = []
            for m in (node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
                start = getattr(m, "lineno", 0)
                end = getattr(m, "end_lineno", start)
                code_count, comment_count = self._count_code_and_comment_lines(start, end)
                doc = ast.get_docstring(m)
                if doc:
                    comment_count += len(doc.splitlines())
                ratios.append(code_count / max(1, comment_count))
            avg = sum(ratios) / len(ratios) if ratios else 0.0
            results[f"class:{cls.name}"] = avg
        return results

    def response_for_class(self) -> dict[str, int]:
        """
        RFC (Response For a Class).

        Для каждого метода выполняется DFS по графу вызовов (собранному _CallGraphCollector).
        RFC класса = максимум размеров множеств достижимости среди его методов.
        """
        collector = _CallGraphCollector()
        graph = collector.build(self.tree)  # caller -> set(callees)
        results: dict[str, int] = {}

        for cls in self._class_nodes():
            start_nodes = [
                f"class:{cls.name}.{m.name}"
                for m in cls.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            max_rfc = 0
            for start in start_nodes:
                visited: set[str] = {start}
                stack: list[str] = [start]
                while stack:
                    cur = stack.pop()
                    for callee in graph.get(cur, set()):
                        if callee not in visited:
                            visited.add(callee)
                            stack.append(callee)
                max_rfc = max(max_rfc, len(visited))
            results[f"class:{cls.name}"] = max_rfc if start_nodes else 0
        return results

    def max_nesting_level_per_class(self) -> dict[str, int]:
        """
        Максимальный уровень вложенности (nesting) среди методов класса.

        Каждый метод обрабатывается независимым экземпляром _NestingLevelVisitor.
        """
        results: dict[str, int] = {}
        for cls in self._class_nodes():
            levels: list[int] = []
            for m in cls.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    v = _NestingLevelVisitor()
                    v.visit(m)
                    levels.append(v.max_level)
            results[f"class:{cls.name}"] = max(levels) if levels else 0
        return results

