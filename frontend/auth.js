// ── Auth Configuration ───────────────────────────────────────────────────────

const POCKETBASE_URL = (() => {
    const hostname = window.location.hostname;
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return 'https://pocketbase-production-4854.up.railway.app';
    }
    return 'https://pocketbase-production-4854.up.railway.app';
})();

// ── Token Storage ────────────────────────────────────────────────────────────

const Auth = {

    getToken() {
        return localStorage.getItem('examcrop_token');
    },

    getUser() {
        const raw = localStorage.getItem('examcrop_user');
        try { return raw ? JSON.parse(raw) : null; } catch { return null; }
    },

    isLoggedIn() {
        return !!this.getToken();
    },

    _save(token, user) {
        localStorage.setItem('examcrop_token', token);
        localStorage.setItem('examcrop_user', JSON.stringify(user));
    },

    _clear() {
        localStorage.removeItem('examcrop_token');
        localStorage.removeItem('examcrop_user');
    },

    // ── API calls ─────────────────────────────────────────────────────────────

    async signup(email, password, name = '') {
        const res = await fetch(`${POCKETBASE_URL}/api/collections/users/records`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email,
                password,
                passwordConfirm: password,
                name: name || email.split('@')[0],
            }),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(_pbError(data));

        // Auto-login after signup
        return this.login(email, password);
    },

    async login(email, password) {
        const res = await fetch(`${POCKETBASE_URL}/api/collections/users/auth-with-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ identity: email, password }),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(_pbError(data));

        this._save(data.token, data.record);
        _onAuthChange(data.record);
        return data.record;
    },

    logout() {
        this._clear();
        _onAuthChange(null);
    },

    // Verify the stored token is still valid
    async refresh() {
        const token = this.getToken();
        if (!token) return null;

        try {
            const res = await fetch(`${POCKETBASE_URL}/api/collections/users/auth-refresh`, {
                method: 'POST',
                headers: { 'Authorization': token },
            });

            if (!res.ok) {
                this._clear();
                _onAuthChange(null);
                return null;
            }

            const data = await res.json();
            this._save(data.token, data.record);
            _onAuthChange(data.record);
            return data.record;
        } catch {
            return null;
        }
    },
};

// ── Error Helper ─────────────────────────────────────────────────────────────

function _pbError(data) {
    // PocketBase returns errors in data.message or nested in data.data
    if (data.message) {
        if (data.message.toLowerCase().includes('failed to authenticate')) {
            return 'Incorrect email or password.';
        }
        if (data.message.toLowerCase().includes('already exists')) {
            return 'An account with this email already exists.';
        }
        return data.message;
    }
    return 'Something went wrong. Please try again.';
}

// ── UI State ─────────────────────────────────────────────────────────────────

function _onAuthChange(user) {
    _updateDesktopNav(user);
    _updateMobileNav(user);

    // ── Page-specific callback (e.g. bank.html) ──
    if (typeof window._bankAuthCallback === 'function') {
        window._bankAuthCallback(user);
    }
}

function _updateDesktopNav(user) {
    const navLinks = document.querySelector('.nav-links');
    if (!navLinks) return;

    if (user) {
        const name = user.name || user.email?.split('@')[0] || 'Account';
        navLinks.innerHTML = `
            <a href="/bank"       class="nav-tool-link" id="navBank">My Bank</a>
            <a href="/worksheets" class="nav-tool-link" id="navWorksheets">My Worksheets</a>
            <a href="/settings"   class="nav-tool-link" id="navSettings">Settings</a>
            <a href="/bank" class="nav-auth-btn" id="authNavBtn">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.7"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                ${_escHtml(name)}
            </a>
            <div class="nav-user-menu" id="userNavMenu">
                <a href="#" class="nav-logout-link" id="logoutBtn">Log out</a>
            </div>
        `;
        // Re-bind logout
        document.getElementById('logoutBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            Auth.logout();
            window.location.href = '/';
        });
        // Highlight active page
        const path = window.location.pathname;
        if (path.startsWith('/bank'))        document.getElementById('navBank')?.classList.add('active');
        if (path.startsWith('/worksheets'))  document.getElementById('navWorksheets')?.classList.add('active');
        if (path.startsWith('/settings'))    document.getElementById('navSettings')?.classList.add('active');
    } else {
        navLinks.innerHTML = `
            <div class="nav-dropdown" id="curriculumDropdown">
                <button class="nav-dropdown-trigger" id="curriculumTrigger">
                    Curriculums
                    <svg class="dropdown-chevron" viewBox="0 0 24 24" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="6 9 12 15 18 9"/>
                    </svg>
                </button>
                <div class="dropdown-menu">
                    <a href="/igcse"     class="dropdown-item">IGCSE</a>
                    <a href="/sat"       class="dropdown-item">SAT</a>
                    <a href="/thanaweya" class="dropdown-item">الثانوية العامة</a>
                </div>
            </div>
            <a href="/pricing">Pricing</a>
            <a href="#" class="nav-auth-btn" id="authNavBtn">Log In</a>
            <div class="nav-user-menu" id="userNavMenu" style="display:none">
                <a href="#" class="nav-logout-link" id="logoutBtn">Log out</a>
            </div>
        `;
        // Re-bind curriculum dropdown
        const trigger  = document.getElementById('curriculumTrigger');
        const dropdown = document.getElementById('curriculumDropdown');
        if (trigger && dropdown) {
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                dropdown.classList.toggle('open');
            });
        }
        // Re-bind login button
        document.getElementById('authNavBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            showAuthModal('login');
        });
        // Re-bind logout
        document.getElementById('logoutBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            Auth.logout();
            window.location.href = '/';
        });
    }
}

function _updateMobileNav(user) {
    const mobileMenu = document.getElementById('mobileMenu');
    if (!mobileMenu) return;

    if (user) {
        const name = user.name || user.email?.split('@')[0] || 'Account';
        mobileMenu.innerHTML = `
            <a href="/bank"       class="mobile-nav-link">My Bank</a>
            <a href="/worksheets" class="mobile-nav-link">My Worksheets</a>
            <a href="/settings"   class="mobile-nav-link">Settings</a>
            <a href="#" class="mobile-logout-link" id="mobileLogoutBtn"
               onclick="event.preventDefault(); Auth.logout(); window.location.href='/'">Log out</a>
        `;
    } else {
        mobileMenu.innerHTML = `
            <span class="mobile-section-label">Curriculums</span>
            <a href="/igcse"     class="mobile-nav-link mobile-sub-link">IGCSE</a>
            <a href="/sat"       class="mobile-nav-link mobile-sub-link">SAT</a>
            <a href="/thanaweya" class="mobile-nav-link mobile-sub-link">الثانوية العامة</a>
            <a href="/pricing"   class="mobile-nav-link">Pricing</a>
            <a href="#" class="mobile-nav-link mobile-auth-link" id="mobileAuthBtn">Log In</a>
        `;
        document.getElementById('mobileAuthBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('hamburger')?.classList.remove('open');
            document.getElementById('mobileMenu')?.classList.remove('open');
            showAuthModal('login');
        });
    }
}

function _escHtml(str) {
    return str.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ── Auth Modal ───────────────────────────────────────────────────────────────

let _authMode = 'login'; // 'login' | 'signup'

function showAuthModal(mode = 'login') {
    _authMode = mode;
    const overlay = document.getElementById('authModalOverlay');
    if (!overlay) return;

    _renderAuthModal(mode);
    overlay.classList.add('show');
    setTimeout(() => document.getElementById('authEmailInput')?.focus(), 100);
}

function hideAuthModal() {
    document.getElementById('authModalOverlay')?.classList.remove('show');
    _clearAuthError();
}

function _renderAuthModal(mode) {
    const title    = document.getElementById('authModalTitle');
    const subtitle = document.getElementById('authModalSubtitle');
    const nameRow  = document.getElementById('authNameRow');
    const submitBtn = document.getElementById('authSubmitBtn');
    const switchLink = document.getElementById('authSwitchLink');

    if (mode === 'login') {
        if (title)    title.textContent    = 'Welcome back';
        if (subtitle) subtitle.textContent = 'Log in to your question bank';
        if (nameRow)  nameRow.style.display = 'none';
        if (submitBtn) submitBtn.textContent = 'Log In';
        if (switchLink) switchLink.innerHTML =
            `Don't have an account? <a href="#" id="authSwitchBtn">Sign up free</a>`;
    } else {
        if (title)    title.textContent    = 'Create your account';
        if (subtitle) subtitle.textContent = 'Free during beta — no card needed';
        if (nameRow)  nameRow.style.display = '';
        if (submitBtn) submitBtn.textContent = 'Create Account';
        if (switchLink) switchLink.innerHTML =
            `Already have an account? <a href="#" id="authSwitchBtn">Log in</a>`;
    }

    // Re-bind switch link
    setTimeout(() => {
        document.getElementById('authSwitchBtn')?.addEventListener('click', (e) => {
            e.preventDefault();
            _authMode = _authMode === 'login' ? 'signup' : 'login';
            _renderAuthModal(_authMode);
            _clearAuthError();
        });
    }, 0);
}

