import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Nearby — Khám phá địa điểm quanh bạn',
  description:
    'MVP tìm kiếm và xếp hạng địa điểm theo vị trí, khoảng cách và đánh giá.',
  // Cần cho Proximity Notification Service: Service Worker và quyền thông báo
  // chỉ hoạt động trong secure context, và manifest là thứ biến trang thành một
  // ứng dụng cài được thay vì một tab bình thường.
  manifest: '/manifest.json',
  icons: { icon: '/icon-192.png', apple: '/icon-192.png' },
};

// `themeColor` chuyển ra khỏi `metadata` theo API mới — nhét trong `metadata`
// bị đánh dấu deprecated (typescript/no-deprecated trong .oxlintrc.json).
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  interactiveWidget: 'resizes-content',
  themeColor: '#0f8a62',
};

// Chạy đồng bộ trước khi React hydrate: đặt sẵn class '.dark' theo lựa chọn đã
// lưu / theme hệ thống nên không nháy sáng->tối và <html> khớp trạng thái client.
const themeScript = `(function(){try{var t=localStorage.getItem('nearby-theme');if(t!=='dark'&&t!=='light'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}if(t==='dark'){document.documentElement.classList.add('dark');}}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <head>
        {/* Be Vietnam Pro vẽ dấu tiếng Việt cân hơn Inter/Segoe. Mất mạng thì
            --font-app-sans tự lùi về font hệ thống, giao diện không vỡ.
            Luật no-page-custom-font nhắm vào pages/_document của Pages Router;
            đây là root layout của App Router nên font đã áp cho mọi trang. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line next/no-page-custom-font */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap"
        />
      </head>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        {children}
      </body>
    </html>
  );
}
