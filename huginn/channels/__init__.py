from __future__ import annotations

from huginn.channels.base import ChannelAdapter, HuginnMessage
from huginn.channels.browser_base import SessionBrowser
from huginn.channels.instagram import InstagramChannel
from huginn.channels.telegram import TelegramChannel
from huginn.channels.whatsapp import WhatsAppChannel

__all__ = [
    "ChannelAdapter",
    "HuginnMessage",
    "SessionBrowser",
    "TelegramChannel",
    "WhatsAppChannel",
    "InstagramChannel",
]
