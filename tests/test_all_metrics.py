import pytest
import tempfile
from stats_code_analyser.src.stats_code_analyser.static_analyser import StaticCodeAnalyser


# Фикстура pytest для создания временного Python-файла.
# Используется в тестах для передачи кода в StaticCodeAnalyser
@pytest.fixture
def temp_py_file():
    def _create(content):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.py') as f:
            f.write(content.encode('utf-8'))
            return f.name

    yield _create
    # Временные файлы автоматически очищаются системой


# Тест: обработка некорректного синтаксиса
def test_invalid_syntax(temp_py_file):
    content = "def : pass"  # Явно неверный синтаксис
    fname = temp_py_file(content)
    with pytest.raises(ValueError):
        StaticCodeAnalyser(fname)


# Тест: модуль без классов
def test_no_classes(temp_py_file):
    content = """
# Глобальный комментарий
def global_func():
    pass
"""
    fname = temp_py_file(content)
    analyser = StaticCodeAnalyser(fname)

    # Все метрики должны вернуть пустые словари
    metric_functions = [
        analyser.lcom4,
        analyser.tcc,
        analyser.lcc,
        analyser.max_cognitive_per_class,
        analyser.avg_cognitive_per_class,
        analyser.total_cognitive_per_class,
        analyser.sloc_per_class,
        analyser.max_method_sloc_per_class,
        analyser.avg_method_sloc_per_class,
        analyser.max_halstead_difficulty_per_class,
        analyser.max_halstead_effort_per_class,
        analyser.avg_halstead_difficulty_per_class,
        analyser.avg_halstead_effort_per_class,
        analyser.number_of_methods_per_class,
        analyser.min_code_to_comment_ratio_per_class,
        analyser.avg_code_to_comment_ratio_per_class,
        analyser.response_for_class,
        analyser.max_nesting_level_per_class,
    ]

    for func in metric_functions:
        result = func()
        assert result == {}, f"Ожидался пустой словарь для {func.__name__}"


# Тест: пустой модуль (проверка работы кеша Halstead)
def test_empty_module(temp_py_file):
    content = ""  # Пустой файл
    fname = temp_py_file(content)
    analyser = StaticCodeAnalyser(fname)

    # Все метрики должны вернуть пустые словари
    metric_functions = [
        analyser.lcom4,
        analyser.tcc,
        analyser.lcc,
        analyser.max_cognitive_per_class,
        analyser.avg_cognitive_per_class,
        analyser.total_cognitive_per_class,
        analyser.sloc_per_class,
        analyser.max_method_sloc_per_class,
        analyser.avg_method_sloc_per_class,
        analyser.max_halstead_difficulty_per_class,
        analyser.max_halstead_effort_per_class,
        analyser.avg_halstead_difficulty_per_class,
        analyser.avg_halstead_effort_per_class,
        analyser.number_of_methods_per_class,
        analyser.min_code_to_comment_ratio_per_class,
        analyser.avg_code_to_comment_ratio_per_class,
        analyser.response_for_class,
        analyser.max_nesting_level_per_class,
    ]

    for func in metric_functions:
        result = func()
        assert result == {}, f"Ожидался пустой словарь для {func.__name__}"

    # Проверка: в кеше Halstead добавляется ключ "global"
    halstead = analyser._compute_all_halstead()
    assert "global" in halstead
    assert halstead["global"] == (0.0, 0.0, 0.0)


# Тест: обработка ситуации, когда end_lineno = None
def test_node_loc_with_end_lineno_none(temp_py_file):
    content = """
class TestClass:
    pass
"""
    fname = temp_py_file(content)
    analyser = StaticCodeAnalyser(fname)

    # Получаем AST-узел класса
    class_node = analyser._class_nodes()[0]

    # Сохраняем оригинал и обнуляем end_lineno
    original_end_lineno = class_node.end_lineno
    class_node.end_lineno = None

    # Вызываем метрику, которая использует _node_loc
    sloc = analyser.sloc_per_class()

    # Восстанавливаем end_lineno
    class_node.end_lineno = original_end_lineno

    class_key = 'class:TestClass'
    assert class_key in sloc
    assert sloc[class_key] >= 0  # Проверяем, что ветка обработана


