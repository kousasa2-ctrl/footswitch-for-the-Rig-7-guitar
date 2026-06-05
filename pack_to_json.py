import json
import os

# Имя итогового файла
OUTPUT_JSON_FILE = "project_code.json"
# Расширения файлов, которые мы ищем
ALLOWED_EXTENSIONS = (".py", ".cpp", ".h", ".hpp", ".c")
# Имена папок, которые нужно СТРОГО пропустить (чтобы не сканировать библиотеки)
IGNORED_FOLDERS = {".venv", "venv", ".git", "__pycache__", "build", "dist"}

project_data = {}

# Точка отсчета — текущая папка, где запущен скрипт (".")
current_directory = os.getcwd()
print(f"Сканируем рабочую директорию: {current_directory}\n")

for root, dirs, files in os.walk(current_directory):
    # Исключаем ненужные папки из обхода (модифицируем dirs на месте)
    dirs[:] = [d for d in dirs if d not in IGNORED_FOLDERS]

    for file in files:
        if file.endswith(ALLOWED_EXTENSIONS):
            # Пропускаем сам файл скрипта-сборщика, если он совпадает по расширению
            if file == os.path.basename(__file__):
                continue
                
            full_path = os.path.join(root, file)

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    code_content = f.read()

                # Делаем путь относительным (например, "folder/main.py" вместо "F:/гита/folder/main.py")
                relative_path = os.path.relpath(full_path, current_directory)
                clean_path = relative_path.replace("\\", "/")
                
                project_data[clean_path] = code_content
                print(f"Добавлен: {clean_path}")

            except Exception as e:
                print(f"Ошибка чтения {file}: {e}")

# Сохранение результата
with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as json_file:
    json.dump(project_data, json_file, ensure_ascii=False, indent=4)

print(f"\nУспех! Создан файл: {os.path.abspath(OUTPUT_JSON_FILE)}")
