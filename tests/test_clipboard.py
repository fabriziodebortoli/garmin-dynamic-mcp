import subprocess

from garmin_dynamic_mcp.clipboard import clear_clipboard_if, read_clipboard


class FakeRun:
    def __init__(self, outputs=None, fail=False):
        self.outputs = list(outputs or [])
        self.calls = []
        self.fail = fail

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.fail:
            raise OSError("no such program")
        out = self.outputs.pop(0) if self.outputs else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


def has(*names):
    return lambda name: f"/usr/bin/{name}" if name in names else None


def test_windows_reads_with_powershell():
    run = FakeRun(["key-123\r\n"])
    assert read_clipboard(platform="win32", which=has("powershell"), run=run) == "key-123\r\n"
    argv, kwargs = run.calls[0]
    assert argv[0] == "/usr/bin/powershell" and "Get-Clipboard -Raw" in argv[-1]
    assert not kwargs.get("shell")


def test_macos_reads_with_pbpaste():
    run = FakeRun(["key-123"])
    assert read_clipboard(platform="darwin", which=has("pbpaste"), run=run) == "key-123"
    assert run.calls[0][0] == ["/usr/bin/pbpaste"]


def test_linux_prefers_wl_paste_then_xclip():
    run = FakeRun(["k"])
    read_clipboard(platform="linux", which=has("wl-paste", "xclip"), run=run)
    assert run.calls[0][0][0] == "/usr/bin/wl-paste"
    run = FakeRun(["k"])
    read_clipboard(platform="linux", which=has("xclip"), run=run)
    assert run.calls[0][0][:2] == ["/usr/bin/xclip", "-selection"]


def test_no_tool_returns_none():
    assert read_clipboard(platform="linux", which=has(), run=FakeRun()) is None


def test_command_failure_returns_none():
    assert read_clipboard(platform="darwin", which=has("pbpaste"), run=FakeRun(fail=True)) is None


def test_clear_only_when_clipboard_still_holds_value():
    run = FakeRun(["other text"])
    assert clear_clipboard_if("key-123", platform="darwin", which=has("pbpaste", "pbcopy"), run=run) is False
    assert len(run.calls) == 1

    run = FakeRun([" key-123\n", ""])
    assert clear_clipboard_if("key-123", platform="darwin", which=has("pbpaste", "pbcopy"), run=run) is True
    assert run.calls[1][0] == ["/usr/bin/pbcopy"] and run.calls[1][1]["input"] == ""


def test_clear_on_windows_uses_set_clipboard():
    run = FakeRun(["key-123", ""])
    assert clear_clipboard_if("key-123", platform="win32", which=has("powershell"), run=run) is True
    assert "Set-Clipboard" in run.calls[1][0][-1]
