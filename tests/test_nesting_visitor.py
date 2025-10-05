# tests/test_nesting_visitor.py
"""
Тесты для src/nesting_visitor._NestingLevelVisitor.

Описание набора тестов
----------------------
Набор покрывает весь публичный и внутренний функционал посетителя:
- контекстный менеджер _BlockCtx (__enter__/__exit__);
- обход последовательностей (traverse);
- обработчики visit_* для управляющих конструкций: If, For, AsyncFor, While,
  With, AsyncWith, Try, Match, ListComp, SetComp, DictComp, GeneratorExp;
- поведение при вложенных определениях (FunctionDef/ClassDef) — их тела
  учитываются в глубине внешнего блока;
- measure_function: вычисление максимальной глубины для отдельной функции;
- measure_module_functions: сбор глубин для всех функций/методов модуля
  с квалифицированными именами (Class.method или function_name);
- отдельный тест для visit_AsyncFunctionDef, чтобы гарантированно покрыть
  этот путь (он возвращает generic_visit).

Требования к окружению
----------------------
- Python 3.10+ (для поддержки match/case в тестовых примерах).
- Запускать pytest из корня проекта (там, где находятся каталоги `src` и `tests`).
"""

import ast
import pytest
from stats_code_analyser.nesting_visitor import _NestingLevelVisitor


def test_init():
    """
    Проверяет корректную инициализацию объекта _NestingLevelVisitor.

    Что проверяется:
    - после создания экземпляра _current и max_level равны 0;
    - стек квалификаторов пуст.

    Почему важно:
    Начальное состояние определяет корректность последующих измерений;
    некорректный стартовый статус может привести к ложным глубинам.
    """
    v = _NestingLevelVisitor()
    assert v._current == 0
    assert v.max_level == 0
    assert v._qualifier_stack == []


def test_block_ctx_basic():
    """
    Проверяет поведение контекстного менеджера _BlockCtx при обычном использовании.

    Что проверяется:
    - __enter__ увеличивает _current и обновляет max_level;
    - после выхода из with __exit__ восстанавливает _current.

    Ожидаемый результат:
    Внутри with _current == 1 и max_level == 1; после выхода _current == 0.
    """
    v = _NestingLevelVisitor()
    with v._block():
        assert v._current == 1
        assert v.max_level == 1
    assert v._current == 0


def test_block_ctx_nested():
    """
    Проверяет вложенные контекстные менеджеры: накопление глубины.

    Что проверяется:
    - при нескольких вложениях _current увеличивается пошагово;
    - max_level отражает максимальную достигнутую глубину;
    - по выходе из внутренних блоков _current корректно уменьшается до внешнего уровня.

    Ожидаемый результат:
    При трёх вложенных with max_level == 3; по выходу _current возвращается к 0.
    """
    v = _NestingLevelVisitor()
    with v._block():
        assert v._current == 1
        assert v.max_level == 1
        with v._block():
            assert v._current == 2
            assert v.max_level == 2
            with v._block():
                assert v._current == 3
                assert v.max_level == 3
        assert v._current == 1
    assert v._current == 0


def test_block_ctx_exit_negative():
    """
    Покрывает защиту от отрицательных значений в __exit__.

    Что проверяется:
    - если _current по какой-то причине негативен при вызове __exit__,
      значение должно быть установлено в 0 (защита от подпростых ошибок).

    Ожидаемый результат:
    После вызова ctx.__exit__ значение _current равно 0.
    """
    v = _NestingLevelVisitor()
    ctx = v._block()
    v._current = -1
    ctx.__exit__(None, None, None)
    assert v._current == 0


def test_traverse_empty():
    """
    Проверяет traverse([]).

    Что проверяется:
    - обход пустого списка не должен менять счётчики.

    Ожидаемый результат:
    max_level остаётся 0.
    """
    v = _NestingLevelVisitor()
    v.traverse([])
    assert v.max_level == 0


def test_traverse_simple_nodes():
    """
    Проверяет traverse для простых инструкций (присвоений).

    Что проверяется:
    - traversal простых узлов не создаёт дополнительных уровней вложенности.

    Ожидаемый результат:
    max_level == 0 после обхода присвоений.
    """
    code = "x = 1\ny = 2"
    nodes = ast.parse(code).body
    v = _NestingLevelVisitor()
    v.traverse(nodes)
    assert v.max_level == 0


def test_measure_function_type_error():
    """
    Проверяет валидацию входного аргумента в measure_function.

    Что проверяется:
    - если передать узел, не являющийся FunctionDef/AsyncFunctionDef,
      должен быть поднят TypeError.

    Ожидаемый результат:
    TypeError.
    """
    v = _NestingLevelVisitor()
    with pytest.raises(TypeError):
        v.measure_function(ast.Module(body=[]))


def test_measure_function_no_nesting():
    """
    Простая функция без управляющих конструкций.

    Что проверяется:
    - функция, содержащая только присвоения/return, даёт глубину 0.

    Ожидаемый результат:
    measure_function возвращает 0.
    """
    code = """
def simple():
    x = 1
    return x
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 0


def test_measure_function_with_if():
    """
    Одна управляющая конструкция if в теле функции.

    Что проверяется:
    - условие + тело body инкрементируют глубину на 1;
    - orelse не инкрементируется.

    Ожидаемый результат:
    measure_function == 1.
    """
    code = """
