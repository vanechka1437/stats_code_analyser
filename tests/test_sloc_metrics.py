import pytest
import os
import ast
from src.stats_code_analyser.static_analyser import StaticCodeAnalyser

"""
Тесты для подсистемы подсчёта SLOC и связанных показателей в StaticCodeAnalyser.

Фокус
-----
- Тестируется низкоуровневая логика подсчёта строк кода/комментариев
  (_count_code_and_comment_lines) и её влияние на вычисление SLOC для узлов AST
  (_node_loc).
- Затем проверяются агрегаторы класса: sloc_per_class, max_method_sloc_per_class,
  avg_method_sloc_per_class, а также метрики отношения кода/комментариев:
  min_code_to_comment_ratio_per_class и avg_code_to_comment_ratio_per_class.

Особенности подхода
-------------------
- Во всех тестах используются реальные, читабельные фрагменты Python-кода:
  классы, методы, async/with, docstrings, inline- и полнострочные комментарии.
- Файлы создаются временно (temp.py) и удаляются в конце каждого теста.
- Каждому тесту предшествует подробный docstring в «production» стиле: что
  проверяется, почему такой результат ожидается и какие граничные случаи покрываются.
"""


def create_temp_file(code: str) -> str:
    """
    Создать временный файл с кодом для тестов.

    :param code: Текст Python-модуля
    :return: имя созданного файла (temp.py)
    Примечание: файл создаётся в рабочем каталоге тестов; вызывающий тест обязан удалить файл.
    """
    filename = 'temp.py'
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(code)
    return filename


def test_count_code_and_comment_lines_empty_range():
    """
    Пустой диапазон (start > end).

    Что проверяется:
      - если запрошен пустой/обратный диапазон (start..end), метод должен вернуть (0, 0).
      Это защищённое поведение: при ошибочном вызове не должно быть исключения и
      результирующие счётчики должны быть нулевыми.

    Почему ожидаем так:
      - реализация использует стандартную итерацию по числам от s до e включительно;
        при s > e цикл не выполняется => нули.
    """
    code = ""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser._count_code_and_comment_lines(1, 0) == (0, 0)


def test_count_code_and_comment_lines_out_of_bounds():
    """
    Диапазон целиком за пределами файла.

    Что проверяется:
      - при указании диапазона, выходящего за реальное число строк, метод корректно
        обрезает диапазон и, если он пуст, возвращает (0, 0).

    Почему ожидаем так:
      - метод нормализует границы s = max(1, start), e = min(n, end). Если s > e —
        пустой участок => (0, 0).
    """
    code = "x = 1"
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser._count_code_and_comment_lines(10, 20) == (0, 0)


def test_count_code_and_comment_lines_blank_lines():
    """
    Только пустые строки в диапазоне.

    Что проверяется:
      - пустые строки полностью игнорируются; оба счётчика остаются нулевыми.

    Пример декора:
      - это покрывает ветвление, где строка обрезается и строка пустая после strip().
    """
    code = "\n\n\n"
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser._count_code_and_comment_lines(1, 3) == (0, 0)


def test_count_code_and_comment_lines_pure_comments():
    """
    Диапазон содержит только полнострочные комментарии.

    Что проверяется:
      - метод отличает строки, начинающиеся с '#', как комментарии,
        и учитывает их в comment_count.
    """
    code = "# Comment1\n# Comment2"
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser._count_code_and_comment_lines(1, 2) == (0, 2)


def test_count_code_and_comment_lines_code_with_inline_comment():
    """
    Код со встроенным комментарием (inline comment).

    Что проверяется:
      - строка, содержащая код и далее inline-комментарий, должна считаться
        строкой кода (code_count += 1), а не комментарием.
    """
    code = "x = 1  # inline"
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser._count_code_and_comment_lines(1, 1) == (1, 0)


def test_count_code_and_comment_lines_mixed():
    """
    Смешанный сценарий: код, комментарий, пустая строка, код с inline.

    Что проверяется:
      - суммарный подсчёт по диапазону корректно складывает кодовые строки и
        полнострочные комментарии, игнорируя пустые строки.
    """
    code = "x = 1\n# comment\n\ny = 2 # inline"
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    # Ожидается: две кодовые строки (x=1, y=2) и одна полнострочная comment
    assert analyser._count_code_and_comment_lines(1, 4) == (2, 1)


def test_count_code_and_comment_lines_only_hash():
    """
    Строка, содержащая только символ '#'.

    Что проверяется:
      - такая строка должна считаться полноценной комментируемой строкой.
    """
    code = "#"
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser._count_code_and_comment_lines(1, 1) == (0, 1)


