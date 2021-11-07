"""
MIT License

Copyright (c) 2021-present noaione

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

This implements the rest of AAC and MP3 encoding quality.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Optional

from librespot.audio import SuperAudioFormat
from librespot.audio.decoders import AudioQuality
from librespot.structure import AudioQualityPicker
from librespot.proto import Metadata_pb2 as Metadata


class AutoFallbackAudioQuality(AudioQualityPicker):
    logger = logging.getLogger("Spotilava:Player:AutoFallbackAudioQuality")
    preferred: AudioQuality

    def __init__(self, preferred: AudioQuality) -> None:
        self.preferred: AudioQuality = preferred
        self.other_quality: List[AudioQuality] = [
            AudioQuality.VERY_HIGH,
            AudioQuality.HIGH,
            AudioQuality.NORMAL,
        ]
        self.other_quality.remove(self.preferred)

    @staticmethod
    def get_all_files(files: List[Metadata.AudioFile], format: SuperAudioFormat) -> List[Metadata.AudioFile]:
        valid_files = []
        for file in files:
            if file.HasField("format") and SuperAudioFormat.get(file.format) == format:
                valid_files.append(file)
        return valid_files

    def get_audio(self, files: List[Metadata.AudioFile], preferred: AudioQuality) -> Metadata.AudioFile:
        if not files:
            return None
        matches = preferred.get_matches(files)
        if len(matches) > 0:
            return matches[0]
        return None

    def _get_fmt_name(self, fmt: Any) -> Any:
        try:
            return Metadata.AudioFile.Format.Name(fmt)
        except Exception:
            return fmt

    def get_file(self, files: List[Metadata.AudioFile]) -> Optional[Metadata.AudioFile]:
        # Note: AAC files currently are broken.
        vorbis_files = AutoFallbackAudioQuality.get_all_files(files, SuperAudioFormat.VORBIS)
        # aac_files = AutoFallbackAudioQuality.get_all_files(files, SuperAudioFormat.AAC)
        mp3_files = AutoFallbackAudioQuality.get_all_files(files, SuperAudioFormat.MP3)

        collected_valid_audio: List[Optional[Metadata.AudioFile]] = []
        collected_valid_audio.append(self.get_audio(vorbis_files, self.preferred))
        # collected_valid_audio.append(self.get_audio(aac_files, self.preferred))
        collected_valid_audio.append(self.get_audio(mp3_files, self.preferred))

        for other_fmt in self.other_quality:
            collected_valid_audio.append(self.get_audio(vorbis_files, other_fmt))
            # collected_valid_audio.append(self.get_audio(aac_files, other_fmt))
            collected_valid_audio.append(self.get_audio(mp3_files, other_fmt))

        collected_valid_audio = list(filter(lambda x: x is not None, collected_valid_audio))
        if not collected_valid_audio:
            self.logger.warning("Couldn't find any suitable matches, available {}")
            return None
        select_fmt = collected_valid_audio[0]
        self.logger.info(f"Selected audio format {self._get_fmt_name(select_fmt.format)}")
        return select_fmt
