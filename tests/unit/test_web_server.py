"""Launch the browser only after this server has successfully bound its port."""
import threading
import pytest

pytest.importorskip("uvicorn")
from acoustic_sync.web import server as module


@pytest.mark.parametrize("open_browser", [True, False])
def test_browser_launch_after_readiness(monkeypatch, open_browser):
    opened = threading.Event()
    urls = []

    class Server:
        started = False

        def __init__(self, config):
            assert config.host == "127.0.0.1"
            assert config.port == 9123

        def run(self):
            assert not urls
            self.started = True
            if open_browser:
                assert opened.wait(2)

    def browser(url):
        urls.append(url)
        opened.set()
        return True

    monkeypatch.setattr(module.uvicorn, "Server", Server)
    monkeypatch.setattr(module.webbrowser, "open", browser)
    module.run_server(object(), port=9123, open_browser=open_browser)
    assert urls == (["http://127.0.0.1:9123/"] if open_browser else [])


def test_startup_failure_does_not_open_browser(monkeypatch):
    class Server:
        started = False

        def __init__(self, config):
            pass

        def run(self):
            raise OSError("Port occupied")

    opened = []
    monkeypatch.setattr(module.uvicorn, "Server", Server)
    monkeypatch.setattr(module.webbrowser, "open", lambda url: opened.append(url))
    with pytest.raises(OSError, match="Port occupied"):
        module.run_server(object(), open_browser=True)
    assert not opened
