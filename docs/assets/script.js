/* Claude Code Guide — Interactive Features */

(function () {
    "use strict";

    // --- Theme Toggle ---
    function initTheme() {
        var saved = localStorage.getItem("cc-guide-theme");
        var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        var theme = saved || (prefersDark ? "dark" : "light");
        document.documentElement.setAttribute("data-theme", theme);
    }

    function toggleTheme() {
        var current = document.documentElement.getAttribute("data-theme");
        var next = current === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("cc-guide-theme", next);
        if (typeof mermaid !== "undefined") {
            mermaid.initialize({ theme: next === "dark" ? "dark" : "default" });
        }
    }

    // --- Sidebar Navigation ---
    function initSidebar() {
        var toggle = document.getElementById("menuToggle");
        var sidebar = document.getElementById("sidebar");
        var overlay = document.getElementById("sidebarOverlay");
        if (!toggle || !sidebar) return;

        toggle.addEventListener("click", function () {
            toggle.classList.toggle("active");
            sidebar.classList.toggle("open");
            if (overlay) overlay.classList.toggle("visible");
        });

        if (overlay) {
            overlay.addEventListener("click", function () {
                toggle.classList.remove("active");
                sidebar.classList.remove("open");
                overlay.classList.remove("visible");
            });
        }
    }

    // --- TOC Generation ---
    function initTOC() {
        var body = document.querySelector(".chapter-body");
        if (!body) return;

        var headings = body.querySelectorAll("h2, h3");
        if (headings.length < 2) return;

        var toc = document.createElement("div");
        toc.className = "toc";
        toc.innerHTML = '<div class="toc-title">📋 この章の目次</div><ul class="toc-list"></ul>';
        var list = toc.querySelector(".toc-list");

        headings.forEach(function (h, i) {
            if (!h.id) h.id = "toc-" + i;
            var li = document.createElement("li");
            li.className = h.tagName === "H3" ? "toc-h3" : "toc-h2";
            var a = document.createElement("a");
            a.href = "#" + h.id;
            a.textContent = h.textContent;
            a.addEventListener("click", function (e) {
                e.preventDefault();
                h.scrollIntoView({ behavior: "smooth", block: "start" });
            });
            li.appendChild(a);
            list.appendChild(li);
        });

        body.insertBefore(toc, body.firstChild.nextSibling);
    }

    // --- Copy Button ---
    function initCopyButtons() {
        var pres = document.querySelectorAll(".chapter-body pre");
        pres.forEach(function (pre) {
            var wrapper = document.createElement("div");
            wrapper.className = "code-block-wrapper";
            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(pre);

            var btn = document.createElement("button");
            btn.className = "copy-btn";
            btn.textContent = "コピー";
            btn.addEventListener("click", function () {
                var code = pre.querySelector("code");
                var text = code ? code.textContent : pre.textContent;
                navigator.clipboard.writeText(text).then(function () {
                    btn.textContent = "✓ コピー済み";
                    btn.classList.add("copied");
                    setTimeout(function () {
                        btn.textContent = "コピー";
                        btn.classList.remove("copied");
                    }, 2000);
                });
            });
            wrapper.appendChild(btn);
        });
    }

    // --- In-page Search ---
    function initSearch() {
        var body = document.querySelector(".chapter-body");
        if (!body) return;

        var container = document.createElement("div");
        container.className = "search-bar";
        container.innerHTML =
            '<input type="text" id="pageSearch" placeholder="ページ内検索..." />' +
            '<span class="search-count" id="searchCount"></span>' +
            '<button class="search-prev" id="searchPrev" title="前へ">▲</button>' +
            '<button class="search-next" id="searchNext" title="次へ">▼</button>' +
            '<button class="search-clear" id="searchClear" title="クリア">✕</button>';

        var nav = document.querySelector(".chapter-nav-top");
        if (nav) {
            nav.parentNode.insertBefore(container, nav);
        } else {
            body.parentNode.insertBefore(container, body);
        }

        var input = document.getElementById("pageSearch");
        var countEl = document.getElementById("searchCount");
        var prevBtn = document.getElementById("searchPrev");
        var nextBtn = document.getElementById("searchNext");
        var clearBtn = document.getElementById("searchClear");

        var marks = [];
        var currentIdx = -1;

        function clearHighlights() {
            marks.forEach(function (el) {
                var parent = el.parentNode;
                parent.replaceChild(document.createTextNode(el.textContent), el);
                parent.normalize();
            });
            marks = [];
            currentIdx = -1;
            countEl.textContent = "";
        }

        function highlight(text) {
            clearHighlights();
            if (!text) return;

            // 入力長上限（過度に長い入力による正規計算量増大を防止）
            var MAX_SEARCH_LEN = 100;
            if (text.length > MAX_SEARCH_LEN) {
                text = text.slice(0, MAX_SEARCH_LEN);
            }

            var walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null, false);
            var nodes = [];
            while (walker.nextNode()) nodes.push(walker.currentNode);

            var escaped = text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            var regex = new RegExp("(" + escaped + ")", "gi");

            nodes.forEach(function (node) {
                if (!regex.test(node.textContent)) return;
                regex.lastIndex = 0;

                var frag = document.createDocumentFragment();
                var lastIdx = 0;
                var match;
                var parent = node.parentNode;

                while ((match = regex.lastIndex !== undefined ? regex.exec(node.textContent) : null) !== null) {
                    if (match.index > lastIdx) {
                        frag.appendChild(document.createTextNode(node.textContent.slice(lastIdx, match.index)));
                    }
                    var mark = document.createElement("mark");
                    mark.className = "search-highlight";
                    mark.textContent = match[1];
                    frag.appendChild(mark);
                    marks.push(mark);
                    lastIdx = regex.lastIndex;
                }
                if (lastIdx < node.textContent.length) {
                    frag.appendChild(document.createTextNode(node.textContent.slice(lastIdx)));
                }
                parent.replaceChild(frag, node);
            });

            if (marks.length > 0) {
                countEl.textContent = "1/" + marks.length;
                currentIdx = 0;
                marks[0].classList.add("search-current");
                marks[0].scrollIntoView({ behavior: "smooth", block: "center" });
            } else {
                countEl.textContent = "0件";
            }
        }

        function goTo(dir) {
            if (marks.length === 0) return;
            marks[currentIdx].classList.remove("search-current");
            currentIdx = (currentIdx + dir + marks.length) % marks.length;
            marks[currentIdx].classList.add("search-current");
            marks[currentIdx].scrollIntoView({ behavior: "smooth", block: "center" });
            countEl.textContent = (currentIdx + 1) + "/" + marks.length;
        }

        var debounceTimer;
        input.addEventListener("input", function () {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () {
                highlight(input.value.trim());
            }, 300);
        });

        prevBtn.addEventListener("click", function () { goTo(-1); });
        nextBtn.addEventListener("click", function () { goTo(1); });
        clearBtn.addEventListener("click", function () {
            input.value = "";
            clearHighlights();
        });

        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault();
                goTo(e.shiftKey ? -1 : 1);
            }
            if (e.key === "Escape") {
                input.value = "";
                clearHighlights();
                input.blur();
            }
        });
    }

    // --- Initialize ---
    initTheme();
    initSidebar();

    var themeBtn = document.getElementById("themeToggle");
    if (themeBtn) {
        themeBtn.addEventListener("click", toggleTheme);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            initTOC();
            initCopyButtons();
            initSearch();
        });
    } else {
        initTOC();
        initCopyButtons();
        initSearch();
    }
})();
