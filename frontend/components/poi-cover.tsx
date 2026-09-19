'use client';

import {
  Baby,
  Banknote,
  BatteryCharging,
  Beer,
  BookOpen,
  Building2,
  Bus,
  Cake,
  Church,
  CircleParking,
  Coffee,
  Croissant,
  CreditCard,
  Drama,
  Droplets,
  Dumbbell,
  FerrisWheel,
  Film,
  Flower,
  Flower2,
  Footprints,
  Fuel,
  Gem,
  Glasses,
  GraduationCap,
  Hotel,
  Landmark,
  Library,
  type LucideIcon,
  Mailbox,
  MapPin,
  Palette,
  PawPrint,
  Pill,
  Plane,
  Scissors,
  School,
  Shield,
  Shirt,
  ShoppingBag,
  ShoppingCart,
  Smartphone,
  Smile,
  Sparkles,
  SprayCan,
  Store,
  Stethoscope,
  ToyBrick,
  TrainFront,
  Trees,
  UtensilsCrossed,
  Volleyball,
  Warehouse,
  WashingMachine,
  Wrench,
} from 'lucide-react';

import { cn } from '@/lib/utils';

type CoverStyle = { icon: LucideIcon; surface: string };

// Bảng tra CỨNG theo category, không băm chuỗi, không Math.random: cùng một
// địa điểm phải cho ra đúng một ảnh bìa ở mọi lần render — kể cả render trên
// máy chủ rồi hydrate lại ở trình duyệt, nếu không React sẽ báo lệch DOM.
//
// Mỗi ô có SẴN một màu nền đặc rồi mới chồng gradient lên. Gradient Tailwind
// phụ thuộc biến --tw-gradient-*; nếu vì lý do gì đó lớp đó không sinh ra thì
// thẻ vẫn là một mảng màu tử tế chứ không phải ô trắng trong buổi bảo vệ.
//
// Bảng này phải phủ TOÀN BỘ 54 mã category trong `poi_features.CATEGORY_MAP`
// (tăng từ 32 sau đợt mở rộng bộ lọc OSM: cây xăng, sửa xe, bến xe, ga tàu,
// tín ngưỡng, mầm non, thú cưng, tiệm vàng...), cộng vài bí danh mà giao diện
// hay gọi tên khác ('shopping', 'office'). Thiếu một mã thì POI loại đó rơi về
// DEFAULT_STYLE — vẫn hiển thị được, chỉ là mất dấu hiệu nhận biết bằng mắt.
const COVER_STYLES: Record<string, CoverStyle> = {
  cafe: {
    icon: Coffee,
    surface: 'bg-amber-600 bg-linear-to-br from-amber-500 via-orange-600 to-amber-800',
  },
  restaurant: {
    icon: UtensilsCrossed,
    surface: 'bg-orange-600 bg-linear-to-br from-orange-500 via-red-500 to-rose-700',
  },
  bar: {
    icon: Beer,
    surface: 'bg-violet-600 bg-linear-to-br from-violet-500 via-purple-600 to-indigo-800',
  },
  bakery: {
    icon: Croissant,
    surface: 'bg-yellow-600 bg-linear-to-br from-yellow-400 via-amber-500 to-orange-700',
  },
  park: {
    icon: Trees,
    surface: 'bg-emerald-600 bg-linear-to-br from-emerald-400 via-green-600 to-teal-800',
  },
  playground: {
    icon: ToyBrick,
    surface: 'bg-lime-600 bg-linear-to-br from-lime-400 via-emerald-500 to-green-700',
  },
  museum: {
    icon: Landmark,
    surface: 'bg-stone-600 bg-linear-to-br from-stone-400 via-stone-600 to-neutral-800',
  },
  gallery: {
    icon: Palette,
    surface: 'bg-fuchsia-600 bg-linear-to-br from-fuchsia-400 via-pink-600 to-purple-800',
  },
  landmark: {
    icon: Landmark,
    surface: 'bg-amber-700 bg-linear-to-br from-amber-500 via-yellow-700 to-stone-800',
  },
  theatre: {
    icon: Drama,
    surface: 'bg-rose-600 bg-linear-to-br from-rose-500 via-red-600 to-rose-900',
  },
  cinema: {
    icon: Film,
    surface: 'bg-slate-700 bg-linear-to-br from-slate-600 via-indigo-800 to-slate-900',
  },
  bookstore: {
    icon: BookOpen,
    surface: 'bg-teal-700 bg-linear-to-br from-teal-500 via-cyan-700 to-slate-800',
  },
  library: {
    icon: Library,
    surface: 'bg-cyan-700 bg-linear-to-br from-cyan-500 via-teal-700 to-slate-800',
  },
  shopping: {
    icon: ShoppingBag,
    surface: 'bg-pink-600 bg-linear-to-br from-pink-500 via-rose-600 to-fuchsia-800',
  },
  shopping_mall: {
    icon: ShoppingBag,
    surface: 'bg-pink-600 bg-linear-to-br from-pink-500 via-rose-600 to-fuchsia-800',
  },
  clothes: {
    icon: Shirt,
    surface: 'bg-rose-500 bg-linear-to-br from-rose-400 via-pink-500 to-purple-700',
  },
  supermarket: {
    icon: ShoppingCart,
    surface: 'bg-sky-600 bg-linear-to-br from-sky-500 via-blue-600 to-indigo-800',
  },
  convenience: {
    icon: Store,
    surface: 'bg-blue-600 bg-linear-to-br from-blue-500 via-sky-600 to-cyan-800',
  },
  market: {
    icon: Warehouse,
    surface: 'bg-amber-600 bg-linear-to-br from-amber-500 via-lime-600 to-emerald-800',
  },
  electronics: {
    icon: Smartphone,
    surface: 'bg-zinc-700 bg-linear-to-br from-zinc-500 via-slate-700 to-zinc-900',
  },
  hairdresser: {
    icon: Scissors,
    surface: 'bg-violet-500 bg-linear-to-br from-violet-400 via-purple-500 to-fuchsia-700',
  },
  hotel: {
    icon: Hotel,
    surface: 'bg-indigo-600 bg-linear-to-br from-indigo-500 via-violet-600 to-slate-900',
  },
  school: {
    icon: School,
    surface: 'bg-sky-700 bg-linear-to-br from-sky-500 via-indigo-600 to-blue-900',
  },
  university: {
    icon: GraduationCap,
    surface: 'bg-blue-800 bg-linear-to-br from-blue-600 via-indigo-800 to-slate-900',
  },
  hospital: {
    icon: Stethoscope,
    surface: 'bg-red-600 bg-linear-to-br from-red-400 via-rose-600 to-red-900',
  },
  pharmacy: {
    icon: Pill,
    surface: 'bg-emerald-600 bg-linear-to-br from-emerald-400 via-teal-600 to-cyan-800',
  },
  dentist: {
    icon: Smile,
    surface: 'bg-cyan-600 bg-linear-to-br from-cyan-400 via-sky-600 to-blue-900',
  },
  gym: {
    icon: Dumbbell,
    surface: 'bg-slate-700 bg-linear-to-br from-slate-500 via-zinc-700 to-neutral-900',
  },
  bank: {
    icon: Banknote,
    surface: 'bg-emerald-700 bg-linear-to-br from-emerald-500 via-green-700 to-slate-900',
  },
  atm: {
    icon: CreditCard,
    surface: 'bg-teal-700 bg-linear-to-br from-teal-500 via-emerald-700 to-slate-900',
  },
  fuel: {
    icon: Fuel,
    surface: 'bg-orange-700 bg-linear-to-br from-orange-500 via-amber-700 to-stone-900',
  },
  office: {
    icon: Building2,
    surface: 'bg-slate-600 bg-linear-to-br from-slate-500 via-slate-700 to-slate-900',
  },
  airport: {
    icon: Plane,
    surface: 'bg-sky-800 bg-linear-to-br from-sky-600 via-blue-800 to-slate-950',
  },
  spa: {
    icon: Flower2,
    surface: 'bg-rose-500 bg-linear-to-br from-rose-300 via-pink-500 to-fuchsia-700',
  },
  event_venue: {
    icon: Cake,
    surface: 'bg-fuchsia-700 bg-linear-to-br from-fuchsia-500 via-purple-700 to-indigo-900',
  },
  charging_station: {
    icon: BatteryCharging,
    surface: 'bg-lime-700 bg-linear-to-br from-lime-500 via-emerald-700 to-teal-900',
  },
  car_repair: {
    icon: Wrench,
    surface: 'bg-zinc-700 bg-linear-to-br from-zinc-500 via-stone-700 to-neutral-900',
  },
  car_wash: {
    icon: SprayCan,
    surface: 'bg-sky-600 bg-linear-to-br from-sky-400 via-cyan-600 to-blue-800',
  },
  parking: {
    icon: CircleParking,
    surface: 'bg-slate-600 bg-linear-to-br from-slate-400 via-blue-600 to-slate-900',
  },
  bus_station: {
    icon: Bus,
    surface: 'bg-amber-700 bg-linear-to-br from-amber-500 via-orange-700 to-stone-900',
  },
  train_station: {
    icon: TrainFront,
    surface: 'bg-indigo-700 bg-linear-to-br from-indigo-500 via-blue-700 to-slate-950',
  },
  place_of_worship: {
    icon: Church,
    surface: 'bg-yellow-700 bg-linear-to-br from-yellow-600 via-amber-700 to-stone-900',
  },
  post_office: {
    icon: Mailbox,
    surface: 'bg-orange-600 bg-linear-to-br from-orange-400 via-amber-600 to-red-800',
  },
  police: {
    icon: Shield,
    surface: 'bg-blue-800 bg-linear-to-br from-blue-600 via-indigo-800 to-slate-950',
  },
  government: {
    icon: Building2,
    surface: 'bg-slate-600 bg-linear-to-br from-slate-500 via-slate-700 to-slate-900',
  },
  kindergarten: {
    icon: Baby,
    surface: 'bg-pink-500 bg-linear-to-br from-pink-400 via-rose-500 to-orange-600',
  },
  pet: {
    icon: PawPrint,
    surface: 'bg-amber-600 bg-linear-to-br from-amber-400 via-orange-600 to-amber-900',
  },
  theme_park: {
    icon: FerrisWheel,
    surface: 'bg-fuchsia-600 bg-linear-to-br from-fuchsia-400 via-violet-600 to-indigo-800',
  },
  swimming_pool: {
    icon: Droplets,
    surface: 'bg-cyan-600 bg-linear-to-br from-cyan-400 via-sky-600 to-blue-900',
  },
  sports_field: {
    icon: Volleyball,
    surface: 'bg-green-700 bg-linear-to-br from-green-500 via-emerald-700 to-teal-900',
  },
  shoes: {
    icon: Footprints,
    surface: 'bg-stone-600 bg-linear-to-br from-stone-500 via-amber-700 to-stone-900',
  },
  jewelry: {
    icon: Gem,
    surface: 'bg-yellow-600 bg-linear-to-br from-yellow-400 via-amber-600 to-orange-800',
  },
  optician: {
    icon: Glasses,
    surface: 'bg-teal-600 bg-linear-to-br from-teal-400 via-cyan-600 to-slate-800',
  },
  florist: {
    icon: Flower,
    surface: 'bg-rose-500 bg-linear-to-br from-rose-400 via-pink-500 to-red-700',
  },
  laundry: {
    icon: WashingMachine,
    surface: 'bg-sky-700 bg-linear-to-br from-sky-500 via-blue-700 to-indigo-900',
  },
  beauty: {
    icon: Sparkles,
    surface: 'bg-purple-600 bg-linear-to-br from-purple-400 via-fuchsia-600 to-pink-800',
  },
};

