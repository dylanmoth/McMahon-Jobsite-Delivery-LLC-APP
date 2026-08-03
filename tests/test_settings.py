from mcmahon_dispatch.services.settings_service import SettingsService


def test_settings_are_persisted_atomically(config) -> None:
    settings = SettingsService(config.paths.settings_file)
    settings.set("appearance.theme", "light")
    assert SettingsService(config.paths.settings_file).get("appearance.theme") == "light"
