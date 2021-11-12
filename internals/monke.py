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

Some monkeypatching for librespot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Type, Union

import librespot.audio
from librespot.audio import CdnFeedHelper
from librespot.metadata import EpisodeId, PlayableId, TrackId

from .audio import AutoFallbackAudioQuality
from .errors import NoAudioFound, NoTrackFound

if TYPE_CHECKING:
    from librespot.audio import PlayableContentFeeder, Session
    from librespot.audio.decoders import AudioQuality
    from librespot.proto import Metadata_pb2 as Metadata
    from librespot.structure import HaltListener


def load_track_with_fallback(
    self: Type[PlayableContentFeeder],
    track_id_or_track: Union[TrackId, Metadata.Track],
    audio_quality: AudioQuality,
    preload: bool,
    halt_listener: HaltListener,
):
    session: Session = getattr(self, "__session", getattr(self, "_PlayableContentFeeder__session", None))
    if type(track_id_or_track) is TrackId:
        original = session.api().get_metadata_4_track(track_id_or_track)
        track = self.pick_alternative_if_necessary(original)
        if track is None:
            self.logger.error(f"Unable to find track to be played on with this account")
            raise NoTrackFound
    else:
        track = track_id_or_track

    selected_audio = AutoFallbackAudioQuality(audio_quality).get_file(track.file)
    if selected_audio is None:
        self.logger.fatal("Couldn't find any suitable audio file: available: {}".format(track.file))
        raise NoAudioFound
    return self.load_stream(selected_audio, track, None, preload, halt_listener)


def load_episode_with_fallback(
    self: Type[PlayableContentFeeder],
    episode_id: EpisodeId,
    audio_quality: AudioQuality,
    preload: bool,
    halt_listener: HaltListener,
):
    session: Session = getattr(self, "__session", getattr(self, "_PlayableContentFeeder__session", None))
    episode = session.api().get_metadata_4_episode(episode_id)
    if episode.external_url:
        return CdnFeedHelper.load_episode_external(session, episode, halt_listener)

    selected_audio = AutoFallbackAudioQuality(audio_quality).get_file(episode.audio)
    if selected_audio is None:
        self.logger.fatal("Couldn't find any suitable audio file: available: {}".format(episode.audio))
        raise NoAudioFound
    return self.load_stream(selected_audio, None, episode, preload, halt_listener)


def monkeypatch_load():
    def load_with_fallback(
        self: Type[PlayableContentFeeder],
        playable_id: PlayableId,
        audio_quality: AudioQuality,
        preload: bool,
        halt_listener: HaltListener,
    ):
        if type(playable_id) is TrackId:
            return load_track_with_fallback(self, playable_id, audio_quality, preload, halt_listener)
        elif type(playable_id) is EpisodeId:
            return load_episode_with_fallback(self, playable_id, audio_quality, preload, halt_listener)
        else:
            raise TypeError("Unknown content: {}".format(playable_id))

    librespot.audio.PlayableContentFeeder.load = load_with_fallback
