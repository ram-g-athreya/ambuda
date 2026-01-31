import { $ } from '@/core.ts';
import Proofer from '@/proofer';

const sampleHTML = `
<div>
  <textarea id="content"></textarea>
  <div id="prosemirror-editor"></div>
</div>
`;

// Can't modify existing `window.location` -- delete it so that we can mock it.
delete window.location;
window.IMAGE_URL = 'IMAGE_URL';
window.OCR_BOUNDING_BOXES = '';
window.OpenSeadragon = (_) => ({
  addHandler: jest.fn((_, callback) => callback()),
  world: { getItemAt: jest.fn(() => null) },
  viewport: {
    getHomeZoom: jest.fn(() => 0.5),
    zoomTo: jest.fn(),
    getZoom: jest.fn(() => 0.5),
    fitHorizontally: jest.fn(),
    fitVertically: jest.fn(),
  },
});

const mockEditor = {
  setText: jest.fn(),
  getText: jest.fn(() => ''),
  setTextZoom: jest.fn(),
  getSelection: jest.fn(() => ({ from: 0, to: 0, text: '' })),
  replaceSelection: jest.fn(),
  destroy: jest.fn(),
  focus: jest.fn(),
  setShowAdvancedOptions: jest.fn(),
  insertBlock: jest.fn(),
  deleteActiveBlock: jest.fn(),
  moveBlockUp: jest.fn(),
  moveBlockDown: jest.fn(),
  mergeBlockUp: jest.fn(),
  mergeBlockDown: jest.fn(),
  undo: jest.fn(),
  redo: jest.fn(),
  toggleMark: jest.fn(),
};

window.Alpine = { raw: jest.fn(() => mockEditor) };
window.Sanscript = {
  t: jest.fn((s, from, to) => `:${s}:${to}`),
};
window.fetch = jest.fn(async (url) => {
  if (url.includes('error')) {
    return { ok: false };
  }
  const segments = url.split('/');
  const page = segments.pop();
  return {
    ok: true,
    text: async () => `text for ${page}`,
  };
});
navigator.clipboard = {
  writeText: jest.fn(),
};

beforeEach(() => {
  window.location = null;
  window.localStorage.clear();
  document.write(sampleHTML);
  jest.clearAllMocks();
});

// -- Init & settings --

test('Proofer can be created and initialized', () => {
  const p = Proofer();
  p.init();
  expect(p.textZoom).toBe(1);
  expect(p.imageZoom).toBe(0.5);
});

test('saveSettings and loadSettings round-trip', () => {
  const p = Proofer();
  p.textZoom = 1.5;
  p.imageZoom = 2.0;
  p.layout = 'image-left';
  p.fromScript = 'iast';
  p.toScript = 'devanagari';
  p.trackBoundingBox = true;
  p.normalizeReplaceColonVisarga = false;
  p.saveSettings();

  const p2 = Proofer();
  p2.loadSettings();
  expect(p2.textZoom).toBe(1.5);
  expect(p2.imageZoom).toBe(2.0);
  expect(p2.layout).toBe('image-left');
  expect(p2.fromScript).toBe('iast');
  expect(p2.toScript).toBe('devanagari');
  expect(p2.trackBoundingBox).toBe(true);
  expect(p2.normalizeReplaceColonVisarga).toBe(false);
});

test('loadSettings with empty localStorage uses defaults', () => {
  localStorage.setItem('proofing-editor', '{}');
  const p = Proofer();
  p.loadSettings();
  expect(p.textZoom).toBe(1);
  expect(p.layout).toBe('image-right');
});

test('loadSettings with corrupt localStorage does not throw', () => {
  localStorage.setItem('proofing-editor', 'invalid JSON');
  const p = Proofer();
  p.loadSettings();
});

test('normalize preferences default to true', () => {
  localStorage.setItem('proofing-editor', '{}');
  const p = Proofer();
  p.loadSettings();
  expect(p.normalizeReplaceColonVisarga).toBe(true);
  expect(p.normalizeReplaceSAvagraha).toBe(true);
  expect(p.normalizeReplaceDoublePipe).toBe(true);
});

// -- Callbacks --

test('onBeforeUnload returns true when changes are present', () => {
  const p = Proofer();
  p.hasUnsavedChanges = true;
  expect(p.onBeforeUnload()).toBe(true);
});