def with_if():
    if True:
        print('yes')
    else:
        print('no')
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_nested_if():
    """
    Два вложенных if.

    Что проверяется:
    - if внутри if создаёт накопление уровней.

    Ожидаемый результат:
    measure_function == 2.
    """
    code = """
def nested_if():
    if True:
        if False:
            pass
        else:
            pass
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 2


def test_measure_function_for_loop():
    """
    for ... else: — проверка инкрементации на тело for.

    Что проверяется:
    - тело for увеличивает глубину; orelse не инкрементируется.

    Ожидаемый результат:
    measure_function == 1.
    """
    code = """
def for_loop():
    for i in range(10):
        print(i)
    else:
        print('done')
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_async_for():
    """
    async for внутри async def.

    Что проверяется:
    - visit_AsyncFor делегирует логике for, глубина увеличивается для тела.
    - необходимо покрыть ветвь visit_AsyncFor.

    Ожидаемый результат:
    measure_function == 1.
    """
    code = """
async def async_for():
    async for item in async_iter:
        await process(item)
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.AsyncFunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_while():
    """
    while test: body else: — проверка visit_While.

    Что проверяется:
    - тело while инкрементирует глубину; orelse обходится без инкремента.

    Ожидаемый результат:
    measure_function == 1.
    """
    code = """
def while_loop():
    while condition:
        do_something()
    else:
        cleanup()
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_with_stmt():
    """
    with context as var: — проверяем visit_With и обработку optional_vars.

    Что проверяется:
    - context_expr и optional_vars посещаются, тело инкрементирует глубину.

    Ожидаемый результат:
    measure_function == 1.
    """
    code = """
def with_stmt():
    with open('file') as f:
        data = f.read()
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_async_with():
    """
    async with — покрытие visit_AsyncWith (делегирует visit_With).

    Что проверяется:
    - async with приводит к увеличению глубины, как обычный with.

    Ожидаемый результат:
    measure_function == 1.
    """
    code = """
async def async_with():
    async with async_context() as ctx:
        await use(ctx)
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.AsyncFunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_try_except():
    """
    try / except / else / finally — проверка visit_Try.

    Что проверяется:
    - основной try считается блоком (инкремент);
    - каждый except — отдельный вложенный блок;
    - orelse/finalbody обходятся без инкремента.

    Ожидаемый результат:
    максимальная глубина в простом примере равна 1.
    """
    code = """
def try_except():
    try:
        risky()
    except Exception as e:
        handle(e)
    else:
        success()
    finally:
        cleanup()
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_match():
    """
    Проверка visit_Match: каждый case рассматривается как вложенный блок.

    Что проверяется:
    - subject посещается;
    - для каждого case создаётся отдельный блок;
    - guard (if в case) посещается как выражение.

    Ожидаемый результат:
    глубина = 1 для приведённого примера.
    """
    code = """
def match_stmt(value):
    match value:
        case 1:
            return 'one'
        case 2 if guard:
            return 'two'
        case _:
            return 'other'
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_list_comp():
    """
    List comprehension как отдельный блок.
    Ожидается: comprehension увеличивает глубину на 1.
    """
    code = """
def list_comp():
    [x for x in lst if x > 0]
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_set_comp():
    """
    Set comprehension как отдельный блок.
    """
    code = """
def set_comp():
    {x for x in lst}
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_dict_comp():
    """
    Dict comprehension как отдельный блок.
    """
    code = """
def dict_comp():
    {k: v for k, v in dict.items()}
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_generator_exp():
    """
    Generator expression внутри функции считается отдельным блоком.
    """
    code = """
def gen_exp():
    (x for x in lst)
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_complex_comp():
    """
    Comprehension с несколькими генераторами и условием.

    Что проверяется:
    - последовательность генераторов и условие внутри comprehension
      считаются единым вложенным блоком.
    Ожидается: глубина == 1.
    """
    code = """
def complex_comp():
    [(x,y) for x in lst1 for y in lst2 if x == y]
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_nested_func():
    """
    Вложенная функция: её тело учитывается в подсчёте внешней функции.

    Что проверяется:
    - visit_FunctionDef для вложенной функции использует generic_visit,
      поэтому if внутри inner будет учтён во внешнем подсчёте.
    Ожидается: outer.depth == 1.
    """
    code = """
def outer():
    def inner():
        if True:
            pass
    inner()
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_nested_class():
    """
    Вложенный класс внутри функции: его содержимое учитывается во внешней функции.

    Что проверяется:
    - visit_ClassDef вызывает generic_visit и тело класса обрабатывается;
    - method с with в теле класса увеличит глубину внешней функции.
    """
    code = """
def outer():
    class Inner:
        def meth(self):
            with ctx:
                pass
    return Inner
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_file_processing():
    """
    Реальный пример обработки файла: комбинация try -> with -> for -> if.

    Что проверяется:
    - все вложенные блоки корректно инкрементируют глубину друг за другом.
    Ожидается: максимальная глубина = 4 (try=1, with=2, for=3, if=4).
    """
    code = """
