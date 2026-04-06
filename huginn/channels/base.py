from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HuginnMessage:
    channel: str
    sender: str
    text: str
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send_message(self, recipient: str, text: str) -> None:
        raise NotImplementedError
