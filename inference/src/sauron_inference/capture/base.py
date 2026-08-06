from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..types import Frame


class FrameSource(ABC):
    """Blocking iterator of frames for a single camera."""

    camera_id: str

    @abstractmethod
    def frames(self) -> Iterator[Frame]:
        """Yield frames until stop() is called. Handles reconnection internally."""

    @abstractmethod
    def stop(self) -> None: ...
