# P1 — Tìm chỗ gửi xe theo loại xe, có giá và giờ hoạt động

Ngày: 2026-09-25. Mã nguồn: `backend/app/parking.py`, `parking_tags.py`,
`parking_pricing.py`, `charging_import.py`, migration `0024_parking_facilities`;
giao diện `frontend/components/parking-finder.tsx`, `parking-info.tsx`.

## 1. Vấn đề (đo trên dữ liệu thật)

Overpass API, bbox TP.HCM `10.20,106.00,11.40,107.40`, ngày 2026-09-25:

| Loại OSM | Số điểm | Có tên | Có giá (`charge`) | Có giờ (`opening_hours`) |
|---|---|---|---|---|
| `amenity=parking` | 621 | 50 | 6 | 3 |
| `amenity=motorcycle_parking` | 203 | 15 | 2 | 3 |
| `amenity=charging_station` | 25 | 9 | 0 | 2 |

- Chưa tới **1%** bãi xe có giá hoặc giờ mở cửa. Không có nguồn dữ liệu mở nào
  khác về giá gửi xe ở Việt Nam.
- Bộ nhập cũ chỉ lấy POI **có tên**, nên bỏ mất ~92% bãi xe (chỉ còn 50).
- Khung giá trông giữ xe của TP.HCM (QĐ 35/2018/QĐ-UBND) **đã bị bãi bỏ từ
  16/01/2026** (QĐ 344/QĐ-UBND), và không tìm thấy văn bản thay thế. Vì vậy
  không thể nói "giá theo quy định" cho bãi tư nhân.

Google Maps và các ứng dụng bản đồ phổ biến không hiển thị giá gửi xe máy ở
Việt Nam. Đây là khoảng trống mà đề tài giải quyết.

## 2. Đóng góp (tính mới)

### 2.1. Tìm theo loại phương tiện, với dữ liệu tri-state
Người dùng chọn Xe máy / Ô tô / Xe điện. Mỗi bãi có trạng thái
`yes | no | unknown` cho từng loại xe. Trạng thái này suy ra từ `amenity`
(`motorcycle_parking`), từ các thẻ `motorcycle` / `motorcar`, từ loại xe ghi
trong giá, và từ tên bãi ("Bãi gửi xe hai bánh"). Hệ thống phân biệt
"không nhận" với "chưa rõ": bãi chưa rõ vẫn hiện, nhưng bị phạt điểm và có
nhãn "chưa chắc nhận".

### 2.2. Chuẩn hoá giá dạng chữ tự do
`parse_price` đọc các chuỗi thật như `"5000 VND/bike, 20000 VND/car"`,
`"30k VND"`, `"Xe máy ban ngày 4.000đ, ban đêm 6.000đ"` thành các bản ghi
`{vehicle, amountVnd, unit ∈ lượt|giờ|ngày|đêm|tháng|kWh, unitAssumed}`.
Bộ đọc làm việc thận trọng:
- Bỏ qua chuỗi không có số tiền rõ ràng.
- Khi chuỗi không ghi đơn vị, mặc định là "lượt" và đánh dấu đó là giả định.
- Giữ nguyên chuỗi gốc để đối chiếu.
Kết quả: đọc đúng cả 8/8 chuỗi giá thật trên OSM TP.HCM.

### 2.3. Giá nhiều mức tin cậy, luôn ghi nguồn
| Mức | Nguồn | Khi nào dùng |
|---|---|---|
| `community` | trung vị giá người dùng báo trong 180 ngày | từ 2 báo cáo trở lên; nếu chỉ có 1 báo cáo thì xếp sau OSM |
| `openstreetmap` | thẻ `charge` / `fee=no` | có trên OSM |
| `published` | giá niêm yết của đơn vị vận hành (V-Green 3.858 đ/kWh) | trạm sạc VinFast |
| `regulated` | NQ 01/2018/NQ-HĐND, phí đỗ ô tô lòng đường, lũy tiến theo giờ, tính phí 06:00–24:00 | chỗ đỗ ô tô ven đường |
| `reference` | bảng giá QĐ 35/2018, **ghi rõ "đã bãi bỏ"** | xe máy / xe đạp, không có giá thật |
| `unknown` | — | còn lại |

Các nguyên tắc:
- Không bao giờ trình bày một ước tính như giá thật.
- Giá phụ thuộc khu vực (Quận 1/3/5 cũ so với quận khác) được trả về dạng
  **khoảng**. Lý do: 809/813 bãi không có thông tin quận, nên hệ thống không
  đoán khu vực.

### 2.4. Crowdsource giá và giờ mở cửa
Người dùng báo giá thực tế (số tiền + đơn vị + loại xe) và giờ mở cửa.
- Chống spam: mỗi phiên chỉ được báo một lần cho mỗi bãi, mỗi loại xe, mỗi
  ngày (ràng buộc UNIQUE).
