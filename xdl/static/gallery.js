

function _countFiles(u) {
  if (!_API_MODE) return u.files.length;
  return u.filesLoaded ? u.files.length : (u.count || 0);
}

function _mpath(u, f) {
  return _MEDIA_BASE
    ? (_MEDIA_BASE + '/' + encodeURIComponent(u.uid) + '/' + encodeURIComponent(f))
    : (encodeURIComponent(u.folder) + '/' + encodeURIComponent(f));
}

function _tpath(u, f) {
  return _THUMB_BASE + '/' + encodeURIComponent(u.uid) + '/' + encodeURIComponent(f);
}

function _fmtDate(ts) {
  var d = new Date(ts);
  return d.getFullYear() + '-'
    + String(d.getMonth()+1).padStart(2,'0') + '-'
    + String(d.getDate()).padStart(2,'0');
}

let currentUser = null;
let lbFiles = [];
let lbIdx = 0;
let _cardListScrollY = 0;

/* ── Favorites (收藏夹) — persisted in localStorage; synced to DB in serve mode ── */
var _FAV_KEY = 'xgallery_favorites_v1';
var _FAV_LAYOUT_KEY = 'xgallery_fav_layout';
var _favView = false;
var _favItems = [];
var _favLayout = (function () {
  try { return localStorage.getItem(_FAV_LAYOUT_KEY) === 'grouped' ? 'grouped' : 'flat'; }
  catch (e) { return 'flat'; }
})();

function _favLoad() {
  try { return JSON.parse(localStorage.getItem(_FAV_KEY)) || {}; }
  catch (e) { return {}; }
}
var _favCache = _favLoad();
function _favSave() {
  try { localStorage.setItem(_FAV_KEY, JSON.stringify(_favCache)); } catch (e) {}
  if (_API_MODE) {
    fetch('/api/favorites', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(_favCache),
    }).catch(function () {});
  }
}
/* On serve startup, load favorites from DB (server is source of truth). */
(function () {
  if (!_API_MODE) return;
  fetch('/api/favorites').then(function (r) { return r.json(); }).then(function (data) {
    if (data && typeof data === 'object') {
      _favCache = data;
      try { localStorage.setItem(_FAV_KEY, JSON.stringify(_favCache)); } catch (e) {}
      _updateFavBadge();
    }
  }).catch(function () {});
})();
function _favId(uid, f) { return (uid || '') + '\u0000' + f; }
function _isFav(uid, f) { return Object.prototype.hasOwnProperty.call(_favCache, _favId(uid, f)); }
function _favRecord(u, item) {
  return {
    uid: u.uid || '', folder: u.folder || '', screen: u.screen || '', display: u.display || '',
    f: item.f, t: item.t, ts: item.ts || 0, tid: item.tid || '', ht: item.ht ? 1 : 0
  };
}
function _favAdd(rec) { _favCache[_favId(rec.uid, rec.f)] = rec; _favSave(); _updateFavBadge(); }
function _favRemove(uid, f) { delete _favCache[_favId(uid, f)]; _favSave(); _updateFavBadge(); }
function _favList() {
  return Object.keys(_favCache).map(function (k) { return _favCache[k]; });
}
function _buildFavItems() {
  return _favList().map(function (rec) {
    var it = { f: rec.f, t: rec.t, ts: rec.ts, tid: rec.tid, ht: rec.ht };
    it._u = { uid: rec.uid, folder: rec.folder, screen: rec.screen, display: rec.display };
    return it;
  });
}
function _updateFavBadge() {
  var el = document.getElementById('fav-count');
  if (!el) return;
  var n = Object.keys(_favCache).length;
  el.textContent = n ? ' ' + n : '';
}
function _toggleFav(u, item, heartEl) {
  var on = _isFav(u.uid, item.f);
  if (on) _favRemove(u.uid, item.f);
  else _favAdd(_favRecord(u, item));
  if (heartEl) heartEl.classList.toggle('on', !on);
  if (_favView && on) {
    _favItems = _buildFavItems();
    if (_favItems.length === 0) { showFavorites(true); }
    else { _renderDetailGrid(); }
  }
  var lf = document.getElementById('lb-fav');
  if (lf && lbFiles[lbIdx] && lbFiles[lbIdx].f === item.f) {
    lf.classList.toggle('on', _isFav(u.uid, item.f));
  }
}

function setFavLayout(mode) {
  _favLayout = (mode === 'grouped') ? 'grouped' : 'flat';
  try { localStorage.setItem(_FAV_LAYOUT_KEY, _favLayout); } catch (e) {}
  document.querySelectorAll('#fav-layout .lt').forEach(function (b) {
    b.classList.toggle('active', b.dataset.fl === _favLayout);
  });
  if (_favView) _renderDetailGrid();
}

function _renderFavGrouped(files) {
  var groupsEl = document.getElementById('fav-groups');
  if (!groupsEl) return;
  groupsEl.innerHTML = '';
  var order = [];
  var map = {};
  files.forEach(function (it) {
    var uid = (it._u && it._u.uid) || '';
    if (!map[uid]) {
      map[uid] = { u: it._u || { uid: uid, display: '(未知用户)' }, items: [] };
      order.push(uid);
    }
    map[uid].items.push(it);
  });
  order.sort(function (a, b) {
    var da = map[a].u.display || map[a].u.screen || a;
    var db = map[b].u.display || map[b].u.screen || b;
    return String(da).localeCompare(String(db), 'zh');
  });
  lbFiles = [];
  order.forEach(function (uid) {
    var g = map[uid];
    var u = g.u;
    var head = document.createElement('div');
    head.className = 'fav-group-head';
    var nm = document.createElement('span');
    nm.className = 'fav-group-name';
    nm.textContent = u.display || u.screen || '(未知用户)';
    head.appendChild(nm);
    if (u.screen) {
      var hd = document.createElement('span');
      hd.className = 'fav-group-handle';
      hd.innerHTML = '<a href="https://x.com/' + encodeURIComponent(u.screen) +
        '" target="_blank" rel="noopener">@' + _hesc(u.screen) + '</a>';
      head.appendChild(hd);
    }
    var cnt = document.createElement('span');
    cnt.className = 'fav-group-count';
    cnt.textContent = g.items.length + ' 项';
    head.appendChild(cnt);
    groupsEl.appendChild(head);
    var grid = document.createElement('div');
    grid.className = 'media-grid';
    g.items.forEach(function (it) {
      var gi = lbFiles.length;
      lbFiles.push(it);
      grid.appendChild(_mgCreateItem(u, it, gi));
    });
    groupsEl.appendChild(grid);
  });
}

/* ── Page loading overlay ── */
function _showPageLoading(text) {
  var el = document.getElementById('page-loading');
  var txt = document.getElementById('pl-text');
  if (txt && text) txt.textContent = text;
  if (el) { el.classList.remove('fade-out'); el.style.display = 'flex'; }
}
function _hidePageLoading() {
  var el = document.getElementById('page-loading');
  if (!el) return;
  el.classList.add('fade-out');
  setTimeout(function() { el.style.display = 'none'; }, 380);
}

/* ── Context menu ── */
function _showCtxMenu(e, items) {
  e.preventDefault();
  e.stopPropagation();
  var menu = document.getElementById('ctx-menu');
  menu.innerHTML = '';
  items.forEach(function(item) {
    var li = document.createElement('li');
    if (item.danger) li.className = 'danger';
    li.textContent = item.label;
    li.onclick = function(ev) { ev.stopPropagation(); _hideCtxMenu(); item.action(); };
    menu.appendChild(li);
  });
  menu.style.display = 'block';
  var x = e.clientX, y = e.clientY;
  var mw = menu.offsetWidth, mh = menu.offsetHeight;
  if (x + mw > window.innerWidth) x = window.innerWidth - mw - 4;
  if (y + mh > window.innerHeight) y = window.innerHeight - mh - 4;
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
}
function _hideCtxMenu() {
  document.getElementById('ctx-menu').style.display = 'none';
}
document.addEventListener('click', _hideCtxMenu);
document.addEventListener('contextmenu', function(e) {
  if (!e.target.closest('#ctx-menu')) _hideCtxMenu();
});
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') _hideCtxMenu();
});

/* ── Toast (Dynamic Island) ── */
var _toastTimer = null;
var _toastCommit = null;

