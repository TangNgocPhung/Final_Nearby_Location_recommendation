'use client';

import { useState } from 'react';
import { Clapperboard, ExternalLink, LoaderCircle, Plus, Search, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ApiError, apiRequest, useAuth } from '@/lib/auth';
import { cn } from '@/lib/utils';

export type PoiVideo = {
  id: string;
  youtubeId: string;
  title: string | null;
  startSeconds: number;
};

/** Nút play kiểu YouTube vẽ tay — lucide không còn icon thương hiệu. */
function PlayBadge() {
  return (
    <svg viewBox="0 0 68 48" className="h-11 w-16 drop-shadow-lg" aria-hidden>
      <path
        d="M66.5 7.7A8.5 8.5 0 0 0 60.5 1.6C55.2.2 34 .2 34 .2S12.8.2 7.5 1.6a8.5 8.5 0 0 0-6 6.1C.1 13 .1 24 .1 24s0 11 1.4 16.3a8.5 8.5 0 0 0 6 6.1C12.8 47.8 34 47.8 34 47.8s21.2 0 26.5-1.4a8.5 8.5 0 0 0 6-6.1C67.9 35 67.9 24 67.9 24s0-11-1.4-16.3Z"
        fill="#FF0033"
      />
      <path d="M45 24 27 14v20z" fill="#fff" />
    </svg>
  );
}

function watchUrl(video: PoiVideo): string {
  const start = video.startSeconds > 0 ? `&t=${video.startSeconds}s` : '';
  return `https://www.youtube.com/watch?v=${video.youtubeId}${start}`;
}

/**
 * Bấm vào ảnh thumbnail mới tải iframe: một iframe YouTube kéo về cả MB
 * JavaScript, gắn sẵn cho mọi video thì mở trang chi tiết nào cũng chậm hẳn dù
 * phần lớn người dùng không xem. Dùng youtube-nocookie để không đặt cookie theo
 * dõi trước khi người dùng thực sự bấm phát.
 */
function VideoCard({
  video,
  wide,
  canDelete,
  deleting,
  onDelete,
}: {
  video: PoiVideo;
  wide: boolean;
  canDelete: boolean;
  deleting: boolean;
  onDelete: () => void;
}) {
  const [playing, setPlaying] = useState(false);
  const title = video.title || 'Video YouTube';
  const params = new URLSearchParams({ autoplay: '1', rel: '0', playsinline: '1' });
  if (video.startSeconds > 0) params.set('start', String(video.startSeconds));

  return (
    <figure className={cn('shrink-0 snap-start', wide ? 'w-full' : 'w-[82%]')}>
      <div className="relative aspect-video overflow-hidden rounded-xl bg-black shadow-sm">
        {playing ? (
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${video.youtubeId}?${params}`}
            title={title}
            className="absolute inset-0 size-full"
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <button
            type="button"
            onClick={() => setPlaying(true)}
            className="group absolute inset-0 grid place-items-center"
            aria-label={`Phát video: ${title}`}
          >
            <img
              src={`https://i.ytimg.com/vi/${video.youtubeId}/hqdefault.jpg`}
              alt=""
              loading="lazy"
              className="absolute inset-0 size-full object-cover transition duration-300 group-hover:scale-105"
            />
            <span className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />
            <span className="relative transition group-hover:scale-110">
              <PlayBadge />
            </span>
          </button>
        )}
        {canDelete && (
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className="absolute top-2 right-2 grid size-7 place-items-center rounded-full bg-black/60 text-white hover:bg-red-600 disabled:opacity-60"
            aria-label={`Gỡ video ${title}`}
            title="Gỡ video khỏi địa điểm (admin)"
          >
            {deleting ? <LoaderCircle className="size-4 animate-spin" /> : <X className="size-4" />}
          </button>
        )}
      </div>
      <figcaption className="mt-1.5 flex items-start gap-2 text-sm">
        <span className="line-clamp-2 min-w-0 flex-1 font-medium">{title}</span>
        <a
          href={watchUrl(video)}
          target="_blank"
          rel="noreferrer"
          className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
          aria-label="Mở trên YouTube"
          title="Mở trên YouTube"
        >
          <ExternalLink className="size-4" />
        </a>
      </figcaption>
    </figure>
  );
}

/**
 * Video YouTube của địa điểm — do admin chọn và dán link (backend/app/poi_videos.py),
 * KHÔNG tự tìm: video tự tìm theo tên hay lạc sang quán bên cạnh.
 *
 * Chưa có video thì chỉ hiện một dòng "Tìm trên YouTube" nhỏ, không chừa khung
 * trống. Danh sách giữ ở state cục bộ để admin thêm/gỡ thấy ngay, không phải tải
 * lại cả trang chi tiết; component được mount lại theo từng POI (`key`).
 */
