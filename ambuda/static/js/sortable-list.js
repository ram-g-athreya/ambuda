import { createSearchMatcher } from './sanskrit-search';

function sortAscending(field) {
  return (a, b) => (a.dataset[field] < b.dataset[field] ? -1 : 1);
}

function sortDescending(field) {
  return (a, b) => (a.dataset[field] < b.dataset[field] ? 1 : -1);
}

/**
 * A simple sortable table.
 *
 * FIXME: this class is a kludge of data in markup (through data- attributes)
 * and data in JS (through `this.data`). If we need to add more features here,
 * clean it up properly first.
 */
export default (defaultField) => ({
  // The sort field. Initialize this in `x-data`.
  field: defaultField,
  // The query to filter by. If empty, use all data.
  query: '',
  // The order of the sort ("asc" or "desc").
  order: 'asc',
  // The keys to display.
  displayed: new Set(),
  // A simplified representation of the project data.
  data: [],

  init() {
    const { list } = this.$refs;
    this.data = [...list.children].map((x) => ({
      key: x.dataset.key,
      title: x.dataset.title,
    }));
    this.matcher = createSearchMatcher(this.data, (x) => x.title);
    this.displayed = new Set(this.data.map((x) => x.key));
  },

  /** Filter the list by the user's query string. */
  filter() {
    if (!this.query) {
      this.displayed = new Set(this.data.map((x) => x.key));
      return;
    }
    const matches = this.matcher.filter(this.query);
    this.displayed = new Set(matches.map((x) => x.key));
  },

  /** Sort the filtered list by field `this.field` in order `this.order`. */
  sort() {
    const orderFn = this.order === 'asc' ? sortAscending : sortDescending;
    const { list } = this.$refs;
    [...list.children]
      .sort(orderFn(this.field))
      .forEach((node) => list.appendChild(node));
  },
});
