import sys
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow

def main():
    """
    Точка входа в приложение. Выполняет инициализацию графического окружения,
    конфигурацию базовых параметров интерфейса и запуск цикла обработки событий.
    """
    app = QApplication(sys.argv)

    # Использование стиля Fusion обеспечивает кроссплатформенное единообразие графического интерфейса.
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()