function _confirmDelete(onConfirm) {
  if (_toastTimer) {
    clearTimeout(_toastTimer); _toastTimer = null;
    if (_toastCommit) { _toastCommit(); _toastCommit = null; }
  }
  var toast = document.getElementById('toast');
  var box = document.getElementById('toast-box');
  var cardEl = document.getElementById('toast-card');
  var pillEl = document.getElementById('toast-pill');
  toast.classList.remove('toast-in');
  box.style.transition = 'none';
  box.style.height = ''; box.style.borderRadius = '20px';
  cardEl.style.opacity = '1'; cardEl.style.pointerEvents = ''; cardEl.style.display = 'flex';
  pillEl.style.display = 'none'; pillEl.style.opacity = '1';
  toast.style.transition = ''; toast.style.transform = ''; toast.style.opacity = '';
  void toast.offsetWidth;
  document.getElementById('toast-delete-btn').onclick = function() { onConfirm(); };
  document.getElementById('toast-cancel-btn').onclick = function() { _hideToast(); };
  toast.classList.add('toast-in');
}

function _toUndo(thumbHtml, label, msg, onUndo, onCommit) {
  document.getElementById('toast-thumb').innerHTML = thumbHtml;
  document.getElementById('toast-label').textContent = label;
  document.getElementById('toast-msg').textContent = msg;
  document.getElementById('toast-undo').onclick = function() {
    clearTimeout(_toastTimer); _toastTimer = null; _toastCommit = null;
    _hideToast(); onUndo();
  };
  var box = document.getElementById('toast-box');
  var cardEl = document.getElementById('toast-card');
  var pillEl = document.getElementById('toast-pill');
  var startH = box.offsetHeight;
  box.style.height = startH + 'px';
  cardEl.style.transition = 'opacity 0.12s ease-out';
  cardEl.style.opacity = '0';
  cardEl.style.pointerEvents = 'none';
  setTimeout(function() {
    pillEl.style.visibility = 'hidden'; pillEl.style.display = 'flex';
    var targetH = pillEl.offsetHeight;
    pillEl.style.display = 'none'; pillEl.style.visibility = '';
    cardEl.style.display = 'none';
    pillEl.style.display = 'flex'; pillEl.style.opacity = '0';
    box.style.transition = 'height 0.38s cubic-bezier(0.34,1.56,0.64,1), border-radius 0.3s ease';
    box.style.height = targetH + 'px';
    box.style.borderRadius = '28px';
    setTimeout(function() {
      pillEl.style.transition = 'opacity 0.18s ease-in';
      pillEl.style.opacity = '1';
    }, 180);
    var bar = document.getElementById('toast-bar');
    bar.style.transition = 'none'; bar.style.transform = 'scaleX(1)';
    requestAnimationFrame(function() {
      requestAnimationFrame(function() {
        bar.style.transition = 'transform 5s linear';
        bar.style.transform = 'scaleX(0)';
      });
    });
    _toastCommit = onCommit;
    _toastTimer = setTimeout(function() {
      _toastTimer = null; _toastCommit = null;
      _hideToast(); onCommit();
    }, 5000);
  }, 120);
}

function _hideToast() {
  if (_toastTimer) {
    clearTimeout(_toastTimer); _toastTimer = null;
    if (_toastCommit) { _toastCommit(); _toastCommit = null; }
  }
  var toast = document.getElementById('toast');
  toast.style.transition = 'transform 0.3s ease-in, opacity 0.25s ease-in';
  toast.style.transform = 'translateX(-50%) translateY(-80px) scale(0.85)';
  toast.style.opacity = '0';
  setTimeout(function() {
    toast.classList.remove('toast-in');
    toast.style.transition = ''; toast.style.transform = ''; toast.style.opacity = '';
  }, 300);
}

function _cardThumbsHtml(u) {
  return (u.files || u.preview || []).slice(0, 4).map(function(f) {
    if (_THUMB_BASE && f.ht) return '<img src="' + _tpath(u, f.f) + '" loading="lazy">';
    if (f.t === 'video') return '<video src="' + _mpath(u, f.f) + '" muted playsinline preload="metadata"></video>';
    return '<img src="' + _mpath(u, f.f) + '" loading="lazy">';
  }).join('');
}

function _thumbHtml(u, item) {
  if (!item) return '';
  var src = (_THUMB_BASE && item.ht) ? _tpath(u, item.f) : _mpath(u, item.f);
  if (item.t === 'image') return '<img src="' + src + '" loading="lazy">';
  if (_THUMB_BASE && item.ht) return '<img src="' + src + '" loading="lazy">';
  return '<video src="' + src + '" muted playsinline preload="metadata"></video>';
}

function _updateTopbarMeta() {
  document.getElementById('topbar-meta').textContent =
    _visibleUsers.length + ' 位用户 · ' +
    _visibleUsers.reduce(function(s,u){return s+_countFiles(u);},0) + ' 张媒体';
}

function _deleteUser(u) {
  var count = _countFiles(u);
  var thumbEl = document.getElementById('toast-card-thumb');
  var n = Math.min(count, 4);
  thumbEl.className = n === 1 ? 'single' : n === 3 ? 'three' : '';
  thumbEl.innerHTML = _cardThumbsHtml(u);
  document.getElementById('toast-card-body').innerHTML =
    '删除 <b style="color:#f2f2f7">@' + _hesc(u.screen || u.uid) + '</b> 及其全部 ' + count + ' 个媒体？';
  _confirmDelete(function() {
    var gi = USERS.indexOf(u), vi = _visibleUsers.indexOf(u);
    if (gi >= 0) USERS.splice(gi, 1);
    if (vi >= 0) _visibleUsers.splice(vi, 1);
    _vsCache = {}; _vs.start = -1; _vs.end = -1;
    _vsRefresh(); _updateTopbarMeta();
    _toUndo(
      _thumbHtml(u, (u.files || u.preview || [])[0]),
      '已删除用户',
      '@' + (u.screen || u.uid),
      function() {
        if (gi >= 0) USERS.splice(gi, 0, u);
        if (vi >= 0) _visibleUsers.splice(vi, 0, u);
        _vsCache = {}; _vs.start = -1; _vs.end = -1;
        _vsRefresh(); _updateTopbarMeta();
      },
      function() {
        fetch('/api/user/' + encodeURIComponent(u.uid), {method:'DELETE'})
          .catch(function() { alert('删除失败，请刷新页面'); });
      }
    );
  });
}

function _deleteMedia(u, item) {
  var thumbEl = document.getElementById('toast-card-thumb');
  thumbEl.className = 'single';
  thumbEl.innerHTML = _thumbHtml(u, item);
  document.getElementById('toast-card-body').textContent =
    '删除此' + (item.t === 'video' ? '视频' : '图片') + '？';
  _confirmDelete(function() {
    var i = u.files.indexOf(item);
    if (i >= 0) u.files.splice(i, 1);
    _renderDetailGrid();
    _toUndo(
      _thumbHtml(u, item),
      '已删除媒体',
      item.f,
      function() {
        if (i >= 0) u.files.splice(i, 0, item); else u.files.push(item);
        _renderDetailGrid();
      },
      function() {
        fetch('/api/media/' + encodeURIComponent(u.uid) + '/' + encodeURIComponent(item.f), {method:'DELETE'})
          .catch(function() { alert('删除失败，请刷新页面'); });
      }
    );
  });
}

function _exitSelMode() {
  if (!_selMode) return;
  _selMode = false;
  _selSet.clear();
  var btn = document.getElementById('sel-toggle');
  if (btn) { btn.textContent = '多选'; btn.classList.remove('active'); }
  document.getElementById('sel-bar').classList.remove('active');
  var grid = document.getElementById('media-grid');
  if (grid) {
    grid.classList.remove('sel-mode');
    _mgVS.cache.forEach(function(div) {
      div.classList.remove('sel-active');
      var ck = div.querySelector('.sel-check');
      if (ck) ck.textContent = '';
    });
  }
}

function toggleSelMode() {
  _selMode = !_selMode;
  _selSet.clear();
  var btn = document.getElementById('sel-toggle');
  btn.textContent = _selMode ? '取消' : '多选';
  btn.classList.toggle('active', _selMode);
  var grid = document.getElementById('media-grid');
  if (grid) {
    grid.classList.toggle('sel-mode', _selMode);
    _mgVS.cache.forEach(function(div) {
      div.classList.remove('sel-active');
      var ck = div.querySelector('.sel-check');
      if (ck) ck.textContent = '';
    });
  }
  _updateSelBar();
}

