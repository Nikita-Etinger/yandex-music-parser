from dataclasses import dataclass, field
from typing import Optional
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import os


@dataclass
class MyDriver:
    """
    ## Настройка драйвера Chrome для версии 143
    """
    driver: Optional[Chrome] = None
    options: Options = field(default_factory=Options)
    service: Optional[Service] = None

    def __post_init__(self) -> None:
        self._setup_options()
        self._create_driver()
        if self.driver:
            self.driver.maximize_window()

    def _setup_options(self) -> None:
        """Минимальные настройки для стабильной работы"""
        # Уберите все лишние опции для теста
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--no-sandbox')
        # УБЕРИТЕ все anti-detection опции на время теста

    def _create_driver(self) -> None:
        """Создание драйвера с конкретной версией"""
        try:
            print("Создание драйвера для Chrome 143...")

            # Способ 1: С явным указанием версии
            chrome_version = "143.0.7499.170"
            self.service = Service(ChromeDriverManager(version=chrome_version).install())

            # ИЛИ Способ 2: Используйте только мажорную версию
            # major_version = "143"
            # self.service = Service(ChromeDriverManager(version=major_version).install())

            # ИЛИ Способ 3: Ручной путь (после скачивания)
            # self.service = Service(r'C:\Users\ADMIN\PycharmProjects\yan_mus_parcer\chromedriver.exe')

            self.driver = Chrome(service=self.service, options=self.options)
            print("Драйвер успешно создан!")

        except Exception as e:
            print(f"Ошибка: {e}")
            print("\nПробуем альтернативные способы...")
            self._try_alternative_methods()

    def _try_alternative_methods(self) -> None:
        """Альтернативные методы создания драйвера"""
        methods = [
            self._method_use_chrome_type,
            self._method_use_major_version_only,
            self._method_use_manual_path,
            self._method_use_simple_service
        ]

        for i, method in enumerate(methods, 1):
            try:
                print(f"\nПопытка {i}: {method.__name__}")
                method()
                if self.driver:
                    print(f"Успех с методом {i}!")
                    return
            except Exception as e:
                print(f"Метод {i} не удался: {str(e)[:100]}")

        raise RuntimeError("Не удалось создать драйвер ни одним методом")

    def _method_use_chrome_type(self) -> None:
        """Использование chrome_type"""
        from webdriver_manager.core.os_manager import ChromeType
        self.service = Service(
            ChromeDriverManager(
                chrome_type=ChromeType.GOOGLE,
                version="143"
            ).install()
        )
        self.driver = Chrome(service=self.service, options=self.options)

    def _method_use_major_version_only(self) -> None:
        """Только мажорная версия"""
        self.service = Service(ChromeDriverManager(version="143").install())
        self.driver = Chrome(service=self.service, options=self.options)

    def _method_use_manual_path(self) -> None:
        """Ручной путь к драйверу"""
        # Предполагаем, что chromedriver.exe в папке проекта
        driver_path = os.path.join(os.path.dirname(__file__), 'chromedriver.exe')
        if not os.path.exists(driver_path):
            # Ищем в других возможных местах
            possible_paths = [
                'chromedriver.exe',
                './chromedriver.exe',
                '../chromedriver.exe',
                r'C:\Users\ADMIN\Downloads\chromedriver.exe',
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    driver_path = path
                    break

        self.service = Service(driver_path)
        self.driver = Chrome(service=self.service, options=self.options)

    def _method_use_simple_service(self) -> None:
        """Простейший метод - без Service"""
        # Этот метод работает, если chromedriver в PATH
        self.driver = Chrome(options=self.options)

    @property
    def get_driver(self) -> Chrome:
        if not self.driver:
            raise RuntimeError("Драйвер не создан")
        return self.driver

    def quit(self) -> None:
        if self.driver:
            self.driver.quit()