# tests/test_rfc_metric.py
"""
Тесты для метода response_for_class() фасада StaticCodeAnalyser.

Назначение
---------
проверка RFC (Response For a Class) на реальных, практических примерах кода:
- классы без методов и с простыми методами;
- внутренние вызовы между методами одного класса;
- вызовы внешних (глобальных) функций;
- рекурсивные вызовы и циклы вызовов;
- асинхронные методы;
- несколько точек входа (методов) в классе;
- взаимодействие классов (пример MVC).

Особенности тестов
------------------
- Каждый тест использует реальный фрагмент Python-кода, отражающий типичные
  сценарии (getter, обработчик запросов, контроллер/модель, сервис с зависимостями).
- Во всех тестах создаётся временный файл 'temp.py' и удаляется после инициализации
  StaticCodeAnalyser, чтобы имитировать чтение реального модуля с диска.
- В каждом тесте даётся явное обоснование ожидаемого значения RFC:
  RFC класса = максимальное число уникальных квалифицированных методов/функций,
  достижимых из одного метода этого класса (включая сам стартовый метод).
"""

import os
from stats_code_analyser.static_analyser import StaticCodeAnalyser


def create_temp_file(code: str) -> str:
    """
    Создаёт временный файл temp.py с содержимым code.

    Возвращает имя файла. Тест обязан удалить файл после создания объекта
    StaticCodeAnalyser (файл используется только для инициализации анализатора).
    """
    filename = 'temp.py'
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(code)
    return filename


def test_response_for_class_no_classes():
    """
    Модуль без объявлений классов.

    Описание:
      - В модуле нет классов, значит метод response_for_class() должен вернуть
        пустой mapping: в нём нет ни одного класса для анализа.

    Ожидаемый результат:
      - {} — пустой словарь.
    """
    code = "x = 1"
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.response_for_class() == {}


def test_response_for_class_no_methods():
    """
    Класс без методов.

    Описание:
      - Класс объявлен, но внутри нет FunctionDef/AsyncFunctionDef.
      - Для такого класса рассматривается отсутствие методов => RFC = 0.

    Ожидаемый результат:
      - {'class:NoMethods': 0}
    """
    code = """
class NoMethods:
    pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.response_for_class() == {"class:NoMethods": 0}


def test_response_for_class_single_method_no_calls():
    """
    Класс с одним простым методом без вызовов.

    Описание:
      - Метод возвращает значение свойства, не делает вызовов других методов.
      - Граф вызовов содержит узел только для этого метода; достижимые узлы из
        него — только он сам. По определению RFC считает количество достижимых
        квалифицированных методов, включая стартовую вершину.

    Ожидаемый результат:
      - {'class:Single': 1}  (сам метод)
    """
    code = """
class Single:
    def get(self):
        return self.value
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.response_for_class() == {"class:Single": 1}


def test_response_for_class_with_internal_calls():
    """
    Методы с вызовами других методов того же класса.

    Описание:
      - handle() вызывает self.validate() и self.process().
      - граф вызовов (caller -> callees) для handle содержит ребра к validate и process.
      - достижимые вершины из handle: {handle, validate, process} => размер 3.
      - RFC класса = максимум достижимостей по всем его методам => 3.

    Ожидаемый результат:
      - RequestHandler -> 3
    """
    code = """
class RequestHandler:
    def handle(self):
        self.validate()
        self.process()

    def validate(self):
        pass  # validation logic

    def process(self):
        pass  # processing logic
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.response_for_class()["class:RequestHandler"] == 3  # handle reaches validate and process


def test_response_for_class_with_external_call():
    """
    Вызов внешней (глобальной) функции из метода класса.

    Описание:
      - global функция log_error доступна по квалифицированному имени 'function:log_error'.
      - метод handle_error вызывает log_error: достижимые из handle_error = {class:ErrorHandler.handle_error, function:log_error}.
      - RFC класса ErrorHandler = 2 (метод сам + внешняя функция).

    Ожидаемый результат:
      - ErrorHandler -> 2
    """
    code = """
def log_error(msg):
    print(msg)