function _updateSelBar() {
  var n = _selSet.size;
  document.getElementById('sel-count').textContent = '已选 ' + n + ' 项';
  document.getElementById('sel-del-btn').disabled = n === 0;
  document.getElementById('sel-bar').classList.toggle('active', _selMode);
}

function _deleteSelected() {
  var n = _selSet.size;
  if (n === 0) return;
  var u = currentUser;
  var selItems = (u.files || []).filter(function(item) { return _selSet.has(item.f); });
  var thumbEl = document.getElementById('toast-card-thumb');
  var cnt = Math.min(n, 4);
  thumbEl.className = cnt === 1 ? 'single' : cnt === 3 ? 'three' : '';
  thumbEl.innerHTML = selItems.slice(0, 4).map(function(item) { return _thumbHtml(u, item); }).join('');
  document.getElementById('toast-card-body').innerHTML =
    '删除已选 <b style="color:#f2f2f7">' + n + '</b> 个媒体？';
  _confirmDelete(function() {
    var origFiles = (u.files || []).slice();
    u.files = (u.files || []).filter(function(item) { return !_selSet.has(item.f); });
    var firstItem = selItems[0];
    _exitSelMode();
    _renderDetailGrid();
    _toUndo(
      firstItem ? _thumbHtml(u, firstItem) : '',
      '已删除 ' + selItems.length + ' 个媒体',
      u.screen || u.uid,
      function() { u.files = origFiles; _renderDetailGrid(); },
      function() {
        selItems.forEach(function(item) {
          fetch('/api/media/' + encodeURIComponent(u.uid) + '/' + encodeURIComponent(item.f), {method:'DELETE'})
            .catch(function() {});
        });
      }
    );
  });
}
var _visibleUsers = USERS.slice();
var _userSort = 'name';
var _mediaFilter = 'all';
var _sortOrder = 'default';
var _selMode = false;
var _selSet = new Set();
var _userSelMode = false;
var _userSelSet = new Set();

function _buildVisibleUsers(q) {
  var base = q ? USERS.filter(function(u) {
    var s = (u.display + ' ' + u.screen + ' ' + u.uid).toLowerCase();
    return s.indexOf(q.toLowerCase()) >= 0;
  }) : USERS.slice();
  if (_userSort === 'count') {
    base.sort(function(a, b) { return b.count - a.count; });
  } else if (_userSort === 'recent') {
    base.sort(function(a, b) { return (b.latest || '').localeCompare(a.latest || ''); });
  }
  return base;
}

function setUserSort(s) {
  _userSort = s;
  document.querySelectorAll('#ust-wrap .st').forEach(function(b) {
    b.classList.toggle('active', b.id === 'ust-' + s);
  });
  onSearch(document.getElementById('search-input').value || '');
}

function setSort(s) {
  _sortOrder = s;
  document.querySelectorAll('[data-s]').forEach(function(b) { b.classList.toggle('active', b.dataset.s === s); });
  _renderDetailGrid();
}

function _applySortFilter(files) {
  var out = _mediaFilter === 'all' ? files.slice() : files.filter(function(item) { return item.t === _mediaFilter; });
  if (_sortOrder !== 'default') {
    out.sort(function(a, b) {
      var ta = a.ts || 0, tb = b.ts || 0;
      return _sortOrder === 'desc' ? tb - ta : ta - tb;
    });
  }
  return out;
}

function _exitUserSelMode() {
  if (!_userSelMode) return;
  _userSelMode = false;
  _userSelSet.clear();
  Object.keys(_vsCache).forEach(function(k) {
    var c = _vsCache[k];
    c.classList.remove('card-selected');
    var ck = c.querySelector('.card-sel-check');
    if (ck) ck.textContent = '';
  });
  var btn = document.getElementById('user-sel-toggle');
  if (btn) { btn.textContent = '多选'; btn.classList.remove('active'); }
  document.getElementById('sel-bar').classList.remove('active');
  document.getElementById('view-cards').classList.remove('user-sel-mode');
}

function toggleUserSelMode() {
  _userSelMode = !_userSelMode;
  _userSelSet.clear();
  Object.keys(_vsCache).forEach(function(k) {
    var c = _vsCache[k];
    c.classList.remove('card-selected');
    var ck = c.querySelector('.card-sel-check');
    if (ck) ck.textContent = '';
  });
  var btn = document.getElementById('user-sel-toggle');
  btn.textContent = _userSelMode ? '取消' : '多选';
  btn.classList.toggle('active', _userSelMode);
  document.getElementById('view-cards').classList.toggle('user-sel-mode', _userSelMode);
  _updateUserSelBar();
}

function _updateUserSelBar() {
  var n = _userSelSet.size;
  document.getElementById('sel-count').textContent = '已选 ' + n + ' 位用户';
  document.getElementById('sel-del-btn').disabled = n === 0;
  document.getElementById('sel-bar').classList.toggle('active', _userSelMode);
}

function _deleteSelectedUsers() {
  var n = _userSelSet.size;
  if (n === 0) return;
  var selUsers = _visibleUsers.filter(function(u) { return _userSelSet.has(u.uid); });
  var thumbEl = document.getElementById('toast-card-thumb');
  var cnt = Math.min(n, 4);
  thumbEl.className = cnt === 1 ? 'single' : cnt === 3 ? 'three' : '';
  thumbEl.innerHTML = selUsers.slice(0, 4).map(function(u) {
    var f = u.files && u.files[0];
    return f ? _thumbHtml(u, f) : '<div style="background:#2c2c2e;width:100%;height:100%"></div>';
  }).join('');
  document.getElementById('toast-card-body').innerHTML =
    '删除已选 <b style="color:#f2f2f7">' + n + '</b> 位用户（含全部媒体）？';
  _confirmDelete(function() {
    selUsers.forEach(function(u) {
      var gi = USERS.indexOf(u);
      if (gi >= 0) USERS.splice(gi, 1);
    });
    _exitUserSelMode();
    _vsCache = {};
    _visibleUsers = _buildVisibleUsers(document.getElementById('search-input').value || '');
    _vs.start = -1; _vs.end = -1;
    _vsRefresh();
    var firstUser = selUsers[0];
    var firstThumb = firstUser && firstUser.files && firstUser.files[0] ? _thumbHtml(firstUser, firstUser.files[0]) : '';
    _toUndo(
      firstThumb,
      '已删除 ' + selUsers.length + ' 位用户',
      selUsers.map(function(u) { return u.screen || u.uid; }).join(', '),
      function() {
        selUsers.forEach(function(u) { USERS.push(u); });
        _vsCache = {};
        _visibleUsers = _buildVisibleUsers(document.getElementById('search-input').value || '');
        _vs.start = -1; _vs.end = -1;
        _vsRefresh();
      },
      function() {
        selUsers.forEach(function(u) {
          fetch('/api/user/' + encodeURIComponent(u.uid), {method:'DELETE'})
            .catch(function() {});
        });
      }
    );
  });
}

function deleteSelectedDispatch() {
  if (_userSelMode) _deleteSelectedUsers();
  else _deleteSelected();
}

function _configFilterTabs(files) {
  var total = files.length;
  var imgCount = files.filter(function(f){return f.t==='image';}).length;
  var vidCount = files.filter(function(f){return f.t==='video';}).length;
  document.querySelector('[data-f="all"]').textContent = '全部 ' + total;
  document.querySelector('[data-f="image"]').textContent = '图片 ' + imgCount;
  document.querySelector('[data-f="video"]').textContent = '视频 ' + vidCount;
  document.querySelector('[data-f="image"]').style.display = imgCount ? '' : 'none';
  document.querySelector('[data-f="video"]').style.display = vidCount ? '' : 'none';
  var hasDates = files.some(function(f) { return f.ts; });
  document.querySelectorAll('.st,.sort-divider').forEach(function(el) {
    el.style.display = hasDates ? '' : 'none';
  });
  var flWrap = document.getElementById('fav-layout');
  var flDiv = document.getElementById('fav-layout-div');
  if (flWrap) flWrap.style.display = _favView ? 'inline-flex' : 'none';
  if (flDiv) flDiv.style.display = _favView ? '' : 'none';
  if (_favView) {
    document.querySelectorAll('#fav-layout .lt').forEach(function (b) {
      b.classList.toggle('active', b.dataset.fl === _favLayout);
    });
  }
  document.getElementById('filter-tabs').style.display = '';
}

