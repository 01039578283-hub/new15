const activeScript = document.currentScript;

// HTML 파일을 서버 없이 직접 열어도 내부 메뉴를 확인할 수 있게 합니다.
if (location.protocol === "file:" && activeScript?.src) {
  const siteRoot = new URL("../", activeScript.src);
  document.querySelectorAll('a[href^="/"]').forEach((link) => {
    const original = link.getAttribute("href");
    if (!original || original.startsWith("//")) return;
    let localPath = original.slice(1);
    if (!localPath || localPath.endsWith("/")) localPath += "index.html";
    link.href = new URL(localPath, siteRoot).href;
  });
}

document.documentElement.classList.add("motion-ready");

const header = document.querySelector(".site-header");
const updateHeader = () => header?.classList.toggle("is-scrolled", window.scrollY > 12);
updateHeader();
window.addEventListener("scroll", updateHeader, { passive: true });

const revealItems = document.querySelectorAll(".reveal");
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { rootMargin: "0px 0px -8%", threshold: 0.08 }
  );
  revealItems.forEach((item) => observer.observe(item));
} else {
  revealItems.forEach((item) => item.classList.add("is-visible"));
}

document.querySelectorAll(".faq-list details").forEach((item) => {
  item.addEventListener("toggle", () => {
    if (!item.open) return;
    document.querySelectorAll(".faq-list details[open]").forEach((openItem) => {
      if (openItem !== item) openItem.open = false;
    });
  });
});

document.querySelectorAll(".academy-directory").forEach((directory) => {
  const input = directory.querySelector(".academy-search-input");
  const groups = [...directory.querySelectorAll(".academy-region-group")];
  const links = [...directory.querySelectorAll(".academy-local-link")];
  const result = directory.querySelector(".academy-result-count");

  const update = () => {
    const keyword = (input?.value || "").trim().toLocaleLowerCase("ko-KR");
    let visibleCount = 0;
    groups.forEach((group) => {
      let regionCount = 0;
      group.querySelectorAll(".academy-city-group").forEach((city) => {
        let cityCount = 0;
        city.querySelectorAll(".academy-local-link").forEach((link) => {
          const searchable = `${link.dataset.locality || ""} ${city.dataset.city || ""} ${group.dataset.region || ""}`.toLocaleLowerCase("ko-KR");
          const visible = !keyword || searchable.includes(keyword);
          link.hidden = !visible;
          if (visible) cityCount += 1;
        });
        city.hidden = cityCount === 0;
        regionCount += cityCount;
      });
      group.hidden = regionCount === 0;
      if (keyword && regionCount) group.open = true;
      visibleCount += regionCount;
    });
    if (result) result.textContent = keyword ? `검색 결과 ${visibleCount}개` : `전체 ${links.length}개 동네`;
  };

  input?.addEventListener("input", update);
  directory.querySelector('[data-action="expand"]')?.addEventListener("click", () => groups.forEach((group) => { if (!group.hidden) group.open = true; }));
  directory.querySelector('[data-action="collapse"]')?.addEventListener("click", () => groups.forEach((group) => { group.open = false; }));
  update();
});