def process_file(path):
    try:
        with open(path) as f:
            for line in f:
                if line.strip():
                    process(line)
    except IOError:
        log_error()
    finally:
        cleanup()
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 4


def test_measure_function_quicksort():
    """
    Quicksort: сочетание if + comprehensions.

    Что проверяется:
    - comprehension и if не приводят к чрезмерному накоплению уровней
      в данном паттерне; ожидаем глубину 1.
    """
    code = """
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[0]
    left = [x for x in arr[1:] if x < pivot]
    right = [x for x in arr[1:] if x > pivot]
    return quicksort(left) + [pivot] + quicksort(right)
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_try_multiple_handlers():
    """
    Проверка try с несколькими except: все except-блоки присутствуют,
    максимальная глубина — 1 в простом примере.
    """
    code = """
def multi_try():
    try:
        do()
    except ValueError:
        handle_value()
    except TypeError:
        handle_type()
    except:
        handle_other()
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_elif():
    """
    Цепочка if / elif / else: elif не добавляет глубины сверх одного уровня.
    """
    code = """
def elif_chain():
    if a:
        pass
    elif b:
        pass
    else:
        pass
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_match_guard():
    """
    match с guard в case: guard рассматривается как выражение, но depth остаётся 1.
    """
    code = """
def match_guard(value):
    match value:
        case x if x > 0:
            positive()
        case x if x < 0:
            negative()
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_function_multi_with():
    """
    Множественный with (with a, b: тело) считается одним блоком — depth == 1.
    """
    code = """
def multi_with():
    with A() as a, B() as b:
        use(a, b)
"""
    func = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    v = _NestingLevelVisitor()
    assert v.measure_function(func) == 1


def test_measure_module_functions_simple():
    """
    Проверяет, что measure_module_functions возвращает словарь с
    - именем top_level для функций верхнего уровня,
    - и 'Class.method' для методов класса.

    Ожидаемый результат: оба ключа присутствуют с глубиной 0.
    """
    code = """
def top_level():
    pass

class Cls:
    def method(self):
        pass
"""
    module = ast.parse(code)
    v = _NestingLevelVisitor()
    results = v.measure_module_functions(module)
    assert 'top_level' in results
    assert 'Cls.method' in results
    assert results['top_level'] == 0
    assert results['Cls.method'] == 0


def test_measure_module_functions_nested():
    """
    Вложенные классы: последний класс в стеке используется при квалификации имени.

    Что проверяется:
    - класс Outer содержит Inner, метод deep_meth должен быть квалифицирован как 'Inner.deep_meth'
      (текущая реализация использует последний элемент стека).
    - также проверяем вложенную функцию top_with_nested -> nested.
    """
    code = """
class Outer:
    class Inner:
        def deep_meth(self):
            if True:
                pass

def top_with_nested():
    def nested():
        while True:
            pass
"""
    module = ast.parse(code)
    v = _NestingLevelVisitor()
    results = v.measure_module_functions(module)
    assert 'Inner.deep_meth' in results
    assert results['Inner.deep_meth'] == 1
    assert 'top_with_nested' in results
    assert results['top_with_nested'] == 1


def test_measure_module_functions_complex():
    """
    Комплексный пример с несколькими уровнями вложения и разными конструкциями.

    Что проверяется:
    - корректность набора ключей;
    - ожидаемые глубины для top, Parent.parent_meth, Child.child_meth и top_nested.
    """
    code = """
def top():
    if True:
        pass

class Parent:
    def parent_meth():
        with ctx:
            for i in range(10):
                pass

    class Child:
        def child_meth():
            try:
                raise
            except:
                pass

def top_nested():
    def inner():
        match val:
            case 1:
                pass
"""
    module = ast.parse(code)
    v = _NestingLevelVisitor()
    results = v.measure_module_functions(module)
    assert 'top' in results and results['top'] == 1
    assert 'Parent.parent_meth' in results and results['Parent.parent_meth'] == 2
    assert 'Child.child_meth' in results and results['Child.child_meth'] == 1
    assert 'top_nested' in results and results['top_nested'] == 1


def test_visit_asyncfunctiondef_invokes_generic_visit_and_traverses_body():
    """
    Прямой вызов visitor.visit(async_node) должен попасть в visit_AsyncFunctionDef,
    который возвращает generic_visit; generic_visit рекурсивно обходит тело.

    Что проверяется:
    - создаётся async def с вложенным if;
    - прямой v.visit(async_node) выполняет обход тела async-функции;
    - результат — max_level == 1 (if был обнаружен и обработан).

    Ожидаемый результат:
    v.max_level == 1 после вызова visit на AsyncFunctionDef узле.
    """
    code = """
async def afunc():
    if True:
        await something()
"""
    tree = ast.parse(code)
    async_node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
    v = _NestingLevelVisitor()
    v.visit(async_node)
    assert v.max_level == 1
