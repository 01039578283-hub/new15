/* Local progressive-enhancement search: source links remain in the HTML. */
(() => {
  const normalize = (value) => value.normalize('NFKC').toLocaleLowerCase('ko-KR');
  document.querySelectorAll('[data-branch-search-root]').forEach((root) => {
    const input = root.querySelector('[data-branch-search-input]');
    const reset = root.querySelector('[data-branch-search-reset]');
    const status = root.querySelector('[data-branch-search-status]');
    const empty = root.querySelector('[data-branch-search-empty]');
    const results = root.querySelector('[data-branch-search-results]');
    const directory = root.dataset.searchMode === 'directory';
    const entries = Array.from(root.querySelectorAll('[data-branch-search]'), (card) => ({
      card,
      text: normalize(card.dataset.branchSearch).replace(/\s+/gu, ''),
    }));
    const groups = Array.from(root.querySelectorAll('[data-branch-search-group]'));
    const jumps = Array.from(root.querySelectorAll('[data-branch-search-jump]'));
    let composing = false;

    const update = () => {
      const tokens = normalize(input.value.trim()).split(/\s+/u).filter(Boolean);
      const active = tokens.length > 0;
      let matches = 0;
      entries.forEach(({ card, text }) => {
        const match = tokens.every((token) => text.includes(token));
        card.hidden = !match;
        if (match) matches += 1;
      });
      groups.forEach((group) => {
        group.hidden = !group.querySelector('[data-branch-search]:not([hidden])');
      });
      jumps.forEach((jump) => {
        const id = jump.getAttribute('href').slice(1);
        jump.hidden = groups.find((group) => group.id === id)?.hidden ?? false;
      });
      results.hidden = directory && (!active || matches === 0);
      empty.hidden = !active || matches !== 0;
      reset.disabled = input.value.length === 0;
      status.textContent = active
        ? `검색 결과 ${matches}개 지점 · 전체 ${entries.length}개`
        : directory
          ? `전국 ${entries.length}개 지점을 검색하거나 아래에서 지역을 선택하세요.`
          : `전체 ${entries.length}개 지점을 표시하고 있습니다.`;
    };
    const clear = () => {
      input.value = '';
      composing = false;
      update();
      input.focus();
    };
    input.addEventListener('compositionstart', () => { composing = true; });
    input.addEventListener('compositionend', () => { composing = false; update(); });
    input.addEventListener('input', (event) => {
      if (!composing && !event.isComposing) update();
    });
    input.addEventListener('search', update);
    input.addEventListener('keydown', (event) => {
      if (event.isComposing || composing) return;
      if (event.key === 'Escape') { event.preventDefault(); clear(); }
      if (event.key === 'Enter') event.preventDefault();
    });
    reset.addEventListener('click', clear);
    // Handles values restored by back/forward navigation without network requests.
    window.addEventListener('pageshow', update);
    update();
    root.querySelector('[data-branch-search-controls]').hidden = false;
  });
})();
