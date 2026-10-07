(() => {
  if (!('HTMLDialogElement' in window)) return;
  let dialog, image, viewport, sizeButton, originalLink, previous;
  const close = () => { dialog.close(); image.removeAttribute('src'); previous?.focus(); };
  const create = () => {
    dialog = document.createElement('dialog');
    dialog.className = 'image-zoom-dialog';
    dialog.setAttribute('aria-label', '안내 이미지 확대');
    dialog.innerHTML = '<div class="image-zoom-toolbar"><p>화면에 맞추거나 원본 크기로 확대해 글씨를 읽어보세요.</p><button type="button" data-size aria-pressed="false">원본 크기</button><a data-original target="_blank" rel="noopener">원본 새 창</a><button type="button" data-close>닫기</button></div><div class="image-zoom-scroll"><img alt=""></div>';
    document.body.append(dialog);
    image = dialog.querySelector('img'); viewport = dialog.querySelector('.image-zoom-scroll');
    sizeButton = dialog.querySelector('[data-size]'); originalLink = dialog.querySelector('[data-original]');
    dialog.querySelector('[data-close]').addEventListener('click', close);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    sizeButton.addEventListener('click', () => {
      const native = viewport.classList.toggle('is-native');
      sizeButton.setAttribute('aria-pressed', String(native));
      sizeButton.textContent = native ? '화면에 맞추기' : '원본 크기';
    });
  };
  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-readable-image]');
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (!dialog) create();
    previous = link;
    viewport.classList.remove('is-native'); sizeButton.setAttribute('aria-pressed', 'false'); sizeButton.textContent = '원본 크기';
    image.alt = link.querySelector('img')?.alt || '안내 이미지';
    originalLink.href = link.href; image.src = link.href;
    dialog.showModal(); viewport.scrollTop = 0; viewport.scrollLeft = 0;
    dialog.querySelector('[data-close]').focus();
  });
})();
