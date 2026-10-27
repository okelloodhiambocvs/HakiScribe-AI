import types
import importlib.util
import sys
from pathlib import Path

class FakeCol:
    def __init__(self, calls):
        self.calls = calls
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def metric(self, *args, **kwargs):
        self.calls.append(("metric", args, kwargs))
    def write(self, *args, **kwargs):
        self.calls.append(("write", args, kwargs))

def _load_app_shell(monkeypatch):
    fake_st = types.ModuleType("streamlit")
    calls = []
    fake_st.session_state = {}

    def _rec(name, ret=None):
        def _fn(*args, **kwargs):
            calls.append((name, args, kwargs))
            return ret
        return _fn

    fake_st.set_page_config = _rec("set_page_config")
    fake_st.title = _rec("title")
    fake_st.info = _rec("info")
    fake_st.subheader = _rec("subheader")
    fake_st.write = _rec("write")
    fake_st.success = _rec("success")
    fake_st.warning = _rec("warning")
    fake_st.error = _rec("error")
    fake_st.text_input = lambda *a, **k: k.get("value", "")
    fake_st.text_area = lambda *a, **k: k.get("value", "")
    fake_st.button = lambda *a, **k: False

    def _columns(n=3, *args, **kwargs):
        count = n if isinstance(n, int) else len(n)
        return [FakeCol(calls) for _ in range(count)]
    fake_st.columns = _columns

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    spec = importlib.util.spec_from_file_location("app_under_test", str(Path("app.py").resolve()))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return calls

def test_app_shell_renders_title(monkeypatch):
    calls = _load_app_shell(monkeypatch)
    titles = [c for c in calls if c[0] == "title"]
    assert titles, "app.py must call st.title"
    assert "HakiScribe" in str(titles[0][1])

def test_app_shell_shows_human_in_the_loop_notice(monkeypatch):
    calls = _load_app_shell(monkeypatch)
    infos = [c for c in calls if c[0] == "info"]
    assert infos, "app.py must call st.info"
    text = str(infos[0][1]).lower()
    assert "human" in text