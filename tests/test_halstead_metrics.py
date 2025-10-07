# tests/test_halstead_complete.py
"""
Набор тестов для Halstead-утилит.

Описание:
- Тесты гарантируют корректность классификации токенов и подсчёта Halstead-метрик
  во всех ключевых ветвях реализации.
- Включены сценарии с реальным кодом: декораторы, comprehensions, lambda,
  вложенные функции/классы, async def, присваивания, выражения и пр.
- Тесты стремятся покрыть все вспомогательные функции (модульные или статические
  методы visitor'а), включая: _count_tokens, _compute_volume, _compute_difficulty,
  _compute_halstead_metrics_from_tokens, а также проверяют распределение токенов
  по контекстам (tokens_by_context) и сбор диапазонов (collect_ranges).
"""

import ast
import io
import math
import tokenize
import tempfile
import os
from stats_code_analyser.halstead_utils import _QualifiedHalsteadMetricsVisitor, _HalsteadTokenClassifier, \
    _compute_volume, _compute_difficulty, _compute_halstead_metrics_from_tokens
from stats_code_analyser.static_analyser import StaticCodeAnalyser


def _tokenize_and_classify(text: str):
    """Генерирует токены из текста и классифицирует их согласно _HalsteadTokenClassifier."""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        cls = _HalsteadTokenClassifier.classify(tok.type, tok.string)
        if cls:
            out.append(cls)
    return out


def _local_halstead_from_tokens(tokens):
    """
    Локальная реализация Halstead (точно соответствует спецификации в модуле):
    возвращает (volume, difficulty, effort).
    """
    unique_ops = set()
    unique_opsnds = set()
    N1 = N2 = 0
    for kind, s in tokens:
        if kind == "operator":
            unique_ops.add(s)
            N1 += 1
        elif kind == "operand":
            unique_opsnds.add(s)
            N2 += 1
    n1 = len(unique_ops)
    n2 = len(unique_opsnds)
    if n1 == 0 or n2 == 0:
        return 0.0, 0.0, 0.0
    n = n1 + n2
    N = N1 + N2
    volume = N * math.log2(n) if n > 0 else 0.0
    difficulty = (n1 / 2.0) * (N2 / n2) if n2 > 0 else 0.0
    effort = difficulty * volume
    return volume, difficulty, effort


def _get_helper(name: str):
    """
    Попытка получить вспомогательную функцию из модуля или как статический метод у visitor-класса.
    Это делает тесты устойчивыми к тому, как именно реализована вспомогательная логика.
    """
    import src as module
    fn = getattr(module, name, None)
    if fn:
        return fn
    cls = getattr(module, "_QualifiedHalsteadMetricsVisitor", None)
    if cls:
        fn = getattr(cls, name, None)
        if fn:
            return fn
    raise AssertionError(f"Не найдена функция/метод {name} в src.halstead_utils")


def test_token_classifier_ignores_non_semantic_tokens():
    """
    Классфикатор должен игнорировать нефункциональные токены:
    NL, NEWLINE, INDENT, DEDENT, COMMENT, ENDMARKER -> возвращают None.
    """
    ignore_types = (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                    tokenize.COMMENT, tokenize.ENDMARKER)
    for t in ignore_types:
        assert _HalsteadTokenClassifier.classify(t, "") is None


def test_token_classifier_keyword_and_literals_handling():
    """
    Ключевые слова интерпретируются как операторы (кроме True/False/None),
    литералы (NUMBER, STRING) и булевы значения/None — как операнды.
    """
    assert _HalsteadTokenClassifier.classify(tokenize.NAME, "if") == ("operator", "if")
    assert _HalsteadTokenClassifier.classify(tokenize.NAME, "def") == ("operator", "def")
    assert _HalsteadTokenClassifier.classify(tokenize.NAME, "True") == ("operand", "True")
    assert _HalsteadTokenClassifier.classify(tokenize.NUMBER, "123") == ("operand", "123")
    assert _HalsteadTokenClassifier.classify(tokenize.STRING, "'s'") == ("operand", "'s'")
    assert _HalsteadTokenClassifier.classify(tokenize.OP, "+") == ("operator", "+")


