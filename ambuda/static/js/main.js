/* globals Alpine, Sanscript */

import { $ } from './core.ts';
import Bharati from './bharati';
import Dictionary from './dictionary';
import HamburgerButton from './hamburger-button';
import HTMLPoller from './html-poller';
import Reader from './reader';
import Proofer from './proofer';
import PublishConfig from './publish-config';
import SortableList from './sortable-list';
import TextSearch from './library-search';
import Tutorial from './tutorial';

window.addEventListener('alpine:init', () => {
  Alpine.data('dictionary', Dictionary);
  Alpine.data('htmlPoller', HTMLPoller);
  Alpine.data('bharati', Bharati);
  Alpine.data('reader', Reader);
  Alpine.data('proofer', Proofer);
  Alpine.data('publishConfig', PublishConfig);
  Alpine.data('sortableList', SortableList);
  Alpine.data('textSearch', TextSearch);
  Alpine.data('tutorialProofer', Tutorial);
});

(() => {
  HamburgerButton.init();
})();