function showFavorites(noHistory) {
  _exitSelMode();
  _exitUserSelMode();
  if (!_favView) _cardListScrollY = window.scrollY;
  _favView = true;
  currentUser = null;
  _favItems = _buildFavItems();
  if (!noHistory) {
    history.pushState({view:'fav'}, '', '#favorites');
  }
  if (window._mediaObs) { window._mediaObs.disconnect(); window._mediaObs = null; }
  document.getElementById('view-cards').style.display = 'none';
  document.getElementById('view-detail').style.display = 'block';
  document.getElementById('back-btn').style.display = 'flex';
  document.getElementById('search-input').style.display = 'none';
  document.getElementById('ust-wrap').style.display = 'none';
  document.getElementById('topbar-title').textContent = '❤️ 收藏夹';
  document.getElementById('detail-name').textContent = '收藏夹';
  document.getElementById('detail-meta').innerHTML = '共 ' + _favItems.length + ' 项收藏';
  _mediaFilter = 'all';
  _sortOrder = 'default';
  document.querySelectorAll('.ft').forEach(function(b) { b.classList.toggle('active', b.dataset.f === 'all'); });
  document.querySelectorAll('.st').forEach(function(b) { b.classList.toggle('active', b.dataset.s === 'default'); });
  // 多选 in the favorites view would mean "bulk delete media" — not meaningful
  // for a cross-user favorites collection, so hide it.
  var stog = document.getElementById('sel-toggle');
  if (stog) stog.style.display = 'none';
  window.scrollTo(0, 0);
  if (_favItems.length === 0) {
    document.getElementById('filter-tabs').style.display = 'none';
    document.getElementById('topbar-meta').textContent = '0 张媒体';
    var fg0 = document.getElementById('fav-groups');
    if (fg0) { fg0.style.display = 'none'; fg0.innerHTML = ''; }
    var grid = document.getElementById('media-grid');
    grid.style.display = '';
    grid.style.paddingTop = ''; grid.style.paddingBottom = '';
    grid.innerHTML =
      '<div style="grid-column:1/-1;padding:80px 20px;text-align:center;color:#71767b;font-size:15px">' +
      '还没有收藏任何媒体<br><span style="font-size:13px">把鼠标移到图片上，点左上角的 ♥ 即可收藏</span></div>';
    _mgVS.items = []; _mgVS.rows = 0; _mgVS.start = -1; _mgVS.end = -1;
    return;
  }
  _configFilterTabs(_favItems);
  _renderDetailGrid();
}