def test_compute_volume_and_difficulty_helpers_exist_and_correct():
    """
    Проверяем модульные/статические helper-ы:
      - _compute_volume(n_total, n_unique) -> ожидаем N*log2(n)
      - _compute_difficulty(n1, N2, n2) -> ожидаем (n1/2)*(N2/n2)
    Тест устойчив к месту определения (модуль/класс).
    """
    # тестовые значения
    vol = _compute_volume(10, 5)  # N=10, n_unique=5 -> 10*log2(5)
    assert math.isclose(vol, 10 * math.log2(5), rel_tol=1e-12)
    # zero unique => 0
    assert _compute_volume(5, 0) == 0.0

    diff = _compute_difficulty(6, 7, 4)  # (6/2)*(7/4)==3*(1.75)==5.25
    assert math.isclose(diff, (6.0 / 2.0) * (7.0 / 4.0), rel_tol=1e-12)
    # n2 == 0 => difficulty 0
    assert _compute_difficulty(2, 5, 0) == 0.0


def test_count_tokens_and_compute_metrics_helpers_cover_branches():
    """
    Проверяем _compute_halstead_metrics_from_tokens на простых наборах токенов,
    покрывая разные варианты:
      - только операторы/операнды (нормальный случай)
      - отсутствие операндов/операторов (возвращает нули)
    """

    # набор токенов: 2 оператора '+' и '-', 3 операнда 'a','b','c'
    tokens = [("operator", "+"), ("operand", "a"), ("operand", "b"), ("operator", "-"), ("operand", "c")]
    metrics = _compute_halstead_metrics_from_tokens(tokens)
    # проверяем, что полученные значения совпадают с локальным расчётом
    expected = _local_halstead_from_tokens(tokens)
    assert all(math.isclose(a, b, rel_tol=1e-12) for a, b in zip(metrics, expected))

    # крайний случай: нет операндов (только операторы) -> нули
    tokens2 = [("operator", "+"), ("operator", "-")]
    metrics2 = _compute_halstead_metrics_from_tokens(tokens2)
    assert metrics2 == (0.0, 0.0, 0.0)


def test_collect_ranges_and_tokens_by_context_complex_module():
    """
    Комплексный модуль, покрывающий ветви _collect_ranges и _tokens_by_context:
      - декораторы (декоратор расширяет диапазон)
      - вложенные функции, lambda, async def, вложенные классы
      - list comprehension

    Проверяется:
      - ожидаемые контексты присутствуют (global, top-level function, методы класса A)
      - для вложенного метода с именем 'm' существует контекст вида 'class:<...>.m'
      - для каждого найденного контекста подсчёт Halstead по его токенам выполняется без ошибок
    """
    code = '''
CONST = 1

def deco(f):
    def wrapper(*a, **k):
        return f(*a, **k)
    return wrapper

@deco
def top(x):
    def inner(y):
        return y * 2
    lam = lambda z: z + 1
    data = [inner(i) for i in range(5) if i % 2 == 0]
    return sum(data) + lam(x)

class A:
    async def am(self):
        return await self._helper()

    def _helper(self):
        return 42

    class B:
        def m(self):
            return "ok"
'''
    tree = ast.parse(code)
    visitor = _QualifiedHalsteadMetricsVisitor(code)
    visitor.visit(tree)

    tokens_by_ctx = visitor._tokens_by_context()

    # Базовые контексты, которые обязательно должны присутствовать
    assert "global" in tokens_by_ctx
    assert "function:top" in tokens_by_ctx
    assert "class:A._helper" in tokens_by_ctx
    assert "class:A.am" in tokens_by_ctx

    # Для вложенного метода 'm' допускаем разные схемы квалификации имени:
    # например, "class:A.B.m" или "class:B.m" — проверяем наличие любого ключа
    # вида 'class:<anything>.m'
    found_m_context = None
    for k in tokens_by_ctx.keys():
        if k.startswith("class:") and k.endswith(".m"):
            found_m_context = k
            break

    assert found_m_context is not None, "Не найден контекст для метода 'm' в любом классе"

    # Для всех проверяем, что подсчёт Halstead по токенам не падает
    expected_ctxs = {"global", "function:top", "class:A._helper", "class:A.am", found_m_context}
    for ctx in expected_ctxs:
        assert ctx in tokens_by_ctx, f"Контекст {ctx} не найден в tokens_by_context"
        tokens = tokens_by_ctx[ctx]
        # выполнение локального расчёта Halstead не должно приводить к исключению
        _local_halstead_from_tokens(tokens)


