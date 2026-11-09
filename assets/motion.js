'use strict';
(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const opening = document.getElementById('opening');
  const replay = document.getElementById('replay');
  if (!window.gsap || !window.ScrollTrigger) { opening.remove(); replay.hidden = true; return; }
  gsap.registerPlugin(ScrollTrigger);
  let intro, running = false;
  const mm = gsap.matchMedia();

  function playOpening(force = false) {
    if (reduced.matches || running) return;
    let seen = false;
    try { seen = sessionStorage.getItem('antou.opening.seen') === '1'; } catch {}
    if (!force && (seen || ['#studio', '#workbench'].includes(location.hash))) return;
    running = true; replay.disabled = true;
    opening.classList.add('running'); document.body.classList.add('motion-enabled');
    const letters = opening.querySelectorAll('.opening-word > span');
    const panels = opening.querySelectorAll('.opening-panel');
    const words = document.querySelectorAll('.hero-word');
    const count = {value: 0};
    intro?.kill();
    intro = gsap.timeline({defaults: {ease: 'power4.inOut'}, onComplete: () => {
      opening.classList.remove('running'); running = false; replay.disabled = false;
      try { sessionStorage.setItem('antou.opening.seen', '1'); } catch {}
      gsap.set('.hero-word, .hero-stage', {clearProps: 'willChange'});
      document.body.classList.remove('motion-enabled'); ScrollTrigger.refresh();
    }});
    intro.set(opening, {visibility: 'visible'})
      .set(panels, {yPercent: 0}).set('.opening-word', {clipPath: 'inset(0% 0% 0% 0%)'})
      .set('.opening-meta', {y: 0}).set('.opening-word sup', {scale: 1})
      .fromTo(letters, {yPercent: 130, rotate: 8, scaleX: .6, scaleY: 1.35}, {yPercent: 0, rotate: 0, scaleX: 1, scaleY: 1, duration: 1.25, stagger: .065, ease: 'expo.out'}, .12)
      .to(count, {value: 100, duration: 1.7, ease: 'power2.out', onUpdate: () => { document.getElementById('openingCount').textContent = String(Math.round(count.value)).padStart(3, '0') + ' / 100'; }}, 0)
      .to('.opening-word', {clipPath: 'inset(0% 0% 100% 0%)', duration: .75}, 1.72)
      .to('.opening-meta', {y: 100, duration: .65}, 1.72)
      .to(panels[0], {yPercent: -101, duration: 1.25}, 2.02)
      .to(panels[1], {yPercent: 101, duration: 1.25}, 2.02)
      .fromTo(words, {yPercent: 130, xPercent: -6, rotation: 5, scaleX: .72, scaleY: 1.25}, {yPercent: 0, xPercent: 0, rotation: 0, scaleX: 1, scaleY: 1, duration: 1.75, stagger: .22, ease: 'expo.out'}, 2.27)
      .fromTo('.hero-stage', {clipPath: 'inset(0% 50% 0% 50%)', y: 65, scale: 1.025}, {clipPath: 'inset(0% 0% 0% 0%)', y: 0, scale: 1, duration: 1.8, ease: 'power4.inOut'}, 2.5)
      .fromTo('.hero-side', {y: 55, clipPath: 'inset(100% 0% 0% 0%)'}, {y: 0, clipPath: 'inset(0% 0% 0% 0%)', duration: 1.3}, 2.85);
  }

  mm.add('(prefers-reduced-motion: no-preference)', () => {
    document.querySelectorAll('.reveal-title').forEach((title, index) => {
      const section = title.closest('section');
      const tl = gsap.timeline({scrollTrigger: {trigger: title, start: 'top 88%', once: true}});
      tl.fromTo(title.querySelectorAll('.line-mask > span'),
        {yPercent: 125, xPercent: index % 2 ? 12 : -12, rotation: 4, scaleX: .84},
        {yPercent: 0, xPercent: 0, rotation: 0, scaleX: 1, duration: 1.65, stagger: .18, ease: 'expo.out'});
      const cards = section.querySelectorAll('.stagger-item');
      if (cards.length) tl.fromTo(cards,
        {y: 145, rotation: 3, clipPath: 'inset(0% 0% 100% 0%)'},
        {y: 0, rotation: 0, clipPath: 'inset(0% 0% 0% 0%)', duration: 1.5, stagger: .18, ease: 'power4.out'}, .7);
      const bench = section.querySelector('.workbench');
      if (bench) tl.fromTo(bench, {y: 100, clipPath: 'inset(0% 0% 100% 0%)'}, {y: 0, clipPath: 'inset(0% 0% 0% 0%)', duration: 1.6, ease: 'power4.out'}, .7);
    });
    document.querySelectorAll('.card-image').forEach(image => {
      gsap.fromTo(image, {clipPath: 'inset(0% 0% 100% 0%)'}, {clipPath: 'inset(0% 0% 0% 0%)', duration: 1.65, ease: 'power4.inOut', scrollTrigger: {trigger: image, start: 'top 97%', once: true}});
    });
    document.querySelectorAll('[data-parallax]').forEach(image => {
      gsap.fromTo(image, {yPercent: -4}, {yPercent: 4, ease: 'none', scrollTrigger: {trigger: image.parentElement, start: 'top bottom', end: 'bottom top', scrub: 1.4}});
    });
    gsap.to('.asterisk', {rotation: 75, ease: 'none', scrollTrigger: {trigger: '.hero', start: 'top top', end: 'bottom top', scrub: 1.8}});
    playOpening();
    return () => { intro?.kill(); opening.classList.remove('running'); running = false; replay.disabled = false; document.body.classList.remove('motion-enabled'); gsap.set('.hero-word, .hero-stage, .hero-side', {clearProps: 'all'}); };
  });
  replay.onclick = () => { if (reduced.matches) return; window.scrollTo({top: 0, behavior: 'instant'}); playOpening(true); };
  const finishOpening = () => { if (running) intro.progress(1); };
  document.getElementById('skipOpening').onclick = finishOpening;
  document.querySelector('.skip-link').addEventListener('click', finishOpening);
  window.addEventListener('antou:focus', () => {
    finishOpening();
    gsap.killTweensOf('.workbench'); gsap.set('.workbench', {clearProps: 'all'});
    requestAnimationFrame(() => ScrollTrigger.refresh());
  });
  // Escape dismisses a decorative opening immediately; never trap navigation.
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && running) intro.progress(1); });
  if (reduced.matches) replay.hidden = true;
  reduced.addEventListener('change', () => { replay.hidden = reduced.matches; });
})();
