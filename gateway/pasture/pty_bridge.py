"""PTY <-> WebSocket bridge.

The client picks a kind and target; the providers turn that into a fixed
argv (never a shell string). The process runs in a new session on a fresh
PTY. Binary frames carry terminal bytes both ways; text frames carry JSON
control messages ({"t":"resize","cols","rows"}, {"t":"ping"}).

Closing the socket hangs up only the client process (herdr attach, tmux
attach, or a plain shell); herdr panes and tmux sessions live on.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import json
import logging
import os
import shutil
import signal
import struct
import termios

from aiohttp import WSMsgType, web

log = logging.getLogger("pasture.pty")

READ_CHUNK = 65536
HIGH_WATER = 1 << 20
LOW_WATER = 256 << 10
IDLE_CLOSE = 3600
MAX_PTYS_PER_SESSION = 4

CLOSE_EXPIRED = 4401
CLOSE_IDLE = 4408


def _winsize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def clamp_size(cols, rows) -> tuple[int, int]:
    try:
        cols, rows = int(cols), int(rows)
    except (TypeError, ValueError):
        return 80, 24
    return max(10, min(cols, 500)), max(4, min(rows, 300))


class Pty:
    def __init__(self, argv: list[str], env: dict[str, str], cwd: str, cols: int, rows: int):
        self.argv = argv
        self.env = env
        self.cwd = cwd
        self.cols, self.rows = cols, rows
        self.pid = -1
        self.fd = -1
        self.status: int | None = None

    def spawn(self) -> None:
        # Prepare everything before fork so the child does as little as
        # possible: chdir, set the window size, execve.
        program = self.argv[0]
        if "/" not in program:
            program = shutil.which(program, path=self.env.get("PATH")) or program
        argv = [os.fsencode(program)] + [os.fsencode(a) for a in self.argv[1:]]
        env = {os.fsencode(k): os.fsencode(v) for k, v in self.env.items()}
        cwd = os.fsencode(self.cwd)
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        pid, fd = os.forkpty()
        if pid == 0:  # child
            try:
                try:
                    os.chdir(cwd)
                except OSError:
                    os.chdir(b"/")
                fcntl.ioctl(0, termios.TIOCSWINSZ, winsize)
                os.execve(argv[0], argv, env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        os.set_blocking(fd, False)

    def resize(self, cols: int, rows: int) -> None:
        if (cols, rows) != (self.cols, self.rows) and self.fd >= 0:
            self.cols, self.rows = cols, rows
            _winsize(self.fd, cols, rows)  # the kernel sends SIGWINCH to the foreground group

    def poll(self) -> int | None:
        if self.status is None and self.pid > 0:
            try:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                self.status = -1
            else:
                if pid:
                    self.status = os.waitstatus_to_exitcode(status)
        return self.status

    async def terminate(self) -> None:
        """SIGHUP, SIGTERM after 2 s, SIGKILL after 3 s, then reap."""
        if self.pid <= 0:
            return
        for sig, wait in ((signal.SIGHUP, 2.0), (signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
            if self.poll() is not None:
                break
            try:
                os.killpg(self.pid, sig)
            except ProcessLookupError:
                pass
            for _ in range(int(wait / 0.05)):
                if self.poll() is not None:
                    break
                await asyncio.sleep(0.05)
        self.close_fd()

    def close_fd(self) -> None:
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1


class Bridge:
    """Runs one terminal session over an already-prepared WebSocket."""

    def __init__(self, ws: web.WebSocketResponse, pty: Pty, alive, touch):
        self.ws = ws
        self.pty = pty
        self.alive = alive  # () -> bool: is the login session still valid?
        self.touch = touch  # () -> None: record activity
        self.loop = asyncio.get_running_loop()
        self.out: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.queued = 0
        self.reading = False
        self.pending_in = bytearray()
        self.writing = False
        self.last_frame = self.loop.time()

    # -- PTY -> WS -------------------------------------------------------

    def _start_reading(self) -> None:
        if not self.reading and self.pty.fd >= 0:
            self.loop.add_reader(self.pty.fd, self._on_readable)
            self.reading = True

    def _stop_reading(self) -> None:
        if self.reading:
            self.loop.remove_reader(self.pty.fd)
            self.reading = False

    def _on_readable(self) -> None:
        try:
            data = os.read(self.pty.fd, READ_CHUNK)
        except BlockingIOError:
            return
        except OSError as e:  # EIO: the child side closed
            if e.errno not in (errno.EIO, errno.EBADF):
                log.warning("pty read: %s", e)
            data = b""
        if not data:
            self._stop_reading()
            self.out.put_nowait(None)
            return
        self.queued += len(data)
        self.out.put_nowait(data)
        if self.queued > HIGH_WATER:
            self._stop_reading()  # backpressure: resume once the socket drains

    async def _sender(self) -> None:
        while True:
            data = await self.out.get()
            if data is None:
                return
            self.queued -= len(data)
            await self.ws.send_bytes(data)
            if not self.reading and self.queued < LOW_WATER and self.pty.status is None:
                self._start_reading()

    # -- WS -> PTY -------------------------------------------------------

    def _write(self, data: bytes) -> None:
        self.pending_in += data
        if len(self.pending_in) > HIGH_WATER:
            del self.pending_in[: len(self.pending_in) - HIGH_WATER]
        self._flush_in()

    def _flush_in(self) -> None:
        while self.pending_in and self.pty.fd >= 0:
            try:
                n = os.write(self.pty.fd, self.pending_in)
            except BlockingIOError:
                break
            except OSError:
                self.pending_in.clear()
                break
            del self.pending_in[:n]
        if self.pending_in and not self.writing and self.pty.fd >= 0:
            self.loop.add_writer(self.pty.fd, self._on_writable)
            self.writing = True
        elif not self.pending_in and self.writing:
            self.loop.remove_writer(self.pty.fd)
            self.writing = False

    def _on_writable(self) -> None:
        self._flush_in()

    def _control(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("t") == "resize":
            cols, rows = clamp_size(msg.get("cols"), msg.get("rows"))
            self.pty.resize(cols, rows)
        elif msg.get("t") == "ping":
            asyncio.ensure_future(self.ws.send_str('{"t":"pong"}'))

    async def _receiver(self) -> None:
        async for msg in self.ws:
            if not self.alive():
                await self.ws.close(code=CLOSE_EXPIRED, message=b"session expired")
                return
            self.last_frame = self.loop.time()
            self.touch()
            if msg.type == WSMsgType.BINARY:
                self._write(msg.data)
            elif msg.type == WSMsgType.TEXT:
                self._control(msg.data)
            elif msg.type == WSMsgType.ERROR:
                return

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(15)
            if not self.alive():
                await self.ws.close(code=CLOSE_EXPIRED, message=b"session expired")
                return
            if self.loop.time() - self.last_frame > IDLE_CLOSE:
                await self.ws.close(code=CLOSE_IDLE, message=b"idle")
                return

    async def run(self) -> None:
        self.pty.spawn()
        self._start_reading()
        await self.ws.send_str(json.dumps({"t": "hello", "pid": self.pty.pid}))
        sender = asyncio.create_task(self._sender())
        receiver = asyncio.create_task(self._receiver())
        watchdog = asyncio.create_task(self._watchdog())
        try:
            done, _ = await asyncio.wait({sender, receiver, watchdog}, return_when=asyncio.FIRST_COMPLETED)
            if sender in done and not self.ws.closed:
                # The program exited: tell the client why, then close normally.
                await asyncio.sleep(0.05)
                code = self.pty.poll()
                for _ in range(20):
                    if code is not None:
                        break
                    await asyncio.sleep(0.05)
                    code = self.pty.poll()
                await self.ws.send_str(json.dumps({"t": "exit", "code": code}))
                await self.ws.close()
        finally:
            for task in (sender, receiver, watchdog):
                task.cancel()
            self._stop_reading()
            if self.writing and self.pty.fd >= 0:
                self.loop.remove_writer(self.pty.fd)
            await self.pty.terminate()
            if not self.ws.closed:
                await self.ws.close()
