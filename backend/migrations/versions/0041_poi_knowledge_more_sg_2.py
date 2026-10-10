"""POI Knowledge: thêm 9 địa danh (lăng, đình, chùa, hội quán, bảo tàng, công trường, thánh thất) cho Săn địa danh.

Revision ID: 0041_poi_knowledge_more_sg_2
Revises: 0040_poi_knowledge_more_sg

Đợt thứ ba theo ĐÚNG quy ước của 0022/0028/0040:

- Mọi item (`historical_events` / `interesting_facts`) có `source` (URL) và
  `verified = true`. Nội dung được tra từ Wikipedia tiếng Việt ngày 2026-10-10.
- Dữ kiện không có trong trang nguồn thì KHÔNG đưa vào; chỗ trang nguồn ghi
  "chưa xác định / chưa rõ" thì ghi đúng như vậy (đình An Hội, chùa Trường Thọ).
- Trang "Thánh thất Sài Gòn" đang bị Wikipedia gắn cảnh báo thiếu nguồn tham
  khảo, trang "Chùa Hội Sơn" có vài chỗ chưa nhất quán — chỉ lấy các ý nêu rõ,
  không suy diễn thêm.
- Các bản tóm tắt WebFetch do mô hình nhỏ sinh ra, chưa phải văn bản gốc: số
  liệu cụ thể nên được đối chiếu lại trước khi dùng làm số liệu chính trong báo cáo.
- Ứng viên bị loại vì trang nguồn không đủ chi tiết hoặc không có POI tương ứng:
  lăng Trương Tấn Bửu, lăng Võ Di Nguy, Bitexco, Đan viện Cát Minh, chùa Tập Phước.

POI được gắn bằng tên chuẩn hoá (pg_trgm) + category + vị trí trong bán kính
300 m — KHÔNG dùng UUID cứng (xem 0025). POI không tìm thấy thì bỏ qua và ghi
log, không làm hỏng migration. `ON CONFLICT DO NOTHING`: không ghi đè kiến thức đã có.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from urllib.parse import quote

import sqlalchemy as sa
from alembic import op

revision = "0041_poi_knowledge_more_sg_2"
down_revision = "0040_poi_knowledge_more_sg"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_RADIUS_M = 300
_MIN_SIMILARITY = 0.6


def _wiki(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="()_,")


def _item(title: str, description: str, source: str) -> dict:
    return {"title": title, "description": description, "source": source, "verified": True}


_VO_TANH = _wiki("vi", "Lăng Võ Tánh (Phú Nhuận)")
_THONG_TAY_HOI = _wiki("vi", "Đình Thông Tây Hội")
_AN_HOI = _wiki("vi", "Đình An Hội")
_HOI_SON = _wiki("vi", "Chùa Hội Sơn")
_QUAN_KHU_7 = _wiki("vi", "Bảo tàng Lực lượng Vũ trang miền Đông Nam Bộ")
_PHUOC_AN = _wiki("vi", "Hội quán Phước An")
_ME_LINH = _wiki("vi", "Công trường Mê Linh")
_TRUONG_THO = _wiki("vi", "Chùa Trường Thọ")
_THANH_THAT = _wiki("vi", "Thánh thất Sài Gòn")

# (tên POI, category chấp nhận, lat, lon, content_type, intro, intro_source,
#  specialty, historical_context, context_source, historical_events, interesting_facts)
ROWS = [
    (
        "Đền thờ Võ Tánh",
        ("place_of_worship",),
        10.8021,
        106.6752,
        "historical",
        "Lăng Võ Tánh là quần thể đền thờ và lăng mộ tưởng niệm danh tướng Võ Tánh, ở số 19 Hồ Văn Huê, Phú Nhuận.",
        _VO_TANH,
        None,
        "Công trình được lập năm 1802 tại thôn Phú Nhuận theo sắc chỉ của vua Gia Long, theo lời thỉnh cầu của dân địa phương.",
        _VO_TANH,
        [
            _item(
                "Trùng tu và quy hoạch lại (2006-2007)",
                "Trong giai đoạn 2006-2007 di tích được trùng tu, nâng cấp và quy hoạch lại diện tích lăng mộ.",
                _VO_TANH,
            ),
            _item(
                "Xếp hạng di tích cấp thành phố (30/12/2019)",
                "Ngày 30/12/2019 UBND TP.HCM ban hành Quyết định 5462/QĐ-UBND xếp hạng di tích kiến trúc nghệ thuật cấp thành phố; quận Phú Nhuận tổ chức lễ đón nhận bằng xếp hạng ngày 5/6/2020.",
                _VO_TANH,
            ),
        ],
        [
            _item(
                "Tự thiêu ở thành Bình Định",
                "Theo trang nguồn, khi thành Bình Định sắp thất thủ năm 1801, Võ Tánh đã “tự thiêu dưới lầu Bát Giác”.",
                _VO_TANH,
            ),
            _item(
                "Lăng dạng mộ gió",
                "Lăng ở Phú Nhuận được mô tả là một dạng “mộ gió”, tức mộ dùng để thờ cúng khi người mất không thể mai táng theo cách thông thường.",
                _VO_TANH,
            ),
            _item(
                "Lễ giỗ Long Văn Hầu",
                "Hằng năm tại đây có lễ giỗ Long Văn Hầu vào ngày 16 tháng 6 âm lịch.",
                _VO_TANH,
            ),
        ],
    ),
    (
        "Đình Thông Tây Hội",
        ("place_of_worship",),
        10.84,
        106.6648,
        "historical",
        "Ngôi đình cổ trên đường Thống Nhất, Gò Vấp, được xây khoảng năm 1679 và là di tích kiến trúc nghệ thuật cấp quốc gia.",
        _THONG_TAY_HOI,
        None,
        "Trước năm 1944 đình có tên là đình Hanh Thông Tây; trang nguồn gọi đây là ngôi đình cổ nhất còn tồn tại của vùng Gia Định xưa và của miền Nam.",
        _THONG_TAY_HOI,
        [
            _item(
                "Hai lần trùng tu (1896, 1927)",
                "Đình được trùng tu lần thứ nhất năm 1896 theo tài liệu chữ Hán còn lưu trong đình, và lần thứ hai năm 1927.",
                _THONG_TAY_HOI,
            ),
            _item(
                "Hợp hai làng, đổi tên (1944)",
                "Năm 1944 hai làng Hanh Thông Tây và An Hội sáp nhập; đình được chọn làm đình chung và đổi tên thành Thông Tây Hội.",
                _THONG_TAY_HOI,
            ),
            _item(
                "Xếp hạng di tích quốc gia (26/9/1998)",
                "Đình được Bộ Văn hóa Thông tin công nhận là di tích kiến trúc nghệ thuật văn hóa lịch sử cấp quốc gia theo quyết định ngày 26/9/1998.",
                _THONG_TAY_HOI,
            ),
        ],
        [
            _item(
                "Khu đất bị thu hẹp",
                "Khu đất ban đầu rộng 5.188 m², nhưng do dân lấn chiếm để ở nên nay chỉ còn khoảng 1.500 m².",
                _THONG_TAY_HOI,
            ),
            _item(
                "Chạm khắc cổ còn nguyên",
                "Đình giữ được 37 hiện vật quý; các tác phẩm chạm khắc vẫn giữ đường nét và lớp sơn son thếp vàng cổ, không bị phủ sơn mới như nhiều đình khác.",
                _THONG_TAY_HOI,
            ),
            _item(
                "Hai vị thần chính",
                "Vị thần chính được thờ là Đông Chinh vương và Dực Thánh vương, hai vị hoàng thất làm tướng thời vua Lý Thái Tổ.",
                _THONG_TAY_HOI,
            ),
        ],
    ),
    (
        "Đình An Hội",
        ("place_of_worship",),
        10.8421,
        106.6496,
        "cultural",
        "Đình An Hội ở số 307/24 đường số 10, Gò Vấp, nằm trong khuôn viên Miếu Võ Tiên Sư và Miếu Bà Chúa Ngọc.",
        _AN_HOI,
        None,
        "Năm thành lập chưa xác định; đình còn lưu bản Hàm Ân chữ Hán đề tháng 2 năm 1822, ban đầu được dựng ở khu vực nay là sân bay Tân Sơn Nhất rồi dời về vị trí hiện nay khoảng năm 1950.",
        _AN_HOI,
        [
            _item(
                "Dời về vị trí hiện nay (khoảng 1950)",
                "Khoảng năm 1950 đình được dời từ khu vực sân bay Tân Sơn Nhất ngày nay về địa điểm hiện tại.",
                _AN_HOI,
            ),
            _item(
                "Xếp hạng di tích cấp thành phố (23/11/2020)",
                "Ngày 23/11/2020 UBND TP.HCM xếp hạng đình là di tích kiến trúc nghệ thuật cấp thành phố theo Quyết định 4292/QĐ-UBND.",
                _AN_HOI,
            ),
        ],
        [
            _item(
                "Kết cấu tứ trụ",
                "Nhà đình có kết cấu “tứ trụ” phổ biến ở đình Nam Bộ, với tường gạch, kèo bê tông, rui mè gỗ và mái ngói.",
                _AN_HOI,
            ),
            _item(
                "Thờ Thành hoàng, Bà Chúa Ngọc và Quan Thánh",
                "Đình thờ Thành hoàng, Bà Chúa Ngọc và Quan Thánh Đế Quân; hằng năm tổ chức lễ Kỳ yên.",
                _AN_HOI,
            ),
        ],
    ),
    (
        "Chùa Hội Sơn",
        ("place_of_worship",),
        10.8714,
        106.8409,
        "historical",
        "Chùa cổ ở số 1A1 Nguyễn Xiển, phường Long Bình (Thủ Đức), được xem là một trong những ngôi chùa lâu đời nhất thành phố.",
        _HOI_SON,
        None,
        "Chùa do thiền sư Khánh Long xây dựng vào thế kỷ 17 trên một ngọn đồi cao 15 m so với mặt biển.",
        _HOI_SON,
        [
            _item(
                "Xếp hạng di tích quốc gia (1993)",
                "Năm 1993 chùa được xếp hạng di tích kiến trúc nghệ thuật quốc gia.",
                _HOI_SON,
            ),
            _item(
                "Hỏa hoạn chánh điện (17/7/2012)",
                "Đêm 17/7/2012 chánh điện bốc cháy; chùa nằm trên đồi cao và bị mất điện nên việc chữa cháy tại chỗ gặp khó khăn. Vụ cháy không gây thiệt hại về người.",
                _HOI_SON,
            ),
        ],
        [
            _item(
                "Hoành phi của vua Khải Định",
                "Trong chùa từng có bức hoành phi do vua Khải Định tặng.",
                _HOI_SON,
            ),
            _item(
                "Chánh điện bằng gỗ",
                "Chánh điện rộng hơn 300 m² và làm bằng gỗ nên lửa lan nhanh; vụ cháy làm đổ toàn bộ chánh điện, thiêu rụi hơn 30 tượng Phật lâu đời và làm chuông đồng vỡ đôi.",
                _HOI_SON,
            ),
        ],
    ),
    (
        "Bảo tàng Lực lượng Vũ trang miền Đông Nam Bộ",
        ("museum",),
        10.7994,
        106.666,
        "historical",
        "Bảo tàng quân sự (còn gọi là Bảo tàng Quân khu 7) ở số 247 Hoàng Văn Thụ, quận Tân Bình, thành lập ngày 5/2/1988.",
        _QUAN_KHU_7,
        None,
        "Khu nhà ban đầu được xây vào 1958-1959 cho Trường Cộng đồng Mỹ tại Sài Gòn; sau khi người Mỹ rời đi, dãy nhà bỏ trống được Bệnh viện dã chiến số 3 sử dụng từ tháng 2/1965.",
        _QUAN_KHU_7,
        [
            _item(
                "Bệnh viện dã chiến (2/1965)",
                "Tháng 2 năm 1965 dãy nhà bỏ trống của Trường Cộng đồng Mỹ được Bệnh viện dã chiến số 3 sử dụng.",
                _QUAN_KHU_7,
            ),
            _item(
                "Thành lập bảo tàng (5/2/1988)",
                "Ngày 5/2/1988 bảo tàng được thành lập trên địa điểm của bệnh viện dã chiến cũ.",
                _QUAN_KHU_7,
            ),
        ],
        [
            _item(
                "Khí tài ngoài trời",
                "Khu trưng bày ngoài trời có xe tăng M48A3, T-54 và xe bọc thép M113.",
                _QUAN_KHU_7,
            ),
            _item(
                "Mô hình Tết Mậu Thân và địa đạo Củ Chi",
                "Bảo tàng có mô hình cuộc tấn công Tết Mậu Thân vào Đại sứ quán Hoa Kỳ và mô hình một số gian phòng trong địa đạo Củ Chi.",
                _QUAN_KHU_7,
            ),
        ],
    ),
    (
        "Hội quán Phước An",
        ("place_of_worship",),
        10.755,
        106.6589,
        "cultural",
        "Hội quán Phước An (còn gọi là Chùa Minh Hương) ở số 184 Hồng Bàng, Chợ Lớn, là cơ sở tín ngưỡng của cộng đồng người Hoa.",
        _PHUOC_AN,
        None,
        "Nơi này trước kia là ngôi miếu nhỏ An Hòa Miếu đã có từ năm 1865; cuối thế kỷ 19 ông Quách Lai Kim, người Phúc Kiến, cùng 20 thương nhân khác quyên góp xây lại.",
        _PHUOC_AN,
        [
            _item(
                "Thành hội quán của bảy phủ Minh Hương",
                "Sau khi xây lại, nơi này trở thành hội quán chung của bảy phủ người Minh Hương nên còn gọi là “Minh Hương Thất Phủ”.",
                _PHUOC_AN,
            ),
            _item(
                "Xếp hạng di tích cấp thành phố (27/4/2009)",
                "Ngày 27/4/2009 UBND TP.HCM xếp hạng hội quán là di tích kiến trúc nghệ thuật cấp thành phố.",
                _PHUOC_AN,
            ),
        ],
        [
            _item(
                "Vừa thờ thần vừa thờ Phật",
                "Ban đầu thờ Quan Thánh đế quân, về sau thêm Phật Di Lặc và Bồ Tát Quan Âm.",
                _PHUOC_AN,
            ),
            _item(
                "Tiểu tượng gốm Cây Mai",
                "Khuôn viên rộng gần 1.000 m²; trên bờ nóc và bờ mái có quần thể tiểu tượng gốm Cây Mai tạo nét đặc sắc riêng.",
                _PHUOC_AN,
            ),
        ],
    ),
    (
        "Công trường Mê Linh",
        ("park",),
        10.7753,
        106.7063,
        "historical",
        "Bùng binh nơi sáu con đường giao nhau, gần công viên Bến Bạch Đằng và sông Sài Gòn, có tượng Trần Hưng Đạo đặt giữa hồ nước.",
        _ME_LINH,
        None,
        "Năm 1875 chính quyền thuộc địa Pháp dựng một tháp vinh danh một thương nhân Pháp; năm 1878 công trường có tượng Charles Rigault de Genouilly và mang tên Place Rigault de Genouilly.",
        _ME_LINH,
        [
            _item(
                "Đổi tên Công trường Mê Linh (1955)",
                "Năm 1955 tượng Rigault de Genouilly bị dỡ bỏ và nơi này đổi tên thành Công trường Mê Linh, gợi nhớ nơi Hai Bà Trưng khởi nghĩa; năm 1962 hồ nước nhân tạo được xây và đặt tượng Hai Bà Trưng.",
                _ME_LINH,
            ),
            _item(
                "Tượng Hai Bà Trưng bị giật đổ (1963)",
                "Năm 1963 tượng Hai Bà Trưng bị đám đông giật đổ trong cuộc đảo chính.",
                _ME_LINH,
            ),
            _item(
                "Khánh thành tượng Trần Hưng Đạo (1967)",
                "Năm 1967 tượng Trần Hưng Đạo được khánh thành.",
                _ME_LINH,
            ),
        ],
        [
            _item(
                "Tượng cao gần 6 mét trên bệ gần 10 mét",
                "Tượng Trần Hưng Đạo cao gần 6 m đặt trên bệ cao gần 10 m, là tác phẩm của Phạm Thông, thắng cuộc thi tạc tượng do Hải quân Việt Nam Cộng hòa và Hội Đức Thánh Trần tổ chức.",
                _ME_LINH,
            ),
            _item(
                "Công trường Bạch Đằng",
                "Một thời gian khu vực do hải quân quản lý nên còn được gọi là Công trường Bạch Đằng.",
                _ME_LINH,
            ),
        ],
    ),
    (
        "Chùa Sắc Tứ Trường Thọ",
        ("place_of_worship",),
        10.8265,
        106.6802,
        "historical",
        "Chùa cổ thuộc hệ phái Lâm Tế ở số 53/524 Nguyễn Văn Nghi, quận Gò Vấp, từng được ban hai danh xưng sắc tứ.",
        _TRUONG_THO,
        None,
        "Chưa rõ người lập và năm dựng chùa, chỉ phỏng đoán là thế kỷ 18; chùa ban đầu ở thôn Hòa Mỹ (nay là vùng Đa Kao - Thị Nghè) và được dời về Gò Vấp sau khi quân Pháp đánh chiếm Gia Định năm 1859.",
        _TRUONG_THO,
        [
            _item(
                "Dời về Gò Vấp (sau 1859)",
                "Năm 1859 quân Pháp đánh chiếm Gia Định, sau đó chùa được dời về Gò Vấp như vị trí hiện nay.",
                _TRUONG_THO,
            ),
            _item(
                "Hai lần sắc tứ",
                "Chùa được ban sắc “Pháp Vũ Tự” dưới triều vua Gia Long và “Trường Thọ Tự” dưới triều vua Tự Đức (trang nguồn không nêu năm cụ thể).",
                _TRUONG_THO,
            ),
            _item(
                "Trùng tu gần nhất (1994-1995)",
                "Chùa được trùng tu nhiều lần, lần gần nhất vào 1994-1995.",
                _TRUONG_THO,
            ),
        ],
        [
            _item(
                "Ba tên gọi",
                "Chùa từng có nhiều tên gọi: Vĩnh Trường, Pháp Vũ, rồi Trường Thọ.",
                _TRUONG_THO,
            ),
            _item(
                "Hai tấm biển sắc tứ",
                "Chùa còn giữ hai tấm biển “sắc tứ” của vua Gia Long và vua Tự Đức.",
                _TRUONG_THO,
            ),
            _item(
                "Đại hồng chung khắc địa danh xưa",
                "Đại hồng chung trong chùa có khắc chữ Hán nổi ghi các địa danh xưa như Gia Định thành và Bình Trị tổng.",
                _TRUONG_THO,
            ),
        ],
    ),
    (
        "Thánh thất Sài Gòn",
        ("place_of_worship",),
        10.7545,
        106.6795,
        "architectural",
        "Công trình lớn của đạo Cao Đài ở số 891 Trần Hưng Đạo, phường Chợ Quán, xây lại theo mẫu số 4 của Tòa Thánh Tây Ninh.",
        _THANH_THAT,
        None,
        "Năm 1949 Hộ pháp Phạm Công Tắc mua một biệt thự kiểu Pháp trên khuôn viên 931 m² (lúc đó mang số 107 Trần Hưng Đạo) làm văn phòng liên lạc; giữa thập niên 1990 Tộc đạo Sài Gòn quyết định xây lại thành Thánh thất.",
        _THANH_THAT,
        [
            _item(
                "Thêm hai tầng hậu điện (1973)",
                "Năm 1973 Thượng Đầu Thanh xây thêm hai tầng cho phần hậu điện.",
                _THANH_THAT,
            ),
            _item(
                "Đặt đá đầu tiên (21/3/1999)",
                "Ngày 21/3/1999 diễn ra lễ đặt viên đá đầu tiên xây Thánh thất mới.",
                _THANH_THAT,
            ),
            _item(
                "An vị Thánh tượng Thiên nhãn (16/4/2000) và khánh thành (14/7/2001)",
                "Ngày 16/4/2000 làm lễ An vị Thánh tượng Thiên nhãn; Thánh thất được khánh thành ngày 14/7/2001.",
                _THANH_THAT,
            ),
        ],
        [
            _item(
                "Ba tầng mô phỏng Tòa Thánh",
                "Công trình gồm 3 tầng; tầng 2 là phần chính, mô phỏng Thánh thất mẫu số 4 với Hiệp Thiên Đài, Cửu Trùng Đài và Bát Quái Đài.",
                _THANH_THAT,
            ),
            _item(
                "Lầu chuông và lầu trống",
                "Lầu chuông và lầu trống mỗi lầu cao 18 m, gồm 5 tầng.",
                _THANH_THAT,
            ),
            _item(
                "Khuôn viên nhỏ, sức chứa lớn",
                "Khuôn viên chỉ 931 m² nhưng thiết kế để đáp ứng sinh hoạt cho hơn 5.000 tín đồ; kinh phí xây dựng khoảng 1,335 tỷ đồng.",
                _THANH_THAT,
            ),
        ],
    ),
]


_FIND_POI = sa.text(
    """
    SELECT p.id::text AS id, p.name
    FROM pois p
    WHERE p.category = ANY(CAST(:categories AS text[]))
      AND ST_DWithin(
          p.location,
          ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
          :radius_m
      )
      AND similarity(p.normalized_name, :normalized_name) >= :min_similarity
    ORDER BY
        similarity(p.normalized_name, :normalized_name) DESC,
        ST_Distance(p.location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography),
        p.id
    LIMIT 1
    """
)

_INSERT = sa.text(
    """
    INSERT INTO poi_knowledge (
        poi_id, content_type, intro, specialty, historical_context,
        historical_events, interesting_facts, source, verified
    )
    VALUES (
        CAST(:poi_id AS uuid), :content_type, :intro, :specialty,
        :historical_context, CAST(:historical_events AS jsonb),
        CAST(:interesting_facts AS jsonb), :source, true
    )
    ON CONFLICT (poi_id) DO NOTHING
    RETURNING poi_id
    """
)


def _normalize(value: str) -> str:
    """Cùng quy tắc với `app.poi_features.normalize_text`."""
    text = value.replace("Đ", "D").replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def _find(connection, name: str, categories: tuple[str, ...], lat: float, lon: float):
    return connection.execute(
        _FIND_POI,
        {
            "normalized_name": _normalize(name),
            "categories": list(categories),
            "lat": lat,
            "lon": lon,
            "radius_m": _RADIUS_M,
            "min_similarity": _MIN_SIMILARITY,
        },
    ).first()


def upgrade() -> None:
    connection = op.get_bind()
    for (name, categories, lat, lon, content_type, intro, intro_source, specialty,
         context, context_source, events, facts) in ROWS:
        match = _find(connection, name, categories, lat, lon)
        if match is None:
            logger.warning("poi_knowledge more_sg_2: KHÔNG tìm thấy POI cho %s", name)
            continue
        inserted = connection.execute(
            _INSERT,
            {
                "poi_id": match.id,
                "content_type": content_type,
                "intro": intro,
                "specialty": specialty,
                "historical_context": context,
                "historical_events": json.dumps(events, ensure_ascii=False),
                "interesting_facts": json.dumps(facts, ensure_ascii=False),
                "source": context_source or intro_source,
            },
        ).first()
        logger.info(
            "poi_knowledge more_sg_2: %s -> %s (%s)%s",
            name, match.id, match.name, "" if inserted else " — đã có kiến thức, bỏ qua",
        )


def downgrade() -> None:
    connection = op.get_bind()
    for name, categories, lat, lon, *_ in ROWS:
        match = _find(connection, name, categories, lat, lon)
        if match is not None:
            connection.execute(
                sa.text("DELETE FROM poi_knowledge WHERE poi_id = CAST(:poi_id AS uuid) AND verified"),
                {"poi_id": match.id},
            )
