import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTableView, QProgressBar,
    QTextEdit, QGroupBox, QCheckBox, QScrollArea, QFileDialog,
    QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# Проверка наличия модулей ядра и корректности путей импорта
try:
    from core.scanner import AssetScanner, ScanResult
    from ui.models import FilesTableModel, AssetFilterProxyModel
except ImportError:
    print("[!] Ошибка импорта. Убедитесь, что запускаете скрипт из корня проекта.")
    sys.exit(1)


class ScanWorker(QThread):
    """
    Класс для выполнения операции сканирования в отдельном потоке выполнения.
    Использование QThread предотвращает блокировку основного потока GUI при интенсивном I/O.
    """
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(object)

    def __init__(self, target_path, exceptions):
        """
        Инициализация потока сканирования.

        :param target_path: Абсолютный путь к целевой директории для анализа.
        """
        super().__init__()
        self.target_path = target_path
        self.exceptions = exceptions

    def run(self):
        """
        Точка входа в логику фонового потока.
        Выполняет итеративный обход файловой системы и передает промежуточные результаты через сигналы.
        """
        try:
            self.log_signal.emit(f"Инициализация сканера для пути: {self.target_path}")
            scanner = AssetScanner(self.target_path)
            self.log_signal.emit(f"Режим сканирования: {scanner.mode}")

            count = 0
            for file_data in scanner.scan_generator():
                count += 1
                # Ограничение частоты обновления интерфейса для оптимизации производительности QEventLoop
                if count % 500 == 0:
                    self.status_signal.emit(f"Просканировано файлов: {count}...")
                    self.log_signal.emit(f"Найден файл: {file_data['rel_path']}/{file_data['file_name']}")

            result = scanner.get_result()
            self.finished_signal.emit(result)

        except Exception as e:
            self.log_signal.emit(f"[ОШИБКА]: {str(e)}")
            self.finished_signal.emit(None)