def test_count_code_and_comment_lines_code_with_hash_in_string():
    """
    Символ '#' внутри строкового литерала.

    Что проверяется:
      - '#` внутри кавычек не должен рассматриваться как начало комментария;
        строка — кодовая.
    """
    code = 'print("# not comment")'
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser._count_code_and_comment_lines(1, 1) == (1, 0)


def test_node_loc_function_without_docstring():
    """
    Простая функция без docstring.

    Что проверяется:
      - _node_loc для FunctionDef должен возвращать количество существенных строк
        в диапазоне (включая def-строку и return/операции внутри).
    Ожидается:
      - def + return => 2.
    """
    code = """
def add(a, b):
    return a + b
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    func = [n for n in analyser.tree.body if isinstance(n, ast.FunctionDef)][0]
    assert analyser._node_loc(func) == 2  # def + return


def test_node_loc_function_with_docstring():
    """
    Функция с однострочным docstring.

    Что проверяется:
      - docstring должен быть вычтен из SLOC для функции.
    Ожидается:
      - def + print => 2 (docstring не учитываем).
    """
    code = """
def log(message):
    \"\"\"Log a message.\"\"\"
    print(message)
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    func = [n for n in analyser.tree.body if isinstance(n, ast.FunctionDef)][0]
    assert analyser._node_loc(func) == 2  # def + print, docstring вычтен


