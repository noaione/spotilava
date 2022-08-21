from typing import List, Optional, Union, cast

from librespot.audio.decoders import AudioQuality
from sanic.request import Request

from internals.spotify.shims import SpotifyAudioFormat

__all__ = (
    "get_spotify_audio_format",
    "get_spotify_audio_quality",
)


QueryParam = Optional[Union[str, List[str]]]


def select_first(single_or_multi: Union[str, List[str]]) -> str:
    if isinstance(single_or_multi, list):
        return single_or_multi[0]
    return single_or_multi


def get_spotify_audio_format(request: Request) -> Optional[SpotifyAudioFormat]:
    # Fallback from `format` to `fmt`
    query_param = cast(QueryParam, request.args.get("format") or request.args.get("fmt"))
    if query_param is None:
        return None
    query_param = select_first(query_param)

    query_param = query_param.lower()
    audio_mappings = {
        "mp3": SpotifyAudioFormat.MP3,
        "aac": SpotifyAudioFormat.AAC,
        "vorbis": SpotifyAudioFormat.VORBIS,
        "ogg": SpotifyAudioFormat.VORBIS,
        "m4a": SpotifyAudioFormat.AAC,
        "opus": SpotifyAudioFormat.VORBIS,
        "flac": SpotifyAudioFormat.FLAC,
        "hires": SpotifyAudioFormat.FLAC,
    }

    return audio_mappings.get(query_param)


def get_spotify_audio_quality(request: Request) -> Optional[AudioQuality]:
    # Fallback from `format` to `fmt`
    query_param = cast(QueryParam, request.args.get("q") or request.args.get("qual") or request.args.get("quality"))
    if query_param is None:
        return None

    query_param = query_param.lower()
    quality_mappings = {
        "lowest": AudioQuality.NORMAL,
        "low": AudioQuality.NORMAL,
        "lq": AudioQuality.NORMAL,
        "medium": AudioQuality.HIGH,
        "normal": AudioQuality.HIGH,
        "high": AudioQuality.VERY_HIGH,
        "hq": AudioQuality.VERY_HIGH,
        "highest": AudioQuality.VERY_HIGH,
    }

    return quality_mappings.get(query_param)
