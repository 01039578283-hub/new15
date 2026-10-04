(() => {
  'use strict';
  const root = document.querySelector('[data-teacher-search]');
  if (!root) return;
  const form = root.querySelector('form');
  const input = root.querySelector('input[type="search"]');
  const region = root.querySelector('select');
  const cards = [...root.querySelectorAll('[data-teacher-card]')];
  const count = root.querySelector('[data-teacher-count]');
  const empty = root.querySelector('[data-teacher-empty]');
  const normalize = text => text.normalize('NFKC').toLocaleLowerCase('ko-KR').replace(/\s+/g, ' ').trim();
  const params = new URLSearchParams(location.search);
  input.value = (params.get('q') || '').slice(0, 100);
  region.value = [...region.options].some(o => o.value === params.get('region')) ? params.get('region') : '';
  const apply = () => {
    const terms = normalize(input.value).split(' ').filter(Boolean);
    let shown = 0;
    cards.forEach(card => {
      const matches = (!region.value || card.dataset.region === region.value) && terms.every(term => normalize(card.dataset.search).includes(term));
      card.hidden = !matches;
      if (matches) shown++;
    });
    count.textContent = `지점 ${shown}개${shown !== cards.length ? ` / 전체 ${cards.length}개` : ''}`;
    empty.hidden = shown > 0;
    const next = new URL(location.href);
    input.value.trim() ? next.searchParams.set('q', input.value.trim()) : next.searchParams.delete('q');
    region.value ? next.searchParams.set('region', region.value) : next.searchParams.delete('region');
    history.replaceState(null, '', next);
  };
  form.addEventListener('submit', event => { event.preventDefault(); apply(); });
  input.addEventListener('input', apply);
  region.addEventListener('change', apply);
  root.querySelectorAll('[data-teacher-reset]').forEach(button => button.addEventListener('click', () => { input.value = ''; region.value = ''; apply(); input.focus(); }));
  apply();
})();