function showUser(idx, noHistory) {
  _exitSelMode();
  _exitUserSelMode();
  _favView = false;
  var _fg = document.getElementById('fav-groups');
  if (_fg) { _fg.style.display = 'none'; _fg.innerHTML = ''; }
  var _mg0 = document.getElementById('media-grid');
  if (_mg0) _mg0.style.display = '';
  _cardListScrollY = window.scrollY;
  currentUser = _visibleUsers[idx];
  const u = currentUser;
  if (!noHistory) {
    history.pushState({view:'user',uid:u.uid}, '', '#user-' + encodeURIComponent(u.uid));
  }
  document.getElementById('view-cards').style.display = 'none';
  document.getElementById('view-detail').style.display = 'block';
  document.getElementById('back-btn').style.display = 'flex';
  document.getElementById('search-input').style.display = 'none';
  document.getElementById('ust-wrap').style.display = 'none';
  document.getElementById('topbar-title').textContent = u.display + (u.screen ? ' @' + u.screen : '');
  document.getElementById('detail-name').textContent = u.display;
  if (window._mediaObs) { window._mediaObs.disconnect(); window._mediaObs = null; }
  _mediaFilter = 'all';
  _sortOrder = 'default';
  document.querySelectorAll('.ft').forEach(function(b) { b.classList.toggle('active', b.dataset.f === 'all'); });
  document.querySelectorAll('.st').forEach(function(b) { b.classList.toggle('active', b.dataset.s === 'default'); });

  function _renderWithFiles() {
    var total = u.files.length;
    document.getElementById('topbar-meta').textContent = total + ' 张媒体';
    document.getElementById('detail-meta').innerHTML =
      (u.screen ? '<a class="handle-link" href="https://x.com/' + encodeURIComponent(u.screen) + '" target="_blank" rel="noopener">@' + _hesc(u.screen) + '</a>' : '')
      + (u.uid ? ' · ID：' + _hesc(u.uid) : '') + ' · ' + total + ' 张';
    var stog = document.getElementById('sel-toggle');
    if (stog) stog.style.display = '';
    _configFilterTabs(u.files);
    window.scrollTo(0, 0);
    _renderDetailGrid();
  }

  if (_API_MODE && !u.filesLoaded) {
    var cnt = u.count || '…';
    document.getElementById('topbar-meta').textContent = cnt + ' 张媒体';
    document.getElementById('detail-meta').innerHTML =
      (u.screen ? '<a class="handle-link" href="https://x.com/' + encodeURIComponent(u.screen) + '" target="_blank" rel="noopener">@' + _hesc(u.screen) + '</a>' : '')
      + (u.uid ? ' · ID：' + _hesc(u.uid) : '') + ' · ' + cnt + ' 张';
    document.getElementById('filter-tabs').style.display = 'none';
    document.getElementById('media-grid').innerHTML = '';
    if (!u._fetching) {
      u._fetching = true;
      _showPageLoading('@' + (u.screen || u.uid) + ' 的媒体加载中…');
      fetch('/api/media/' + encodeURIComponent(u.uid))
        .then(function(r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function(files) {
          u.files = files;
          u.filesLoaded = true;
          u._fetching = false;
          _hidePageLoading();
          if (currentUser === u) _renderWithFiles();
        })
        .catch(function() {
          u._fetching = false;
          _hidePageLoading();
          if (currentUser === u) {
            document.getElementById('media-grid').innerHTML =
              '<div style="padding:60px;text-align:center;color:#f4212e;font-size:15px">' +
              '加载失败，<a href="javascript:void(0)" onclick="showUser(' + idx + ',true)" style="color:#0a84ff">重试</a></div>';
          }
        });
    }
  } else {
    _renderWithFiles();
  }
}

function showCards(noHistory) {
  _exitSelMode();
  _favView = false;
  var _fg = document.getElementById('fav-groups');
  if (_fg) { _fg.style.display = 'none'; _fg.innerHTML = ''; }
  var _mg0 = document.getElementById('media-grid');
  if (_mg0) _mg0.style.display = '';
  document.getElementById('view-detail').style.display = 'none';
  document.getElementById('view-cards').style.display = 'block';
  document.getElementById('back-btn').style.display = 'none';
  document.getElementById('search-input').style.display = '';
  document.getElementById('ust-wrap').style.display = 'flex';
  document.getElementById('topbar-title').textContent = 'X Gallery';
  // Re-apply whatever is still in the search box to keep filter in sync
  onSearch(document.getElementById('search-input').value || '');
  requestAnimationFrame(function() {
    window.scrollTo(0, _cardListScrollY);
    _vsUpdate();
  });
}

function lbOpen(idx) {
  _lbResetZoom();
  lbIdx = idx;
  lbRender();
  document.getElementById('lightbox').classList.add('active');
  document.body.style.overflow = 'hidden';
}

function lbClose() {
  _lbResetZoom();
  document.getElementById('lightbox').classList.remove('active');
  document.body.style.overflow = '';
  const vid = document.getElementById('lb-media');
  if (vid.tagName === 'VIDEO') { vid.pause(); }
}

function lbNav(dir) {
  lbIdx = (lbIdx + dir + lbFiles.length) % lbFiles.length;
  lbRender();
}

function lbRender() {
  _lbResetZoom();
  const item = lbFiles[lbIdx];
  const ou = item._u || currentUser;
  const path = _mpath(ou, item.f);
  let el = document.getElementById('lb-media');

  if (item.t === 'video') {
    if (el.tagName !== 'VIDEO') {
      const v = document.createElement('video');
      v.id = 'lb-media';
      v.setAttribute('controls', ''); v.setAttribute('autoplay', ''); v.setAttribute('loop', ''); v.setAttribute('muted', '');
      v.className = 'lb-video';
      el.replaceWith(v); el = v;
    }
    el.src = path;
    el.load();
    el.play().catch(function(){});
  } else {
    if (el.tagName !== 'IMG') {
      const img = document.createElement('img');
      img.id = 'lb-media'; img.alt = item.f;
      el.replaceWith(img); el = img;
    }
    el.src = path; el.alt = item.f;
  }
  _lbAttachZoom(el);
  document.getElementById('lb-counter').textContent = (lbIdx + 1) + ' / ' + lbFiles.length;
  var tlink = document.getElementById('lb-tweet');
  if (tlink) {
    if (item.tid) { tlink.href = 'https://x.com/i/web/status/' + item.tid; tlink.style.display = 'inline-block'; }
    else { tlink.style.display = 'none'; }
  }
  var fav = document.getElementById('lb-fav');
  if (fav) fav.classList.toggle('on', ou ? _isFav(ou.uid, item.f) : false);
}

function lbToggleFav() {
  var item = lbFiles[lbIdx];
  if (!item) return;
  var ou = item._u || currentUser;
  if (!ou) return;
  _toggleFav(ou, item, null);
  var fav = document.getElementById('lb-fav');
  if (fav) fav.classList.toggle('on', _isFav(ou.uid, item.f));
  // Sync thumbnail heart in the virtual-scroll cache (if rendered)
  var cached = _mgVS.cache.get(lbIdx);
  if (cached) {
    var h = cached.querySelector('.fav-heart');
    if (h) h.classList.toggle('on', _isFav(ou.uid, item.f));
  }
}

// ── Lightbox zoom / pan ─────────────────────────────────────────────────
var _lbScale = 1;
var _lbDrag = {on:false, moved:false, sx:0, sy:0, tx:0, ty:0};

function _lbApplyTransform(el) {
  el.style.transform = 'translate(' + _lbDrag.tx + 'px,' + _lbDrag.ty + 'px) scale(' + _lbScale + ')';
  el.style.cursor = _lbScale > 1 ? (_lbDrag.on ? 'grabbing' : 'grab') : 'default';
}

function _lbResetZoom() {
  _lbScale = 1;
  _lbDrag = {on:false, moved:false, sx:0, sy:0, tx:0, ty:0};
  var el = document.getElementById('lb-media');
  if (el && el.tagName === 'IMG') {
    el.style.transform = '';
    el.style.cursor = 'default';
    el.style.maxWidth = '';
    el.style.maxHeight = '';
  }
}

function _lbAttachZoom(el) {
  if (el.tagName !== 'IMG') {
    el.onclick = function(e) { e.stopPropagation(); };
    return;
  }
  el.onclick = function(e) { e.stopPropagation(); };

  el.onwheel = function(e) {
    e.preventDefault();
    e.stopPropagation();
    var factor = (e.deltaY || e.deltaX || 0) < 0 ? 1.12 : 1 / 1.12;
    var newScale = Math.min(10, Math.max(1, _lbScale * factor));
    if (newScale === _lbScale) return;
    if (newScale === 1) {
      // snap back to origin
      _lbScale = 1;
      _lbDrag.tx = 0; _lbDrag.ty = 0;
      el.style.transition = 'transform .15s ease';
      el.style.maxWidth = ''; el.style.maxHeight = '';
      _lbApplyTransform(el);
      return;
    }
    // zoom-to-cursor: keep the point under the mouse fixed
    var cx = window.innerWidth / 2, cy = window.innerHeight / 2;
    var ratio = newScale / _lbScale;
    _lbDrag.tx = _lbDrag.tx * ratio + (e.clientX - cx) * (1 - ratio);
    _lbDrag.ty = _lbDrag.ty * ratio + (e.clientY - cy) * (1 - ratio);
    _lbScale = newScale;
    el.style.transition = 'none';
    el.style.maxWidth = 'none'; el.style.maxHeight = 'none';
    _lbApplyTransform(el);
  };

  el.onpointerdown = function(e) {
    if (e.button !== 0) return;
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    _lbDrag.on = true;
    _lbDrag.moved = false;
    _lbDrag.sx = e.clientX - _lbDrag.tx;
    _lbDrag.sy = e.clientY - _lbDrag.ty;
    el.style.cursor = _lbScale > 1 ? 'grabbing' : 'default';
  };
  el.onpointermove = function(e) {
    if (!_lbDrag.on) return;
    var nx = e.clientX - _lbDrag.sx;
    var ny = e.clientY - _lbDrag.sy;
    if (Math.abs(nx - _lbDrag.tx) > 3 || Math.abs(ny - _lbDrag.ty) > 3) _lbDrag.moved = true;
    _lbDrag.tx = nx; _lbDrag.ty = ny;
    el.style.transition = 'none';
    _lbApplyTransform(el);
  };
  el.onpointerup = function(e) {
    if (!_lbDrag.on) return;
    _lbDrag.on = false;
    _lbApplyTransform(el);
  };
}

document.addEventListener('keydown', function(e) {
  const lb = document.getElementById('lightbox');
  if (!lb.classList.contains('active')) return;
  if (e.key === 'ArrowLeft') lbNav(-1);
  else if (e.key === 'ArrowRight') lbNav(1);
  else if (e.key === 'Escape') lbClose();
});

// Prevent page scroll while lightbox is open (non-image wheel is handled here)
document.getElementById('lightbox').addEventListener('wheel', function(e) {
  if (document.getElementById('lightbox').classList.contains('active')) e.preventDefault();
}, {passive: false});

// ── Virtual scroll (card list) ──────────────────────────────────────────
var _vs = {rowH: 320, perRow: 1, start: -1, end: -1, calibrated: false};
var _vsWrap = null, _vsGrid = null;
var _vsCache = {};
var _vsRafPending = false;

// Lazy thumbnail loader: only populate card-thumbs when card enters viewport
var _vsThumbObs = new IntersectionObserver(function(entries) {
  entries.forEach(function(entry) {
    if (!entry.isIntersecting || entry.target._vsLoaded) return;
    entry.target._vsLoaded = true;
    _vsThumbObs.unobserve(entry.target);
    var u = entry.target._vsUser;
    var thumbItems = u.filesLoaded ? u.files : (u.preview || u.files || []);
    thumbItems.slice(0, 6).forEach(function(item) {
      var path = _mpath(u, item.f);
      if (item.t === 'video' && item.ht && _THUMB_BASE) {
        var img = document.createElement('img');
        img.src = _tpath(u, item.f); img.alt = item.f;
        img.className = 'thumb-img'; entry.target.appendChild(img);
      } else if (item.t === 'video') {
        var v = document.createElement('video');
        v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); v.setAttribute('preload', 'metadata');
        v.src = path; v.className = 'thumb-video'; entry.target.appendChild(v);
      }else {
        var img = document.createElement('img');
        img.src = path; img.alt = item.f;
        img.className = 'thumb-img'; entry.target.appendChild(img);
      }
    });
  });
}, {rootMargin: '400px'});

function _vsInit() {
  var host = document.getElementById('vs-host');
  _vsWrap = document.createElement('div');
  _vsWrap.style.cssText = 'position:relative;width:100%';
  _vsGrid = document.createElement('div');
  _vsGrid.className = 'cards-grid';
  _vsGrid.style.cssText = 'position:absolute;left:0;right:0';
  _vsWrap.appendChild(_vsGrid);
  host.appendChild(_vsWrap);
  window.addEventListener('scroll', _vsOnScroll, {passive:true});
  window.addEventListener('resize', _vsOnResize, {passive:true});
  // Defer to after browser layout so offsetWidth is correct
  requestAnimationFrame(_vsRefresh);
}

function _vsOnScroll() {
  if (_vsRafPending) return;
  _vsRafPending = true;
  requestAnimationFrame(function() { _vsRafPending = false; _vsUpdate(); _mgScroll(); });
}

function _vsOnResize() {
  _vs.calibrated = false;
  _mgResize();
  requestAnimationFrame(_vsRefresh);
}

