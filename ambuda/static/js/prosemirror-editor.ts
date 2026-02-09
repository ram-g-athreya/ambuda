/* eslint-disable max-classes-per-file */
import {
  EditorState, Plugin, Transaction, Selection,
} from 'prosemirror-state';
import { EditorView, Decoration, DecorationSet } from 'prosemirror-view';
import {
  Schema, Node as PMNode, Mark, Fragment,
  DOMParser as PMDOMParser, DOMSerializer, NodeSpec, MarkSpec,
} from 'prosemirror-model';
import { keymap } from 'prosemirror-keymap';
import { history, undo as pmUndo, redo as pmRedo } from 'prosemirror-history';
import { baseKeymap } from 'prosemirror-commands';
import { INLINE_MARKS, getAllMarkNames, type MarkName } from './marks-config.ts';

// Keep in sync with ambuda/utils/structuring.py::BlockType
const BLOCK_TYPES = [
  { tag: 'p', label: 'Paragraph', color: 'blue' },
  { tag: 'verse', label: 'Verse', color: 'purple' },
  { tag: 'heading', label: 'Heading', color: 'orange' },
  { tag: 'title', label: 'Title', color: 'indigo' },
  { tag: 'subtitle', label: 'Subtitle', color: 'pink' },
  { tag: 'footnote', label: 'Footnote', color: 'green' },
  { tag: 'trailer', label: 'Trailer', color: 'teal' },
  { tag: 'ignore', label: 'Ignore', color: 'gray' },
  { tag: 'metadata', label: 'Metadata', color: 'gray' },
];

const BLOCK_TYPE_COLORS: Record<string, string> = Object.fromEntries(
  BLOCK_TYPES.map((bt) => [bt.tag, bt.color === 'gray' ? 'border-gray-300' : `border-${bt.color}-400`]),
);

// Nodes are the basic pieces of the document.
const nodes: Record<string, NodeSpec> = {
  doc: {
    content: 'block+',
  },
  block: {
    content: 'inline*',
    attrs: {
      // The block type.
      type: { default: 'p' },
      // The text that this block belongs to
      text: { default: null },
      // Slug ID
      n: { default: null },
      // Footnote mark
      mark: { default: null },
      lang: { default: null },
      // If true, merge this block with the next when publishing at ext.
      merge_next: { default: false },
    },
    group: 'block',
    code: true,
    preserveWhitespace: 'full',
    parseDOM: [
      {
        // matched XML tags
        tag: 'p, verse, heading, title, subtitle, footnote, trailer, ignore',
        preserveWhitespace: 'full',
        getAttrs(dom: HTMLElement) {
          return {
            type: dom.tagName.toLowerCase(),
            text: dom.getAttribute('text'),
            n: dom.getAttribute('n'),
            mark: dom.getAttribute('mark'),
            lang: dom.getAttribute('lang'),
            merge_next: dom.getAttribute('merge-next') === 'true',
          };
        },
      },
    ],
    toDOM(node: PMNode) {
      const attrs: Record<string, string> = {};
      if (node.attrs.text) attrs.text = node.attrs.text;
      if (node.attrs.n) attrs.n = node.attrs.n;
      if (node.attrs.mark) attrs.mark = node.attrs.mark;
      if (node.attrs.lang) attrs.lang = node.attrs.lang;
      if (node.attrs.merge_next) attrs['merge-next'] = 'true';

      // format: [tag, attrs, "hole" where children should be inserted]
      return [node.attrs.type || 'p', attrs, 0];
    },
  },
  text: {
    group: 'inline',
  },
};

// Marks are labels attached to text.
const marks: Record<string, MarkSpec> = Object.fromEntries(
  INLINE_MARKS.map((markConfig) => [
    markConfig.name,
    {
      parseDOM: [{ tag: markConfig.name }],
      toDOM() {
        return ['span', { class: markConfig.className }, 0];
      },
      ...(markConfig.excludes ? { excludes: markConfig.excludes } : {}),
    },
  ]),
);

const customSchema = new Schema({ nodes, marks });

// Extract the word at the cursor position along with line context
function getWordAtCursor(
  state: EditorState,
): { word: string; lineText: string; wordIndex: number } | null {
  const { $from } = state.selection;
  const node = $from.parent;

  if (node.type.name !== 'block') {
    return null;
  }

  const buf: string[] = [];
  node.forEach((child) => {
    if (child.isText && child.text) {
      buf.push(child.text);
    }
  });
  const text = buf.join('');
  const cursorOffset = $from.parentOffset;

  if (!text || cursorOffset > text.length) {
    return null;
  }

  const lineStart = text.lastIndexOf('\n', cursorOffset - 1) + 1;
  const lineEnd = text.indexOf('\n', cursorOffset);
  const line = text.substring(lineStart, lineEnd === -1 ? text.length : lineEnd).trim();

  const cursorLineOFfset = cursorOffset - lineStart;
  const words = line.split(/\s+/).filter((w) => w.length > 0);
  let pos = 0;
  for (let i = 0; i < words.length; i += 1) {
    const wordStart = line.indexOf(words[i], pos);
    const wordEnd = wordStart + words[i].length;
    if (cursorLineOFfset >= wordStart && cursorLineOFfset <= wordEnd) {
      return { word: words[i], line, wordIndex: i };
    }
    pos = wordEnd;
  }

  return null;
}

