export interface InlineMarkConfig {
  name: string;
  emoji: string;
  label: string;
  className: string;
  excludes?: string;
}

// Keep in sync with ambuda/utils/project_structuring.py::InlineType
export const INLINE_MARKS: InlineMarkConfig[] = [
  {
    name: 'error',
    emoji: '⛔',
    label: 'Error',
    className: 'pm-error',
    excludes: 'fix',
  },
  {
    name: 'fix',
    emoji: '✅',
    label: 'Fix',
    className: 'pm-fix',
    excludes: 'error',
  },
  {
    name: 'flag',
    emoji: '?',
    label: 'Unclear',
    className: 'pm-flag',
  },
  {
    name: 'ref',
    emoji: 'ref: ',
    label: 'Footnote number',
    className: 'pm-ref',
    excludes: '_',
  },
  {
    name: 'stage',
    emoji: '🎬',
    label: 'Stage direction',
    className: 'pm-stage',
    excludes: 'speaker',
  },
  {
    name: 'speaker',
    emoji: '📣',
    label: 'Speaker',
    className: 'pm-speaker',
    excludes: 'stage',
  },
  {
    name: 'chaya',
    emoji: '🌒',
    label: 'Chaya',
    className: 'pm-chaya',
    excludes: 'speaker',
  },
  {
    name: 'prakrit',
    emoji: '☀️',
    label: 'Prakrit',
    className: 'pm-prakrit',
    excludes: 'speaker',
  },
  {
    name: 'note',
    emoji: '📝',
    label: 'Internal note',
    className: 'pm-note',
    excludes: '_',
  },
  {
    name: 'add',
    emoji: '',
    label: 'Added by editor',
    className: 'pm-add',
  },
  {
    name: 'ellipsis',
    emoji: '',
    label: 'Omitted by editor',
    className: 'pm-ellipsis',
  },
  {
    name: 'quote',
    emoji: '💬',
    label: 'Quote',
    className: 'pm-quote',
  },
];

export type MarkName = typeof INLINE_MARKS[number]['name'];

export function getAllMarkNames(): string[] {
  return INLINE_MARKS.map((m) => m.name);
}