function _vsRefresh() {
  var w = _vsWrap.offsetWidth || window.innerWidth || 900;
  var gap = 16;
  var newPerRow = Math.max(1, Math.floor((w + gap) / (280 + gap)));
  if (newPerRow !== _vs.perRow) {
    _vsCache = {};
    _vs.start = -1; _vs.end = -1;
    _vs.perRow = newPerRow;
  }
  _vsGrid.style.gridTemplateColumns = 'repeat(' + newPerRow + ',1fr)';
  // Compute rowH from CSS: thumbs aspect-ratio 3:2 + card-info ~64px + gap
  var cardWidth = (w - (newPerRow - 1) * gap) / newPerRow;
  _vs.rowH = Math.ceil(cardWidth * (2 / 3) + 64) + gap;
  _vs.calibrated = false;  // re-calibrate after layout with new width
  _vsWrap.style.height = (Math.ceil(_visibleUsers.length / _vs.perRow) * _vs.rowH) + 'px';
  _vsUpdate();
}

function _vsUpdate() {
  if (!_vsWrap || document.getElementById('view-cards').style.display === 'none') return;
  var scrollY = window.scrollY;
  var viewH = window.innerHeight;
  var wrapTop = _vsWrap.getBoundingClientRect().top + scrollY;
  var rel = Math.max(0, scrollY - wrapTop);
  var BUFFER = 4;
  var firstRow = Math.max(0, Math.floor(rel / _vs.rowH) - BUFFER);
  var lastRow = Math.min(
    Math.ceil(_visibleUsers.length / _vs.perRow),
    Math.ceil((rel + viewH) / _vs.rowH) + BUFFER
  );
  var newStart = firstRow * _vs.perRow;
  var newEnd = Math.min(_visibleUsers.length, lastRow * _vs.perRow);
  if (newStart === _vs.start && newEnd === _vs.end) return;

  var prevStart = _vs.start, prevEnd = _vs.end;
  _vs.start = newStart; _vs.end = newEnd;
  _vsGrid.style.top = (firstRow * _vs.rowH) + 'px';

  var isFirst = prevStart < 0;
  var overlap = isFirst ? 0 : Math.max(0, Math.min(prevEnd, newEnd) - Math.max(prevStart, newStart));
  var prevSize = Math.max(1, prevEnd - prevStart);
  if (isFirst || overlap < prevSize * 0.4) {
    _vsGrid.innerHTML = '';
    for (var i = newStart; i < newEnd; i++) {
      if (!_vsCache[i]) _vsCache[i] = _vsCard(i);
      _vsGrid.appendChild(_vsCache[i]);
    }
  } else {
    var anchor = _vsGrid.firstChild || null;
    for (var i = Math.min(prevStart, newEnd) - 1; i >= newStart; i--) {
      if (!_vsCache[i]) _vsCache[i] = _vsCard(i);
      _vsGrid.insertBefore(_vsCache[i], anchor);
      anchor = _vsCache[i];
    }
    for (var i = Math.max(prevEnd, newStart); i < newEnd; i++) {
      if (!_vsCache[i]) _vsCache[i] = _vsCard(i);
      _vsGrid.appendChild(_vsCache[i]);
    }
    for (var i = prevStart; i < Math.min(newStart, prevEnd); i++) {
      if (_vsCache[i] && _vsCache[i].parentNode) _vsGrid.removeChild(_vsCache[i]);
    }
    for (var i = Math.max(newEnd, prevStart); i < prevEnd; i++) {
      if (_vsCache[i] && _vsCache[i].parentNode) _vsGrid.removeChild(_vsCache[i]);
    }
  }

  // Calibrate actual row height once; only update wrap height (no re-render)
  if (!_vs.calibrated && _vsGrid.children.length > 0) {
    var h = _vsGrid.children[0].getBoundingClientRect().height;
    if (h > 10) {
      _vs.calibrated = true;
      _vs.rowH = Math.ceil(h) + 16;
      _vsWrap.style.height = (Math.ceil(_visibleUsers.length / _vs.perRow) * _vs.rowH) + 'px';
      // No re-render: currently visible cards are already correct in DOM
    }
  }
}

function _vsCard(idx) {
  var u = _visibleUsers[idx];
  var card = document.createElement('div');
  card.className = 'card' + (_userSelMode && _userSelSet.has(u.uid) ? ' card-selected' : '');
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  var chk = document.createElement('span');
  chk.className = 'card-sel-check';
  if (_userSelSet.has(u.uid)) chk.textContent = '✓';
  card.appendChild(chk);
  card.onclick = (function(i, us, c, ck) {
    return function() {
      if (_userSelMode) {
        if (_userSelSet.has(us.uid)) {
          _userSelSet.delete(us.uid);
          c.classList.remove('card-selected');
          ck.textContent = '';
        } else {
          _userSelSet.add(us.uid);
          c.classList.add('card-selected');
          ck.textContent = '✓';
        }
        _updateUserSelBar();
      } else {
        showUser(i);
      }
    };
  })(idx, u, card, chk);
  card.onkeydown = (function(i) { return function(e) { if (e.key==='Enter'||e.key===' ') showUser(i); }; })(idx);

  var thumbs = document.createElement('div');
  thumbs.className = 'card-thumbs';
  thumbs._vsUser = u;
  if (!thumbs._vsLoaded) _vsThumbObs.observe(thumbs);

  var infoText = document.createElement('div');
  infoText.className = 'card-info-text';
  infoText.innerHTML = '<span class="card-name">' + _hesc(u.display) + '</span>'
    + (u.screen ? '<span class="card-handle">@' + _hesc(u.screen) + '</span>' : '');
  var badge = document.createElement('span');
  badge.className = 'card-count';
  badge.textContent = _countFiles(u) + ' 张';
  var info = document.createElement('div');
  info.className = 'card-info';
  info.appendChild(infoText); info.appendChild(badge);

  card.appendChild(thumbs); card.appendChild(info);
  card.oncontextmenu = (function(u) {
    return function(e) {
      _showCtxMenu(e, [{label:'删除此用户（含全部媒体）', danger:true, action:function(){_deleteUser(u);}}]);
    };
  })(u);
  return card;
}

function _hesc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function onSearch(q) {
  _visibleUsers = _buildVisibleUsers(q.trim());
  _vsCache = {};
  _vs.start = -1; _vs.end = -1;
  _vsRefresh();
  document.getElementById('topbar-meta').textContent =
    _visibleUsers.length + ' 位用户 · ' +
    _visibleUsers.reduce(function(s,u){return s+_countFiles(u);},0) + ' 张媒体';
}

function setFilter(f) {
  _mediaFilter = f;
  document.querySelectorAll('.ft').forEach(function(b) { b.classList.toggle('active', b.dataset.f === f); });
  _renderDetailGrid();
}

/* ─── Media grid virtual scroll ─── */
var _mgVS = { items: [], cols: 1, rowH: 0, rows: 0, start: -1, end: -1, cache: new Map() };

function _mgMeasure(grid) {
  var W = grid.clientWidth || grid.offsetWidth;
  var gap = 3, minW = 200;
  var cols = Math.max(1, Math.floor((W + gap) / (minW + gap)));
  var itemW = (W - gap * (cols - 1)) / cols;
  _mgVS.cols = cols;
  _mgVS.rowH = itemW + gap;
  _mgVS.rows = Math.ceil(_mgVS.items.length / cols);
  grid.style.gridTemplateColumns = 'repeat(' + cols + ',1fr)';
}