// Plugin to track cursor changes and emit active word
function activeWordPlugin(
  onActiveWordChange?: (context: { word: string; line: string; wordIndex: number } | null) => void,
) {
  return new Plugin({
    view() {
      return {
        update(view, prevState) {
          if (!view.state.selection.eq(prevState.selection)) {
            const context = getWordAtCursor(view.state);
            if (onActiveWordChange) {
              onActiveWordChange(context);
            }
          }
        },
      };
    },
  });
}

function createBlockBelow(state: EditorState, dispatch?: (tr: Transaction) => void): boolean {
  const { $from, $to } = state.selection;
  const currentBlock = $from.node($from.depth);

  if (currentBlock.type.name !== 'block') {
    return false;
  }

  if (dispatch) {
    const blockPos = $from.before($from.depth);
    const blockStart = blockPos + 1; // +1 to account for the block node itself
    const cursorPos = $from.pos;

    const cursorInBlock = cursorPos - blockStart;

    const contentBefore: PMNode[] = [];
    const contentAfter: PMNode[] = [];

    let currentPos = 0;
    currentBlock.forEach((child, offset) => {
      const childEnd = currentPos + child.nodeSize;

      if (childEnd <= cursorInBlock) {
        // Entire child is before cursor
        contentBefore.push(child);
      } else if (currentPos >= cursorInBlock) {
        // Entire child is after cursor
        contentAfter.push(child);
      } else if (child.isText) {
        // Cursor is within this child (text node)
        const splitPoint = cursorInBlock - currentPos;
        const textBefore = child.text!.substring(0, splitPoint);
        const textAfter = child.text!.substring(splitPoint);

        if (textBefore) {
          contentBefore.push(state.schema.text(textBefore, child.marks));
        }
        if (textAfter) {
          contentAfter.push(state.schema.text(textAfter, child.marks));
        }
      }

      currentPos = childEnd;
    });

    let { tr } = state;
    const newCurrentBlock = state.schema.nodes.block.create(
      currentBlock.attrs,
      contentBefore.length > 0 ? contentBefore : undefined,
    );
    tr = tr.replaceWith(blockPos, blockPos + currentBlock.nodeSize, newCurrentBlock);

    const afterPos = blockPos + newCurrentBlock.nodeSize;
    const newBlock = state.schema.nodes.block.create(
      { type: 'p' },
      contentAfter.length > 0 ? contentAfter : undefined,
    );
    tr = tr.insert(afterPos, newBlock);

    // Set cursor at the beginning of the new block
    tr = tr.setSelection(Selection.near(tr.doc.resolve(afterPos + 1)));

    dispatch(tr);
  }

  return true;
}

class BlockView {
  dom: HTMLElement;

  contentDOM: HTMLElement;

  node: PMNode;

  view: EditorView;

  getPos: () => number | undefined;

  controlsDOM: HTMLElement;

  typeSelect: HTMLSelectElement;

  textInput: HTMLInputElement;

  textLabel: HTMLSpanElement;

  nInput: HTMLInputElement;

  nLabel: HTMLSpanElement;

  markInput: HTMLInputElement;

  markLabel: HTMLSpanElement;

  mergeCheckbox: HTMLInputElement;

  mergeLabel: HTMLLabelElement;

  dropdownButton: HTMLButtonElement;

  dropdownMenu: HTMLElement;

  dropdownWrapper: HTMLElement;

  mergeUpBtn: HTMLButtonElement;

  mergeDownBtn: HTMLButtonElement;

  dropdownOpen: boolean;

  editor: any; // ProofingEditor instance

  private createLabeledInput(attrName: string, labelText: string, placeholder: string, width: string, extraClass: string = ''): { label: HTMLSpanElement; input: HTMLInputElement } {
    const label = document.createElement('span');
    label.className = 'text-slate-400 text-[11px] ml-1';
    label.textContent = labelText;
    this.controlsDOM.appendChild(label);

    const input = document.createElement('input');
    input.type = 'text';
    input.value = this.node.attrs[attrName] || '';
    input.placeholder = placeholder;
    input.className = `border border-slate-300 bg-transparent text-xs text-slate-600 ${width} px-1 py-0 hover:bg-slate-100 rounded ${extraClass}`;
    input.addEventListener('change', () => this.updateNodeAttr(attrName, input.value || null));
    this.controlsDOM.appendChild(input);

    return { label, input };
  }

