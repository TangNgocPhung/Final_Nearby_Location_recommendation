"""POI Knowledge: thêm Địa đạo Phú Thọ Hòa và Bót Dây Thép (đã đối chiếu nguồn thật).

Revision ID: 0023_phu_tho_hoa_bot_day_thep
Revises: 0022_poi_knowledge_verified

Nội dung tra qua Wikipedia tiếng Việt + Nhân Dân/Báo Lào Cai/Báo Quân khu 7 —
cùng chuẩn "chỉ giữ claim có nguồn cụ thể" đã dùng ở 0021/0022.

**Địa đạo Phú Thọ Hòa có 2 bản ghi trùng trong ``pois``** (đo được thật,
2026-09-20): ``e7e46513-...`` (category ``landmark``, có địa chỉ) và
``c6dac7d0-...`` (category ``park``, không địa chỉ) — cả hai đều nhập từ OSM,
khả năng OSM có hai node/way khác nhau cho cùng một địa điểm thật (một điểm
di tích, một vùng công viên bao quanh). Migration này CHỈ gắn knowledge vào
bản ``landmark`` (đúng bản chất "di tích lịch sử" hơn là "công viên"),
KHÔNG xử lý gộp trùng — đó là việc của lớp dedupe dữ liệu POI, ngoài phạm vi
một migration nội dung.

**Bót Dây Thép**: nội dung gốc có nhắc chi tiết tra tấn/hành quyết trong giai
đoạn 1945-1947 — viết lại ở mức khái quát, giữ đúng sự thật lịch sử nhưng
không đi sâu miêu tả bạo lực, cùng tinh thần "trung lập, tôn trọng" đã áp
dụng cho Công viên Lê Thị Riêng ở migration 0021.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0023_phu_tho_hoa_bot_day_thep"
down_revision = "0022_poi_knowledge_verified"
branch_labels = None
depends_on = None


ROWS = [
    (
        "e7e46513-f93a-4344-9d86-73c45b0e99bd",  # Địa Đạo Phú Thọ Hòa (bản landmark)
        "historical",
        "Địa đạo được xem là hệ thống địa đạo xuất hiện sớm nhất ở Nam Bộ, hình thành trước cả Địa đạo Củ Chi, gắn với cuộc kháng chiến chống Pháp và Mỹ của quân dân địa phương.",
        "https://vi.wikipedia.org/wiki/%C4%90%E1%BB%8Ba_%C4%91%E1%BA%A1o_Ph%C3%BA_Th%E1%BB%8D_H%C3%B2a",
        None,
        "Khởi đào năm 1947 do Chi bộ Phú Thọ Hòa (Nguyễn Văn Tiểng, Lâm Quốc Đăng, Tám Lê Thanh) khởi xướng, ban đầu 16 người chia 4 toán đào thủ công vào ban đêm; sau mở rộng thành mạng lưới liên xã dài hơn 10 km theo địa hình. Được Bộ Văn hóa và Thông tin công nhận Di tích lịch sử cấp quốc gia ngày 28/6/1996 theo Quyết định số 1460-QĐ/VH.",
        "https://vi.wikipedia.org/wiki/%C4%90%E1%BB%8Ba_%C4%91%E1%BA%A1o_Ph%C3%BA_Th%E1%BB%8D_H%C3%B2a",
        [
            {
                "title": "Đốt kho nhiên liệu Pháp (đêm 31/8/1952)",
                "description": "Lực lượng từ địa đạo đốt cháy kho nhiên liệu của Pháp tại Phú Thọ, thiêu rụi hơn 3 triệu lít xăng.",
                "source": "https://vi.wikipedia.org/wiki/%C4%90%E1%BB%8Ba_%C4%91%E1%BA%A1o_Ph%C3%BA_Th%E1%BB%8D_H%C3%B2a",
                "verified": True,
            },
            {
                "title": "Phá kho bom (đêm 31/5 – 1/6/1953)",
                "description": "Một tiểu đoàn quyết tử xuất phát từ địa đạo phá huỷ một kho bom lớn của Pháp.",
                "source": "https://vi.wikipedia.org/wiki/%C4%90%E1%BB%8Ba_%C4%91%E1%BA%A1o_Ph%C3%BA_Th%E1%BB%8D_H%C3%B2a",
                "verified": True,
            },
        ],
        [
            {
                "description": "Được xác định là địa đạo xuất hiện đầu tiên ở Nam Bộ, có trước cả Địa đạo Củ Chi.",
                "source": "https://vi.wikipedia.org/wiki/%C4%90%E1%BB%8Ba_%C4%91%E1%BA%A1o_Ph%C3%BA_Th%E1%BB%8D_H%C3%B2a",
                "verified": True,
            },
            {
                "description": "Khu di tích hiện nay thực chất là công trình được phục dựng vào năm 1985.",
                "source": "https://mia.vn/cam-nang-du-lich/dia-dao-phu-tho-hoa-18336",
                "verified": True,
            },
        ],
        True,
    ),
    (
        "603f22b4-bb7f-426d-9d72-dd43ac0bad49",  # Bót Dây Thép
        "historical",
        "Di tích lịch sử cấp quốc gia gắn với cuộc đấu tranh cách mạng của quân dân Sài Gòn – Gia Định thời kháng chiến chống Pháp.",
        "https://nhandan.vn/bot-day-thep-nguc-tu-thoi-thuoc-phap-post546857.html",
        None,
        "Nguyên là một trạm phát/thu tín hiệu vô tuyến ('Nhà Dây Thép') do người Pháp xây dựng đầu thế kỷ 20, thiết kế bởi hai kỹ sư Hermall và Stéru, gồm 3 dãy nhà kiểu kiến trúc phương Tây với 3 cột ăng-ten, cột cao nhất hơn 70 m. Sau khi Pháp tái chiếm năm 1945, nơi đây được dùng làm nơi giam giữ, thẩm vấn trong 9 năm kháng chiến chống Pháp (1945–1954). Được công nhận Di tích lịch sử – văn hóa cấp quốc gia ngày 18/1/1993.",
        "https://nhandan.vn/bot-day-thep-nguc-tu-thoi-thuoc-phap-post546857.html",
        [],
        [
            {
                "description": "Công trình nguyên là trạm vô tuyến điện tín do Pháp xây dựng đầu thế kỷ 20, có cột ăng-ten cao hơn 70 m.",
                "source": "https://nhandan.vn/bot-day-thep-nguc-tu-thoi-thuoc-phap-post546857.html",
                "verified": True,
            }
        ],
        True,
    ),
]

_INSERT_KNOWLEDGE = sa.text(
    """
    INSERT INTO poi_knowledge (
        poi_id, content_type, intro, specialty, historical_context,
        historical_events, interesting_facts, source, verified
    )
    SELECT
        CAST(:poi_id AS uuid), :content_type, :intro, :specialty,
        :historical_context, CAST(:historical_events AS jsonb),
        CAST(:interesting_facts AS jsonb), :source, :verified
    WHERE EXISTS (SELECT 1 FROM pois WHERE id = CAST(:poi_id AS uuid))
    ON CONFLICT (poi_id) DO NOTHING
    """
)


def upgrade() -> None:
    connection = op.get_bind()
    for (
        poi_id, content_type, intro, intro_source, specialty, historical_context,
        context_source, historical_events, interesting_facts, verified,
    ) in ROWS:
        connection.execute(
            _INSERT_KNOWLEDGE,
            {
                "poi_id": poi_id,
                "content_type": content_type,
                "intro": intro,
                "specialty": specialty,
                "historical_context": historical_context,
                "historical_events": json.dumps(historical_events, ensure_ascii=False),
                "interesting_facts": json.dumps(interesting_facts, ensure_ascii=False),
                "source": context_source or intro_source,
                "verified": verified,
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM poi_knowledge WHERE poi_id = ANY(CAST(:ids AS uuid[]))"),
        {
            "ids": [
                "e7e46513-f93a-4344-9d86-73c45b0e99bd",
                "603f22b4-bb7f-426d-9d72-dd43ac0bad49",
            ]
        },
    )
