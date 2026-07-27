"""面试日程"编辑/改状态"集成竖切（ADR-0016/#63）：真 HTTP -> 真服务 -> 真库。

#63 修复前 PUT 更新与 PATCH 状态双双 500：UPDATE commit 后构造 DTO 读服务端 onupdate
的 updated_at 触发 MissingGreenlet（ADR-0019 前无 eager_defaults）。本竖切直接编码验收
标准：更新/改状态均 200 且返回完整 DTO（含 updatedAt），并作为该 bug 类的回归防护。
"""

from fastapi.testclient import TestClient

_PAYLOAD = {
    "companyName": "竖切测试公司",
    "position": "Java后端",
    "interviewTime": "2026-08-01T10:00:00",
    "interviewType": "VIDEO",
    "roundNumber": 1,
}


def test_schedule_update_and_status_roundtrip(integration_client: TestClient) -> None:
    """create -> PUT 更新(200) -> PATCH status(200) -> DELETE；全程 updatedAt 可读。"""
    create = integration_client.post("/api/interview-schedule", json=_PAYLOAD)
    assert create.status_code == 200
    body = create.json()
    assert body["code"] == 200
    schedule_id = body["data"]["id"]

    # PUT 更新：#63 修复前此处 500（MissingGreenlet）
    update = integration_client.put(
        f"/api/interview-schedule/{schedule_id}", json={**_PAYLOAD, "position": "Java后端-改"}
    ).json()
    assert update["code"] == 200
    assert update["data"]["position"] == "Java后端-改"
    assert update["data"]["updatedAt"]  # commit 后 onupdate 列可读（ADR-0019 回归防护）

    # PATCH 状态：同根因第二处
    patch = integration_client.patch(f"/api/interview-schedule/{schedule_id}/status?status=COMPLETED").json()
    assert patch["code"] == 200
    assert patch["data"]["status"] == "COMPLETED"
    assert patch["data"]["updatedAt"]

    # 线性收尾（隔离由 conftest TRUNCATE 保证，不用 finally 以免双重失败顶替主失败信号）
    delete = integration_client.delete(f"/api/interview-schedule/{schedule_id}").json()
    assert delete["code"] == 200
