"""DLC (Downloadable Content) pack engine — desktop side.

Mirrors web/js/browser-backend.js: a DLC is a pack of demos (+ experiments).
Official packs (data/dlc/*.dlc.json) are lightweight area-filter manifests
resolved against the built-in demo library; custom / AI / user packs embed full
demo objects and live as files under data/dlc_custom/. A pack's `code` only ever
runs in the sandboxed worker, exactly like any other demo.

Pure/self-contained: callers pass a `library_index` (a list of light demo dicts
with id/area/topic/title/equation) so this module never imports the library.
"""
from __future__ import annotations

import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
DLC_DIR = os.path.join(_HERE, "data", "dlc")            # official packs (read-only)
CUSTOM_DIR = os.path.join(_HERE, "data", "dlc_custom")  # imported / AI packs


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 — missing/corrupt file is non-fatal
        return None


def official_packs() -> list[dict]:
    index = _read_json(os.path.join(DLC_DIR, "index.json")) or []
    out = []
    for fname in index:
        p = _read_json(os.path.join(DLC_DIR, fname))
        if isinstance(p, dict):
            p["source"] = "official"
            out.append(p)
    return out


def custom_packs() -> list[dict]:
    out = []
    if os.path.isdir(CUSTOM_DIR):
        for fname in sorted(os.listdir(CUSTOM_DIR)):
            if fname.endswith(".json"):
                p = _read_json(os.path.join(CUSTOM_DIR, fname))
                if isinstance(p, dict):
                    p["source"] = p.get("source", "user")
                    out.append(p)
    return out


def all_packs() -> list[dict]:
    return official_packs() + custom_packs()


def find_pack(pack_id: str) -> dict | None:
    for p in all_packs():
        if p.get("id") == pack_id:
            return p
    return None


def find_embedded(demo_id: str) -> dict | None:
    """A demo/experiment object embedded in any pack (custom or official)."""
    for p in custom_packs() + official_packs():
        for d in (p.get("demos") or []) + (p.get("experiments") or []):
            if d.get("id") == demo_id:
                return d
    return None


def validate(obj) -> list[str]:
    """Return a list of validation errors ([] == valid)."""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["Not a JSON object."]
    if str(obj.get("format", "")).split("/")[0] != "visuallm-dlc":
        errors.append('Missing or bad `format` (expected "visuallm-dlc/1").')
    if not obj.get("id") or not isinstance(obj.get("id"), str):
        errors.append("Missing `id`.")
    if not obj.get("name") or not isinstance(obj.get("name"), str):
        errors.append("Missing `name`.")
    demos = obj.get("demos") or []
    exps = obj.get("experiments") or []
    areas = obj.get("areas") or []
    if not demos and not exps and not areas:
        errors.append("Pack is empty (no demos, experiments, or areas).")
    for i, d in enumerate(list(demos) + list(exps)):
        if not isinstance(d, dict):
            errors.append(f"Item {i} is not an object.")
            continue
        if not d.get("id"):
            errors.append(f"Item {i} is missing `id`.")
        if not str(d.get("code", "")).strip():
            errors.append(f"Item {d.get('id', i)} is missing animation `code`.")
    return errors


def pack_meta(p: dict, library_index: list[dict]) -> dict:
    areas = p.get("areas") or []
    area_count = sum(1 for d in library_index if d.get("area") in areas) if areas else 0
    return {
        "id": p.get("id"),
        "name": p.get("name") or p.get("id"),
        "description": p.get("description", ""),
        "category": p.get("category", "custom"),
        "icon": p.get("icon") or ("📦" if p.get("source") == "official" else "🧩"),
        "source": p.get("source", "user"),
        "demoCount": area_count + len(p.get("demos") or []),
        "experimentCount": len(p.get("experiments") or []),
    }


def pack_catalog(p: dict, library_index: list[dict]) -> dict:
    groups: dict[str, dict[str, list]] = {}

    def push(area, topic, d):
        area = area or "General"
        topic = topic or "Demos"
        groups.setdefault(area, {}).setdefault(topic, []).append(d)

    areas = p.get("areas") or []
    if areas:
        for d in library_index:
            if d.get("area") in areas:
                push(d.get("area"), d.get("topic"),
                     {"id": d.get("id"), "title": d.get("title"), "equation": d.get("equation", "")})
    for d in (p.get("demos") or []):
        push(d.get("area"), d.get("topic"),
             {"id": d.get("id"), "title": d.get("title"), "equation": d.get("equation", "")})

    sections = []
    for area in sorted(groups):
        topics = [{"topic": t, "demos": groups[area][t]} for t in sorted(groups[area])]
        sections.append({"area": area, "topics": topics})
    experiments = [
        {"id": e.get("id"), "title": e.get("title"), "blurb": e.get("blurb", "")}
        for e in (p.get("experiments") or [])
    ]
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "description": p.get("description", ""),
        "icon": p.get("icon", "📦"),
        "source": p.get("source", "official"),
        "sections": sections,
        "experiments": experiments,
    }


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", (s or "pack").lower()).strip("-") or "pack"


def import_pack(obj: dict) -> dict:
    """Persist an imported/generated pack as a file. Assumes validate() passed."""
    os.makedirs(CUSTOM_DIR, exist_ok=True)
    obj = dict(obj)
    obj["source"] = obj.get("source") if obj.get("source") in ("ai", "user") else "user"
    with open(os.path.join(CUSTOM_DIR, _slug(obj.get("id")) + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return obj


def remove_pack(pack_id: str) -> bool:
    path = os.path.join(CUSTOM_DIR, _slug(pack_id) + ".json")
    if os.path.exists(path):
        os.remove(path)
        return True
    # Fall back to a scan (id may differ from the slugged filename).
    if os.path.isdir(CUSTOM_DIR):
        for fname in os.listdir(CUSTOM_DIR):
            p = _read_json(os.path.join(CUSTOM_DIR, fname))
            if isinstance(p, dict) and p.get("id") == pack_id:
                os.remove(os.path.join(CUSTOM_DIR, fname))
                return True
    return False
