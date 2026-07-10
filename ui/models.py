import typing
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex


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

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """
        Реализация быстрой сортировки (Timsort) при клике на заголовок колонки.
        Эффективно обрабатывает списки словарей до 100k+ записей за счет C-оптимизации Python.
        """
        if not (0 <= column < len(self._columns)):
            return

        # Оповещаем представление о том, что структура (порядок) данных изменится
        self.layoutAboutToBeChanged.emit()

        sort_key_func = self._columns[column][2]
        is_reverse = (order == Qt.SortOrder.DescendingOrder)

        # Выполняем сортировку in-place
        self._data.sort(key=sort_key_func, reverse=is_reverse)

        # Оповещаем представление об успешном завершении сортировки
        self.layoutChanged.emit()

    def update_data(self, new_data: typing.List[dict]) -> None:
        """
        Заменяет текущий набор данных на новый и корректно обновляет QTableView.
        Использование beginResetModel() и endResetModel() необходимо для полного обновления структуры.
        """
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()