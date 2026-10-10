#!/usr/bin/env bash
# Cài Ollama trên VPS cho chatbot, kênh vector của tìm kiếm và thuyết minh.
# Chạy TRÊN VPS, một lần, trước `docker compose up`:
#
#   sudo bash deploy/install-ollama.sh
#
# Container gọi Ollama qua host.docker.internal -> host-gateway, tức IP của
# docker0 (mặc định 172.17.0.1) — xem mục 4 đầu deploy/docker-compose.prod.yml.
#
# Ollama mặc định chỉ nghe 127.0.0.1, container KHÔNG tới được. Thay vì mở
# 0.0.0.0 (lộ cổng 11434 ra internet nếu tường lửa chưa bật — Ollama không có
# xác thực, ai cũng gọi được model của bạn), script cho Ollama nghe đúng IP
# docker0: chỉ máy chủ và container gọi được.
#
# RAM: ba model dưới đây cộng lại ~6 GB khi cùng nạp, cộng ~3,6 GB của stack.
# Máy 8 GB sẽ chật; 16 GB là thoải mái.
set -euo pipefail

MODELS=(bge-m3 llama3.2:3b qwen3.5:4b)

[ "$(id -u)" -eq 0 ] || { echo "LỖI: chạy bằng sudo" >&2; exit 1; }
command -v docker >/dev/null || { echo "LỖI: cài Docker trước (RUNBOOK mục 1)" >&2; exit 1; }

# docker0 chỉ có khi dịch vụ Docker đang chạy.
systemctl start docker
BRIDGE_IP="$(ip -4 -o addr show docker0 | awk '{print $4}' | cut -d/ -f1)"
[ -n "$BRIDGE_IP" ] || { echo "LỖI: không đọc được IP của docker0" >&2; exit 1; }
echo "IP docker0: $BRIDGE_IP"

if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

# After=docker.service: Ollama nghe trên IP của docker0, nên phải khởi động SAU
# khi Docker dựng xong interface đó — không thì lúc reboot nó bind thất bại.
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/nearby.conf <<EOF
[Unit]
After=docker.service
Wants=docker.service

[Service]
Environment="OLLAMA_HOST=${BRIDGE_IP}:11434"
EOF
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

# ufw mặc định DROP mọi gói tin vào máy, kể cả từ mạng bridge của compose
# (172.16.0.0/12). Thiếu luật này thì mỗi lượt tìm kiếm treo 10 giây chờ Ollama.
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow from 172.16.0.0/12 to any port 11434 proto tcp comment "Ollama cho container"
fi
# Ảnh Ubuntu của Oracle Cloud không dùng ufw mà có sẵn luật REJECT cuối chuỗi
# INPUT (RUNBOOK mục 0) — cùng hậu quả, nên mở theo cùng cách với 80/443.
if command -v netfilter-persistent >/dev/null \
   && ! iptables -C INPUT -s 172.16.0.0/12 -p tcp --dport 11434 -j ACCEPT 2>/dev/null; then
  iptables -I INPUT 1 -s 172.16.0.0/12 -p tcp --dport 11434 -j ACCEPT
  netfilter-persistent save
fi

export OLLAMA_HOST="${BRIDGE_IP}:11434"
for _ in $(seq 1 30); do
  ollama list >/dev/null 2>&1 && break
  sleep 1
done
for model in "${MODELS[@]}"; do
  echo "== Tải $model =="
  ollama pull "$model"
done

echo
echo "== Kiểm chứng từ BÊN TRONG một container =="
if docker run --rm --add-host=host.docker.internal:host-gateway curlimages/curl:8.10.1 \
     -sf --max-time 10 http://host.docker.internal:11434/api/tags | grep -q bge-m3; then
  echo "OK: container gọi được Ollama và thấy bge-m3."
else
  echo "LỖI: container KHÔNG gọi được Ollama — kiểm tra 'systemctl status ollama' và tường lửa." >&2
  exit 1
fi
