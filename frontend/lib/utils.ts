import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Dấu phẩy thập phân kiểu Việt Nam — cùng định dạng với câu trả lời của chat
// (`_format_distance` ở backend/app/chat.py).
export function formatMeters(meters: number | null | undefined): string {
  if (meters == null) return '';
  if (Math.round(meters) < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(1).replace('.', ',')} km`;
}
