'use client';

import { ArrowLeft, Lock } from 'lucide-react';

import { Button } from '@/components/ui/button';

/** Màn chặn trong khung trợ lý cho tính năng chỉ dành cho tài khoản đã đăng nhập
 * (lịch sử trò chuyện, hẹn nhóm). Khách vãng lai vẫn hỏi đáp bình thường. */
export function LoginRequired({
  title,
  description,
  onBack,
}: {
  title: string;
  description: string;
  onBack: () => void;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <Button type="button" size="icon" variant="ghost" onClick={onBack} aria-label="Quay lại trò chuyện">
          <ArrowLeft className="size-4" />
        </Button>
        <p className="min-w-0 flex-1 text-sm font-semibold">{title}</p>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Lock className="size-5" aria-hidden />
        </span>
        <p className="text-sm font-medium">Cần đăng nhập</p>
        <p className="text-xs text-muted-foreground">{description}</p>
        <p className="text-xs text-muted-foreground">
          Bấm nút <span className="font-medium text-foreground">Đăng nhập</span> ở góc trên màn hình để tiếp tục.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onBack}>
          Quay lại trò chuyện
        </Button>
      </div>
    </div>
  );
}