const DEFAULT_STYLE: CoverStyle = {
  icon: MapPin,
  surface: 'bg-emerald-700 bg-linear-to-br from-emerald-600 via-teal-700 to-slate-900',
};

function initialOf(name: string): string {
  // Array.from chứ không phải name[0]: tên tiếng Việt có dấu tổ hợp, cắt theo
  // mã đơn vị UTF-16 có thể lấy ra nửa ký tự và hiện thành ô vuông.
  const first = Array.from(name.trim())[0];
  return first ? first.toLocaleUpperCase('vi-VN') : '?';
}

export function PoiCover({
  name,
  category,
  className,
}: {
  name: string;
  category: string;
  className?: string;
}) {
  const style = COVER_STYLES[category] ?? DEFAULT_STYLE;
  const Icon = style.icon;

  return (
    <div
      role="img"
      aria-label={`Ảnh bìa sinh sẵn cho ${name}`}
      className={cn(
        'relative isolate flex size-full items-center justify-center overflow-hidden',
        style.surface,
        className,
      )}
    >
      <div className="pointer-events-none absolute -right-12 -top-14 size-44 rounded-full bg-white/10" />
      <div className="pointer-events-none absolute -bottom-20 -left-10 size-56 rounded-full bg-white/[0.07]" />
      <Icon
        aria-hidden
        strokeWidth={1.1}
        className="pointer-events-none absolute -bottom-5 -right-4 size-36 text-white/15"
      />
      <span className="relative grid size-16 place-items-center rounded-2xl bg-white/20 text-3xl font-bold text-white ring-1 ring-white/30 backdrop-blur-sm">
        {initialOf(name)}
      </span>
    </div>
  );
}
