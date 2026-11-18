import pytest
from toolkit.brain import history

@pytest.fixture(autouse=True)
def clean_history(tmp_path, monkeypatch):
    """Point history at a temp dir for every test."""
    from toolkit.config import settings
    monkeypatch.setenv("TOOLKIT_DATA_DIR", str(tmp_path))
    settings.cache_clear()
    history.clear()

def test_save_and_load():
    history.save_turn("user", "hello")
    history.save_turn("assistant", "hi there")
    
    turns = history.load_recent(10)
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].text == "hello"
    assert turns[1].role == "assistant"
    assert turns[1].text == "hi there"

def test_load_recent_respects_limit():
    for i in range(5):
        history.save_turn("user", f"msg {i}")
    
    turns = history.load_recent(3)
    assert len(turns) == 3
    # Should get the *last* 3, oldest first
    assert turns[0].text == "msg 2"
    assert turns[2].text == "msg 4"