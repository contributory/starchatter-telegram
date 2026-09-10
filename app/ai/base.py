from agents import function_tool
from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import AIProvider
from openai import AsyncClient
import os


async def get_client() -> AsyncClient:
    """Get OpenAI client from default provider in database (read from local)"""
    provider = await local_db.get_default_provider()
    if provider:
        return AsyncClient(
            base_url=provider.base_url,
            api_key=provider.api_key,
        )
    raise ValueError("No AI provider configured. Use /providers to add one.")


async def models():
    """Get list of models - prefer calling provider API, if failed then use models in AIProvider"""
    try:
        client = await get_client()
        models_list = await client.models.list()
        return [m.id for m in models_list.data]
    except Exception as e:
        print(f"Error calling provider API: {e}, falling back to AIProvider models")
        # Fallback: get from AIProvider
        provider = await local_db.get_default_provider()
        if provider and provider.models:
            return provider.models
        # If no models, return empty list
        return []


async def get_client_for_provider(provider: AIProvider) -> AsyncClient:
    """Get OpenAI client for a specific provider"""
    return AsyncClient(
        base_url=provider.base_url,
        api_key=provider.api_key,
    )

async def get_provider_models(provider_name: str | None = None, provider: AIProvider | None = None):
    """Get list of models for a specific provider.
    If provider_name is provided, use that provider.
    If provider is provided directly, use that.
    Otherwise, use default provider.
    """
    # Resolve provider
    if provider is None:
        if provider_name:
            db_provider = await local_db.get_provider_by_name(provider_name)
            if not db_provider:
                return []
            provider = db_provider
        else:
            provider = await local_db.get_default_provider()
            if not provider:
                return []

    # Try to get models from provider API first
    try:
        client = await get_client_for_provider(provider)
        models_list = await client.models.list()
        return [m.id for m in models_list.data]
    except Exception as e:
        print(f"Error calling provider API for {provider.name}: {e}, falling back to AIProvider models")

    # Fallback: get from AIProvider.models field
    if provider and provider.models:
        return provider.models

    # If no models, return empty list
    return []

async def get_model() -> str:
    """Get model ID from DefaultModel (read from local)"""
    default_model = await local_db.get_default_model("chat")
    if default_model and default_model.model:
        return default_model.model
    return ""


@function_tool
def list_models():
    """Tool to list models - run async in sync context"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(models())


@function_tool
def set_model(model_id: str):
    """Tool to set default model for chat - run async in sync context"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Get current provider
    provider = loop.run_until_complete(local_db.get_default_provider())
    if provider:
        # Save model to DefaultModel (write via cloud, will mirror to local)
        loop.run_until_complete(cloud_db.set_default_model("chat", provider.name, model_id))
        return f"Model `{model_id}` has been set as default for chat!"
    return "No provider is configured. Use /providers to add a provider."
