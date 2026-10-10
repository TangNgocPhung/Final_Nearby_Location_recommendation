'use client';

import { useState, useSyncExternalStore, type ComponentType } from 'react';
import {
  Bell,
  BookOpenText,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  CircleParking,
  CloudFog,
  Handshake,
  Headphones,
  Keyboard,
  Landmark,
  LocateFixed,
  Mic,
  Route,
  ScanEye,
  Search,
  Sparkles,
} from 'lucide-react';

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

const STORAGE_KEY = 'nearby-guide-seen';

type Icon = ComponentType<{ className?: string }>;

const QUICK_START = [
  'Cho phép định vị',
  'Chọn bán kính và danh mục',
  'Tìm kiếm',
  'Xem chi tiết và chỉ đường',
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
    ],
  },
  {
    value: 'tools',
    title: 'Tiện ích quanh bạn (gửi xe, xăng, sạc, WC, xe buýt)',
    Icon: CircleParking,
    items: [
      'Dưới ô tìm kiếm có 6 nút nhanh: Gửi xe, Trạm sạc, Trạm xăng, Tiện lợi, Nhà vệ sinh và Xe buýt. Bấm một nút để mở bảng tương ứng, bấm dấu X để quay lại.',
    ],
  },
  {
    value: 'assistant',
    title: 'Trợ lý trò chuyện',
    Icon: Sparkles,
    items: [
      'Bấm nút tròn có biểu tượng tin nhắn ở góc dưới phải bản đồ (hoặc tab "Trợ lý" trên điện thoại) để hỏi bằng lời tự nhiên, ví dụ "gần đây có quán phở nào đang mở?".',
    ],
  },
  {
    value: 'tour',
    title: 'Tour thuyết minh',
    Icon: Headphones,
    items: [
      'Tour thuyết minh: đi bộ quanh di tích và nghe kể chuyện từng điểm dừng theo thứ tự.',
    ],
  },
  {
    value: 'landmarks',
    title: 'Địa danh gần bạn',
    Icon: Landmark,
    items: [
      'Thẻ "Địa danh gần bạn" dưới 6 nút tiện ích cho biết 3 địa danh gần nhất mà bạn chưa ghé, kèm khoảng cách. Bấm một dòng để bay tới đó trên bản đồ và xem chi tiết.',
    ],
  },
  {
    value: 'meetup',
    title: 'Hẹn nhóm',
    Icon: Handshake,
    items: [
      'Thêm vị trí của từng người trong nhóm, chọn loại địa điểm (cà phê, ăn uống, bar/pub) — hệ thống đề xuất quán công bằng về quãng đường cho cả nhóm.',
    ],
  },
  {
    value: 'fog',
    title: 'Bản đồ sương mù',
    Icon: CloudFog,
    items: [
      'Bấm "Sương mù" ở góc trên bản đồ: toàn bộ bản đồ phủ sương, bạn đi tới đâu vùng đó sáng lên.',
      'Mở đủ diện tích (0,1 → 100 km²) để đạt mốc; bảng "Theo quận" cho biết đã đi bao nhiêu ở mỗi quận.',
    ],
  },
  {
    value: 'ar',
    title: 'Khám phá bằng camera (AR)',
    Icon: ScanEye,
    items: [
      'Bấm "AR" ở góc trên bản đồ, cho phép dùng camera và GPS. Địa điểm xung quanh hiện lơ lửng đúng hướng bạn đang xoay điện thoại.',
    ],
  },
  {
    value: 'voice',
    title: 'Tìm bằng giọng nói',
    Icon: Mic,
    items: [
      'Biểu tượng micro cạnh ô tìm kiếm: nói thay vì gõ.',
    ],
  },
  {
    value: 'track',
    title: 'Theo dõi vị trí và nhắc khi tới gần',
    Icon: Bell,
    items: [
      'Bấm "Theo dõi vị trí" để bản đồ tự cập nhật theo bạn khi di chuyển. Bấm lần nữa để dừng.',
    ],
  },
  {
    value: 'account',
    title: 'Tài khoản, địa điểm đã lưu và đánh giá',
    Icon: Bookmark,
    items: [
      'Đăng nhập để giữ địa điểm đã lưu và đánh giá của bạn trên mọi thiết bị.',
    ],
  },
  {
    value: 'display',
    title: 'Ngôn ngữ và giao diện',
    Icon: Keyboard,
    items: [
      'Đổi ngôn ngữ giao diện ở ô "Ngôn ngữ / Language" trên thanh trên (trên điện thoại nằm trong menu ⋮).',
    ],
  },
];

const PHONE_TIPS = [
  'Thanh tab dưới đáy có 4 mục: Tìm kiếm, Bản đồ, Kết quả và Trợ lý — chuyển qua lại chỉ bằng một tay.',
  'Nút "Vị trí của tôi" nổi ở góc dưới phải bản đồ.',
  'Menu ⋮ trên cùng chứa ngôn ngữ, giao diện sáng/tối và phần giới thiệu đồ án.',
];

type Chapter = { key: string; title: string; Icon: Icon };

const CHAPTERS: Chapter[] = [
  { key: 'quick', title: 'Bắt đầu nhanh', Icon: LocateFixed },
  ...TOPICS.map(({ value, title, Icon }) => ({ key: value, title, Icon })),
  { key: 'tips', title: 'Phím tắt và mẹo cho điện thoại', Icon: Keyboard },
];

