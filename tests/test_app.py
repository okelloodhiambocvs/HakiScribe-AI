import types
import importlib.util
from pathlib import Path

def _load_app_shell(monkeypatch):
    # Create fake streamlit with ALL methods our app.py uses
    fake_st = types.ModuleType("streamlit")
    calls = []

    class FakeCol:
        def metric(self, *args, **kwargs):
            calls.append(("metric", args, kwargs))

    def _rec(name):
        def _fn(*args, **kwargs):
            calls.append((name, args, kwargs))
            if name == "columns":
                n = args[0] if args else 3
                return [FakeCol() for _ in range(n)]
            return None
        return _fn

    for m in ["set_page_config", "title", "info", "subheader", "metric", "columns", "write"]:
        setattr(fake_st, m, _rec(m))

    monkeypatch.setitem(__import__("sys").modules, "streamlit", fake_st)

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