"""The web page's texts (templates/map_i18n.js): both languages have the same keys and the same
{placeholders}, and every key the scripts ask for by name exists."""

from __future__ import annotations

import re
from importlib import resources

TEMPLATES = resources.files("styleatlas").joinpath("templates")
STRING = re.compile(r'(\w+):\s*"((?:[^"\\]|\\.)*)"')
ARRAY = re.compile(r"(\w+):\s*\[")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _tables() -> dict[str, dict[str, str]]:
    text = TEMPLATES.joinpath("map_i18n.js").read_text("utf-8")
    en_start, zh_start = text.index("en: {"), text.index("zh: {")
    tables = {}
    for lang, part in (("en", text[en_start:zh_start]), ("zh", text[zh_start:])):
        table = {k: v for k, v in STRING.findall(part)}
        table.update({k: "" for k in ARRAY.findall(part) if k not in table})
        tables[lang] = table
    return tables


def test_both_languages_have_the_same_keys_and_placeholders():
    tables = _tables()
    en, zh = tables["en"], tables["zh"]
    assert len(en) > 200  # the parse found the tables
    assert set(en) == set(zh), set(en) ^ set(zh)
    for key in en:
        assert set(PLACEHOLDER.findall(en[key])) == set(PLACEHOLDER.findall(zh[key])), key


def test_every_text_the_scripts_name_exists():
    tables = _tables()
    used = set()
    for name in ("map.js", "map_layout.js", "map_group.js", "map_app.js"):
        used |= set(re.findall(r'\bt\("(\w+)"\)', TEMPLATES.joinpath(name).read_text("utf-8")))
    assert used and not used - set(tables["en"]), sorted(used - set(tables["en"]))


def test_a_line_that_fills_placeholders_fills_all_of_them():
    """`t("exported").replace("{n}", ...)` must replace every {x} the text has (a line that
    replaces none keeps the template for later and is skipped)."""
    en = _tables()["en"]
    missing = []
    for name in ("map.js", "map_layout.js", "map_group.js", "map_app.js"):
        lines = TEMPLATES.joinpath(name).read_text("utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            follow = []  # a chain may go on in the next lines: ".replace(...)"
            for nxt in lines[number:]:
                if not nxt.lstrip().startswith(".replace("):
                    break
                follow.append(nxt.strip())
            for match in re.finditer(r'\bt\("(\w+)"\)', line):
                rest = line[match.end() :] + "".join(follow)
                filled = set(re.findall(r'^\.replace\("\{(\w+)\}"|\.replace\("\{(\w+)\}"', rest))
                filled = {a or b for a, b in filled}
                wanted = set(PLACEHOLDER.findall(en.get(match.group(1), "")))
                if filled and wanted - filled:
                    missing.append(f"{name}:{number} {match.group(1)} lacks {wanted - filled}")
    assert not missing, missing


def test_no_text_key_is_defined_twice():
    """A repeated key silently replaces the first text (the later one wins in a JS object)."""
    from collections import Counter

    text = TEMPLATES.joinpath("map_i18n.js").read_text("utf-8")
    en_start, zh_start = text.index("en: {"), text.index("zh: {")
    for part in (text[en_start:zh_start], text[zh_start:]):
        keys = [k for k, _ in STRING.findall(part)] + ARRAY.findall(part)
        twice = [k for k, n in Counter(keys).items() if n > 1]
        assert not twice, twice
