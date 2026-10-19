/* Sets the theme before the page paints, so a manual choice never flashes the other one. The choice is the browser's
   own to remember: where storage is refused, the page follows the system. */
(function () {
  try {
    var saved = localStorage.getItem('acme-bank.theme');
    if (saved === 'light' || saved === 'dark') document.documentElement.setAttribute('data-theme', saved);
  } catch (e) { /* no storage: the system decides */ }
}());
