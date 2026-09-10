"""Update command handler - performs git pull and restarts the application"""
import subprocess
import sys
import os

from pyrogram import Client, filters, types
from app.handlers.owner import is_user_owner_async

@Client.on_message(filters.command("update") & filters.private)  # type: ignore
async def update_handler(client: Client, message: types.Message):
    """Handle update command - performs git pull and restarts the application"""
    # Check if user is owner
    if not await is_user_owner_async(message.from_user.id):
        await message.reply("❌ You don't have permission to use this command.", quote=True)
        return

    await message.reply("🔄 Starting update process...", quote=True)

    try:
        # Perform git pull
        await message.reply("📥 Pulling latest changes from repository...", quote=True)
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True,
            text=True,
            check=True
        )

        await message.reply(f"📝 Git pull output:\n```\n{result.stdout}\n```", quote=True)

        # Notify user about restart
        await message.reply("🔁 Restarting application to apply updates...", quote=True)

        # Restart the application
        python = sys.executable
        os.execl(python, python, *sys.argv)

    except subprocess.CalledProcessError as e:
        await message.reply(f"❌ Git pull failed:\n```\n{e.stderr}\n```", quote=True)
    except Exception as e:
        await message.reply(f"❌ Update failed: {str(e)}", quote=True)