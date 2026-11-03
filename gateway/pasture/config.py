"""Gateway configuration, read once from PASTURE_* environment variables.

The NixOS module sets every variable; for local development see README.md.
Paths to secrets are read lazily (they are runtime files, never env values).
"""

from __future__ import annotations

import json
import os
import pwd
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as e:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from e


def _float(name: str, default: float) -> float:
    value = _env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as e:
        raise ConfigError(f"{name} must be a number, got {value!r}") from e


def _list(name: str) -> list[str]:
    value = _env(name)
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Config:
    host: str
    origin: str
    bind: str = "127.0.0.1"
    port: int = 8795
    static_dir: Path | None = None
    state_dir: Path = field(default_factory=lambda: Path.home() / ".local/state/pasture")
    runtime_dir: Path = field(default_factory=lambda: Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "pasture")

    session_key_file: Path | None = None
    enroll_token_file: Path | None = None
    credentials_file: Path | None = None
    enrollment: bool = False

    idle_minutes: int = 30
    absolute_minutes: int = 480
    rp_name: str = "pasture"
    user_name: str = "owner"
    app_name: str = "pasture"

    shell_enable: bool = True
    shell_command: list[str] | None = None
    tmux: str | None = None
    tmux_default: str | None = None
    herdr: str | None = None
    herdr_sessions: list[str] = field(default_factory=lambda: ["default"])
    herdr_methods_file: Path | None = None
    herdr_prefix: str = "ctrl+b"
    agent_kinds: list[str] = field(default_factory=list)
    project_roots: list[Path] = field(default_factory=lambda: [Path.home()])

    ntfy_url: str | None = None
    ntfy_topic: str = "agents"

    dictate: bool = False
    whisper: str | None = None  # whisper.cpp's whisper-server
    whisper_model: str | None = None
    ffmpeg: str | None = None  # only for uploaded recordings (browsers without AudioWorklet)
    dictate_language: str = "en"
    dictate_threads: int = 4
    dictate_max_seconds: int = 60
    dictate_idle_minutes: float = 0.0  # stop the model after this long unused; 0 = keep it loaded
    dictate_prompt: str = ""
    dictate_args: list[str] = field(default_factory=list)

    cert_file: Path | None = None

    @property
    def secure_cookies(self) -> bool:
        return self.origin.startswith("https://")

    def login_shell(self) -> list[str]:
        if self.shell_command:
            return list(self.shell_command)
        shell = os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
        return [shell, "-l"]


def _path(name: str) -> Path | None:
    value = _env(name)
    return Path(value).expanduser() if value else None


def load() -> Config:
    host = _env("PASTURE_HOST")
    if not host:
        raise ConfigError("PASTURE_HOST is required (the WebAuthn RP ID, e.g. host.example.ts.net)")
    origin = _env("PASTURE_ORIGIN", f"https://{host}")
    assert origin is not None

    shell_command = None
    raw = _env("PASTURE_SHELL_COMMAND")
    if raw:
        try:
            shell_command = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ConfigError("PASTURE_SHELL_COMMAND must be a JSON list of strings") from e
        if not (isinstance(shell_command, list) and shell_command and all(isinstance(a, str) for a in shell_command)):
            raise ConfigError("PASTURE_SHELL_COMMAND must be a non-empty JSON list of strings")

    roots = [Path(p).expanduser() for p in _list("PASTURE_PROJECT_ROOTS")] or [Path.home()]

    dictate_args: list[str] = []
    raw = _env("PASTURE_DICTATE_ARGS")
    if raw:
        try:
            dictate_args = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ConfigError("PASTURE_DICTATE_ARGS must be a JSON list of strings") from e
        if not (isinstance(dictate_args, list) and all(isinstance(a, str) for a in dictate_args)):
            raise ConfigError("PASTURE_DICTATE_ARGS must be a JSON list of strings")

    cfg = Config(
        host=host,
        origin=origin.rstrip("/"),
        bind=_env("PASTURE_BIND", "127.0.0.1") or "127.0.0.1",
        port=_int("PASTURE_PORT", 8795),
        static_dir=_path("PASTURE_STATIC"),
        session_key_file=_path("PASTURE_SESSION_KEY_FILE"),
        enroll_token_file=_path("PASTURE_ENROLL_TOKEN_FILE"),
        credentials_file=_path("PASTURE_CREDENTIALS_FILE"),
        enrollment=_bool("PASTURE_ENROLL", False),
        idle_minutes=_int("PASTURE_SESSION_IDLE_MINUTES", 30),
        absolute_minutes=_int("PASTURE_SESSION_ABSOLUTE_MINUTES", 480),
        rp_name=_env("PASTURE_RP_NAME", "pasture") or "pasture",
        user_name=_env("PASTURE_USER_NAME", "owner") or "owner",
        app_name=_env("PASTURE_APP_NAME", "pasture") or "pasture",
        shell_enable=_bool("PASTURE_SHELL", True),
        shell_command=shell_command,
        tmux=_env("PASTURE_TMUX"),
        tmux_default=_env("PASTURE_TMUX_DEFAULT"),
        herdr=_env("PASTURE_HERDR"),
        herdr_sessions=_list("PASTURE_HERDR_SESSIONS") or ["default"],
        herdr_methods_file=_path("PASTURE_HERDR_METHODS"),
        herdr_prefix=_env("PASTURE_HERDR_PREFIX", "ctrl+b") or "ctrl+b",
        agent_kinds=_list("PASTURE_AGENT_KINDS"),
        project_roots=roots,
        ntfy_url=(_env("PASTURE_NTFY") or "").rstrip("/") or None,
        ntfy_topic=_env("PASTURE_NTFY_TOPIC", "agents") or "agents",
        dictate=_bool("PASTURE_DICTATE", False),
        whisper=_env("PASTURE_DICTATE_SERVER"),
        whisper_model=_env("PASTURE_DICTATE_MODEL"),
        ffmpeg=_env("PASTURE_DICTATE_FFMPEG"),
        dictate_language=_env("PASTURE_DICTATE_LANGUAGE", "en") or "en",
        dictate_threads=_int("PASTURE_DICTATE_THREADS", 4),
        dictate_max_seconds=_int("PASTURE_DICTATE_MAX_SECONDS", 60),
        dictate_idle_minutes=_float("PASTURE_DICTATE_IDLE_MINUTES", 0.0),
        dictate_prompt=_env("PASTURE_DICTATE_PROMPT", "") or "",
        dictate_args=dictate_args,
        cert_file=_path("PASTURE_CERT_FILE"),
    )
    # systemd's StateDirectory=/RuntimeDirectory= export these.
    state = _path("PASTURE_STATE_DIR") or _path("STATE_DIRECTORY")
    if state:
        cfg.state_dir = state
    runtime = _path("PASTURE_RUNTIME_DIR") or _path("RUNTIME_DIRECTORY")
    if runtime:
        cfg.runtime_dir = runtime
    if cfg.dictate and not (cfg.whisper and cfg.whisper_model):
        raise ConfigError("dictation needs PASTURE_DICTATE_SERVER (whisper-server) and PASTURE_DICTATE_MODEL")
    return cfg


def read_secret(path: Path | None) -> bytes:
    """Read a secret file; trailing whitespace is stripped. Missing file = empty."""
    if path is None:
        return b""
    try:
        return path.read_bytes().strip()
    except FileNotFoundError:
        return b""
