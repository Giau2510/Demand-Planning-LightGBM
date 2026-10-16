"""Linux VPS: the 'is the app already running' check (second `serve`, `restore` while running) must work off Windows.
os.kill is faked: on Windows a real os.kill(pid, 0) would send CTRL_C_EVENT."""
import os

from app import cli


def test_pid_alive_on_posix_uses_signal_zero(monkeypatch):
    calls = []

    def fake_kill(pid, sig):
        calls.append((pid, sig))
        if pid == 111:
            return None
        if pid == 222:
            raise PermissionError
        raise ProcessLookupError

    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.os, "kill", fake_kill)
    assert cli._pid_alive(111) is True
    assert cli._pid_alive("222") is True               # another user's process still exists
    assert cli._pid_alive(333) is False
    assert cli._pid_alive(None) is False and cli._pid_alive("x") is False
    assert calls == [(111, 0), (222, 0), (333, 0)]


def test_pid_alive_on_windows_never_calls_os_kill(monkeypatch):
    if cli.sys.platform != "win32":
        return
    monkeypatch.setattr(cli.os, "kill", lambda *a: (_ for _ in ()).throw(AssertionError("os.kill on Windows")))
    assert cli._pid_alive(os.getpid()) is True
    assert cli._pid_alive(999999) is False
