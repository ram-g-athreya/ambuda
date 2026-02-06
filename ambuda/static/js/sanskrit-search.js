/* global Sanscript */

/**
 * Convert a string from Devanagari to Harvard-Kyoto transliteration.
 * Returns the original string if Sanscript is not available.
 */
export function toHK(str) {
  if (!str || typeof Sanscript === 'undefined') return str;
  return Sanscript.t(str, 'devanagari', 'hk');
}

/**
 * A text matcher for Sanskrit text.
 */
export function createSearchMatcher(items, getText) {
  const entries = items.map((item) => {
    const original = getText(item);
    const text = original.toLowerCase();
    const hk = toHK(original).toLowerCase();
    return { item, text, hk };
  });

  return {
    filter(query) {
      if (!query) return items;
      const q = query.toLowerCase();
      return entries
        .filter((e) => e.text.includes(q) || e.hk.includes(q))
        .map((e) => e.item);
    },
  };
}
