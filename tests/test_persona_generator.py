from colosseum.core.models import PersonaProfileRequest
from colosseum.personas.generator import PersonaGenerator


def test_persona_generator_uses_profile_fields():
    generator = PersonaGenerator()
    persona = generator.generate(
        PersonaProfileRequest(
            persona_name="Calm Product Strategist",
            profession="Product manager",
            personality="analytical and calm",
            debate_style="direct and evidence-driven",
            free_text="I hate bloated arguments and I care about execution risk.",
        )
    )

    assert persona.name == "Calm Product Strategist"
    assert persona.persona_id == "calm_product_strategist"
    assert "Product manager" in persona.content
    assert "analytical and calm" in persona.content
    assert "direct and evidence-driven" in persona.content
    assert "I hate bloated arguments" in persona.content
