(() => {
  'use strict';
  const library = document.querySelector('.guide-library');
  if (library) {
    const input = library.querySelector('#guide-search');
    const grade = library.querySelector('#guide-grade');
    const reader = library.querySelector('#guide-reader');
    const buttons = [...library.querySelectorAll('[data-filter]')];
    const cards = [...library.querySelectorAll('.guide-card')];
    const groups = [...library.querySelectorAll('.guide-group')];
    const params = new URLSearchParams(location.search);
    let category = buttons.some(b => b.dataset.filter === params.get('category')) ? params.get('category') : '';
    input.value = params.get('q') || '';
    for (const [control, key] of [[grade, 'grade'], [reader, 'reader']]) {
      const value = params.get(key) || '';
      if ([...control.options].some(o => o.value === value)) control.value = value;
    }
    const normalize = s => s.normalize('NFKC').toLocaleLowerCase('ko-KR').trim();
    const update = () => {
      const words = normalize(input.value).split(/\s+/).filter(Boolean);
      let count = 0;
      for (const card of cards) {
        const text = normalize(card.dataset.search);
        card.hidden = !(!category || card.dataset.category === category) || !(!grade.value || card.dataset.grade.split(',').includes(grade.value)) || !(!reader.value || card.dataset.reader.split(',').includes(reader.value)) || !words.every(word => text.includes(word));
        if (!card.hidden) count++;
      }
      for (const group of groups) {
        const count = [...group.querySelectorAll('.guide-card')].filter(c => !c.hidden).length;
        group.hidden = count === 0;
        group.querySelector('.guide-group-head > span').textContent = `${count}개`;
      }
      for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.filter === category));
      library.querySelector('.guide-count').textContent = `검색 결과 ${count}개 / 전체 ${cards.length}개`;
      library.querySelector('.guide-empty').hidden = count !== 0;
      const next = new URL(location.href);
      for (const [key, value] of [['q', input.value.trim()], ['category', category], ['grade', grade.value], ['reader', reader.value]]) value ? next.searchParams.set(key, value) : next.searchParams.delete(key);
      if (location.protocol !== 'file:') history.replaceState(null, '', next);
    };
    input.addEventListener('input', update);
    grade.addEventListener('change', update);
    reader.addEventListener('change', update);
    library.querySelector('form').addEventListener('submit', e => e.preventDefault());
    for (const button of buttons) button.addEventListener('click', () => { category = button.dataset.filter; update(); });
    for (const button of library.querySelectorAll('[data-reset]')) button.addEventListener('click', () => { input.value = ''; grade.value = ''; reader.value = ''; category = ''; update(); });
    update();
  }
  for (const form of document.querySelectorAll('.guide-record')) {
    const fields = [...form.querySelectorAll('textarea')];
    const status = form.querySelector('.guide-save-status');
    const clearButton = form.querySelector('[data-clear]');
    let clearArmed = false;
    const disarmClear = () => { clearArmed = false; clearButton.textContent = '입력 비우기'; };
    const printValues = fields.map(field => { const value = document.createElement('div'); value.className = 'guide-print-value'; field.after(value); return value; });
    const sync = () => fields.forEach((field, i) => { printValues[i].textContent = field.value; });
    const download = () => {
      disarmClear();
      const lines = [form.dataset.title, '영수코칭 · 나의 학습 기록', '', ...fields.flatMap(field => [field.closest('label').querySelector('span').textContent, field.value.replace(/\r?\n/g, '\r\n'), ''])];
      const file = new Blob(['\uFEFF', lines.join('\r\n')], { type: 'text/plain;charset=utf-8' });
      const href = URL.createObjectURL(file); const anchor = document.createElement('a');
      anchor.href = href; anchor.download = `영수코칭-${form.dataset.slug}-학습기록.txt`; document.body.append(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(href), 10000);
      status.textContent = 'TXT 파일 저장을 요청했습니다. 브라우저의 다운로드에서 확인하세요.';
    };
    form.addEventListener('submit', e => e.preventDefault());
    form.addEventListener('input', () => { disarmClear(); sync(); });
    form.querySelector('[data-save]').addEventListener('click', download);
    form.querySelector('[data-print]').addEventListener('click', () => { sync(); window.print(); });
    clearButton.addEventListener('click', () => {
      if (fields.some(field => field.value) && !clearArmed) {
        clearArmed = true; clearButton.textContent = '한 번 더 눌러 비우기';
        status.textContent = '한 번 더 누르면 입력을 비웁니다. 필요한 기록은 먼저 TXT로 저장하세요.';
        return;
      }
      form.reset(); disarmClear(); sync(); status.textContent = '입력을 비웠습니다.';
    });
    window.addEventListener('beforeprint', sync);
    sync();
  }
})();
