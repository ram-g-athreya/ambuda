import routes from './routes.js';

export default () => ({
  config: {
    publish: [],
    pages: []
  },
  showJSON: false,
  fields: [],

  init() {
    this.generateFieldsFromSchema();

    try {
      // Load from global constant set in template
      this.config = window.PUBLISH_CONFIG || { publish: [], pages: [] };

      if (!this.config || typeof this.config !== 'object') {
        this.config = { publish: [], pages: [] };
      }

      if (!Array.isArray(this.config.publish)) {
        this.config.publish = [];
      }

      if (!Array.isArray(this.config.pages)) {
        this.config.pages = [];
      }

      this.config.publish.forEach(entry => {
        this.fields.forEach(field => {
          if (!(field.name in entry)) {
            entry[field.name] = this.getDefaultValue(field);
          }
        });
      });
    } catch (e) {
      console.error('Failed to initialize config:', e);
      this.config = { publish: [], pages: [] };
    }
  },

  generateFieldsFromSchema() {
    // Load from global constant set in template
    const schema = window.PUBLISH_CONFIG_SCHEMA || {};
    const properties = schema.properties || {};
    const required = schema.required || [];

    const fieldMetadata = {
      title: { placeholder: 'e.g., Rāmāyaṇa', description: 'Display title for the text' },
      slug: { placeholder: 'e.g., ramayana', description: 'Unique identifier for the text' },
      target: { placeholder: 'e.g., text1', description: 'Target text field from structuring' },
      author: { placeholder: 'e.g., Vālmīki', description: 'Author of the work' },
      genre: { placeholder: 'e.g., Kāvya', description: 'Genre of the text' },
      language: { placeholder: '', description: 'Primary language of the text' },
      parent_slug: { placeholder: 'e.g., ramayana', description: 'Slug of the parent text (for translations/commentaries)' }
    };

    // Define field order explicitly
    const fieldOrder = ['title', 'slug', 'target', 'author', 'genre', 'language', 'parent_slug'];

    this.fields = fieldOrder
      .filter(name => properties[name])
      .map(name => {
        const prop = properties[name];
        let type = prop.type;
        let enumValues = prop.enum;

        if (prop.anyOf) {
          const nonNullType = prop.anyOf.find(t => t.type !== 'null');
          if (nonNullType) {
            type = nonNullType.type;
            enumValues = nonNullType.enum;
          }
        }

        const meta = fieldMetadata[name] || {};

        return {
          name: name,
          label: this.titleCase(name),
          type: type,
          required: required.includes(name),
          enum: enumValues,
          placeholder: meta.placeholder || '',
          description: prop.description || meta.description || ''
        };
      });
  },

  titleCase(str) {
    return str.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  },

  getDefaultValue(field) {
    if (field.type === 'boolean') return false;
    if (field.type === 'number' || field.type === 'integer') return null;
    return '';
  },

  addPublishEntry() {
    const newEntry = {};
    this.fields.forEach(field => {
      newEntry[field.name] = this.getDefaultValue(field);
    });
    this.config.publish.push(newEntry);
  },

  removePublishEntry(index) {
    if (confirm('Remove this configuration?')) {
      this.config.publish.splice(index, 1);
    }
  },

  getPreviewUrl(textSlug) {
    if (!textSlug) return '#';
    return routes.publishProjectText(window.PROJECT_SLUG, textSlug);
  },

  generateJSON() {
    const cleaned = {
      publish: this.config.publish.map(entry => {
        const clean = {};
        this.fields.forEach(field => {
          const value = entry[field.name];
          // Include required fields always & optional fields only if they have a value
          if (field.required || (value !== '' && value !== null && value !== undefined)) {
            clean[field.name] = value;
          }
        });
        return clean;
      }),
      pages: this.config.pages
    };
    return JSON.stringify(cleaned, null, 2);
  },

  copyJSON() {
    navigator.clipboard.writeText(this.generateJSON()).then(() => {
      alert('Copied to clipboard!');
    }).catch(err => {
      console.error('Copy failed:', err);
    });
  },

  submitForm(event) {
    this.$refs.hiddenConfig.value = this.generateJSON();
    event.target.submit();
  }
});
