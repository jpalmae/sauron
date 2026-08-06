from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..types import Detection


class Detector(ABC):
    """Object detector over BGR uint8 frames."""

    @abstractmethod
    def detect(self, image: np.ndarray) -> list[Detection]: ...

    def close(self) -> None:
        pass
