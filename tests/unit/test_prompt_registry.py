import pytest

from p1.prompts.registry import Prompt, PromptNotFoundError, PromptRegistry


def _write_prompt(prompts_dir, capability, version, text):
    capability_dir = prompts_dir / capability
    capability_dir.mkdir(parents=True, exist_ok=True)
    (capability_dir / f"{version}.md").write_text(text)


def test_loads_the_named_capability(tmp_path):
    _write_prompt(tmp_path, "chn09_classify_message", "v1", "Classify: {message}")

    registry = PromptRegistry(tmp_path)
    prompt = registry.get("chn09_classify_message")

    assert prompt == Prompt(capability="chn09_classify_message", version="v1", text="Classify: {message}")


def test_defaults_to_the_highest_version(tmp_path):
    _write_prompt(tmp_path, "chn09_classify_message", "v1", "old template")
    _write_prompt(tmp_path, "chn09_classify_message", "v2", "new template")
    _write_prompt(tmp_path, "chn09_classify_message", "v10", "newest template")

    prompt = PromptRegistry(tmp_path).get("chn09_classify_message")

    assert prompt.version == "v10"
    assert prompt.text == "newest template"


def test_can_pin_an_older_version_deliberately(tmp_path):
    _write_prompt(tmp_path, "chn09_classify_message", "v1", "old template")
    _write_prompt(tmp_path, "chn09_classify_message", "v2", "new template")

    prompt = PromptRegistry(tmp_path).get("chn09_classify_message", version="v1")

    assert prompt.version == "v1"
    assert prompt.text == "old template"


def test_unknown_capability_raises_rather_than_defaulting(tmp_path):
    registry = PromptRegistry(tmp_path)
    with pytest.raises(PromptNotFoundError):
        registry.get("does_not_exist")


def test_unknown_version_raises_rather_than_falling_back(tmp_path):
    _write_prompt(tmp_path, "chn09_classify_message", "v1", "old template")
    registry = PromptRegistry(tmp_path)
    with pytest.raises(PromptNotFoundError):
        registry.get("chn09_classify_message", version="v99")


def test_capability_directory_with_no_version_files_raises(tmp_path):
    (tmp_path / "chn09_classify_message").mkdir()
    (tmp_path / "chn09_classify_message" / "notes.txt").write_text("not a version file")

    registry = PromptRegistry(tmp_path)
    with pytest.raises(PromptNotFoundError):
        registry.get("chn09_classify_message")


def test_list_capabilities(tmp_path):
    _write_prompt(tmp_path, "chn09_classify_message", "v1", "x")
    _write_prompt(tmp_path, "chn10_participation_note", "v1", "y")

    registry = PromptRegistry(tmp_path)

    assert registry.list_capabilities() == ["chn09_classify_message", "chn10_participation_note"]


def test_list_capabilities_on_missing_directory_returns_empty(tmp_path):
    registry = PromptRegistry(tmp_path / "does_not_exist")
    assert registry.list_capabilities() == []


def test_render_fills_placeholders():
    prompt = Prompt(capability="c", version="v1", text="Classify this message: {message}")
    assert prompt.render(message="hello") == "Classify this message: hello"


def test_render_raises_on_missing_placeholder_rather_than_leaving_it_unfilled():
    prompt = Prompt(capability="c", version="v1", text="Classify: {message}")
    with pytest.raises(ValueError):
        prompt.render()
