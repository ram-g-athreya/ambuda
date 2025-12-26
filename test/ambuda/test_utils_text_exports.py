from ambuda.utils.text_exports import EXPORTS, ExportConfig, ExportType, ExportScheme


def test_export_config_set_scheme():
    for e in EXPORTS:
        if e.type == ExportType.PDF:
            assert e.scheme
        else:
            # Not supported for other types yet.
            assert e.scheme is None


def test_exports_have_unique_slug_patterns():
    export_keys = {x.slug_pattern for x in EXPORTS}
    assert len(export_keys) == len(EXPORTS)


def test_exports_have_unique_labels():
    export_labels = {x.label for x in EXPORTS}
    assert len(export_labels) == len(EXPORTS)
