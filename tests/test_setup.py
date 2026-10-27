from pathlib import Path

def test_project_structure():
    assert Path("src/transcription/__init__.py").exists()
    assert Path("src/agents/__init__.py").exists()
    assert Path("src/verification/__init__.py").exists()
    assert Path("src/utils/config.py").exists()
    assert Path("app.py").exists()

def test_config_loads_without_key():
    from src.utils.config import is_configured
    # Should not crash even without real key
    assert isinstance(is_configured(), bool)