# Spotilava 🎵
A webserver acting as an intermediary between lavaplayer/lavalink and Spotify.

This webserver is an actual Spotify player and not using Youtube or something like that.

**THIS ONLY WORKS ON PREMIUM ACCOUNT**

## Disclaimer

I am not responsible if your account got banned, this webserver still possibly breaks Spotify ToS since it falls into account sharing.

## Requirements

- Python 3.8+ (I haven't tested with Python 3.6/3.7)
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

- `/:track_id` fetch the metadata of the track ID. (JSON)
- `/:track_id/listen` fetch the track itself, returns the OGG Vorbis stream. (Binary)
- `/album/:album_id/` get the list of Album data. (JSON)
- `/playlist/:playlist_id` get the list of playlist data. (JSON)

The other API can be used to fetch about playlist/album/track information before requesting lavaplayer the real URL (`/:track_id/listen`).

I'm planning to implement support for Shows/Podcast too.

## How it works?

I'm using an external library called [librespot-python](https://github.com/kokarare1212/librespot-python) which is still maintained and use the original [librespot](https://github.com/librespot-org/librespot) implementation which is an Open Spotify Client.

The program will then request the input stream of the file with `librespot-python` help, and then will do this:

1. Request the first x bytes (default to 4096 bytes)
2. Inject that bytes with OGG metadata so lavalink will parse it correctly.
3. Return a stream response with [Sanic](https://sanicframework.org/en/guide/advanced/streaming.html#response-streaming) which will send the injected bytes then the remainder of the file.
4. Lavaplayer will happily accept the data and not broke apart hopefully.

## Current Problems

1. Lavalink/Lavaplayer cannot parse the correct duration, so you need a way to inject the correct metadata in your bot.

![Showcase #1](https://p.ihateani.me/ryxzjpok.png)

Lavaplayer would just return an `UNDEFINED_LENGTH` a.k.a the longest number you can put on Java.

2. librespot sometimes failed with error: `spotify.APReponseMessage`

I cannot fix this currently since this is most likely a failure from `librespot-python` itself. You can just start the server again to see if it's works.

3. Spotify would froze at `Created new session! device_id xxxxxxxxx` and not finished connecting.

This problem is unknown to me currently, this would also make your terminal (in Windows?) cannot be stopped, you need to close the whole terminal.

Just rerun the `app.py` again and see if it would froze at that section again.

## License

This project is licensed with [MIT License]([LICENSE](https://github.com/noaione/spotilava/blob/master/LICENSE)).

## Donate

If you like this project, consider donating to me: https://n4o.xyz/#/donate

