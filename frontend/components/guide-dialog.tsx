'use client';

import type { ComponentType } from 'react';
import {
  Bell,
  BookOpenText,
  Bookmark,
  CircleParking,
  CloudFog,
  Handshake,
  Headphones,
  Keyboard,
  LocateFixed,
  MapPin,
  Mic,
  Route,
  ScanEye,
  Search,
  Sparkles,
} from 'lucide-react';

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Button } from '@/components/ui/button';
import { Kbd } from '@/components/ui/kbd';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

type Icon = ComponentType<{ className?: string }>;

const QUICK_START: { title: string; body: string }[] = [
  {
    title: 'Cho phép định vị',
    body: 'Bấm "Vị trí của tôi" để trình duyệt xin quyền GPS. Nếu không bật GPS, bạn vẫn tìm được quanh khu vực mặc định hoặc chạm lên bản đồ để chọn một điểm.',
  },
  {
    title: 'Chọn bán kính và danh mục',
    body: 'Chọn bán kính (từ vài trăm mét đến vài km) và bấm một danh mục như Ăn uống, Cà phê, Y tế… để thu hẹp kết quả.',
  },
  {
    title: 'Tìm kiếm',
    body: 'Gõ từ khoá như "cà phê", "phở", "công viên" rồi bấm Tìm — hoặc bấm biểu tượng micro để nói. Kết quả hiện cả trong danh sách lẫn trên bản đồ.',
  },
  {
    title: 'Xem chi tiết và chỉ đường',
    body: 'Bấm vào một địa điểm để xem giờ mở cửa, độ đông, đánh giá, ảnh; sau đó chọn "Chỉ đường" để có lộ trình thật cho xe máy, ô tô hoặc đi bộ.',
  },
];