export function PoiVideos({
  apiBaseUrl,
  poiId,
  poiName,
  city,
  initialVideos,
}: {
  apiBaseUrl: string;
  poiId: string;
  poiName: string;
  city: string;
  initialVideos: PoiVideo[];
}) {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [videos, setVideos] = useState(initialVideos);
  const [formOpen, setFormOpen] = useState(false);
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [message, setMessage] = useState('');

  const searchUrl = `https://www.youtube.com/results?search_query=${encodeURIComponent(
    [poiName, city].filter(Boolean).join(' '),
  )}`;

  async function handleAdd(event: { preventDefault(): void }) {
    event.preventDefault();
    if (!url.trim() || saving) return;
    setSaving(true);
    setMessage('');
    try {
      const { video } = await apiRequest<{ video: PoiVideo }>(
        apiBaseUrl,
        `/api/v1/admin/pois/${poiId}/videos`,
        { method: 'POST', body: JSON.stringify({ url: url.trim(), title: title.trim() || null }) },
      );
      setVideos((current) => [...current, video]);
      setUrl('');
      setTitle('');
      setFormOpen(false);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : 'Không lưu được video');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(video: PoiVideo) {
    if (!window.confirm(`Gỡ video "${video.title || video.youtubeId}" khỏi địa điểm này?`)) return;
    setDeletingId(video.id);
    setMessage('');
    try {
      await apiRequest(apiBaseUrl, `/api/v1/admin/videos/${video.id}`, { method: 'DELETE' });
      setVideos((current) => current.filter((item) => item.id !== video.id));
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : 'Không gỡ được video');
    } finally {
      setDeletingId(null);
    }
  }

  const searchLink = (
    <a
      href={searchUrl}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground hover:underline"
    >
      <Search className="size-3.5" aria-hidden />
      Tìm video về địa điểm này trên YouTube
    </a>
  );

  return (
    <section className="px-4 py-4">
      <div className="flex items-center gap-2">
        <h3 className="flex flex-1 items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          <Clapperboard className="size-4" />
          VIDEO
          {videos.length > 1 && (
            <span className="rounded-full bg-muted px-1.5 text-xs font-medium">{videos.length}</span>
          )}
        </h3>
        {isAdmin && !formOpen && (
          <Button type="button" variant="ghost" size="sm" onClick={() => setFormOpen(true)}>
            <Plus className="size-4" />
            Thêm video
          </Button>
        )}
      </div>

      {videos.length > 0 ? (
        <div
          className={cn(
            'mt-2 flex gap-3',
            videos.length > 1 && '-mx-4 snap-x snap-mandatory overflow-x-auto px-4 pb-1',
          )}
        >
          {videos.map((video) => (
            <VideoCard
              key={video.id}
              video={video}
              wide={videos.length === 1}
              canDelete={isAdmin}
              deleting={deletingId === video.id}
              onDelete={() => handleDelete(video)}
            />
          ))}
        </div>
      ) : (
        <div className="mt-1.5">{searchLink}</div>
      )}

      {isAdmin && formOpen && (
        <form
          onSubmit={handleAdd}
          className="mt-3 space-y-2 rounded-xl border border-dashed p-3"
        >
          <p className="text-xs text-muted-foreground">
            Dán link YouTube của <b>một</b> video nói về đúng địa điểm này. Link có mốc
            thời gian (<code>?t=90</code>) sẽ phát từ mốc đó. Bỏ trống tiêu đề thì lấy
            tiêu đề gốc của video.
          </p>
          <input
            // type="text" chứ không "url": admin hay dán "youtu.be/…" thiếu
            // https:// hoặc id trần — backend nhận được, trình duyệt thì chặn.
            type="text"
            inputMode="url"
            required
            maxLength={300}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://www.youtube.com/watch?v=… hoặc https://youtu.be/…"
            className="h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Link YouTube"
          />
          <input
            type="text"
            maxLength={160}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Tiêu đề (tuỳ chọn)"
            className="h-9 w-full rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Tiêu đề video"
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setFormOpen(false);
                setMessage('');
              }}
            >
              Huỷ
            </Button>
            <Button type="submit" size="sm" disabled={saving || !url.trim()}>
              {saving && <LoaderCircle className="size-4 animate-spin" />}
              Gắn video
            </Button>
          </div>
        </form>
      )}

      {message && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {message}
        </p>
      )}

      {videos.length > 0 && isAdmin && <div className="mt-2">{searchLink}</div>}
    </section>
  );
}
