#!/usr/bin/env python3
"""
DePola Lyrics - companheiro de Spotify (para PC).

O que faz:
  1. Descobre a música que está tocando (API do Spotify ou controle de mídia do Windows).
  2. Busca a letra sincronizada (LRC) no LRCLIB e converte em cues [inicioMs, fimMs, "texto"].
  3. Abre um servidor WebSocket local. No Minecraft você digita  /connect 127.0.0.1:8000
     e este programa manda comandos  "scriptevent lyr:sp_..."  para o addon.

O áudio continua tocando no Spotify, FORA do jogo. Só a letra vai para o Minecraft.
Só usa a biblioteca padrão do Python (3.8 ou mais novo).
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import time
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import lrc
import mini_ws
from fontes import FonteErro, SpotifyFonte, WindowsFonte

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
TOKEN_PATH = os.path.join(HERE, "spotify_token.json")
LRCLIB = "https://lrclib.net/api"
USER_AGENT = "DePolaLyrics-Companion/1.3.0 (uso pessoal; addon de Minecraft)"

DEFAULT_CONFIG = {
    "fonte": "windows",              # windows | spotify | auto
    "spotify_client_id": "",
    "porta_login_spotify": 8888,     # tem que ser igual ao Redirect URI cadastrado no painel do Spotify
    "porta_minecraft": 8000,         # a mesma do /connect 127.0.0.1:8000
    "so_spotify_no_windows": True,   # fonte windows: só olhar o app Spotify (False = qualquer player)
    "intervalo_consulta_s": 1.5,
    "tamanho_pedaco": 380,           # caracteres por comando (limite do jogo ~2048; na prática use bem menos)
    "intervalo_comandos_ms": 80,     # pausa entre comandos para não sobrecarregar o jogo
    "limite_caracteres_linha": 42,   # igual ao build_songs.py
    "tolerancia_duracao_s": 8,       # aceitar letra de versão com até X s de diferença na duração
    "pasta_cache": "",               # onde guardar as letras já baixadas ("" = pasta letras_cache ao lado do programa)
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print("Criei o arquivo config.json ao lado do programa.")
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    except Exception as e:
        sys.exit(f"ERRO: não consegui ler o config.json ({e}). Apague-o para recriar.")
    return cfg


# ===================================================================== LRCLIB
def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8"))


_EDITION = re.compile(r"\s*[-–(\[]\s*(remaster(ed)?|live|mono|stereo|deluxe|bonus|single version|radio edit|\d{4} ?(remaster|version)).*$", re.I)
_FEAT = re.compile(r"\s*[(\[]\s*(feat\.?|ft\.?|with)\s[^)\]]*[)\]]", re.I)


def title_variants(title):
    out = [title]
    t = _FEAT.sub("", title).strip()
    if t not in out:
        out.append(t)
    t2 = _EDITION.sub("", t).strip()
    if t2 and t2 not in out:
        out.append(t2)
    return out


def fetch_lyrics(track, tolerance_s=8):
    """Devolve ('ok', cues) | ('instrumental', None) | ('nolyrics', None) | ('erro', mensagem)."""
    dur_s = round(track["duration_ms"] / 1000)
    artist = track["artist"]
    last_error = None
    for title in title_variants(track["title"]):
        # 1) busca exata (artista + título + álbum + duração)
        q = {"artist_name": artist, "track_name": title, "album_name": track.get("album", ""), "duration": dur_s}
        try:
            d = _http_json(f"{LRCLIB}/get?" + urllib.parse.urlencode(q))
            if d.get("instrumental"):
                return "instrumental", None
            if d.get("syncedLyrics"):
                return "ok", d["syncedLyrics"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                last_error = f"LRCLIB respondeu {e.code}"
        except Exception as e:
            last_error = f"sem conexão com o LRCLIB ({getattr(e, 'reason', e)})"
        # 2) busca aproximada: escolhe a de duração mais próxima que tenha letra sincronizada
        try:
            res = _http_json(f"{LRCLIB}/search?" + urllib.parse.urlencode({"track_name": title, "artist_name": artist}))
            best = None
            for r in res:
                if not r.get("syncedLyrics"):
                    continue
                diff = abs((r.get("duration") or 0) - dur_s)
                if diff <= tolerance_s and (best is None or diff < best[0]):
                    best = (diff, r)
            if best:
                return "ok", best[1]["syncedLyrics"]
        except Exception as e:
            last_error = last_error or f"falha na busca do LRCLIB ({getattr(e, 'reason', e)})"
    if last_error:
        return "erro", last_error
    return "nolyrics", None


def fetch_cues(track, tolerance_s=8):
    kind, data = fetch_lyrics(track, tolerance_s)
    if kind != "ok":
        return kind, data
    cues = lrc.parse_lrc(data)
    return ("ok", cues) if cues else ("nolyrics", None)


def copy_to_clipboard(text):
    """Copia o texto para a área de transferência do Windows (comando clip). Falha em silêncio."""
    try:
        subprocess.run(["clip"], input=text.encode("ascii"), check=True, timeout=5)
        return True
    except Exception:
        return False


# ===================================================================== codificação
def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def track_tid(track):
    return "k" + hashlib.sha1((str(track["id"]) + "|" + str(track["duration_ms"])).encode("utf-8")).hexdigest()[:6]


def make_chunks(tid, track, cues, size):
    payload = {"t": track["title"], "a": track["artist"], "d": track["duration_ms"], "c": cues}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    enc = b64u(raw)
    parts = [enc[i:i + size] for i in range(0, len(enc), size)] or [""]
    n = len(parts)
    return [f"{tid}.{i}.{n}.{p}" for i, p in enumerate(parts)]


# ===================================================================== modelo de posição
class Model:
    def __init__(self):
        self.track = None
        self.anchor_pos = 0.0
        self.anchor_t = 0.0
        self.playing = False

    def position(self):
        if self.playing:
            return self.anchor_pos + (time.monotonic() - self.anchor_t) * 1000
        return self.anchor_pos

    def anchor(self, pos, playing):
        self.anchor_pos = float(pos)
        self.anchor_t = time.monotonic()
        self.playing = playing


# ===================================================================== programa
class Companion:
    SEEK_MS = 1200      # salto maior que isso = o usuário pulou/voltou na música
    SOFT = 0.15         # correção suave de pequenas diferenças

    def __init__(self, cfg, source, lyrics_fn=None, log=print):
        self.cfg = cfg
        self.source = source
        self.lyrics_fn = lyrics_fn or (lambda t: fetch_cues(t, cfg["tolerancia_duracao_s"]))
        self.log = log
        self.model = Model()
        self.pool = ThreadPoolExecutor(max_workers=1)      # fonte de música: sempre na mesma thread
        self.lyr_pool = ThreadPoolExecutor(max_workers=2)  # LRCLIB
        self.conn = None
        self.sent_ok = 0
        self.errs_logged = 0
        # estado do que precisa ir para o jogo
        self.pos_dirty = False
        self.status_queue = []     # mensagens "status" pendentes (alta prioridade)
        self.data_queue = []       # pedaços da letra (baixa prioridade)
        self.cur_tid = None
        self.cur_chunks = None     # pedaços da letra da faixa atual (para reenviar)
        self.cur_status = None     # ('nolyrics'|'idle'|'loading', info)
        self.cache = {}            # track id -> (kind, data)
        self.cache_dir = cfg.get("pasta_cache") or os.path.join(HERE, "letras_cache")
        self.last_err = None
        lrc.MAX_LINE_CHARS = int(cfg["limite_caracteres_linha"])
        chunk = int(cfg["tamanho_pedaco"])
        self.chunk = max(100, min(chunk, 1500))

    # ---------------- cache de letras no disco (músicas já ouvidas funcionam sem internet)
    def _disk_path(self, track_id):
        return os.path.join(self.cache_dir, hashlib.sha1(str(track_id).encode("utf-8")).hexdigest()[:20] + ".json")

    def _disk_get(self, track_id):
        try:
            with open(self._disk_path(track_id), "r", encoding="utf-8") as f:
                cues = json.load(f)["cues"]
            if cues and all(isinstance(c, list) and len(c) == 3 for c in cues):
                return cues
        except Exception:
            pass
        return None

    def _disk_put(self, track_id, track, cues):
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._disk_path(track_id), "w", encoding="utf-8") as f:
                json.dump({"title": track["title"], "artist": track["artist"], "cues": cues}, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------------- envio ao Minecraft
    def _wire(self, kind, msg):
        return {
            "header": {"version": 1, "requestId": hashlib.md5(f"{time.time()}{kind}{msg[:20]}".encode()).hexdigest(),
                       "messagePurpose": "commandRequest", "messageType": "commandRequest"},
            "body": {"version": 1, "commandLine": f"scriptevent lyr:sp_{kind} {msg}", "origin": {"type": "player"}},
        }

    async def _send(self, kind, msg):
        if self.conn and not self.conn.closed:
            await self.conn.send_text(json.dumps(self._wire(kind, msg)))
            self.sent_ok += 1

    def pos_message(self):
        m = self.model
        return f"{self.cur_tid}.{max(0, int(m.position()))}.{'p' if m.playing else 's'}"

    async def sender_loop(self):
        gap = int(self.cfg["intervalo_comandos_ms"]) / 1000
        next_hb = time.monotonic() + 3
        next_resend = time.monotonic() + 30
        while True:
            await asyncio.sleep(gap)
            if not self.conn or self.conn.closed:
                continue
            now = time.monotonic()
            if now >= next_hb:
                next_hb = now + 3
                if self.cur_tid and self.model.track:
                    self.pos_dirty = True
            if now >= next_resend:
                next_resend = now + 30
                if self.cur_chunks and not self.data_queue:
                    self.data_queue = list(self.cur_chunks)
            try:
                if self.status_queue:
                    kind, msg = self.status_queue.pop(0)
                    await self._send(kind, msg)
                elif self.pos_dirty and self.cur_tid and self.cur_chunks is not None and self.model.track:
                    self.pos_dirty = False
                    await self._send("pos", self.pos_message())   # montada AGORA, com a posição de agora
                elif self.data_queue:
                    await self._send("data", self.data_queue.pop(0))
            except Exception as e:
                self.log(f"Falha ao enviar ao Minecraft: {e}")

    async def on_connect(self, conn):
        if self.conn and not self.conn.closed:
            self.conn.close()
        self.conn = conn
        self.log("\n>>> Minecraft conectado! Ligue o botão '🎧 Spotify' no menu do item.")
        self.status_queue.append(("hello", "1"))
        if self.cur_status:
            self.status_queue.append((self.cur_status[0], self.cur_status[1]))
        if self.cur_chunks:
            self.data_queue = list(self.cur_chunks)
            self.pos_dirty = True
        try:
            while True:
                text = await conn.recv()
                if text is None:
                    break
                self._on_mc_message(text)
        finally:
            if self.conn is conn:
                self.conn = None
            self.log("\n>>> Minecraft desconectou. No jogo, digite /connect de novo para reconectar.")

    def _on_mc_message(self, text):
        try:
            d = json.loads(text)
        except Exception:
            return
        if d.get("header", {}).get("messagePurpose") == "commandResponse":
            body = d.get("body", {})
            if body.get("statusCode", 0) != 0 and self.errs_logged < 5:
                self.errs_logged += 1
                self.log(f"Minecraft recusou um comando: {body.get('statusMessage')} "
                         "(se for sobre tamanho, diminua 'tamanho_pedaco' no config.json)")

    # ---------------- faixa atual
    def _queue_status(self, kind, info="x"):
        self.cur_status = (kind, info)
        self.status_queue.append((kind, info))

    async def new_track(self, obs):
        m = self.model
        m.track = obs
        m.anchor(obs["position_ms"], obs["playing"])
        self.cur_tid = track_tid(obs)
        self.cur_chunks = None
        self.data_queue = []
        self.pos_dirty = False
        label = f"{obs['artist']} - {obs['title']}"
        self.log(f"\n♫ {label}")
        self._queue_status("loading")
        tid = self.cur_tid
        cached = self.cache.get(obs["id"])
        if cached is None:
            disk = self._disk_get(obs["id"])
            if disk:
                cached = ("ok", disk)
                self.log("   (letra já estava salva no PC)")
        if cached is None:
            cached = await asyncio.get_running_loop().run_in_executor(self.lyr_pool, self.lyrics_fn, obs)
            if cached[0] == "ok":
                self._disk_put(obs["id"], obs, cached[1])
        if obs["id"] not in self.cache:
            if cached[0] != "erro":
                self.cache[obs["id"]] = cached
                if len(self.cache) > 60:
                    self.cache.pop(next(iter(self.cache)))
        if self.cur_tid != tid:
            return  # o usuário já trocou de música enquanto buscava
        kind, data = cached
        if kind == "ok":
            self.cur_chunks = make_chunks(tid, obs, data, self.chunk)
            self.data_queue = list(self.cur_chunks)
            self.cur_status = None
            self.pos_dirty = True
            self.log(f"   letra: {len(data)} linhas ({len(self.cur_chunks)} comandos)")
        elif kind == "instrumental":
            self.log("   instrumental (sem letra)")
            self._queue_status("nolyrics", b64u(("♪ " + obs["title"] + " (instrumental)").encode("utf-8"))[:300])
        elif kind == "nolyrics":
            self.log("   AVISO: não achei letra sincronizada no LRCLIB para esta faixa.")
            self._queue_status("nolyrics", b64u(obs["title"].encode("utf-8"))[:300])
        else:
            self.log(f"   AVISO: erro ao buscar letra: {data}")
            self._queue_status("nolyrics", b64u(obs["title"].encode("utf-8"))[:300])

    async def handle_obs(self, obs):
        m = self.model
        if obs is None:
            if m.track is not None:
                self.log("\n(nada tocando)")
                m.track = None
                self.cur_tid = None
                self.cur_chunks = None
                self.data_queue = []
                self._queue_status("idle")
            return
        if m.track is None or obs["id"] != m.track["id"]:
            await self.new_track(obs)
            return
        if obs["playing"] != m.playing:
            m.anchor(obs["position_ms"], obs["playing"])
            self.pos_dirty = True
            self.log("   ▶ continuou" if obs["playing"] else "   ⏸ pausou")
            return
        expected = m.position()
        drift = obs["position_ms"] - expected
        if m.playing:
            if abs(drift) > self.SEEK_MS:
                m.anchor(obs["position_ms"], True)
                self.pos_dirty = True
                self.log(f"   ⇆ pulou para {obs['position_ms'] / 1000:.1f}s")
            else:
                m.anchor(expected + drift * self.SOFT, True)   # correção suave, sem ressincronizar no jogo
        elif abs(drift) > 300:
            m.anchor(obs["position_ms"], False)
            self.pos_dirty = True

    async def poll_loop(self):
        loop = asyncio.get_running_loop()
        interval = float(self.cfg["intervalo_consulta_s"])
        while True:
            try:
                obs = await loop.run_in_executor(self.pool, self.source.poll)
                self.last_err = None
                await self.handle_obs(obs)
            except FonteErro as e:
                if str(e) != self.last_err:
                    self.last_err = str(e)
                    self.log(f"AVISO: {e}")
            except Exception as e:  # nunca deixar o programa cair por um erro de rede
                if str(e) != self.last_err:
                    self.last_err = str(e)
                    self.log(f"AVISO: erro inesperado ao consultar a música: {e!r}")
            await asyncio.sleep(interval)

    async def run(self):
        port = int(self.cfg["porta_minecraft"])
        try:
            server = await mini_ws.serve("127.0.0.1", port, self.on_connect)
        except OSError as e:
            sys.exit(f"ERRO: a porta {port} está ocupada ({e}). Feche outro programa ou mude 'porta_minecraft' no config.json.")
        cmd = f"/connect 127.0.0.1:{port}"
        copied = copy_to_clipboard(cmd)
        self.log("\n==================================================")
        self.log(" Companheiro pronto. NO MINECRAFT, digite no chat:")
        self.log(f"      {cmd}")
        if copied:
            self.log(" (já copiei para você: abra o chat e aperte Ctrl+V)")
        self.log(" (o mundo precisa estar com cheats/trapaças ligados)")
        self.log("==================================================\n")
        async with server:
            await asyncio.gather(self.poll_loop(), self.sender_loop())


def build_source(cfg):
    fonte = cfg["fonte"]
    if fonte == "auto":
        fonte = "spotify" if cfg["spotify_client_id"].strip() else "windows"
        print(f"Fonte escolhida automaticamente: {fonte}")
    if fonte == "spotify":
        return SpotifyFonte(cfg["spotify_client_id"], cfg["porta_login_spotify"], TOKEN_PATH)
    if fonte == "windows":
        return WindowsFonte(cfg["so_spotify_no_windows"])
    sys.exit("ERRO: 'fonte' no config.json deve ser auto, spotify ou windows.")


def main():
    cfg = load_config()
    source = build_source(cfg)
    comp = Companion(cfg, source)
    try:
        comp.pool.submit(source.login).result()
    except FonteErro as e:
        sys.exit(f"\nERRO: {e}")
    try:
        asyncio.run(comp.run())
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == "__main__":
    main()
