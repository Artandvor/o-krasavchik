"""Реестр характеристик. Каждая характеристика — YAML-файл в characteristics/.
Чтобы добавить новую, достаточно положить файл (или описать её текстом — см. agents/compiler.py)."""
import yaml

from .config import CHAR_DIR

REQUIRED = ("key", "title", "type", "tool", "scope")


class Registry:
    def __init__(self, path=CHAR_DIR):
        self.path = path
        self.reload()

    def reload(self):
        self.specs = {}
        for p in sorted(self.path.glob("*.yaml")):
            s = yaml.safe_load(p.read_text(encoding="utf-8"))
            missing = [k for k in REQUIRED if k not in s]
            if missing:
                print(f"[registry] {p.name}: нет полей {missing}, пропускаю")
                continue
            s.setdefault("params", {})
            s.setdefault("trust", {})
            s["trust"].setdefault("guest", 0.85)  # гость, который пожил в номере, — сильная проверка
            s.setdefault("ttl_days", 180)
            s.setdefault("demand", 0.05)
            s.setdefault("search", {})
            s.setdefault("group", "Другое")
            s["_file"] = p.name
            self.specs[s["key"]] = s

    def get(self, key):
        return self.specs.get(key)

    def all(self):
        return list(self.specs.values())

    def save(self, spec: dict):
        spec = {k: v for k, v in spec.items() if not k.startswith("_")}
        p = self.path / f"{spec['key']}.yaml"
        p.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.reload()
        return self.specs[spec["key"]]


_reg = None


def get_registry() -> Registry:
    global _reg
    if _reg is None:
        _reg = Registry()
    return _reg
