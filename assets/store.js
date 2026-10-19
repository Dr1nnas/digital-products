/* Persline store: client-side search, filters and sort (no dependencies). */
(function () {
  var form = document.getElementById('filters'), res = document.getElementById('results');
  if (!form || !res) return;
  var pre = res.getAttribute('data-pre') || '', cat = form.getAttribute('data-cat');
  var info = document.getElementById('result-info'), pager = document.getElementById('static-pager');
  var moreWrap = document.getElementById('more-wrap'), moreBtn = document.getElementById('more');
  var STEP = 24, shown = STEP, data = null, catNames = {}, list = [], loading = null;
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); };
  var money = function (x) { return '$' + Number(x).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ','); };
  function load() {
    if (loading) return loading;
    var url = pre + (cat ? 'data/c/' + cat + '.json' : 'data/catalog.json');
    loading = fetch(url).then(function (r) { return r.json(); }).then(function (j) {
      if (Array.isArray(j)) { data = j; } else { data = j.items; (j.cats || []).forEach(function (c) { catNames[c.s] = c.n; }); }
      data.forEach(function (it) { it._t = (it.n + ' ' + it.u + ' ' + it.g + ' ' + (catNames[it.c] || it.c)).toLowerCase(); });
      return data;
    });
    return loading;
  }
  function val(n) { var el = form.elements[n]; return el ? el.value.trim() : ''; }
  function card(it) {
    var price = it.t === 'p'
      ? '<span class="price"><b>' + money(it.p) + '</b>' + (it.x ? ' <s>' + money(it.x) + '</s>' : '') + '</span>'
      : '<span class="price"><s>' + money(it.p) + '</s> <b class="free">Free</b><span class="launch"> during launch</span></span>';
    var badge = it.t === 'p' ? '<span class="badge soon">Coming soon</span>' : '<span class="badge free">Free</span>';
    var img = it.i ? '<img src="' + pre + esc(it.i) + '" alt="" width="800" height="640" loading="lazy" decoding="async">' : '<div class="noimg"></div>';
    return '<article class="card"><a class="card-link" href="' + pre + 'p/' + esc(it.s) + '/"><div class="card-img">' + img + badge +
      '</div><div class="card-body"><p class="card-cat">' + esc(catNames[it.c] || it.c.replace(/-/g, ' ')) + '</p><h3>' + esc(it.n) +
      '</h3><p class="card-sum">' + esc(it.u) + '</p><div class="card-foot">' + price + '</div></div></a></article>';
  }
  function apply() {
    var q = val('q').toLowerCase().split(/\s+/).filter(Boolean), c = val('cat'), t = val('type');
    var mn = parseFloat(val('min')), mx = parseFloat(val('max')), s = val('sort') || 'new';
    list = data.filter(function (it) {
      if (c && it.c !== c) return false;
      if (t && it.t !== t) return false;
      if (!isNaN(mn) && it.p < mn) return false;
      if (!isNaN(mx) && it.p > mx) return false;
      for (var i = 0; i < q.length; i++) if (it._t.indexOf(q[i]) < 0) return false;
      return true;
    });
    var cmp = { pa: function (a, b) { return a.p - b.p; }, pd: function (a, b) { return b.p - a.p; },
      az: function (a, b) { return a.n.localeCompare(b.n); }, new: function (a, b) { return a.a < b.a ? 1 : a.a > b.a ? -1 : 0; } }[s];
    list.sort(cmp);
    shown = STEP; render();
    if (!cat && history.replaceState) {
      var p = new URLSearchParams();
      ['q', 'cat', 'type', 'min', 'max', 'sort'].forEach(function (k) { var v = val(k); if (v && !(k === 'sort' && v === 'new')) p.set(k, v); });
      history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p : ''));
    }
  }
  function render() {
    res.innerHTML = list.slice(0, shown).map(card).join('') || '<p class="empty">No products match. Try fewer filters.</p>';
    if (info) { info.hidden = false; info.textContent = list.length + ' product' + (list.length === 1 ? '' : 's') + (list.length > shown ? ' · showing ' + shown : ''); }
    if (pager) pager.hidden = true;
    if (moreWrap) moreWrap.hidden = list.length <= shown;
  }
  if (!moreWrap && cat) {  // category pages get their own "show more" when filtering
    moreWrap = document.createElement('nav'); moreWrap.className = 'pager'; moreWrap.hidden = true;
    moreWrap.innerHTML = '<button type="button" class="btn">Show more</button>'; res.parentNode.insertBefore(moreWrap, pager);
    moreBtn = moreWrap.firstChild;
  }
  if (moreBtn) moreBtn.addEventListener('click', function () { shown += STEP; render(); });
  var timer;
  function onChange() { clearTimeout(timer); timer = setTimeout(function () { load().then(apply); }, 120); }
  form.addEventListener('input', onChange); form.addEventListener('change', onChange);
  if (!cat) {  // search page: restore state from URL and render immediately
    var u = new URLSearchParams(location.search);
    ['q', 'cat', 'type', 'min', 'max', 'sort'].forEach(function (k) { if (u.get(k) && form.elements[k]) form.elements[k].value = u.get(k); });
    var hq = document.querySelector('.hsearch input'); if (hq && u.get('q')) hq.value = u.get('q');
    load().then(apply).catch(function () { info.textContent = 'Could not load the catalog. Please reload.'; });
  }
})();