  private createDropdownButton(icon: string, label: string, handler: () => void, className: string = ''): HTMLButtonElement {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `w-full text-left px-3 py-2 text-xs hover:bg-slate-100 flex items-center gap-2 ${className}`;
    btn.innerHTML = `<span>${icon}</span> ${label}`;
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      handler();
      this.closeDropdown();
    });
    this.dropdownMenu.appendChild(btn);
    return btn;
  }

  constructor(node: PMNode, view: EditorView, getPos: () => number | undefined, editor: any) {
    this.node = node;
    this.view = view;
    this.getPos = getPos;
    this.editor = editor;
    this.dropdownOpen = false;

    if (editor.blockViews) {
      editor.blockViews.add(this);
    }

    this.dom = document.createElement('div');
    this.setBlockDOMClasses();

    // Controls bar
    this.controlsDOM = document.createElement('div');
    this.controlsDOM.className = 'flex gap-1 mb-1 px-1.5 py-1 text-xs text-slate-500 items-center bg-slate-50 rounded leading-tight';

    // Type dropdown
    this.typeSelect = document.createElement('select');
    this.typeSelect.className = 'border border-slate-300 bg-white text-xs font-medium cursor-pointer hover:bg-slate-100 rounded px-1 py-0';
    const currentType = node.attrs.type || 'p';
    BLOCK_TYPES.forEach((bt) => {
      const option = document.createElement('option');
      option.value = bt.tag;
      option.textContent = bt.label;
      if (bt.tag === currentType) option.selected = true;
      this.typeSelect.appendChild(option);
    });
    this.typeSelect.addEventListener('change', () => this.updateNodeAttr('type', this.typeSelect.value));
    this.controlsDOM.appendChild(this.typeSelect);

    // Attribute inputs
    // TODO: rename `text` to `label` in storage.
    const text = this.createLabeledInput('text', 'label=', 'label', 'w-20');
    this.textLabel = text.label;
    this.textInput = text.input;
    this.textLabel.style.display = this.editor.showAdvancedOptions ? '' : 'none';
    this.textInput.style.display = this.editor.showAdvancedOptions ? '' : 'none';

    const n = this.createLabeledInput('n', 'n=', '#', 'w-12', 'font-mono');
    this.nLabel = n.label;
    this.nInput = n.input;

    const mark = this.createLabeledInput('mark', 'mark=', 'mark', 'w-16', 'font-mono');
    this.markLabel = mark.label;
    this.markInput = mark.input;

    this.updateFieldVisibility();

    // Merge checkbox
    this.mergeLabel = document.createElement('label');
    this.mergeLabel.className = 'flex items-center gap-0.5 cursor-pointer hover:bg-slate-100 px-1 rounded ml-1';
    this.mergeLabel.style.display = this.editor.showAdvancedOptions ? '' : 'none';

    this.mergeCheckbox = document.createElement('input');
    this.mergeCheckbox.type = 'checkbox';
    this.mergeCheckbox.className = 'w-3 h-3';
    this.mergeCheckbox.checked = node.attrs.merge_next || false;
    this.mergeCheckbox.addEventListener('change', () => this.updateNodeAttr('merge_next', this.mergeCheckbox.checked));

    const mergeText = document.createElement('span');
    mergeText.className = 'text-[11px]';
    mergeText.textContent = 'merge next';

    this.mergeLabel.appendChild(this.mergeCheckbox);
    this.mergeLabel.appendChild(mergeText);
    this.controlsDOM.appendChild(this.mergeLabel);

    // Dropdown
    this.dropdownWrapper = document.createElement('div');
    this.dropdownWrapper.className = 'ml-auto relative';

    this.dropdownButton = document.createElement('button');
    this.dropdownButton.type = 'button';
    this.dropdownButton.className = 'text-[11px] px-2 py-0.5 bg-slate-100 hover:bg-slate-200 rounded border border-slate-300';
    this.dropdownButton.title = 'Block actions';
    this.dropdownButton.innerHTML = '&hellip;';
    this.dropdownButton.addEventListener('click', (e) => {
      e.preventDefault();
      this.toggleDropdown();
    });
    this.dropdownWrapper.appendChild(this.dropdownButton);

    this.dropdownMenu = document.createElement('div');
    this.dropdownMenu.className = 'absolute right-0 mt-1 bg-white border border-slate-300 rounded shadow-lg z-10 min-w-[140px]';
    this.dropdownMenu.style.display = 'none';

    this.createDropdownButton('<span class="text-green-600">+</span>', 'Add below', () => this.addBlockBelow());
    this.createDropdownButton('↑', 'Move up', () => this.moveBlockUp(), 'border-t border-slate-200');
    this.createDropdownButton('↓', 'Move down', () => this.moveBlockDown());
    this.mergeUpBtn = this.createDropdownButton('⤒', 'Merge up', () => this.mergeBlockUp(), 'border-t border-slate-200');
    this.mergeDownBtn = this.createDropdownButton('⤓', 'Merge down', () => this.mergeBlockDown());
    this.createDropdownButton('×', 'Remove', () => this.removeBlock(), 'border-t border-slate-200 hover:!bg-red-50 text-red-700');

    this.dropdownWrapper.appendChild(this.dropdownMenu);
    this.controlsDOM.appendChild(this.dropdownWrapper);

    document.addEventListener('click', (e) => {
      if (this.dropdownOpen && !this.dropdownWrapper.contains(e.target as Node)) {
        this.closeDropdown();
      }
    });

    this.dom.appendChild(this.controlsDOM);

    // Content area
    this.contentDOM = document.createElement('div');
    this.updateContentDOMClasses();
    this.contentDOM.style.fontSize = `${this.editor.textZoom}rem`;
    this.contentDOM.contentEditable = 'true';
    this.dom.appendChild(this.contentDOM);
  }

  setBlockDOMClasses() {
    const blockType = this.node.attrs.type || 'p';
    this.dom.className = `border-l-4 pl-4 mb-3 transition-colors ${BLOCK_TYPE_COLORS[blockType] || 'border-gray-400'}`;
    if (this.node.attrs.merge_next) {
      this.dom.classList.add('bg-yellow-50', '!border-dashed');
    }
  }

  updateFieldVisibility() {
    const isFootnote = this.node.attrs.type === 'footnote';
    const showAdvanced = this.editor.showAdvancedOptions;

    // N field: show for non-footnote blocks when advanced options are enabled
    if (this.nLabel && this.nInput) {
      const showN = !isFootnote && showAdvanced;
      this.nLabel.style.display = showN ? '' : 'none';
      this.nInput.style.display = showN ? '' : 'none';
    }

    // Mark field: always show for footnote blocks, hide for others
    if (this.markLabel && this.markInput) {
      this.markLabel.style.display = isFootnote ? '' : 'none';
      this.markInput.style.display = isFootnote ? '' : 'none';
    }
  }

  updateContentDOMClasses() {
    const blockType = this.node.attrs.type || 'p';
    this.contentDOM.className = 'pm-content-dom';
    if (blockType === 'ignore') {
      this.contentDOM.classList.add('bg-gray-100', 'text-gray-500');
    } else if (blockType === 'metadata') {
      this.contentDOM.classList.add('pm-metadata');
    }
  }

  updateNodeAttr(name: string, value: any) {
    const pos = this.getPos();
    if (pos === undefined) return;

    const tr = this.view.state.tr.setNodeMarkup(pos, undefined, {
      ...this.node.attrs,
      [name]: value,
    });
    this.view.dispatch(tr);

    if (name === 'type' || name === 'merge_next') {
      this.setBlockDOMClasses();
      if (name === 'type') {
        this.updateContentDOMClasses();
        this.updateFieldVisibility();
      }
    }
  }

  update(node: PMNode) {
    if (node.type !== this.node.type) return false;

    this.node = node;

    this.setBlockDOMClasses();
    this.updateContentDOMClasses();

    const blockType = node.attrs.type || 'p';
    if (this.typeSelect.value !== blockType) {
      this.typeSelect.value = blockType;
    }
    if (this.textInput.value !== (node.attrs.text || '')) {
      this.textInput.value = node.attrs.text || '';
    }
    if (this.nInput && this.nInput.value !== (node.attrs.n || '')) {
      this.nInput.value = node.attrs.n || '';
    }
    if (this.markInput && this.markInput.value !== (node.attrs.mark || '')) {
      this.markInput.value = node.attrs.mark || '';
    }
    if (this.mergeCheckbox.checked !== node.attrs.merge_next) {
      this.mergeCheckbox.checked = node.attrs.merge_next;
    }

    this.updateFieldVisibility();

    return true;
  }

  stopEvent(event: Event) {
    // Allow all events within the contentDOM (for editing)
    // but prevent events in the controls from affecting ProseMirror
    return this.controlsDOM.contains(event.target as Node);
  }

  ignoreMutation(mutation: MutationRecord) {
    // Ignore mutations in controls
    if (mutation.type === 'attributes' && mutation.target !== this.contentDOM) {
      return true;
    }
    return false;
  }

  updateAdvancedOptionsVisibility() {
    const show = this.editor.showAdvancedOptions;
    this.textLabel.style.display = show ? '' : 'none';
    this.textInput.style.display = show ? '' : 'none';
    this.mergeLabel.style.display = show ? '' : 'none';
    // Update n and mark field visibility based on both advanced options and block type
    this.updateFieldVisibility();
  }

  getBlockIndex(): number {
    const pos = this.getPos();
    if (pos === undefined) return -1;
    let offset = 0;
    for (let i = 0; i < this.view.state.doc.childCount; i += 1) {
      if (offset === pos) return i;
      offset += this.view.state.doc.child(i).nodeSize;
    }
    return -1;
  }

  toggleDropdown() {
    this.dropdownOpen = !this.dropdownOpen;
    this.dropdownMenu.style.display = this.dropdownOpen ? 'block' : 'none';

    if (this.dropdownOpen) {
      const index = this.getBlockIndex();
      const count = this.view.state.doc.childCount;
      const disabledClass = 'opacity-40 pointer-events-none';
      this.mergeUpBtn.className = this.mergeUpBtn.className.replace(disabledClass, '').trim();
      this.mergeDownBtn.className = this.mergeDownBtn.className.replace(disabledClass, '').trim();

      const isFirst = index <= 0;
      const isLast = index >= count - 1;
      if (isFirst) this.mergeUpBtn.className += ` ${disabledClass}`;
      if (isLast) this.mergeDownBtn.className += ` ${disabledClass}`;
    }
  }

  closeDropdown() {
    this.dropdownOpen = false;
    this.dropdownMenu.style.display = 'none';
  }

  addBlockBelow() {
    const pos = this.getPos();
    if (pos === undefined) return;

    const blockPos = pos;
    const afterPos = blockPos + this.node.nodeSize;
    const newBlock = this.view.state.schema.nodes.block.create({ type: 'p' });
    const tr = this.view.state.tr.insert(afterPos, newBlock);
    tr.setSelection(Selection.near(tr.doc.resolve(afterPos + 1)));
    this.view.dispatch(tr);
  }

  removeBlock() {
    const pos = this.getPos();
    if (pos === undefined) return;

    // Don't allow deleting if it's the only block
    if (this.view.state.doc.childCount === 1) {
      alert('Cannot remove the last block');
      return;
    }

    if (window.confirm('Are you sure you want to remove this block?')) {
      const tr = this.view.state.tr.delete(pos, pos + this.node.nodeSize);
      this.view.dispatch(tr);
    }
  }

  moveBlockUp() {
    this.editor.moveBlockUp(this.getBlockIndex());
  }

  moveBlockDown() {
    this.editor.moveBlockDown(this.getBlockIndex());
  }

  mergeBlockUp() {
    this.editor.mergeBlockUp(this.getBlockIndex());
  }

  mergeBlockDown() {
    this.editor.mergeBlockDown(this.getBlockIndex());
  }

  destroy() {
    // Unregister this BlockView from the editor
    if (this.editor.blockViews) {
      this.editor.blockViews.delete(this);
    }
  }
}

