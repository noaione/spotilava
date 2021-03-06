# Spotilava Extension

This page will describe all of the Spotilava native extension that it's supported.

Here is the list:
- [Tidal](#tidal)
- [Deezer](#deezer) [Upcoming]

## Tidal

[Tidal](https://tidal.com/) is a Norwegian based high quality music streaming service developed by Square Inc. They mostly provide a much better audio quality even providing quality almost-master-like audio with [MQA](https://en.wikipedia.org/wiki/Master_Quality_Authenticated) codecs.

Suprisingly, Lavalink are able to decode MQA audio just fine even with some choking sometimes!

**NOTE**: You need Premium Account to use this feature, I haven't test it with free account!

### API Route

All of the route need to be prefixed with `/tidal`

- `/:track_id` get the metadata of the track ID. (JSON)
- `/:track_id/listen` get the track itself, returns the FLAC or M4A stream. (Binary)
- `/album/:album_id/` get the list of Album data. (JSON)
- `/playlist/:playlist_id` get the list of playlist data. (JSON)

It has the same format as the original API route except you need to prefix it with `/tidal` like this: `/tidal/:trackId/listen`

### Configuration

**Tidal is disabled by default**, so you need to enable it by adding this line into your `.env` file:

```js
ENABLE_TIDAL=1
```

After that, start the server and you should see the following line got printed into your console:

```c
[20xx-xx-xx XX:XX:XX HOSTNAME][INFO] (TidalAPI[12345]): _link_login: Please visit https://link.tidal.com and enter XXXXX to authorize
[20xx-xx-xx XX:XX:XX HOSTNAME][INFO] (TidalAPI[12345]): _link_login: The above link is valid for XXX seconds
```

It might be different, but you need to go to the URL and enter the code provided to authorize your Spotilava client with Tidal. The link will be valid whatever the next line said, so make sure you do it before that.

After that, Spotilava will automatically authorize it if you allow it.

```c
[20xx-xx-xx XX:XX:XX HOSTNAME][INFO] (TidalAPI[12345]): create: Tidal: User authorized!
[20xx-xx-xx XX:XX:XX HOSTNAME][INFO] (TidalAPI[12345]): create: Tidal: User ID: 12345
[20xx-xx-xx XX:XX:XX HOSTNAME][INFO] (TidalAPI[12345]): create: Tidal: Country Code: XXXX
```

If you change your account premium subscription, it might be the best to delete the saved token and reauthorize. You can delete the token at `config/tidal.json` from your root application directory.

### Hack and more

1. If the quality returned is in AAC/ALAC quality, Spotilava will need to download the whole file first to properly tag the file.
2. Spotilava will do `OFFLINE` request when requesting for download URL since it properly returns the Master Quality version. If it failed, we will fallback into `STREAM` request.

### Acknowledgments

This might not be possible without this following repository and wiki:

- [Tidal-Media-Downloader](https://github.com/yaronzz/Tidal-Media-Downloader): I used it as general idea for the link authorization and decryption.
- [Fokka-Engineering Tidal Wiki](https://github.com/Fokka-Engineering/TIDAL/wiki): This wiki contains a lot of API result and request that helps me a lot to figure out how some stuff works.

## Deezer

*Upcoming feature*
