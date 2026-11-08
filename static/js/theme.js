// System theme auto-detection & persistent theme toggle
(function() {
    function getQueryTheme() {
        try {
            var params = new URLSearchParams(window.location.search);
            var t = params.get('theme');
            if (t === 'light' || t === 'dark') return t;
            return null;
        } catch (e) {
            return null;
        }
    }

    function getStoredTheme() {
        try {
            return localStorage.getItem('theme');
        } catch (e) {
            return null;
        }
    }

    function getSystemTheme() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }

    function applyTheme(theme) {
        var effective = theme || getQueryTheme() || getStoredTheme() || getSystemTheme();
        if (effective === 'dark') {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
        window.__currentTheme = effective;
        try {
            window.dispatchEvent(new CustomEvent('theme-changed', { detail: { theme: effective } }));
        } catch (e) {}
    }

    window.toggleTheme = function() {
        var current = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        var next = current === 'dark' ? 'light' : 'dark';
        try {
            localStorage.setItem('theme', next);
        } catch (e) {}
        applyTheme(next);
        return next;
    };

    window.resetThemeToSystem = function() {
        try {
            localStorage.removeItem('theme');
        } catch (e) {}
        applyTheme();
    };

    // Apply immediately to prevent FOUT (flash of unstyled theme)
    applyTheme();

    // Listen for system/browser theme changes if no manual preference stored
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
            if (!getQueryTheme() && !getStoredTheme()) {
                applyTheme(e.matches ? 'dark' : 'light');
            }
        });
    }
})();
