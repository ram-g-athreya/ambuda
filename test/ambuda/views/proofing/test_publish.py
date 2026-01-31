import pytest
from pydantic import ValidationError

from ambuda.models.proofing import PublishConfig, LanguageCode
from ambuda.views.proofing.publish import _validate_slug


@pytest.mark.parametrize(
    "slug",
    [
        "ramayana",
        "a-b-c",
        "text123",
        "vol-1-ch-2",
        "a",
        "1",
    ],
)
def test_validate_slug_valid(slug):
    assert _validate_slug(slug) is None


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "-bad",
        "bad-",
        "has--double",
        "Upper",
        "has space",
        "rāmāyaṇa",
        "has_underscore",
        "has.dot",
        "-",
        "---",
    ],
)
def test_validate_slug_invalid(slug):
    assert _validate_slug(slug) is not None


@pytest.mark.parametrize("code", list(LanguageCode))
def test_valid_language_codes(code):
    config = PublishConfig(slug="test", title="Test", language=code.value)
    assert config.language == code


def test_default_language():
    config = PublishConfig(slug="test", title="Test")
    assert config.language == LanguageCode.SA


def test_invalid_language_code():
    with pytest.raises(ValidationError):
        PublishConfig(slug="test", title="Test", language="xx")


def test_empty_language_code():
    with pytest.raises(ValidationError):
        PublishConfig(slug="test", title="Test", language="")


def test_language_codes_have_labels():
    for code in LanguageCode:
        assert isinstance(code.label, str)
        assert len(code.label) > 0