function _mgCreateItem(u, item, globalIdx) {
  var ou = item._u || u;
  var div = document.createElement('div');
  div.className = 'media-item' + (_selMode && _selSet.has(item.f) ? ' sel-active' : '');
  var path = _mpath(ou, item.f);
  if (item.t === 'video' && item.ht && _THUMB_BASE) {
    var img = document.createElement('img');
    img.src = _tpath(ou, item.f); img.alt = item.f; img.loading = 'lazy';
    div.appendChild(img);
    var ov = document.createElement('div'); ov.className = 'play-ov'; div.appendChild(ov);
  } else if (item.t === 'video') {
    var v = document.createElement('video');
    v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); v.setAttribute('preload', 'none');
    v.src = path;
    div.appendChild(v);
    var ov2 = document.createElement('div'); ov2.className = 'play-ov'; div.appendChild(ov2);
  } else {
    var img2 = document.createElement('img');
    img2.src = (_THUMB_BASE && item.ht) ? _tpath(ou, item.f) : path;
    img2.alt = item.f; img2.loading = 'lazy';
    div.appendChild(img2);
  }
  if (item.ts) {
    var dateEl = document.createElement('span');
    dateEl.className = 'media-item-date';
    dateEl.textContent = _fmtDate(item.ts);
    div.appendChild(dateEl);
  }
  var heart = document.createElement('span');
  heart.className = 'fav-heart' + (_isFav(ou.uid, item.f) ? ' on' : '');
  heart.textContent = '♥';
  heart.title = '收藏';
  heart.onclick = (function(o, it, h) {
    return function(e) { e.stopPropagation(); _toggleFav(o, it, h); };
  })(ou, item, heart);
  div.appendChild(heart);
  var chk = document.createElement('span');
  chk.className = 'sel-check';
  if (_selSet.has(item.f)) chk.textContent = '✓';
  div.appendChild(chk);
  div.onclick = (function(it, idx, d, ck) {
    return function() {
      if (_selMode) {
        if (_selSet.has(it.f)) { _selSet.delete(it.f); d.classList.remove('sel-active'); ck.textContent = ''; }
        else { _selSet.add(it.f); d.classList.add('sel-active'); ck.textContent = '✓'; }
        _updateSelBar();
      } else {
        lbOpen(idx);
      }
    };
  })(item, globalIdx, div, chk);
  div.oncontextmenu = (function(it, o, h) {
    return function(e) {
      if (_favView) {
        _showCtxMenu(e, [{label:'取消收藏', action:function(){ _toggleFav(o, it, h); }}]);
      } else {
        _showCtxMenu(e, [
          {label:(_isFav(o.uid, it.f) ? '取消收藏' : '收藏'), action:function(){ _toggleFav(o, it, h); }},
          {label:'删除此媒体', danger:true, action:function(){ _deleteMedia(o, it); }}
        ]);
      }
    };
  })(item, ou, heart);
  return div;
}

function _mgApplyRange(newStart, newEnd) {
  var mg = _mgVS;
  var grid = document.getElementById('media-grid');
  var u = currentUser;
  if ((!u && !_favView) || !grid) return;
  var firstIdx = newStart * mg.cols;
  var lastIdx = Math.min(mg.items.length - 1, (newEnd + 1) * mg.cols - 1);
  var prevFirst = mg.start < 0 ? firstIdx : mg.start * mg.cols;
  var prevLast = mg.end < 0 ? -1 : Math.min(mg.items.length - 1, (mg.end + 1) * mg.cols - 1);
  // Remove top items scrolled out
  for (var ri = prevFirst; ri < firstIdx; ri++) {
    var el = mg.cache.get(ri);
    if (el && el.parentNode) el.parentNode.removeChild(el);
    mg.cache.delete(ri);
  }
  // Remove bottom items scrolled out
  for (var ri2 = lastIdx + 1; ri2 <= prevLast; ri2++) {
    var el2 = mg.cache.get(ri2);
    if (el2 && el2.parentNode) el2.parentNode.removeChild(el2);
    mg.cache.delete(ri2);
  }
  // Prepend new top items
  if (mg.start >= 0 && firstIdx < prevFirst) {
    var refNode = grid.firstChild;
    for (var ni = firstIdx; ni < prevFirst && ni <= lastIdx; ni++) {
      if (!mg.cache.has(ni)) {
        var nd = _mgCreateItem(u, mg.items[ni], ni);
        mg.cache.set(ni, nd);
        grid.insertBefore(nd, refNode);
      }
    }
  }
  // Append new bottom items (also handles initial full render when prevLast=-1)
  var appendStart = Math.max(firstIdx, prevLast + 1);
  for (var ai = appendStart; ai <= lastIdx; ai++) {
    if (!mg.cache.has(ai)) {
      var nd2 = _mgCreateItem(u, mg.items[ai], ai);
      mg.cache.set(ai, nd2);
      grid.appendChild(nd2);
    }
  }
  grid.style.paddingTop = (newStart * mg.rowH) + 'px';
  var botRows = Math.max(0, mg.rows - newEnd - 1);
  grid.style.paddingBottom = (botRows * mg.rowH) + 'px';
  mg.start = newStart;
  mg.end = newEnd;
}

function _mgScroll() {
  if (document.getElementById('view-detail').style.display === 'none') return;
  var mg = _mgVS;
  if (mg.rowH === 0 || mg.cols === 0 || mg.rows === 0) return;
  var grid = document.getElementById('media-grid');
  if (!grid) return;
  var scrollY = window.scrollY;
  var viewH = window.innerHeight;
  var gridTop = grid.getBoundingClientRect().top + scrollY;
  var relScroll = Math.max(0, scrollY - gridTop);
  var BUFFER = 5;
  var newStart = Math.max(0, Math.floor(relScroll / mg.rowH) - BUFFER);
  var newEnd = Math.min(mg.rows - 1, Math.ceil((relScroll + viewH) / mg.rowH) + BUFFER);
  if (newStart === mg.start && newEnd === mg.end) return;
  _mgApplyRange(newStart, newEnd);
}

function _mgInit(files) {
  _mgVS.items = files;
  _mgVS.start = -1;
  _mgVS.end = -1;
  _mgVS.cache = new Map();
  _mgVS.rowH = 0;
  var grid = document.getElementById('media-grid');
  if (!grid) return;
  grid.style.paddingTop = '';
  grid.style.paddingBottom = '';
  grid.innerHTML = '';
  grid.classList.toggle('sel-mode', _selMode);
  if (files.length === 0) { _mgVS.rows = 0; _mgVS.cols = 1; return; }
  _mgMeasure(grid);
  _mgScroll();
}

function _mgResize() {
  if ((!currentUser && !_favView) || document.getElementById('view-detail').style.display === 'none') return;
  var grid = document.getElementById('media-grid');
  if (!grid || _mgVS.rowH === 0) return;
  var oldCols = _mgVS.cols;
  _mgMeasure(grid);
  if (_mgVS.cols !== oldCols) {
    // Column count changed — full reset
    _mgVS.cache = new Map();
    _mgVS.start = -1; _mgVS.end = -1;
    grid.style.paddingTop = '';
    grid.style.paddingBottom = '';
    grid.innerHTML = '';
    _mgScroll();
  }
}

function _renderDetailGrid() {
  var src = _favView ? _favItems : (currentUser ? currentUser.files : null);
  if (!src) return;
  var files = _applySortFilter(src);
  var mediaGrid = document.getElementById('media-grid');
  var groupsEl = document.getElementById('fav-groups');
  if (_favView && _favLayout === 'grouped') {
    if (mediaGrid) {
      mediaGrid.style.display = 'none';
      mediaGrid.style.paddingTop = ''; mediaGrid.style.paddingBottom = '';
      mediaGrid.innerHTML = '';
    }
    _mgVS.items = []; _mgVS.rows = 0; _mgVS.start = -1; _mgVS.end = -1;
    _mgVS.rowH = 0; _mgVS.cache = new Map();
    if (groupsEl) groupsEl.style.display = '';
    _renderFavGrouped(files);
  } else {
    if (groupsEl) { groupsEl.style.display = 'none'; groupsEl.innerHTML = ''; }
    if (mediaGrid) mediaGrid.style.display = '';
    lbFiles = files;
    _mgInit(files);
  }
  var suffix = _mediaFilter !== 'all' ? '（已筛选）' : '';
  document.getElementById('topbar-meta').textContent = files.length + ' 张媒体' + suffix;
}

document.addEventListener('DOMContentLoaded', function() {
  function _init() {
    _visibleUsers = _buildVisibleUsers('');
    _updateTopbarMeta();
    _vsInit();
    // Hide "最近" sort button if no user has latest data
    if (!USERS.some(function(u) { return u.latest; })) {
      var btn = document.getElementById('ust-recent');
      if (btn) btn.style.display = 'none';
    }
    document.getElementById('ust-wrap').style.display = 'flex';
    _updateFavBadge();
    _dlInit();
    var hash = location.hash;
    var uid = hash.startsWith('#user-') ? decodeURIComponent(hash.slice(6)) : '';
    if (uid) {
      var idx = _visibleUsers.findIndex(function(u) { return u.uid === uid; });
      if (idx >= 0) {
        history.replaceState({view:'user',uid:uid}, '', location.pathname + location.search + hash);
        showUser(idx, true);
        return;
      }
    }
    if (hash === '#favorites') {
      history.replaceState({view:'fav'}, '', location.pathname + location.search + hash);
      showFavorites(true);
      return;
    }
    history.replaceState({view:'cards'}, '', location.pathname + location.search);
  }
  if (_API_MODE) {
    _showPageLoading('正在加载用户列表…');
    fetch('/api/users')
      .then(function(r) { return r.json(); })
      .then(function(data) { USERS = data; _init(); _hidePageLoading(); })
      .catch(function() {
        _hidePageLoading();
        document.getElementById('vs-host').innerHTML =
          '<div style="padding:40px;text-align:center;color:#f4212e;font-size:15px">加载用户列表失败，请刷新页面</div>';
      });
  } else {
    _init();
    _hidePageLoading();
  }
});