function parseInlineContent(elem: Element, schema: Schema): PMNode[] {
  const result: PMNode[] = [];

  function serializeNode(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent || '';
    } if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as Element;
      const tagName = el.tagName.toLowerCase();
      const children = Array.from(node.childNodes).map(serializeNode).join('');
      return `<${tagName}>${children}</${tagName}>`;
    }
    return '';
  }

  function traverse(node: Node, activeMarks: readonly Mark[] = []) {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent || '';
      if (text) {
        result.push(schema.text(text, activeMarks));
      }
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as Element;
      const tagName = el.tagName.toLowerCase();

      // Check if it's a mark we want to render visually
      const validMarkNames = getAllMarkNames();
      if (validMarkNames.includes(tagName)) {
        const mark = schema.mark(tagName);
        const newMarks = mark.addToSet(activeMarks);
        // Traverse children with the mark applied
        for (let i = 0; i < node.childNodes.length; i += 1) {
          traverse(node.childNodes[i], newMarks);
        }
      } else {
        // For other inline elements (like <a>, <b>, etc.), preserve them as text
        const serialized = serializeNode(node);
        if (serialized) {
          result.push(schema.text(serialized, activeMarks));
        }
      }
    }
  }

  for (let i = 0; i < elem.childNodes.length; i += 1) {
    traverse(elem.childNodes[i]);
  }

  return result;
}

