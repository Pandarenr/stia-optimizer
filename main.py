import time
from core.scanner import AssetScanner

def test_scan():
    # Укажи путь к своей папке модов
    path_to_scan = input("Введите путь для теста (папка mods или конкретный мод): ")

    scanner = AssetScanner(path_to_scan)
    print(f"Режим сканирования: {scanner.mode}")
    print("Начинаю анализ...")

    # Имитируем Progress Bar
    count = 0
    for file_data in scanner.scan_generator():
        count += 1
        if count % 100 == 0:
            print(f"Просканировано: {count} файлов...")

    # Получаем финальный результат
    result = scanner.get_result()

    print("\n" + "="*50)
    print(f"АНАЛИЗ ЗАВЕРШЕН за {result.summary['time_sec']} сек.")
    print(f"Всего файлов: {result.summary['count']}")
    print(f"Общий вес: {result.summary['total_size_mb']:.2f} MB")
    print("="*50)

    # Выводим Топ-10 токенов по весу
    print("\nТОП-10 ТЯЖЕЛЫХ КАТЕГОРИЙ (ТОКЕНОВ):")
    sorted_tokens = sorted(result.token_stats.items(), key=lambda x: x[1]['total_size_mb'], reverse=True)
    for token, stats in sorted_tokens[:10]:
        print(f" - {token:<15} : {stats['total_size_mb']:>10.2f} MB ({stats['count']} файлов)")

if __name__ == "__main__":
    test_scan()