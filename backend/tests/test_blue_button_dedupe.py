"""Same-export Blue Button pdf+txt twin helpers (pure; no DB)."""

from app.intake.dedup import file_stem, prefer_keep_other, same_export_stem_peer


def test_file_stem_strips_ext():
    assert file_stem("mhv_STRANSKY_20230904_1454.pdf") == "mhv_stransky_20230904_1454"
    assert file_stem("mhv_STRANSKY_20230904_1454.txt") == "mhv_stransky_20230904_1454"


def test_prefer_keep_txt_over_pdf_same_stem():
    assert prefer_keep_other(
        "mhv_STRANSKY_20230904_1454.pdf",
        "mhv_STRANSKY_20230904_1454.txt",
    )
    assert not prefer_keep_other(
        "mhv_STRANSKY_20230904_1454.txt",
        "mhv_STRANSKY_20230904_1454.pdf",
    )


def test_prefer_not_when_stems_differ():
    assert not prefer_keep_other("a.pdf", "b.txt")


def test_stem_peer_skips_pdf_when_txt_ready():
    candidates = [
        (
            "11111111-1111-1111-1111-111111111111",
            "fp",
            None,
            "ready",
            "mhv_STRANSKY_20230904_1454.txt",
            None,
        )
    ]
    hit = same_export_stem_peer("mhv_STRANSKY_20230904_1454.pdf", candidates)
    assert hit == "11111111-1111-1111-1111-111111111111"


def test_stem_peer_ignores_processing_peer():
    candidates = [
        (
            "11111111-1111-1111-1111-111111111111",
            "fp",
            None,
            "processing",
            "mhv_STRANSKY_20230904_1454.txt",
            None,
        )
    ]
    assert same_export_stem_peer("mhv_STRANSKY_20230904_1454.pdf", candidates) is None
