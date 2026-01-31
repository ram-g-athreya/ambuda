/* global Sanscript */

import routes from './routes.js';

function toHK(str) {
  // for unit tests
  if (!str || typeof Sanscript === 'undefined') return str;

  return Sanscript.t(str, 'devanagari', 'hk');
}

function createPicker(field, component, {
  getItems, displayValue, match, onSelect,
}) {
  const k = (suffix) => `_${field}_${suffix}`;

  return {
    displayValue(entry) {
      return entry[k('query')] !== undefined ? entry[k('query')] : displayValue(component, entry);
    },
    open(entry) {
      entry[k('open')] = true;
      entry[k('query')] = '';
      entry[k('sel')] = 0;
    },
    close(entry) {
      entry[k('open')] = false;
      entry[k('query')] = undefined;
    },
    search(entry, value) {
      entry[k('query')] = value;
      entry[k('sel')] = 0;
    },
    keydown(entry, e) {
      const items = this.filtered(entry);
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        entry[k('sel')] = Math.min((entry[k('sel')] || 0) + 1, items.length - 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        entry[k('sel')] = Math.max((entry[k('sel')] || 0) - 1, 0);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        this.select(entry, items[entry[k('sel')] || 0]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        this.close(entry);
      }
    },
    filtered(entry) {
      const query = (entry[k('query')] || '').toLowerCase();
      const items = getItems(component);
      if (!query) return items;
      return items.filter((item) => match(item, query));
    },
    select(entry, item) {
      if (!item) return;
      onSelect(entry, item);
      this.close(entry);
    },
  };
}

export default () => ({
  config: { publish: [], pages: [] },
  showJSON: false,
  filterHelpOpen: false,
  fields: [],
  languageLabels: window.LANGUAGE_LABELS || {},
  authors: window.AUTHOR_NAMES || [],
  newAuthorOpen: false,
  newAuthorName: '',
  genres: window.GENRE_NAMES || [],
  newGenreOpen: false,
  newGenreName: '',
  _allLanguages: null,
  pickers: {},

  init() {
    this.pickers = {
      lang: createPicker('lang', this, {
        getItems: (c) => c._allLanguages ||= Object.entries(c.languageLabels).map(([code, label]) => ({ code, label })),
        displayValue: (c, entry) => c.languageLabels[entry.language] || entry.language,
        match: (opt, query) => opt.label.toLowerCase().includes(query) || opt.code.includes(query),
        onSelect: (entry, opt) => { entry.language = opt.code; },
      }),
      author: createPicker('author', this, {
        getItems: (c) => c.authors,
        displayValue: (c, entry) => entry.author || '',
        match: (name, query) => name.toLowerCase().includes(query),
        onSelect: (entry, name) => { entry.author = name; },
      }),
      genre: createPicker('genre', this, {
        getItems: (c) => c.genres,
        displayValue: (c, entry) => entry.genre || '',
        match: (name, query) => { const lower = name.toLowerCase(); return lower.includes(query) || toHK(name).toLowerCase().startsWith(query); },
        onSelect: (entry, name) => { entry.genre = name; },
      }),
    };
    this.generateFieldsFromSchema();
    this.config = window.PUBLISH_CONFIG;
    this.config.publish.forEach((entry) => {
      this.fields.forEach((f) => { if (!(f.name in entry)) entry[f.name] = this.getDefaultValue(f); });
      entry._expanded = false;
    });
  },

  generateFieldsFromSchema() {
    const schema = window.PUBLISH_CONFIG_SCHEMA || {};
    const properties = schema.properties || {};
    const required = schema.required || [];
    const defs = schema.$defs || {};

    const fieldMetadata = {
      title: { placeholder: 'e.g., Rāmāyaṇa', description: 'Display title for the text' },
      slug: { placeholder: 'e.g., ramayana', description: 'Unique identifier for the text' },
      target: { placeholder: 'e.g., (page 1 10)', description: 'S-expression filter for block selection' },
      author: { placeholder: 'e.g., Vālmīki', description: 'Author of the work' },
      genre: { placeholder: 'Search genres...', description: 'The category this text best belongs to' },
      language: { placeholder: 'Search languages...', description: 'Primary language of the text' },
      parent_slug: { placeholder: 'e.g., ramayana', description: 'Slug of the parent text (for translations/commentaries)' },
    };

    const fieldOrder = ['title', 'slug', 'target', 'author', 'genre', 'language', 'parent_slug'];
    const labels = { target: 'Filter' };

    this.fields = fieldOrder
      .filter((name) => properties[name])
      .map((name) => {
        const prop = properties[name];
        let { type } = prop;
        let enumValues = prop.enum;

        if (prop.$ref) {
          const resolved = defs[prop.$ref.replace('#/$defs/', '')] || {};
          type ||= resolved.type;
          enumValues ||= resolved.enum;
        }
        if (prop.anyOf) {
          const nonNull = prop.anyOf.find((t) => t.type !== 'null');
          if (nonNull) { type = nonNull.type; enumValues = nonNull.enum; }
        }

        const meta = fieldMetadata[name] || {};
        return {
          name,
          label: labels[name] || this.titleCase(name),
          type,
          required: required.includes(name),
          enum: enumValues,
          placeholder: meta.placeholder || '',
          description: prop.description || meta.description || '',
        };
      });
  },

  addAuthor() {
    const name = (this.newAuthorName || '').trim();
    if (!name) return;
    if (!this.authors.includes(name)) {
      this.authors.push(name);
      this.authors.sort();
    }
    this.newAuthorName = '';
    this.newAuthorOpen = false;
  },

  addGenre() {
    const name = (this.newGenreName || '').trim();
    if (!name) return;
    if (!this.genres.includes(name)) {
      this.genres.push(name);
      this.genres.sort();
    }
    this.newGenreName = '';
    this.newGenreOpen = false;
  },

  // -- Utilities --

  titleCase(str) {
    return str.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
  },

  getDefaultValue(field) {
    if (field.type === 'boolean') return false;
    if (field.type === 'number' || field.type === 'integer') return null;
    return '';
  },

  getConfigLabel(entry) {
    if (entry.title && entry.slug) return `${entry.title} (${entry.slug})`;
    return entry.title || entry.slug || 'New config';
  },

  isEntryEmpty(entry) {
    return this.fields.every((f) => {
      const v = entry[f.name];
      return v === '' || v === null || v === undefined || v === false;
    });
  },

  addPublishEntry() {
    const newEntry = { _expanded: true };
    this.fields.forEach((f) => { newEntry[f.name] = this.getDefaultValue(f); });
    this.config.publish.push(newEntry);
  },

  removePublishEntry(index) {
    const entry = this.config.publish[index];
    if (this.isEntryEmpty(entry) || confirm('Remove this configuration?')) {
      this.config.publish.splice(index, 1);
    }
  },

  getPreviewUrl(textSlug) {
    if (!textSlug) return '#';
    return routes.publishProjectText(window.PROJECT_SLUG, textSlug);
  },

  generateJSON() {
    const cleaned = {
      publish: this.config.publish.map((entry) => {
        const clean = {};
        this.fields.forEach((f) => {
          const v = entry[f.name];
          if (f.required || (v !== '' && v !== null && v !== undefined)) clean[f.name] = v;
        });
        return clean;
      }),
      pages: this.config.pages,
    };
    return JSON.stringify(cleaned, null, 2);
  },

  copyJSON() {
    navigator.clipboard.writeText(this.generateJSON())
      .then(() => alert('Copied to clipboard!'))
      .catch((err) => console.error('Copy failed:', err));
  },

  submitForm(event) {
    this.$refs.hiddenConfig.value = this.generateJSON();
    event.target.submit();
  },
});
