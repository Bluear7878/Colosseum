"""Canonical model pricing table (prompt_cost, completion_cost) per 1k tokens."""

MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-6":               (0.015,     0.075),
    "claude-sonnet-4-6":             (0.003,     0.015),
    "claude-haiku-4-5-20251001":     (0.0008,    0.004),
    "gpt-5.4":                       (0.0025,    0.010),
    "gpt-5.3-codex":                 (0.0015,    0.006),
    "o3":                            (0.002,     0.008),
    "o4-mini":                       (0.0011,    0.0044),
    "gemini-3.1-pro-preview":        (0.0025,    0.015),
    "gemini-3-flash-preview":        (0.00015,   0.0006),
    "gemini-3.1-flash-lite-preview": (0.000075,  0.0003),
    "gemini-2.5-pro":                (0.00125,   0.010),
    "gemini-2.5-flash":              (0.000075,  0.0003),
    "gemini-2.5-flash-lite":         (0.0000375, 0.00015),
}