class MainWindow(QMainWindow):
    """
    Основной класс интерфейса приложения.
    Реализует управление жизненным циклом компонентов GUI и взаимодействие с бизнес-логикой.
    """
    def __init__(self):
        """Инициализация главного окна и конфигурация графических компонентов."""
        super().__init__()
        self.setWindowTitle("Stalker Texture Intelligence Analyzer & Optimizer")
        self.resize(1000, 700)

        self.config = {
            "max_top_tokens": 20,
            "default_exceptions": "ui, sky, map, intro"
        }

        self.files_model = FilesTableModel()

        self.proxy_model = AssetFilterProxyModel()
        self.proxy_model.setSourceModel(self.files_model)

        self.current_top_tokens = set()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)

        self._setup_top_panel()
        self._setup_filters_panel()
        self._setup_table_panel()
        self._setup_bottom_panel()

        self.scan_worker = None

    def _setup_top_panel(self):
        """Конфигурация верхней панели управления (ввод параметров и запуск)."""
        top_layout = QHBoxLayout()

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Исключения (токены через запятую):"))
        self.exceptions_input = QLineEdit()
        self.exceptions_input.setText("ui, sky, map, intro")
        left_layout.addWidget(self.exceptions_input)
        left_layout.addStretch()

        right_layout = QVBoxLayout()
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Путь к папке mods или gamedata...")

        self.btn_browse = QPushButton("Обзор...")
        self.btn_browse.clicked.connect(self.browse_folder)

        path_layout.addWidget(self.path_input)
        path_layout.addWidget(self.btn_browse)

        self.btn_scan = QPushButton("SCAN")
        self.btn_scan.setMinimumHeight(40)
        self.btn_scan.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.btn_scan.clicked.connect(self.start_scan)

        right_layout.addLayout(path_layout)
        right_layout.addWidget(self.btn_scan)

        top_layout.addLayout(left_layout, stretch=1)
        top_layout.addLayout(right_layout, stretch=2)
        self.main_layout.addLayout(top_layout)

    def _setup_filters_panel(self):
        """Инициализация области динамических фильтров на базе QScrollArea."""
        self.filters_group = QGroupBox("Топ категорий (Будет заполнено после сканирования)")
        self.filters_group.setMinimumHeight(120)
        self.filters_group.setMaximumHeight(150)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self.scroll_content = QWidget()
        self.filters_layout = QGridLayout(self.scroll_content)
        self.filters_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(self.scroll_content)

        group_layout = QVBoxLayout(self.filters_group)
        group_layout.setContentsMargins(0, 5, 0, 0)
        group_layout.addWidget(scroll)

        self.main_layout.addWidget(self.filters_group)

    def _setup_table_panel(self):
        """Настройка основного компонента отображения данных сканирования."""
        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)

        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(True)

        self.main_layout.addWidget(self.table_view, stretch=1)

    def _setup_bottom_panel(self):
        """Формирование статус-бара и панели логирования."""
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.main_layout.addWidget(self.progress_bar)

        status_layout = QHBoxLayout()
        self.lbl_status = QLabel("Статус: Готов к работе.")
        self.btn_toggle_log = QPushButton("Показать лог ▼")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.clicked.connect(self.toggle_log)

        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch()
        status_layout.addWidget(self.btn_toggle_log)
        self.main_layout.addLayout(status_layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        self.log_output.hide()
        self.main_layout.addWidget(self.log_output)

    def toggle_log(self, checked):
        """Управление видимостью консоли логов."""
        if checked:
            self.log_output.show()
            self.btn_toggle_log.setText("Скрыть лог ▲")
        else:
            self.log_output.hide()
            self.btn_toggle_log.setText("Показать лог ▼")

    def browse_folder(self):
        """Вызов системного диалога выбора директории."""
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сканирования")
        if folder:
            self.path_input.setText(folder)

    def add_log(self, message):
        """
        Запись информационного сообщения в консоль вывода.

        :param message: Текстовая строка для отображения.
        """
        self.log_output.append(message)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def start_scan(self):
        """
        Запуск процесса асинхронного сканирования.
        Выполняет предварительную валидацию пути и переводит UI в состояние ожидания.
        """
        target_path = self.path_input.text().strip()
        if not target_path or not os.path.exists(target_path):
            self.add_log("[!] Ошибка: Укажите корректный путь.")
            return

        self.btn_scan.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.path_input.setEnabled(False)

        # Перевод QProgressBar в неопределенное состояние для визуализации активности
        self.progress_bar.setRange(0, 0)
        self.lbl_status.setText("Статус: Сканирование...")
        self.log_output.clear()

        self._clear_filters()

        exceptions = {e.strip() for e in self.exceptions_input.text().split(',') if e.strip()}

        self.scan_worker = ScanWorker(target_path, exceptions)
        self.scan_worker.log_signal.connect(self.add_log)
        self.scan_worker.status_signal.connect(self.lbl_status.setText)
        self.scan_worker.finished_signal.connect(self.on_scan_finished)
        self.scan_worker.start()

    def _clear_filters(self):
        """Очистка контейнера динамических фильтров от существующих виджетов."""
        while self.filters_layout.count():
            item = self.filters_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def on_scan_finished(self, result: ScanResult):
        """
        Обработка результата сканирования при завершении фонового потока.
        Восстанавливает интерактивность UI и инициализирует обновление табличных данных.

        :param result: Объект ScanResult с агрегированными данными.
        """
        self.btn_scan.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.path_input.setEnabled(True)

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        if result is None:
            self.lbl_status.setText("Статус: Ошибка сканирования.")
            return

        self.files_model.update_data(result.files)
        self.table_view.resizeColumnsToContents()

        summary = result.summary
        self.lbl_status.setText(f"Статус: Завершено. Файлов: {summary['count']} | Вес: {summary['total_size_mb']} МБ | Время: {summary['time_sec']} с.")
        self.add_log("=== СКАНИРОВАНИЕ ЗАВЕРШЕНО ===")

        self._populate_filters(result.token_stats)

    def _populate_filters(self, token_stats):
        """
        Инициализирует графические компоненты фильтрации на основе статистических данных.
        Динамически формирует сетку чекбоксов для наиболее ресурсоемких категорий (токенов).

        :param token_stats: Статистика распределения веса ресурсов по токенам.
        """
        self.current_top_tokens.clear()
        sorted_tokens = sorted(token_stats.items(), key=lambda x: x[1]['total_size_mb'], reverse=True)

        max_columns = 5
        row, col = 0, 0
        limit = self.config.get("max_top_tokens", 25)

        for token, stats in sorted_tokens[:limit]:
            self.current_top_tokens.add(token)

            cb_text = f"{token} ({stats['total_size_mb']:.1f} MB)"
            cb = QCheckBox(cb_text)

            exceptions = [e.strip() for e in self.exceptions_input.text().split(',')]

            if token in exceptions:
                cb.setChecked(False)
                # cb.setEnabled(False) # Опциональная блокировка изменения состояния исключенных категорий
            else:
                cb.setChecked(True)

            cb.toggled.connect(self.apply_filters)

            self.filters_layout.addWidget(cb, row, col)
            col += 1
            if col >= max_columns:
                col = 0
                row += 1

        self.cb_others = QCheckBox("OTHERS (Разное)")
        self.cb_others.setChecked(True)
        self.cb_others.toggled.connect(self.apply_filters)
        self.filters_layout.addWidget(self.cb_others, row, col)

        self.apply_filters()

    def get_selected_tokens(self):
        """
        Выполняет обход виджетов в слое фильтров и формирует список активных токенов.

        :return: Список строковых идентификаторов выбранных токенов.
        """
        selected = []
        for i in range(self.filters_layout.count()):
            item = self.filters_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, QCheckBox) and widget.isChecked():
                token = widget.text().split(' ')[0]
                selected.append(token)
        return selected

    def apply_filters(self):
        """
        Агрегирует состояние элементов управления интерфейса и обновляет параметры прокси-модели.
        Синхронизирует выбор пользователя с логикой фильтрации QSortFilterProxyModel.
        """
        selected = set()
        for i in range(self.filters_layout.count()):
            w = self.filters_layout.itemAt(i).widget()
            if isinstance(w, QCheckBox) and w != getattr(self, 'cb_others', None):
                if w.isChecked():
                    token = w.text().split(' ')[0]
                    selected.add(token)

        forbidden = {e.strip() for e in self.exceptions_input.text().split(',') if e.strip()}

        self.proxy_model.set_filter_params(
            selected_tokens=selected,
            show_others=self.cb_others.isChecked(),
            top_tokens_list=self.current_top_tokens,
            forbidden_tokens=forbidden
        )