# Тест: класс без методов
def test_simple_class_no_methods(temp_py_file):
    content = """
class Simple:
    \"\"\"Докстринг класса\"\"\"

    field = 1  # Поле с комментарием
"""
    fname = temp_py_file(content)
    analyser = StaticCodeAnalyser(fname)

    metric_functions = [
        analyser.lcom4,
        analyser.tcc,
        analyser.lcc,
        analyser.max_cognitive_per_class,
        analyser.avg_cognitive_per_class,
        analyser.total_cognitive_per_class,
        analyser.sloc_per_class,
        analyser.max_method_sloc_per_class,
        analyser.avg_method_sloc_per_class,
        analyser.max_halstead_difficulty_per_class,
        analyser.max_halstead_effort_per_class,
        analyser.avg_halstead_difficulty_per_class,
        analyser.avg_halstead_effort_per_class,
        analyser.number_of_methods_per_class,
        analyser.min_code_to_comment_ratio_per_class,
        analyser.avg_code_to_comment_ratio_per_class,
        analyser.response_for_class,
        analyser.max_nesting_level_per_class,
    ]

    class_key = 'class:Simple'
    for func in metric_functions:
        result = func()
        assert list(result.keys()) == [class_key]
        value = result[class_key]
        assert isinstance(value, (int, float))
        # Для класса без методов почти всё 0, кроме SLOC
        if func.__name__ != 'sloc_per_class':
            assert value == 0 or value == 0.0, f"Неожиданное значение {func.__name__}: {value}"

    # SLOC > 0 (строка с class + поле)
    assert analyser.sloc_per_class()[class_key] > 0


# Тест: сложный класс с методами, циклами, комментариями и async
def test_complex_class(temp_py_file):
    content = '''
class Complex:
    """Докстринг класса"""

    field = 10  # Поле

    def __init__(self):
        """Докстринг конструктора"""
        self.field = self.field + 1  # Halstead
        # Только комментарий

        self.field -= 2  # Инлайн-комментарий
        pass  # Ещё одна строка кода

    def method1(self):
        x = 1 * 2 / 3 - 4  # Halstead операторы/операнды
        if x > 0:  # Когнитивная сложность + вложенность
            while True:
                for i in range(5):
                    if i == 2:
                        print(i)
        return x

    def method2(self):
        return self.method1()  # RFC и связность

    async def async_method(self):
        """Докстринг async"""
        await asyncio.sleep(1)  # Асинхронный вызов
        return self.field  # Доступ к полю
'''
    fname = temp_py_file(content)
    analyser = StaticCodeAnalyser(fname)

    class_key = 'class:Complex'

    # Проверяем все метрики для сложного класса
    lcom4 = analyser.lcom4()
    assert class_key in lcom4 and isinstance(lcom4[class_key], int) and lcom4[class_key] > 0

    tcc = analyser.tcc()
    assert class_key in tcc and isinstance(tcc[class_key], float)

    lcc = analyser.lcc()
    assert class_key in lcc and isinstance(lcc[class_key], float)

    max_cog = analyser.max_cognitive_per_class()
    assert class_key in max_cog and isinstance(max_cog[class_key], int) and max_cog[class_key] > 0  # if/while/for

    avg_cog = analyser.avg_cognitive_per_class()
    assert class_key in avg_cog and isinstance(avg_cog[class_key], float)

    total_cog = analyser.total_cognitive_per_class()
    assert class_key in total_cog and isinstance(total_cog[class_key], int) and total_cog[class_key] > 0

    sloc = analyser.sloc_per_class()
    assert class_key in sloc and isinstance(sloc[class_key], int) and sloc[class_key] > 0

    max_method_sloc = analyser.max_method_sloc_per_class()
    assert class_key in max_method_sloc and isinstance(max_method_sloc[class_key], int) and max_method_sloc[
        class_key] > 0

    avg_method_sloc = analyser.avg_method_sloc_per_class()
    assert class_key in avg_method_sloc and isinstance(avg_method_sloc[class_key], float) and avg_method_sloc[
        class_key] > 0

    max_hal_diff = analyser.max_halstead_difficulty_per_class()
    assert class_key in max_hal_diff and isinstance(max_hal_diff[class_key], float) and max_hal_diff[class_key] > 0

    max_hal_eff = analyser.max_halstead_effort_per_class()
    assert class_key in max_hal_eff and isinstance(max_hal_eff[class_key], float) and max_hal_eff[class_key] > 0

    avg_hal_diff = analyser.avg_halstead_difficulty_per_class()
    assert class_key in avg_hal_diff and isinstance(avg_hal_diff[class_key], float)

    avg_hal_eff = analyser.avg_halstead_effort_per_class()
    assert class_key in avg_hal_eff and isinstance(avg_hal_eff[class_key], float)

    num_methods = analyser.number_of_methods_per_class()
    assert class_key in num_methods and num_methods[class_key] == 4  # __init__, method1, method2, async_method

    min_code_comment = analyser.min_code_to_comment_ratio_per_class()
    assert class_key in min_code_comment and isinstance(min_code_comment[class_key], float)

    avg_code_comment = analyser.avg_code_to_comment_ratio_per_class()
    assert class_key in avg_code_comment and isinstance(avg_code_comment[class_key], float)

    rfc = analyser.response_for_class()
    assert class_key in rfc and isinstance(rfc[class_key], int) and rfc[class_key] > 1  # Есть вызовы

    max_nest = analyser.max_nesting_level_per_class()
    assert class_key in max_nest and isinstance(max_nest[class_key], int) and max_nest[
        class_key] >= 4  # if-while-for-if
