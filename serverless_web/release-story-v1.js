(function(){
  const bar=document.getElementById('progress');
  const update=()=>{const h=document.documentElement.scrollHeight-innerHeight;bar.style.width=(h?scrollY/h*100:0)+'%';};
  addEventListener('scroll',update,{passive:true});update();
  const toc=document.querySelector('.toc');
  const headings=[...document.querySelectorAll('.article h2[id]')];
  headings.forEach((heading,index)=>{
    const link=document.createElement('a');
    link.href=`#${heading.id}`;
    link.dataset.target=heading.id;
    link.innerHTML=`<span class="toc-index">${String(index+1).padStart(2,'0')}</span><span>${heading.textContent}</span>`;
    toc.append(link);
  });
  const links=[...toc.querySelectorAll('a')];
  const obs=new IntersectionObserver(entries=>{
    const hit=entries.filter(e=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];
    if(!hit)return;
    links.forEach(a=>a.classList.toggle('active',a.dataset.target===hit.target.id));
  },{rootMargin:'-18% 0px -68% 0px',threshold:[0,.1,.25,.5]});
  links.forEach(a=>{const el=document.getElementById(a.dataset.target);if(el)obs.observe(el);});
  document.querySelectorAll('video').forEach(video=>{
    video.addEventListener('error',()=>{
      const frame=video.closest('[data-media]');
      const source=video.querySelector('source')?.src;
      if(!frame||!source||frame.querySelector('.video-fallback'))return;
      const fallback=document.createElement('p');
      fallback.className='video-fallback';
      fallback.innerHTML=`This browser could not play the embedded clip. <a href="${source}">Open or download the original video.</a>`;
      frame.append(fallback);
    });
  });
  document.querySelectorAll('.article .media-block').forEach(frame=>{
    const button=document.createElement('button');
    button.type='button';
    button.className='media-expand';
    button.textContent='Expand media';
    button.setAttribute('aria-expanded','false');
    button.addEventListener('click',()=>{
      const expanded=frame.classList.toggle('is-expanded');
      button.textContent=expanded?'Reduce media':'Expand media';
      button.setAttribute('aria-expanded',String(expanded));
      if(expanded)frame.scrollIntoView({behavior:'smooth',block:'nearest'});
    });
    frame.append(button);
  });
})();
