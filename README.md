# Minecraft-Bedrock-X-Spotify
Minecraft Bedrock addon that shows synchronized song lyrics in the world, with a Windows companion that follows what's playing in Spotify. No Premium or API needed.
# DePola Lyrics 1.3.0 – Spotify lyrics mode

A Minecraft Bedrock addon that displays synchronized lyrics floating in the world, line by line, in front of the player.
Version 1.3.0 adds a **🎧 Spotify** button: your music keeps playing in the Spotify desktop app (outside the game),
and the addon shows the matching lyrics in real time.

## How it works

1. A small Python companion for Windows reads what is playing from the Windows media controls.
   It needs no Spotify API, no login and no Premium account.
2. It fetches synchronized lyrics (LRC) from [LRCLIB](https://lrclib.net) and converts them into the addon's cue format.
3. It opens a local WebSocket server. In Minecraft you run "/connect 127.0.0.1:8000",
   and the companion sends "scriptevent lyr:sp_..." commands that the addon turns into floating lyrics.
4. Pause, skip, seek and track changes are re-synced automatically.
   Lyrics already downloaded are cached on disk, so songs you've played before work offline.

Each player keeps their own settings (box, scale, font, sync offset) and the privacy option still applies.
The addon never touches audio.

## Install

1. Open `DePola Lyrics 1.3.0 Spotify.mcaddon` to import the addon. Enable both packs in your world and turn on cheats.
2. Run `Instalar obrigatório.bat` once (it installs the required Python packages and tries to install Python if missing).
3. Run `Iniciar Spotify.bat` and keep the window open. It copies `/connect 127.0.0.1:8000` to your clipboard.
4. In Minecraft, paste it into the chat. Then use the item menu → **🎧 Spotify** and play a song in the Spotify desktop app.

If the lyrics are early or late, adjust **Settings → Sync (ms)** in the item menu.

## Requirements

- Windows 10/11 with Minecraft Bedrock Edition
- Spotify desktop app (a Free account works)
- Python 3 (the installer tries to set it up)
- A world with cheats enabled (needed for `/connect`; this disables achievements in that world)

## Limitations

- Windows only. Playback on a phone or another device is not detected.
- Lyrics depend on LRCLIB having synchronized lyrics for the track.
- Sync accuracy depends on the position that Spotify reports to Windows. Use the sync offset to compensate.
- Experimental; tested by the author on a single setup.


## Troubleshooting

### "/connect" fails or the companion never says "Minecraft connected"

1. **Turn off encrypted websockets (the most common cause).**
   In Minecraft go to **Settings → General → Profile** and switch **Require Encrypted Websockets** OFF.
   If you see "Encrypted Session Required", this is the fix. The companion uses a plain (unencrypted) local WebSocket.
2. **Use `127.0.0.1`, not `localhost`:** `/connect 127.0.0.1:8000`
3. **Cheats must be enabled** in the world (this disables achievements in that world).
4. **Connect from inside the world you are playing.** If you connect in a singleplayer world and then join a server,
   commands sent over the websocket will not work.
5. **Is the companion running?** The `Iniciar Spotify.bat` window must stay open and say "Companheiro pronto".
6. **Port already in use:** edit `fontes/config.json` and change `porta_minecraft` (e.g. `8001`),
   then use the same number in `/connect`.
7. **Windows loopback / firewall (may be needed on some setups):** if Minecraft still cannot reach `127.0.0.1`,
   allow the companion/Python through the Windows firewall prompt on first run (private networks), or try
   `CheckNetIsolation LoopbackExempt -a -n="Microsoft.MinecraftUWP_8wekyb3d8bbwe"` in an **administrator** terminal,
   then restart Minecraft. The package name can differ between Minecraft versions.
8. To disconnect, type `/connect off`. To reconnect, run `/connect` again (the companion keeps running).

### Connected, but no lyrics appear in the world

- Open the item menu and make sure **🎧 Spotify** shows **(ligado / on)**. Choosing a built-in song or "Stop music" turns it off.
- Both packs (Behavior and Resource) must be enabled in the world.
- Play the song in the **Spotify desktop app for Windows** on the same PC. Playback on a phone/other device is not detected.
  The browser player may not be detected; if you want to use another player, set `"so_spotify_no_windows": false` in `fontes/config.json`.
- Check the companion window: if it says it found no synchronized lyrics, LRCLIB has none for that track.
- If the companion window shows commands being rejected, lower `tamanho_pedaco` in `fontes/config.json` (e.g. `250`).
- If the companion stops responding for ~11 seconds, the lyrics freeze until it comes back.

### Lyrics are early, late, or drift

- Use the item menu → **Settings → Sync (ms)** to compensate (each player has their own offset).
- Sync depends on the playback position Spotify reports to Windows, which can lag slightly.
- After a pause or seek the lyrics re-sync automatically; if they don't, pause and resume once.

### Installer / startup problems

- **"Python not found":** install Python 3 from python.org and tick **Add python.exe to PATH**, then run `Instalar obrigatório.bat` again.
- **`pip install` fails:** check your internet connection and try again. The Windows media packages (`winrt-*`) may require a recent Python (3.9+ is recommended).
- **"Faltam pacotes do Windows" at startup:** run `Instalar obrigatório.bat` again.
- **Nothing detected while music plays:** open the Windows media overlay (volume/media keys). If Spotify does not appear there,
  the companion cannot see it either. Restart the Spotify app.
- **Old lyrics keep showing for a track:** delete the `fontes/letras_cache` folder to force a fresh download.

### Still stuck?

Open an issue and paste the text from the companion window (remove anything personal).

## Disclaimer

Not affiliated with, endorsed by, or sponsored by Spotify, Mojang or Microsoft.
Lyrics are fetched from LRCLIB and belong to their respective rights holders.
