"""
Fontes de "o que está tocando agora". Cada fonte tem:
    login()  -> prepara (login no Spotify, etc.)
    poll()   -> dict com a faixa atual, ou None se não houver nada tocando.

Formato devolvido por poll():
    {"id", "title", "artist", "album", "duration_ms",
     "playing": bool, "position_ms": int}
position_ms já vem corrigido pelo tempo que a consulta demorou.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

SCOPES = "user-read-playback-state user-read-currently-playing"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SIX_MONTHS = 180 * 24 * 3600


class FonteErro(Exception):
    """Erro com mensagem já pensada para o usuário (em português)."""


# ============================================================== Spotify
class SpotifyFonte:
    def __init__(self, client_id, redirect_port, token_path):
        self.client_id = client_id.strip()
        self.port = int(redirect_port)
        self.redirect_uri = f"http://127.0.0.1:{self.port}/callback"
        self.token_path = token_path
        self.tok = {}
        self.retry_after_until = 0.0
        self.aviso_expira = False

    # ---------- armazenamento
    def _load(self):
        try:
            with open(self.token_path, "r", encoding="utf-8") as f:
                self.tok = json.load(f)
        except Exception:
            self.tok = {}

    def _save(self):
        tmp = self.token_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.tok, f)
        os.replace(tmp, self.token_path)

    # ---------- OAuth PKCE (sem client secret)
    def _token_request(self, data):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(
            TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode())
            except Exception:
                err = {}
            raise FonteErro(f"O Spotify recusou o login ({e.code}): {err.get('error_description') or err.get('error') or ''}")
        except urllib.error.URLError as e:
            raise FonteErro(f"Sem internet para falar com o Spotify: {e.reason}")

    def _store(self, resp, keep_refresh=None):
        now = time.time()
        self.tok["access_token"] = resp["access_token"]
        self.tok["expires_at"] = now + int(resp.get("expires_in", 3600)) - 60
        if resp.get("refresh_token"):
            self.tok["refresh_token"] = resp["refresh_token"]
            self.tok["refresh_created_at"] = now  # o refresh token vale ~6 meses a partir daqui
        elif keep_refresh:
            self.tok["refresh_token"] = keep_refresh
        self.tok["client_id"] = self.client_id
        self._save()

    def login(self):
        if not self.client_id:
            raise FonteErro("Falta o Client ID do Spotify no config.json (veja o LEIA-ME).")
        self._load()
        if self.tok.get("refresh_token") and self.tok.get("client_id") == self.client_id:
            try:
                self._refresh()
                print("Spotify: já logado (sessão salva).")
                return
            except FonteErro as e:
                print(f"Spotify: sessão salva não serve mais ({e}). Vou pedir login de novo.")
        self._browser_login()

    def _browser_login(self):
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(16)
        result = {}
        done = threading.Event()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if urllib.parse.urlparse(self.path).path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                result["code"] = (q.get("code") or [None])[0]
                result["error"] = (q.get("error") or [None])[0]
                result["state"] = (q.get("state") or [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                msg = "Pronto! Pode fechar esta aba e voltar para o programa." if result["code"] else "Não deu certo. Volte ao programa e leia a mensagem."
                self.wfile.write(f"<html><body style='font-family:sans-serif'><h2>DePola Lyrics</h2><p>{msg}</p></body></html>".encode("utf-8"))
                done.set()

            def log_message(self, *a):
                pass

        try:
            srv = http.server.HTTPServer(("127.0.0.1", self.port), H)
        except OSError as e:
            raise FonteErro(f"A porta {self.port} já está em uso ({e}). Mude 'porta_login_spotify' no config.json "
                            "E o Redirect URI no painel do Spotify para o mesmo número.")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        params = {
            "client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
            "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state,
        }
        url = AUTH_URL + "?" + urllib.parse.urlencode(params)
        print("\nVou abrir o navegador para você entrar no Spotify e autorizar.")
        print("Se não abrir sozinho, copie este endereço e cole no navegador:\n" + url + "\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        ok = done.wait(300)
        srv.shutdown()
        if not ok:
            raise FonteErro("Tempo esgotado esperando o login (5 min).")
        if result.get("error") or not result.get("code"):
            raise FonteErro(f"Login cancelado ou recusado ({result.get('error')}).")
        if result.get("state") != state:
            raise FonteErro("Resposta de login com 'state' diferente. Tente de novo.")
        resp = self._token_request({
            "grant_type": "authorization_code", "code": result["code"], "redirect_uri": self.redirect_uri,
            "client_id": self.client_id, "code_verifier": verifier,
        })
        self._store(resp)
        print("Spotify: login feito com sucesso.")

    def _refresh(self):
        rt = self.tok.get("refresh_token")
        if not rt:
            raise FonteErro("Sem refresh token.")
        resp = self._token_request({"grant_type": "refresh_token", "refresh_token": rt, "client_id": self.client_id})
        self._store(resp, keep_refresh=rt)

    def _access(self):
        if time.time() >= self.tok.get("expires_at", 0):
            try:
                self._refresh()
            except FonteErro as e:
                print(f"Spotify: renovando o login... ({e})")
                self._browser_login()
        created = self.tok.get("refresh_created_at")
        if created and not self.aviso_expira and time.time() - created > SIX_MONTHS - 14 * 24 * 3600:
            self.aviso_expira = True
            print("AVISO: o login do Spotify vence em breve (dura 6 meses). Apague spotify_token.json e entre de novo.")
        return self.tok["access_token"]

    # ---------- leitura do player
    def poll(self):
        if time.time() < self.retry_after_until:
            raise FonteErro("(Spotify pediu para esperar um pouco; aguardando)")
        req = urllib.request.Request(
            API_URL + "/me/player?additional_types=track",
            headers={"Authorization": "Bearer " + self._access()},
        )
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status = r.status
                raw = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.tok["expires_at"] = 0
                raise FonteErro("(login expirou, renovando)")
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", "5"))
                self.retry_after_until = time.time() + wait
                raise FonteErro(f"(Spotify limitou as consultas; esperando {wait}s)")
            if e.code == 403:
                raise FonteErro("O Spotify respondeu 403: sua conta provavelmente NÃO está na lista de usuários do app "
                                "(painel do Spotify > seu app > Settings > User Management) ou o dono do app não tem Premium.")
            raise FonteErro(f"Erro do Spotify ({e.code}).")
        except (urllib.error.URLError, TimeoutError) as e:
            raise FonteErro(f"(sem conexão com o Spotify: {getattr(e, 'reason', e)})")
        t1 = time.monotonic()
        if status == 204 or not raw:
            return None
        d = json.loads(raw.decode("utf-8"))
        item = d.get("item")
        if not item or d.get("currently_playing_type") not in (None, "track"):
            return None  # anúncio, podcast ou nada tocando
        playing = bool(d.get("is_playing"))
        pos = int(d.get("progress_ms") or 0)
        if playing:
            # o Spotify mediu o progresso mais ou menos no meio da consulta
            pos += int((time.monotonic() - (t0 + t1) / 2) * 1000)
        artists = [a.get("name", "") for a in item.get("artists", [])]
        return {
            "id": item.get("id") or item.get("uri") or item.get("name"),
            "title": item.get("name", ""),
            "artist": artists[0] if artists else "",
            "artists": artists,
            "album": (item.get("album") or {}).get("name", ""),
            "duration_ms": int(item.get("duration_ms") or 0),
            "playing": playing,
            "position_ms": pos,
        }


# ============================================================== Windows
class WindowsFonte:
    """Lê o controle de mídia do Windows (o mesmo da tecla play/pause). EXPERIMENTAL / não testado."""

    def __init__(self, so_spotify=True):
        self.so_spotify = so_spotify
        self.loop = None
        self.mgr = None

    def login(self):
        try:
            import asyncio
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M  # noqa
        except Exception as e:
            raise FonteErro("Faltam pacotes do Windows para ler o player. Rode 'Instalar_fonte_windows.bat'. "
                            f"(detalhe: {e})")
        self._M = M
        self.loop = asyncio.new_event_loop()
        self.mgr = self.loop.run_until_complete(M.request_async())

    def _pick(self):
        sessions = list(self.mgr.get_sessions())
        if self.so_spotify:
            for s in sessions:
                if "spotify" in (s.source_app_user_model_id or "").lower():
                    return s
            return None
        return self.mgr.get_current_session() or (sessions[0] if sessions else None)

    def poll(self):
        import datetime
        s = self._pick()
        if s is None:
            return None
        props = self.loop.run_until_complete(s.try_get_media_properties_async())
        info = s.get_playback_info()
        tl = s.get_timeline_properties()
        status = int(info.playback_status)       # 4 = tocando, 5 = pausado
        if status not in (4, 5):
            return None
        pos = tl.position.total_seconds()
        if status == 4 and tl.last_updated_time is not None:
            now = datetime.datetime.now(datetime.timezone.utc)
            pos += max(0.0, (now - tl.last_updated_time).total_seconds())
        dur = (tl.end_time - tl.start_time).total_seconds()
        title, artist = props.title or "", props.artist or ""
        if not title:
            return None
        return {
            "id": f"{artist}|{title}", "title": title, "artist": artist, "artists": [artist],
            "album": props.album_title or "", "duration_ms": int(dur * 1000),
            "playing": status == 4, "position_ms": int(pos * 1000),
        }
