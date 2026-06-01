from pedalboard import load_plugin
import os

vst_path = os.path.join("plugins", "Guitar Rig 7.vst3")

if os.path.exists(vst_path):
    print(f"Файл найден: {vst_path}")
    try:
        plugin = load_plugin(vst_path)
        print(plugin)
        print("VST3 плагин успешно загружен!")
        print("Доступные атрибуты плагина:")
        attrs = [
            'programs',
            'parameters',
            'presets',
            'current_program'
        ]
        for attr in attrs:
            print(f"  {attr}: {getattr(plugin, attr, None)}")
        print("dir(plugin) sample:")
        print([name for name in dir(plugin) if name in attrs or name.startswith('program') or name.startswith('preset')][:50])
    except Exception as e:
        print(f"Ошибка загрузки плагина: {e}")
else:
    print(f"ФАЙЛ НЕ НАЙДЕН по пути: {vst_path}")