class ErrorHandler:
    def handle_error(self):
        log_error("Error occurred")
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.response_for_class()["class:ErrorHandler"] == 2  # handle_error + log_error


def test_response_for_class_with_cycle():
    """
    Рекурсивный метод (вызов самого себя через self).

    Описание:
      - factorial вызывает self.factorial — это ребро на ту же самую квалифицированную вершину.
      - множество достижимых узлов содержит только эту вершину (уникальные), следовательно размер = 1.
      - Циклы/рекурсия не приводят к многократному учёту одной и той же функции.

    Ожидаемый результат:
      - Recursive -> 1
    """
    code = """
class Recursive:
    def factorial(self, n):
        if n <= 1:
            return 1
        return n * self.factorial(n - 1)
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.response_for_class()["class:Recursive"] == 1  # only itself, since cycle but same method


def test_response_for_class_multiple_classes_with_calls():
    """
    Взаимодействие нескольких классов: контроллер создаёт модель и вызывает её метод.

    Описание:
      - Model.save() — отдельный метод класса Model.
      - Controller.update() создаёт экземпляр Model и вызывает model.save().
      - collector разрешает вызов Class.method по имени конструктора (Model()) и attribute call -> 'class:Model.save'
      - достижимые из Controller.update: {class:Controller.update, class:Model.save} => размер 2.
      - Model без вызовов => RFC=1.

    Ожидаемый результат:
      - Model -> 1
      - Controller -> 2
    """
    code = """
class Model:
    def save(self):
        pass

class Controller:
    def update(self):
        model = Model()
        model.save()
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    rfc = analyser.response_for_class()
    assert rfc["class:Model"] == 1
    assert rfc["class:Controller"] == 2  # update + save (even though save is from another class)


def test_response_for_class_with_async_methods():
    """
    Асинхронные методы и await-вызовы внутри класса.

    Описание:
      - main() делает await self.step() — это разрешается как вызов метода того же класса.
      - достижимые из main: {class:AsyncService.main, class:AsyncService.step} => Размер 2.

    Ожидаемый результат:
      - AsyncService -> 2
    """
    code = """
class AsyncService:
    async def main(self):
        await self.step()

    async def step(self):
        pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.response_for_class()["class:AsyncService"] == 2


def test_response_for_class_with_multiple_entry_points():
    """
    Класс с несколькими методами-«точками входа», разной структурой вызовов.

    Описание:
      - a() вызывает b() и c(); b() вызывает d(); c() и d() — листовые.
      - достижимости:
          * из a: {a, b, c, d} -> 4
          * из b: {b, d} -> 2
          * из c: {c} -> 1
          * из d: {d} -> 1
          * из e: {e, c} -> 2
      - RFC класса = максимум размеров (из a => 4).

    Ожидаемый результат:
      - Multi -> 4
    """
    code = """
class Multi:
    def a(self):
        self.b()
        self.c()

    def b(self):
        self.d()

    def c(self):
        pass

    def d(self):
        pass

    def e(self):
        self.c()
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    os.remove(filename)
    assert analyser.response_for_class()["class:Multi"] == 4  # from a: a,b,c,d (max)


def test_combined_rfc_metrics_real_example():
    """
    Интеграционный пример: сервис вызывает локальные шаги и внешнюю функцию.

    Описание:
      - external_api_call() — глобальная функция.
      - Service.main() вызывает step1() и external_api_call().
      - step1() вызывает step2(); step2() — листовый метод.
      - достижимости из main: {main, step1, step2, function:external_api_call} => 4.
      - RFC(Service) = 4.

    Ожидаемый результат:
      - Service -> 4
    """
    code = """
def external_api_call():
    pass

class Service:
    def main(self):
        self.step1()
        external_api_call()

    def step1(self):
        self.step2()

    def step2(self):
        pass
"""
    filename = create_temp_file(code)
    analyser = StaticCodeAnalyser(filename)
    rfc = analyser.response_for_class()
    assert rfc["class:Service"] == 4  # main reaches step1, step2, external_api_call
    os.remove(filename)
