from mcmahon_dispatch.services.settings_service import SettingsService


def test_settings_are_persisted_atomically(config) -> None:
    settings = SettingsService(config.paths.settings_file)
    settings.set("appearance.theme", "light")
    assert SettingsService(config.paths.settings_file).get("appearance.theme") == "light"


def test_unchanged_settings_do_not_trigger_another_write(config, monkeypatch) -> None:
    settings = SettingsService(config.paths.settings_file)
    writes = 0
    original = settings._write_atomic

    def counted_write() -> None:
        nonlocal writes
        writes += 1
        original()

    monkeypatch.setattr(settings, "_write_atomic", counted_write)

    assert settings.set("appearance.theme", "dark") is False
    assert settings.set_many({"appearance.theme": "dark"}) is False
    assert writes == 0

    assert settings.set("appearance.theme", "light") is True
    assert writes == 1


def test_settings_snapshot_is_isolated(config) -> None:
    settings = SettingsService(config.paths.settings_file)
    snapshot = settings.snapshot()
    snapshot["appearance.theme"] = "light"

    assert settings.get("appearance.theme") == "dark"
