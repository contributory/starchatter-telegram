from os import environ, path
from getpass import getpass

ENV_FILE = ".env"


def load_env_file() -> dict:
    """Load existing .env file."""
    env_vars = {}
    if path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def save_env_file(env_vars: dict):
    """Save environment variables to .env file."""
    with open(ENV_FILE, "w") as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")


def get_env_or_prompt(
    key: str, is_secret: bool = False, is_int: bool = False
) -> str | int:
    """Get environment variable or prompt user if not set, then save to .env."""
    value = environ.get(key)
    if value is not None:
        return value

    # Try loading from .env file
    env_vars = load_env_file()
    if key in env_vars:
        value = env_vars[key]
        environ[key] = value
        return int(value) if is_int else value

    # Prompt user for value
    prompt_text = f"Enter {key}"
    if is_secret:
        prompt_text += " (hidden input)"
    prompt_text += ": "

    if is_secret:
        value = getpass(prompt_text)
    else:
        value = input(prompt_text)

    if is_int:
        value = str(value)

    # Save to .env
    env_vars[key] = value
    save_env_file(env_vars)
    environ[key] = value

    return int(value) if is_int else value


BOT_TOKEN = get_env_or_prompt("BOT_TOKEN", is_secret=True)
API_ID = get_env_or_prompt("API_ID", is_int=True)
API_HASH = get_env_or_prompt("API_HASH", is_secret=True)
TURSO_DB_URL = get_env_or_prompt("TURSO_DB_URL")
TURSO_AUTH_TOKEN = get_env_or_prompt("TURSO_AUTH_TOKEN", is_secret=True)
OWNER_PASSWORD = get_env_or_prompt("OWNER_PASSWORD", is_secret=True)

# Optional: Web panel URL for admin interface (can be empty)
WEB_PANEL_URL = environ.get("WEB_PANEL_URL", "")

# Public OAuth callback used by MCP Authorization Code flow.
MCP_OAUTH_REDIRECT_URI = environ.get(
    "MCP_OAUTH_REDIRECT_URI",
    "https://starchatter.serverweb.serv00.net/oauth_callback.php",
)
