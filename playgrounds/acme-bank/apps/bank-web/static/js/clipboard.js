/* Copies a text to the clipboard, from inside the click that asked. Where the browser refuses the clipboard (a frame that is not allowed it, a page that is not
   secure), the text is selected in a field of its own and copied by selection. Says whether it worked. */
export async function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* the clipboard is not ours here: copy by selection */ }
  const field = document.createElement('textarea');
  field.value = text;
  field.setAttribute('readonly', '');
  field.style.position = 'fixed';
  field.style.opacity = '0';
  document.body.append(field);
  field.select();
  let done = false;
  try { done = document.execCommand('copy'); } catch { /* nothing more to try */ }
  field.remove();
  return done;
}
