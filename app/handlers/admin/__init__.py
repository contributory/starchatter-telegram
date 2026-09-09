"""Admin panel handlers package."""

from app.handlers.admin.super_command import super_command
from app.handlers.admin.admin_callbacks import admin_navigation_handler

__all__ = ["super_command", "admin_navigation_handler"]
