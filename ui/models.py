import typing
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel


class FilesTableModel(QAbstractTableModel):
    """
    Высокопроизводительная модель для отображения списка файлов (словарей) в QTableView.
    Оптимизирована для работы с объемами от 10 000 до 100 000 записей за счет
    генерации отображаемых данных "на лету" и использования эффективной встроенной сортировки.
    """

    def __init__(self, data: typing.Optional[typing.List[dict]] = None, parent=None):
        super().__init__(parent)
        self._data = data if data is not None else []

        # Конфигурация колонок:
        # (Название колонки, Функция извлечения/форматирования для DisplayRole, Функция генерации ключа для сортировки)
        # Использование функций-генераторов ключей позволяет быстро сортировать числа как числа, а не как строки.
        self._columns = (
            (
                "Файл",
                lambda x: x.get("file_name", ""),
                lambda x: x.get("file_name", "")
            ),
            (
                "Разрешение",
                lambda x: f'{x.get("width", 0)} x {x.get("height", 0)}',
                lambda x: (x.get("width", 0), x.get("height", 0))  # Сортировка по ширине, затем по высоте
            ),
            (
                "Формат",
                lambda x: x.get("format", ""),
                lambda x: x.get("format", "")
            ),
            (
                "Размер, МБ",
                lambda x: f'{x.get("size_mb", 0.0):.1f}',
                lambda x: x.get("size_mb", 0.0)  # Сортировка по float, обеспечивает корректную числовую сортировку
            ),
            (
                "Мод",
                lambda x: x.get("mod_name", ""),
                lambda x: x.get("mod_name", "")
            ),
            (
                "Путь",
                lambda x: x.get("rel_path", ""),
                lambda x: x.get("rel_path", "")
            )
        )

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Возвращает количество строк в таблице."""
        if parent.isValid():
            return 0
        return len(self._data)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Возвращает количество колонок на основе конфигурации."""
        if parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> typing.Any:
        """Предоставляет данные для отображения и стилизации в QTableView."""
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        # Проверка выхода за границы списка
        if not (0 <= row < len(self._data)) or not (0 <= col < len(self._columns)):
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            item = self._data[row]
            display_func = self._columns[col][1]
            return display_func(item)

        # Отдаем данные для СОРТИРОВКИ (чтобы прокси-модель знала правду)
        if role == Qt.ItemDataRole.UserRole:
            item = self._data[row]
            sort_key_func = self._columns[col][2] # Наша лямбда-функция из конфига колонок
            return sort_key_func(item)

        # Опционально: выравнивание чисел (Разрешение и Размер) по правому краю для лучшей читаемости
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (1, 3):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> typing.Any:
        """Устанавливает заголовки колонок таблицы."""
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self._columns):
                return self._columns[section][0]
        return None

    # def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
    #     """
    #     Реализация быстрой сортировки (Timsort) при клике на заголовок колонки.
    #     Эффективно обрабатывает списки словарей до 100k+ записей за счет C-оптимизации Python.
    #     """
    #     if not (0 <= column < len(self._columns)):
    #         return

    #     # Оповещаем представление о том, что структура (порядок) данных изменится
    #     self.layoutAboutToBeChanged.emit()

    #     sort_key_func = self._columns[column][2]
    #     is_reverse = (order == Qt.SortOrder.DescendingOrder)

    #     # Выполняем сортировку in-place
    #     self._data.sort(key=sort_key_func, reverse=is_reverse)

    #     # Оповещаем представление об успешном завершении сортировки
    #     self.layoutChanged.emit()

    def update_data(self, new_data: typing.List[dict]) -> None:
        """
        Заменяет текущий набор данных на новый и корректно обновляет QTableView.
        Использование beginResetModel() и endResetModel() необходимо для полного обновления структуры.
        """
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()

class AssetFilterProxyModel(QSortFilterProxyModel):
    """
    Прокси-модель для фильтрации данных ресурсов на основе сопоставления токенов.
    Обеспечивает динамическое управление видимостью строк в QTableView без модификации основной модели.
    """
    def __init__(self, parent=None):
        """
        Инициализация параметров фильтрации.

        :param parent: Родительский объект QObject.
        """
        super().__init__(parent)
        self.selected_tokens = set()
        self.show_others = True
        self.top_tokens_list = set()
        self.forbidden_tokens = set()

        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(True)

    def set_filter_params(self, selected_tokens, show_others, top_tokens_list, forbidden_tokens):
        """
        Обновляет критерии фильтрации и инициирует обновление представления.

        :param selected_tokens: Набор токенов, активных в интерфейсе (выбранные чекбоксы).
        :param show_others: Флаг отображения ресурсов, не имеющих вхождений в top_tokens_list.
        :param top_tokens_list: Полный перечень токенов, выведенных в панель категорий.
        """
        self.selected_tokens = selected_tokens
        self.show_others = show_others
        self.top_tokens_list = top_tokens_list
        self.forbidden_tokens = forbidden_tokens
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if not (0 <= source_row < len(model._data)):
            return False

        file_data = model._data[source_row]
        file_tokens = set(file_data.get("tokens", []))

        # Подготавливаем строку пути для проверки (все в нижнем регистре)
        full_path_str = f"{file_data.get('rel_path', '')}/{file_data.get('file_name', '')}".lower()

        # 1. АБСОЛЮТНЫЙ БАН (Исключения)
        if self.forbidden_tokens:
            # Проверяем, есть ли хоть одно запрещенное слово в пути файла
            for forbidden in self.forbidden_tokens:
                if forbidden in full_path_str:
                    return False

        # 2. ФИЛЬТРАЦИЯ ТОПА (Снятые галочки)
        unselected_top = self.top_tokens_list - self.selected_tokens
        if unselected_top:
            if not file_tokens.isdisjoint(unselected_top):
                return False

        # 3. РАЗРЕШЕНИЕ ПОКАЗА
        if self.selected_tokens and not file_tokens.isdisjoint(self.selected_tokens):
            return True

        is_others = file_tokens.isdisjoint(self.top_tokens_list)
        if is_others and self.show_others:
            return True

        return False

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        # Берем данные напрямую через UserRole, который мы прописали в модели
        left_data = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        right_data = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)

        # Если данные — кортежи (как в Разрешении) или числа (как в Размере)
        # Python сам сравнит их правильно: (2048, 2048) < (4096, 4096) или 1.2 < 10.5
        if left_data is not None and right_data is not None:
            return left_data < right_data

        # Если данных нет, используем стандартное поведение
        return super().lessThan(left, right)