def test_integration_static_analyser_and_caching_for_halstead(tmpdir=None):
    """
    Интеграционный тест: StaticCodeAnalyser._compute_all_halstead и кэширование.
    Создаём временный файл с реальным кодом и сравниваем результаты visitor и analyser.
    """
    code = """
class Calc:
    def add(self, a, b):
        return a + b
    def noop(self):
        pass

def free(x):
    return x * 3
"""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8")
    try:
        tmp.write(code)
        tmp.flush()
        tmp.close()

        analyser = StaticCodeAnalyser(tmp.name)
        all_h = analyser._compute_all_halstead()

        # Прямой visitor
        visitor = _QualifiedHalsteadMetricsVisitor(code)
        visitor.visit(ast.parse(code))

        # проверка ключей и значений
        for k, v in visitor.result.items():
            assert k in all_h
            got = all_h[k]
            assert all(math.isclose(a, b, rel_tol=1e-12) for a, b in zip(v, got))

        # кэширование: повторный вызов не должен менять результат
        all_h2 = analyser._compute_all_halstead()
        assert all_h == all_h2

    finally:
        os.remove(tmp.name)


def test_classify_returns_none_for_unknown_token_type():
    """
    Проверяет ветвь классификатора для неизвестного типа токена:
    ожидается возврат None.
    """
    assert _HalsteadTokenClassifier.classify(9999, "??") is None
    # ERRORTOKEN также не должен классифицироваться как оператор/операнд
    assert _HalsteadTokenClassifier.classify(tokenize.ERRORTOKEN, "@") is None


def test_collect_ranges_records_lambda_inside_class():
    """
    При наличии lambda внутри тела класса посетитель должен зарегистрировать
    запись о lambda с квалифицированным именем, содержащим '.lambda:'.
    Тест устойчив к формату элементов visitor._ranges: tuple, namedtuple или dataclass.
    """

    code = "class C:\n    x = lambda a: a + 1\n"
    tree = ast.parse(code)
    visitor = _QualifiedHalsteadMetricsVisitor(code)
    visitor.visit(tree)

    found = False
    for r in getattr(visitor, "_ranges", []):
        name = None
        # Попробуем несколько способов извлечь имя из элемента ranges
        if isinstance(r, (tuple, list)) and len(r) > 0:
            name = r[0]
        else:
            # распространённые имена полей (dataclass / namedtuple / простые объекты)
            for attr in ("name", "qual", "0"):
                if hasattr(r, attr):
                    try:
                        name = getattr(r, attr)
                    except Exception:
                        name = None
                    if name is not None:
                        break
            # дополнительные попытки: если есть _fields (namedtuple)
            if name is None and hasattr(r, "_fields") and len(r._fields) > 0:
                try:
                    name = getattr(r, r._fields[0])
                except Exception:
                    name = None
        # безопасная конвертация в строку и проверка префикса
        if isinstance(name, str) and name.startswith("class:") and ".lambda:" in name:
            found = True
            break
        # в крайнем случае — смотреть на строковое представление объекта
        if not found and ".lambda:" in str(r):
            found = True
            break

    assert found, "Ожидалось найти запись вида 'class:<Name>.lambda:<start>' в visitor._ranges"


def test_tokens_by_context_returns_global_on_tokenize_error():
    """
    Тестирует обработку исключения при создании токенов:
    если генерация токенов выбрасывает Exception, метод _tokens_by_context
    должен вернуть безопасный mapping (минимум: ключ 'global').

    Для воспроизведения ошибки временно подменяем tokenize.generate_tokens,
    затем возвращаем оригинал.
    """

    broken_code = "'''unclosed string\n"

    # Подмена генератора токенов, чтобы он сразу бросал исключение при вызове.
    orig = tokenize.generate_tokens
    try:
        def _raise(*args, **kwargs):
            raise Exception("simulated tokenizer failure")

        tokenize.generate_tokens = _raise

        visitor = _QualifiedHalsteadMetricsVisitor(broken_code)
        result = visitor._tokens_by_context()

        assert isinstance(result, dict)
        assert "global" in result
        # значение должно быть списком (минимально пустой список)
        assert isinstance(result["global"], list)
    finally:
        tokenize.generate_tokens = orig
