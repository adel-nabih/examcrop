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
    const authBtn  = document.getElementById('authNavBtn');
    const userMenu = document.getElementById('userNavMenu');

    if (!authBtn) return;

    if (user) {
        authBtn.textContent   = 'My Bank';
        authBtn.href          = '/bank';
        authBtn.onclick       = null;
        authBtn.style.display = '';
        if (userMenu) userMenu.style.display = '';
    } else {
        authBtn.textContent = 'Log In';
        authBtn.href        = '#';
        authBtn.onclick     = (e) => { e.preventDefault(); showAuthModal('login'); };
        if (userMenu) userMenu.style.display = 'none';
    }

    // ── Page-specific callback (e.g. bank.html) ──
    if (typeof window._bankAuthCallback === 'function') {
        window._bankAuthCallback(user);
    }

    // ── Mobile menu auth link ──
    const mobileAuthBtn    = document.getElementById('mobileAuthBtn');
    const mobileLogoutLink = document.getElementById('mobileLogoutBtn');

    if (mobileAuthBtn) {
        if (user) {
            mobileAuthBtn.textContent = 'My Bank';
            mobileAuthBtn.href        = '/bank';
            mobileAuthBtn.onclick     = null;
            if (mobileLogoutLink) mobileLogoutLink.style.display = '';
        } else {
            mobileAuthBtn.textContent = 'Log In';
            mobileAuthBtn.href        = '#';
            mobileAuthBtn.onclick     = (e) => {
                e.preventDefault();
                document.getElementById('hamburger')?.classList.remove('open');
                document.getElementById('mobileMenu')?.classList.remove('open');
                showAuthModal('login');
            };
            if (mobileLogoutLink) mobileLogoutLink.style.display = 'none';
        }
    }
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