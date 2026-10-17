/* Preserve map imagery and attribution while removing external navigation. */
(()=>{'use strict';
 const root=document.querySelector('.root_daum_roughmap');if(!root)return;
 function clean(){
  root.querySelectorAll('.wrap_btn_roadview,.cont,.phone').forEach(n=>n.remove());
  root.querySelectorAll('a').forEach(a=>{
   for(const attr of ['href','target','onclick','title'])a.removeAttribute(attr);
   a.tabIndex=-1;
   a.querySelectorAll('img[alt]').forEach(img=>{if(/이동|새창/.test(img.alt))img.alt='Kakao 지도';});
  });
  const tiles=[...root.querySelectorAll('.map img')];
  if(tiles.some(img=>img.complete&&img.naturalWidth>0)&&!document.documentElement.dataset.mapReady){
   document.documentElement.dataset.mapReady='true';
   parent.postMessage({type:'wawa-kakao-ready',id:root.id.replace('daumRoughmapContainer','')},location.origin);
  }
 }
 let scheduled=false;
 const schedule=()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;clean();});};
 new MutationObserver(records=>{if(records.some(r=>r.addedNodes.length))schedule();}).observe(root,{subtree:true,childList:true});
 root.addEventListener('load',schedule,true);clean();
 for(const type of ['click','auxclick'])document.addEventListener(type,e=>{if(e.target.closest('a')){e.preventDefault();e.stopImmediatePropagation();}},true);
 document.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.closest('a')){e.preventDefault();e.stopImmediatePropagation();}},true);
 let width=document.documentElement.clientWidth;
 window.addEventListener('resize',()=>{
  const next=document.documentElement.clientWidth;if(next===width)return;width=next;
  if(window.wawaLocationMap?.jsMap){const center=window.wawaLocationMap.jsMap.getCenter();window.wawaLocationMap.jsMap.relayout();window.wawaLocationMap.jsMap.setCenter(center);}
 },{passive:true});
})();
