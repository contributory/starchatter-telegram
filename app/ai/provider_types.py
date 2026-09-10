"""Provider type definitions shared by provider UI and runtime."""

from __future__ import annotations

PROVIDER_CHAT_COMPLETIONS = "chat_completions"
PROVIDER_OPENAI_RESPONSES = "openai_responses"

PROVIDER_TYPE_LABELS = {
    PROVIDER_CHAT_COMPLETIONS: "Chat Completions",
    PROVIDER_OPENAI_RESPONSES: "OpenAI Responses",
}

API_KEY_PROVIDER_TYPES = set(PROVIDER_TYPE_LABELS)


def provider_type_label(provider_type: str | None) -> str:
    return PROVIDER_TYPE_LABELS.get(
        provider_type or PROVIDER_CHAT_COMPLETIONS,
        "Unknown",
    )


def is_api_key_provider(provider_type: str | None) -> bool:
    return (provider_type or PROVIDER_CHAT_COMPLETIONS) in API_KEY_PROVIDER_TYPES
