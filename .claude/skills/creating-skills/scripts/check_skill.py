#!/usr/bin/env python3
"""Проверка скилла Claude Code по правилам Anthropic. Только читает файлы.

Запуск:
  python3 check_skill.py <папка-скилла или папка со скиллами>
  python3 check_skill.py --compare <старая-папка> <новая-папка>
Зависимостей нет, нужен только Python 3.8+. В Windows запускай как `python` или `py`.
"""
import os
import re
import sys
from pathlib import Path

MAX_BODY_LINES = 500       # лимит строк SKILL.md
MAX_DESC = 1024            # лимит поля description
MAX_DESC_WITH_WHEN = 1536  # description + when_to_use обрезаются на этой длине в Claude Code
TOC_AFTER = 100            # файл длиннее требует оглавления
WHEN_WORDS = r'when|trigger|\buse\b|когда|использ|применя|если|триггер|просьб|просит'
TOC_TITLE = r'^#+\s*(Contents|Table of contents|Содержание|Оглавление)'


def frontmatter(text):
    m = re.match(r'---\n(.*?)\n---\n?(.*)', text, re.S)
    if not m:
        return None, text
    fm = {}
    for k, v in re.findall(r'^([\w-]+):[ \t]*(.*(?:\n[ \t]+.*)*)', m.group(1), re.M):
        fm[k] = re.sub(r'\s+', ' ', v).strip().strip('"\'')
    return fm, m.group(2)


def strip_fences(text):
    return re.sub(r'(`{3,}|~{3,}).*?\n.*?\1', '', text, flags=re.S)


def md_links(text):
    return [u.split('#')[0] for u in re.findall(r'\]\(([^)\s]+)\)', strip_fences(text))
            if not re.match(r'(https?:|mailto:|#)', u) and u.split('#')[0]]


def check(skill):
    text = (skill / 'SKILL.md').read_text(encoding='utf-8')
    fm, body = frontmatter(text)
    if fm is None:
        return 0, 0, ['нет frontmatter']
    out = []
    name, desc = fm.get('name', ''), fm.get('description', '')
    full = (desc + ' ' + fm.get('when_to_use', '')).strip()
    manual = fm.get('disable-model-invocation', '').lower() in ('true', 'yes', 'on', '1')

    if not name:
        out.append('нет поля name')
    elif not re.fullmatch(r'[a-z0-9-]{1,64}', name) or re.search(r'anthropic|claude', name):
        out.append(f'имя «{name}» вне правил (a-z, 0-9, дефис, до 64, без anthropic/claude)')
    elif name != skill.name:
        out.append(f'name «{name}» не совпадает с именем папки «{skill.name}»')
    if re.search(r'<[a-zA-Z/][^>]*>', name + desc):
        out.append('XML-теги в name или description')
    if not desc:
        out.append('пустое описание')
    else:
        if not manual and not re.search(WHEN_WORDS, full, re.I):
            out.append('в описании не видно, когда применять')
        if len(desc) > MAX_DESC:
            out.append(f'описание {len(desc)} > {MAX_DESC}')
        if re.search(r'\b(I can|I will|You can)\b|\b(я помогу|я могу|ты можешь|вы можете)\b', desc, re.I):
            out.append('описание не от третьего лица')
    if len(full) > MAX_DESC_WITH_WHEN:
        out.append(f'description + when_to_use {len(full)} > {MAX_DESC_WITH_WHEN}')

    lines = body.count('\n') + 1
    if lines > MAX_BODY_LINES:
        out.append(f'SKILL.md {lines} строк > {MAX_BODY_LINES}')

    files = [f for f in skill.rglob('*') if f.is_file() and f.suffix == '.md' and f.name != 'SKILL.md']
    mentioned = lambda t, f: f.relative_to(skill).as_posix() in t or f.name in t
    linked = {f for f in files if mentioned(text, f)}

    for link in md_links(body):
        if not (skill / link).exists():
            out.append(f'битая ссылка {link}')
    for p in set(re.findall(r'(?<![\w./])(~/[\w./-]+|/(?:Users|home|opt|etc)/[\w./-]+)', strip_fences(text))):
        if '/skills/' in p and not os.path.exists(os.path.expanduser(p.rstrip('.'))):
            out.append(f'путь не существует {p}')

    deep = {}
    for f in files:
        ft = f.read_text(encoding='utf-8', errors='ignore')
        for g in files:
            if g != f and g not in linked and mentioned(ft, g):
                deep.setdefault(g, f.relative_to(skill))
    for f in files:
        ft = f.read_text(encoding='utf-8', errors='ignore')
        rel = f.relative_to(skill)
        if f in deep:
            out.append(f'{rel}: открывается только через {deep[f]} (2-й уровень)')
        elif f not in linked:
            out.append(f'{rel}: SKILL.md его не упоминает')
        n = ft.count('\n')
        if n > TOC_AFTER and not re.search(TOC_TITLE, '\n'.join(ft.splitlines()[:40]), re.M | re.I):
            out.append(f'{rel}: {n} строк без оглавления')

    if re.search(r'[\w.]\\[\w.]', ''.join(md_links(body))):
        out.append('обратный слэш в путях')

    code = '\n'.join(re.findall(r'(?:`{3,}|~{3,})[^\n]*\n(.*?)(?:`{3,}|~{3,})', text, re.S))
    for f in skill.rglob('*'):
        if f.is_file() and f.suffix != '.md' and '__pycache__' not in f.parts:
            rel = f.relative_to(skill).as_posix()
            if re.search(r'(?<![\w/}.~-])' + re.escape(rel) + r'(?![\w/-])', code):
                out.append(f'команда с {rel} без ${{CLAUDE_SKILL_DIR}}')
    if manual:
        out.append('(ручной вызов: описание не в контексте)')
    return lines, len(desc), out


def compare(old, new):
    norm = lambda s: re.sub(r'\s+', ' ', s).strip()
    have = set()
    for f in Path(new).rglob('*.md'):
        have |= {norm(l) for l in f.read_text(encoding='utf-8').splitlines()}
    old_lines = (Path(old) / 'SKILL.md').read_text(encoding='utf-8').splitlines()
    lost = [l for l in old_lines if norm(l) and norm(l) not in have and not norm(l).startswith('description:')]
    print(f'Потеряно строк: {len(lost)}')
    for l in lost:
        print('  -', l[:120])


def main(argv):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')  # кириллица в консоли Windows
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == '--compare':
        if len(argv) != 4:
            print('Нужно: --compare <старая> <новая>')
            return 2
        compare(argv[2], argv[3])
        return 0
    root = Path(argv[1]).expanduser()
    if not root.is_dir():
        print(f'Нет папки {root}')
        return 2
    skills = [root] if (root / 'SKILL.md').exists() else sorted(
        d for d in root.iterdir() if (d / 'SKILL.md').exists())
    if not skills:
        print(f'В {root} нет SKILL.md')
        return 2
    total = 0
    for s in skills:
        lines, dlen, issues = check(s)
        n = sum(1 for i in issues if not i.startswith('('))
        total += n
        print(f'{s.name:30} строк {lines:4}  описание {dlen:4}  нарушений {n}')
        for i in issues:
            print('   ·', i)
    print(f'\nСкиллов: {len(skills)}, нарушений: {total}')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