- Đồng thuận: lấy trung vị theo đơn vị được báo nhiều nhất, để không trộn giá
  theo lượt với giá theo giờ. Kèm số lượt báo, tỉ lệ trùng khớp (`agreement`)
  và ngày báo gần nhất.
- Giờ mở cửa lấy giá trị được báo nhiều nhất, và phải parse được.
Nhờ đó dữ liệu tự dày lên theo thời gian sử dụng.

### 2.5. Xếp hạng theo chi phí và điểm đến
Đầu vào: điểm đến (địa điểm đang xem hoặc vị trí người dùng), thời gian gửi
và loại xe. Với mỗi bãi trong bán kính 1 km quanh điểm đến:
- **Tiền gửi ước tính cho đúng thời gian gửi**: theo lượt, theo giờ (làm tròn
  lên), theo ngày, theo đêm; lũy tiến với phí lòng đường; tách ngày/đêm theo
  quy tắc 18:00–06:00.
- **Mở suốt thời gian gửi** (`open_throughout`), có xử lý ca qua đêm. Bãi
  **chắc chắn đóng** trong lúc gửi bị loại. Bãi chưa rõ giờ vẫn giữ nhưng bị
  phạt điểm.
- **Điểm** (thấp là tốt):

  `score = 0.5·walk + 0.35·cost + 0.15·uncertainty`

  Trong đó:
  - `walk` = quãng đi bộ / bán kính.
  - `cost` = tiền ước tính / tiền cao nhất trong nhóm. Chưa biết giá thì
    `cost` = 1, để không thưởng cho việc thiếu dữ liệu.
  - `uncertainty` = trung bình của ba độ không chắc: mức tin cậy của giá,
    giờ mở cửa chưa rõ, loại xe chưa rõ.

## 3. Dữ liệu sau khi làm lại (2026-09-25)

- Bộ nhập OSM lấy cả bãi xe / trạm sạc **không tên**. Tên được tự sinh từ
  loại + đơn vị vận hành / tên đường. Các bãi này không bị gộp trùng theo tên,
  vì hai "Bãi giữ xe máy" cách nhau 50 m là hai bãi khác nhau. Bãi
  `access=private` bị loại.
- Kết quả: 788 bãi xe và 25 trạm sạc (trước đây là 50 bãi).
- Trạm sạc có thêm nguồn Open Charge Map (`scripts/import_parking.py
  --openchargemap`, cần API key miễn phí). Trạm nằm trong 40 m quanh trạm đã
  có thì được gộp.
- Ví dụ quanh Chợ Bến Thành, bán kính 1 km: 70 chỗ cho xe máy, 51 chỗ cho ô
  tô, 1 trạm sạc.

## 4. Hạn chế (nói thẳng)

- Giá thật vẫn rất ít cho tới khi có người dùng báo. Mức `reference` chỉ là
  tham khảo từ văn bản đã hết hiệu lực.
- NQ 07/2020 có sửa NQ 01/2018 nhưng chưa đọc được toàn văn, nên chưa khẳng
  định được bảng phí lòng đường không đổi.
- Chưa có dữ liệu chỗ trống theo thời gian thực.
- Đồng thuận crowdsource chưa chống được việc cố tình báo sai có tổ chức
  (nhiều phiên giả).
- Trọng số 0.5 / 0.35 / 0.15 được chọn theo lập luận, chưa được học từ dữ
  liệu hành vi.

## 5. Hướng đánh giá đề xuất

- **Độ phủ**: tỉ lệ bãi có giá theo từng mức tin cậy, trước và sau một đợt
  thu thập báo cáo.
- **Độ chính xác của bộ đọc giá**: gán nhãn tay các chuỗi `charge` và đo
  precision / recall.
- **Chất lượng xếp hạng**: với một tập điểm đến, so thứ hạng theo "gần nhất"
  với thứ hạng theo `score`, bằng khảo sát người dùng (bãi nào họ thực sự
  chọn).

## Nguồn pháp lý

- QĐ 344/QĐ-UBND (16/01/2026), bãi bỏ QĐ 35/2018:
  https://congbao.hochiminhcity.gov.vn/cong-bao/van-ban/quyet-dinh/so/344-qd-ubnd/ngay/16-01-2026/noi-dung/49047
- NQ 01/2018/NQ-HĐND, phí đỗ ô tô lòng đường:
  https://congbao.hochiminhcity.gov.vn/cong-bao/van-ban/nghi-quyet/so/01-2018-nq-hdnd/ngay/16-03-2018/noi-dung/42994
- V-Green, giá sạc 3.858 đ/kWh: https://vgreen.net/vi/san-pham-dich-vu
