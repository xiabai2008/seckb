from seckb.utils.simhash import from_signed64, hamming, simhash64, to_signed64

BASE = (
    "the quick brown fox jumps over the lazy dog while the security team "
    "monitors network traffic for suspicious activity around the perimeter "
    "and the analyst writes a detailed report about the incident response"
)


def test_identical_text_zero_distance():
    assert hamming(simhash64(BASE), simhash64(BASE)) == 0


def test_small_change_small_distance():
    changed = BASE.replace("quick", "slow")
    assert hamming(simhash64(BASE), simhash64(changed)) <= 8


def test_signed64_roundtrip():
    h = simhash64(BASE)
    assert from_signed64(to_signed64(h)) == h


def test_empty_text():
    assert simhash64("") == 0
