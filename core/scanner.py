import os
import struct
import time
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Generator, Any

# Соответствие идентификаторов DXGI_FORMAT их строковым представлениям
DXGI_FORMAT_MAP = {
    71: "BC1_UNORM", 74: "BC2_UNORM", 77: "BC3_UNORM",
    80: "BC4_UNORM", 83: "BC5_UNORM", 95: "BC6H_UF16",
    98: "BC7_UNORM"
}

@dataclass
class ScanResult:
    """
    Контейнер для хранения агрегированных результатов сканирования ресурсов.

    :ivar summary: Общая статистическая информация (количество, объем, время выполнения).
    :ivar token_stats: Статистические данные распределения веса по категориям (токенам).
    :ivar files: Список метаданных всех обработанных файлов.
    """
    summary: dict[str, Any] = field(default_factory=dict)
    token_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: list[dict[str, Any]] = field(default_factory=list)


class AssetScanner:
    """
    Обеспечивает рекурсивное сканирование файловой системы для анализа DDS-ресурсов
    и извлечения технических метаданных из их заголовков.
    """
    # Пре-компиляция регулярного выражения для минимизации накладных расходов при массовой токенизации
    _TOKEN_PATTERN = re.compile(r'[a-z0-9а-яё]+')

    # Использование множества (set) для обеспечения константной сложности поиска O(1)
    IGNORE_TOKENS = {'gamedata', 'textures', 'dds'}

    def __init__(self, target_path: str | Path):
        """
        Инициализация сканера.

        :param target_path: Базовый путь для начала сканирования.
        """
        self.target_path = Path(target_path).resolve()
        self.mode = self._detect_mode()

        self._stats = {"count": 0, "total_size_mb": 0.0, "time_sec": 0.0}
        self._token_stats: dict[str, dict[str, float | int]] = {}
        self._files: list[dict[str, Any]] = []

    def _detect_mode(self) -> str:
        """
        Определение типа структуры целевой директории (MO2, Single Mod или RAW).

        :return: Строковой идентификатор режима работы.
        """
        if not self.target_path.is_dir():
            return "RAW"

        if (self.target_path / 'gamedata' / 'textures').exists():
            return "SINGLE"

        try:
            for child in self.target_path.iterdir():
                if child.is_dir() and (child / 'gamedata' / 'textures').exists():
                    return "MO2"
        except PermissionError:
            pass

        return "RAW"

    @staticmethod
    def parse_dds_header(file_path: Path) -> dict[str, int | str] | None:
        """
        Выполняет парсинг бинарного заголовка DDS без полной десериализации файла.

        :param file_path: Путь к DDS-файлу.
        :return: Словарь с параметрами изображения или None, если файл не является валидным DDS.
        """
        try:
            with open(file_path, 'rb') as f:
                data = f.read(128)
                if len(data) < 128 or data[:4] != b'DDS ':
                    return None

                # Смещения согласно спецификации DirectDraw Surface: Height (12), Width (16)
                height, width = struct.unpack_from('<II', data, 12)

                # MipMapCount располагается по смещению 28
                mipmap_count = struct.unpack_from('<I', data, 28)[0]

                # Извлечение FourCC для определения формата сжатия (смещение 84)
                fourcc = data[84:88]

                if fourcc == b'DX10':
                    # Чтение расширенного заголовка DX10 (20 байт) для современных форматов сжатия
                    dx10_data = f.read(20)
                    if len(dx10_data) == 20:
                        dxgi_format = struct.unpack_from('<I', dx10_data, 0)[0]
                        fmt = DXGI_FORMAT_MAP.get(dxgi_format, f"DXGI_{dxgi_format}")
                    else:
                        fmt = "DX10_ERR"
                elif fourcc == b'\x00\x00\x00\x00':
                    # Обработка несжатых форматов на основе RGBBitCount (смещение 88)
                    rgb_bits = struct.unpack_from('<I', data, 88)[0]
                    fmt = f"RAW_{rgb_bits}BPP"
                else:
                    try:
                        fmt = fourcc.decode('ascii').replace('\x00', '')
                    except UnicodeDecodeError:
                        fmt = "UNKNOWN"

                return {
                    "width": width,
                    "height": height,
                    "mipmaps": mipmap_count,
                    "format": fmt
                }
        except Exception:
            return None

    def _tokenize(self, text: str) -> list[str]:
        """
        Анализирует строку и извлекает уникальные значимые токены для категоризации.

        :param text: Входная строка для анализа.
        :return: Список нормализованных уникальных токенов.
        """
        text_lc = text.lower()

        tokens = {
            token for token in self._TOKEN_PATTERN.findall(text_lc)
            if len(token) >= 2 and token not in self.IGNORE_TOKENS and not token.isdigit()
        }

        return list(tokens)

    def _resolve_paths_and_mod(self, file_path: Path) -> tuple[str, str]:
        """
        Вычисляет принадлежность файла к конкретной модификации и определяет его относительный путь.

        :param file_path: Полный путь к файлу.
        :return: Кортеж (имя_мода, относительный_путь).
        """
        rel_to_target = file_path.relative_to(self.target_path)
        parts = rel_to_target.parts

        mod_name = "Root"
        rel_path_str = str(file_path.parent)

        if self.mode == "MO2":
            if len(parts) > 0:
                mod_name = parts[0]
            try:
                tex_idx = parts.index('textures')
                rel_path_str = str(Path(*parts[tex_idx+1:-1])) if len(parts) - 1 > tex_idx else ""
            except ValueError:
                rel_path_str = str(file_path.parent.relative_to(self.target_path))

        elif self.mode == "SINGLE":
            mod_name = self.target_path.name
            try:
                tex_idx = parts.index('textures')
                rel_path_str = str(Path(*parts[tex_idx+1:-1])) if len(parts) - 1 > tex_idx else ""
            except ValueError:
                rel_path_str = str(file_path.parent.relative_to(self.target_path))

        else: # RAW
            rel_path_str = str(file_path.parent.relative_to(self.target_path))

        if rel_path_str == ".":
            rel_path_str = ""

        return mod_name, rel_path_str.replace('\\', '/')

    def scan_generator(self) -> Generator[dict[str, Any], None, None]:
        """
        Выполняет итеративное сканирование файловой структуры.
        Использование генератора позволяет обрабатывать данные без блокировки вызывающего потока.

        :yield: Словарь с результатами анализа текущего файла.
        """
        start_time = time.time()

        for root, _, files in os.walk(self.target_path):
            for file in files:
                if not file.lower().endswith('.dds'):
                    continue

                file_path = Path(root) / file
                header_info = self.parse_dds_header(file_path)

                if not header_info:
                    continue

                size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 4)
                mod_name, rel_path = self._resolve_paths_and_mod(file_path)

                tokens = self._tokenize(f"{rel_path}/{file_path.stem}")

                file_data = {
                    "mod_name": mod_name,
                    "full_path": str(file_path),
                    "rel_path": rel_path,
                    "file_name": file.lower(),
                    "size_mb": size_mb,
                    "width": header_info["width"],
                    "height": header_info["height"],
                    "format": header_info["format"],
                    "tokens": tokens
                }

                self._stats["count"] += 1
                self._stats["total_size_mb"] += size_mb
                self._files.append(file_data)

                for token in tokens:
                    if token not in self._token_stats:
                        self._token_stats[token] = {"count": 0, "total_size_mb": 0.0}
                    self._token_stats[token]["count"] += 1
                    self._token_stats[token]["total_size_mb"] += size_mb

                yield file_data

        self._stats["total_size_mb"] = round(self._stats["total_size_mb"], 2)
        self._stats["time_sec"] = round(time.time() - start_time, 2)

        for t in self._token_stats:
            self._token_stats[t]["total_size_mb"] = round(self._token_stats[t]["total_size_mb"], 4)

    def get_result(self) -> ScanResult:
        """
        Формирует итоговый объект ScanResult на основе собранных данных.

        :return: Экземпляр ScanResult с полным набором статистических данных.
        """
        return ScanResult(
            summary=self._stats,
            token_stats=self._token_stats,
            files=self._files
        )