test('onBeforeUnload returns null when no changes', () => {
  const p = Proofer();
  expect(p.onBeforeUnload()).toBe(null);
});

// -- Fetch & OCR --

test('runOCR fetches and sets content', async () => {
  const p = Proofer();
  p.init();
  window.location = new URL('https://ambuda.org/proofing/my-project/my-page');
  await p.runOCR();
  expect(mockEditor.setText).toHaveBeenCalledWith('text for my-page');
  expect($('#content').value).toBe('text for my-page');
});

test('runOCR handles server error', async () => {
  const p = Proofer();
  p.init();
  window.location = new URL('https://ambuda.org/proofing/error');
  await p.runOCR();
  expect(mockEditor.setText).toHaveBeenCalledWith('(server error)');
});

// -- Image zoom --

test('increaseImageZoom multiplies by 1.2', () => {
  const p = Proofer();
  p.init();
  expect(p.imageZoom).toBe(0.5);
  p.increaseImageZoom();
  expect(p.imageZoom).toBeCloseTo(0.6);
});

test('decreaseImageZoom multiplies by 0.8', () => {
  const p = Proofer();
  p.init();
  p.decreaseImageZoom();
  expect(p.imageZoom).toBeCloseTo(0.4);
});

test('resetImageZoom restores home zoom', () => {
  const p = Proofer();
  p.init();
  p.imageZoom = 3;
  p.resetImageZoom();
  expect(p.imageZoom).toBe(0.5);
});

// -- Text zoom --

test('increaseTextSize adds 0.1', () => {
  const p = Proofer();
  p.init();
  p.increaseTextSize();
  expect(p.textZoom).toBeCloseTo(1.1);
  expect(mockEditor.setTextZoom).toHaveBeenCalledWith(expect.closeTo(1.1));
});

test('decreaseTextSize subtracts 0.1 with min 0.5', () => {
  const p = Proofer();
  p.init();
  p.decreaseTextSize();
  expect(p.textZoom).toBeCloseTo(0.9);

  // Verify floor
  p.textZoom = 0.5;
  p.decreaseTextSize();
  expect(p.textZoom).toBe(0.5);
});

test('resetTextSize resets to 1', () => {
  const p = Proofer();
  p.init();
  p.textZoom = 2;
  p.resetTextSize();
  expect(p.textZoom).toBe(1);
});

// -- Layout --

test('setLayout changes layout and saves', () => {
  const p = Proofer();
  p.init();
  p.displayImageOnLeft();
  expect(p.layout).toBe('image-left');

  const p2 = Proofer();
  p2.loadSettings();
  expect(p2.layout).toBe('image-left');
});

test('getLayoutClasses returns correct classes', () => {
  const p = Proofer();
  p.layout = 'image-left';
  expect(p.getLayoutClasses()).toBe('flex flex-row-reverse h-[90vh]');
  p.layout = 'image-right';
  expect(p.getLayoutClasses()).toBe('flex flex-row h-[90vh]');
  p.layout = 'image-top';
  expect(p.getLayoutClasses()).toBe('flex flex-col-reverse h-[90vh]');
  p.layout = 'image-bottom';
  expect(p.getLayoutClasses()).toBe('flex flex-col h-[90vh]');
  p.layout = 'unknown';
  expect(p.getLayoutClasses()).toBe('flex flex-row h-[90vh]');
});

// -- Revision colors --

test('getRevisionColorClass returns correct classes', () => {
  const p = Proofer();
  expect(p.getRevisionColorClass('reviewed-0')).toBe('bg-red-200 text-red-800');
  expect(p.getRevisionColorClass('reviewed-1')).toBe('bg-yellow-200 text-yellow-800');
  expect(p.getRevisionColorClass('reviewed-2')).toBe('bg-green-200 text-green-800');
  expect(p.getRevisionColorClass('skip')).toBe('bg-gray-200 text-gray-800');
  expect(p.getRevisionColorClass('unknown')).toBe('');
});

// -- Misc --

test('copyCharacter writes to clipboard', () => {
  const p = Proofer();
  p.copyCharacter({ target: { textContent: 'ऽ' } });
  expect(navigator.clipboard.writeText).toHaveBeenCalledWith('ऽ');
});
