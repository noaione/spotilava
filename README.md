# Spotilava 🎵
A webserver acting as an intermediary between lavaplayer/lavalink and Spotify.

This webserver is an actual Spotify player and not using Youtube or something like that.

**THIS ONLY WORKS ON PREMIUM ACCOUNT**

## Disclaimer

I am not responsible if your account got banned, this webserver still possibly breaks Spotify ToS since it falls into account sharing.

I would recommend a burner premium account.

## Features
- [x] API routes to fetch Album/Playlist/Artist/Show information (including Track and Episode)
- [x] Support listening to Track natively
- [x] Support listening to Podcast/episode natively
- [x] Automatically use the best possible audio quality and format
  - The fallback is as follows: `Vorbis` -> `MP3` (AAC is currently disabled because it's broken)
  - It will also take account the audio quality. (`VERY_HIGH` > `HIGH` > `NORMAL`)
- [x] Automatic metadata injection if needed w/ mutagen (so Lavalink/Lavaplayer parse it properly.)
- [x] Asynchronous from the start (Powered with [Sanic](https://sanicframework.org/))
- [x] Support fetching Spotify lyrics (which powered by Musixmatch)

## Requirements

- Python 3.7+ (Tested on Python 3.8, Python 3.9)
- Spotify Premium Account
- A server to host this.

## Usage

To use this webserver, you need to prepare a python virtual environment.

1. Install `virtualenv` if you dont have it. (`pip install virtualenv -U`)
2. Create a new virtualenv with `virtualenv venv`
3. Enter your virtualenv with:
   - Windows: `.\venv\Scripts\activate`
   - Linux/Mac: `source ./venv/bin/activate`
4. Install all the requirements:
   - `pip install -U -r requirements.txt`
5. Rename the `.env.example` file to `.env` and fill in.
   - More info: [Configuration](#configuration)
6. Start the server with `python3 app.py`, make sure you're in the virtualenv.
7. Start requesting with Lavalink with this URL format:
   - `https://127.0.0.1:37784/:track_id/listen`
   - `:track_id` need to be changed into Spotify hex ID, for example:
     - The link `https://open.spotify.com/track/5erw0k8hLca8iP36AhFMsE` will have the track ID of: `5erw0k8hLca8iP36AhFMsE`

## Configuration

In `.env.example` you will find 3 options:
- `SPOTILAVA_USERNAME`, fill this with your Spotify email or username
- `SPOTILAVA_PASSWORD`, fill this with your Spotify password
- `SPOTILAVA_CHUNK_SIZE`, the chunk size of the send.
  Please make sure it's a multiple of 8 and not less than 4096, I recommend not changing it.

## API Route

- `/:track_id` get the metadata of the track ID. (JSON)
- `/:track_id/listen` get the track itself, returns the OGG Vorbis or MP3 stream. (Binary)
- `/:track_id/lyrics` get the track lyrics (if available) (JSON)
- `/album/:album_id/` get the list of Album data. (JSON)
- `/playlist/:playlist_id` get the list of playlist data. (JSON)
- `/show/:show_id/` get the list of Show/Podcast data. (JSON)
- `/artist/:artist_id/` get the list of artist top tracks. (JSON) **[See note at the bottom]**
- `/episode/:episode_id` get the metadata of a podcast episode. (JSON)
- `/episode/:episode_id/listen` get the episode itself, returns an OGG Vorbis or MP3 stream. (Binary)

The other API can be used to fetch about playlist/album/track information before requesting lavaplayer the real URL (`/:track_id/listen`).

~~I'm planning to implement support for Shows/Podcast too.~~
Implemented since commit: [`d54fdd9`](https://github.com/noaione/spotilava/commit/d54fdd9045d5e54460e72ec65a1f43d97b72267f)

**Note on top artist tracks**:<br>
It will use your account country as what the top tracks are for the artist in that country.

## Extensions

Spotilava includes some extension that support other premium music provider like Tidal and more, learn more [here](EXTENSIONS.md).

## How it works?

I'm using an external library called [librespot-python](https://github.com/kokarare1212/librespot-python) which is still maintained and use the original [librespot](https://github.com/librespot-org/librespot) implementation which is an Open Spotify Client.

The program will then request the input stream of the file with `librespot-python` help, and then will do this:

1. Request the first x bytes (default to 4096 bytes)
2. Check what file format it's (MP3 or Vorbis)
3. Inject the metadata if possible.
4. Return a stream response with [Sanic](https://sanicframework.org/en/guide/advanced/streaming.html#response-streaming) which will send the injected bytes then the remainder of the file.
5. Lavaplayer will happily accept the data and not broke apart hopefully.

## Current Problems

1. Lavalink/Lavaplayer cannot parse the correct duration, so you need a way to inject the correct metadata in your bot.

![Showcase #1](https://p.ihateani.me/ryxzjpok.png)

Lavaplayer would just return an `UNDEFINED_LENGTH` a.k.a the longest number you can put on Java.

2. librespot sometimes failed with error: `spotify.APReponseMessage`

I cannot fix this currently since this is most likely a failure from `librespot-python` itself. You can just start the server again to see if it's works.

3. ~~Spotify would froze at `Created new session! device_id xxxxxxxxx` and not finished connecting.~~

This problem might be fixed at commit [`d1f951f`](https://github.com/noaione/spotilava/commit/d1f951f92cad198a784aa32109822f0701817174) since the upstream `librespot-python` fixes the freezing if the previous auth failed, or the client is not disconnected properly.

4. Lavaplayer/Lavalink sometimes will throws error at the very end of the tracks

Unknown problems to me, some tracks (mainly OGG one) will throws errors after the track playback is ended. See [`#4`](https://github.com/noaione/spotilava/issues/4)

## License

This project is licensed with [MIT License]([LICENSE](https://github.com/noaione/spotilava/blob/master/LICENSE)).

## Donate

If you like this project, consider donating to me: https://n4o.xyz/#/donate

