'use client';

import { useCallback, useEffect, useState } from 'react';

export type UiLanguage = { code: string; name: string; nativeName: string };

const STORAGE_KEY = 'nearby-language';
const SOURCE_LANGUAGE = 'vi';
const FALLBACK_LANGUAGES: UiLanguage[] = [
  { code: 'vi', name: 'Vietnamese', nativeName: 'Tiếng Việt' },
];
const MAX_TEXT_LENGTH = 2000;
const ATTRIBUTES = ['placeholder', 'title', 'aria-label', 'alt'] as const;
const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA', 'CODE', 'PRE']);
const HAS_LETTER = /\p{L}/u;

type Slot = { source: string; applied: string | null };

function readStoredLanguage(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeLanguage(code: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Không lưu được (chế độ riêng tư...) — chỉ mất lựa chọn ở lần mở sau.
  }
}

function isExcluded(element: Element | null): boolean {
  if (!element) return true;
  if (SKIP_TAGS.has(element.tagName)) return true;
  return element.closest('[translate="no"], [contenteditable="true"]') !== null;
}

/**
 * Dịch TOÀN BỘ chữ đang hiện trên trang (text node + placeholder/title/
 * aria-label/alt) sang một ngôn ngữ khác bằng bản dịch đã có sẵn trong cache
 * backend. Hook này chỉ đọc cache, không tự gọi backend để tạo thêm bản dịch.
 *
 * Chỉ đổi `nodeValue`/thuộc tính của node sẵn có, KHÔNG thay node (kiểu
 * Google Translate chèn <font>) — React vẫn giữ đúng node của nó; lần render
 * sau React ghi đè chữ tiếng Việt mới, MutationObserver bắt được và dịch lại
 * (từ cache, gần như tức thì).
 *
 * Phần tử có `translate="no"` bị bỏ qua — dùng cho chữ đã ở đúng ngôn ngữ
 * (đoạn thuyết minh) hoặc tên ngôn ngữ trong ô chọn.
 */
class DomTranslator {
  private readonly texts = new Map<Text, Slot>();
  private readonly attrs = new Map<Element, Map<string, Slot>>();
  private readonly dict = new Map<string, string>();
  private readonly failed = new Set<string>();
  private readonly dirty = new Set<Node>();
  private observer: MutationObserver | null = null;
  private flushTimer: number | null = null;
  private stopped = false;

  constructor(
    private readonly apiBaseUrl: string,
    private readonly language: string,
    private readonly onProgress: (progress: { done: number; total: number } | null) => void,
  ) {}

