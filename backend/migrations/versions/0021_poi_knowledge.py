"""Lớp kiến thức riêng cho POI Guide (Phase 15) — giới thiệu/lịch sử/chuyên môn.

Revision ID: 0021_poi_knowledge
Revises: 0020_hairdresser_pois

Vì sao một bảng riêng thay vì thêm cột vào `pois`: `pois.description` là dữ
liệu NHẬP TỪ OSM (một câu ngắn, tự động), còn nội dung ở đây là biên soạn TAY,
cần trường ``verified`` để phân biệt "đã kiểm chứng" với "AI/người biên soạn
tự viết, CHƯA có nguồn xác nhận" — trộn hai loại vào cùng một cột
`description` thì mất khả năng phân biệt đó, và một job re-import OSM vô tình
ghi đè `description` sẽ xoá mất nội dung biên soạn tay không liên quan gì tới
OSM.

`content_type` quyết định FRONTEND hiển thị mục nào — không phải POI nào cũng
có lịch sử (bệnh viện) hay chuyên môn y tế (công viên), ép hiển thị đủ mọi
mục cho mọi POI sẽ ra những khối trống rỗng vô nghĩa.

Không phải mọi cột đều bắt buộc: một bệnh viện có `specialty` nhưng hợp lý là
KHÔNG có `historical_context`; NULL ở đây nghĩa là "không áp dụng", không phải
"chưa nhập xong".

`verified BOOLEAN DEFAULT false`: mặc định KHÔNG coi nội dung là đã kiểm
chứng — người biên soạn (kể cả AI) phải chủ động đánh dấu true sau khi đối
chiếu nguồn thật. An toàn hơn default true, vì sai ở chiều "chưa kiểm chứng dù
thực ra đúng" ít hại hơn hẳn chiều ngược lại (hiển thị sai như đã kiểm chứng).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_poi_knowledge"
down_revision = "0020_hairdresser_pois"
branch_labels = None
depends_on = None


# 14 POI THẬT đã xác nhận tồn tại trong dữ liệu (id lấy bằng SELECT trực tiếp,
# không suy đoán/bịa UUID). Nội dung do người biên soạn (qua trợ lý AI) viết từ
# kiến thức nền chung, KHÔNG đối chiếu một nguồn trích dẫn cụ thể nào — vì vậy
# mọi hàng đều `verified = false` và cố tình tránh số liệu/tên riêng dễ sai
# (ví dụ: KHÔNG ghi tên kiến trúc sư cho Bưu điện Trung tâm Sài Gòn — "Gustave
# Eiffel thiết kế" là truyền thuyết phổ biến nhưng KHÔNG chính xác). Việc kiểm
# chứng lại từng dòng trước khi dùng cho báo cáo/luận văn thuộc trách nhiệm
# người dùng dữ liệu này, không phải migration.
#
# (poi_id, content_type, intro, specialty, historical_context,
#  historical_events, interesting_facts)
KNOWLEDGE_ROWS: list[tuple[str, str, str, str | None, str | None, list[str], list[str]]] = [
    (
        "10000000-0000-0000-0000-000000000020",  # Dinh Độc Lập
        "historical",
        "Dinh thự từng là nơi làm việc của chính quyền miền Nam Việt Nam trước năm 1975, nay là di tích lịch sử mở cửa cho khách tham quan.",
        None,
        "Công trình hiện tại được xây dựng lại trên nền dinh thự cũ, hoàn thành vào khoảng cuối thập niên 1960, mang phong cách kiến trúc hiện đại đặc trưng của thời kỳ đó.",
        ["Gắn liền với các sự kiện chính trị quan trọng của miền Nam Việt Nam trước năm 1975"],
        ["Bên trong còn giữ nội thất và cách bài trí các phòng làm việc theo thời kỳ trước", "Có hệ thống tầng hầm bên dưới dinh"],
    ),
    (
        "10000000-0000-0000-0000-000000000019",  # Nhà thờ Đức Bà
        "architectural",
        "Nhà thờ chính tòa Công giáo mang kiến trúc châu Âu, một trong những công trình biểu tượng ở trung tâm thành phố.",
        None,
        "Được xây dựng vào cuối thế kỷ 19 trong thời kỳ Pháp thuộc.",
        [],
        ["Mặt tiền có hai tháp chuông cao là điểm nhận diện đặc trưng", "Phía trước có tượng Đức Mẹ"],
    ),
    (
        "0cf8a1c6-b4ac-4b36-af9c-a4d00e6b77b2",  # Bưu điện Trung tâm Sài Gòn
        "architectural",
        "Công trình bưu điện mang phong cách kiến trúc Pháp, hiện vẫn hoạt động như một bưu cục kết hợp điểm tham quan.",
        None,
        "Xây dựng trong thời kỳ Pháp thuộc, cuối thế kỷ 19.",
        [],
        ["Bên trong có bản đồ cổ và các chi tiết trang trí theo phong cách châu Âu", "Nằm gần Nhà thờ Đức Bà, thường được ghé thăm cùng lúc"],
    ),
    (
        "10000000-0000-0000-0000-000000000016",  # Chợ Bến Thành
        "cultural",
        "Khu chợ truyền thống lâu đời, một trong những biểu tượng thương mại của thành phố.",
        None,
        "Hình thành từ đầu thế kỷ 20, từng là đầu mối giao thương sầm uất của khu vực trung tâm.",
        [],
        ["Cổng chợ với tháp đồng hồ là điểm nhận diện quen thuộc", "Bán đa dạng mặt hàng từ thực phẩm, quần áo tới quà lưu niệm"],
    ),
    (
        "10000000-0000-0000-0000-000000000018",  # Bảo tàng Chứng tích Chiến tranh
        "historical",
        "Bảo tàng trưng bày hiện vật và tư liệu liên quan tới chiến tranh tại Việt Nam.",
        None,
        "Thành lập sau năm 1975, nội dung trưng bày tập trung vào hậu quả của chiến tranh.",
        [],
        ["Thu hút đông đảo du khách quốc tế", "Có khu trưng bày ngoài trời với các phương tiện quân sự"],
    ),
    (
        "b77eae42-8b8c-4c6d-a6f6-95dfb0b289a1",  # Bảo tàng Thành phố Hồ Chí Minh
        "historical",
        "Bảo tàng giới thiệu lịch sử hình thành và phát triển của thành phố.",
        None,
        "Tòa nhà bảo tàng vốn là một công trình kiến trúc từ thời Pháp thuộc, sau này được chuyển đổi công năng thành bảo tàng.",
        [],
        ["Không gian trưng bày kết hợp kiến trúc cổ với hiện vật lịch sử", "Nằm ở khu vực trung tâm, gần nhiều địa danh khác"],
    ),
    (
        "10000000-0000-0000-0000-000000000013",  # Hồ Con Rùa
        "cultural",
        "Quảng trường vòng xoay quen thuộc, điểm hẹn và vui chơi về đêm của người dân và du khách.",
        None,
        "Khu vực đã trải qua nhiều lần thay đổi cảnh quan qua các thời kỳ.",
        [],
        ["Tên gọi dân gian xuất phát từ một công trình điêu khắc từng đặt tại đây", "Xung quanh có nhiều quán ăn, quán cà phê hoạt động về đêm"],
    ),
    (
        "f1856c1d-1e4a-445b-8efa-5385cfe2525d",  # Công viên Lê Thị Riêng
        "nature",
        "Không gian xanh phục vụ vui chơi, thể dục và sinh hoạt cộng đồng tại khu vực trung tâm.",
        None,
        None,
        [],
        ["Có khu vui chơi dành cho trẻ em", "Là nơi nhiều người dân quanh khu vực tập thể dục buổi sáng"],
    ),
    (
        "95baf653-acf7-4076-bea9-3ff55b4c82dd",  # Công viên Tao Đàn
        "nature",
        "Một trong những công viên lớn và lâu đời ở khu vực trung tâm thành phố, nhiều cây xanh cổ thụ.",
        None,
        None,
        [],
        ["Không gian rộng, phù hợp đi bộ và tập thể dục buổi sáng", "Thường là nơi tổ chức các hội hoa xuân, hội chợ theo mùa"],
    ),
    (
        "f6151ff6-cc7a-41cb-b702-dca51b0a8d68",  # Thảo Cầm Viên Sài Gòn
        "nature",
        "Vườn thú kết hợp vườn thực vật lâu đời, điểm tham quan quen thuộc cho gia đình có trẻ nhỏ.",
        None,
        "Là một trong những vườn thú lâu đời tại Việt Nam, hình thành từ thời Pháp thuộc.",
        [],
        ["Có nhiều loài động vật và thực vật đa dạng", "Phù hợp cho các chuyến tham quan cả gia đình"],
    ),
    (
        "d60b068b-37c2-4cef-8e5f-2e3074137201",  # Bệnh viện Nhi đồng 1
        "medical",
        "Bệnh viện chuyên khám và điều trị các bệnh lý cho trẻ em.",
        "Nhi khoa",
        None,
        [],
        [],
    ),
    (
        "a48cd510-b6c1-4ac3-93e1-07f9fe8cee13",  # Bệnh viện Nhi đồng 2
        "medical",
        "Bệnh viện chuyên khám và điều trị các bệnh lý cho trẻ em.",
        "Nhi khoa",
        None,
        [],
        [],
    ),
    (
        "eded28c9-3576-43c0-b720-81987d251c91",  # Bệnh viện Da liễu
        "medical",
        "Bệnh viện chuyên khám và điều trị các bệnh lý về da.",
        "Da liễu",
        None,
        [],
        [],
    ),
    (
        "d44f5761-9b5f-4a69-b9e3-d65cece3844c",  # Bệnh viện Chợ Rẫy
        "medical",
        "Bệnh viện đa khoa quy mô lớn, tiếp nhận khám và điều trị nhiều chuyên khoa.",
        "Đa khoa",
        None,
        [],
        [],
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
        :historical_context, CAST(:historical_events AS text[]),
        CAST(:interesting_facts AS text[]),
        'Kiến thức phổ thông do người biên soạn (qua trợ lý AI) tổng hợp, chưa đối chiếu nguồn cụ thể',
        false
    WHERE EXISTS (SELECT 1 FROM pois WHERE id = CAST(:poi_id AS uuid))
    ON CONFLICT (poi_id) DO NOTHING
    """
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE poi_knowledge (
            poi_id UUID PRIMARY KEY REFERENCES pois(id) ON DELETE CASCADE,
            content_type TEXT NOT NULL CHECK (content_type IN (
                'historical', 'cultural', 'medical', 'nature',
                'food', 'education', 'entertainment', 'architectural'
            )),
            intro TEXT,
            specialty TEXT,
            historical_context TEXT,
            historical_events TEXT[] NOT NULL DEFAULT '{}'::text[],
            interesting_facts TEXT[] NOT NULL DEFAULT '{}'::text[],
            source TEXT,
            verified BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # Dùng lại trigger từ migration 0003 thay vì viết hàm thứ hai làm đúng một
    # việc giống hệt (cùng quy ước với `saved_places` ở migration 0016).
    op.execute(
        "CREATE TRIGGER poi_knowledge_set_updated_at BEFORE UPDATE ON poi_knowledge "
        "FOR EACH ROW EXECUTE FUNCTION set_pois_updated_at()"
    )

    connection = op.get_bind()
    for (
        poi_id, content_type, intro, specialty, historical_context,
        historical_events, interesting_facts,
    ) in KNOWLEDGE_ROWS:
        connection.execute(
            _INSERT_KNOWLEDGE,
            {
                "poi_id": poi_id,
                "content_type": content_type,
                "intro": intro,
                "specialty": specialty,
                "historical_context": historical_context,
                "historical_events": "{" + ",".join(
                    '"' + e.replace('"', '\\"') + '"' for e in historical_events
                ) + "}",
                "interesting_facts": "{" + ",".join(
                    '"' + f.replace('"', '\\"') + '"' for f in interesting_facts
                ) + "}",
            },
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS poi_knowledge")
