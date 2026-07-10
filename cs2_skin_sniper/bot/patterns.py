"""Справочник известных редких paint seed (примеры — расширяй под себя).

paint seed определяет рисунок скина. У некоторых скинов отдельные сиды дают
особо ценные паттерны (напр. «blue gem» у AK-47 Case Hardened). Значения ниже —
широко известные примеры; полные списки ведут сообщества (CSBluegem и т.п.).
Добавляй свои сиды при создании правила.
"""

from __future__ import annotations

# Ключ — подстрока названия скина, значение — список особо ценных paint seed.
KNOWN_RARE_SEEDS: dict[str, list[int]] = {
    "AK-47 | Case Hardened": [661, 670, 555, 651, 179, 460, 168, 955],
    "Karambit | Case Hardened": [387, 852, 963, 442],
    "Five-SeveN | Case Hardened": [278, 690, 868],
}


def rare_seeds_for(name: str) -> list[int]:
    """Известные редкие сиды для скина по подстроке названия."""
    for key, seeds in KNOWN_RARE_SEEDS.items():
        if key.lower() in name.lower():
            return seeds
    return []
