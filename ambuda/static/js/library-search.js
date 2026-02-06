import { createSearchMatcher } from './sanskrit-search';

/**
 * A lightweight Alpine component that filters [data-title] items
 * across multiple [data-section] groups, hiding empty sections
 * automatically. Supports transliteration-aware matching via
 * createSearchMatcher.
 */
export default () => ({
  query: '',
  matcher: null,

  init() {
    const els = [...this.$el.querySelectorAll('[data-title]')];
    this.matcher = createSearchMatcher(els, (el) => el.dataset.title);
  },

  filter() {
    const items = this.$el.querySelectorAll('[data-title]');
    const sections = this.$el.querySelectorAll('[data-section]');

    if (!this.query) {
      items.forEach((el) => { el.style.display = ''; });
      sections.forEach((el) => { el.style.display = ''; });
      return;
    }

    const matched = new Set(this.matcher.filter(this.query));
    items.forEach((el) => {
      el.style.display = matched.has(el) ? '' : 'none';
    });
    sections.forEach((section) => {
      const hasVisible = [...section.querySelectorAll('[data-title]')]
        .some((el) => el.style.display !== 'none');
      section.style.display = hasVisible ? '' : 'none';
    });
  },
});