function ChapterBody({ chapterKey }: { chapterKey: string }) {
  if (chapterKey === 'quick') {
    return (
      <ol className="grid gap-3">
        {QUICK_START.map((title, index) => (
          <li key={title} className="flex items-center gap-3">
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary text-sm font-bold text-primary-foreground">
              {index + 1}
            </span>
            <p className="min-w-0 font-semibold">{title}</p>
          </li>
        ))}
      </ol>
    );
  }

  if (chapterKey === 'tips') {
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border bg-muted/40 p-4">
          <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            <Keyboard className="size-4" />
            Phím tắt
          </h4>
          <p className="flex items-center gap-2 text-sm">
            <span className="flex items-center gap-1">
              <Kbd>Alt</Kbd>+<Kbd>V</Kbd>
            </span>
            Bật/tắt chế độ giọng nói
          </p>
        </div>
        <div className="rounded-xl border bg-muted/40 p-4">
          <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            <Route className="size-4" />
            Trên điện thoại
          </h4>
          <ul className="grid gap-1 text-sm text-muted-foreground">
            {PHONE_TIPS.map((tip) => (
              <li key={tip} className="ml-4 list-disc">
                {tip}
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  const topic = TOPICS.find((t) => t.value === chapterKey);
  if (!topic) return null;
  return (
    <ul className="grid gap-2 pl-5 text-muted-foreground">
      {topic.items.map((item) => (
        <li key={item} className="list-disc">
          {item}
        </li>
      ))}
    </ul>
  );
}

// Nằm trong DialogContent nên unmount khi đóng: mỗi lần mở lại đều bắt đầu từ chương 1.
function GuideChapters({ onDone }: { onDone: () => void }) {
  const [index, setIndex] = useState(0);
  const chapter = CHAPTERS[index];
  const total = CHAPTERS.length;
  const isFirst = index === 0;
  const isLast = index === total - 1;

  return (
    <>
      <div className="grid gap-4 px-6">
        <div className="grid gap-2">
          <div className="flex items-center justify-between text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            <span>
              Chương {index + 1}/{total}
            </span>
          </div>
          <div
            aria-hidden
            className="h-1.5 overflow-hidden rounded-full bg-muted"
          >
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-300"
              style={{ width: `${((index + 1) / total) * 100}%` }}
            />
          </div>
        </div>

        <section className="min-h-56" aria-live="polite">
          <h3 className="mb-3 flex items-center gap-2.5 text-lg font-semibold">
            <chapter.Icon className="size-5 shrink-0 text-primary" />
            {chapter.title}
          </h3>
          <ChapterBody chapterKey={chapter.key} />
        </section>
      </div>

      <DialogFooter className="sticky bottom-0 z-10 mx-0 mb-0 items-center rounded-b-xl px-6 py-4 sm:justify-between">
        <div className="hidden flex-wrap gap-1.5 sm:flex">
          {CHAPTERS.map((c, i) => (
            <button
              key={c.key}
              type="button"
              aria-label={`Chương ${i + 1}: ${c.title}`}
              aria-current={i === index ? 'step' : undefined}
              onClick={() => setIndex(i)}
              className={`size-2 rounded-full transition-colors ${
                i === index
                  ? 'bg-primary'
                  : 'bg-muted-foreground/30 hover:bg-muted-foreground/60'
              }`}
            />
          ))}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={isFirst}
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
          >
            <ChevronLeft className="size-4" />
            Trước
          </Button>
          {isLast ? (
            <Button onClick={onDone}>Đã hiểu</Button>
          ) : (
            <Button onClick={() => setIndex((i) => Math.min(total - 1, i + 1))}>
              Tiếp
              <ChevronRight className="size-4" />
            </Button>
          )}
        </div>
      </DialogFooter>
    </>
  );
}

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
              năng của trang — xem lần lượt từng chương.
            </DialogDescription>
          </DialogHeader>
        </div>

        <GuideChapters onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function readSeen() {
  try {
    return localStorage.getItem(STORAGE_KEY) !== null;
  } catch {
    // Chế độ ẩn danh / bị chặn storage: coi như đã xem, không tự mở.
    return true;
  }
}

const noopSubscribe = () => () => {};

// Tự mở ở lần truy cập đầu, nhưng chờ hộp "Giới thiệu" (cũng tự mở lần đầu) đóng
// xong để hai hộp không chồng lên nhau. Snapshot phía server là "đã xem" để HTML
// server render khớp với lần hydrate đầu.
export function useGuideDialog(aboutOpen: boolean) {
  const seen = useSyncExternalStore(noopSubscribe, readSeen, () => true);
  const [dismissed, setDismissed] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);

  const open = manualOpen || (!seen && !dismissed && !aboutOpen);

  const onOpenChange = (next: boolean) => {
    setManualOpen(next);
    if (!next) {
      setDismissed(true);
      try {
        localStorage.setItem(STORAGE_KEY, '1');
      } catch {
        // Không lưu được thì lần sau hộp lại tự mở, không sao.
      }
    }
  };

  return { open, setOpen: setManualOpen, onOpenChange };
}
