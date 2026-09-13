from seckb.pipeline.dedupe import find_by_sha256, find_near_duplicate
from seckb.utils.simhash import simhash64, to_signed64

TEXT = (
    "以太坊智能合约审计中常见的重入漏洞利用方式与 Solidity 转账函数调用顺序 "
    "密切相关，开发者在编写提现逻辑时必须先更新余额再进行外部调用。"
) * 3


def test_find_by_sha256(kb):
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES('post','t','deadbeef','markdown','now')"
    )
    assert find_by_sha256(kb.conn, "deadbeef") == 1
    assert find_by_sha256(kb.conn, "unknown") is None


def test_find_near_duplicate(kb):
    near = TEXT + "补充一句无关紧要的话。"
    far = "Kubernetes 集群安全加固清单：RBAC 最小权限、网络策略、镜像签名与审计日志。"
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, simhash, format, imported_at) VALUES('post','t','a1',?,'markdown','now')",
        (to_signed64(simhash64(TEXT)),),
    )
    assert find_near_duplicate(kb.conn, near) == 1
    assert find_near_duplicate(kb.conn, far) is None