const TOPICS: {
  value: string;
  title: string;
  Icon: Icon;
  items: string[];
}[] = [
  {
    value: 'search',
    title: 'Tìm kiếm và đọc kết quả',
    Icon: Search,
    items: [
      'Kết quả được xếp hạng bằng nhiều kênh (từ khoá, khoảng cách, ngữ nghĩa) rồi hợp nhất, nên gõ tự nhiên như "quán cà phê yên tĩnh để làm việc" vẫn ra kết quả hợp lý.',
      'Các nhãn dưới ô tìm kiếm cho biết hệ thống đã dùng kênh nào, thời tiết hiện tại và số tín hiệu dùng để xếp hạng.',
      'Bấm một cụm tròn số trên bản đồ để phóng to vào các địa điểm trong cụm đó.',
      'Chú giải trên bản đồ: chấm xanh dương là vị trí của bạn, chấm nhiều màu là địa điểm theo loại, vòng tròn xanh lá là cụm, vùng sáng là vành H3 đang được tìm.',
    ],
  },
  {
    value: 'tools',
    title: 'Tiện ích quanh bạn (gửi xe, xăng, sạc, WC, xe buýt)',
    Icon: CircleParking,
    items: [
      'Dưới ô tìm kiếm có 6 nút nhanh: Gửi xe, Trạm sạc, Trạm xăng, Tiện lợi, Nhà vệ sinh và Xe buýt. Bấm một nút để mở bảng tương ứng, bấm dấu X để quay lại.',
      'Danh sách được xếp theo thời gian di chuyển thật tới nơi (xe hoặc đi bộ), không chỉ theo đường chim bay.',
      'Gửi xe: chọn loại xe, thời gian gửi và nơi bạn muốn tới. Nút "Gửi xe" ở trang chi tiết địa điểm sẽ điền sẵn điểm đến.',
      'Xe buýt: tra tuyến, xem giờ chạy, lộ trình và các trạm dừng gần bạn.',
    ],
  },
  {
    value: 'assistant',
    title: 'Trợ lý trò chuyện',
    Icon: Sparkles,
    items: [
      'Bấm nút tròn có biểu tượng tin nhắn ở góc dưới phải bản đồ (hoặc tab "Trợ lý" trên điện thoại) để hỏi bằng lời tự nhiên, ví dụ "gần đây có quán phở nào đang mở?".',
      'Trợ lý có các gợi ý nhanh: Tour thuyết minh, Săn địa danh, Giọng nói và Hẹn nhóm. Có thể bấm câu trả lời nhanh thay vì gõ.',
      'Nói "đặt nhà ở đây" để lưu vị trí hiện tại làm nhà; về sau trợ lý sẽ gợi ý quán ăn quanh nhà bạn.',
      'Lịch sử trò chuyện được lưu để bạn mở lại.',
    ],
  },
  {
    value: 'tour',
    title: 'Tour thuyết minh và Săn địa danh',
    Icon: Headphones,
    items: [
      'Tour thuyết minh: đi bộ quanh di tích và nghe kể chuyện từng điểm dừng theo thứ tự.',
      'Săn địa danh: khám phá các địa danh quanh bạn; nơi nào đã tới sẽ được đánh dấu ✓, nơi chưa tới đánh dấu ?.',
    ],
  },
  {
    value: 'meetup',
    title: 'Hẹn nhóm',
    Icon: Handshake,
    items: [
      'Thêm vị trí của từng người trong nhóm, chọn loại địa điểm (cà phê, ăn uống, bar/pub) — hệ thống đề xuất quán công bằng về quãng đường cho cả nhóm.',
      'Mỗi người được gắn một chữ cái (A, B, C…) trên bản đồ, các quán đề xuất đánh số 1, 2, 3.',
    ],
  },
  {
    value: 'fog',
    title: 'Bản đồ sương mù',
    Icon: CloudFog,
    items: [
      'Bấm "Sương mù" ở góc trên bản đồ: toàn bộ bản đồ phủ sương, bạn đi tới đâu vùng đó sáng lên.',
      'Chế độ này dùng GPS riêng chỉ để ghi các ô bạn đã đi qua, không gửi dữ liệu theo dõi vị trí.',
      'Có nút xoá dữ liệu vùng đã khám phá nếu muốn bắt đầu lại.',
    ],
  },
  {
    value: 'ar',
    title: 'Khám phá bằng camera (AR)',
    Icon: ScanEye,
    items: [
      'Bấm "AR" ở góc trên bản đồ, cho phép dùng camera và GPS. Địa điểm xung quanh hiện lơ lửng đúng hướng bạn đang xoay điện thoại.',
      'Bấm một huy hiệu để xem địa điểm đó. Nếu không có GPS, màn hình sẽ nói rõ lý do.',
    ],
  },
  {
    value: 'voice',
    title: 'Tìm bằng giọng nói',
    Icon: Mic,
    items: [
      'Biểu tượng micro cạnh ô tìm kiếm: nói thay vì gõ.',
      'Chế độ giọng nói đầy đủ dành cho người khiếm thị: nhấn Alt + V ở bất kỳ đâu trên trang để bật/tắt; tìm kiếm và dẫn đường hoàn toàn bằng lời.',
    ],
  },
  {
    value: 'track',
    title: 'Theo dõi vị trí và nhắc khi tới gần',
    Icon: Bell,
    items: [
      'Bấm "Theo dõi vị trí" để bản đồ tự cập nhật theo bạn khi di chuyển. Bấm lần nữa để dừng.',
      'Có thể đặt vùng nhắc cho một địa điểm: khi bạn tới gần, trình duyệt sẽ gửi thông báo (cần cho phép thông báo).',
    ],
  },
  {
    value: 'account',
    title: 'Tài khoản, địa điểm đã lưu và đánh giá',
    Icon: Bookmark,
    items: [
      'Đăng nhập để giữ địa điểm đã lưu và đánh giá của bạn trên mọi thiết bị.',
      'Bấm "Lưu" ở trang chi tiết để thêm vào mục "Đã lưu" ở thanh bên; bấm "Bỏ lưu" để gỡ.',
      'Bạn có thể chấm điểm và đánh giá địa điểm ngay trong trang chi tiết.',
    ],
  },
  {
    value: 'display',
    title: 'Ngôn ngữ và giao diện',
    Icon: Keyboard,
    items: [
      'Đổi ngôn ngữ giao diện ở ô "Ngôn ngữ / Language" trên thanh trên (trên điện thoại nằm trong menu ⋮).',
      'Biểu tượng mặt trăng/mặt trời chuyển giữa giao diện sáng và tối.',
    ],
  },
];