// Parse XML content to ProseMirror document
// XML is always rooted in a <page> tag containing block elements
function parseXMLToDoc(xmlString: string, schema: Schema): PMNode {
  // Handle empty content
  if (!xmlString || xmlString.trim() === '') {
    return schema.node('doc', null, [schema.node('block', { type: 'p' })]);
  }

  const parser = new DOMParser();
  const xmlDoc = parser.parseFromString(xmlString, 'text/xml');

  // Check for parse errors
  const parseError = xmlDoc.querySelector('parsererror');
  if (parseError) {
    console.error('[parseXMLToDoc] XML parse error:', parseError.textContent);
    throw new Error(`Failed to parse XML: ${parseError.textContent}`);
  }

  const blocks: PMNode[] = [];
  const pageElement = xmlDoc.documentElement;

  // Verify it's a <page> element
  if (pageElement.tagName.toLowerCase() !== 'page') {
    throw new Error(`Expected <page> root element, got <${pageElement.tagName}>`);
  }

  // Parse all child block elements
  for (let i = 0; i < pageElement.children.length; i += 1) {
    const elem = pageElement.children[i];
    const type = elem.tagName.toLowerCase();

    // Extract attributes
    const attrs: any = { type };
    if (elem.hasAttribute('text')) attrs.text = elem.getAttribute('text');
    if (elem.hasAttribute('n')) attrs.n = elem.getAttribute('n');
    if (elem.hasAttribute('mark')) attrs.mark = elem.getAttribute('mark');
    if (elem.hasAttribute('lang')) attrs.lang = elem.getAttribute('lang');
    if (elem.getAttribute('merge-next') === 'true') attrs.merge_next = true;

    // Parse inline content
    const content = parseInlineContent(elem, schema);

    blocks.push(schema.node('block', attrs, content));
  }

  if (blocks.length === 0) {
    blocks.push(schema.node('block', { type: 'p' }));
  }

  return schema.node('doc', null, blocks);
}

