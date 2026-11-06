def test_installed():
    from jasme_jats import builder
    assert hasattr(builder.Builder, "autonum_mark")