const PHONE_TIPS = [
  'Thanh tab dưới đáy có 4 mục: Tìm kiếm, Bản đồ, Kết quả và Trợ lý — chuyển qua lại chỉ bằng một tay.',
  'Nút "Vị trí của tôi" nổi ở góc dưới phải bản đồ.',
  'Menu ⋮ trên cùng chứa ngôn ngữ, giao diện sáng/tối và phần giới thiệu đồ án.',
];

export function GuideDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] gap-5 overflow-y-auto p-0 sm:max-w-2xl [&>[data-slot=dialog-close]]:text-white [&>[data-slot=dialog-close]]:hover:bg-white/15">
        <div className="rounded-t-xl bg-gradient-to-br from-emerald-700 to-emerald-500 px-6 pt-6 pb-5 text-white">
          <div className="grid size-12 place-items-center rounded-2xl bg-white/15 ring-1 ring-white/25">
            <BookOpenText className="size-6" />
          </div>
          <DialogHeader className="mt-4 gap-1">
            <DialogTitle className="text-2xl leading-tight font-bold text-white">
              Hướng dẫn sử dụng Nearby
            </DialogTitle>
            <DialogDescription className="text-white/85">
              Bốn bước để tìm được địa điểm đầu tiên, cùng cách dùng từng tính
              năng của trang.
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="grid gap-5 px-6 pb-2">
          <section>
            <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              <LocateFixed className="size-4" />
              Bắt đầu nhanh
            </h3>
            <ol className="grid gap-3">
              {QUICK_START.map((step, index) => (
                <li key={step.title} className="flex gap-3">
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary text-sm font-bold text-primary-foreground">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="font-semibold">{step.title}</p>
                    <p className="text-sm text-muted-foreground">{step.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section>
            <h3 className="mb-1 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              <MapPin className="size-4" />
              Tính năng chi tiết
            </h3>
            <Accordion className="rounded-xl border px-4">
              {TOPICS.map(({ value, title, Icon, items }) => (
                <AccordionItem key={value} value={value}>
                  <AccordionTrigger className="items-center">
                    <span className="flex items-center gap-2.5">
                      <Icon className="size-4 shrink-0 text-primary" />
                      {title}
                    </span>
                  </AccordionTrigger>
                  <AccordionContent>
                    <ul className="grid gap-1.5 pl-6.5 text-muted-foreground">
                      {items.map((item) => (
                        <li key={item} className="list-disc">
                          {item}
                        </li>
                      ))}
                    </ul>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </section>

          <section className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-xl border bg-muted/40 p-4">
              <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                <Keyboard className="size-4" />
                Phím tắt
              </h3>
              <p className="flex items-center gap-2 text-sm">
                <span className="flex items-center gap-1">
                  <Kbd>Alt</Kbd>+<Kbd>V</Kbd>
                </span>
                Bật/tắt chế độ giọng nói
              </p>
            </div>
            <div className="rounded-xl border bg-muted/40 p-4">
              <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                <Route className="size-4" />
                Trên điện thoại
              </h3>
              <ul className="grid gap-1 text-sm text-muted-foreground">
                {PHONE_TIPS.map((tip) => (
                  <li key={tip} className="list-disc ml-4">
                    {tip}
                  </li>
                ))}
              </ul>
            </div>
          </section>
        </div>

        <DialogFooter className="mx-0 mb-0 rounded-b-xl px-6 py-4">
          <Button onClick={() => onOpenChange(false)}>Đã hiểu</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