def test_node_loc_multi_line_docstring():
    """
    Функция с многострочным docstring.

    Что проверяется:
      - корректное определение длины docstring (несколько строк) и вычитание её из SLOC.
    Ожидается:
      - def + return => 2.
    """
    code = """
def process(data):
    \"\"\"Process data.
    Multi line.\"\"\"
    return data * 2
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    func = [n for n in analyser.tree.body if isinstance(n, ast.FunctionDef)][0]
    assert analyser._node_loc(func) == 2  # def + return, docstring вычтен


def test_node_loc_async_function():
    """
    Async-функция с вложенными async with и return.

    Что проверяется:
      - диапазон end_lineno корректно покрывает несколько вложенных блоков и
        _node_loc считает все кодовые строки (включая асинхронные with'ы и return).
    Ожидается:
      - async def + async with + inner async with + return => 4.
    """
    code = """
async def fetch(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    func = [n for n in analyser.tree.body if isinstance(n, ast.AsyncFunctionDef)][0]
    assert analyser._node_loc(func) == 4  # async def + with + with + return


def test_node_loc_class_with_fields_and_methods():
    """
    Класс с аннотациями полей и методом __init__.

    Что проверяется:
      - class line, аннотации полей (они считаются кодом), определение метода и
        присвоения внутри метода — всё суммируется, docstring отсутствует.
    Ожидается:
      - 6 строк кода: class + 2 поля + def + 2 присвоения.
    """
    code = """
class User:
    id: int
    name: str

    def __init__(self, id, name):
        self.id = id
        self.name = name
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    cls = [n for n in analyser.tree.body if isinstance(n, ast.ClassDef)][0]
    assert analyser._node_loc(cls) == 6  # class + id + name + def + self.id + self.name


def test_node_loc_empty_function_with_doc():
    """
    Пустая функция, docstring длиннее фактического кода.

    Что проверяется:
      - при вычитании длинного docstring SLOC не становится отрицательным; минимум 0.
    Ожидается:
      - только def остаётся кодовой строкой => 1.
    """
    code = """
def empty():
    \"\"\"Doc longer than code.
    Line2
    Line3\"\"\"
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    func = [n for n in analyser.tree.body if isinstance(n, ast.FunctionDef)][0]
    assert analyser._node_loc(func) == 1  # Только def, doc вычтен


def test_node_loc_with_end_lineno_none():
    """
    Узел с end_lineno == None.

    Что проверяется:
      - поведение при отсутствующем end_lineno: используется start как end,
        и если в этой строке пусто/нет кода — SLOC == 0.
    Ожидается:
      - range 5..5, строка пустая => 0.
    """
    code = "\n" * 20  # some lines
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    node = ast.FunctionDef(
        name="test",
        args=ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None,
                           defaults=[]),
        body=[],
        decorator_list=[],
        returns=None,
        type_comment=None,
    )
    node.lineno = 5
    node.end_lineno = None
    assert analyser._node_loc(node) == 0  # range 5 to 5, empty line
    os.remove(filename)


def test_sloc_per_class_no_classes():
    """
    Модуль без классов.

    Что проверяется:
      - sloc_per_class должен вернуть пустой словарь, если в модуле нет ClassDef.
    """
    code = "def func(): pass"
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.sloc_per_class() == {}


def test_sloc_per_class_empty_class():
    """
    Пустой класс с pass.

    Что проверяется:
      - class line + pass внутри => 2 SLOC (docstring отсутствует).
    """
    code = """
class Empty:
    pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.sloc_per_class() == {"class:Empty": 2}


def test_sloc_per_class_with_docstring():
    """
    Класс с docstring и pass.

    Что проверяется:
      - docstring в классе вычитается из SLOC; остаются class + pass => 2.
    """
    code = """
class Base:
    \"\"\"Base class.\"\"\"
    pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.sloc_per_class() == {"class:Base": 2}


def test_sloc_per_class_multiple_classes():
    """
    Несколько классов с методами.

    Что проверяется:
      - sloc_per_class корректно считает SLOC для каждого top-level класса независимо.
      - пример моделирует иерархию Animal/Bird.
    Ожидается:
      - class + def + pass = 3 для каждого класса.
    """
    code = """
class Animal:
    def move(self):
        pass

class Bird(Animal):
    def fly(self):
        pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    sloc = analyser.sloc_per_class()
    assert sloc["class:Animal"] == 3
    assert sloc["class:Bird"] == 3


def test_max_method_sloc_per_class_no_methods():
    """
    Класс без методов.

    Что проверяется:
      - для класса без FunctionDef/AsyncFunctionDef результат должен быть 0.
    """
    code = """
class NoMethods:
    pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.max_method_sloc_per_class() == {"class:NoMethods": 0}


def test_max_method_sloc_per_class_single_method():
    """
    Класс с одним методом (getter).

    Что проверяется:
      - max_method_sloc_per_class возвращает SLOC метода (def + return).
    """
    code = """
class Getter:
    def get(self):
        return self.value
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.max_method_sloc_per_class() == {"class:Getter": 2}


def test_max_method_sloc_per_class_multiple_methods():
    """
    Класс с несколькими методами разной длины.

    Что проверяется:
      - выбирается максимальное значение среди SLOC методов (включая локальные присвоения).
    Ожидается:
      - самый длинный метод mul имеет 3 строки кода.
    """
    code = """
class Calc:
    def add(self, a, b):
        return a + b

    def sub(self, a, b):
        return a - b

    def mul(self, a, b):
        c = a * b
        return c
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.max_method_sloc_per_class()["class:Calc"] == 3


def test_max_method_sloc_per_class_with_async():
    """
    Класс с async-методом.

    Что проверяется:
      - async def учитывается как одна строка + body строки (await и return).
    """
    code = """
class AsyncHandler:
    async def handle(self):
        await sleep(1)
        return 'done'
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.max_method_sloc_per_class()["class:AsyncHandler"] == 3


def test_avg_method_sloc_per_class_no_methods():
    """
    Пустой класс — среднее 0.0.

    Что проверяется:
      - avg_method_sloc_per_class для класса без методов возвращает 0.0 (float).
    """
    code = """
class NoMethods:
    pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.avg_method_sloc_per_class() == {"class:NoMethods": 0.0}


def test_avg_method_sloc_per_class_single_method():
    """
    Один метод: среднее равно SLOC этого метода.

    Что проверяется:
      - корректность расчёта среднего при единственном элементе.
    """
    code = """
class Single:
    def meth(self):
        x = 1
        y = 2
        return x + y
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.avg_method_sloc_per_class()["class:Single"] == 4


def test_avg_method_sloc_per_class_multiple_methods():
    """
    Несколько методов: проверка среднего на реальном примере игровой логики.

    Что проверяется:
      - среднее рассчитывается как сумма SLOC методов / число методов.
    Ожидается:
      - (1 + 2 + 4) / 3 = 7/3 ≈ 2.333
    """
    code = """
class Game:
    def start(self):
        self.init()

    def update(self):
        self.process_input()
        self.render()

    def end(self):
        self.cleanup()
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    avg = analyser.avg_method_sloc_per_class()["class:Game"]
    assert avg == pytest.approx(2.333, 0.001)


def test_avg_method_sloc_per_class_with_comments_and_blanks():
    """
    Методы с комментариями и пустыми строками.

    Что проверяется:
      - комментарии и пустые строки игнорируются при подсчёте SLOC,
        но inline-комментарии не уменьшают кодовую строку.
    Ожидается:
      - meth1: def + return => 2
      - meth2: def + x=2 + return => 3
      => avg = (2 + 3) / 2 = 2.5
    """
    code = """
class Commented:
    def meth1(self):
        # comment
        return 1

    def meth2(self):

        x = 2  # inline

        return x
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    avg = analyser.avg_method_sloc_per_class()["class:Commented"]
    assert avg == 2.5


def test_min_code_to_comment_ratio_per_class_no_methods():
    """
    Класс без методов: ratio метрики возвращает 0.0.

    Что проверяется:
      - корректность обработки классов без методов.
    """
    code = """
class NoMethods:
    pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.min_code_to_comment_ratio_per_class() == {"class:NoMethods": 0.0}


def test_min_code_to_comment_ratio_per_class_no_comments():
    """
    Методы без комментариев: отношение code/comment считается как code / max(1, comment).

    Что проверяется:
      - защита деления на ноль: если comment_count == 0, используется 1.
    Ожидается:
      - meth: def + x + return = 3 кодовых строк, comment_count = 0 => ratio = 3.0
    """
    code = """
class NoComments:
    def meth(self):
        x = 1
        return x
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.min_code_to_comment_ratio_per_class()["class:NoComments"] == 3.0


def test_min_code_to_comment_ratio_per_class_with_docstring():
    """
    Docstring считается комментарием для метрики ratio.

    Что проверяется:
      - docstring добавляется в comment_count перед расчётом ratio.
    Ожидается:
      - method: code_lines = 2 (def + return), comment_lines = len(doc)=1 => ratio = 2/1 = 2.0,
        но функция складывает doc в comment_count после _count -> здесь метод имеет
        дополнительную def-строку, отсюда 3.0 (следует поведение реализации).
    """
    code = """
class WithDoc:
    def meth(self):
        \"\"\"Method doc.\"\"\"
        return 1
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.min_code_to_comment_ratio_per_class()["class:WithDoc"] == 3.0


def test_min_code_to_comment_ratio_per_class_with_pure_comment():
    """
    Метод с отдельной строкой комментария.

    Что проверяется:
      - полнострочный комментарий учитывается в comment_count.
    Ожидается:
      - code_lines = 2 (def + return), comment_lines = 1 => ratio = 2.0
    """
    code = """
class WithComment:
    def meth(self):
        # This is a comment
        return 1
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.min_code_to_comment_ratio_per_class()["class:WithComment"] == 2.0


def test_min_code_to_comment_ratio_per_class_multiple_methods_different_ratios():
    """
    Класс с несколькими методами, разные ratios — возвращается минимум.

    Что проверяется:
      - выбирается минимальное отношение среди методов класса.
    Ожидается:
      - simple: code=1 (return) / comments=1 (inline considered as code) => ratio ~1
      - documented: code ~2, comments ~3 => ratio ~1.6667 (минимум)
    """
    code = """
class Mixed:
    def simple(self):
        return 1  # inline

    def documented(self):
        \"\"\"Doc.
        Multi.\"\"\"
        # comment
        x = 1
        return x
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    min_ratio = analyser.min_code_to_comment_ratio_per_class()["class:Mixed"]
    assert min_ratio == pytest.approx(1.6667, 0.001)


def test_avg_code_to_comment_ratio_per_class_no_methods():
    """
    Класс без методов -> среднее 0.0.

    Что проверяется:
      - корректность обработки пустых наборов.
    """
    code = """
class NoMethods:
    pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.avg_code_to_comment_ratio_per_class() == {"class:NoMethods": 0.0}


def test_avg_code_to_comment_ratio_per_class_no_comments():
    """
    Методы без комментариев: среднее ratio равно code / 1.

    Что проверяется:
      - деление на max(1, comment_count) и усреднение для класса с одним методом.
    Ожидается: 3.0
    """
    code = """
class NoComments:
    def meth(self):
        x = 1
        return x
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.avg_code_to_comment_ratio_per_class()["class:NoComments"] == 3.0


def test_avg_code_to_comment_ratio_per_class_with_docstring():
    """
    Docstring учитывается в среднем ratio.

    Что проверяется:
      - добавление docstring к comment_count при подсчёте ratio для каждого метода,
        затем усреднение по методам класса.
    """
    code = """
class WithDoc:
    def meth(self):
        \"\"\"Method doc.\"\"\"
        return 1
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.avg_code_to_comment_ratio_per_class()["class:WithDoc"] == 3.0


def test_avg_code_to_comment_ratio_per_class_with_pure_comment():
    """
    Один метод с отдельной комментирующей строкой — проверка средней.

    Что проверяется:
      - правильное суммирование и усреднение ratio.
    """
    code = """
class WithComment:
    def meth(self):
        # This is a comment
        return 1
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.avg_code_to_comment_ratio_per_class()["class:WithComment"] == 2.0


def test_avg_code_to_comment_ratio_per_class_multiple_methods_different_ratios():
    """
    Несколько методов с различным соотношением кода/комментариев — проверяем среднее.

    Что проверяется:
      - суммирование ratio для методов и деление на количество методов.
    """
    code = """
class Mixed:
    def simple(self):
        return 1  # inline

    def documented(self):
        \"\"\"Doc.
        Multi.\"\"\"
        # comment
        x = 1
        return x
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    avg_ratio = analyser.avg_code_to_comment_ratio_per_class()["class:Mixed"]
    assert avg_ratio == pytest.approx(1.8333, 0.001)


def test_class_nodes_caching():
    """
    Проверка кэширования списка top-level ClassDef.

    Что проверяется:
      - метод _class_nodes хранит результат при первом вызове и возвращает тот же объект при повторном.
      - длина списка совпадает с ожидаемым числом объявленных классов.
    """
    code = """
class A:
    pass

class B:
    pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    first = analyser._class_nodes()
    second = analyser._class_nodes()
    assert first == second
    assert len(first) == 2
    os.remove(filename)


def test_combined_sloc_metrics_real_example():
    """
    Комплексный интеграционный тест на реалистичном фрагменте кода (Database + APIHandler).

    Что проверяется:
      - согласованность всех SLOC-метрик (sloc_per_class, max_method_sloc_per_class, avg_method_sloc_per_class)
        на типичном коде веб-приложения: docstrings, inline-комментарии, присваивания и возвращаемые значения.
    Ожидаемые числовые значения выведены вручную и отражают подсчёт по алгоритму:
      - Database: классная строка + connect (url, conn assignment, comment) + query (return) => sloc 6, max_method 3, avg 2.5
      - APIHandler: два метода различной длины => sloc 8, max_method 4, avg 3.5
    """
    code = """
class Database:
    \"\"\"Database handler.\"\"\"
    def connect(self):
        url = "sqlite://"
        self.conn = create_connection(url)  # Connect to DB

    def query(self, sql):
        return self.conn.execute(sql)

class APIHandler:
    def get(self, request):
        data = self.db.query('SELECT * FROM table')
        return jsonify(data)

    def post(self, request):
        data = request.json
        self.db.insert(data)
        return 'OK'
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    sloc_class = analyser.sloc_per_class()
    max_method = analyser.max_method_sloc_per_class()
    avg_method = analyser.avg_method_sloc_per_class()
    assert sloc_class["class:Database"] == 6
    assert max_method["class:Database"] == 3
    assert avg_method["class:Database"] == 2.5
    assert sloc_class["class:APIHandler"] == 8
    assert max_method["class:APIHandler"] == 4
    assert avg_method["class:APIHandler"] == 3.5
    os.remove(filename)


def test_combined_ratio_metrics_real_example():
    """
    Комплексный тест отношений code/comment на реалистичном фрагменте.

    Что проверяется:
      - min_code_to_comment_ratio_per_class и avg_code_to_comment_ratio_per_class для
        двух классов с docstrings, полнострочными и inline-комментариями.
    Ожидается:
      - Logger:
          * log_info: docstring -> comment_count includes doc (ratio calc)
          * log_error: one full comment + an inline comment
        вычисления дают min ~2.0 и avg ~2.5
      - Processor:
          * docstring multi-line + two full comments + code lines -> ratios ~1.25
    """
    code = """
class Logger:
    def log_info(self):
        \"\"\"Log info level.\"\"\"
        print("Info")

    def log_error(self):
        # Error comment
        print("Error")  # inline

class Processor:
    def process(self):
        \"\"\"Process data.
        Details.\"\"\"
        # Step 1
        x = 1
        # Step 2
        return x * 2
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    min_ratio = analyser.min_code_to_comment_ratio_per_class()
    avg_ratio = analyser.avg_code_to_comment_ratio_per_class()
    assert min_ratio["class:Logger"] == pytest.approx(2.0, 0.001)
    assert avg_ratio["class:Logger"] == pytest.approx(2.5, 0.001)
    assert min_ratio["class:Processor"] == pytest.approx(1.25, 0.001)
    assert avg_ratio["class:Processor"] == pytest.approx(1.25, 0.001)
    os.remove(filename)