function _clearAuthError() {
    const err = document.getElementById('authErrorMsg');
    if (err) { err.textContent = ''; err.style.display = 'none'; }
}

function _showAuthError(msg) {
    const err = document.getElementById('authErrorMsg');
    if (err) { err.textContent = msg; err.style.display = ''; }
}

function _setAuthLoading(loading) {
    const btn = document.getElementById('authSubmitBtn');
    if (!btn) return;
    btn.disabled    = loading;
    btn.textContent = loading
        ? (_authMode === 'login' ? 'Logging in...' : 'Creating account...')
        : (_authMode === 'login' ? 'Log In' : 'Create Account');
}

// ── Modal Form Submit ─────────────────────────────────────────────────────────

async function _handleAuthSubmit(e) {
    e.preventDefault();
    _clearAuthError();

    const email    = document.getElementById('authEmailInput')?.value.trim();
    const password = document.getElementById('authPasswordInput')?.value;
    const name     = document.getElementById('authNameInput')?.value.trim();

    if (!email || !password) return;
    if (password.length < 8) {
        _showAuthError('Password must be at least 8 characters.');
        return;
    }

    _setAuthLoading(true);

    try {
        if (_authMode === 'signup') {
            await Auth.signup(email, password, name);
        } else {
            await Auth.login(email, password);
        }
        hideAuthModal();
    } catch (err) {
        _showAuthError(err.message);
    } finally {
        _setAuthLoading(false);
    }
}

// ── Init ─────────────────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', () => {
    // Wire up modal form
    document.getElementById('authForm')?.addEventListener('submit', _handleAuthSubmit);

    // Close on overlay click
    document.getElementById('authModalOverlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'authModalOverlay') hideAuthModal();
    });

    document.getElementById('authModalClose')?.addEventListener('click', hideAuthModal);

    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') hideAuthModal();
    });

    // Wire up logout
    document.getElementById('logoutBtn')?.addEventListener('click', (e) => {
        e.preventDefault();
        Auth.logout();
        window.location.href = '/';
    });

    // On load — check if token is still valid, update UI
    const user = Auth.getUser();
    if (user) {
        _onAuthChange(user);          // fast optimistic UI
        Auth.refresh();               // async validate in background
    } else {
        _onAuthChange(null);
    }
});

// Expose globally so script.js can check auth state
window.Auth       = Auth;
window.showAuthModal = showAuthModal;
window.hideAuthModal = hideAuthModal;