window.addEventListener('popstate', function(e) {
  var state = e.state || {view:'cards'};
  if (state.view === 'user') {
    _visibleUsers = _buildVisibleUsers('');
    var idx = _visibleUsers.findIndex(function(u) { return u.uid === state.uid; });
    if (idx >= 0) showUser(idx, true); else showCards(true);
  } else if (state.view === 'fav') {
    showFavorites(true);
  } else {
    showCards(true);
  }
});

/* ── Download panel (API mode only) ── */
var _dlCmd = 'user';
var _dlEs = null;

function _dlInit() {
  if (!_API_MODE) return;
  document.getElementById('dl-btn').style.display = '';
  _dlRenderForm();
}

function toggleDlPanel() {
  var panel = document.getElementById('dl-panel');
  var overlay = document.getElementById('dl-overlay');
  var open = panel.classList.toggle('open');
  overlay.classList.toggle('open', open);
  document.body.style.overflow = open ? 'hidden' : '';
}

function dlSelectCmd(cmd) {
  _dlCmd = cmd;
  document.querySelectorAll('.dl-tab').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.cmd === cmd);
  });
  _dlRenderForm();
}

function _dlRenderForm() {
  var el = document.getElementById('dl-form');
  if (_dlCmd === 'user') {
    el.innerHTML =
      '<div class="dl-field"><label>用户名</label>' +
      '<input type="text" id="dl-username" placeholder="@handle"></div>' +
      '<div class="dl-field"><label>限制数量 (0=全部)</label>' +
      '<input type="number" id="dl-limit" value="0" min="0"></div>' +
      '<label class="dl-check-row"><input type="checkbox" id="dl-full"> 完整重新扫描 (--full)</label>' +
      '<div class="dl-field"><label>媒体类型</label>' +
      '<div class="dl-radio-row">' +
      '<label><input type="radio" name="dl-mt" value="all" checked> 全部</label>' +
      '<label><input type="radio" name="dl-mt" value="image"> 仅图片</label>' +
      '<label><input type="radio" name="dl-mt" value="video"> 仅视频</label>' +
      '</div></div>';
  } else if (_dlCmd === 'tweet') {
    el.innerHTML =
      '<div class="dl-field"><label>推文ID或URL（每行一个）</label>' +
      '<textarea id="dl-ids" placeholder="1234567890&#10;https://x.com/user/status/..."></textarea></div>' +
      '<div class="dl-field"><label>媒体类型</label>' +
      '<div class="dl-radio-row">' +
      '<label><input type="radio" name="dl-mt" value="all" checked> 全部</label>' +
      '<label><input type="radio" name="dl-mt" value="image"> 仅图片</label>' +
      '<label><input type="radio" name="dl-mt" value="video"> 仅视频</label>' +
      '</div></div>';
  } else if (_dlCmd === 'likes') {
    el.innerHTML =
      '<div class="dl-field"><label>用户名（留空=从配置读取）</label>' +
      '<input type="text" id="dl-me" placeholder="@handle (可选)"></div>' +
      '<div class="dl-field"><label>限制数量 (0=全部)</label>' +
      '<input type="number" id="dl-limit" value="0" min="0"></div>' +
      '<label class="dl-check-row"><input type="checkbox" id="dl-full"> 完整重新扫描 (--full)</label>' +
      '<div class="dl-field"><label>媒体类型</label>' +
      '<div class="dl-radio-row">' +
      '<label><input type="radio" name="dl-mt" value="all" checked> 全部</label>' +
      '<label><input type="radio" name="dl-mt" value="image"> 仅图片</label>' +
      '<label><input type="radio" name="dl-mt" value="video"> 仅视频</label>' +
      '</div></div>';
  } else if (_dlCmd === 'merge-db') {
    el.innerHTML =
      '<div class="dl-field"><label>源DB文件路径</label>' +
      '<input type="text" id="dl-src" placeholder="/path/to/source.db"></div>';
  }
}

function _dlGetArgs() {
  var args = {};
  var mt = document.querySelector('input[name="dl-mt"]:checked');
  if (mt) args.media_type = mt.value === 'all' ? '' : mt.value;
  if (_dlCmd === 'user') {
    args.username = (document.getElementById('dl-username') || {}).value || '';
    args.limit = parseInt((document.getElementById('dl-limit') || {}).value || '0', 10) || 0;
    args.full = !!(document.getElementById('dl-full') || {}).checked;
  } else if (_dlCmd === 'tweet') {
    args.ids = (document.getElementById('dl-ids') || {}).value || '';
  } else if (_dlCmd === 'likes') {
    args.me = (document.getElementById('dl-me') || {}).value || '';
    args.limit = parseInt((document.getElementById('dl-limit') || {}).value || '0', 10) || 0;
    args.full = !!(document.getElementById('dl-full') || {}).checked;
  } else if (_dlCmd === 'merge-db') {
    args.src = (document.getElementById('dl-src') || {}).value || '';
  }
  return args;
}

function dlStart() {
  var log = document.getElementById('dl-log');
  var btn = document.getElementById('dl-start-btn');
  var status = document.getElementById('dl-status');
  log.innerHTML = '';
  btn.disabled = true;
  status.textContent = '⏳ 运行中…';
  _dlSetStatus(true);

  fetch('/api/task/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cmd: _dlCmd, args: _dlGetArgs()}),
  }).then(function(r) { return r.json(); }).then(function(data) {
    if (data.error) {
      _dlAppendLog('❌ ' + data.error, 'dl-err');
      _dlSetStatus(false, null);
      return;
    }
    _dlConnectStream();
  }).catch(function(err) {
    _dlAppendLog('❌ 网络错误: ' + err, 'dl-err');
    _dlSetStatus(false, null);
  });
}

function _dlConnectStream() {
  if (_dlEs) { _dlEs.close(); _dlEs = null; }
  var es = new EventSource('/api/task/stream');
  _dlEs = es;
  es.onmessage = function(e) {
    _dlAppendLog(e.data, '');
  };
  es.addEventListener('done', function(e) {
    var payload = JSON.parse(e.data || '{}');
    var code = payload.exit;
    if (code === 0) {
      _dlAppendLog('✅ 完成 (exit 0)', 'dl-ok');
    } else {
      _dlAppendLog('❌ 退出码: ' + code, 'dl-err');
    }
    _dlSetStatus(false, code);
    es.close();
    _dlEs = null;
  });
  es.addEventListener('ping', function() {});
  es.onerror = function() {
    if (es.readyState === EventSource.CLOSED) {
      _dlSetStatus(false, null);
      _dlEs = null;
    }
  };
}

function _dlAppendLog(text, cls) {
  if (!text && text !== 0) return;
  var log = document.getElementById('dl-log');
  var line = document.createElement('div');
  if (cls) line.className = cls;
  line.textContent = text;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function _dlSetStatus(running, code) {
  var btn = document.getElementById('dl-start-btn');
  var status = document.getElementById('dl-status');
  var topbarRefresh = document.getElementById('dl-gallery-refresh-btn');
  var panelRefresh = document.getElementById('dl-panel-refresh-btn');
  btn.disabled = running;
  if (running) {
    status.textContent = '⏳ 运行中…';
    if (topbarRefresh) topbarRefresh.style.display = 'none';
    if (panelRefresh) panelRefresh.style.display = 'none';
  } else if (code === null || code === undefined) {
    status.textContent = '空闲';
  } else if (code === 0) {
    status.textContent = '✅ 完成';
    if (topbarRefresh) topbarRefresh.style.display = '';
    if (panelRefresh) panelRefresh.style.display = '';
  } else {
    status.textContent = '❌ 失败 (' + code + ')';
  }
}

function dlRefreshGallery() {
  location.reload();
}