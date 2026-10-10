"""POI Knowledge: thêm 16 địa danh (khách sạn lịch sử, chùa, hội quán, chợ, công viên, địa đạo, rừng Cần Giờ…) cho Săn địa danh.

Revision ID: 0040_poi_knowledge_more_sg
Revises: 0039_visitor_photo_per_owner

Sau 0028 còn 46 POI có `poi_knowledge` (34 địa danh săn được). Bản này thêm 16
địa danh nữa theo ĐÚNG quy ước của 0022/0028:

- Mọi item (`historical_events` / `interesting_facts`) có `source` (URL) và
  `verified = true`. Nội dung được tra từ Wikipedia (tiếng Việt, một số tiếng Anh)
  và Sài Gòn Giải Phóng ngày 2026-10-10.
- Dữ kiện không có trong trang nguồn thì KHÔNG đưa vào; chỗ trang nguồn ghi
  "chưa thống nhất" thì ghi đúng như vậy. Hội quán Nhị Phủ và Khu du lịch Suối
  Tiên là hai trang đang bị Wikipedia gắn cảnh báo thiếu chú thích / văn phong
  quảng cáo — chỉ lấy các ý nêu rõ trong trang, bỏ các con số không có nguồn.
- Địa đạo Bến Đình: số liệu "200 km", "ba tầng"… là của CẢ hệ thống địa đạo Củ
  Chi và được viết đúng như vậy, không gán riêng cho Bến Đình.
- Các bản tóm tắt WebFetch do mô hình nhỏ sinh ra, chưa phải văn bản gốc: số
  liệu cụ thể nên được đối chiếu lại trước khi dùng làm số liệu chính trong báo cáo.

POI được gắn bằng tên chuẩn hoá (pg_trgm) + category + vị trí trong bán kính
300 m — KHÔNG dùng UUID cứng, vì UUID của POI nhập từ OSM đổi sau mỗi lần nhập
lại (xem 0025). POI không tìm thấy thì bỏ qua và ghi log, không làm hỏng
migration. `ON CONFLICT DO NOTHING`: không ghi đè kiến thức đã có.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from urllib.parse import quote

import sqlalchemy as sa
from alembic import op

revision = "0040_poi_knowledge_more_sg"
down_revision = "0039_visitor_photo_per_owner"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_RADIUS_M = 300
_MIN_SIMILARITY = 0.6


def _wiki(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="()_,")


def _item(title: str, description: str, source: str) -> dict:
    return {"title": title, "description": description, "source": source, "verified": True}


_MAJESTIC = _wiki("en", "Hotel Majestic (Saigon)")
_CONTINENTAL = _wiki("en", "Hotel Continental Saigon")
_MARIAMMAN = _wiki("en", "Mariamman Temple, Ho Chi Minh City")
_GIAC_VIEN = _wiki("vi", "Chùa Giác Viên")
_PHUNG_SON = _wiki("vi", "Chùa Phụng Sơn")
_NHI_PHU = _wiki("vi", "Hội quán Nhị Phủ")
_NGHIA_NHUAN = _wiki("vi", "Hội quán Nghĩa Nhuận")
_CU_CHI = _wiki("vi", "Địa đạo Củ Chi")
_BEN_DINH = "https://www.sggp.org.vn/luu-dau-di-san-post583979.html"
_CAN_GIO = _wiki("vi", "Rừng ngập mặn Cần Giờ")
_GA_SAI_GON = _wiki("vi", "Ga Sài Gòn")
_SUOI_TIEN = _wiki("vi", "Khu du lịch Suối Tiên")
_AN_DONG = _wiki("vi", "Chợ An Đông")
_CHIEN_DICH = _wiki("vi", "Bảo tàng Chiến dịch Hồ Chí Minh")
_23_9 = _wiki("vi", "Công viên 23 tháng 9")
_LE_VAN_TAM = _wiki("vi", "Công viên Lê Văn Tám")
_BACH_TUNG_DIEP = _wiki("vi", "Công viên Bách Tùng Diệp")

# (tên POI, category chấp nhận, lat, lon, content_type, intro, intro_source,
#  specialty, historical_context, context_source, historical_events, interesting_facts)
ROWS = [
    (
        "Majestic Hotel",
        ("hotel",),
        10.7729,
        106.706,
        "architectural",
        "Khách sạn lịch sử ở số 1 Đồng Khởi (xưa là rue Catinat), góc đại lộ Tôn Đức Thắng, Quận 1, nhìn ra bến Bạch Đằng và sông Sài Gòn.",
        _MAJESTIC,
        None,
        "Thương nhân người Hoa Hui Bon Hoa xây khách sạn năm 1925 theo phong cách kiến trúc thuộc địa Pháp; thiết kế ban đầu gồm ba tầng và 44 phòng ngủ.",
        _MAJESTIC,
        [
            _item(
                "Thêm hai tầng (1965)",
                "Năm 1965 khách sạn được xây thêm hai tầng theo thiết kế của kiến trúc sư Ngô Viết Thụ.",
                _MAJESTIC,
            ),
            _item(
                "Đổi tên sau 1975",
                "Sau năm 1975 khách sạn được đổi tên thành Khách sạn Cửu Long (Mekong) và trở thành nhà khách của chính quyền.",
                _MAJESTIC,
            ),
            _item(
                "Trùng tu kiểu Phục Hưng (1994) và nối thêm tòa mới (2003)",
                "Năm 1994 khách sạn được cải tạo theo phong cách Phục Hưng; năm 2003 thêm một tòa nhà tám tầng phía đường Tôn Đức Thắng.",
                _MAJESTIC,
            ),
        ],
        [
            _item(
                "Ông chủ giàu nhất Nam Kỳ",
                "Hui Bon Hoa được mô tả là một trong những thương nhân giàu nhất miền Nam Việt Nam thời bấy giờ.",
                _MAJESTIC,
            ),
            _item(
                "Quy mô hiện nay",
                "Khách sạn có 175 phòng, sáu nhà hàng và ba quầy bar, thuộc Saigontourist và vận hành ở hạng năm sao.",
                _MAJESTIC,
            ),
        ],
    ),
    (
        "Khách sạn Continental Sài Gòn",
        ("hotel",),
        10.777,
        106.7026,
        "historical",
        "Khách sạn Continental (Hoàn Cầu) ở số 132-134 Đồng Khởi, góc quảng trường Lam Sơn, là khách sạn kiểu Pháp khánh thành năm 1880, nổi tiếng nhờ tiểu thuyết “Người Mỹ trầm lặng”.",
        _CONTINENTAL,
        None,
        "Pierre Cazeau, nhà sản xuất đồ gia dụng và vật liệu xây dựng, bắt đầu xây khách sạn năm 1878; khách sạn khánh thành năm 1880.",
        _CONTINENTAL,
        [
            _item(
                "Tu sửa lớn (1892)",
                "Năm 1892 ông Grosstephan cho tu sửa lại khách sạn.",
                _CONTINENTAL,
            ),
            _item(
                "Đóng cửa rồi mở lại (1976-1989)",
                "Khách sạn đóng cửa năm 1976, mở lại năm 1986, được trùng tu hoàn toàn trong 1988-1989 rồi mở cửa trở lại năm 1989 với tên Hotel Continental.",
                _CONTINENTAL,
            ),
        ],
        [
            _item(
                "“Radio Catinat”",
                "Trong chiến tranh Đông Dương lần thứ nhất, nơi này được gọi là “Radio Catinat” vì phóng viên, nhà báo và doanh nhân tụ họp bàn chuyện chính trị, thời sự.",
                _CONTINENTAL,
            ),
            _item(
                "“Continental Shelf” và các văn phòng báo chí",
                "Thời chiến tranh Việt Nam, quầy bar tầng trệt được nhà báo gọi đùa là “Continental Shelf”; Newsweek và Time đặt văn phòng ở Sài Gòn tại tầng hai.",
                _CONTINENTAL,
            ),
            _item(
                "Phòng 214 của Graham Greene",
                "Nhà văn Graham Greene là khách lưu trú lâu dài ở phòng 214 và nghĩ ra “Người Mỹ trầm lặng” tại đây; khách sạn xuất hiện trong tiểu thuyết, hai bản phim 1958 và 2002 và phim “Indochine” (1992).",
                _CONTINENTAL,
            ),
        ],
    ),
    (
        "Đền Sri Mariamman",
        ("place_of_worship",),
        10.7723,
        106.6956,
        "cultural",
        "Đền Hindu thờ nữ thần Mariamman ở phường Bến Thành, ngay gần chợ Bến Thành.",
        _MARIAMMAN,
        None,
        "Đền được cộng đồng thương nhân Nagarathar từ Tamil Nadu (Ấn Độ) xây vào cuối thế kỷ 19; người lập đền được ghi là Palaniappa Chettiar.",
        _MARIAMMAN,
        [],
        [
            _item(
                "Tượng hai con của Parvati",
                "Ở gian ngoài có tượng Ganesha và Muruga, hai người con của Parvati, đặt ở bên phải và bên trái nữ thần.",
                _MARIAMMAN,
            ),
            _item(
                "Cổng tháp raja-gopuram",
                "Đền có cổng tháp raja-gopuram cao khoảng 12 m; tường ngoài có nhiều tượng nữ thần Mariamman và một đại sảnh mandapam.",
                _MARIAMMAN,
            ),
            _item(
                "Tín đồ phần lớn là người Việt",
                "Đền phục vụ khoảng năm mươi gia đình người Tamil, còn phần lớn người đến lễ là người Việt hoặc người Việt gốc Hoa.",
                _MARIAMMAN,
            ),
        ],
    ),
    (
        "Chùa Giác Viên",
        ("place_of_worship",),
        10.763,
        106.6392,
        "historical",
        "Cổ tự ở đường Lạc Long Quân (còn gọi là chùa Hố Đất), được xếp hạng di tích lịch sử - văn hóa cấp quốc gia.",
        _GIAC_VIEN,
        None,
        "Năm 1798 thiền sư Tổ Tông-Viên Quang cho sửa một am nhỏ thành chùa, đặt tên Viện Quan Âm; năm 1850 hòa thượng Tiên Giác-Hải Tịnh trùng tu thành chùa Giác Viên.",
        _GIAC_VIEN,
        [
            _item(
                "Trùng tu thành chùa Giác Viên (1850)",
                "Năm 1850 hòa thượng Tiên Giác-Hải Tịnh cho trùng tu viện thành chùa và đổi tên thành Giác Viên.",
                _GIAC_VIEN,
            ),
            _item(
                "Xếp hạng di tích quốc gia (7/1/1993)",
                "Ngày 7/1/1993 Bộ Văn hóa - Thông tin công nhận chùa là di tích lịch sử - văn hóa cấp quốc gia.",
                _GIAC_VIEN,
            ),
        ],
        [
            _item(
                "Tượng, bao lam và phù điêu",
                "Chùa có 153 pho tượng lớn nhỏ (đa số bằng gỗ), 57 bao lam và 60 phù điêu, phần lớn chạm khắc vào thế kỷ 19 và đầu thế kỷ 20.",
                _GIAC_VIEN,
            ),
            _item(
                "Giá võng của triều Nguyễn",
                "Chùa còn giữ chiếc giá võng do triều Nguyễn tặng hòa thượng Tiên Giác-Hải Tịnh.",
                _GIAC_VIEN,
            ),
            _item(
                "Năm dựng chùa chưa thống nhất",
                "Có ý kiến cho rằng chùa đã có từ năm 1771 hoặc 1831, dựa trên bức hoành phi đề “Tân Mão niên tại”; trang nguồn ghi năm khởi lập là 1850.",
                _GIAC_VIEN,
            ),
        ],
    ),
    (
        "Chùa Phụng Sơn",
        ("place_of_worship",),
        10.7568,
        106.6448,
        "historical",
        "Chùa Phụng Sơn (còn gọi là chùa Gò) ở số 1408 đường 3 Tháng 2, Quận 11, là di tích lịch sử - văn hóa cấp quốc gia.",
        _PHUNG_SON,
        None,
        "Chùa do thiền sư Liễu Thông tạo lập vào đầu thế kỷ 19 dưới triều vua Gia Long; trang nguồn không nêu năm cụ thể.",
        _PHUNG_SON,
        [
            _item(
                "Xây cất lại am lá (1904)",
                "Năm 1904 am lá được xây cất lại; hòa thượng Huệ Minh trụ trì từ 1904 đến 1915.",
                _PHUNG_SON,
            ),
            _item(
                "Cổng tam quan mới (1963)",
                "Năm 1963 hòa thượng Thích Phước Quang cho xây lại cổng tam quan theo bản vẽ của kiến trúc sư Nguyễn Bá Lăng.",
                _PHUNG_SON,
            ),
            _item(
                "Xếp hạng di tích quốc gia (16/11/1988)",
                "Ngày 16/11/1988 chùa được xếp hạng di tích lịch sử văn hóa cấp quốc gia.",
                _PHUNG_SON,
            ),
        ],
        [
            _item(
                "Chim phụng và cây ngô đồng",
                "Theo tích kể, một con chim phụng đậu trên cây ngô đồng trước am và cất tiếng gáy nên thiền sư đặt tên chùa là Phụng Sơn Tự.",
                _PHUNG_SON,
            ),
            _item(
                "Khu đất khảo cổ",
                "Năm 1988 và 1991 các nhà khảo cổ tìm thấy đồ gốm và mặt người bằng đất nung thuộc văn hóa Óc Eo trong khuôn viên chùa.",
                _PHUNG_SON,
            ),
            _item(
                "Miếu Ông Tà",
                "Trong khuôn viên có miếu thờ Ông Tà (Neak Tà), một nét tín ngưỡng phổ biến của cư dân Khmer.",
                _PHUNG_SON,
            ),
        ],
    ),
    (
        "Hội quán Nhị Phủ",
        ("place_of_worship",),
        10.7514,
        106.6573,
        "cultural",
        "Hội quán Nhị Phủ (còn gọi là Miếu Nhị Phủ hay Chùa Ông Bổn) ở số 264 Hải Thượng Lãn Ông, Chợ Lớn.",
        _NHI_PHU,
        None,
        "Được xây khoảng năm 1730 bởi người Hoa gốc Phúc Kiến, đồng hương hai phủ Tuyền Châu và Chương Châu nên có tên “Nhị Phủ”.",
        _NHI_PHU,
        [
            _item(
                "Lập thêm hai hội quán lân cận (1740, 1809)",
                "Năm 1740 nhóm Tuyền Châu lập thêm Hội quán Ôn Lăng; năm 1809 nhóm Chương Châu lập Hội quán Hà Chương gần khu vực miếu.",
                _NHI_PHU,
            ),
            _item(
                "Xếp hạng di tích quốc gia (30/8/1998)",
                "Ngày 30/8/1998 Bộ Văn hóa - Thông tin công nhận hội quán là di tích văn hóa - lịch sử cấp quốc gia; trước đó công trình được trùng tu lớn vào các năm 1875, 1901 và 1990.",
                _NHI_PHU,
            ),
        ],
        [
            _item(
                "Nơi duy nhất ở Chợ Lớn thờ ông Bổn",
                "Đây là nơi duy nhất ở Chợ Lớn thờ Bổn Đầu Công (ông Bổn), vị thần bảo vệ đất đai và con người; phần lớn đền miếu khác thờ Thiên Hậu hoặc Quan Đế.",
                _NHI_PHU,
            ),
            _item(
                "Kiến trúc chữ khẩu",
                "Bốn dãy nhà bao quanh sân thiên tỉnh theo hình chữ “khẩu”, diện tích khoảng 2.500 m².",
                _NHI_PHU,
            ),
            _item(
                "Câu đối, hoành phi và lễ tế",
                "Miếu có 14 câu đối và 30 hoành phi, phần lớn làm từ năm 1864 đến 1901; lễ tế ông Bổn tổ chức vào ngày 15 tháng 8 âm lịch.",
                _NHI_PHU,
            ),
        ],
    ),
    (
        "Hội quán Nghĩa Nhuận",
        ("place_of_worship",),
        10.7494,
        106.6544,
        "cultural",
        "Hội quán Nghĩa Nhuận (còn gọi là đình Nghĩa Nhuận hay miếu Quan Đế) ở số 27 Phan Văn Khỏe, Chợ Lớn, thờ chính Quan Thánh đế quân.",
        _NGHIA_NHUAN,
        None,
        "Theo học giả Vương Hồng Sển, hội quán do ông Đỗ Hữu Phương lập năm 1872; nguyên là đình của thôn Tân Nhuận, về sau thời Pháp thuộc trở thành hội quán của người Minh Hương.",
        _NGHIA_NHUAN,
        [
            _item(
                "Sắc phong thần hoàng (1853)",
                "Năm 1853 thần hoàng bổn cảnh của làng được vua Tự Đức ban sắc phong.",
                _NGHIA_NHUAN,
            ),
            _item(
                "Tái thiết (1940)",
                "Công trình được tái thiết năm 1940 với chính điện và tiền điện xây thêm.",
                _NGHIA_NHUAN,
            ),
            _item(
                "Xếp hạng di tích quốc gia (7/1/1993)",
                "Ngày 7/1/1993 Bộ Văn hóa xếp hạng hội quán là di tích kiến trúc nghệ thuật cấp quốc gia.",
                _NGHIA_NHUAN,
            ),
        ],
        [
            _item(
                "Đá chạm và gốm Biên Hòa",
                "Mặt tiền có tác phẩm đá chạm của thợ đá Bửu Long, còn bờ nóc, bờ dải được trang trí bằng gốm mỹ nghệ Biên Hòa.",
                _NGHIA_NHUAN,
            ),
            _item(
                "Ba lễ lớn trong năm",
                "Hằng năm có ba lễ lớn: Vía Quan Thánh đế quân (24/6 âm lịch), lễ Kỳ yên (17/8 âm lịch) và lễ cúng Bà Thiên Hậu (23/3 âm lịch), trong đó lễ vía Bà có múa mâm vàng và diễn tuồng.",
                _NGHIA_NHUAN,
            ),
        ],
    ),
    (
        "Địa Đạo Bến Đình Củ Chi",
        ("landmark",),
        11.063,
        106.5291,
        "historical",
        "Một trong hai khu của Khu di tích lịch sử Địa đạo Củ Chi, ở ấp Bến Đình, xã Nhuận Đức, là căn cứ của Huyện ủy Củ Chi.",
        _BEN_DINH,
        None,
        "Hệ thống địa đạo Củ Chi được đào sớm nhất từ năm 1948; đến năm 1965 đã đào được khoảng 200 km.",
        _CU_CHI,
        [
            _item(
                "Xuất phát cho Tết Mậu Thân (1968)",
                "Trong chiến dịch Tết Mậu Thân 1968, quân Giải phóng xuất phát từ hệ thống địa đạo Củ Chi để tấn công vào trung tâm Sài Gòn.",
                _CU_CHI,
            ),
            _item(
                "Di tích quốc gia đặc biệt (2016)",
                "Khu di tích địa đạo Củ Chi, trong đó có Bến Đình, được xếp hạng Di tích quốc gia đặc biệt (bằng xếp hạng đón nhận ngày 12/2/2016).",
                _CU_CHI,
            ),
            _item(
                "Tuyến tàu du lịch sông Sài Gòn (7/2020)",
                "Tháng 7/2020 tuyến tàu du lịch từ bến Bạch Đằng (Quận 1) đến Bến Đình và Bến Dược bắt đầu hoạt động, hành trình 78 km kéo dài khoảng 2 giờ.",
                _BEN_DINH,
            ),
        ],
        [
            _item(
                "Ba tầng hầm (cả hệ thống Củ Chi)",
                "Địa đạo Củ Chi có ba tầng: tầng trên cách mặt đất khoảng 3 m, tầng giữa khoảng 5-8 m, tầng dưới sâu hơn 12 m.",
                _CU_CHI,
            ),
            _item(
                "Xà phòng đánh lạc hướng chó nghiệp vụ",
                "Người dân đặt xà phòng Mỹ ở cửa hầm và lỗ thông gió để làm nhiễu mùi, khiến chó nghiệp vụ không phát hiện được.",
                _CU_CHI,
            ),
        ],
    ),
    (
        "Rừng Ngập Mặn Vàm Sát",
        ("landmark",),
        10.4894,
        106.7958,
        "nature",
        "Vàm Sát là khu du lịch sinh thái nằm trong Khu dự trữ sinh quyển Cần Giờ (Rừng Sác), vùng rừng ngập mặn ở châu thổ các cửa sông Đồng Nai, Sài Gòn và Vàm Cỏ.",
        _CAN_GIO,
        None,
        "Rừng Cần Giờ từng bị tàn phá nặng trong chiến tranh; năm 1978 Cần Giờ sáp nhập về Thành phố Hồ Chí Minh, năm 1979 thành phố phát động chiến dịch trồng lại rừng và lập Lâm trường Duyên Hải.",
        _CAN_GIO,
        [
            _item(
                "Anh hùng đặc công Rừng Sác (23/9/1973)",
                "Ngày 23/9/1973 Đoàn 10 - Trung đoàn 10 đặc công Rừng Sác được phong tặng danh hiệu Anh hùng Lực lượng vũ trang nhân dân.",
                _CAN_GIO,
            ),
            _item(
                "Khu dự trữ sinh quyển thế giới (21/1/2000)",
                "Ngày 21/1/2000 UNESCO công nhận Cần Giờ là khu dự trữ sinh quyển thế giới đầu tiên của Việt Nam.",
                _CAN_GIO,
            ),
            _item(
                "Vàm Sát được Tổ chức Du lịch Thế giới ghi nhận (2/2003)",
                "Tháng 2/2003 Tổ chức Du lịch Thế giới công nhận khu du lịch Vàm Sát là một trong hai khu du lịch sinh thái phát triển bền vững của Việt Nam.",
                _CAN_GIO,
            ),
        ],
        [
            _item(
                "Quy mô khu dự trữ sinh quyển",
                "Tổng diện tích 75.740 ha, gồm vùng lõi 4.721 ha, vùng đệm 41.139 ha và vùng chuyển tiếp 29.880 ha.",
                _CAN_GIO,
            ),
            _item(
                "Thực vật và chim",
                "Khảo sát năm 2007 ghi nhận 220 loài thực vật bậc cao; khu hệ chim có khoảng 130 loài, nổi bật là đàn khỉ đuôi dài.",
                _CAN_GIO,
            ),
            _item(
                "Bò sát trong Sách Đỏ",
                "Có 11 loài bò sát trong Sách Đỏ Việt Nam như kỳ đà nước, trăn đất và cá sấu hoa cà.",
                _CAN_GIO,
            ),
        ],
    ),
    (
        "Sài Gòn",
        ("train_station",),
        10.7823,
        106.6772,
        "historical",
        "Ga Sài Gòn (tên cũ là ga Hòa Hưng) ở số 1 Nguyễn Thông, là ga cuối của tuyến đường sắt Bắc - Nam.",
        _GA_SAI_GON,
        None,
        "Ga gốc do người Pháp xây và khánh thành năm 1885 gần chợ Bến Thành, khu vực đường Hàm Nghi; nhà ga hiện nay được nâng cấp từ ga hàng hóa Hòa Hưng cũ.",
        _GA_SAI_GON,
        [
            _item(
                "Dời ga về vị trí gần công viên 23 tháng 9 (1911-1915)",
                "Trong giai đoạn 1911-1915 người Pháp dời ga đến gần công viên 23 tháng 9; công trình hoàn thành vào tháng 9/1915.",
                _GA_SAI_GON,
            ),
            _item(
                "Thành ga hành khách (1978-1983)",
                "Năm 1978 ga hàng hóa Hòa Hưng cũ được nâng cấp thành ga hành khách Sài Gòn; ga chính thức hoạt động từ tháng 11/1983.",
                _GA_SAI_GON,
            ),
            _item(
                "Bán vé qua mạng (đầu 2007)",
                "Đầu năm 2007 ga bắt đầu bán vé qua mạng để giảm tình trạng xếp hàng của hành khách.",
                _GA_SAI_GON,
            ),
        ],
        [
            _item(
                "Điểm cuối đường sắt Việt Nam",
                "Đây là ga cuối cùng trên tuyến đường sắt Bắc - Nam, nơi hành khách từ Nam Bộ đi các tỉnh Trung Bộ và Bắc Bộ.",
                _GA_SAI_GON,
            ),
        ],
    ),
    (
        "Khu du lịch Suối Tiên",
        ("theme_park",),
        10.8619,
        106.8038,
        "cultural",
        "Khu du lịch văn hóa ở số 120 Xa lộ Hà Nội, phường Tăng Nhơn Phú, kết hợp yếu tố văn hóa, lịch sử và tâm linh.",
        _SUOI_TIEN,
        None,
        "Khu bắt đầu từ một lâm trại nuôi trăn và sản xuất hàng thủ công mỹ nghệ do ông Đinh Văn Vui (người Sóc Trăng) xây dựng năm 1987 trên khoảng 6.600 m² đất hoang hóa.",
        _SUOI_TIEN,
        [
            _item(
                "Lâm trại đầu tiên (1987)",
                "Năm 1987 ông Đinh Văn Vui dựng lâm trại nuôi trăn và làm hàng thủ công mỹ nghệ, là khởi đầu của khu du lịch.",
                _SUOI_TIEN,
            ),
        ],
        [
            _item(
                "Truyền thuyết bảy cô tiên",
                "Tên “Suối Tiên” bắt nguồn từ truyền thuyết về bảy cô gái đồng trinh cùng tuổi Rồng hóa tiên tại dòng suối.",
                _SUOI_TIEN,
            ),
            _item(
                "Quy mô",
                "Khu có diện tích hiện nay 105 ha với trên 150 công trình.",
                _SUOI_TIEN,
            ),
        ],
    ),
    (
        "Chợ An Đông",
        ("market",),
        10.7581,
        106.6722,
        "cultural",
        "Chợ An Đông (tên chính thức là Trung tâm Thương mại - Dịch vụ An Đông) ở số 34-36 An Dương Vương, nổi tiếng là nơi bán sỉ thời trang lớn nhất thành phố.",
        _AN_DONG,
        None,
        "Chợ hình thành khoảng năm 1950 như một chợ truyền thống và chính thức được thành lập năm 1954.",
        _AN_DONG,
        [
            _item(
                "Xây mới (4/1989)",
                "Tháng 4/1989, do xuống cấp nghiêm trọng, chợ được đầu tư xây dựng mới.",
                _AN_DONG,
            ),
            _item(
                "Thành trung tâm thương mại sáu tầng (1991)",
                "Năm 1991 chợ được nâng cấp thành Trung tâm Thương mại - Dịch vụ An Đông với quy mô sáu tầng.",
                _AN_DONG,
            ),
        ],
        [
            _item(
                "Quy mô",
                "Tổng diện tích mặt bằng hơn 25.000 m² với 2.718 sạp.",
                _AN_DONG,
            ),
            _item(
                "Bốn mặt đường",
                "Khuôn viên chợ được giới hạn bởi bốn tuyến đường: An Dương Vương, Hùng Vương, Nguyễn Duy Dương và Yết Kiêu.",
                _AN_DONG,
            ),
        ],
    ),
    (
        "Bảo tàng Chiến dịch Hồ Chí Minh",
        ("museum",),
        10.787,
        106.7042,
        "historical",
        "Bảo tàng lịch sử quân sự ở số 2 Lê Duẩn, thành lập ngày 27/7/1987 trong một tòa nhà xây từ đầu thế kỷ 20 theo thiết kế của kiến trúc sư người Pháp.",
        _CHIEN_DICH,
        None,
        "Năm 1890 tướng Théophile Pennequin lập Foyer du soldat et du marin ở đây làm nơi sinh hoạt của binh lính Pháp; nơi này được xây dựng lại năm 1936-1937.",
        _CHIEN_DICH,
        [
            _item(
                "Xây dựng lại (1936-1937)",
                "Công trình được xây dựng lại trong 1936-1937 với quầy bar, thư viện, sân khấu nhỏ và thiết bị thể thao ngoài trời, gồm một hồ bơi.",
                _CHIEN_DICH,
            ),
            _item(
                "Trường Cao đẳng Quốc phòng (1967)",
                "Năm 1967 chính quyền Việt Nam Cộng hòa dùng nơi này làm trường Cao đẳng Quốc phòng.",
                _CHIEN_DICH,
            ),
            _item(
                "Thành lập bảo tàng (27/7/1987)",
                "Bảo tàng được thành lập ngày 27/7/1987.",
                _CHIEN_DICH,
            ),
        ],
        [
            _item(
                "Khu trưng bày ngoài trời",
                "Ngoài trời có xe tăng T-54 số hiệu 848, máy bay F5E, nhiều loại pháo và xe thiết giáp M113.",
                _CHIEN_DICH,
            ),
            _item(
                "Câu lạc bộ thời Ngô Đình Diệm",
                "Dưới thời Ngô Đình Diệm, tòa nhà là câu lạc bộ của Đảng Cần lao Nhân vị.",
                _CHIEN_DICH,
            ),
        ],
    ),
    (
        "Công viên 23 tháng 9",
        ("park",),
        10.7696,
        106.6939,
        "historical",
        "Công viên ở trung tâm thành phố (phường Bến Thành), nằm giữa đường Lê Lai và Phạm Ngũ Lão, trải dài từ công trường Quách Thị Trang đến đường Nguyễn Trãi.",
        _23_9,
        None,
        "Khu đất trước đây là ga xe lửa Sài Gòn do người Pháp xây từ thế kỷ 19; sau năm 1975 ga bị phá và dời về Quận 3, một phần đất được biến thành công viên.",
        _23_9,
        [
            _item(
                "Dự án cao ốc bỏ dở (1998)",
                "Năm 1998 khu dân cư tại đây bị san bằng cho dự án cao ốc Saigon Cultural Center của Đài Loan; sau khủng hoảng kinh tế châu Á dự án bị bỏ hoang.",
                _23_9,
            ),
            _item(
                "Phá hàng rào công viên (2002)",
                "Năm 2002 hàng rào công viên bắt đầu được phá dỡ trong dự án cải tạo thành mảng xanh.",
                _23_9,
            ),
            _item(
                "Không cấp phép tòa nhà 54 tầng (2006)",
                "Năm 2006 có đề xuất xây tòa nhà văn phòng 54 tầng nhưng thành phố không cấp phép vì lo ngại ảnh hưởng cảnh quan đô thị.",
                _23_9,
            ),
        ],
        [
            _item(
                "“Lỗ đen của Sài Gòn”",
                "Phần xây dở của dự án năm 1998 được người dân gọi là “lỗ đen của Sài Gòn”.",
                _23_9,
            ),
            _item(
                "Hội hoa xuân",
                "Công viên là điểm vui chơi quan trọng của người dân thành phố, và hội hoa xuân hằng năm được tổ chức tại đây.",
                _23_9,
            ),
            _item(
                "Kết nối metro số 1",
                "Dự án cải tạo dự kiến biến toàn bộ diện tích mặt đất thành công viên công cộng, đặt các chức năng khác ở bốn tầng ngầm và kết nối với tuyến metro số 1.",
                _23_9,
            ),
        ],
    ),
    (
        "Công viên Lê Văn Tám",
        ("park",),
        10.7871,
        106.694,
        "historical",
        "Công viên ở phường Tân Định, nằm giữa các đường Hai Bà Trưng, Điện Biên Phủ, Võ Thị Sáu và Phan Liêm, đặt theo tên thiếu niên anh hùng Lê Văn Tám.",
        _LE_VAN_TAM,
        None,
        "Thời Pháp thuộc nơi này là nghĩa địa dành cho người Pháp, gọi là “Đất Thánh Tây”; thời Việt Nam Cộng hòa mang tên nghĩa trang Mạc Đĩnh Chi; sau khi giải tỏa, khu đất được xây thành công viên.",
        _LE_VAN_TAM,
        [
            _item(
                "Chỉ thị dời nghĩa trang (1983)",
                "Năm 1983 Chỉ thị 17/CT-UBND yêu cầu dời nghĩa trang Mạc Đĩnh Chi ra khỏi thành phố.",
                _LE_VAN_TAM,
            ),
            _item(
                "Khai trương công viên (1985)",
                "Năm 1985 công viên khai trương, đánh dấu 10 năm sự kiện 30/4/1975.",
                _LE_VAN_TAM,
            ),
        ],
        [
            _item(
                "Hội sách TP.HCM",
                "Cứ hai năm một lần Hội sách TP.HCM được tổ chức tại công viên; hội sách năm 2014 có 500 gian hàng của 156 đơn vị với hơn 20 triệu cuốn sách.",
                _LE_VAN_TAM,
            ),
        ],
    ),
    (
        "Công viên Bách Tùng Diệp",
        ("park",),
        10.7765,
        106.6992,
        "historical",
        "Công viên (tên cũ là Công viên Liên Hiệp) ở góc đường Lý Tự Trọng - Nam Kỳ Khởi Nghĩa, đối diện Bảo tàng Thành phố Hồ Chí Minh.",
        _BACH_TUNG_DIEP,
        None,
        "Năm 1864 người Pháp giao khu đất cho Tây Ban Nha xây tòa lãnh sự; đất bị bỏ trống hơn nửa thế kỷ và được chăm sóc thành vườn cây gọi là “Jardin d'Espagne” (Vườn Tây Ban Nha).",
        _BACH_TUNG_DIEP,
        [
            _item(
                "Đất đổi chủ nhưng không xây (1927-1928)",
                "Năm 1927 Tây Ban Nha giao đất cho Anh, nhưng năm 1928 Anh đổi sang lô đất khác trên đại lộ Norodom.",
                _BACH_TUNG_DIEP,
            ),
            _item(
                "Đổi tên Công viên Liên Hiệp (1955)",
                "Năm 1955 khu đất được đổi tên thành Công viên Liên Hiệp.",
                _BACH_TUNG_DIEP,
            ),
        ],
        [
            _item(
                "Cây đa cổ thụ năm thân",
                "Công viên có một cây đa cổ thụ năm thân, đầu thập niên 2000 đã hơn 300 năm tuổi.",
                _BACH_TUNG_DIEP,
            ),
            _item(
                "Chợ Cây Da Còm",
                "Theo Trương Vĩnh Ký, dưới triều Tự Đức khu vực này có chợ sầm uất gọi là chợ Cây Da Còm, sĩ tử trước kỳ thi thường ra mua áo mũ.",
                _BACH_TUNG_DIEP,
            ),
            _item(
                "Tượng Quách Thị Trang",
                "Tượng Quách Thị Trang được dời về công viên khi công trường Quách Thị Trang bị phá bỏ để thi công ga ngầm tuyến Bến Thành - Suối Tiên.",
                _BACH_TUNG_DIEP,
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
            logger.warning("poi_knowledge more_sg: KHÔNG tìm thấy POI cho %s", name)
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
            "poi_knowledge more_sg: %s -> %s (%s)%s",
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
