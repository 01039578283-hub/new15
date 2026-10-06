(() => {
  'use strict';
  const library = document.querySelector('[data-edu-library]');
  if (library) {
    const search = library.querySelector('[data-search-input]');
    const stage = library.querySelector('[data-stage-input]');
    const subject = library.querySelector('[data-subject-input]');
    const cards = [...library.querySelectorAll('[data-edu-card]')];
    const buttons = [...library.querySelectorAll('button[data-category]')];
    const freshButton = library.querySelector('[data-new-only]');
    let freshOnly = Boolean(freshButton && location.hash === '#new-articles');
    let category = '';
    const update = () => {
      const words = search.value.trim().toLocaleLowerCase('ko').split(/\s+/).filter(Boolean);
      let count = 0;
      for (const card of cards) {
        const visible = words.every(w => card.dataset.search.toLocaleLowerCase('ko').includes(w)) &&
          (!stage.value || card.dataset.stage.split(',').includes(stage.value)) &&
          (!subject || !subject.value || card.dataset.subject === subject.value) &&
          (!category || card.dataset.category === category) &&
          (!freshOnly || card.dataset.edition === '20261006');
        card.hidden = !visible;
        count += Number(visible);
      }
      library.querySelector('[data-count]').textContent = `${count}개 / 전체 ${cards.length}개`;
      library.querySelector('[data-empty]').hidden = count !== 0;
      buttons.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.category === category)));
      if (freshButton) freshButton.setAttribute('aria-pressed', String(freshOnly));
    };
    const reset = () => { search.value = ''; stage.value = ''; if (subject) subject.value = ''; category = ''; freshOnly = false; update(); };
    library.querySelector('form').addEventListener('submit', e => { e.preventDefault(); update(); });
    search.addEventListener('input', update);
    stage.addEventListener('change', update);
    if (subject) subject.addEventListener('change', update);
    buttons.forEach(b => b.addEventListener('click', () => { category = b.dataset.category; update(); }));
    if (freshButton) freshButton.addEventListener('click', () => { freshOnly = !freshOnly; update(); });
    library.querySelectorAll('[data-reset]').forEach(b => b.addEventListener('click', reset));
    if (freshButton) window.addEventListener('hashchange', () => {
      if (location.hash === '#new-articles') { freshOnly = true; update(); }
    });
    if (freshButton) document.querySelectorAll('a[href="#new-articles"]').forEach(link => {
      link.addEventListener('click', () => { freshOnly = true; update(); });
    });
    update();
  }
  const picker = document.querySelector('[data-local-picker]');
  if (!picker) return;
  fetch('/assets/education/locations.json').then(r => { if (!r.ok) throw Error('locations'); return r.json(); }).then(data => {
    const branchSelect = picker.querySelector('[data-branch-select]');
    const localSelect = picker.querySelector('[data-local-select]');
    const branchLink = picker.querySelector('[data-branch-link]');
    const localLink = picker.querySelector('[data-local-link]');
    const status = picker.querySelector('[data-local-status]');
    const params = new URLSearchParams(location.search);
    const from = params.get('from') || '';
    let sourceBranch = data.subjects[from];
    if (!sourceBranch && from.startsWith('/지점안내/')) {
      const parts = from.split('/').filter(Boolean);
      if (parts.length >= 3) sourceBranch = '/' + parts.slice(0,3).join('/') + '/';
    }
    // Only current public branch/neighborhood paths in this allowlist become links.
    if (!data.branches[sourceBranch]) sourceBranch = '';
    if (sourceBranch) branchSelect.value = sourceBranch;
    const update = preferredLocal => {
      const key = branchSelect.value;
      const branch = data.branches[key];
      localSelect.replaceChildren(new Option('동네 안내 선택', ''));
      if (branch) branch.locals.forEach(l => localSelect.add(new Option(l.name,l.path)));
      localSelect.disabled = !branch || branch.locals.length === 0;
      if (branch && branch.locals.some(l => l.path === preferredLocal)) localSelect.value = preferredLocal;
      branchLink.href = branch ? key : '/지점안내/';
      branchLink.textContent = branch ? branch.name + ' 지점 안내 보기 →' : '가까운 지점 안내 보기 →';
      const selectedLocal = branch && branch.locals.find(l => l.path === localSelect.value);
      localLink.href = selectedLocal ? selectedLocal.path : '/과목별학원/';
      localLink.textContent = selectedLocal ? selectedLocal.name + ' 안내 보기 →' : '동네별 학원 안내 보기 →';
      status.textContent = branch ? branch.name + '의 실제 운영 학년·과목·일정은 지점 안내와 상담에서 확인하세요.' : '지점을 고르면 연결된 동네 안내도 선택할 수 있습니다.';
      const contextualFrom = selectedLocal ? selectedLocal.path : branch ? key : '';
      document.querySelectorAll('a[href]').forEach(a => {
        const href = a.getAttribute('href');
        if (a.closest('.site-header,.site-footer') || a.closest('.breadcrumb')) return;
        const next = new URL(href, location.origin);
        const pathname = decodeURIComponent(next.pathname);
        if (next.origin !== location.origin || (!pathname.startsWith('/교육정보/') && !pathname.startsWith('/학습커리큘럼/'))) return;
        if (contextualFrom) next.searchParams.set('from', contextualFrom); else next.searchParams.delete('from');
        a.href = next.pathname + next.search + next.hash;
      });
    };
    let preferred = '';
    if (sourceBranch) preferred = (data.branches[sourceBranch].locals.find(l => from.startsWith(l.path)) || {}).path || '';
    update(preferred);
    branchSelect.addEventListener('change', () => update(''));
    localSelect.addEventListener('change', () => update(localSelect.value));
  }).catch(() => {
    picker.querySelector('[data-local-status]').textContent = '지점·동네 목록을 불러오지 못했습니다. 아래 전체 안내 버튼에서 찾아보세요.';
  });
})();
