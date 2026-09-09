from sqlalchemy import select
from pyrogram import idle
from app.client import client
from app.database.cloud import cloud_db
from app.database.local import local_db
from app.database.models import (
    AIProvider, DefaultModel, TelegramGroup, TelegramUser,
    TelegramChannel, GroupMember, ChannelMember, MCPServer
)


async def sync_cloud_to_local():
    """Sync all data from cloud to local database - cloud data always overwrites local data"""

    models = [AIProvider, TelegramUser, TelegramGroup, TelegramChannel, GroupMember, ChannelMember, DefaultModel, MCPServer]

    for model in models:
        try:
            # Get all data from cloud
            result = await cloud_db.execute(select(model))
            cloud_objects = result.scalars().all()

            # Clear all existing data from local table first
            await local_db.execute(model.__table__.delete())

            # Insert all cloud data to local, creating fresh instances to avoid session conflicts
            for obj in cloud_objects:
                obj_copy = type(obj)(
                    ** {col.name: getattr(obj, col.name)
                       for col in obj.__table__.columns
                       if hasattr(obj, col.name)}
                )
                await local_db.add(obj_copy)

            print(f"Synced {len(cloud_objects)} {model.__name__} records from cloud to local")
        except Exception as e:
            print(f"Error syncing {model.__name__}: {e}")


async def main():
    await client.start()
    cloud_db.init_db()
    local_db.init_db()

    # Sync từ cloud về local - gán cloud_db và local_db làm tham số mặc định
    print("Syncing data from cloud to local...")
    # try:
    await sync_cloud_to_local()
    # except Exception as e:
    #     print(f"Sync error: {e}")
    print("Sync completed.")
    await idle()
    await client.stop()
