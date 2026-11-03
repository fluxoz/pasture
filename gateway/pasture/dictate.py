"""Local dictation: recorded audio -> ffmpeg (16 kHz mono WAV) -> whisper.cpp.

Audio lives only in a private temp dir for the length of the request and is
never logged. One transcription runs at a time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile

from .config import Config

log = logging.getLogger("pasture.dictate")

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 45.0
# whisper.cpp marks silence and noise like "[BLANK_AUDIO]" or "(wind blowing)".
NOISE = re.compile(r"^\s*[\[(][^\])]*[\])]\s*$")


class DictationError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Dictation:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.lock = asyncio.Lock()

    async def _run(self, argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise DictationError("transcription timed out", 504)
        return proc.returncode or 0, out, err

    async def transcribe(self, audio: bytes) -> str:
        if not audio:
            raise DictationError("no audio")
        if len(audio) > MAX_BYTES:
            raise DictationError("recording too long", 413)
        if self.lock.locked():
            raise DictationError("busy with another recording", 429)
        async with self.lock:
            self.cfg.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = tempfile.mkdtemp(prefix="dictate-", dir=self.cfg.runtime_dir)
            try:
                src = os.path.join(tmp, "in")
                wav = os.path.join(tmp, "out.wav")
                fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(audio)
                code, _, err = await self._run(
                    [
                        self.cfg.ffmpeg or "ffmpeg",
                        "-nostdin",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        src,
                        "-t",
                        str(self.cfg.dictate_max_seconds),
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        wav,
                    ],
                    20.0,
                )
                if code != 0:
                    log.warning("ffmpeg failed (%d): %s", code, err.decode(errors="replace")[-300:])
                    raise DictationError("could not decode the recording", 422)
                code, out, err = await self._run(
                    [
                        self.cfg.whisper or "whisper-cli",
                        "-m",
                        self.cfg.whisper_model or "",
                        "-l",
                        self.cfg.dictate_language,
                        "-t",
                        str(self.cfg.dictate_threads),
                        "-nt",
                        "-np",
                        "-f",
                        wav,
                    ],
                    TIMEOUT,
                )
                if code != 0:
                    log.warning("whisper failed (%d): %s", code, err.decode(errors="replace")[-300:])
                    raise DictationError("transcription failed", 502)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        lines = [ln.strip() for ln in out.decode(errors="replace").splitlines()]
        return " ".join(ln for ln in lines if ln and not NOISE.match(ln)).strip()
