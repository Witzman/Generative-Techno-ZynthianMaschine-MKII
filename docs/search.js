(function () {
  'use strict';

  var input  = document.getElementById('nav-search');
  if (!input) return;

  var panel  = document.getElementById('search-results');
  var list   = document.getElementById('search-results-list');
  var noRes  = document.getElementById('search-no-results');
  var tracks = document.querySelectorAll('#sidebar .track');

  var index      = null;
  var pending    = null;
  var focusIndex = -1;

  function loadIndex() {
    if (index)   return Promise.resolve();
    if (pending) return pending;
    pending = fetch('search-index.json')
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; pending = null; });
    return pending;
  }

  function escapeRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function highlight(text, words) {
    if (!words.length) return text;
    var re = new RegExp('(' + words.map(escapeRe).join('|') + ')', 'gi');
    return text.replace(re, '<mark>$1</mark>');
  }

  function excerpt(body, words) {
    var idx = -1;
    for (var i = 0; i < words.length; i++) {
      var p = body.toLowerCase().indexOf(words[i].toLowerCase());
      if (p !== -1) { idx = p; break; }
    }
    var start = Math.max(0, idx === -1 ? 0 : idx - 60);
    var end   = Math.min(body.length, start + 160);
    return (start > 0 ? '\u2026' : '') +
           highlight(body.slice(start, end), words) +
           (end < body.length ? '\u2026' : '');
  }

  function scoreItem(item, words) {
    var s  = 0;
    var tl = item.title.toLowerCase();
    var hl = item.headings.map(function (h) { return h.text; }).join(' ').toLowerCase();
    var bl = item.body.toLowerCase();
    words.forEach(function (w) {
      var wl = w.toLowerCase();
      if (tl.includes(wl)) s += 10;
      if (hl.includes(wl)) s +=  5;
      if (bl.includes(wl)) s +=  1;
    });
    return s;
  }

  function setFocus(idx) {
    var items = list.querySelectorAll('.search-result');
    if (focusIndex >= 0 && focusIndex < items.length)
      items[focusIndex].classList.remove('result-focused');
    focusIndex = Math.max(0, Math.min(idx, items.length - 1));
    if (items.length) {
      items[focusIndex].classList.add('result-focused');
      items[focusIndex].scrollIntoView({ block: 'nearest' });
    }
  }

  input.addEventListener('keydown', function (e) {
    var items = list.querySelectorAll('.search-result');
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setFocus(focusIndex < 0 ? 0 : focusIndex + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setFocus(focusIndex <= 0 ? 0 : focusIndex - 1);
    } else if (e.key === 'Enter' && focusIndex >= 0) {
      e.preventDefault();
      var link = items[focusIndex].querySelector('a');
      if (link) window.location.href = link.href;
    } else if (e.key === 'Escape') {
      input.value = '';
      showPanel(false);
    }
  });

  function showPanel(show) {
    panel.style.display = show ? '' : 'none';
    tracks.forEach(function (t) { t.style.display = show ? 'none' : ''; });
    if (!show) focusIndex = -1;
  }

  function renderResults(results, words) {
    list.innerHTML = '';
    focusIndex = -1;
    if (!results.length) { noRes.style.display = ''; return; }
    noRes.style.display = 'none';
    results.forEach(function (item) {
      var matchHeading = null;
      item.headings.forEach(function (h) {
        if (!matchHeading &&
            words.some(function (w) { return h.text.toLowerCase().includes(w.toLowerCase()); })) {
          matchHeading = h;
        }
      });
      var href = matchHeading ? item.url + '#' + matchHeading.id : item.url;
      var li   = document.createElement('li');
      li.className = 'search-result';
      li.innerHTML =
        '<a href="' + href + '">' +
        '<span class="result-title">'   + highlight(item.title, words) + '</span>' +
        (matchHeading
          ? '<span class="result-heading">\u00a7\u00a0' + highlight(matchHeading.text, words) + '</span>'
          : '') +
        '<span class="result-excerpt">' + excerpt(item.body, words) + '</span>' +
        '</a>';
      list.appendChild(li);
    });
  }

  input.addEventListener('input', function () {
    var q = input.value.trim();
    if (!q) { showPanel(false); return; }
    var words = q.split(/\s+/).filter(Boolean);
    loadIndex().then(function () {
      var results = index
        .map(function (item) { return { item: item, s: scoreItem(item, words) }; })
        .filter(function (r) { return r.s > 0; })
        .sort(function (a, b) { return b.s - a.s; })
        .slice(0, 12)
        .map(function (r) { return r.item; });
      renderResults(results, words);
      showPanel(true);
    });
  });
}());
