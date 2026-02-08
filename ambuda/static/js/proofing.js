/* globals Alpine */
import Proofer from './proofer';
import PublishConfig from './publish-config';
import Tutorial from './tutorial';

window.addEventListener('alpine:init', () => {
  Alpine.data('proofer', Proofer);
  Alpine.data('publishConfig', PublishConfig);
  Alpine.data('tutorialProofer', Tutorial);
});
