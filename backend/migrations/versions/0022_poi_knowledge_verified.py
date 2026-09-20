"""POI Knowledge: cấu trúc lại events/facts theo từng claim + nạp nội dung đã đối chiếu nguồn thật.

Revision ID: 0022_poi_knowledge_verified
Revises: 0021_poi_knowledge

Migration 0021 gieo 14 dòng `poi_knowledge` với nội dung biên soạn từ kiến
thức nền, `historical_events`/`interesting_facts` là mảng CHUỖI THÔ, và toàn
bộ `verified = false`. Bản này thay bằng nội dung đã tra cứu thật (Wikipedia
tiếng Việt + báo chí uy tín — Thanh Niên, Tuổi Trẻ, VnExpress) qua WebSearch
trong phiên làm việc, có URL nguồn cụ thể cho từng claim.

**Vì sao đổi ``historical_events``/``interesting_facts`` từ ``TEXT[]`` sang
``JSONB[]`` cấu trúc ``{title?, description, source, verified}``:** một record
`poi_knowledge` có thể có claim ĐÃ kiểm chứng (ngày khởi công, lấy từ
Wikipedia) đứng cạnh claim CHƯA kiểm chứng (một chi tiết nghe hợp lý nhưng
chưa tìm ra nguồn). Cột `verified` ở CẤP BẢN GHI không phân biệt được hai loại
đó — chatbot sau này (khi được nối vào) cần biết CHÍNH XÁC claim nào có thể
trích nguồn, claim nào chỉ là suy luận, để không lỡ nói chắc một điều chưa ai
xác nhận.

Nội dung lần này: MỌI item còn giữ lại đều có `source` (URL) và
`verified = true` — những claim tôi (AI) không tìm ra nguồn cụ thể trong lần
tra cứu này bị BỎ HẲN thay vì giữ lại với `verified = false`, đúng tinh thần
"ít nhưng kiểm chứng được hơn nhiều nhưng mù mờ" đã thống nhất. `verified` ở
cấp bản ghi (`poi_knowledge.verified`) chỉ true khi TẤT CẢ field có nội dung
của bản ghi đó đều đã có nguồn.

Với bệnh viện: không tìm lịch sử chi tiết cho Nhi Đồng 1/2 trong lần tra cứu
này nên KHÔNG thêm `historical_context` bịa — chỉ giữ `intro`/`specialty`
(sự thật hiển nhiên, xác nhận qua nhiều nguồn tổng hợp).
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0022_poi_knowledge_verified"
down_revision = "0021_poi_knowledge"
branch_labels = None
depends_on = None


# (poi_id, content_type, intro, intro_source, specialty, historical_context,
#  context_source, historical_events, interesting_facts, verified)
#
# historical_events / interesting_facts: list[dict] theo schema
# {"title": str | None, "description": str, "source": str, "verified": true}
# — mọi item ở đây đều verified=true vì đã có URL nguồn cụ thể tìm được qua
# WebSearch; claim nào không tìm ra nguồn thì bị loại khỏi danh sách luôn.
ROWS = [
    (
        "10000000-0000-0000-0000-000000000020",  # Dinh Độc Lập
        "historical",
        "Dinh thự từng là nơi làm việc của chính quyền miền Nam Việt Nam trước năm 1975, nay là di tích lịch sử quốc gia mở cửa cho khách tham quan.",
        "https://dsvh.gov.vn/di-tich-lich-su-dinh-doc-lap-2937",
        None,
        "Công trình hiện tại được khởi công ngày 1/7/1962, hoàn thành ngày 31/10/1966, theo thiết kế của kiến trúc sư Ngô Viết Thụ.",
        "https://vi.wikipedia.org/wiki/Dinh_%C4%90%E1%BB%99c_L%E1%BA%ADp",
        [
            {
                "title": "Đánh bom dinh (8/4/1975)",
                "description": "Một phi công ném bom vào dinh nhằm mưu sát Tổng thống Nguyễn Văn Thiệu, gây thiệt hại không lớn.",
                "source": "https://vi.wikipedia.org/wiki/Dinh_%C4%90%E1%BB%99c_L%E1%BA%ADp",
                "verified": True,
            },
            {
                "title": "Xe tăng tiến vào dinh (30/4/1975)",
                "description": "10:45 xe tăng Quân Giải phóng húc đổ cổng dinh; tới 11:30 lá cờ được thay, đánh dấu kết thúc chiến tranh.",
                "source": "https://vi.wikipedia.org/wiki/Dinh_%C4%90%E1%BB%99c_L%E1%BA%ADp",
                "verified": True,
            },
        ],
        [
            {
                "description": "Dinh có hai tầng hầm được thiết kế để chống chịu bom đạn.",
                "source": "https://vi.wikipedia.org/wiki/Dinh_%C4%90%E1%BB%99c_L%E1%BA%ADp",
                "verified": True,
            },
            {
                "description": "Nội thất bên trong hơn 100 phòng vẫn giữ theo bài trí thập niên 1960.",
                "source": "https://vi.wikipedia.org/wiki/Dinh_%C4%90%E1%BB%99c_L%E1%BA%ADp",
                "verified": True,
            },
        ],
        True,
    ),
    (
        "10000000-0000-0000-0000-000000000019",  # Nhà thờ Đức Bà
        "architectural",
        "Nhà thờ chính tòa Công giáo mang kiến trúc châu Âu, một trong những công trình biểu tượng ở trung tâm thành phố.",
        "https://vi.wikipedia.org/wiki/Nh%C3%A0_th%E1%BB%9D_ch%C3%ADnh_t%C3%B2a_%C4%90%E1%BB%A9c_B%C3%A0_S%C3%A0i_G%C3%B2n",
        None,
        "Khởi công ngày 7/10/1877, hoàn thành và khánh thành đúng lễ Phục sinh 11/4/1880.",
        "https://vi.wikipedia.org/wiki/Nh%C3%A0_th%E1%BB%9D_ch%C3%ADnh_t%C3%B2a_%C4%90%E1%BB%A9c_B%C3%A0_S%C3%A0i_G%C3%B2n",
        [
            {
                "title": "Xây thêm hai tháp chuông (1895)",
                "description": "Hai tháp chuông cao 57,6 m mỗi tháp được xây thêm, mỗi tháp có 6 quả chuông đồng lớn.",
                "source": "https://vi.wikipedia.org/wiki/Nh%C3%A0_th%E1%BB%9D_ch%C3%ADnh_t%C3%B2a_%C4%90%E1%BB%A9c_B%C3%A0_S%C3%A0i_G%C3%B2n",
                "verified": True,
            }
        ],
        [
            {
                "description": "Trên đỉnh mỗi tháp có một cây thánh giá cao 3,5 m, nặng 600 kg.",
                "source": "https://vi.wikipedia.org/wiki/Nh%C3%A0_th%E1%BB%9D_ch%C3%ADnh_t%C3%B2a_%C4%90%E1%BB%A9c_B%C3%A0_S%C3%A0i_G%C3%B2n",
                "verified": True,
            }
        ],
        True,
    ),
    (
        "0cf8a1c6-b4ac-4b36-af9c-a4d00e6b77b2",  # Bưu điện Trung tâm Sài Gòn
        "architectural",
        "Công trình bưu điện mang phong cách kiến trúc Pháp, hiện vẫn hoạt động như một bưu cục kết hợp điểm tham quan.",
        "https://vi.wikipedia.org/wiki/B%C6%B0u_%C4%91i%E1%BB%87n_S%C3%A0i_G%C3%B2n",
        None,
        "Toà nhà hiện tại được xây mới năm 1886–1891 theo thiết kế của kiến trúc sư Auguste Vildieu và phụ tá Alfred Foulhoux, khánh thành năm 1891.",
        "https://vi.wikipedia.org/wiki/B%C6%B0u_%C4%91i%E1%BB%87n_S%C3%A0i_G%C3%B2n",
        [
            {
                "title": "Công trình tiền thân (1860–1863) — KHÁC toà nhà hiện tại",
                "description": "Trước đó, kiến trúc sư Gustave Eiffel thiết kế Sở Dây thép Sài Gòn nguyên bản, khánh thành 13/1/1863. Đây là một công trình KHÁC với toà bưu điện đang đứng hiện nay — claim phổ biến 'Eiffel thiết kế Bưu điện Trung tâm' nhắc nhầm sang công trình này.",
                "source": "https://vi.wikipedia.org/wiki/B%C6%B0u_%C4%91i%E1%BB%87n_S%C3%A0i_G%C3%B2n",
                "verified": True,
            }
        ],
        [
            {
                "description": "Bên trong còn lưu hai bản đồ lịch sử từ năm 1892 và 1936.",
                "source": "https://vi.wikipedia.org/wiki/B%C6%B0u_%C4%91i%E1%BB%87n_S%C3%A0i_G%C3%B2n",
                "verified": True,
            }
        ],
        True,
    ),
    (
        "10000000-0000-0000-0000-000000000016",  # Chợ Bến Thành
        "cultural",
        "Khu chợ truyền thống lâu đời, một trong những biểu tượng thương mại của thành phố.",
        "https://vi.wikipedia.org/wiki/Ch%E1%BB%A3_B%E1%BA%BFn_Th%C3%A0nh",
        None,
        "Chợ mới được nhà thầu Brossard et Maupin khởi công xây dựng từ năm 1912, hoàn tất cuối tháng 3/1914.",
        "https://vi.wikipedia.org/wiki/Ch%E1%BB%A3_B%E1%BA%BFn_Th%C3%A0nh",
        [],
        [
            {
                "description": "Tháp đồng hồ ba mặt ở cửa Nam được giữ nguyên từ lúc khởi dựng.",
                "source": "https://www.donghosen.com/tin-moi/thap-dong-ho-cho-ben-thanh-lich-su-hinh-thanh-va-gia-tri-van-hoa-n107.html",
                "verified": True,
            }
        ],
        True,
    ),
    (
        "10000000-0000-0000-0000-000000000018",  # Bảo tàng Chứng tích Chiến tranh
        "historical",
        "Bảo tàng trưng bày hiện vật và tư liệu liên quan tới chiến tranh tại Việt Nam.",
        "https://baotangchungtichchientranh.vn/lich-su-bao-tang-chung-tich-chien-tranh/40/",
        None,
        "Thành lập ngày 4/9/1975.",
        "https://baotangchungtichchientranh.vn/lich-su-bao-tang-chung-tich-chien-tranh/40/",
        [],
        [],
        True,
    ),
    (
        "b77eae42-8b8c-4c6d-a6f6-95dfb0b289a1",  # Bảo tàng Thành phố Hồ Chí Minh
        "historical",
        "Bảo tàng giới thiệu lịch sử hình thành và phát triển của thành phố.",
        "https://vi.wikipedia.org/wiki/B%E1%BA%A3o_t%C3%A0ng_Th%C3%A0nh_ph%E1%BB%91_H%E1%BB%93_Ch%C3%AD_Minh",
        None,
        "Toà nhà được xây dựng 1885–1890 theo thiết kế kiến trúc sư Alfred Foulhoux, ban đầu là dinh Thống đốc Nam Kỳ, sau được gọi là Dinh Gia Long. Bảo tàng chính thức thành lập năm 1978.",
        "https://vi.wikipedia.org/wiki/B%E1%BA%A3o_t%C3%A0ng_Th%C3%A0nh_ph%E1%BB%91_H%E1%BB%93_Ch%C3%AD_Minh",
        [],
        [],
        True,
    ),
    (
        "10000000-0000-0000-0000-000000000013",  # Hồ Con Rùa
        "cultural",
        "Quảng trường vòng xoay quen thuộc, điểm hẹn và vui chơi về đêm của người dân và du khách.",
        "https://baomoi.com/vi-sao-goi-la-ho-con-rua-c55511900.epi",
        None,
        "Khu vực từng mang tên công trường Chiến sĩ thời Pháp, đổi tên thành Công trường Quốc tế năm 1972.",
        "https://baomoi.com/vi-sao-goi-la-ho-con-rua-c55511900.epi",
        [
            {
                "title": "Vòng xoay cải tạo, đặt tượng rùa (1967)",
                "description": "Sau đợt cải tạo năm 1967, một tượng rùa hợp kim lớn được đặt ở trung tâm, đỡ bia đá khắc tên các nước viện trợ miền Nam Việt Nam — tượng này về sau không còn, nhưng tên gọi dân gian 'Hồ Con Rùa' vẫn giữ tới nay.",
                "source": "https://baomoi.com/vi-sao-goi-la-ho-con-rua-c55511900.epi",
                "verified": True,
            }
        ],
        [],
        True,
    ),
    (
        "f1856c1d-1e4a-445b-8efa-5385cfe2525d",  # Công viên Lê Thị Riêng
        "historical",
        "Công viên văn hóa tại Quận 10, kết hợp không gian xanh với khu tưởng niệm lịch sử.",
        "https://thanhnien.vn/cong-vien-le-thi-rieng-nhung-dau-tich-lich-su-va-nhiem-vu-tim-kiem-hai-cot-liet-si-18526060914400418.htm",
        None,
        "Khu vực từng là nghĩa trang Đô Thành (sau đổi tên nghĩa trang Chí Hòa) trước năm 1975. Sau ngày thống nhất, thành phố quy tập hài cốt và chỉnh trang thành công viên văn hóa, khánh thành ngày 19/3/1988 với tên Công viên Văn hóa Lê Thị Riêng.",
        "https://thanhnien.vn/cong-vien-le-thi-rieng-nhung-dau-tich-lich-su-va-nhiem-vu-tim-kiem-hai-cot-liet-si-18526060914400418.htm",
        [
            {
                "title": "Tìm kiếm hài cốt liệt sĩ hy sinh Tết Mậu Thân 1968",
                "description": "Khu vực từng ghi nhận các đợt tìm kiếm, quy tập hài cốt chiến sĩ hy sinh trong cuộc Tổng tiến công Tết Mậu Thân 1968.",
                "source": "https://vnexpress.net/cong-vien-le-thi-rieng-noi-tim-mo-chien-si-hy-sinh-58-nam-truoc-5081168.html",
                "verified": True,
            }
        ],
        [
            {
                "description": "Công viên có nhà truyền thống và bia tưởng niệm ghi danh hơn 2.000 liệt sĩ.",
                "source": "https://thanhnien.vn/cong-vien-le-thi-rieng-nhung-dau-tich-lich-su-va-nhiem-vu-tim-kiem-hai-cot-liet-si-18526060914400418.htm",
                "verified": True,
            }
        ],
        True,
    ),
    (
        "95baf653-acf7-4076-bea9-3ff55b4c82dd",  # Công viên Tao Đàn
        "historical",
        "Một trong những công viên lớn và lâu đời ở khu vực trung tâm thành phố, nhiều cây xanh cổ thụ.",
        "https://vnexpress.net/cong-vien-tao-dan-vuon-thuong-uyen-cua-sai-gon-xua-3877905.html",
        None,
        "Sau năm 1812, Tổng trấn Gia Định Lê Văn Duyệt dùng khu đất làm vườn cảnh riêng, dân gian gọi là Vườn Ông Thượng. Thời Pháp thuộc mang tên Jardin de la Ville (còn gọi Vườn Bờ-Rô). Sau năm 1955, chính quyền Sài Gòn đổi tên thành Vườn Tao Đàn, nay là Công viên Tao Đàn.",
        "https://thanhnien.vn/cong-vien-tao-dan-chuyen-it-biet-ve-vuon-ong-thuong-giua-sai-gon-185260717183355629.htm",
        [],
        [],
        True,
    ),
    (
        "f6151ff6-cc7a-41cb-b702-dca51b0a8d68",  # Thảo Cầm Viên Sài Gòn
        "nature",
        "Vườn thú kết hợp vườn thực vật lâu đời, điểm tham quan quen thuộc cho gia đình có trẻ nhỏ.",
        "https://vi.wikipedia.org/wiki/Th%E1%BA%A3o_C%E1%BA%A7m_Vi%C3%AAn_S%C3%A0i_G%C3%B2n",
        None,
        "Được thành lập năm 1864, mở cửa cho công chúng năm 1869 — một trong những vườn thú-thực vật lâu đời nhất còn hoạt động trên thế giới.",
        "https://vi.wikipedia.org/wiki/Th%E1%BA%A3o_C%E1%BA%A7m_Vi%C3%AAn_S%C3%A0i_G%C3%B2n",
        [],
        [
            {
                "description": "Hiện chăm sóc hơn 2.000 cá thể động vật thuộc khoảng 135 loài và hơn 2.500 cây thuộc hơn 900 loài thực vật.",
                "source": "https://vi.wikipedia.org/wiki/Th%E1%BA%A3o_C%E1%BA%A7m_Vi%C3%AAn_S%C3%A0i_G%C3%B2n",
                "verified": True,
            }
        ],
        True,
    ),
    (
        "d60b068b-37c2-4cef-8e5f-2e3074137201",  # Bệnh viện Nhi đồng 1
        "medical",
        "Bệnh viện chuyên khoa Nhi hạng I, một trong những bệnh viện nhi hàng đầu tại Việt Nam.",
        "https://nhidong.org.vn/",
        "Nhi khoa",
        None,
        None,
        [],
        [],
        True,
    ),
    (
        "a48cd510-b6c1-4ac3-93e1-07f9fe8cee13",  # Bệnh viện Nhi đồng 2
        "medical",
        "Bệnh viện chuyên khoa Nhi hạng I trực thuộc Sở Y tế TP.HCM, khám chữa bệnh cho trẻ từ 0 đến 16 tuổi.",
        "https://youmed.vn/tin-tuc/benh-vien-nhi-dong-2-tp-hcm-va-quy-trinh-kham-chua-benh/",
        "Nhi khoa",
        None,
        None,
        [],
        [],
        True,
    ),
    (
        "eded28c9-3576-43c0-b720-81987d251c91",  # Bệnh viện Da liễu
        "medical",
        "Bệnh viện chuyên khoa hạng I về da liễu, tuyến cao nhất của TP.HCM và các tỉnh phía Nam.",
        "https://bvdl.org.vn/cong-dong/n-2.18/gioi-thieu/tong-quan-benh-vien-da-lieu",
        "Da liễu",
        None,
        None,
        [],
        [],
        True,
    ),
    (
        "d44f5761-9b5f-4a69-b9e3-d65cece3844c",  # Bệnh viện Chợ Rẫy
        "medical",
        "Bệnh viện đa khoa hạng đặc biệt tuyến Trung ương, một trong những bệnh viện tuyến cuối lớn nhất cả nước.",
        "https://vi.wikipedia.org/wiki/B%E1%BB%87nh_vi%E1%BB%87n_Ch%E1%BB%A3_R%E1%BA%ABy",
        "Đa khoa (tuyến cuối)",
        "Thành lập năm 1900, được xếp hạng đặc biệt từ ngày 3/2/2010.",
        "https://vi.wikipedia.org/wiki/B%E1%BB%87nh_vi%E1%BB%87n_Ch%E1%BB%A3_R%E1%BA%ABy",
        [],
        [],
        True,
    ),
]

_KNOWLEDGE_JSONB_COLUMNS = ("historical_events", "interesting_facts")

_UPDATE_ROW = sa.text(
    """
    UPDATE poi_knowledge SET
        content_type = :content_type,
        intro = :intro,
        specialty = :specialty,
        historical_context = :historical_context,
        historical_events = CAST(:historical_events AS jsonb),
        interesting_facts = CAST(:interesting_facts AS jsonb),
        source = :source,
        verified = :verified
    WHERE poi_id = CAST(:poi_id AS uuid)
    """
)


def upgrade() -> None:
    # JSONB thay TEXT[]: mỗi phần tử giờ là một object {title?, description,
    # source, verified}, không còn là chuỗi thô — xem lý do ở docstring đầu
    # file. USING '[]'::jsonb vì cột cũ có DEFAULT '{}'::text[] (mảng rỗng),
    # không parse được thành jsonb qua ::jsonb trực tiếp.
    op.execute(
        "ALTER TABLE poi_knowledge "
        "ALTER COLUMN historical_events DROP DEFAULT, "
        "ALTER COLUMN historical_events TYPE JSONB USING '[]'::jsonb, "
        "ALTER COLUMN historical_events SET DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE poi_knowledge "
        "ALTER COLUMN interesting_facts DROP DEFAULT, "
        "ALTER COLUMN interesting_facts TYPE JSONB USING '[]'::jsonb, "
        "ALTER COLUMN interesting_facts SET DEFAULT '[]'::jsonb"
    )

    connection = op.get_bind()
    for (
        poi_id, content_type, intro, intro_source, specialty,
        historical_context, context_source, historical_events,
        interesting_facts, verified,
    ) in ROWS:
        # `source` cấp bản ghi: nguồn CHUNG cho intro/specialty/historical_context
        # (thường cùng một bài viết) — events/facts có `source` riêng từng mục
        # vì có thể tới từ bài khác.
        record_source = context_source or intro_source
        connection.execute(
            _UPDATE_ROW,
            {
                "poi_id": poi_id,
                "content_type": content_type,
                "intro": intro,
                "specialty": specialty,
                "historical_context": historical_context,
                "historical_events": json.dumps(historical_events, ensure_ascii=False),
                "interesting_facts": json.dumps(interesting_facts, ensure_ascii=False),
                "source": record_source,
                "verified": verified,
            },
        )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE poi_knowledge "
        "ALTER COLUMN historical_events DROP DEFAULT, "
        "ALTER COLUMN historical_events TYPE TEXT[] USING '{}'::text[], "
        "ALTER COLUMN historical_events SET DEFAULT '{}'::text[]"
    )
    op.execute(
        "ALTER TABLE poi_knowledge "
        "ALTER COLUMN interesting_facts DROP DEFAULT, "
        "ALTER COLUMN interesting_facts TYPE TEXT[] USING '{}'::text[], "
        "ALTER COLUMN interesting_facts SET DEFAULT '{}'::text[]"
    )
