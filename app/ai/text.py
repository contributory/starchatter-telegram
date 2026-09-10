"""AI-generated text utility with language detection and fallback."""

import logging
from app.database.local import local_db
from app.ai.provider_types import PROVIDER_OPENAI_RESPONSES
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def generate_localized_text(original_text: str, user_language: str = "en") -> str:
    """
    Generate localized text using AI provider.

    Args:
        original_text: The original English text to translate/localize
        user_language: The target language code (default: "en")

    Returns:
        AI-generated text in the user's language, or original English text on failure
    """
    # Check if provider is configured (đọc từ local)
    provider = await local_db.get_default_provider()
    if not provider:
        logger.debug(
            f"No AI provider configured, using original text: {original_text[:50]}..."
        )
        return original_text

    # Resolve the provider/model configured specifically for translation.
    default_model = await local_db.get_default_model("translate")
    model_id = ""
    if default_model and default_model.model:
        model_id = default_model.model
    if default_model and default_model.provider_name:
        selected_provider = await local_db.get_provider_by_name(default_model.provider_name)
        if selected_provider:
            provider = selected_provider

    try:
        client = AsyncOpenAI(
            base_url=provider.base_url,
            api_key=provider.api_key,
        )

        system_text = (
            "You are a professional translator. "
            f"Translate the given text to the user's language ({user_language}). "
            "Keep the same tone, format, and meaning. "
            f"If translation is not needed (already in {user_language}), return the text as-is. "
            "Only output the translated text, no explanations."
        )
        user_text = f"Translate this text to {user_language}:\n\n{original_text}"

        provider_type = getattr(provider, "provider_type", None) or "chat_completions"
        if provider_type == PROVIDER_OPENAI_RESPONSES:
            response = await client.responses.create(
                model=model_id,
                instructions=system_text,
                input=user_text,
            )
            if response.output_text:
                return response.output_text.strip()
        else:
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
            )
            if response and response.choices and response.choices[0].message.content:
                return response.choices[0].message.content.strip()

    except Exception as e:
        logger.warning(f"AI text generation failed: {e}")
        return original_text

    return original_text


async def get_user_language(user_id: int) -> str:
    """
    Detect user's preferred language.
    This is a placeholder - in production, you'd get this from Telegram's user info
    or from a user settings database.
    """
    # For now, default to English
    # TODO: Implement actual language detection from user settings
    return "en"


# Convenience function for commands
async def localize(
    text: str, locale: str | None = None, user_id: int | None = None
) -> str:
    """
    Localize text to user's language.

    Args:
        text: Original English text
        locale: Explicit locale code (e.g., "vi", "ja", "ko")
        user_id: User ID to detect their preferred language

    Returns:
        Localized text or original if localization fails
    """
    if locale:
        return await generate_localized_text(text, locale)

    if user_id:
        detected_lang = await get_user_language(user_id)
        return await generate_localized_text(text, detected_lang)

    return text
