from __future__ import annotations

import re
from pathlib import Path

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
CUSTOM_DIR = Path(__file__).resolve().parent / "custom"


def _parse_persona_file(path: Path) -> dict:
    """Parse a persona MD file and extract metadata."""
    pid = path.stem
    text = path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    name = pid.replace("_", " ").title()
    desc = ""
    for line in lines:
        if line.startswith("# "):
            name = line[2:].strip()
        elif line.startswith("> ") and not desc:
            desc = line[2:].strip()
    return {"persona_id": pid, "name": name, "description": desc}


class PersonaLoader:
    def list_personas(self) -> list[dict]:
        results: list[dict] = []
        # Builtin personas
        if BUILTIN_DIR.exists():
            for f in sorted(BUILTIN_DIR.glob("*.md")):
                meta = _parse_persona_file(f)
                meta["source"] = "builtin"
                results.append(meta)
        # Custom personas
        if CUSTOM_DIR.exists():
            for f in sorted(CUSTOM_DIR.glob("*.md")):
                meta = _parse_persona_file(f)
                meta["source"] = "custom"
                results.append(meta)
        return results

    def load_persona(self, persona_id: str) -> str | None:
        # Check builtin first, then custom
        for directory in (BUILTIN_DIR, CUSTOM_DIR):
            path = directory / f"{persona_id}.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

    def save_custom_persona(self, persona_id: str, content: str) -> dict:
        """Save a custom persona MD file. Returns metadata."""
        CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
        # Sanitize persona_id
        safe_id = re.sub(r"[^a-z0-9_]", "_", persona_id.lower().strip())
        if not safe_id:
            safe_id = "custom_persona"
        path = CUSTOM_DIR / f"{safe_id}.md"
        path.write_text(content, encoding="utf-8")
        meta = _parse_persona_file(path)
        meta["source"] = "custom"
        return meta

    def delete_custom_persona(self, persona_id: str) -> bool:
        """Delete a custom persona. Returns True if deleted."""
        path = CUSTOM_DIR / f"{persona_id}.md"
        if path.exists():
            path.unlink()
            return True
        return False
