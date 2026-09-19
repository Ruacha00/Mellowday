"""A user can remove a previously saved turn limit without clearing credentials."""
from mellowday import config


def test_clear_saved_turn_limit(isolated_data_dir, monkeypatch):
    monkeypatch.delenv('MELLOWDAY_API_KEY', raising=False)
    config.update_model_config(api_key='keep-this-key', max_turns=7)
    assert config.load_model_config().max_turns == 7
    changed = config.update_model_config(api_key='', max_turns=None)
    assert changed.max_turns is None
    assert changed.api_key == 'keep-this-key'
    assert config.load_model_config().max_turns is None
