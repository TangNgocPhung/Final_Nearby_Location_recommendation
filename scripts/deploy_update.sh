#!/usr/bin/env bash
# Cập nhật một bản Nearby ĐANG CHẠY trên máy chủ. Chạy TRÊN VPS, tại thư mục repo:
#
#   bash scripts/deploy_update.sh
#
# Khác lần triển khai đầu (deploy/RUNBOOK.md mục 0-9): KHÔNG dựng lại OSRM
# (60-90 phút), KHÔNG nhập lại OSM, KHÔNG xin lại chứng chỉ. Chỉ kéo mã mới,
# dựng lại ảnh, chạy migration, thay container và DỰNG LẠI CHỈ MỤC.
#
# Bước chỉ mục là lý do script này tồn tại. Nó là bước duy nhất dễ quên mà hỏng
# IM LẶNG: chỉ mục OpenSearch sống độc lập với Postgres và không tự cập nhật,
# nên bỏ qua thì API vẫn trả 200 kèm kết quả — chỉ là kết quả của chỉ mục cũ.
# Không có cách nào nhìn màn hình mà biết, phải đo bằng truy vấn.
#
# Biến môi trường:
#   ENV_FILE   mặc định config/production.env
#   SKIP_PULL  =1 để bỏ qua bước kéo mã (khi đã tự checkout đúng commit)
set -uo pipefail

ENV_FILE="${ENV_FILE:-config/production.env}"
BRANCH="${BRANCH:-main}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/docker-compose.prod.yml)

die() { echo "LỖI: $*" >&2; exit 1; }
step() { echo; echo "== $* =="; }

[ -f docker-compose.yml ] || die "chạy script từ thư mục gốc của repo"
[ -f "$ENV_FILE" ] || die "không thấy $ENV_FILE. File này chứa mật khẩu nên không nằm trong git — chép từ máy dev sang (RUNBOOK mục 3)."

# --- 1. Kéo mã mới ------------------------------------------------------------
#
# Chỉ nhận fast-forward. Lịch sử phân nhánh mà `git pull` tự merge thì máy chủ
# chạy một commit không ai từng kiểm thử — thà dừng và báo còn hơn.
if [ "${SKIP_PULL:-0}" != "1" ]; then
  step "Kéo mã mới ($BRANCH)"
  git fetch origin "$BRANCH" || die "không fetch được"
  git checkout "$BRANCH" || die "không checkout được $BRANCH"
  if ! git merge --ff-only "origin/$BRANCH"; then
    echo >&2
    echo "Lịch sử local đã phân nhánh khỏi origin/$BRANCH (thường là do lịch sử" >&2
    echo "trên GitHub đã được viết lại). Nếu máy chủ KHÔNG có commit riêng cần giữ:" >&2
    echo >&2
    echo "    git reset --hard origin/$BRANCH" >&2
    echo >&2
    die "dừng ở đây để bạn tự quyết, không tự ý xoá lịch sử của máy chủ"
  fi
fi
echo "Đang ở commit: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"

# --- 2. Dựng ảnh TRƯỚC KHI migrate --------------------------------------------
#
# Thứ tự này là bắt buộc, và đây là lỗi đã gặp thật trên production
# (19/09/2026): `migrate`, `search-index` và `backend` cùng khai báo
# `build: ./backend`, nhưng Compose dựng cho mỗi service MỘT ẢNH RIÊNG
# (`<project>-migrate`, `<project>-search-index`, `<project>-backend`).
#
# Bản trước chạy `run --rm migrate` trước rồi mới `build backend frontend`, nên
# migration chạy bằng ảnh migrate CŨ: alembic không thấy file migration mới,
# báo "đã ở head" rồi thoát 0 — không một dấu hiệu lỗi nào. Sau đó
# `search-index` cũng dùng ảnh cũ nên index lại đủ 15977 POI mà thiếu hẳn
# trường `search_keywords`. Kết quả: deploy báo thành công, site chạy mã mới,
# nhưng dữ liệu và chỉ mục vẫn là của phiên bản cũ.
#
# Vì vậy: dựng ĐỦ bốn ảnh trước, rồi mới chạy bất cứ thứ gì.
step "Dựng lại ảnh (backend, frontend, migrate, search-index)"
"${COMPOSE[@]}" --profile data build backend frontend migrate search-index \
  || die "build thất bại"

# --- 3. Migration -------------------------------------------------------------
step "Chạy migration"
"${COMPOSE[@]}" run --rm migrate || die "migration thất bại — DỪNG, không thay container"

# --- 4. Thay container --------------------------------------------------------
#
# --no-deps: chỉ thay backend/frontend, không đụng tới database/opensearch/neo4j
# và ba container OSRM đang giữ 2,6 GB đồ thị trong bộ nhớ.
step "Khởi động lại backend + frontend"
"${COMPOSE[@]}" up -d --no-deps backend frontend || die "không khởi động lại được"

# --- 5. Dựng lại chỉ mục ------------------------------------------------------
step "Dựng lại chỉ mục OpenSearch (bắt buộc)"
"${COMPOSE[@]}" --profile data run --rm search-index || die "dựng chỉ mục thất bại — site đang chạy mã mới nhưng CHỈ MỤC CŨ, kết quả tìm kiếm sẽ sai"

# --- 6. Đo, đừng đoán ---------------------------------------------------------
step "Kiểm chứng"
PUBLIC_HOST="$(grep -E '^PUBLIC_HOST=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
if [ -z "$PUBLIC_HOST" ]; then
  echo "Không đọc được PUBLIC_HOST từ $ENV_FILE, bỏ qua bước đo."
  exit 0
fi

echo "- Trang chủ:"
curl -sI "https://$PUBLIC_HOST/" | head -1

echo "- Nhãn trả về cho truy vấn \"xem phim\" (mong đợi: chỉ có \"Xem phim\"):"
curl -s -X POST "https://$PUBLIC_HOST/api/v1/search" \
     -H 'Content-Type: application/json' \
     -d '{"query":"xem phim","latitude":10.7757,"longitude":106.7009,"radius":3000,"limit":10}' \
  | grep -o '"categoryLabel":"[^"]*"' | sort | uniq -c

echo
echo "Lẫn nhãn khác \"Xem phim\" nghĩa là chỉ mục chưa được dựng lại, KHÔNG phải"
echo "xếp hạng sai — xem lại bước 5 ở trên."
