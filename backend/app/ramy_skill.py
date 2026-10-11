"""Instrucciones comerciales locales, cargadas una vez por proceso."""
from functools import lru_cache
from pathlib import Path

SKILL_FILE = Path(__file__).with_name('ramy_sales_skill.txt')

@lru_cache(maxsize=1)
def skill_instructions():
    text = SKILL_FILE.read_text(encoding='utf-8').strip()
    if not text or len(text) > 12000:
        raise ValueError('Instrucciones comerciales ausentes o demasiado extensas')
    return '\nRAMY_VENTAS_SKILL_V1:\n' + text
