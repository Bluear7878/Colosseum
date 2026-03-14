from __future__ import annotations

from pathlib import Path

from colosseum.core.models import PersonaProfileRequest
from colosseum.personas.generator import PersonaGenerator
from colosseum.personas.loader import PersonaLoader
from colosseum.personas.registry import PersonaRegistry, sanitize_persona_id


def test_registry_parses_legacy_markdown_persona(tmp_path):
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    custom_dir.mkdir()
    (builtin_dir / "legacy_voice.md").write_text(
        "# Legacy Voice\n\n> Desc from blockquote\n\n## Your Role\nBe practical.\n",
        encoding="utf-8",
    )

    registry = PersonaRegistry(builtin_dir=builtin_dir, custom_dir=custom_dir)
    persona = registry.get_persona("legacy_voice")

    assert persona is not None
    assert persona.persona_id == "legacy_voice"
    assert persona.name == "Legacy Voice"
    assert persona.description == "Desc from blockquote"
    assert persona.source == "builtin"
    assert "Be practical." in persona.content


def test_registry_parses_frontmatter_metadata(tmp_path):
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    custom_dir.mkdir()
    (custom_dir / "frontmatter.md").write_text(
        "---\n"
        "persona_id: system_thinker\n"
        "name: System Thinker\n"
        "description: Thinks in interfaces and boundaries.\n"
        "version: 2.1\n"
        "tags: [systems, architecture]\n"
        "active: false\n"
        "---\n"
        "# System Thinker\n\n> Thinks in interfaces and boundaries.\n\nUse first principles.\n",
        encoding="utf-8",
    )

    registry = PersonaRegistry(builtin_dir=builtin_dir, custom_dir=custom_dir)
    persona = registry.get_persona("system_thinker")

    assert persona is not None
    assert persona.version == "2.1"
    assert persona.tags == ["systems", "architecture"]
    assert persona.is_active is False
    assert persona.content.startswith("# System Thinker")


def test_loader_saves_custom_persona_with_sanitized_id(tmp_path):
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    custom_dir.mkdir()
    loader = PersonaLoader(builtin_dir=builtin_dir, custom_dir=custom_dir)

    metadata = loader.save_custom_persona(
        "My New Persona!!",
        "# My New Persona\n\n> Custom desc\n\nKeep it focused.\n",
    )

    assert metadata["persona_id"] == "my_new_persona"
    assert (custom_dir / "my_new_persona.md").exists()
    assert loader.load_persona("my_new_persona") is not None


def test_registry_prefers_custom_persona_over_builtin_on_conflict(tmp_path):
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    custom_dir.mkdir()
    (builtin_dir / "shared.md").write_text(
        "# Shared\n\n> Builtin\n\nBuiltin content.\n", encoding="utf-8"
    )
    (custom_dir / "shared.md").write_text(
        "# Shared\n\n> Custom\n\nCustom content.\n", encoding="utf-8"
    )

    registry = PersonaRegistry(builtin_dir=builtin_dir, custom_dir=custom_dir)
    persona = registry.get_persona("shared")

    assert persona is not None
    assert persona.source == "custom"
    assert "Custom content." in persona.content


def test_loader_delete_custom_persona_only_removes_custom_copy(tmp_path):
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    custom_dir.mkdir()
    (builtin_dir / "shared.md").write_text(
        "# Shared\n\n> Builtin\n\nBuiltin content.\n", encoding="utf-8"
    )
    (custom_dir / "shared.md").write_text(
        "# Shared\n\n> Custom\n\nCustom content.\n", encoding="utf-8"
    )

    loader = PersonaLoader(builtin_dir=builtin_dir, custom_dir=custom_dir)

    assert loader.delete_custom_persona("shared") is True
    assert loader.load_persona("shared") == "# Shared\n\n> Builtin\n\nBuiltin content."


def test_generated_persona_remains_registry_compatible(tmp_path):
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    builtin_dir.mkdir()
    custom_dir.mkdir()
    generator = PersonaGenerator()
    generated = generator.generate(
        PersonaProfileRequest(
            persona_name="Calm Product Strategist",
            profession="Product manager",
            personality="analytical and calm",
            debate_style="direct and evidence-driven",
            free_text="Care about execution risk.",
        )
    )
    registry = PersonaRegistry(builtin_dir=builtin_dir, custom_dir=custom_dir)

    saved = registry.save_custom_persona(generated.persona_id, generated.content)

    assert saved.persona_id == sanitize_persona_id(generated.persona_id)
    assert saved.name == generated.name
    assert "Care about execution risk." in saved.content


def test_builtin_public_figure_personas_are_registered_with_safety_guardrails():
    registry = PersonaRegistry()

    expected_ids = {
        "cristiano_ronaldo",
        "lionel_messi",
        "pep_guardiola",
        "serena_williams",
        "geoffrey_hinton",
        "yoshua_bengio",
        "andrej_karpathy",
        "demis_hassabis",
        "andrew_ng",
        "fei_fei_li",
        "ilya_sutskever",
        "elon_musk",
    }

    persona_ids = {persona.persona_id for persona in registry.list_personas()}
    assert expected_ids.issubset(persona_ids)

    ronaldo = registry.get_persona("cristiano_ronaldo")
    karpathy = registry.get_persona("andrej_karpathy")

    assert ronaldo is not None
    assert karpathy is not None
    assert "Do not claim to be Cristiano Ronaldo" in ronaldo.content
    assert "Do not claim to be Andrej Karpathy" in karpathy.content


def test_builtin_personas_define_explicit_voice_signal_sections():
    builtin_dir = Path("src/colosseum/personas/builtin")
    persona_files = sorted(builtin_dir.glob("*.md"))

    assert persona_files, "Expected builtin persona files to exist."
    for path in persona_files:
        content = path.read_text(encoding="utf-8")
        assert "## Voice Signals" in content, f"{path.name} is missing a Voice Signals section."
        assert "## Signature Moves" in content, f"{path.name} is missing a Signature Moves section."
