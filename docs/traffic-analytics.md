# Thống kê truy cập website

Trong Quản trị viên → Tổng quan, mục Lượt truy cập website hiển thị lượt tải
trang hôm nay, lượt tải trang/phiên mở trang/trình duyệt trong 7, 14 hoặc 30 ngày,
biểu đồ theo ngày và phân bố thiết bị. Báo cáo CSV gồm các chỉ số này.

- Một `page_view` được ghi khi tải ứng dụng, kể cả chưa bật GPS hoặc đăng nhập.
  Tải lại tăng lượt tải trang; React remount không tăng thêm.
- `session_id` hiện có của Nearby là ID trình duyệt lưu trong localStorage,
  không phải người thật. Nhiều máy, chế độ riêng tư hoặc xoá storage có thể đếm riêng.
- `metadata.visit_id` được lưu trong sessionStorage để nhóm các lần tải lại
  trong cùng phiên mở trang. Đây không phải phiên hết hạn sau 30 phút.
- Thiết bị là nhóm suy ra từ trình duyệt (điện thoại, máy tính bảng, máy tính),
  không bảo đảm chính xác tuyệt đối. Sự kiện không gửi IP, vị trí, URL hay user-agent đầy đủ.
- Cả quản trị viên cũng được tính. Không phải công cụ lọc bot chuyên dụng;
  chặn request, mất mạng hay tắt JavaScript có thể khiến số liệu thiếu.
- Không suy ngược lượt truy cập lịch sử từ GPS/tìm kiếm. Mốc bắt đầu là sự kiện
  page_view đầu tiên được nhận. Chưa có dữ liệu thì hiển thị 0 và lời giải thích.
- Ranh giới ngày dùng Asia/Ho_Chi_Minh. Trình duyệt/phiên theo cả kỳ được đếm
  riêng biệt; cộng các ngày có thể lớn hơn số riêng biệt trong cả kỳ.

## Triển khai

Cần dựng lại backend, migrate, stream-worker và frontend. Chạy migration
0042 trước khi dùng frontend mới để API/DB chấp nhận page_view. Khởi động lại
stream-worker với mã mới. Không cần nhập lại POI hoặc dựng lại chỉ mục tìm kiếm
chỉ vì tính năng này. Script deploy_update.sh hiện có cũng chạy các bước backend
và migration, nhưng stream-worker cần được cập nhật riêng.

Migration không xoá lịch sử. Downgrade chỉ chạy khi chưa có page_view;
nếu đã có, phải quyết định cách lưu trữ dữ liệu trước khi quay về ràng buộc cũ.

## Kiểm thử

`node --test frontend/tests/telemetry-page-view.test.mjs`

`python -m pytest backend/tests/unit/test_page_view_event.py -c backend/pytest.ini`

Bộ kiểm thử SQL: đặt ANALYTICS_TEST_DATABASE_URL cho PostgreSQL cục bộ rồi chạy
backend/tests/integration/test_admin_traffic.py. Chỉ dùng bảng tạm trong kết nối
kiểm thử, không chỉnh dữ liệu ứng dụng.