function escapeXML(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function serializeInlineContent(node: PMNode): string {
  let result = '';

  node.forEach((child) => {
    if (child.isText) {
      let text = escapeXML(child.text || '');
      child.marks.forEach((mark) => {
        text = `<${mark.type.name}>${text}</${mark.type.name}>`;
      });

      result += text;
    }
  });

  return result;
}

function serializeDocToXML(doc: PMNode): string {
  const parts: string[] = [];

  doc.forEach((block) => {
    const type = block.attrs.type || 'p';
    const attrs: string[] = [];

    if (block.attrs.text) attrs.push(`text="${escapeXML(block.attrs.text)}"`);
    if (block.attrs.n) attrs.push(`n="${escapeXML(block.attrs.n)}"`);
    if (block.attrs.mark) attrs.push(`mark="${escapeXML(block.attrs.mark)}"`);
    if (block.attrs.lang) attrs.push(`lang="${escapeXML(block.attrs.lang)}"`);
    if (block.attrs.merge_next) attrs.push('merge-next="true"');

    const attrsStr = attrs.length > 0 ? ` ${attrs.join(' ')}` : '';
    const content = serializeInlineContent(block);

    parts.push(`<${type}${attrsStr}>${content}</${type}>`);
  });

  return `<page>\n${parts.join('\n')}\n</page>`;
}

// Schema for XML editing mode - a simple code editor
const xmlSchema = new Schema({
  nodes: {
    doc: {
      content: 'codeblock',
    },
    codeblock: {
      content: 'text*',
      group: 'block',
      code: true,
      preserveWhitespace: 'full',
      parseDOM: [{ tag: 'pre' }],
      toDOM() {
        return ['pre', { class: 'xml-code' }, 0];
      },
    },
    text: {
      group: 'inline',
    },
  },
  marks: {},
});

function createXMLDecorations(state: EditorState): DecorationSet {
  const decorations: Decoration[] = [];
  const text = state.doc.textContent;

  const tagRegex = /<\/?([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>/g;
  let match = tagRegex.exec(text);

  while (match !== null) {
    // Positions need to account for document structure:
    // doc (pos 0) -> codeblock (pos 1) -> text content starts at pos 1
    // So we add 1 to convert text offsets to document positions
    const from = match.index + 1;
    const to = match.index + match[0].length + 1;

    decorations.push(
      Decoration.inline(from, to, {
        style: 'color: #60a5fa;', // Blue color for tags
      }),
    );
    match = tagRegex.exec(text);
  }

  return DecorationSet.create(state.doc, decorations);
}

// Plugin to add XML syntax highlighting decorations
function xmlHighlightPlugin() {
  return new Plugin({
    state: {
      init(_, state) {
        return createXMLDecorations(state);
      },
      apply(tr, set, oldState, newState) {
        if (!tr.docChanged) return set;
        return createXMLDecorations(newState);
      },
    },
    props: {
      decorations(state) {
        return this.getState(state);
      },
    },
  });
}

export class XMLView {
  view: EditorView;

  schema: Schema;

  onChange?: () => void;

  // eslint-disable-next-line default-param-last
  constructor(element: HTMLElement, initialContent: string = '', onChange?: () => void) {
    this.schema = xmlSchema;
    this.onChange = onChange;

    const textNode = initialContent ? this.schema.text(initialContent) : undefined;
    const codeblock = this.schema.node('codeblock', null, textNode ? [textNode] : []);

    const state = EditorState.create({
      doc: this.schema.node('doc', null, [codeblock]),
      plugins: [
        history(),
        xmlHighlightPlugin(),
        keymap({ 'Mod-z': pmUndo, 'Mod-y': pmRedo }),
        keymap(baseKeymap),
      ],
    });

    // Create wrapper for styling
    const wrapper = document.createElement('div');
    wrapper.className = 'w-full h-full bg-gray-800 text-gray-300';
    element.appendChild(wrapper);

    this.view = new EditorView(wrapper, {
      state,
      dispatchTransaction: (transaction) => {
        const newState = this.view.state.apply(transaction);
        this.view.updateState(newState);

        if (transaction.docChanged && this.onChange) {
          this.onChange();
        }
      },
      attributes: {
        class: 'w-full h-full font-mono text-sm focus:outline-none',
        spellcheck: 'false',
      },
    });
  }

  getText(): string {
    return this.view.state.doc.textContent;
  }

  setText(text: string) {
    const textNode = text ? this.schema.text(text) : undefined;
    const codeblock = this.schema.node('codeblock', null, textNode ? [textNode] : []);
    const newState = EditorState.create({
      doc: this.schema.node('doc', null, [codeblock]),
      plugins: this.view.state.plugins,
    });
    this.view.updateState(newState);
  }

  focus() {
    this.view.focus();
  }

  getSelection(): { from: number; to: number; text: string } {
    const { from, to } = this.view.state.selection;
    const text = this.view.state.doc.textBetween(from, to, '\n');
    return { from, to, text };
  }

  replaceSelection(text: string) {
    const { state } = this.view;
    const { from, to } = state.selection;

    const tr = state.tr.insertText(text, from, to);
    const newState = state.apply(tr);
    this.view.updateState(newState);
    this.view.focus();

    if (this.onChange) {
      this.onChange();
    }
  }

  undo() {
    pmUndo(this.view.state, this.view.dispatch);
  }

  redo() {
    pmRedo(this.view.state, this.view.dispatch);
  }

  destroy() {
    this.view.destroy();
  }
}

export default class {
  view: EditorView;

  schema: Schema;

  onChange?: () => void;

  onActiveWordChange?: (
    context: { word: string; lineText: string; wordIndex: number } | null,
  ) => void;

  showAdvancedOptions: boolean;

  blockViews: Set<BlockView>;

  textZoom: number;

  constructor(
    element: HTMLElement,
    // eslint-disable-next-line default-param-last
    initialContent: string = '',
    onChange?: () => void,
    // eslint-disable-next-line default-param-last
    showAdvancedOptions: boolean = false,
    // eslint-disable-next-line default-param-last
    textZoom: number = 1.0,
    onActiveWordChange?: (
      context: { word: string; lineText: string; wordIndex: number } | null,
    ) => void,
  ) {
    this.schema = customSchema;
    this.onChange = onChange;
    this.onActiveWordChange = onActiveWordChange;
    this.showAdvancedOptions = showAdvancedOptions;
    this.blockViews = new Set();
    this.textZoom = textZoom;

    let doc;
    try {
      doc = parseXMLToDoc(initialContent, this.schema);
    } catch (error) {
      doc = this.schema.node('doc', null, [this.schema.node('block', { type: 'p' })]);
    }

    const state = EditorState.create({
      doc,
      plugins: [
        history(),
        keymap({ 'Mod-z': pmUndo, 'Mod-y': pmRedo, 'Shift-Enter': createBlockBelow }),
        keymap(baseKeymap),
        activeWordPlugin(this.onActiveWordChange),
      ],
    });

    this.view = new EditorView(element, {
      state,
      nodeViews: {
        block: (node, view, getPos) => new BlockView(node, view, getPos as () => number, this),
      },
      dispatchTransaction: (transaction) => {
        const newState = this.view.state.apply(transaction);
        this.view.updateState(newState);

        if (transaction.docChanged && this.onChange) {
          this.onChange();
        }
      },
    });
  }

  getText(): string {
    return serializeDocToXML(this.view.state.doc);
  }

  setText(text: string) {
    const newDoc = parseXMLToDoc(text, this.schema);
    const newState = EditorState.create({
      doc: newDoc,
      plugins: this.view.state.plugins,
    });
    this.view.updateState(newState);
  }

  focus() {
    this.view.focus();
  }

  getSelection(): { from: number; to: number; text: string } {
    const { from, to } = this.view.state.selection;
    const text = this.view.state.doc.textBetween(from, to, '\n');
    return { from, to, text };
  }

  replaceSelection(text: string) {
    const { state } = this.view;
    const { from, to } = state.selection;

    const tr = state.tr.insertText(text, from, to);
    const newState = state.apply(tr);
    this.view.updateState(newState);
    this.view.focus();

    if (this.onChange) {
      this.onChange();
    }
  }

  toggleMark(markType: MarkName) {
    const { state, dispatch } = this.view;
    const { from, to } = state.selection;

    const mark = this.schema.marks[markType];
    if (!mark) return;

    const hasMark = state.doc.rangeHasMark(from, to, mark);
    if (hasMark) {
      const tr = state.tr.removeMark(from, to, mark);
      dispatch(tr);
    } else {
      const tr = state.tr.addMark(from, to, mark.create());
      dispatch(tr);
    }
  }

  getBlockIndexFromSelection(): number {
    const { state } = this.view;
    const { $from } = state.selection;

    let blockDepth = $from.depth;
    while (blockDepth > 0 && state.doc.resolve($from.pos).node(blockDepth).type.name !== 'block') {
      blockDepth -= 1;
    }
    if (blockDepth === 0) return -1;

    const currentBlock = $from.node(blockDepth);
    for (let i = 0; i < state.doc.childCount; i += 1) {
      if (state.doc.child(i) === currentBlock) return i;
    }
    return -1;
  }

  getBlockStartPos(index: number): number {
    const { state } = this.view;
    let pos = 0;
    for (let i = 0; i < index; i += 1) {
      pos += state.doc.child(i).nodeSize;
    }
    return pos;
  }

  insertBlock(blockIndex?: number) {
    const { state, dispatch } = this.view;
    if (blockIndex === undefined) blockIndex = this.getBlockIndexFromSelection();
    if (blockIndex < 0) return;

    const afterPos = this.getBlockStartPos(blockIndex) + state.doc.child(blockIndex).nodeSize;
    const newBlock = this.schema.nodes.block.create({ type: 'p' });
    const tr = state.tr.insert(afterPos, newBlock);
    tr.setSelection(Selection.near(tr.doc.resolve(afterPos + 1)));
    dispatch(tr);

    if (this.onChange) {
      this.onChange();
    }
  }

  deleteActiveBlock(blockIndex?: number) {
    const { state, dispatch } = this.view;
    if (blockIndex === undefined) blockIndex = this.getBlockIndexFromSelection();
    if (blockIndex < 0) return;

    if (state.doc.childCount === 1) return;

    const blockPos = this.getBlockStartPos(blockIndex);
    const tr = state.tr.delete(blockPos, blockPos + state.doc.child(blockIndex).nodeSize);
    dispatch(tr);

    if (this.onChange) {
      this.onChange();
    }
  }

  moveBlockUp(blockIndex?: number) {
    if (blockIndex === undefined) blockIndex = this.getBlockIndexFromSelection();
    if (blockIndex <= 0) return;
    this.swapBlocks(blockIndex - 1, blockIndex);
  }

  moveBlockDown(blockIndex?: number) {
    if (blockIndex === undefined) blockIndex = this.getBlockIndexFromSelection();
    if (blockIndex < 0 || blockIndex >= this.view.state.doc.childCount - 1) return;
    this.swapBlocks(blockIndex, blockIndex + 1);
  }

  private swapBlocks(indexA: number, indexB: number) {
    const { state, dispatch } = this.view;
    const blockA = state.doc.child(indexA);
    const blockB = state.doc.child(indexB);

    const newChildren: PMNode[] = [];
    for (let i = 0; i < state.doc.childCount; i += 1) {
      if (i === indexA) newChildren.push(blockB);
      else if (i === indexB) newChildren.push(blockA);
      else newChildren.push(state.doc.child(i));
    }

    const newDoc = state.schema.node('doc', null, newChildren);
    let tr = state.tr.replaceWith(0, state.doc.content.size, newDoc);
    // Place cursor in whichever block ended up at indexA (the earlier position)
    tr = tr.setSelection(Selection.near(tr.doc.resolve(this.getBlockStartPos(indexA) + 1)));
    dispatch(tr);

    if (this.onChange) {
      this.onChange();
    }
  }

  mergeBlockUp(blockIndex?: number) {
    this.mergeBlocks('up', blockIndex);
  }

  mergeBlockDown(blockIndex?: number) {
    this.mergeBlocks('down', blockIndex);
  }

  mergeBlocks(direction: 'up' | 'down', blockIndex?: number) {
    const { state, dispatch } = this.view;
    if (blockIndex === undefined) blockIndex = this.getBlockIndexFromSelection();

    if (direction === 'up' && blockIndex <= 0) return;
    if (direction === 'down' && (blockIndex < 0 || blockIndex >= state.doc.childCount - 1)) return;

    const keepIndex = direction === 'up' ? blockIndex - 1 : blockIndex;
    const removeIndex = direction === 'up' ? blockIndex : blockIndex + 1;
    const keepBlock = state.doc.child(keepIndex);
    const removeBlock = state.doc.child(removeIndex);

    const separator = state.schema.text('\n');
    const mergedContent = Fragment.from([
      ...keepBlock.content.content,
      separator,
      ...removeBlock.content.content,
    ]);
    const mergedBlock = keepBlock.copy(mergedContent);

    const newChildren: PMNode[] = [];
    for (let i = 0; i < state.doc.childCount; i += 1) {
      if (i === keepIndex) {
        newChildren.push(mergedBlock);
      } else if (i !== removeIndex) {
        newChildren.push(state.doc.child(i));
      }
    }

    const newDoc = state.schema.node('doc', null, newChildren);
    let tr = state.tr.replaceWith(0, state.doc.content.size, newDoc);

    let targetPos = 0;
    for (let i = 0; i < keepIndex; i += 1) {
      targetPos += newChildren[i].nodeSize;
    }
    tr = tr.setSelection(Selection.near(tr.doc.resolve(targetPos + 1)));

    dispatch(tr);

    if (this.onChange) {
      this.onChange();
    }
  }

  undo() {
    pmUndo(this.view.state, this.view.dispatch);
  }

  redo() {
    pmRedo(this.view.state, this.view.dispatch);
  }

  setShowAdvancedOptions(show: boolean) {
    this.showAdvancedOptions = show;

    this.blockViews.forEach((blockView) => {
      blockView.updateAdvancedOptionsVisibility();
    });
  }

  setTextZoom(zoom: number) {
    this.textZoom = zoom;

    this.blockViews.forEach((blockView) => {
      blockView.contentDOM.style.fontSize = `${zoom}rem`;
    });
  }

  destroy() {
    this.view.destroy();
  }
}
