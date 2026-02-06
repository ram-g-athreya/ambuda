/* global Alpine, OpenSeadragon, TUTORIAL_INITIAL_CONTENT, TUTORIAL_IMAGE_URL, TUTORIAL_LESSON_ID */
/* Tutorial proofer — simplified from proofer.js */
// TODO: can this be joined with proofer.js? Maybe a simpler frontend?

import { $ } from './core.ts';
import ProofingEditor from './prosemirror-editor.ts';

export default () => ({
  editor: null,
  imageViewer: null,
  splitPercent: 50,

  // Feedback state
  showFeedback: false,
  isCorrect: false,
  feedbackMessage: '',

  init() {
    const editorElement = $('#prosemirror-editor');
    const initialContent = TUTORIAL_INITIAL_CONTENT || '';

    this.editor = new ProofingEditor(editorElement, initialContent, () => {
      // no-op on change — no save tracking needed
    }, false, 1, null);

    if (TUTORIAL_IMAGE_URL && typeof OpenSeadragon !== 'undefined') {
      this.imageViewer = OpenSeadragon({
        id: 'osd-image',
        tileSources: {
          type: 'image',
          url: TUTORIAL_IMAGE_URL,
          buildPyramid: false,
        },
        showZoomControl: false,
        showHomeControl: false,
        showRotationControl: false,
        showFullPageControl: false,
        gestureSettingsMouse: { flickEnabled: true },
        animationTime: 0.5,
        zoomPerClick: 1.1,
        maxZoomPixelRatio: 2.5,
      });
    }
  },

  async checkAnswer() {
    const content = Alpine.raw(this.editor).getText();

    try {
      const response = await fetch(`/proofing/tutorial/${TUTORIAL_LESSON_ID}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });

      const data = await response.json();
      this.isCorrect = data.correct;
      this.feedbackMessage = data.message;
      this.showFeedback = true;
    } catch (error) {
      this.isCorrect = false;
      this.feedbackMessage = 'Error checking answer. Please try again.';
      this.showFeedback = true;
    }
  },

  // Split pane resize (reused from proofer.js)
  startResize() {
    const container = this.$refs.splitContainer;

    const onMouseMove = (ev) => {
      const rect = container.getBoundingClientRect();
      let percent = ((ev.clientX - rect.left) / rect.width) * 100;
      if (Math.abs(percent - 50) < 2) percent = 50;
      this.splitPercent = Math.max(10, Math.min(90, percent));
    };

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  },

  resetSplit() {
    this.splitPercent = 50;
  },
});
