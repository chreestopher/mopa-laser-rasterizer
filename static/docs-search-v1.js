(() => {
  const searchIndex = JSON.parse(document.getElementById('docs_search_index').textContent);
  const input = document.getElementById('docs_search');
  const clearButton = document.getElementById('docs_search_clear');
  const results = document.getElementById('docs_search_results');
  let activeIndex = -1;

  const normalize = value => String(value || '').toLocaleLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
  const searchableIndex = searchIndex.map(item => ({
    ...item,
    normalizedTitle: normalize(item.title),
    normalizedSection: normalize(item.section),
    normalizedText: normalize(item.text),
  }));

  function appendHighlightedText(element, text, terms) {
    const pattern = terms
      .filter(Boolean)
      .sort((left, right) => right.length - left.length)
      .map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('|');
    if (!pattern) {
      element.textContent = text;
      return;
    }
    const matcher = new RegExp(`(${pattern})`, 'ig');
    String(text).split(matcher).forEach(part => {
      if (terms.some(term => normalize(part) === term)) {
        const mark = document.createElement('mark');
        mark.textContent = part;
        element.appendChild(mark);
      } else {
        element.appendChild(document.createTextNode(part));
      }
    });
  }

  function excerptFor(item, phrase, terms) {
    const source = String(item.text || '').replace(/\s+/g, ' ').trim();
    if (!source) return item.section;
    const normalizedSource = normalize(source);
    let matchPosition = normalizedSource.indexOf(phrase);
    if (matchPosition < 0) {
      matchPosition = terms.reduce((best, term) => {
        const position = normalizedSource.indexOf(term);
        return position >= 0 && (best < 0 || position < best) ? position : best;
      }, -1);
    }
    const excerptLength = 210;
    const start = Math.max(0, Math.min(matchPosition - 65, source.length - excerptLength));
    const beginning = start > 0 ? '…' : '';
    const ending = start + excerptLength < source.length ? '…' : '';
    return `${beginning}${source.slice(start, start + excerptLength).trim()}${ending}`;
  }

  function scoreItem(item, phrase, terms) {
    const combined = `${item.normalizedTitle} ${item.normalizedSection} ${item.normalizedText}`;
    if (!terms.every(term => combined.includes(term))) return 0;
    let score = 1;
    if (item.normalizedTitle === phrase) score += 220;
    else if (item.normalizedTitle.includes(phrase)) score += 120;
    if (item.normalizedSection === phrase) score += 170;
    else if (item.normalizedSection.includes(phrase)) score += 90;
    if (item.normalizedText.includes(phrase)) score += 35;
    terms.forEach(term => {
      if (item.normalizedTitle.includes(term)) score += 28;
      if (item.normalizedSection.includes(term)) score += 20;
      score += Math.min(5, item.normalizedText.split(term).length - 1) * 3;
    });
    if (item.section === 'Overview') score += 4;
    return score;
  }

  function setActiveResult(nextIndex) {
    const links = [...results.querySelectorAll('.docs-search-result')];
    if (!links.length) {
      activeIndex = -1;
      input.removeAttribute('aria-activedescendant');
      return;
    }
    activeIndex = Math.max(0, Math.min(nextIndex, links.length - 1));
    links.forEach((link, index) => link.classList.toggle('is-active', index === activeIndex));
    input.setAttribute('aria-activedescendant', links[activeIndex].id);
    links[activeIndex].scrollIntoView({block: 'nearest'});
  }

  function renderSearch() {
    const phrase = normalize(input.value).trim().replace(/\s+/g, ' ');
    const terms = [...new Set(phrase.split(' ').filter(term => term.length > 1))];
    results.replaceChildren();
    clearButton.hidden = !phrase;
    activeIndex = -1;
    input.removeAttribute('aria-activedescendant');
    if (!phrase || !terms.length) return;

    const matches = searchableIndex
      .map(item => ({item, score: scoreItem(item, phrase, terms)}))
      .filter(match => match.score > 0)
      .sort((left, right) => right.score - left.score || left.item.title.localeCompare(right.item.title))
      .slice(0, 10);

    if (!matches.length) {
      const empty = document.createElement('div');
      empty.className = 'docs-search-empty';
      empty.textContent = `No documentation matched “${input.value.trim()}”. Try fewer or more general words.`;
      results.appendChild(empty);
      return;
    }

    const summary = document.createElement('p');
    summary.className = 'docs-search-summary';
    summary.textContent = `${matches.length} best ${matches.length === 1 ? 'match' : 'matches'}`;
    results.appendChild(summary);

    matches.forEach(({item}, index) => {
      const link = document.createElement('a');
      link.id = `docs_search_result_${index}`;
      link.className = 'docs-search-result';
      link.href = item.url;
      const title = document.createElement('span');
      title.className = 'docs-search-result-title';
      appendHighlightedText(title, item.title, terms);
      const meta = document.createElement('span');
      meta.className = 'docs-search-result-meta';
      meta.textContent = `${item.group} · ${item.section}`;
      const excerpt = document.createElement('span');
      excerpt.className = 'docs-search-result-excerpt';
      appendHighlightedText(excerpt, excerptFor(item, phrase, terms), terms);
      link.append(title, meta, excerpt);
      link.addEventListener('mouseenter', () => setActiveResult(index));
      link.addEventListener('focus', () => setActiveResult(index));
      results.appendChild(link);
    });
  }

  input.addEventListener('input', renderSearch);
  input.addEventListener('keydown', event => {
    const links = [...results.querySelectorAll('.docs-search-result')];
    if (event.key === 'ArrowDown' && links.length) {
      event.preventDefault();
      setActiveResult(activeIndex < 0 ? 0 : activeIndex + 1);
    } else if (event.key === 'ArrowUp' && links.length) {
      event.preventDefault();
      setActiveResult(activeIndex < 0 ? links.length - 1 : activeIndex - 1);
    } else if (event.key === 'Enter' && activeIndex >= 0 && links[activeIndex]) {
      event.preventDefault();
      links[activeIndex].click();
    } else if (event.key === 'Escape') {
      input.value = '';
      renderSearch();
    }
  });
  clearButton.addEventListener('click', () => {
    input.value = '';
    renderSearch();
    input.focus();
  });
})();
