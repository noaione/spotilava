from __future__ import annotations

from enum import Enum

__all__ = ("TidalAudioQuality",)


class TidalAudioQuality(Enum):
    low = "LOW"
    normal = "NORMAL"
    lossless = "LOSSLESS"
    master = "HI_RES"

    def __lt__(self, other: TidalAudioQuality):
        return int(self) < int(other)

    def __gt__(self, other: TidalAudioQuality):
        return int(self) > int(other)

    def __le__(self, other: TidalAudioQuality):
        return int(self) <= int(other)

    def __ge__(self, other: TidalAudioQuality):
        return int(self) >= int(other)

    def __int__(self):
        mapping = {"low": 0, "normal": 1, "lossless": 2, "master": 3}
        return mapping.get(self.name, -1)

    def __str__(self):
        return self.name.capitalize()

    def __eq__(self, other: TidalAudioQuality):
        return int(self) == int(other)

    def __ne__(self, other: TidalAudioQuality):
        return not self.__eq__(other)
