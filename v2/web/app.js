"use strict";
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var form = $("form"), q = $("q"), go = $("go"), grid = $("grid"),
      notes = $("notes"), status = $("status"), toast = $("toast");
  var PLAT_NAME = { huya: "虎牙", douyu: "斗鱼", bili: "B站" };
  var mySeq = 0;       // 前端自己的“最新一次搜索”编号，只认最后一次
  var toastTimer = null;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove("show"); }, 1800);
  }

  // ---- 主题（变量切换 + CSS transition，无闪烁）
  $("theme").addEventListener("click", function () {
    var r = document.documentElement;
    var t = r.dataset.theme === "dark" ? "light" : "dark";
    r.dataset.theme = t;
    try { localStorage.setItem("lh-theme", t); } catch (e) {}
  });

  // ---- 头像：先直接加载，失败改文字占位
  function hashHue(s) {
    var h = 0;
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return h;
  }
  function placeholder(av, name) {
    var h = hashHue(name);
    av.style.background = "linear-gradient(135deg,hsl(" + h + ",75%,55%),hsl(" + ((h + 40) % 360) + ",80%,68%))";
    av.textContent = (name || "?").trim().charAt(0).toUpperCase();
  }
  function makeAvatar(it) {
    if (it.avatar) {
      var img = el("img", "avatar");
      img.referrerPolicy = "no-referrer";   // 多数 CDN 的防盗链看 Referer
      img.loading = "lazy";
      img.alt = "";
      img.onerror = function () {
        var d = el("div", "avatar");
        placeholder(d, it.name);
        if (img.parentNode) img.parentNode.replaceChild(d, img);
      };
      img.src = it.avatar;
      return img;
    }
    var d = el("div", "avatar");
    placeholder(d, it.name);
    return d;
  }

  // ---- 渲染
  function card(it, i) {
    var c = el("article", "card");
    c.style.animationDelay = Math.min(i, 12) * 25 + "ms";
    var head = el("div", "head");
    head.appendChild(makeAvatar(it));
    var who = el("div", "who");
    who.appendChild(el("div", "name", it.name));
    who.appendChild(el("div", "rid", "房间 " + it.rid + (it.hot ? " · 人气 " + it.hot : "")));
    head.appendChild(who);
    c.appendChild(head);
    c.appendChild(el("div", "info", it.info || it.cate || "（无简介）"));
    var foot = el("div", "foot");
    foot.appendChild(el("span", "tag", it.platform_name || PLAT_NAME[it.platform] || ""));
    foot.appendChild(el("span", "state" + (it.live ? " on" : ""), it.live ? "直播中" : "未开播"));
    var wrap = el("span", "play-wrap");
    var b = el("button", "play", "播放");
    b.disabled = true;
    b.title = "下一步实现";
    wrap.appendChild(b);
    wrap.addEventListener("click", function () { showToast("播放功能下一步实现"); });
    foot.appendChild(wrap);
    c.appendChild(foot);
    return c;
  }
  function renderEmpty(big, small) {
    grid.textContent = "";
    var e = el("div", "empty");
    e.appendChild(el("div", "big", big));
    e.appendChild(el("div", "", small));
    grid.appendChild(e);
  }
  function renderLoading() {
    grid.textContent = "";
    for (var i = 0; i < 6; i++) grid.appendChild(el("div", "skel"));
  }
  function renderNotes(errors) {
    notes.textContent = "";
    Object.keys(errors || {}).forEach(function (p) {
      var n = el("div", "note");
      n.appendChild(el("b", "", "提示"));
      n.appendChild(document.createTextNode(errors[p]));
      notes.appendChild(n);
    });
  }
  function renderResult(res) {
    renderNotes(res.errors);
    var n = res.items.length;
    if (!n) {
      var failed = Object.keys(res.errors || {}).length;
      renderEmpty(failed ? "没有拿到结果" : "没有找到相关主播",
                  failed ? "上面是各平台的原因，可以换个平台或改用房间号" : "换个关键词试试，或直接输入房间号");
      status.textContent = "";
      return;
    }
    grid.textContent = "";
    res.items.forEach(function (it, i) { grid.appendChild(card(it, i)); });
    status.textContent = "找到 " + n + " 个结果 · 用时 " + (res.ms / 1000).toFixed(1) + " 秒";
    grid.scrollTop = 0;
  }

  // ---- 搜索
  function selectedPlatforms() {
    return Array.prototype.slice.call(document.querySelectorAll("#plats input:checked"))
      .map(function (i) { return i.value; });
  }
  function setBusy(b) {
    go.disabled = b;
    go.textContent = b ? "搜索中…" : "搜索";
  }
  function doSearch() {
    var kw = q.value.trim();
    if (!kw) { showToast("请输入主播名、房间号或房间链接"); return; }
    if (!window.pywebview || !window.pywebview.api) {
      renderEmpty("未连接后端", "请通过 python v2/app_web.py 启动");
      return;
    }
    var seq = ++mySeq;
    setBusy(true);
    notes.textContent = "";
    status.textContent = "正在搜索…";
    renderLoading();
    window.pywebview.api.search(kw, selectedPlatforms()).then(function (res) {
      if (seq !== mySeq || res.stale) return;      // 已有更新的搜索，丢弃
      setBusy(false);
      if (!res.ok) { renderEmpty(res.error, ""); status.textContent = ""; return; }
      renderResult(res);
    }).catch(function (e) {
      if (seq !== mySeq) return;
      setBusy(false);
      renderEmpty("搜索出错了", String(e));
      status.textContent = "";
    });
  }
  form.addEventListener("submit", function (e) { e.preventDefault(); doSearch(); });

  renderEmpty("搜一个主播吧", "输入主播名回车，或粘贴房间号 / 房间链接");
  window.__lh = { doSearch: doSearch };   // 供自动化测试调用
})();