  async start() {
    try {
      const response = await fetch(
        `${this.apiBaseUrl}/api/v1/translations/${encodeURIComponent(this.language)}`,
      );
      if (response.ok) {
        const data = (await response.json()) as { translations: Record<string, string> };
        for (const [source, translated] of Object.entries(data.translations)) {
          this.dict.set(source, translated);
        }
      }
    } catch {
      // Không lấy được cache — giữ nguyên tiếng Việt, không tự sinh bản dịch.
    }
    if (this.stopped) return;
    this.scan(document.body);
    this.observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'childList') {
          mutation.addedNodes.forEach((node) => this.dirty.add(node));
        } else {
          this.dirty.add(mutation.target);
        }
      }
      if (this.flushTimer === null) {
        this.flushTimer = window.setTimeout(() => {
          this.flushTimer = null;
          const nodes = [...this.dirty];
          this.dirty.clear();
          for (const node of nodes) if (node.isConnected) this.scan(node);
        }, 150);
      }
    });
    this.observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: [...ATTRIBUTES],
    });
  }

  /** Trả lại nguyên văn tiếng Việt cho mọi chỗ đã dịch. */
  stop() {
    this.stopped = true;
    this.observer?.disconnect();
    if (this.flushTimer !== null) window.clearTimeout(this.flushTimer);
    for (const [node, slot] of this.texts) {
      if (slot.applied !== null && node.nodeValue === slot.applied) node.nodeValue = slot.source;
    }
    for (const [element, slots] of this.attrs) {
      for (const [name, slot] of slots) {
        if (slot.applied !== null && element.getAttribute(name) === slot.applied) {
          element.setAttribute(name, slot.source);
        }
      }
    }
    this.onProgress(null);
  }

  private scan(root: Node) {
    if (root.nodeType === Node.TEXT_NODE) {
      this.visitText(root as Text);
      return;
    }
    if (!(root instanceof Element)) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      this.visitText(node as Text);
    }
    const selector = ATTRIBUTES.map((name) => `[${name}]`).join(',');
    const elements = [...(root.matches(selector) ? [root] : []), ...root.querySelectorAll(selector)];
    for (const element of elements) {
      for (const name of ATTRIBUTES) this.visitAttribute(element, name);
    }
  }

  private visitText(node: Text) {
    const value = node.nodeValue ?? '';
    const slot = this.texts.get(node);
    if (slot && slot.applied !== null && value === slot.applied) return; // chữ do mình ghi
    if (!HAS_LETTER.test(value) || isExcluded(node.parentElement)) return;
    const next: Slot = { source: value, applied: null };
    this.texts.set(node, next);
    this.translateSlot(next, (text) => {
      node.nodeValue = text;
    });
  }

  private visitAttribute(element: Element, name: string) {
    const value = element.getAttribute(name);
    if (!value || !HAS_LETTER.test(value) || isExcluded(element)) return;
    let slots = this.attrs.get(element);
    const slot = slots?.get(name);
    if (slot && slot.applied !== null && value === slot.applied) return;
    if (!slots) {
      slots = new Map();
      this.attrs.set(element, slots);
    }
    const next: Slot = { source: value, applied: null };
    slots.set(name, next);
    this.translateSlot(next, (text) => element.setAttribute(name, text));
  }

  /** Áp bản dịch nếu đã có, không thì giữ nguyên tiếng Việt. Giữ nguyên khoảng
   * trắng đầu/cuối của chuỗi gốc — React hay tách " kết quả" thành node riêng. */
  private translateSlot(slot: Slot, write: (text: string) => void) {
    const key = slot.source.trim();
    if (key.length > MAX_TEXT_LENGTH) return;
    const translated = this.dict.get(key);
    if (translated !== undefined) {
      const text = slot.source.replace(key, translated);
      slot.applied = text;
      write(text);
    } else if (!this.failed.has(key)) {
      this.failed.add(key);
    }
  }

}

/**
 * Ngôn ngữ giao diện (tiếng Việt + các cache dịch đã có sẵn ở backend)
 * — lưu lựa chọn trong localStorage, dịch trang bằng `DomTranslator`.
 */
export function useAutoTranslate(apiBaseUrl: string) {
  const [languages, setLanguages] = useState<UiLanguage[]>(FALLBACK_LANGUAGES);
  const [language, setLanguageState] = useState(SOURCE_LANGUAGE);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);

  useEffect(() => {
    // localStorage chỉ có ở trình duyệt — đọc sau mount (cùng mẫu use-theme).
    const stored = readStoredLanguage();
    // oxlint-disable-next-line react/react-compiler
    if (stored) setLanguageState(stored);
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/v1/languages?translations_only=1`, { signal: controller.signal })
      .then(
        (response) =>
          (response.ok ? response.json() : null) as Promise<{ languages: UiLanguage[] } | null>,
      )
      .then((data) => {
        if (!data?.languages?.length) return;
        setLanguages(data.languages);
        if (stored && !data.languages.some((item) => item.code === stored)) {
          storeLanguage(SOURCE_LANGUAGE);
          setLanguageState(SOURCE_LANGUAGE);
        }
      })
      .catch(() => {
        // Backend chưa chạy — chỉ còn tiếng Việt, giao diện vẫn dùng được.
        if (stored && stored !== SOURCE_LANGUAGE) setLanguageState(SOURCE_LANGUAGE);
      });
    return () => controller.abort();
  }, [apiBaseUrl]);

  useEffect(() => {
    document.documentElement.lang = language;
    if (language === SOURCE_LANGUAGE) return;
    const translator = new DomTranslator(apiBaseUrl, language, setProgress);
    void translator.start();
    return () => translator.stop();
  }, [apiBaseUrl, language]);

  const setLanguage = useCallback((code: string) => {
    storeLanguage(code);
    setLanguageState(code);
  }, []);

  return { languages, language, setLanguage, progress };
}
