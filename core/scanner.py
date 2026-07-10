import os
import struct
import time
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Generator, Any

# Карта распространенных DX10 форматов (DXGI_FORMAT)
DXGI_FORMAT_MAP = {
    71: "BC1_UNORM", 74: "BC2_UNORM", 77: "BC3_UNORM",
    80: "BC4_UNORM", 83: "BC5_UNORM", 95: "BC6H_UF16",
    98: "BC7_UNORM"
}

@dataclass
class ScanResult:
    summary: dict[str, Any] = field(default_factory=dict)
    token_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: list[dict[str, Any]] = field(default_factory=list)


class AssetScanner:
    """
    Класс для рекурсивного сканирования ресурсов и извлечения метаданных из DDS файлов.
    """
    # Пре-компилированное регулярное выражение для ускорения токенизации.
    # Ищет последовательности букв (лат/кир) и цифр в нижнем регистре.
    _TOKEN_PATTERN = re.compile(r'[a-z0-9а-яё]+')

    # Набор исключений (set обеспечивает поиск за O(1))
    IGNORE_TOKENS = {'gamedata', 'textures', 'dds'}

    def __init__(self, target_path: str | Path):
        self.target_path = Path(target_path).resolve()
        self.mode = self._detect_mode()

        # Состояние сканирования
        self._stats = {"count": 0, "total_size_mb": 0.0, "time_sec": 0.0}
        self._token_stats: dict[str, dict[str, float | int]] = {}
        self._files: list[dict[str, Any]] = []

    def _detect_mode(self) -> str:
        """Автоматическое определение структуры папки (MO2, Single Mod, Raw)."""
        if not self.target_path.is_dir():
            return "RAW"

        # Проверка на Single Mod
        if (self.target_path / 'gamedata' / 'textures').exists():
            return "SINGLE"

        # Проверка на MO2 Mods (хотя бы одна подпапка содержит gamedata/textures)
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
        Чтение и парсинг заголовка DDS без загрузки всего файла.
        Исправлено: корректные смещения для Width, Height и MipMaps.
        """
        try:
            with open(file_path, 'rb') as f:
                data = f.read(128)
                if len(data) < 128 or data[:4] != b'DDS ':
                    return None

                # Height (12), Width (16)
                height, width = struct.unpack_from('<II', data, 12)

                # MipMapCount (28) — Pitch (20) и Depth (24) пропускаем
                mipmap_count = struct.unpack_from('<I', data, 28)[0]

                # PixelFormat -> FourCC (84)
                fourcc = data[84:88]

                if fourcc == b'DX10':
                    # Читаем расширенный заголовок DX10 (еще 20 байт после основного 128-байтного)
                    dx10_data = f.read(20)
                    if len(dx10_data) == 20:
                        dxgi_format = struct.unpack_from('<I', dx10_data, 0)[0]
                        fmt = DXGI_FORMAT_MAP.get(dxgi_format, f"DXGI_{dxgi_format}")
                    else:
                        fmt = "DX10_ERR"
                elif fourcc == b'\x00\x00\x00\x00':
                    # Для несжатых форматов смотрим RGBBitCount (смещение 88)
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
        Разбивает строку (путь или имя файла) на список уникальных ключевых слов.

        Процесс:
        1. Приведение всей строки к нижнему регистру.
        2. Извлечение слов через регулярное выражение.
        3. Фильтрация слишком коротких слов и технических терминов.
        4. Удаление дубликатов через set comprehension.

        :param text: Строка для анализа (например, 'act/act_stalker_bump').
        :return: Список очищенных токенов ['act', 'stalker', 'bump'].
        """
        # Приводим к нижнему регистру один раз для всей строки
        text_lc = text.lower()

        # Находим все совпадения, фильтруем и убираем дубликаты за один проход
        tokens = {
            token for token in self._TOKEN_PATTERN.findall(text_lc)
            if len(token) >= 2 and token not in self.IGNORE_TOKENS and not token.isdigit()
        }

        return list(tokens)

    def _resolve_paths_and_mod(self, file_path: Path) -> tuple[str, str]:
        """Определяет имя мода и относительный путь файла на основе режима."""
        rel_to_target = file_path.relative_to(self.target_path)
        parts = rel_to_target.parts

        mod_name = "Root"
        rel_path_str = str(file_path.parent)

        if self.mode == "MO2":
            if len(parts) > 0:
                mod_name = parts[0]
            try:
                tex_idx = parts.index('textures')
                # Путь относительно папки textures
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

        # Очистка rel_path, если файл лежит прямо в textures
        if rel_path_str == ".":
            rel_path_str = ""

        return mod_name, rel_path_str.replace('\\', '/')

    def scan_generator(self) -> Generator[dict[str, Any], None, None]:
        """
        Генератор сканирования. Итерирует по файлам, возвращает инфу по каждому
        и позволяет UI не блокироваться.
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

                # Токенизируем относительный путь + имя файла (без расширения)
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

                # Обновляем статистику
                self._stats["count"] += 1
                self._stats["total_size_mb"] += size_mb
                self._files.append(file_data)

                # Обновляем статистику токенов
                for token in tokens:
                    if token not in self._token_stats:
                        self._token_stats[token] = {"count": 0, "total_size_mb": 0.0}
                    self._token_stats[token]["count"] += 1
                    self._token_stats[token]["total_size_mb"] += size_mb

                yield file_data

        # Завершение
        self._stats["total_size_mb"] = round(self._stats["total_size_mb"], 2)
        self._stats["time_sec"] = round(time.time() - start_time, 2)

        # Округление веса токенов
        for t in self._token_stats:
            self._token_stats[t]["total_size_mb"] = round(self._token_stats[t]["total_size_mb"], 4)

    def get_result(self) -> ScanResult:
        """
        Возвращает итоговый объект ScanResult.
        Вызывать после того, как scan_generator() завершил работу.
        """
        return ScanResult(
            summary=self._stats,
            token_stats=self._token_stats,
            files=self._files
        )