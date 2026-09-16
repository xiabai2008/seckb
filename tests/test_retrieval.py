from seckb.retrieval import Candidate, FusedCandidate, rrf_fuse


def test_rrf_fuse_single_pool_keeps_order():
    pools = [("fts", [Candidate(1, 11, 1), Candidate(2, 12, 2)])]
    fused = rrf_fuse(pools, k=60)
    assert [item.asset_id for item in fused] == [1, 2]
    assert fused[0].matched_by == {"fts"}
    assert fused[0].chunk_id == 11


def test_rrf_fuse_multi_pool_boosts_overlap():
    pools = [
        ("fts", [Candidate(1, 11, 1), Candidate(2, 12, 2)]),
        ("vector", [Candidate(2, 22, 1), Candidate(3, 33, 2)]),
    ]
    fused = rrf_fuse(pools, k=60)
    assert fused[0].asset_id == 2
    assert fused[0].matched_by == {"fts", "vector"}
    assert fused[0].chunk_id == 12
    assert fused[1].score > fused[2].score


def test_rrf_fuse_meili_asset_level_candidate():
    pools = [
        ("fts", [Candidate(1, 11, 1)]),
        ("meili", [Candidate(1, None, 1)]),
    ]
    fused = rrf_fuse(pools, k=60)
    assert fused[0].asset_id == 1
    assert fused[0].chunk_id == 11
    assert fused[0].matched_by == {"fts", "meili"}
