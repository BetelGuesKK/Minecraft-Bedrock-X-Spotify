"""
Servidor WebSocket mínimo (só biblioteca padrão do Python, nada para instalar).
Suficiente para o /connect do Minecraft Bedrock: aceita UMA ou mais conexões,
envia texto e lê texto/ping/close.
"""
import asyncio
import base64
import hashlib
import struct

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WSConnection:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.closed = False
        self.peer = writer.get_extra_info("peername")

    async def send_text(self, text):
        if self.closed:
            return
        data = text.encode("utf-8")
        head = bytearray([0x81])  # FIN + texto
        n = len(data)
        if n < 126:
            head.append(n)
        elif n < 65536:
            head.append(126)
            head += struct.pack(">H", n)
        else:
            head.append(127)
            head += struct.pack(">Q", n)
        self.writer.write(bytes(head) + data)
        await self.writer.drain()

    async def _send_control(self, opcode, payload=b""):
        if self.closed:
            return
        self.writer.write(bytes([0x80 | opcode, len(payload)]) + payload)
        await self.writer.drain()

    async def recv(self):
        """Devolve uma mensagem de texto, ou None quando a conexão fechar."""
        buf = b""
        while True:
            try:
                b1, b2 = await self.reader.readexactly(2)
                fin, opcode = b1 & 0x80, b1 & 0x0F
                masked, n = b2 & 0x80, b2 & 0x7F
                if n == 126:
                    n = struct.unpack(">H", await self.reader.readexactly(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", await self.reader.readexactly(8))[0]
                mask = await self.reader.readexactly(4) if masked else b""
                payload = await self.reader.readexactly(n) if n else b""
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                self.closed = True
                return None
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:      # close
                try:
                    await self._send_control(0x8)
                except Exception:
                    pass
                self.closed = True
                return None
            if opcode == 0x9:      # ping
                try:
                    await self._send_control(0xA, payload)
                except Exception:
                    pass
                continue
            if opcode == 0xA:      # pong
                continue
            buf += payload
            if fin:
                return buf.decode("utf-8", errors="replace")

    def close(self):
        self.closed = True
        try:
            self.writer.close()
        except Exception:
            pass


async def serve(host, port, on_connect):
    """on_connect(conn) é uma corrotina chamada a cada conexão nova."""

    async def handle(reader, writer):
        try:
            req = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        except Exception:
            writer.close()
            return
        headers = {}
        for line in req.decode("latin-1").split("\r\n")[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        key = headers.get("sec-websocket-key")
        if not key or "websocket" not in headers.get("upgrade", "").lower():
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        writer.write(
            ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode()
        )
        await writer.drain()
        conn = WSConnection(reader, writer)
        try:
            await on_connect(conn)
        finally:
            conn.close()

    return await asyncio.start_server(handle, host, port)
